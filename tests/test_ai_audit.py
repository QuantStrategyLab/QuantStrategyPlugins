from quant_strategy_plugins.ai_audit import _failure_text, _scrub_api_key_from_text, build_ai_audit_endpoints


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
