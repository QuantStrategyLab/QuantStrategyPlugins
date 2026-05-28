from __future__ import annotations

import json

import pandas as pd

from quant_strategy_plugins.macro_external_context import (
    SourceCoverage,
    build_macro_external_context,
    read_manual_context,
    write_macro_external_context_outputs,
)


def _series(values: dict[str, float]) -> pd.Series:
    series = pd.Series(values, dtype=float)
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    series.index.name = "as_of"
    return series


def test_build_macro_external_context_derives_public_hard_data_fields() -> None:
    fred_values = {
        "BAMLH0A0HYM2": _series({"2025-01-01": 3.0, "2025-01-02": 3.2, "2025-01-03": 3.8}),
        "BAMLC0A0CM": _series({"2025-01-01": 1.0, "2025-01-02": 1.1, "2025-01-03": 1.6}),
        "STLFSI4": _series({"2025-01-01": -0.2, "2025-01-02": 0.1, "2025-01-03": 1.2}),
        "TEDRATE": _series({"2025-01-01": 0.2, "2025-01-02": 0.3, "2025-01-03": 0.8}),
        "DTWEXBGS": _series({"2025-01-01": 100.0, "2025-01-02": 101.0, "2025-01-03": 104.0}),
        "T10Y2Y": _series({"2025-01-03": -0.6}),
    }
    cboe_values = {
        "VIX": _series({"2025-01-01": 20.0, "2025-01-02": 30.0, "2025-01-03": 40.0}),
        "VIX3M": _series({"2025-01-01": 25.0, "2025-01-02": 25.0, "2025-01-03": 32.0}),
        "VVIX": _series({"2025-01-03": 125.0}),
        "SKEW": _series({"2025-01-03": 160.0}),
    }
    put_call_values = {
        "totalpc": _series({"2025-01-03": 1.3}),
        "equitypc": _series({"2025-01-03": 1.1}),
    }

    frame, coverage = build_macro_external_context(
        start="2025-01-01",
        end="2025-01-03",
        fred_series={key: value for key, value in {
            "BAMLH0A0HYM2": "hy_oas",
            "BAMLC0A0CM": "ig_oas",
            "STLFSI4": "stlfsi4",
            "TEDRATE": "ted_spread",
            "DTWEXBGS": "dollar_index",
            "T10Y2Y": "yield_curve_10y2y",
        }.items()},
        cboe_index_series={"VIX": "vix", "VIX3M": "vix3m", "VVIX": "vvix", "SKEW": "skew"},
        cboe_put_call_series={"totalpc": "put_call_ratio", "equitypc": "equity_put_call_ratio"},
        return_lookback_days=2,
        delta_lookback_days=2,
        fred_reader=lambda series_id, **_: fred_values[series_id],
        cboe_index_reader=lambda symbol, **_: cboe_values[symbol],
        cboe_put_call_reader=lambda kind, **_: put_call_values[kind],
    )

    latest = frame.loc[frame["as_of"].eq("2025-01-03")].iloc[0]
    assert latest["vix"] == 40.0
    assert latest["vix3m"] == 32.0
    assert latest["vix_vix3m_ratio"] == 1.25
    assert round(float(latest["hy_oas_delta_63d"]), 4) == 0.8
    assert round(float(latest["ig_oas_delta_63d"]), 4) == 0.6
    assert latest["financial_stress"] == 1.2
    assert latest["funding_stress"] == 0.8
    assert latest["put_call_ratio"] == 1.3
    assert latest["equity_put_call_ratio"] == 1.1
    assert round(float(latest["dxy_return_21d"]), 4) == 0.04
    assert latest["yield_curve_10y2y"] == -0.6
    assert any(item.source == "fred:BAMLH0A0HYM2" and item.status == "ok" for item in coverage)


def test_manual_context_overrides_downloaded_values_and_adds_private_fields(tmp_path) -> None:
    manual_path = tmp_path / "manual.csv"
    manual_path.write_text(
        "as_of,vix,fear_greed_index,pentagon_pizza_index,naaim_exposure\n"
        "2025-01-03,55,18,3,30\n",
        encoding="utf-8",
    )

    frame, _coverage = build_macro_external_context(
        start="2025-01-01",
        end="2025-01-03",
        fred_series={},
        cboe_index_series={"VIX": "vix"},
        cboe_put_call_series={},
        manual_context=read_manual_context(manual_path),
        cboe_index_reader=lambda symbol, **_: _series({"2025-01-03": 22.0}),
    )

    latest = frame.iloc[-1]
    assert latest["vix"] == 55.0
    assert latest["fear_greed_index"] == 18.0
    assert latest["pentagon_pizza_index"] == 3.0
    assert latest["naaim_exposure"] == 30.0


def test_build_macro_external_context_bounds_forward_fill_to_staleness_window() -> None:
    frame, _coverage = build_macro_external_context(
        start="2025-01-01",
        end="2025-01-15",
        fred_series={"STLFSI4": "stlfsi4"},
        cboe_index_series={"VIX": "vix"},
        cboe_put_call_series={},
        max_field_staleness_days=3,
        fred_reader=lambda series_id, **_: _series({"2025-01-03": 1.2}),
        cboe_index_reader=lambda symbol, **_: _series({"2025-01-06": 20.0, "2025-01-10": 21.0, "2025-01-15": 22.0}),
    )

    by_date = frame.set_index("as_of")
    assert by_date.loc["2025-01-06", "financial_stress"] == 1.2
    assert pd.isna(by_date.loc["2025-01-10", "financial_stress"])
    assert pd.isna(by_date.loc["2025-01-15", "financial_stress"])


def test_write_macro_external_context_outputs_writes_manifest(tmp_path) -> None:
    output_path = tmp_path / "external_context.csv"
    frame = pd.DataFrame([{"as_of": "2025-01-03", "vix": 30.0}])
    coverage = [SourceCoverage(source="cboe_index:VIX", column="vix", status="ok", rows=1)]

    paths = write_macro_external_context_outputs(frame, coverage, output_path)

    assert paths["external_context"] == output_path
    assert output_path.exists()
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "macro_external_context.v1"
    assert manifest["rows"] == 1
    assert manifest["coverage"][0]["source"] == "cboe_index:VIX"
