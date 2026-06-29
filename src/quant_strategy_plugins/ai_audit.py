from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

PROVIDER_CODEX = "codex"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_AI_AUDIT_BASE_URL = DEFAULT_OPENAI_BASE_URL
DEFAULT_CODEX_MODEL = "codex-cli"
DEFAULT_AI_AUDIT_MODEL = "gpt-5.4-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_AI_AUDIT_TIMEOUT_SECONDS = 15.0
AI_AUDIT_SCHEMA_VERSION = "strategy_plugin_ai_audit.v1"
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
SANITIZE_MAX_FIELD_LENGTH = 2000

# Patterns that may appear in upstream error responses and must be scrubbed.
_API_KEY_SCRUB_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{32,}", re.IGNORECASE),
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]{32,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.=]{20,}", re.IGNORECASE),
    re.compile(r"x-api-key:\s*[^\s,;]{20,}", re.IGNORECASE),
]


@dataclass(frozen=True)
class AiAuditEndpoint:
    name: str
    api_key: str
    provider: str = PROVIDER_OPENAI
    base_url: str = DEFAULT_AI_AUDIT_BASE_URL
    model: str = DEFAULT_AI_AUDIT_MODEL
    api_version: str | None = None

    def normalized(self) -> "AiAuditEndpoint":
        name = str(self.name or "primary").strip() or "primary"
        api_key = str(self.api_key or "").strip()
        provider = str(self.provider or PROVIDER_OPENAI).strip().lower()
        if provider not in {PROVIDER_CODEX, PROVIDER_OPENAI, PROVIDER_ANTHROPIC}:
            provider = PROVIDER_OPENAI
        base_url = str(self.base_url or _provider_default_base_url(provider)).strip().rstrip("/")
        model = str(self.model or _provider_default_model(provider)).strip() or _provider_default_model(provider)
        api_version = _first_non_empty(self.api_version, DEFAULT_ANTHROPIC_VERSION if provider == PROVIDER_ANTHROPIC else None)
        return AiAuditEndpoint(
            name=name,
            api_key=api_key,
            provider=provider,
            base_url=base_url,
            model=model,
            api_version=api_version,
        )

    def report(self) -> dict[str, str]:
        endpoint = self.normalized()
        report = {
            "name": endpoint.name,
            "provider": endpoint.provider,
            "base_url": endpoint.base_url,
            "model": endpoint.model,
        }
        if endpoint.api_version:
            report["api_version"] = endpoint.api_version
        return report


CompletionClient = Callable[[AiAuditEndpoint, Sequence[Mapping[str, str]], float], str | Mapping[str, Any]]


class AiAuditError(RuntimeError):
    pass


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _env(*names: str) -> str | None:
    return _first_non_empty(*(os.getenv(name) for name in names))


def _provider_default_base_url(provider: str) -> str:
    if provider == PROVIDER_CODEX:
        return "local"
    return DEFAULT_ANTHROPIC_BASE_URL if provider == PROVIDER_ANTHROPIC else DEFAULT_OPENAI_BASE_URL


def _provider_default_model(provider: str) -> str:
    if provider == PROVIDER_CODEX:
        return DEFAULT_CODEX_MODEL
    return DEFAULT_ANTHROPIC_MODEL if provider == PROVIDER_ANTHROPIC else DEFAULT_AI_AUDIT_MODEL


def _env_bool(*names: str, default: bool = False) -> bool:
    value = _env(*names)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _sanitize_user_input(value: Any, *, max_length: int = SANITIZE_MAX_FIELD_LENGTH) -> str:
    """Strip control characters and truncate free-text fields before LLM submission."""
    text = str(value or "").strip()
    # Remove C0/C1 control chars except common whitespace (tab, newline)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    return text[:max_length]


def _scrub_api_key_from_text(text: str) -> str:
    """Replace API key-like patterns in error messages with '[REDACTED]'."""
    for pattern in _API_KEY_SCRUB_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _should_retry(status_code: int | None) -> bool:
    return status_code is not None and (status_code == 429 or status_code >= 500)


def _retry_with_backoff(
    fn: Callable[[], str],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
) -> str:
    """Call *fn* with exponential backoff on retriable HTTP errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except AiAuditError as exc:
            last_exc = exc
            cause = exc.__cause__
            status = None
            if isinstance(cause, urllib.error.HTTPError):
                status = cause.code
            if not _should_retry(status) or attempt >= max_retries:
                raise
            wait = base_seconds * (2 ** attempt)
            _logger.warning(
                "ai_audit attempt %d/%d failed with status %s; retrying in %.1fs",
                attempt + 1, max_retries + 1, status, wait,
            )
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def build_ai_audit_endpoints(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
    fallback_model: str | None = None,
    codex_enabled: bool | None = None,
    codex_model: str | None = None,
    anthropic_api_key: str | None = None,
    anthropic_base_url: str | None = None,
    anthropic_model: str | None = None,
    anthropic_version: str | None = None,
) -> tuple[AiAuditEndpoint, ...]:
    primary_key = _first_non_empty(
        api_key,
        _env("QSP_STRATEGY_PLUGIN_AI_AUDIT_API_KEY", "QSP_CRISIS_AI_AUDIT_API_KEY", "OPENAI_API_KEY"),
    )
    primary_base_url = _first_non_empty(
        base_url,
        _env(
            "QSP_STRATEGY_PLUGIN_AI_AUDIT_BASE_URL",
            "QSP_STRATEGY_PLUGIN_AI_AUDIT_OPENAI_BASE_URL",
            "QSP_CRISIS_AI_AUDIT_BASE_URL",
            "QSP_CRISIS_AI_AUDIT_OPENAI_BASE_URL",
            "OPENAI_API_BASE_URL",
            "OPENAI_BASE_URL",
        ),
        DEFAULT_OPENAI_BASE_URL,
    )
    primary_model = _first_non_empty(
        model,
        _env("QSP_STRATEGY_PLUGIN_AI_AUDIT_MODEL", "QSP_CRISIS_AI_AUDIT_MODEL", "OPENAI_MODEL"),
        DEFAULT_AI_AUDIT_MODEL,
    )

    endpoints: list[AiAuditEndpoint] = []
    resolved_codex_enabled = (
        _env_bool("QSP_STRATEGY_PLUGIN_AI_AUDIT_CODEX_ENABLED", "QSP_CRISIS_AI_AUDIT_CODEX_ENABLED", default=True)
        if codex_enabled is None
        else bool(codex_enabled)
    )
    if resolved_codex_enabled:
        endpoints.append(
            AiAuditEndpoint(
                name="codex",
                api_key="",
                provider=PROVIDER_CODEX,
                base_url="local",
                model=_first_non_empty(
                    codex_model,
                    _env("QSP_STRATEGY_PLUGIN_AI_AUDIT_CODEX_MODEL", "QSP_CRISIS_AI_AUDIT_CODEX_MODEL"),
                    DEFAULT_CODEX_MODEL,
                )
                or DEFAULT_CODEX_MODEL,
            ).normalized()
        )

    if primary_key:
        endpoints.append(
            AiAuditEndpoint(
                name="primary",
                api_key=primary_key,
                provider=PROVIDER_OPENAI,
                base_url=primary_base_url or DEFAULT_OPENAI_BASE_URL,
                model=primary_model or DEFAULT_AI_AUDIT_MODEL,
            ).normalized()
        )

    secondary_key = _first_non_empty(
        fallback_api_key,
        _env(
            "QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_API_KEY",
            "QSP_CRISIS_AI_AUDIT_FALLBACK_API_KEY",
            "OPENAI_FALLBACK_API_KEY",
        ),
    )
    secondary_base_url = _first_non_empty(
        fallback_base_url,
        _env(
            "QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_BASE_URL",
            "QSP_CRISIS_AI_AUDIT_FALLBACK_BASE_URL",
            "OPENAI_FALLBACK_BASE_URL",
        ),
        DEFAULT_OPENAI_BASE_URL,
    )
    secondary_model = _first_non_empty(
        fallback_model,
        _env(
            "QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_MODEL",
            "QSP_CRISIS_AI_AUDIT_FALLBACK_MODEL",
            "OPENAI_FALLBACK_MODEL",
        ),
        primary_model,
        DEFAULT_AI_AUDIT_MODEL,
    )
    if secondary_key:
        endpoints.append(
            AiAuditEndpoint(
                name="fallback",
                api_key=secondary_key,
                provider=PROVIDER_OPENAI,
                base_url=secondary_base_url or DEFAULT_OPENAI_BASE_URL,
                model=secondary_model or DEFAULT_AI_AUDIT_MODEL,
            ).normalized()
        )

    anthropic_key = _first_non_empty(
        anthropic_api_key,
        _env(
            "QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY",
            "QSP_CRISIS_AI_AUDIT_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )
    if anthropic_key:
        anthropic_endpoint_base_url = _first_non_empty(
            anthropic_base_url,
            _env(
                "QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_BASE_URL",
                "QSP_CRISIS_AI_AUDIT_ANTHROPIC_BASE_URL",
                "ANTHROPIC_API_BASE_URL",
            ),
            DEFAULT_ANTHROPIC_BASE_URL,
        )
        anthropic_endpoint_model = _first_non_empty(
            anthropic_model,
            _env(
                "QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_MODEL",
                "QSP_CRISIS_AI_AUDIT_ANTHROPIC_MODEL",
                "ANTHROPIC_MODEL",
            ),
            DEFAULT_ANTHROPIC_MODEL,
        )
        endpoints.append(
            AiAuditEndpoint(
                name="anthropic",
                api_key=anthropic_key,
                provider=PROVIDER_ANTHROPIC,
                base_url=anthropic_endpoint_base_url or DEFAULT_ANTHROPIC_BASE_URL,
                model=anthropic_endpoint_model or DEFAULT_ANTHROPIC_MODEL,
                api_version=_first_non_empty(
                    anthropic_version,
                    _env(
                        "QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_VERSION",
                        "QSP_CRISIS_AI_AUDIT_ANTHROPIC_VERSION",
                        "ANTHROPIC_VERSION",
                    ),
                    DEFAULT_ANTHROPIC_VERSION,
                ),
            ).normalized()
        )

    return tuple(endpoints)


def _chat_completions_url(base_url: str) -> str:
    url = str(base_url or DEFAULT_AI_AUDIT_BASE_URL).strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _openai_compatible_chat_completion(
    endpoint: AiAuditEndpoint,
    messages: Sequence[Mapping[str, str]],
    timeout_seconds: float,
) -> str:
    endpoint = endpoint.normalized()
    body = json.dumps(
        {
            "model": endpoint.model,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": 700,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _chat_completions_url(endpoint.base_url),
        data=body,
        headers={
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    def _call() -> str:
        try:
            with urllib.request.urlopen(request, timeout=float(timeout_seconds)) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            detail = _scrub_api_key_from_text(detail)
            raise AiAuditError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise AiAuditError(f"network or encoding error: {exc}") from exc

        payload = json.loads(response_body)
        choices = payload.get("choices") if isinstance(payload, Mapping) else None
        if not choices:
            raise AiAuditError("empty completion choices")
        first = choices[0]
        if not isinstance(first, Mapping):
            raise AiAuditError("invalid completion choice")
        message = first.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
        else:
            content = first.get("text")
        text = str(content or "").strip()
        if not text:
            raise AiAuditError("empty completion content")
        return text

    return _retry_with_backoff(_call)


def _anthropic_messages_url(base_url: str) -> str:
    url = str(base_url or DEFAULT_ANTHROPIC_BASE_URL).strip().rstrip("/")
    if url.endswith("/messages"):
        return url
    return f"{url}/messages"


def _anthropic_messages_completion(
    endpoint: AiAuditEndpoint,
    messages: Sequence[Mapping[str, str]],
    timeout_seconds: float,
) -> str:
    endpoint = endpoint.normalized()
    system_parts = [str(message.get("content") or "") for message in messages if message.get("role") == "system"]
    user_messages = [
        {"role": str(message.get("role") or "user"), "content": str(message.get("content") or "")}
        for message in messages
        if message.get("role") != "system"
    ]
    body = json.dumps(
        {
            "model": endpoint.model,
            "max_tokens": 700,
            "system": "\n\n".join(part for part in system_parts if part.strip()),
            "messages": user_messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _anthropic_messages_url(endpoint.base_url),
        data=body,
        headers={
            "x-api-key": endpoint.api_key,
            "anthropic-version": endpoint.api_version or DEFAULT_ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    def _call() -> str:
        try:
            with urllib.request.urlopen(request, timeout=float(timeout_seconds)) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            detail = _scrub_api_key_from_text(detail)
            raise AiAuditError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise AiAuditError(f"network or encoding error: {exc}") from exc

        payload = json.loads(response_body)
        content = payload.get("content") if isinstance(payload, Mapping) else None
        if not isinstance(content, Sequence) or isinstance(content, (str, bytes, bytearray)):
            raise AiAuditError("Anthropic response did not include content")
        text_parts = [
            str(block.get("text") or "").strip()
            for block in content
            if isinstance(block, Mapping) and block.get("type") == "text" and str(block.get("text") or "").strip()
        ]
        if not text_parts:
            raise AiAuditError("Anthropic response did not include text content")
        return "\n\n".join(text_parts)

    return _retry_with_backoff(_call)


def _complete_with_endpoint(
    endpoint: AiAuditEndpoint,
    messages: Sequence[Mapping[str, str]],
    timeout_seconds: float,
) -> str:
    endpoint = endpoint.normalized()

    # Route through AiGateway when CODEX_AUDIT_SERVICE_URL is configured.
    # API keys live on the VPS — no keys in plugin config needed.
    gateway_url = os.environ.get("CODEX_AUDIT_SERVICE_URL", "").strip()
    if gateway_url:
        prompt = "\n\n".join(
            f"{str(m.get('role') or 'user').upper()}:\n{str(m.get('content') or '').strip()}"
            for m in messages if str(m.get("content") or "").strip()
        )
        if endpoint.provider == PROVIDER_CODEX:
            return _codex_via_gateway(prompt, endpoint.model, timeout_seconds)
        return _llm_via_gateway(prompt, endpoint.model, endpoint.provider, timeout_seconds)

    # Fallback: direct API / subprocess calls
    if endpoint.provider == PROVIDER_CODEX:
        return _codex_exec_completion(endpoint, messages, timeout_seconds)
    if endpoint.provider == PROVIDER_ANTHROPIC:
        return _anthropic_messages_completion(endpoint, messages, timeout_seconds)
    return _openai_compatible_chat_completion(endpoint, messages, timeout_seconds)


def _codex_via_gateway(prompt: str, model: str, timeout_seconds: float) -> str:
    """Execute via AiGateway service — delegates to CodexAdapter on VPS."""
    try:
        from ai_gateway_client import AiGatewayClient, GatewayConfig
        config = GatewayConfig.from_env()
        client = AiGatewayClient(config)
        result = client.execute(prompt, mode="review_only", model=model, timeout=timeout_seconds)
        if result.success:
            return result.output
        raise AiAuditError(result.error)
    except ImportError:
        return _codex_exec_direct(prompt, timeout_seconds)
    except Exception as exc:
        _logger.warning("ai_audit gateway codex call failed: %s; falling back to direct", exc)
        return _codex_exec_direct(prompt, timeout_seconds)


def _llm_via_gateway(prompt: str, model: str, provider: str, timeout_seconds: float) -> str:
    """Analyze via AiGateway service — delegates to LlmAdapter on VPS."""
    try:
        from ai_gateway_client import AiGatewayClient, GatewayConfig
        config = GatewayConfig.from_env()
        client = AiGatewayClient(config)
        result = client.analyze(prompt, model=model, timeout=timeout_seconds)
        if result.success:
            return result.output
        raise AiAuditError(result.error)
    except ImportError:
        return _llm_direct(prompt, model, provider, timeout_seconds)
    except Exception as exc:
        _logger.warning("ai_audit gateway analyze call failed: %s; falling back to direct", exc)
        return _llm_direct(prompt, model, provider, timeout_seconds)


def _llm_direct(prompt: str, model: str, provider: str, timeout_seconds: float) -> str:
    """Direct API call fallback when gateway is unavailable."""
    endpoint = AiAuditEndpoint(
        name="fallback", api_key="", provider=provider,
        base_url="", model=model,
    ).normalized()
    messages: tuple[Mapping[str, str], ...] = ({"role": "user", "content": prompt},)
    if provider == PROVIDER_ANTHROPIC:
        return _anthropic_messages_completion(endpoint, messages, timeout_seconds)
    return _openai_compatible_chat_completion(endpoint, messages, timeout_seconds)


def _codex_exec_direct(prompt: str, timeout_seconds: float) -> str:
    """Direct codex exec fallback when gateway is unavailable."""
    with tempfile.TemporaryDirectory(prefix="qsp-ai-audit-") as temp_dir:
        output_path = Path(temp_dir) / "codex-final-message.md"
        command = ["codex", "exec", "--cd", temp_dir, "--output-last-message", str(output_path), "-"]
        try:
            result = subprocess.run(
                command, input=prompt, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=float(timeout_seconds), check=False, env=_scrubbed_codex_env(),
            )
        except FileNotFoundError as exc:
            raise AiAuditError("codex command was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise AiAuditError(f"codex command timed out after {timeout_seconds:g}s") from exc
        if result.returncode != 0:
            detail = _bounded_text(result.stdout or "", limit=300)
            raise AiAuditError(f"codex command failed with exit code {result.returncode}: {detail}")
        text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if not text:
            text = str(result.stdout or "").strip()
        if not text:
            raise AiAuditError("codex command returned empty output")
        return text


def _scrubbed_codex_env() -> dict[str, str]:
    secret_markers = ("TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "CREDENTIAL", "API_KEY")
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in secret_markers)
    }


def _codex_exec_completion(
    endpoint: AiAuditEndpoint,
    messages: Sequence[Mapping[str, str]],
    timeout_seconds: float,
) -> str:
    del endpoint
    prompt = "\n\n".join(
        f"{str(message.get('role') or 'user').upper()}:\n{str(message.get('content') or '').strip()}"
        for message in messages
        if str(message.get("content") or "").strip()
    )
    with tempfile.TemporaryDirectory(prefix="qsp-ai-audit-") as temp_dir:
        output_path = Path(temp_dir) / "codex-final-message.md"
        command = [
            "codex",
            "exec",
            "--cd",
            temp_dir,
            "--output-last-message",
            str(output_path),
            "-",
        ]
        try:
            result = subprocess.run(
                command,
                input=prompt,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=float(timeout_seconds),
                check=False,
                env=_scrubbed_codex_env(),
            )
        except FileNotFoundError as exc:
            raise AiAuditError("codex command was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise AiAuditError(f"codex command timed out after {timeout_seconds:g}s") from exc
        if result.returncode != 0:
            detail = _bounded_text(result.stdout or "", limit=300)
            raise AiAuditError(f"codex command failed with exit code {result.returncode}: {detail}")
        text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if not text:
            text = str(result.stdout or "").strip()
        if not text:
            raise AiAuditError("codex command returned empty output")
        return text


def _extract_json_object(value: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, Mapping):
        raise AiAuditError("AI audit response must be a JSON object")
    return dict(parsed)


def _bounded_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _bounded_list(value: Any, *, limit: int = 5, item_limit: int = 160) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, Sequence):
        raw_items = list(value)
    else:
        raw_items = []
    items: list[str] = []
    for item in raw_items:
        text = _bounded_text(item, limit=item_limit)
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence


def _normalize_ai_audit_response(response: Mapping[str, Any]) -> dict[str, Any]:
    verdict = _bounded_text(response.get("verdict"), limit=64).lower() or "review"
    if verdict not in {"agree", "review", "data_insufficient"}:
        verdict = "review"
    route_assessment = _bounded_text(response.get("route_assessment"), limit=96).lower() or "insufficient_context"
    confidence = _as_confidence(response.get("confidence"))
    return {
        "verdict": verdict,
        "route_assessment": route_assessment,
        "confidence": confidence,
        "summary": _bounded_text(response.get("summary"), limit=600),
        "key_risks": _bounded_list(response.get("key_risks")),
        "data_gaps": _bounded_list(response.get("data_gaps")),
        "human_review_recommended": _as_bool(response.get("human_review_recommended"), default=True),
    }


def _build_crisis_audit_messages(crisis_payload: Mapping[str, Any]) -> tuple[Mapping[str, str], ...]:
    audit_input = {
        "as_of": _sanitize_user_input(crisis_payload.get("as_of")),
        "canonical_route": _sanitize_user_input(crisis_payload.get("canonical_route")),
        "suggested_action": _sanitize_user_input(crisis_payload.get("suggested_action")),
        "would_trade_if_enabled": _sanitize_user_input(crisis_payload.get("would_trade_if_enabled")),
        "watch_label": _sanitize_user_input(crisis_payload.get("watch_label")),
        "price_scanner_active": _sanitize_user_input(crisis_payload.get("price_scanner_active")),
        "bubble_fragility_active": _sanitize_user_input(crisis_payload.get("bubble_fragility_active")),
        "kill_switch_active": _sanitize_user_input(crisis_payload.get("kill_switch_active")),
        "kill_switch_reason": _sanitize_user_input(crisis_payload.get("kill_switch_reason")),
        "data_freshness": _sanitize_user_input(crisis_payload.get("data_freshness")),
        "data_quality": _sanitize_user_input(crisis_payload.get("data_quality")),
        "evidence": _sanitize_user_input(crisis_payload.get("evidence")),
        "deterministic_audit_summary": _sanitize_user_input(crisis_payload.get("audit_summary")),
    }
    return (
        {
            "role": "system",
            "content": (
                "You are a shadow-only risk-control auditor for a deterministic US equity crisis plugin. "
                "You must not recommend trades, sizing, or override the deterministic route. "
                "Audit whether the supplied evidence coherently supports the route and flag data gaps. "
                "Return JSON only with keys: verdict, route_assessment, confidence, summary, "
                "key_risks, data_gaps, human_review_recommended. "
                "verdict must be one of agree, review, data_insufficient."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(audit_input, ensure_ascii=False, sort_keys=True),
        },
    )


def _build_taco_audit_messages(taco_payload: Mapping[str, Any]) -> tuple[Mapping[str, str], ...]:
    audit_input = {
        "as_of": _sanitize_user_input(taco_payload.get("as_of")),
        "canonical_route": _sanitize_user_input(taco_payload.get("canonical_route")),
        "suggested_action": _sanitize_user_input(taco_payload.get("suggested_action")),
        "manual_review_required": _sanitize_user_input(taco_payload.get("manual_review_required")),
        "notification_reason": _sanitize_user_input(taco_payload.get("notification_reason")),
        "suppression_reason": _sanitize_user_input(taco_payload.get("suppression_reason")),
        "rebound_context_active": _sanitize_user_input(taco_payload.get("rebound_context_active")),
        "event_context_active": _sanitize_user_input(taco_payload.get("event_context_active")),
        "price_stress_scan_active": _sanitize_user_input(taco_payload.get("price_stress_scan_active")),
        "price_crisis_guard_active": _sanitize_user_input(taco_payload.get("price_crisis_guard_active")),
        "event_quality": _sanitize_user_input(taco_payload.get("event_quality")),
        "data_freshness": _sanitize_user_input(taco_payload.get("data_freshness")),
        "selected_event": _sanitize_user_input(taco_payload.get("selected_event")),
        "recognized_event_ids": _sanitize_user_input(taco_payload.get("recognized_event_ids")),
        "active_event_ids": _sanitize_user_input(taco_payload.get("active_event_ids")),
        "rebound_confirmation": _sanitize_user_input(taco_payload.get("rebound_confirmation")),
    }
    return (
        {
            "role": "system",
            "content": (
                "You are a shadow-only event-context auditor for a deterministic TACO rebound plugin. "
                "You must not recommend trades, sizing, or override the deterministic route. "
                "Audit whether the supplied event source, price-stress context, and rebound confirmation "
                "coherently support the manual-review or watch-only route. "
                "Return JSON only with keys: verdict, route_assessment, confidence, summary, "
                "key_risks, data_gaps, human_review_recommended. "
                "verdict must be one of agree, review, data_insufficient."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(audit_input, ensure_ascii=False, sort_keys=True),
        },
    )


def _failure_text(exc: BaseException) -> str:
    return _bounded_text(f"{type(exc).__name__}: {exc}", limit=300)


def _report_shadow_disagreement(
    *,
    audit_kind: str,
    ai_verdict: str,
    ai_confidence: float,
    deterministic_route: str,
) -> None:
    """Fire-and-forget report of AI vs deterministic disagreement to AiGateway.

    When AI shadow audit disagrees with the deterministic route, report it
    so the gateway can track cumulative disagreements and auto-escalate.
    Only sends if CODEX_AUDIT_SERVICE_URL is configured.
    """
    import urllib.request as _ur
    service_url = os.environ.get("CODEX_AUDIT_SERVICE_URL", "").strip()
    if not service_url:
        return
    # Only report if AI disagrees (verdict is not "agree")
    if ai_verdict == "agree":
        return
    try:
        # Map audit kind to plugin name
        plugin_map = {
            "crisis_response_shadow": "crisis_response",
            "taco_rebound_shadow": "taco_rebound",
        }
        plugin = plugin_map.get(audit_kind, audit_kind)
        token = _env(
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
            "CODEX_AUDIT_SERVICE_TOKEN",
        ) or ""
        if not token:
            token = os.environ.get("CODEX_AUDIT_SERVICE_TOKEN", "")
        if not token:
            return  # No auth available, skip silently
        payload = json.dumps({
            "plugin": plugin,
            "ai_verdict": ai_verdict,
            "ai_confidence": ai_confidence,
            "deterministic_route": deterministic_route,
            "source_repository": os.environ.get("AI_GATEWAY_SOURCE_REPO", ""),
        }).encode("utf-8")
        req = _ur.Request(
            f"{service_url.rstrip('/')}/v1/ai/feedback/shadow",
            data=payload, method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "quant-strategy-plugins",
            },
        )
        _ur.urlopen(req, timeout=5)
    except Exception:
        pass  # Fire-and-forget — never block the main audit flow


def build_disabled_ai_audit(*, audit_kind: str = "strategy_plugin") -> dict[str, Any]:
    return {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "audit_kind": audit_kind,
        "enabled": False,
        "status": "disabled",
        "mode": "shadow_only",
        "final_route_unchanged": True,
    }


def _run_ai_audit(
    deterministic_payload: Mapping[str, Any],
    *,
    audit_kind: str,
    messages: Sequence[Mapping[str, str]],
    enabled: bool,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
    fallback_model: str | None = None,
    codex_enabled: bool | None = None,
    codex_model: str | None = None,
    anthropic_api_key: str | None = None,
    anthropic_base_url: str | None = None,
    anthropic_model: str | None = None,
    anthropic_version: str | None = None,
    timeout_seconds: float = DEFAULT_AI_AUDIT_TIMEOUT_SECONDS,
    completion_client: CompletionClient | None = None,
) -> dict[str, Any]:
    if not enabled:
        return build_disabled_ai_audit(audit_kind=audit_kind)

    endpoints = build_ai_audit_endpoints(
        api_key=api_key,
        base_url=base_url,
        model=model,
        fallback_api_key=fallback_api_key,
        fallback_base_url=fallback_base_url,
        fallback_model=fallback_model,
        codex_enabled=codex_enabled,
        codex_model=codex_model,
        anthropic_api_key=anthropic_api_key,
        anthropic_base_url=anthropic_base_url,
        anthropic_model=anthropic_model,
        anthropic_version=anthropic_version,
    )
    base_payload = {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "audit_kind": audit_kind,
        "enabled": True,
        "mode": "shadow_only",
        "deterministic_profile": deterministic_payload.get("profile"),
        "deterministic_route": deterministic_payload.get("canonical_route"),
        "deterministic_action": deterministic_payload.get("suggested_action"),
        "final_route_unchanged": True,
        "execution_controls": {
            "capital_impact": "none",
            "broker_order_allowed": False,
            "live_allocation_mutation_allowed": False,
            "allocation_recommendation_allowed": False,
            "notification_profile": "shadow_only",
        },
    }
    if not endpoints:
        return {
            **base_payload,
            "status": "skipped",
            "skip_reason": "missing_api_endpoint",
            "attempts": [],
        }

    client = completion_client or _complete_with_endpoint
    attempts: list[dict[str, Any]] = []
    for endpoint in endpoints:
        try:
            raw_response = client(endpoint, messages, float(timeout_seconds))
            audit_response = _normalize_ai_audit_response(_extract_json_object(raw_response))
            attempts.append({**endpoint.report(), "status": "ok"})

            # Phase 3: report AI vs deterministic disagreement to AiGateway
            _report_shadow_disagreement(
                audit_kind=audit_kind,
                ai_verdict=audit_response.get("verdict", ""),
                ai_confidence=audit_response.get("confidence") or 0.0,
                deterministic_route=str(deterministic_payload.get("canonical_route") or
                                       deterministic_payload.get("suggested_action") or ""),
            )

            return {
                **base_payload,
                "status": "ok",
                "selected_endpoint": endpoint.report(),
                "attempts": attempts,
                **audit_response,
            }
        except Exception as exc:
            attempts.append({**endpoint.report(), "status": "failed", "error": _failure_text(exc)})

    return {
        **base_payload,
        "status": "failed",
        "attempts": attempts,
        "error": attempts[-1]["error"] if attempts else "unknown AI audit failure",
    }


def run_crisis_ai_audit(
    crisis_payload: Mapping[str, Any],
    *,
    enabled: bool,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
    fallback_model: str | None = None,
    codex_enabled: bool | None = None,
    codex_model: str | None = None,
    anthropic_api_key: str | None = None,
    anthropic_base_url: str | None = None,
    anthropic_model: str | None = None,
    anthropic_version: str | None = None,
    timeout_seconds: float = DEFAULT_AI_AUDIT_TIMEOUT_SECONDS,
    completion_client: CompletionClient | None = None,
) -> dict[str, Any]:
    return _run_ai_audit(
        crisis_payload,
        audit_kind="crisis_response_shadow",
        messages=_build_crisis_audit_messages(crisis_payload),
        enabled=enabled,
        api_key=api_key,
        base_url=base_url,
        model=model,
        fallback_api_key=fallback_api_key,
        fallback_base_url=fallback_base_url,
        fallback_model=fallback_model,
        codex_enabled=codex_enabled,
        codex_model=codex_model,
        anthropic_api_key=anthropic_api_key,
        anthropic_base_url=anthropic_base_url,
        anthropic_model=anthropic_model,
        anthropic_version=anthropic_version,
        timeout_seconds=timeout_seconds,
        completion_client=completion_client,
    )


def run_taco_ai_audit(
    taco_payload: Mapping[str, Any],
    *,
    enabled: bool,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
    fallback_model: str | None = None,
    codex_enabled: bool | None = None,
    codex_model: str | None = None,
    anthropic_api_key: str | None = None,
    anthropic_base_url: str | None = None,
    anthropic_model: str | None = None,
    anthropic_version: str | None = None,
    timeout_seconds: float = DEFAULT_AI_AUDIT_TIMEOUT_SECONDS,
    completion_client: CompletionClient | None = None,
) -> dict[str, Any]:
    return _run_ai_audit(
        taco_payload,
        audit_kind="taco_rebound_shadow",
        messages=_build_taco_audit_messages(taco_payload),
        enabled=enabled,
        api_key=api_key,
        base_url=base_url,
        model=model,
        fallback_api_key=fallback_api_key,
        fallback_base_url=fallback_base_url,
        fallback_model=fallback_model,
        codex_enabled=codex_enabled,
        codex_model=codex_model,
        anthropic_api_key=anthropic_api_key,
        anthropic_base_url=anthropic_base_url,
        anthropic_model=anthropic_model,
        anthropic_version=anthropic_version,
        timeout_seconds=timeout_seconds,
        completion_client=completion_client,
    )
