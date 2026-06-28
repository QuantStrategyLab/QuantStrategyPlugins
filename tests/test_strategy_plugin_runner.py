from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import quant_strategy_plugins.strategy_plugin_runner as strategy_plugin_runner_module
from quant_strategy_plugins.crisis_response_research import ROUTE_TRUE_CRISIS
from quant_strategy_plugins.market_regime_control_plugin import build_market_regime_control_signal
from quant_strategy_plugins.strategy_plugin_runner import (
    EVIDENCE_AUTOMATION_APPROVED,
    EVIDENCE_NOTIFICATION_ONLY,
    GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS,
    PLUGIN_COMPATIBLE_STRATEGIES,
    PLUGIN_CONSUMPTION_POLICY_REGISTRY,
    PLUGIN_CRISIS_RESPONSE_SHADOW,
    PLUGIN_DEPRECATED_SUCCESSORS,
    PLUGIN_MARKET_REGIME_CONTROL,
    PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY,
    PLUGIN_MACRO_RISK_GOVERNOR,
    PLUGIN_PANIC_REVERSAL_SHADOW,
    PLUGIN_SCHEMA_VERSIONS,
    PLUGIN_TACO_REBOUND_SHADOW,
    STRATEGY_PLUGIN_LOG_SCHEMA_VERSION,
    STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION,
    _apply_plugin_contract,
    load_plugin_config,
    main,
    run_configured_plugins,
)

STRATEGY_NAME = "tqqq_growth_income"
SOXL_STRATEGY_NAME = "soxl_soxx_trend_income"
LEFT_SIDE_STRATEGY_NAME = "mega_cap_leader_rotation_top50_balanced"


def _quiet_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=230)
    rows: list[dict[str, object]] = []
    for symbol in ("QQQ", "TQQQ", "SPY"):
        for offset, as_of in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "as_of": as_of,
                    "close": 100.0 + offset * 0.01,
                    "volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def _soxl_quiet_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=230)
    rows: list[dict[str, object]] = []
    for symbol in ("SOXX", "SOXL", "SPY"):
        for offset, as_of in enumerate(dates):
            multiplier = 3.0 if symbol == "SOXL" else 1.0
            rows.append(
                {
                    "symbol": symbol,
                    "as_of": as_of,
                    "close": 100.0 + offset * 0.01 * multiplier,
                    "volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def _soxl_price_rebound_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=230)
    trend = [100.0 + offset * 0.18 for offset in range(220)]
    last = trend[-1]
    tail = [
        last,
        last * 0.96,
        last * 1.01,
        last * 0.97,
        last * 1.02,
        last * 0.98,
        last * 1.03,
        last * 0.99,
        last * 1.04,
        last * 1.08,
    ]
    soxx = pd.Series(trend + tail, index=dates)
    prices = {
        "SOXX": soxx,
        "SOXL": soxx * 3.0,
        "SPY": pd.Series([100.0 + offset * 0.06 for offset in range(len(dates))], index=dates),
        "XLF": pd.Series([100.0 + offset * 0.05 for offset in range(len(dates))], index=dates),
        "HYG": pd.Series(100.0, index=dates),
        "IEF": pd.Series(100.0, index=dates),
        "VIX": pd.Series(18.0, index=dates),
    }
    rows: list[dict[str, object]] = []
    for symbol, series in prices.items():
        for as_of, close in series.items():
            rows.append({"symbol": symbol, "as_of": as_of, "close": close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def _financial_crisis_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2007-01-02", periods=310)
    rows: list[dict[str, object]] = []
    qqq = pd.Series(100.0, index=dates)
    qqq.iloc[245:] = pd.Series(
        [100.0 - idx * (35.0 / (len(dates) - 245 - 1)) for idx in range(len(dates) - 245)],
        index=dates[245:],
    )
    tqqq = pd.Series(100.0, index=dates)
    tqqq.iloc[245:] = pd.Series(
        [100.0 - idx * (70.0 / (len(dates) - 245 - 1)) for idx in range(len(dates) - 245)],
        index=dates[245:],
    )
    xlf = pd.Series(100.0, index=dates)
    xlf.iloc[220:] = pd.Series(
        [100.0 - idx * (55.0 / (len(dates) - 220 - 1)) for idx in range(len(dates) - 220)],
        index=dates[220:],
    )
    hyg = pd.Series(100.0, index=dates)
    hyg.iloc[235:] = pd.Series(
        [100.0 - idx * (18.0 / (len(dates) - 235 - 1)) for idx in range(len(dates) - 235)],
        index=dates[235:],
    )
    prices = {
        "QQQ": qqq,
        "TQQQ": tqqq,
        "SPY": pd.Series(100.0, index=dates),
        "XLF": xlf,
        "HYG": hyg,
        "IEF": pd.Series(100.0, index=dates),
    }
    for symbol, series in prices.items():
        for as_of, close in series.items():
            rows.append({"symbol": symbol, "as_of": as_of, "close": close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def _shadow_plugin_config(tmp_path, *, include_output_dir: bool = True) -> dict[str, object]:
    prices_path = tmp_path / "prices.csv"
    _quiet_prices().to_csv(prices_path, index=False)
    entry: dict[str, object] = {
        "strategy": STRATEGY_NAME,
        "plugin": PLUGIN_CRISIS_RESPONSE_SHADOW,
        "enabled": True,
        "mode": "shadow",
        "inputs": {
            "prices": str(prices_path),
            "as_of": "2025-11-19",
            "start_date": "2025-01-02",
            "financial_symbols": [],
            "credit_pairs": [],
            "rate_symbols": [],
        },
    }
    if include_output_dir:
        entry["outputs"] = {"output_dir": str(tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW)}
    return {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [entry],
    }


def _taco_rebound_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2026-03-20", periods=16)
    qqq_path = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 92.0, 96.0, 99.0]
    tqqq_path = [100.0, 97.0, 94.0, 91.0, 88.0, 85.0, 82.0, 76.0, 88.0, 96.0]
    rows: list[dict[str, object]] = []
    for idx, as_of in enumerate(dates):
        qqq_close = qqq_path[idx] if idx < len(qqq_path) else 104.0 + idx
        tqqq_close = tqqq_path[idx] if idx < len(tqqq_path) else 110.0 + idx * 2.0
        rows.append({"symbol": "QQQ", "as_of": as_of, "close": qqq_close, "volume": 1_000_000})
        rows.append({"symbol": "TQQQ", "as_of": as_of, "close": tqqq_close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def _panic_reversal_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-04-01", periods=12)
    qqq_path = [100.0, 96.0, 92.0, 88.0, 84.0, 82.0, 84.0, 87.0, 90.0, 92.0, 94.0, 96.0]
    tqqq_path = [100.0, 88.0, 78.0, 70.0, 64.0, 60.0, 66.0, 74.0, 82.0, 88.0, 94.0, 100.0]
    vix_path = [20.0, 32.0, 45.0, 54.0, 60.0, 58.0, 55.0, 48.0, 45.0, 42.0, 39.0, 35.0]
    vix3m_path = [22.0, 28.0, 38.0, 45.0, 48.0, 47.0, 45.0, 41.0, 39.0, 37.0, 35.0, 33.0]
    rows: list[dict[str, object]] = []
    for idx, as_of in enumerate(dates):
        rows.append({"symbol": "QQQ", "as_of": as_of, "close": qqq_path[idx], "volume": 1_000_000})
        rows.append({"symbol": "TQQQ", "as_of": as_of, "close": tqqq_path[idx], "volume": 1_000_000})
        rows.append({"symbol": "VIX", "as_of": as_of, "close": vix_path[idx], "volume": 0})
        rows.append({"symbol": "VIX3M", "as_of": as_of, "close": vix3m_path[idx], "volume": 0})
    return pd.DataFrame(rows)


def _macro_stress_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=260)
    rows: list[dict[str, object]] = []
    qqq = pd.Series([100.0 + idx * 0.10 for idx in range(len(dates))], index=dates)
    qqq.iloc[-30:] = pd.Series([125.0 - idx * (45.0 / 29.0) for idx in range(30)], index=dates[-30:])
    vix = pd.Series(15.0, index=dates)
    vix.iloc[-6:] = [24.0, 27.0, 31.0, 34.0, 38.0, 41.0]
    hyg = pd.Series(100.0, index=dates)
    hyg.iloc[-22:] = pd.Series([100.0 - idx * (9.0 / 21.0) for idx in range(22)], index=dates[-22:])
    ief = pd.Series(100.0, index=dates)
    ief.iloc[-22:] = pd.Series([100.0 + idx * (3.0 / 21.0) for idx in range(22)], index=dates[-22:])
    prices = {"QQQ": qqq, "TQQQ": qqq * 3.0, "VIX": vix, "HYG": hyg, "IEF": ief}
    for symbol, series in prices.items():
        for as_of, close in series.items():
            rows.append({"symbol": symbol, "as_of": as_of, "close": close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def test_strategy_plugin_runner_executes_strategy_scoped_shadow_plugin(tmp_path) -> None:
    config = _shadow_plugin_config(tmp_path)
    summary = run_configured_plugins(config)

    assert summary["schema_version"] == "strategy_plugins.v1"
    result = summary["strategy_plugins"][0]
    assert result["strategy"] == STRATEGY_NAME
    assert result["plugin"] == PLUGIN_CRISIS_RESPONSE_SHADOW
    assert result["mode"] == "shadow"
    assert result["effective_mode"] == "shadow"
    assert result["status"] == "ok"

    latest_signal = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW / "latest_signal.json"
    latest_run = tmp_path / "runner" / "latest_run.json"
    assert latest_signal.exists()
    assert latest_run.exists()
    payload = json.loads(latest_signal.read_text(encoding="utf-8"))
    assert payload["strategy"] == STRATEGY_NAME
    assert payload["plugin"] == PLUGIN_CRISIS_RESPONSE_SHADOW
    assert payload["mode"] == "shadow"
    assert payload["configured_mode"] == "shadow"
    assert payload["effective_mode"] == "shadow"
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["notification_profile"] == "shadow_only"
    assert payload["execution_controls"]["repository_broker_write_allowed"] is False
    assert payload["execution_controls"]["repository_allocation_mutation_allowed"] is False
    assert "platform behavior contract" in payload["execution_controls"]["mode_note"]
    assert payload["localized_messages"]["schema_version"] == STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION
    assert "No notification required" in payload["localized_messages"]["notification"]["en-US"]
    assert "无需通知" in payload["localized_messages"]["notification"]["zh-CN"]
    assert payload["log_record"]["schema_version"] == STRATEGY_PLUGIN_LOG_SCHEMA_VERSION
    assert "策略=" in payload["log_record"]["localized_messages"]["zh-CN"]


def test_strategy_plugin_runner_runs_macro_risk_governor_for_tqqq(tmp_path) -> None:
    prices_path = tmp_path / "macro_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_MACRO_RISK_GOVERNOR
    _macro_stress_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_MACRO_RISK_GOVERNOR,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-12-31",
                    "vix_symbols": ["VIX"],
                    "credit_pairs": ["HYG:IEF"],
                    "crisis_score_threshold": 99.0,
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == STRATEGY_NAME
    assert result["plugin"] == PLUGIN_MACRO_RISK_GOVERNOR
    assert result["status"] == "ok"
    assert "route=delever action=delever" in result["message"]
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["strategy"] == STRATEGY_NAME
    assert payload["plugin"] == PLUGIN_MACRO_RISK_GOVERNOR
    assert payload["canonical_route"] == "delever"
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["localized_messages"]["labels"]["canonical_route"]["zh-CN"] == "降杠杆"
    assert payload["localized_messages"]["labels"]["suggested_action"]["en-US"] == "De-lever"
    assert "VIX 危机水平" in payload["localized_messages"]["notification"]["zh-CN"]


def test_strategy_plugin_runner_keeps_external_stress_watch_only_unless_opted_in(tmp_path) -> None:
    prices_path = tmp_path / "macro_prices.csv"
    external_path = tmp_path / "external_context.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_MACRO_RISK_GOVERNOR
    _quiet_prices().to_csv(prices_path, index=False)
    pd.DataFrame(
        [
            {
                "as_of": "2025-11-19",
                "hy_oas": 8.0,
                "hy_oas_delta_63d": 2.0,
                "financial_stress": 2.0,
            }
        ]
    ).to_csv(external_path, index=False)
    base_inputs = {
        "prices": str(prices_path),
        "external_context": str(external_path),
        "as_of": "2025-11-19",
        "vix_symbols": ["VIX"],
        "credit_pairs": [],
        "watch_score_threshold": 1.0,
        "delever_score_threshold": 1.0,
        "crisis_score_threshold": 99.0,
    }
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_MACRO_RISK_GOVERNOR,
                "enabled": True,
                "inputs": base_inputs,
                "outputs": {"output_dir": str(output_dir / "watch_only")},
            },
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_MACRO_RISK_GOVERNOR,
                "enabled": True,
                "inputs": {**base_inputs, "external_stress_actionable": True},
                "outputs": {"output_dir": str(output_dir / "actionable")},
            },
        ],
    }

    summary = run_configured_plugins(config)

    assert [result["status"] for result in summary["strategy_plugins"]] == ["ok", "ok"]
    watch_payload = json.loads((output_dir / "watch_only" / "latest_signal.json").read_text(encoding="utf-8"))
    actionable_payload = json.loads((output_dir / "actionable" / "latest_signal.json").read_text(encoding="utf-8"))
    assert watch_payload["canonical_route"] == "watch"
    assert watch_payload["actionable_score"] == 0.0
    assert actionable_payload["canonical_route"] == "delever"
    assert actionable_payload["actionable_score"] == 5.0


def test_strategy_plugin_runner_runs_unified_market_regime_control_for_tqqq(tmp_path) -> None:
    prices_path = tmp_path / "market_regime_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_MARKET_REGIME_CONTROL
    _macro_stress_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_MARKET_REGIME_CONTROL,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-12-31",
                    "vix_symbols": ["VIX"],
                    "credit_pairs": ["HYG:IEF"],
                    "crisis_enabled": False,
                    "taco_enabled": False,
                    "crisis_score_threshold": 99.0,
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == STRATEGY_NAME
    assert result["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert result["status"] == "ok"
    assert "route=risk_reduced action=delever" in result["message"]
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["strategy"] == STRATEGY_NAME
    assert payload["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert payload["canonical_route"] == "risk_reduced"
    assert payload["position_control"]["leverage_scalar"] == 0.50
    assert payload["position_control"]["risk_asset_scalar"] == 0.50
    assert payload["position_control"]["taco_allowed"] is False
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["schema_version"] == "volatility_delever_context.v1"
    assert volatility_delever_context["soft_risk"] is True
    assert (
        volatility_delever_context["retention_profiles"]["tqqq_step_softzero_0.25_0.50"]["retention_ratio"]
        == 0.0
    )
    assert volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]["retention_ratio"] == 0.0
    assert (
        volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"][
            "retention_ratio"
        ]
        == 0.0
    )
    assert payload["execution_controls"]["strategy_runtime_metadata_allowed"] is True
    assert payload["execution_controls"]["position_control_allowed"] is True
    assert payload["execution_controls"]["capital_impact"] == "strategy_opt_in"
    assert payload["execution_controls"]["position_control_shadow_only"] is False
    assert payload["execution_controls"]["consumption_evidence_status"] == EVIDENCE_AUTOMATION_APPROVED
    assert payload["consumption_policy"]["position_control_allowed"] is True
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["localized_messages"]["labels"]["canonical_route"]["en-US"] == "Risk reduced"
    assert payload["localized_messages"]["labels"]["plugin"]["zh-CN"] == "市场状态控制"
    assert payload["localized_messages"]["labels"]["suggested_action"]["zh-CN"] == "降杠杆"
    assert payload["notification"]["localized_message_schema_version"] == STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION
    zh_notification = payload["notification"]["localized_messages"]["zh-CN"]
    assert "市场状态控制" in zh_notification
    assert "风险降低" in zh_notification
    assert "market_regime_control" not in zh_notification
    assert "risk_reduced" not in zh_notification
    assert "delever" not in zh_notification
    assert "宏观：VIX 危机水平" in payload["notification"]["localized_reason_labels"]["zh-CN"]
    assert payload["log_record"]["canonical_route"] == "risk_reduced"
    zh_log = payload["log_record"]["localized_messages"]["zh-CN"]
    assert "插件=市场状态控制" in zh_log
    assert "路线=风险降低" in zh_log
    assert "动作=降杠杆" in zh_log
    assert "market_regime_control" not in zh_log
    assert "risk_reduced" not in zh_log
    assert "delever" not in zh_log
    assert "原因码=" not in zh_log
    assert "macro:vix_crisis_level" not in zh_log


def test_strategy_plugin_runner_localizes_watch_route_reason_fallback() -> None:
    payload = _apply_plugin_contract(
        {
            "as_of": "2026-06-16",
            "canonical_route": "watch",
            "suggested_action": "watch_only",
            "notification": {"should_notify": True},
        },
        strategy=SOXL_STRATEGY_NAME,
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        mode="shadow",
    )

    assert payload["notification"]["localized_reason_labels"]["zh-CN"] == ["观察状态"]
    assert payload["notification"]["localized_reason_labels"]["en-US"] == ["Watch state"]
    zh_notification = payload["notification"]["localized_messages"]["zh-CN"]
    zh_log = payload["log_record"]["localized_messages"]["zh-CN"]
    assert "原因：观察状态" in zh_notification
    assert "原因=观察状态" in zh_log
    assert "watch" not in zh_notification
    assert "watch" not in zh_log


def test_strategy_plugin_runner_can_enable_panic_reversal_inside_market_regime_control(tmp_path) -> None:
    prices_path = tmp_path / "market_regime_panic_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_MARKET_REGIME_CONTROL
    _panic_reversal_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_MARKET_REGIME_CONTROL,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-04-10",
                    "start_date": "2025-04-01",
                    "crisis_enabled": False,
                    "macro_enabled": False,
                    "taco_enabled": False,
                    "panic_reversal_enabled": True,
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    assert summary["strategy_plugins"][0]["status"] == "ok"
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["canonical_route"] == "opportunity_watch"
    assert payload["position_control"]["panic_reversal_allowed"] is True
    assert payload["position_control"]["panic_reversal_size_scalar"] == 0.0
    assert payload["position_control"]["taco_allowed"] is False
    assert "panic_reversal:panic_reversal" in payload["position_control"]["reason_codes"]
    zh_notification = payload["notification"]["localized_messages"]["zh-CN"]
    assert "【机会复核｜TQQQ｜VIX 恐慌反转】" in zh_notification
    assert "情况说明：" in zh_notification
    assert "VIX 已从极端恐慌高位回落" in zh_notification
    assert "QQQ/TQQQ 已从短期低点反弹" in zh_notification
    assert "建议操作：" in zh_notification
    assert "检查 VIX 是否继续回落" in zh_notification
    assert "VIX 曾达到恐慌区间" in zh_notification
    assert "VIX 已从高点回落" in zh_notification
    assert "QQQ 3 日收益" in zh_notification
    assert "执行权限" not in zh_notification
    assert "仓位权限" not in zh_notification
    assert "panic_reversal_size_scalar" not in zh_notification


def test_market_regime_control_defaults_panic_crisis_suppression_to_arbiter(monkeypatch) -> None:
    captured: list[bool | None] = []

    def fake_build_panic_payload(_price_history: pd.DataFrame, plugin_config: dict[str, object]) -> dict[str, object]:
        captured.append(plugin_config.get("suppress_when_price_crisis_guard_active"))
        return {
            "profile": "panic_reversal_shadow",
            "as_of": "2025-04-09",
            "canonical_route": "panic_reversal",
            "suggested_action": "notify_manual_review",
            "manual_review_required": True,
            "panic_reversal_context_active": True,
            "reason_codes": ["panic_reversal"],
        }

    monkeypatch.setattr(strategy_plugin_runner_module, "_build_panic_reversal_payload", fake_build_panic_payload)

    payload = strategy_plugin_runner_module._build_market_regime_control_payload(
        pd.DataFrame(),
        {
            "crisis_enabled": False,
            "macro_enabled": False,
            "taco_enabled": False,
            "panic_reversal_enabled": True,
        },
    )
    explicit_payload = strategy_plugin_runner_module._build_market_regime_control_payload(
        pd.DataFrame(),
        {
            "crisis_enabled": False,
            "macro_enabled": False,
            "taco_enabled": False,
            "panic_reversal_enabled": True,
            "suppress_when_price_crisis_guard_active": True,
        },
    )

    assert captured == [False, True]
    assert payload["canonical_route"] == "opportunity_watch"
    assert explicit_payload["canonical_route"] == "opportunity_watch"


def test_market_regime_control_notification_surfaces_vetoed_panic_reversal() -> None:
    payload = build_market_regime_control_signal(
        {
            "macro": {
                "profile": "macro_risk_governor",
                "as_of": "2025-04-09",
                "canonical_route": "delever",
                "suggested_action": "delever",
                "leverage_scalar": 0.0,
                "risk_asset_scalar": 1.0,
                "reason_codes": ["vix_crisis_level"],
            },
            "panic_reversal": {
                "profile": "panic_reversal_shadow",
                "as_of": "2025-04-09",
                "canonical_route": "panic_reversal",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "panic_reversal_context_active": True,
                "reason_codes": ["panic_reversal", "vix_panic_reversal", "price_rebound_confirmation"],
                "metrics": {
                    "benchmark_symbol": "QQQ",
                    "attack_symbol": "TQQQ",
                    "vix": 33.62,
                    "vix_previous": 52.33,
                    "vix_lookback_high": 52.33,
                    "vix_pullback_from_high": 0.3575,
                    "vix_vix3m_ratio": 1.1237,
                    "benchmark_3d_return": 0.1025,
                    "benchmark_rebound_from_recent_low": 0.1200,
                    "attack_rebound_from_recent_low": 0.3524,
                },
                "reversal_confirmation": {
                    "confirmed": True,
                    "thresholds": {
                        "vix_high_lookback_days": 5,
                        "min_vix_high": 50.0,
                    },
                },
            },
        }
    )
    contracted = _apply_plugin_contract(
        payload,
        strategy=STRATEGY_NAME,
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        mode="shadow",
    )

    assert contracted["canonical_route"] == "risk_reduced"
    assert contracted["position_control"]["panic_reversal_allowed"] is False
    assert contracted["notification"]["opportunity_vetoed_should_notify"] is True
    zh_notification = contracted["notification"]["localized_messages"]["zh-CN"]
    assert "【机会被拦截｜TQQQ｜VIX 恐慌反转】" in zh_notification
    assert "情况说明：" in zh_notification
    assert "VIX 已从极端恐慌高位回落" in zh_notification
    assert "但当前仍处于降风险状态，说明策略环境还没有完全解除防守" in zh_notification
    assert "宏观降风险信号优先于 VIX 恐慌反转，所以这条通知先作为人工检查线索" in zh_notification
    assert "建议操作：" in zh_notification
    assert "避免把一次反抽误判为趋势恢复" in zh_notification
    assert "TQQQ 从近 5 日低点反弹 +35.2%" in zh_notification
    assert "market_regime_control" not in zh_notification
    assert "veto" not in zh_notification
    assert "macro_delever_blocks_panic_reversal" not in zh_notification
    assert "执行权限" not in zh_notification
    assert "仓位权限" not in zh_notification


def test_strategy_plugin_runner_runs_general_market_regime_notification(tmp_path) -> None:
    prices_path = tmp_path / "market_regime_prices.csv"
    output_dir = tmp_path / GENERAL_MARKET_REGIME_NOTIFICATION_TARGET / "plugins" / PLUGIN_MARKET_REGIME_CONTROL
    _soxl_quiet_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "notification_targets": [
            {
                "notification_target": GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
                "plugin": PLUGIN_MARKET_REGIME_CONTROL,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-11-19",
                    "benchmark_symbol": "SOXX",
                    "attack_symbol": "SOXL",
                    "crisis_enabled": False,
                    "macro_enabled": False,
                    "taco_enabled": False,
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    assert summary["strategy_plugins"] == []
    result = summary["notification_targets"][0]
    assert result["strategy"] == ""
    assert result["target_type"] == "notification_target"
    assert result["notification_target"] == GENERAL_MARKET_REGIME_NOTIFICATION_TARGET
    assert result["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert result["status"] == "ok"
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert "strategy" not in payload
    assert payload["target_type"] == "notification_target"
    assert payload["notification_target"] == GENERAL_MARKET_REGIME_NOTIFICATION_TARGET
    assert payload["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert payload["schema_version"] in PLUGIN_SCHEMA_VERSIONS[PLUGIN_MARKET_REGIME_CONTROL]
    assert payload["canonical_route"] == "no_action"
    assert payload["execution_controls"]["capital_impact"] == "notification_only"
    assert payload["execution_controls"]["strategy_runtime_metadata_allowed"] is False
    assert payload["execution_controls"]["position_control_allowed"] is False
    assert payload["execution_controls"]["consumption_evidence_status"] == EVIDENCE_NOTIFICATION_ONLY
    assert "manual_review_notification_delegated" not in payload["execution_controls"]
    assert payload["notification_target_policy"]["notification_target"] == GENERAL_MARKET_REGIME_NOTIFICATION_TARGET
    assert payload["notification"]["localized_messages"]["en-US"].startswith("No notification required")
    assert "notification target" in payload["notification"]["localized_messages"]["en-US"]
    assert payload["log_record"]["localized_messages"]["zh-CN"]


def test_strategy_plugin_runner_runs_unified_market_regime_control_for_soxl(tmp_path) -> None:
    prices_path = tmp_path / "market_regime_prices.csv"
    output_dir = tmp_path / SOXL_STRATEGY_NAME / "plugins" / PLUGIN_MARKET_REGIME_CONTROL
    _soxl_quiet_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": SOXL_STRATEGY_NAME,
                "plugin": PLUGIN_MARKET_REGIME_CONTROL,
                "enabled": True,
                "inputs": {"prices": str(prices_path), "benchmark_symbol": "SOXX", "attack_symbol": "SOXL"},
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == SOXL_STRATEGY_NAME
    assert result["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert result["status"] == "ok"
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["strategy"] == SOXL_STRATEGY_NAME
    assert payload["execution_controls"]["position_control_allowed"] is True
    assert payload["execution_controls"]["strategy_runtime_metadata_allowed"] is True
    assert payload["execution_controls"]["capital_impact"] == "strategy_opt_in"
    assert payload["execution_controls"]["position_control_shadow_only"] is False
    assert payload["execution_controls"]["manual_review_notification_delegated"] is True
    assert (
        payload["execution_controls"]["manual_review_notification_target"]
        == GENERAL_MARKET_REGIME_NOTIFICATION_TARGET
    )
    assert (
        payload["execution_controls"]["manual_review_notification_delegate"]
        == f"notification_target:{GENERAL_MARKET_REGIME_NOTIFICATION_TARGET}"
    )
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["actionable_for_position_control"] is True
    assert volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]["retention_ratio"] == 0.0


def test_strategy_plugin_runner_marks_pending_strategy_mount_notification_only(tmp_path) -> None:
    prices_path = tmp_path / "market_regime_prices.csv"
    output_dir = tmp_path / "global_etf_rotation" / "plugins" / PLUGIN_MARKET_REGIME_CONTROL
    _quiet_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": "global_etf_rotation",
                "plugin": PLUGIN_MARKET_REGIME_CONTROL,
                "enabled": True,
                "inputs": {"prices": str(prices_path), "benchmark_symbol": "QQQ", "attack_symbol": "TQQQ"},
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == "global_etf_rotation"
    assert result["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert result["status"] == "ok"
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["strategy"] == "global_etf_rotation"
    assert payload["execution_controls"]["notification_allowed"] is True
    assert payload["execution_controls"]["position_control_allowed"] is False
    assert payload["execution_controls"]["consumption_evidence_status"] == EVIDENCE_NOTIFICATION_ONLY
    assert payload["execution_controls"]["capital_impact"] == "notification_only"
    assert payload["execution_controls"]["strategy_runtime_metadata_allowed"] is False
    assert payload["execution_controls"]["position_control_shadow_only"] is True
    assert payload["consumption_policy"]["position_control_allowed"] is False


def test_strategy_plugin_runner_adds_soxl_price_rebound_retention_context(tmp_path) -> None:
    prices_path = tmp_path / "market_regime_soxl_rebound_prices.csv"
    output_dir = tmp_path / SOXL_STRATEGY_NAME / "plugins" / PLUGIN_MARKET_REGIME_CONTROL
    prices = _soxl_price_rebound_prices()
    prices.to_csv(prices_path, index=False)
    as_of = pd.Timestamp(prices["as_of"].max()).date().isoformat()
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": SOXL_STRATEGY_NAME,
                "plugin": PLUGIN_MARKET_REGIME_CONTROL,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": as_of,
                    "benchmark_symbol": "SOXX",
                    "attack_symbol": "SOXL",
                    "vix_symbols": ["VIX"],
                    "credit_pairs": ["HYG:IEF"],
                    "financial_symbols": ["XLF"],
                    "crisis_enabled": False,
                    "macro_enabled": False,
                    "taco_enabled": False,
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    assert summary["strategy_plugins"][0]["status"] == "ok"
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["canonical_route"] == "no_action"
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["rebound_sources"] == ["price_rebound"]
    price_context = volatility_delever_context["price_rebound_context"]
    assert price_context["confirmed"] is True
    assert price_context["volatility_triggered"] is True
    assert price_context["hard_filter"] is False
    assert price_context["soft_filter"] is False
    soxl_profile = volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]
    assert soxl_profile["retention_ratio"] == 0.5
    assert soxl_profile["reason_codes"] == ["constructive", "price_rebound_confirm"]
    softzero_profile = volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"]
    assert softzero_profile["retention_ratio"] == 0.5
    assert softzero_profile["reason_codes"] == ["constructive", "price_rebound_confirm"]


def test_strategy_plugin_runner_contract_registry_prefers_unified_plugin() -> None:
    assert set(PLUGIN_COMPATIBLE_STRATEGIES[PLUGIN_MARKET_REGIME_CONTROL]) == {
        STRATEGY_NAME,
        SOXL_STRATEGY_NAME,
        "global_etf_rotation",
        "russell_1000_multi_factor_defensive",
        "mega_cap_leader_rotation_top50_balanced",
    }
    assert set(PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS[PLUGIN_MARKET_REGIME_CONTROL]) == {
        GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    }
    assert PLUGIN_COMPATIBLE_STRATEGIES[PLUGIN_PANIC_REVERSAL_SHADOW] == (STRATEGY_NAME,)
    assert PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS[PLUGIN_PANIC_REVERSAL_SHADOW] == (
        GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    )
    assert PLUGIN_SCHEMA_VERSIONS[PLUGIN_MARKET_REGIME_CONTROL] == ("market_regime_control.v1",)
    assert PLUGIN_SCHEMA_VERSIONS[PLUGIN_PANIC_REVERSAL_SHADOW] == ("panic_reversal_shadow.v1",)
    assert PLUGIN_DEPRECATED_SUCCESSORS[PLUGIN_CRISIS_RESPONSE_SHADOW] == PLUGIN_MARKET_REGIME_CONTROL
    assert PLUGIN_DEPRECATED_SUCCESSORS[PLUGIN_MACRO_RISK_GOVERNOR] == PLUGIN_MARKET_REGIME_CONTROL
    assert PLUGIN_DEPRECATED_SUCCESSORS[PLUGIN_TACO_REBOUND_SHADOW] == PLUGIN_MARKET_REGIME_CONTROL
    assert (
        PLUGIN_MARKET_REGIME_CONTROL,
        SOXL_STRATEGY_NAME,
    ) in PLUGIN_CONSUMPTION_POLICY_REGISTRY
    assert (
        PLUGIN_PANIC_REVERSAL_SHADOW,
        SOXL_STRATEGY_NAME,
    ) not in PLUGIN_CONSUMPTION_POLICY_REGISTRY
    assert PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY[
        (PLUGIN_MARKET_REGIME_CONTROL, GENERAL_MARKET_REGIME_NOTIFICATION_TARGET)
    ].position_control_allowed is False
    assert PLUGIN_CONSUMPTION_POLICY_REGISTRY[
        (PLUGIN_MARKET_REGIME_CONTROL, STRATEGY_NAME)
    ].position_control_allowed is True
    assert PLUGIN_CONSUMPTION_POLICY_REGISTRY[
        (PLUGIN_MARKET_REGIME_CONTROL, SOXL_STRATEGY_NAME)
    ].position_control_allowed is True
    for pending_strategy in (
        "global_etf_rotation",
        "russell_1000_multi_factor_defensive",
        "mega_cap_leader_rotation_top50_balanced",
    ):
        policy = PLUGIN_CONSUMPTION_POLICY_REGISTRY[(PLUGIN_MARKET_REGIME_CONTROL, pending_strategy)]
        assert policy.notification_allowed is True
        assert policy.position_control_allowed is False
        assert policy.evidence_status == EVIDENCE_NOTIFICATION_ONLY


def test_strategy_plugin_runner_rehearses_triggered_shadow_artifact_without_execution_permissions(tmp_path) -> None:
    prices = _financial_crisis_prices()
    prices_path = tmp_path / "crisis_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW
    as_of = str(pd.to_datetime(prices["as_of"]).max().date())
    prices.to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_CRISIS_RESPONSE_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": as_of,
                    "start_date": "2007-01-02",
                    "financial_symbols": ["XLF"],
                    "credit_pairs": ["HYG:IEF"],
                    "rate_symbols": [],
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["status"] == "ok"
    assert result["message"] == f"route={ROUTE_TRUE_CRISIS} action=defend"
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["canonical_route"] == ROUTE_TRUE_CRISIS
    assert payload["suggested_action"] == "defend"
    assert payload["would_trade_if_enabled"] is True
    assert payload["price_scanner_active"] is True
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["repository_broker_write_allowed"] is False
    assert payload["execution_controls"]["repository_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["position_control_allowed"] is False
    assert payload["execution_controls"]["capital_impact"] == "notification_only"
    assert payload["execution_controls"]["strategy_runtime_metadata_allowed"] is False
    assert payload["execution_controls"]["position_control_shadow_only"] is True


def test_strategy_plugin_runner_can_enable_ai_audit_without_api_key(tmp_path, monkeypatch) -> None:
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
    config = _shadow_plugin_config(tmp_path)
    config["strategy_plugins"][0]["inputs"]["ai_audit_enabled"] = True
    config["strategy_plugins"][0]["inputs"]["ai_audit_codex_enabled"] = False
    config["strategy_plugins"][0]["inputs"]["ai_audit_model"] = "gpt-5.4-mini"

    summary = run_configured_plugins(config)

    output_dir = Path(summary["strategy_plugins"][0]["output_dir"])
    payload = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert payload["canonical_route"] == "no_action"
    assert payload["ai_audit"]["status"] == "skipped"
    assert payload["ai_audit"]["skip_reason"] == "missing_api_endpoint"
    assert payload["execution_controls"]["ai_audit_shadow_only"] is True


def test_strategy_plugin_runner_defaults_output_under_strategy_plugin_scope(tmp_path, monkeypatch) -> None:
    config = _shadow_plugin_config(tmp_path, include_output_dir=False)
    monkeypatch.chdir(tmp_path)

    summary = run_configured_plugins(config)

    expected = tmp_path / "data" / "output" / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW
    assert summary["strategy_plugins"][0]["output_dir"] == str(
        Path("data/output") / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW
    )
    assert (expected / "latest_signal.json").exists()


def test_strategy_plugin_runner_can_skip_disabled_strategy_plugin(tmp_path) -> None:
    config = _shadow_plugin_config(tmp_path)
    config["strategy_plugins"][0]["enabled"] = False

    summary = run_configured_plugins(config, selected_plugins=[PLUGIN_CRISIS_RESPONSE_SHADOW])

    assert summary["strategy_plugins"][0]["strategy"] == STRATEGY_NAME
    assert summary["strategy_plugins"][0]["status"] == "skipped"
    assert summary["strategy_plugins"][0]["effective_mode"] is None
    assert not (tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW / "latest_signal.json").exists()


def test_strategy_plugin_runner_uses_default_mode_when_entry_mode_is_omitted(tmp_path) -> None:
    config = _shadow_plugin_config(tmp_path)
    del config["strategy_plugins"][0]["mode"]

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["mode"] == "shadow"
    assert result["effective_mode"] == "shadow"
    latest_signal = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW / "latest_signal.json"
    payload = json.loads(latest_signal.read_text(encoding="utf-8"))
    assert payload["strategy"] == STRATEGY_NAME
    assert payload["plugin"] == PLUGIN_CRISIS_RESPONSE_SHADOW
    assert payload["configured_mode"] == "shadow"
    assert payload["execution_controls"]["notification_profile"] == "shadow_only"


def test_strategy_plugin_runner_rejects_crisis_shadow_soxl_strategy_mount(tmp_path) -> None:
    prices_path = tmp_path / "soxl_prices.csv"
    _soxl_quiet_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": SOXL_STRATEGY_NAME,
                "plugin": PLUGIN_CRISIS_RESPONSE_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-11-19",
                    "start_date": "2025-01-02",
                    "benchmark_symbol": "SOXX",
                    "attack_symbol": "SOXL",
                    "financial_symbols": [],
                    "credit_pairs": [],
                    "rate_symbols": [],
                },
            }
        ],
    }

    with pytest.raises(ValueError, match="strategy-limited"):
        run_configured_plugins(config)


def test_strategy_plugin_runner_filters_by_strategy(tmp_path) -> None:
    config = _shadow_plugin_config(tmp_path)
    config["strategy_plugins"].append(
        {
            **config["strategy_plugins"][0],
            "strategy": "soxl_growth_income",
            "outputs": {"output_dir": str(tmp_path / "soxl_growth_income" / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW)},
        }
    )

    summary = run_configured_plugins(config, selected_strategies=[STRATEGY_NAME])

    assert [result["strategy"] for result in summary["strategy_plugins"]] == [STRATEGY_NAME]
    assert (tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW / "latest_signal.json").exists()
    assert not (
        tmp_path / "soxl_growth_income" / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW / "latest_signal.json"
    ).exists()


def test_strategy_plugin_runner_runs_taco_rebound_notification_mount_for_tqqq(tmp_path) -> None:
    prices_path = tmp_path / "taco_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_TACO_REBOUND_SHADOW
    _taco_rebound_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_TACO_REBOUND_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "event_set": "geopolitical-deescalation",
                    "as_of": "2026-04-02",
                    "start_date": "2026-03-20",
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == STRATEGY_NAME
    assert result["plugin"] == PLUGIN_TACO_REBOUND_SHADOW
    assert result["status"] == "ok"
    assert "route=taco_rebound action=notify_manual_review" in result["message"]
    latest = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert latest["manual_review_required"] is True
    assert latest["rebound_confirmation"]["confirmed"] is True
    assert latest["would_trade_if_enabled"] is False
    assert "sleeve_suggestion" not in latest
    zh_notification = latest["localized_messages"]["notification"]["zh-CN"]
    assert "【机会复核｜TQQQ｜TACO 事件反弹】" in zh_notification
    assert "情况说明：" in zh_notification
    assert "事件缓和后，QQQ/TQQQ 出现反弹确认" in zh_notification
    assert "事件：" in zh_notification
    assert "价格确认：" in zh_notification
    assert "建议操作：" in zh_notification


def test_strategy_plugin_runner_can_enable_taco_ai_audit_without_api_key(tmp_path, monkeypatch) -> None:
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

    prices_path = tmp_path / "taco_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_TACO_REBOUND_SHADOW
    _taco_rebound_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_TACO_REBOUND_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "event_set": "geopolitical-deescalation",
                    "as_of": "2026-04-02",
                    "start_date": "2026-03-20",
                    "ai_audit_enabled": True,
                    "ai_audit_codex_enabled": False,
                    "ai_audit_model": "gpt-5.4-mini",
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    assert summary["strategy_plugins"][0]["status"] == "ok"
    latest = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert latest["canonical_route"] == "taco_rebound"
    assert latest["ai_audit"]["status"] == "skipped"
    assert latest["ai_audit"]["skip_reason"] == "missing_api_endpoint"
    assert latest["execution_controls"]["ai_audit_shadow_only"] is True


def test_strategy_plugin_runner_rejects_taco_rebound_for_non_tqqq_strategy(tmp_path) -> None:
    prices_path = tmp_path / "taco_prices.csv"
    output_dir = tmp_path / LEFT_SIDE_STRATEGY_NAME / "plugins" / PLUGIN_TACO_REBOUND_SHADOW
    _taco_rebound_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": LEFT_SIDE_STRATEGY_NAME,
                "plugin": PLUGIN_TACO_REBOUND_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "event_set": "geopolitical-deescalation",
                    "as_of": "2026-04-02",
                    "start_date": "2026-03-20",
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    with pytest.raises(ValueError, match="strategy-limited"):
        run_configured_plugins(config)


def test_strategy_plugin_runner_runs_panic_reversal_notification_mount_for_tqqq(tmp_path) -> None:
    prices_path = tmp_path / "panic_prices.csv"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_PANIC_REVERSAL_SHADOW
    _panic_reversal_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": STRATEGY_NAME,
                "plugin": PLUGIN_PANIC_REVERSAL_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-04-10",
                    "start_date": "2025-04-01",
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == STRATEGY_NAME
    assert result["plugin"] == PLUGIN_PANIC_REVERSAL_SHADOW
    assert result["status"] == "ok"
    assert "route=panic_reversal action=notify_manual_review" in result["message"]
    latest = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert latest["manual_review_required"] is True
    assert latest["would_trade_if_enabled"] is False
    assert latest["execution_controls"]["position_control_allowed"] is False
    assert latest["execution_controls"]["consumption_evidence_status"] == EVIDENCE_NOTIFICATION_ONLY
    assert latest["localized_messages"]["labels"]["canonical_route"]["zh-CN"] == "恐慌反转"
    zh_notification = latest["notification"]["localized_messages"]["zh-CN"]
    assert "【机会复核｜TQQQ｜VIX 恐慌反转】" in zh_notification
    assert "TQQQ 从近 5 日低点反弹" in zh_notification
    assert "执行权限" not in zh_notification
    assert "仓位权限" not in zh_notification


def test_strategy_plugin_runner_rejects_panic_reversal_for_soxl_strategy_mount(tmp_path) -> None:
    prices_path = tmp_path / "panic_prices.csv"
    _panic_reversal_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": SOXL_STRATEGY_NAME,
                "plugin": PLUGIN_PANIC_REVERSAL_SHADOW,
                "enabled": True,
                "inputs": {"prices": str(prices_path), "as_of": "2025-04-10"},
            }
        ],
    }

    with pytest.raises(ValueError, match="strategy-limited"):
        run_configured_plugins(config)


def test_strategy_plugin_runner_runs_panic_reversal_general_notification_target(tmp_path) -> None:
    prices_path = tmp_path / "panic_prices.csv"
    output_dir = tmp_path / GENERAL_MARKET_REGIME_NOTIFICATION_TARGET / "plugins" / PLUGIN_PANIC_REVERSAL_SHADOW
    _panic_reversal_prices().to_csv(prices_path, index=False)
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "notification_targets": [
            {
                "notification_target": GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
                "plugin": PLUGIN_PANIC_REVERSAL_SHADOW,
                "enabled": True,
                "inputs": {
                    "prices": str(prices_path),
                    "as_of": "2025-04-10",
                    "start_date": "2025-04-01",
                },
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    assert summary["strategy_plugins"] == []
    result = summary["notification_targets"][0]
    assert result["plugin"] == PLUGIN_PANIC_REVERSAL_SHADOW
    assert result["status"] == "ok"
    latest = json.loads((output_dir / "latest_signal.json").read_text(encoding="utf-8"))
    assert latest["target_type"] == "notification_target"
    assert latest["execution_controls"]["position_control_allowed"] is False
    assert latest["execution_controls"]["strategy_runtime_metadata_allowed"] is False


def test_strategy_plugin_runner_can_skip_disabled_taco_notification_mount(tmp_path) -> None:
    output_dir = tmp_path / LEFT_SIDE_STRATEGY_NAME / "plugins" / PLUGIN_TACO_REBOUND_SHADOW
    config = {
        "output_dir": str(tmp_path / "runner"),
        "default_mode": "shadow",
        "strategy_plugins": [
            {
                "strategy": LEFT_SIDE_STRATEGY_NAME,
                "plugin": PLUGIN_TACO_REBOUND_SHADOW,
                "enabled": False,
                "outputs": {"output_dir": str(output_dir)},
            }
        ],
    }

    summary = run_configured_plugins(config)

    result = summary["strategy_plugins"][0]
    assert result["strategy"] == LEFT_SIDE_STRATEGY_NAME
    assert result["plugin"] == PLUGIN_TACO_REBOUND_SHADOW
    assert result["status"] == "skipped"
    assert not (output_dir / "latest_signal.json").exists()


def test_strategy_plugin_runner_rejects_incompatible_plugin_strategy_mount(tmp_path) -> None:
    config = _shadow_plugin_config(tmp_path)
    config["strategy_plugins"][0]["strategy"] = LEFT_SIDE_STRATEGY_NAME

    with pytest.raises(ValueError, match="strategy-limited"):
        run_configured_plugins(config)


@pytest.mark.parametrize("mode", ["paper", "advisory", "live", "broker_write"])
def test_strategy_plugin_runner_rejects_non_shadow_mode(tmp_path, mode: str) -> None:
    config = _shadow_plugin_config(tmp_path)
    config["strategy_plugins"][0]["mode"] = mode

    with pytest.raises(ValueError, match="supports only configured modes shadow"):
        run_configured_plugins(config)


def test_strategy_plugin_runner_rejects_duplicate_plugin_config_keys(tmp_path) -> None:
    config = _shadow_plugin_config(tmp_path)
    config["strategy_plugins"][0]["output_dir"] = str(tmp_path / "top_level")

    with pytest.raises(ValueError, match="duplicate strategy plugin config key.*output_dir"):
        run_configured_plugins(config)


def test_strategy_plugin_runner_cli_loads_toml_config(tmp_path) -> None:
    prices_path = tmp_path / "prices.csv"
    config_path = tmp_path / "plugins.toml"
    output_dir = tmp_path / STRATEGY_NAME / "plugins" / PLUGIN_CRISIS_RESPONSE_SHADOW
    _quiet_prices().to_csv(prices_path, index=False)
    config_path.write_text(
        f"""
output_dir = "{tmp_path / 'runner'}"
default_mode = "shadow"

[[strategy_plugins]]
strategy = "{STRATEGY_NAME}"
plugin = "{PLUGIN_CRISIS_RESPONSE_SHADOW}"
enabled = true
mode = "shadow"

[strategy_plugins.inputs]
prices = "{prices_path}"
as_of = "2025-11-19"
start_date = "2025-01-02"
financial_symbols = []
credit_pairs = []
rate_symbols = []

[strategy_plugins.outputs]
output_dir = "{output_dir}"
""".strip(),
        encoding="utf-8",
    )

    loaded = load_plugin_config(config_path)
    exit_code = main(["--config", str(config_path), "--strategies", STRATEGY_NAME])

    assert loaded["default_mode"] == "shadow"
    assert loaded["strategy_plugins"][0]["strategy"] == STRATEGY_NAME
    assert exit_code == 0
    assert (output_dir / "latest_signal.json").exists()


def test_strategy_plugin_runner_example_config_uses_default_mode_without_duplicate_entry_mode() -> None:
    config = load_plugin_config(Path("docs/examples/strategy_plugins.example.toml"))

    assert config["default_mode"] == "shadow"
    assert "mode" not in config["strategy_plugins"][0]
    assert config["strategy_plugins"][0]["plugin"] == PLUGIN_MARKET_REGIME_CONTROL
    assert config["strategy_plugins"][0]["outputs"]["output_dir"].endswith(
        "tqqq_growth_income/plugins/market_regime_control"
    )
    assert config["notification_targets"][0]["notification_target"] == GENERAL_MARKET_REGIME_NOTIFICATION_TARGET
    assert "strategy" not in config["notification_targets"][0]
    assert config["notification_targets"][0]["outputs"]["output_dir"].endswith(
        "market_regime_notification/plugins/market_regime_control"
    )
