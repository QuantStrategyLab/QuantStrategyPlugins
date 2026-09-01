import sys
import types

import pytest

from quant_strategy_plugins import ai_audit
from quant_strategy_plugins.ai_audit import (
    AiAuditError,
    _codex_via_gateway,
    _failure_text,
    _llm_via_gateway,
    _run_ai_audit,
    _scrub_api_key_from_text,
    build_ai_audit_endpoints,
)


def _clear_ai_audit_env(monkeypatch) -> None:
    for key in (
        "QSP_STRATEGY_PLUGIN_AI_AUDIT_API_KEY",
        "QSP_CRISIS_AI_AUDIT_API_KEY",
        "OPENAI_API_KEY",
        "QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_API_KEY",
        "QSP_CRISIS_AI_AUDIT_FALLBACK_API_KEY",
        "OPENAI_FALLBACK_API_KEY",
        "QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY",
        "QSP_CRISIS_AI_AUDIT_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "CODEX_AUDIT_SERVICE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_ai_audit_uses_generic_anthropic_api_key(monkeypatch) -> None:
    _clear_ai_audit_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")

    endpoints = build_ai_audit_endpoints(codex_enabled=False)

    assert len(endpoints) == 1
    assert endpoints[0].name == "anthropic"
    assert endpoints[0].provider == "anthropic"
    assert endpoints[0].model == "claude-test"


def test_ai_audit_prefers_strategy_specific_anthropic_key(monkeypatch) -> None:
    _clear_ai_audit_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-generic")
    monkeypatch.setenv("QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY", "sk-ant-specific")

    endpoints = build_ai_audit_endpoints(codex_enabled=False)

    assert endpoints[0].name == "anthropic"
    assert endpoints[0].api_key == "sk-ant-specific"


def test_ai_audit_scrubs_assignment_style_secret_text() -> None:
    api_key_field = "api" + "_key"
    token_field = "to" + "ken"
    api_key_value = "super" + "secret123"
    token_value = "token" + "secret987"
    raw = f"provider failed with {api_key_field}={api_key_value} and {token_field}='{token_value}'"

    scrubbed = _scrub_api_key_from_text(raw)

    assert "api_key=[REDACTED]" in scrubbed
    assert "token=[REDACTED]" in scrubbed
    assert api_key_value not in scrubbed
    assert token_value not in scrubbed


def test_ai_audit_failure_text_redacts_secret_values() -> None:
    password_field = "pass" + "word"
    password_value = "super" + "secret123"
    error = RuntimeError(f"upstream returned {password_field}={password_value}")

    text = _failure_text(error)

    assert "password=[REDACTED]" in text
    assert password_value not in text


def test_ai_audit_skips_when_gateway_is_unavailable(monkeypatch) -> None:
    _clear_ai_audit_env(monkeypatch)
    calls: list[str] = []

    payload = _run_ai_audit(
        {"canonical_route": "true_crisis", "suggested_action": "defend"},
        audit_kind="crisis_response_shadow",
        messages=({"role": "user", "content": "audit"},),
        enabled=True,
        api_key="sk-primary",
        codex_enabled=False,
        completion_client=lambda *_args: calls.append("direct") or "{}",
    )

    assert payload["status"] == "skipped"
    assert payload["skip_reason"] == "gateway_unavailable"
    assert payload["final_route_unchanged"] is True
    assert calls == []


def test_ai_audit_rejects_custom_completion_client(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.example")
    calls: list[str] = []

    payload = _run_ai_audit(
        {"canonical_route": "true_crisis", "suggested_action": "defend"},
        audit_kind="crisis_response_shadow",
        messages=({"role": "user", "content": "audit"},),
        enabled=True,
        completion_client=lambda *_args: calls.append("custom") or "{}",
    )

    assert payload["status"] == "skipped"
    assert payload["skip_reason"] == "custom_completion_client_forbidden"
    assert calls == []


def test_gateway_uses_default_model_without_local_provider_key(monkeypatch) -> None:
    _clear_ai_audit_env(monkeypatch)
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.example")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        ai_audit,
        "_complete_with_endpoint",
        lambda endpoint, *_args: calls.append((endpoint.provider, endpoint.model))
        or '{"verdict":"agree","summary":"ok","risk_flags":[],"evidence_gaps":[],"confidence":0.5}',
    )
    payload = _run_ai_audit(
        {"canonical_route": "true_crisis", "suggested_action": "defend"},
        audit_kind="crisis_response_shadow",
        messages=({"role": "user", "content": "audit"},),
        enabled=True,
        codex_enabled=False,
    )

    assert payload["status"] == "ok"
    assert calls == [("openai", "gpt-5.4-mini")]


def test_gateway_success_calls_analyze_and_execute(monkeypatch) -> None:
    calls: list[tuple[str, tuple, dict]] = []

    class SuccessfulGatewayClient:
        def __init__(self, _config) -> None:
            pass

        def analyze(self, *args, **kwargs):
            calls.append(("analyze", args, kwargs))
            return types.SimpleNamespace(success=True, output="analysis", provider="openai")

        def execute(self, *args, **kwargs):
            calls.append(("execute", args, kwargs))
            return types.SimpleNamespace(success=True, output="review", provider="codex")

    monkeypatch.setitem(
        sys.modules,
        "ai_gateway_client",
        types.SimpleNamespace(
            AiGatewayClient=SuccessfulGatewayClient,
            GatewayConfig=types.SimpleNamespace(from_env=lambda: object()),
        ),
    )

    assert _llm_via_gateway("audit", "gpt-test", "openai", 3.0) == "analysis"
    assert _codex_via_gateway("review", "codex-test", 4.0) == "review"
    assert calls == [
        ("analyze", ("audit",), {"model": "gpt-test", "timeout": 3.0}),
        ("execute", ("review",), {"mode": "review_only", "model": "codex-test", "timeout": 4.0}),
    ]


@pytest.mark.parametrize("actual_provider", ["anthropic", ""])
def test_gateway_provider_mismatch_fails_closed(monkeypatch, actual_provider: str) -> None:
    class MismatchedGatewayClient:
        def __init__(self, _config) -> None:
            pass

        def analyze(self, *_args, **_kwargs):
            return types.SimpleNamespace(success=True, output="analysis", provider=actual_provider)

    monkeypatch.setitem(
        sys.modules,
        "ai_gateway_client",
        types.SimpleNamespace(
            AiGatewayClient=MismatchedGatewayClient,
            GatewayConfig=types.SimpleNamespace(from_env=lambda: object()),
        ),
    )

    with pytest.raises(AiAuditError, match="ai_gateway_provider_mismatch"):
        _llm_via_gateway("audit", "gpt-test", "openai", 3.0)


@pytest.mark.parametrize(
    ("gateway_call", "direct_fallback"),
    [
        (_llm_via_gateway, "_llm_direct"),
        (_codex_via_gateway, "_codex_exec_direct"),
    ],
)
def test_gateway_failure_never_uses_direct_fallback(monkeypatch, gateway_call, direct_fallback) -> None:
    class FailingGatewayClient:
        def __init__(self, _config) -> None:
            pass

        def analyze(self, *_args, **_kwargs):
            raise RuntimeError("provider token=supersecret123 failed")

        def execute(self, *_args, **_kwargs):
            raise RuntimeError("provider token=supersecret123 failed")

    monkeypatch.setitem(
        sys.modules,
        "ai_gateway_client",
        types.SimpleNamespace(
            AiGatewayClient=FailingGatewayClient,
            GatewayConfig=types.SimpleNamespace(from_env=lambda: object()),
        ),
    )
    direct_calls: list[str] = []
    monkeypatch.setattr(ai_audit, direct_fallback, lambda *_args: direct_calls.append("direct") or "{}")

    with pytest.raises(AiAuditError, match="ai_gateway_request_failed") as exc_info:
        if gateway_call is _llm_via_gateway:
            gateway_call("audit", "test-model", "openai", 1.0)
        else:
            gateway_call("audit", "test-model", 1.0)

    assert "supersecret123" not in str(exc_info.value)
    assert direct_calls == []


@pytest.mark.parametrize(
    ("gateway_call", "direct_fallback"),
    [
        (_llm_via_gateway, "_llm_direct"),
        (_codex_via_gateway, "_codex_exec_direct"),
    ],
)
def test_gateway_client_import_failure_never_uses_direct_fallback(monkeypatch, gateway_call, direct_fallback) -> None:
    monkeypatch.setitem(sys.modules, "ai_gateway_client", None)
    direct_calls: list[str] = []
    monkeypatch.setattr(ai_audit, direct_fallback, lambda *_args: direct_calls.append("direct") or "{}")

    with pytest.raises(AiAuditError, match="ai_gateway_client_unavailable"):
        if gateway_call is _llm_via_gateway:
            gateway_call("audit", "test-model", "openai", 1.0)
        else:
            gateway_call("audit", "test-model", 1.0)

    assert direct_calls == []
