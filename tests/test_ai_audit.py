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
        or ('{"verdict":"agree","summary":"ok","risk_flags":[],"evidence_gaps":[],"confidence":0.5}', False),
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

    assert _llm_via_gateway("audit", "gpt-test", "openai", 3.0) == ("analysis", False)
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


def _install_analysis_result(monkeypatch, result):
    calls = []

    class FakeGatewayClient:
        def __init__(self, _config):
            pass

        def analyze(self, *_args, **_kwargs):
            calls.append("analyze")
            return result

        def execute(self, *_args, **_kwargs):
            raise AssertionError("advisory analysis must not execute")

    monkeypatch.setitem(sys.modules, "ai_gateway_client", types.SimpleNamespace(
        AiGatewayClient=FakeGatewayClient,
        GatewayConfig=types.SimpleNamespace(from_env=lambda: object()),
    ))
    return calls


@pytest.mark.parametrize("status", ["ok", "advisory"])
@pytest.mark.parametrize("entry", [ai_audit.run_crisis_ai_audit, ai_audit.run_taco_ai_audit])
def test_research_content_preserves_status_controls_and_feedback_boundary(monkeypatch, status, entry):
    import json
    from copy import deepcopy
    from quant_strategy_plugins.plugin_signal_utils import flatten_for_csv, json_scalar

    output = json.dumps({
        "verdict": "review", "summary": "synthetic research opinion", "confidence": 0.8,
        "status": "ok", "final_route_unchanged": False, "mode": "live",
        "execution_controls": {"broker_order_allowed": True},
    })
    result = types.SimpleNamespace(
        success=status == "ok", output=output, provider="openai", model="test-model",
        note="advisory" if status == "advisory" else "", error="",
        raw={"status": status, "output": output,
             "policy_verdict": "advisory" if status == "advisory" else "eligible"},
    )
    calls = _install_analysis_result(monkeypatch, result)
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.invalid")
    monkeypatch.setattr(ai_audit, "build_ai_audit_endpoints", lambda **_kwargs: (
        ai_audit.AiAuditEndpoint("primary", "", model="test-model"),
        ai_audit.AiAuditEndpoint("fallback", "", model="fallback-model"),
    ))
    feedback = []
    monkeypatch.setattr(ai_audit, "_report_shadow_disagreement", lambda **fields: feedback.append(fields))
    deterministic = {"profile": "synthetic", "canonical_route": "no_action", "suggested_action": "watch_only"}
    original = deepcopy(deterministic)
    payload = entry(deterministic, enabled=True, codex_enabled=False)

    assert payload["status"] == status
    assert payload["attempts"][0]["status"] == status
    assert calls == ["analyze"]  # Advisory must not trigger a fallback model.
    assert len(feedback) == (1 if status == "ok" else 0)
    assert payload["final_route_unchanged"] is True
    assert payload["mode"] == "shadow_only"
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["allocation_recommendation_allowed"] is False
    assert payload["selected_endpoint"]["provider"] == "openai"
    assert deterministic == original
    embedded = json_scalar({**deterministic, "ai_audit": payload})
    assert flatten_for_csv(embedded)["ai_audit.status"] == status
    assert result.success is (status == "ok")


@pytest.mark.parametrize("changes", [
    {"success": True, "note": "advisory", "raw": {"status": "failed"}},
    {"success": True, "raw": {"status": "invalid"}},
    {"success": True, "raw": {"status": "unknown"}},
    {"success": False, "note": "advisory", "raw": {"status": "ok"}},
    {"success": True, "note": "advisory", "raw": {"status": "advisory"}},
    {"success": False, "note": "advisory", "raw": {"status": "advisory", "policy_verdict": "invalid"}},
    {"success": False, "note": "advisory", "raw": None},
    {"success": True, "note": "failed", "raw": None},
    {"success": True, "raw": {"status": "ok", "output": None}},
    {"success": True, "output": 42},
    {"success": True, "output": None},
    {"success": True, "output": "  "},
    {"success": True, "output": {"summary": "not text"}},
])
def test_invalid_analysis_metadata_and_content_are_rejected(monkeypatch, changes):
    fields = dict(success=True, note="", error="", raw=None, provider="openai", output="synthetic text")
    fields.update(changes)
    _install_analysis_result(monkeypatch, types.SimpleNamespace(**fields))
    with pytest.raises(AiAuditError, match="ai_gateway_rejected"):
        _llm_via_gateway("synthetic prompt", "test-model", "openai", 1.0)


def test_advisory_provider_mismatch_still_rejected(monkeypatch):
    _install_analysis_result(monkeypatch, types.SimpleNamespace(
        success=False, note="advisory", error="", provider="anthropic", output="synthetic text",
        raw={"status": "advisory", "output": "synthetic text"},
    ))
    with pytest.raises(AiAuditError, match="ai_gateway_provider_mismatch"):
        _llm_via_gateway("synthetic prompt", "test-model", "openai", 1.0)
