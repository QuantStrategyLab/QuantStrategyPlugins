import sys
import types
import json
import io
import tomllib
from importlib.metadata import distribution
from pathlib import Path

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


@pytest.mark.parametrize("confidence", ["nan", "NaN", "inf", "-inf", float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("entry", [ai_audit.run_taco_ai_audit])
def test_nonfinite_confidence_remains_unknown_and_does_not_write_feedback(monkeypatch, confidence, entry):
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.invalid")
    monkeypatch.setattr(ai_audit, "build_ai_audit_endpoints", lambda **_: (
        ai_audit.AiAuditEndpoint("primary", "", model="synthetic-model"),
    ))
    monkeypatch.setattr(ai_audit, "_complete_with_endpoint", lambda *_: (
        json.dumps({"verdict": "agree", "confidence": confidence}), False,
    ))
    feedback = []
    monkeypatch.setattr(ai_audit, "_report_shadow_disagreement", lambda **fields: feedback.append(fields))
    payload = entry({"canonical_route": "no_action"}, enabled=True)
    assert payload["confidence"] is None
    assert feedback == []
    assert payload["final_route_unchanged"] is True
    assert payload["execution_controls"]["broker_order_allowed"] is False
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("value,expected", [(None, None), ("invalid", None), (0.0, 0.0), ("0.8", 0.8), (1.0, 1.0)])
def test_confidence_finite_and_missing_values_keep_existing_semantics(value, expected):
    assert ai_audit._as_confidence(value) == expected


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


def test_optional_ai_extra_installs_the_declared_gateway_sdk() -> None:
    from ai_gateway_client import AiGatewayClient, AiResult, GatewayConfig

    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    requirement, = project["optional-dependencies"]["ai"]
    assert requirement.startswith("ai-gateway-client @ git+")
    assert not any(item.startswith("ai-gateway-client") for item in project["dependencies"])
    source = json.loads(distribution("ai-gateway-client").read_text("direct_url.json"))
    assert source["vcs_info"]["commit_id"] == requirement.rsplit("@", 1)[1]
    assert AiGatewayClient.__module__ == "ai_gateway_client.gateway_client"
    assert AiResult.__module__ == "ai_gateway_client.gateway_client"
    assert GatewayConfig.__module__ == "ai_gateway_client.config"


@pytest.mark.parametrize("entry", [ai_audit.run_taco_ai_audit])
def test_installed_sdk_consumes_codex_job_without_feedback_or_api_fallback(monkeypatch, entry):
    from ai_gateway_client import gateway_client

    _clear_ai_audit_env(monkeypatch)
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.invalid")
    monkeypatch.setenv("AI_GATEWAY_SOURCE_REPO", "QuantStrategyLab/UsEquitySnapshotPipelines")
    monkeypatch.setattr(gateway_client, "_fetch_oidc_token", lambda _audience: "synthetic")
    monkeypatch.setattr(gateway_client.time, "sleep", lambda _seconds: None)
    calls = []
    job_id = "synthetic-job-000000000000"

    def urlopen(request, **_kwargs):
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            assert request.full_url == "https://gateway.invalid/v1/ai/execute/jobs"
            payload = json.loads(request.data)
            assert payload["mode"] == "review_only"
            assert payload["model"] == "gpt-6-astra"
            assert payload["source_repository"] == "QuantStrategyLab/UsEquitySnapshotPipelines"
            assert "watch_only" in payload["prompt"]
            response = {"status": "queued", "job_id": job_id}
        else:
            assert request.full_url == f"https://gateway.invalid/v1/ai/execute/jobs/{job_id}"
            response = {"status": "succeeded", "output": json.dumps({
                "verdict": "review", "confidence": 0.8, "summary": "synthetic research opinion",
                "mode": "live", "execution_controls": {"broker_order_allowed": True},
            })}
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(gateway_client.urllib.request, "urlopen", urlopen)
    feedback = []
    monkeypatch.setattr(ai_audit, "_report_shadow_disagreement", lambda **fields: feedback.append(fields))
    deterministic = {"profile": "synthetic", "canonical_route": "no_action", "suggested_action": "watch_only"}
    payload = entry(deterministic, enabled=True, codex_enabled=True, codex_model="gpt-6-astra")

    assert payload["status"] == "advisory"
    assert payload["summary"] == "synthetic research opinion"
    assert payload["deterministic_route"] == "no_action"
    assert payload["final_route_unchanged"] is True
    assert payload["mode"] == "shadow_only"
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["allocation_recommendation_allowed"] is False
    assert len(payload["attempts"]) == 1
    assert [method for method, _url in calls] == ["POST", "GET"]
    assert feedback == []
    assert deterministic["canonical_route"] == "no_action"


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
        audit_kind="taco_rebound_shadow",
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
        audit_kind="taco_rebound_shadow",
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
        audit_kind="taco_rebound_shadow",
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


@pytest.mark.parametrize("entry", [ai_audit.run_taco_ai_audit])
def test_codex_execution_is_advisory_without_feedback_or_route_changes(monkeypatch, entry):
    from copy import deepcopy

    _clear_ai_audit_env(monkeypatch)
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.invalid")
    output = json.dumps({
        "verdict": "review", "confidence": 0.8, "summary": "synthetic research opinion",
        "status": "verified", "final_route_unchanged": False, "mode": "live",
        "execution_controls": {"broker_order_allowed": True},
    })
    calls = []

    class SuccessfulCodexClient:
        def __init__(self, _config):
            pass

        def execute(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return types.SimpleNamespace(success=True, output=output, provider="codex")

        def analyze(self, *_args, **_kwargs):
            raise AssertionError("Codex advisory must not fall back to a paid API")

    monkeypatch.setitem(sys.modules, "ai_gateway_client", types.SimpleNamespace(
        AiGatewayClient=SuccessfulCodexClient,
        GatewayConfig=types.SimpleNamespace(from_env=lambda: object()),
    ))
    feedback = []
    monkeypatch.setattr(ai_audit, "_report_shadow_disagreement", lambda **fields: feedback.append(fields))
    deterministic = {"profile": "synthetic", "canonical_route": "no_action", "suggested_action": "watch_only"}
    original = deepcopy(deterministic)

    payload = entry(deterministic, enabled=True, codex_enabled=True, codex_model="codex-test")

    assert payload["status"] == "advisory"
    assert payload["summary"] == "synthetic research opinion"
    assert payload["confidence"] == 0.8
    assert len(calls) == 1
    assert calls[0][1]["mode"] == "review_only"
    assert calls[0][1]["model"] == "codex-test"
    assert len(payload["attempts"]) == 1
    assert payload["attempts"][0]["status"] == "advisory"
    assert payload["selected_endpoint"]["provider"] == "codex"
    assert feedback == []
    assert deterministic == original
    assert payload["final_route_unchanged"] is True
    assert payload["mode"] == "shadow_only"
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["allocation_recommendation_allowed"] is False


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
    monkeypatch.setattr(ai_audit, direct_fallback, lambda *_args: direct_calls.append("direct") or "{}", raising=False)

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
    monkeypatch.setattr(ai_audit, direct_fallback, lambda *_args: direct_calls.append("direct") or "{}", raising=False)

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
@pytest.mark.parametrize("entry", [ai_audit.run_taco_ai_audit])
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


@pytest.mark.parametrize("value,expected", [
    (False, "False"), (True, "True"), (0, "0"), (0.0, "0.0"),
    (None, ""), ("", ""), ("  text\x00\x7f  ", "text"),
])
def test_input_sanitizer_preserves_known_falsy_values(value, expected):
    assert ai_audit._sanitize_user_input(value) == expected


def test_input_sanitizer_still_truncates_after_cleaning():
    assert ai_audit._sanitize_user_input("  a\x00bcdef  ", max_length=3) == "abc"


@pytest.mark.parametrize("builder,boolean_fields", [
    (ai_audit._build_crisis_audit_messages, (
        "would_trade_if_enabled", "price_scanner_active", "bubble_fragility_active", "kill_switch_active",
    )),
    (ai_audit._build_taco_audit_messages, (
        "manual_review_required", "rebound_context_active", "event_context_active",
        "price_stress_scan_active", "price_crisis_guard_active",
    )),
])
def test_original_prompts_distinguish_false_zero_and_missing(builder, boolean_fields):
    source = dict.fromkeys(boolean_fields, False)
    source["data_freshness"] = 0
    user = json.loads(builder(source)[1]["content"])
    assert all(user[field] == "False" for field in boolean_fields)
    assert user["data_freshness"] == "0"
    assert user["as_of"] == ""
    assert source == {**dict.fromkeys(boolean_fields, False), "data_freshness": 0}


@pytest.mark.parametrize("enabled", [False, True])
def test_crisis_legacy_path_is_closed_even_with_old_authorization(monkeypatch, enabled):
    monkeypatch.setenv("CODEX_AUDIT_SERVICE_URL", "https://gateway.invalid")
    def forbidden(*args, **kwargs):
        pytest.fail("Crisis must not enter the retired gateway or feedback path")
    for name in ("build_ai_audit_endpoints", "_complete_with_endpoint", "_report_shadow_disagreement"):
        monkeypatch.setattr(ai_audit, name, forbidden)
    result = ai_audit.run_crisis_ai_audit(
        {"canonical_route": "no_action"}, enabled=enabled, codex_enabled=True,
        api_key="synthetic", fallback_api_key="synthetic", anthropic_api_key="synthetic",
    )
    assert result["status"] == ("skipped" if enabled else "disabled")
    if enabled:
        assert result["skip_reason"] == "native_context_required"
        assert result["attempts"] == []
    assert result["final_route_unchanged"] is True


@pytest.fixture
def native_instance():
    pytest.importorskip("ai_service.scenarios")
    return {
        "schema_version": "scenario.instance.v1", "id": "synthetic.crisis-audit",
        "project": ai_audit.CRISIS_NATIVE_PROJECT, "template": "report_audit", "template_version": "1",
        "enabled": True, "config_revision": "a" * 40,
        "inputs": {"manifest_ref": "synthetic.report", "data_classification": "synthetic",
                   "fields": {"materials_ref": "synthetic.report", "checklist_ref": "synthetic.consistency"}},
        "stages": [{"phase": "review", "role": "primary", "worker_type": "dot",
                    "route_ref": "synthetic.dot", "model_ref": "synthetic.model", "tool_sets": [],
                    "limits": {"max_media_bytes": 0}}],
        "executor_ref": None, "gate_refs": [], "schedule": {"kind": "manual"},
        "output": {"schema_ref": ai_audit.AI_AUDIT_SCHEMA_VERSION, "evidence_store_ref": "synthetic.audit",
                   "public_projection_ref": "synthetic.advisory", "retention_policy_ref": "synthetic.retention",
                   "sink_ref": "synthetic.advisory"},
        "approvals": {"activation_ref": "synthetic.offline-only"},
    }


def _native_task(instance, payload=None, **changes):
    from datetime import datetime, timezone
    values = dict(source_ref="synthetic.frozen-report", source_revision="b" * 40, source_sha256="c" * 64,
                  occurrence="synthetic.report-1", submitted_at=datetime(2099, 1, 1, tzinfo=timezone.utc))
    values.update(changes)
    return ai_audit.prepare_crisis_shadow_audit(
        payload or {"canonical_route": "no_action", "suggested_action": "watch_only"},
        instance=instance, **values,
    )


def _native_record(task):
    from copy import deepcopy
    return {"id": "synthetic-task", "owner": ai_audit.CRISIS_NATIVE_PROJECT, "provider": "dot",
            "status": "completed", "result_kind": "advisory", "attempt": "synthetic-attempt",
            "worker": "synthetic-worker", "revision": 1, "request": deepcopy(task.request),
            "output": {"verdict": "data_insufficient", "route_assessment": "insufficient_context",
                       "confidence": "unknown", "summary": "The frozen report lacks evidence.", "key_risks": [],
                       "data_gaps": ["Evidence, freshness and observation date are missing."],
                       "human_review_recommended": True}}


def test_native_crisis_prepare_reuses_projection_and_quant_identity(native_instance):
    from ai_service.scenarios.pilot import digest
    source = {"canonical_route": "no_action", "suggested_action": "watch_only", "kill_switch_active": False,
              "raw_bars": "excluded", "account": "excluded", "orders": "excluded"}
    task = _native_task(native_instance, source)
    manifest = task.request["materials"][0]["input_manifest"]
    assert manifest["report"] == json.loads(ai_audit._build_crisis_audit_messages(source)[1]["content"])
    assert "excluded" not in json.dumps(task.request)
    assert manifest["report"]["kill_switch_active"] == "False"
    assert task.spec["input_manifest_sha256"] == digest(manifest)
    assert (task.spec["template"], task.spec["phase"], task.spec["role"]) == ("report_audit", "review", "primary")
    assert task.request["mode"] == "agent"
    assert task.request["profile"] == "synthetic.dot"
    assert set(task.request["output_schema"]["properties"]) == {
        "verdict", "route_assessment", "confidence", "summary", "key_risks", "data_gaps",
        "human_review_recommended",
    }
    source["canonical_route"] = "mutated"
    native_instance["config_revision"] = "d" * 40
    assert manifest["report"]["canonical_route"] == "no_action"
    assert task.spec["config_revision"] == "a" * 40


@pytest.mark.parametrize("section,key,value", [
    (None, "enabled", False), (None, "project", "Other/Project"), (None, "template", "protocol_probe"),
    (None, "executor_ref", "synthetic.executor"), ("schedule", "kind", "event"),
    ("inputs", "data_classification", "restricted"), ("output", "schema_ref", "other.schema"),
    ("stage", "worker_type", "grok"), ("stage", "worker_type", "api"),
    ("stage", "phase", "confirm"), ("stage", "role", "second-opinion"),
    ("stage", "tool_sets", ["synthetic.tool"]), ("limits", "max_calls", 2),
    ("limits", "max_active", 2), ("limits", "max_media_bytes", 1),
    ("limits", "monthly_budget_usd", 1), ("limits", "max_request_bytes", 1),
    ("fields", "small_review", True),
])
def test_native_crisis_rejects_unapproved_scope_and_routes(native_instance, section, key, value):
    from ai_service.scenarios import ContractError
    target = native_instance if section is None else (
        native_instance["stages"][0] if section == "stage" else
        native_instance["stages"][0]["limits"] if section == "limits" else
        native_instance["inputs"]["fields"] if section == "fields" else native_instance[section])
    target[key] = value
    with pytest.raises(ContractError):
        _native_task(native_instance)


@pytest.mark.parametrize("field,value", [("source_ref", "/local/report.json"), ("source_sha256", "bad"),
                                        ("source_revision", "main")])
def test_native_crisis_requires_precise_provenance(native_instance, field, value):
    from ai_service.scenarios import ContractError
    with pytest.raises(ContractError):
        _native_task(native_instance, **{field: value})


def test_native_crisis_verified_result_is_separate_advisory(native_instance, monkeypatch):
    from ai_service.scenarios.pilot import digest
    task = _native_task(native_instance)
    record = _native_record(task)
    original = json.dumps(record, sort_keys=True)
    monkeypatch.setattr(ai_audit, "_report_shadow_disagreement", lambda **_: pytest.fail("no feedback"))
    result = ai_audit.verify_crisis_shadow_audit(task, record, task_id=record["id"])
    assert result["status"] == "advisory"
    assert result["confidence"] is None
    assert result["mode"] == "shadow_only"
    assert result["final_route_unchanged"] is True
    for key in ("broker_order_allowed", "live_allocation_mutation_allowed", "allocation_recommendation_allowed"):
        assert result["execution_controls"][key] is False
    assert result["native_verification"]["output_sha256"] == digest(record["output"])
    assert original == json.dumps(record, sort_keys=True)


@pytest.mark.parametrize("field,value", [
    ("id", "other-task"), ("owner", "Other/Project"), ("provider", "grok"), ("provider", "api"),
    ("status", "queued"), ("status", "outcome_unknown"), ("status", "cancelled"), ("status", "invalid_output"),
    ("status", "failed"), ("result_kind", "final"), ("attempt", None), ("worker", None), ("worker", 7), ("attempt", True), ("revision", 2), ("revision", True),
])
def test_native_crisis_rejects_wrong_identity_or_lifecycle(native_instance, field, value):
    from ai_service.scenarios import ContractError
    task = _native_task(native_instance)
    record = _native_record(task)
    record[field] = value
    with pytest.raises(ContractError):
        ai_audit.verify_crisis_shadow_audit(task, record, task_id="synthetic-task")


@pytest.mark.parametrize("field", ["config_revision", "input_manifest_sha256", "operation_key", "project"])
def test_native_crisis_rejects_changed_request_binding(native_instance, field):
    from ai_service.scenarios import ContractError
    task = _native_task(native_instance)
    record = _native_record(task)
    record["request"]["materials"][0]["scenario_task"][field] = "changed"
    with pytest.raises(ContractError):
        ai_audit.verify_crisis_shadow_audit(task, record, task_id="synthetic-task")


@pytest.mark.parametrize("field,value", [
    ("canonical_route", "trade"), ("suggested_action", "buy"), ("risk_multiplier_suggestion", 2),
    ("kill_switch_active", False), ("execution_controls", {"broker_order_allowed": True}),
    ("mode", "live"), ("status", "ok"), ("confidence", 1.1), ("confidence", float("nan")),
    ("confidence", float("inf")), ("summary", "x" * 601), ("route_assessment", "x" * 97),
    ("key_risks", ["x"] * 6), ("key_risks", ["x" * 161]), ("data_gaps", []),
    ("verdict", "agree"), ("human_review_recommended", False),
])
def test_native_crisis_rejects_output_overreach_and_sparse_evidence_claims(native_instance, field, value):
    from ai_service.scenarios import ContractError
    task = _native_task(native_instance)
    record = _native_record(task)
    record["output"][field] = value
    with pytest.raises(ContractError):
        ai_audit.verify_crisis_shadow_audit(task, record, task_id="synthetic-task")


def _report_cli_context(tmp_path, native_instance):
    import hashlib
    import importlib.util
    module_spec = importlib.util.spec_from_file_location(
        "audit_crisis_shadow_report", Path(__file__).parents[1] / "scripts/audit_crisis_shadow_report.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    report = tmp_path / "frozen.json"
    report.write_text(json.dumps({"profile": "synthetic", "canonical_route": "no_action",
                                  "suggested_action": "watch_only"}))
    instance = tmp_path / "instance.json"
    instance.write_text(json.dumps(native_instance))
    directory = tmp_path / "audit"
    args = ["--enabled", "--instance", str(instance), "--report", str(report),
            "--source-ref", "synthetic.frozen-report", "--source-revision", "b" * 40,
            "--source-sha256", hashlib.sha256(report.read_bytes()).hexdigest(),
            "--occurrence", "synthetic.report-1", "--submitted-at", "2099-01-01T00:00:00Z",
            "--audit-dir", str(directory)]
    return module, args, report, instance, directory


def _native_transport(directory, *, unknown=False, overreach=False):
    from ai_service.client import TaskClient
    calls = []
    class SyntheticTransport:
        def request(self, url, *, method, headers, body=b""):
            calls.append((method, url))
            assert url.startswith("https://quant.invalid/v1/tasks")
            if method == "POST":
                intent_path, = directory.glob("*.intent.json")
                assert intent_path.stat().st_mode & 0o777 == 0o600
                intent = json.loads(intent_path.read_text())
                assert headers["Idempotency-Key"] == intent["operation_key"]
                assert json.loads(body) == intent["request"]
                self.task = types.SimpleNamespace(spec=intent["spec"], request=intent["request"])
                if unknown:
                    raise TimeoutError("synthetic unknown submission")
                result = {"id": "synthetic-task", "status": "queued"}
            else:
                assert url == "https://quant.invalid/v1/tasks/synthetic-task"
                result = _native_record(self.task)
                if overreach:
                    result["output"]["execution_controls"] = {"broker_order_allowed": True}
            return types.SimpleNamespace(status=200, body=json.dumps(result).encode())
    return TaskClient("https://quant.invalid", "synthetic", transport=SyntheticTransport()), calls


def test_native_cli_synthetic_transport_submit_and_readback(tmp_path, native_instance, capsys):
    module, args, report, instance, directory = _report_cli_context(tmp_path, native_instance)
    client, calls = _native_transport(directory)
    before = report.read_bytes(), instance.read_bytes()
    assert module.main(["dry-run", *args], client=client) == 0
    assert calls == [] and not directory.exists()
    assert module.main(["submit", *args], client=client) == 0
    assert module.main(["verify", *args], client=client) == 0
    assert [method for method, _ in calls] == ["POST", "GET"]
    advisory, = directory.glob("*.advisory.json")
    assert json.loads(advisory.read_text())["status"] == "advisory"
    assert before == (report.read_bytes(), instance.read_bytes())
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir())
    assert str(tmp_path) not in capsys.readouterr().out
    assert module.main(["submit", *args], client=client) == 1
    assert len(calls) == 2


def test_native_cli_unknown_submission_retains_intent_and_never_resubmits(tmp_path, native_instance, capsys):
    module, args, _, _, directory = _report_cli_context(tmp_path, native_instance)
    client, calls = _native_transport(directory, unknown=True)
    assert module.main(["submit", *args], client=client) == 1
    intent, = directory.glob("*.intent.json")
    frozen = intent.read_bytes()
    assert module.main(["submit", *args], client=client) == 1
    assert module.main(["verify", *args], client=client) == 1
    assert [method for method, _ in calls] == ["POST"]
    assert frozen == intent.read_bytes()
    responses = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(response["status"] == "unverified" for response in responses)
    assert not list(directory.glob("*.submitted.json"))
    assert not list(directory.glob("*.advisory.json"))


@pytest.mark.parametrize("change", ["report", "instance", "intent", "output"])
def test_native_cli_rejects_changed_context_and_output(tmp_path, native_instance, change):
    module, args, report, instance, directory = _report_cli_context(tmp_path, native_instance)
    client, calls = _native_transport(directory, overreach=change == "output")
    assert module.main(["submit", *args], client=client) == 0
    if change == "report":
        report.write_text(report.read_text() + " ")
    elif change == "instance":
        config = json.loads(instance.read_text())
        config["config_revision"] = "d" * 40
        instance.write_text(json.dumps(config))
    elif change == "intent":
        intent, = directory.glob("*.intent.json")
        value = json.loads(intent.read_text())
        value["request_sha256"] = "d" * 64
        intent.write_text(json.dumps(value))
    assert module.main(["verify", *args], client=client) == 1
    assert [method for method, _ in calls] == (["POST", "GET"] if change == "output" else ["POST"])
    assert not list(directory.glob("*.advisory.json"))


def test_native_cli_default_disabled_without_sdk_or_client(tmp_path, monkeypatch, native_instance):
    module, _, _, _, _ = _report_cli_context(tmp_path, native_instance)
    monkeypatch.setitem(sys.modules, "ai_service.scenarios", None)
    assert module.main([]) == 0


def test_native_cli_audit_directory_cannot_contain_inputs(tmp_path, native_instance):
    module, args, _, _, directory = _report_cli_context(tmp_path, native_instance)
    client, calls = _native_transport(directory)
    args[-1] = str(tmp_path)
    assert module.main(["submit", *args], client=client) == 1
    assert calls == []
    assert not list(tmp_path.glob("*.intent.json"))


def test_native_crisis_complete_evidence_positive_remains_advisory(native_instance):
    from copy import deepcopy
    source = {
        "as_of": "2099-01-01", "canonical_route": "no_action", "suggested_action": "watch_only",
        "would_trade_if_enabled": False, "watch_label": "synthetic", "price_scanner_active": False,
        "bubble_fragility_active": False, "kill_switch_active": False, "kill_switch_reason": "",
        "data_freshness": {"status": "fresh"}, "data_quality": {"quality_score": 1.0},
        "evidence": {"financial_context": False, "credit_context": False},
        "audit_summary": {"final_route": "no_action"},
    }
    original = deepcopy(source)
    task = _native_task(native_instance, source)
    record = _native_record(task)
    record["output"].update(verdict="agree", confidence=0.8, summary="The supplied flags match the route.",
                            data_gaps=[], human_review_recommended=False)
    result = ai_audit.verify_crisis_shadow_audit(task, record, task_id="synthetic-task")
    assert result["status"] == "advisory"
    assert result["verdict"] == "agree"
    assert result["deterministic_route"] == "no_action"
    assert source == original
