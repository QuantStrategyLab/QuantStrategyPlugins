from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
CBOE_INDEX_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
CBOE_PUT_CALL_URL = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/{kind}.csv"

DEFAULT_START_DATE = "1999-01-01"
DEFAULT_OUTPUT_PATH = "data/output/macro_external_context/external_context.csv"

DEFAULT_FRED_SERIES: Mapping[str, str] = {
    "VIXCLS": "vix",
    "VXVCLS": "vix3m",
    "BAMLH0A0HYM2": "hy_oas",
    "BAMLC0A0CM": "ig_oas",
    "STLFSI4": "stlfsi4",
    "NFCI": "nfci",
    "ANFCI": "anfci",
    "T10Y2Y": "yield_curve_10y2y",
    "T10Y3M": "yield_curve_10y3m",
    "DTWEXBGS": "dollar_index",
    "TEDRATE": "ted_spread",
}
DEFAULT_CBOE_INDEX_SERIES: Mapping[str, str] = {
    "VIX": "vix",
    "VIX3M": "vix3m",
    "VVIX": "vvix",
    "SKEW": "skew",
}
DEFAULT_CBOE_PUT_CALL_SERIES: Mapping[str, str] = {
    "totalpc": "put_call_ratio",
    "equitypc": "equity_put_call_ratio",
    "indexpc": "index_put_call_ratio",
}
DEFAULT_EMPTY_EXTERNAL_FIELDS = (
    "fear_greed_index",
    "pentagon_pizza_index",
    "safe_haven_demand",
    "move",
    "pct_above_200d",
    "pct_above_50d",
    "new_high_new_low_spread",
    "advance_decline_drawdown",
    "aaii_bear_bull_spread",
    "naaim_exposure",
)


@dataclass(frozen=True)
class SourceCoverage:
    source: str
    column: str
    status: str
    start: str | None = None
    end: str | None = None
    rows: int = 0
    message: str = ""


def _normalize_timestamp(value: object | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp.normalize()


def _date_mask(series: pd.Series, *, start: str | None, end: str | None) -> pd.Series:
    mask = pd.Series(True, index=series.index)
    start_ts = _normalize_timestamp(start)
    end_ts = _normalize_timestamp(end)
    if start_ts is not None:
        mask &= series >= start_ts
    if end_ts is not None:
        mask &= series <= end_ts
    return mask


def _clean_numeric_series(frame: pd.DataFrame, *, date_column: str, value_column: str) -> pd.Series:
    if date_column not in frame.columns:
        raise ValueError(f"missing date column: {date_column}")
    if value_column not in frame.columns:
        raise ValueError(f"missing value column: {value_column}")
    dates = pd.to_datetime(frame[date_column], errors="coerce").dt.tz_localize(None).dt.normalize()
    values = pd.to_numeric(frame[value_column].replace(".", pd.NA), errors="coerce")
    cleaned = (
        pd.DataFrame({"as_of": dates, "value": values})
        .dropna(subset=["as_of", "value"])
        .drop_duplicates(subset=["as_of"], keep="last")
        .sort_values("as_of")
        .set_index("as_of")["value"]
    )
    cleaned.index.name = "as_of"
    return cleaned.astype(float)


def _coverage(source: str, column: str, series: pd.Series, *, status: str = "ok", message: str = "") -> SourceCoverage:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        empty_status = "empty" if status == "ok" else status
        return SourceCoverage(source=source, column=column, status=empty_status, message=message)
    return SourceCoverage(
        source=source,
        column=column,
        status=status,
        start=values.index.min().date().isoformat(),
        end=values.index.max().date().isoformat(),
        rows=int(values.shape[0]),
        message=message,
    )


def fetch_fred_series(series_id: str, *, start: str | None = None, end: str | None = None) -> pd.Series:
    series_id = str(series_id or "").strip().upper()
    if not series_id:
        raise ValueError("series_id is required")
    params: dict[str, str] = {}
    if start:
        params["cosd"] = str(start)
    if end:
        params["coed"] = str(end)
    query = f"&{urlencode(params)}" if params else ""
    frame = pd.read_csv(f"{FRED_GRAPH_URL.format(series_id=series_id)}{query}")
    values = _clean_numeric_series(frame, date_column="observation_date", value_column=series_id)
    if values.empty:
        return values
    mask = _date_mask(values.index.to_series(index=values.index), start=start, end=end)
    return values.loc[mask]


def _cboe_value_column(frame: pd.DataFrame, symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    columns = {str(column).strip().upper(): column for column in frame.columns}
    for candidate in ("CLOSE", symbol, "LAST"):
        column = columns.get(candidate)
        if column is not None:
            return str(column)
    raise ValueError(f"missing CBOE value column for {symbol}")


def fetch_cboe_index_history(symbol: str, *, start: str | None = None, end: str | None = None) -> pd.Series:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    frame = pd.read_csv(CBOE_INDEX_HISTORY_URL.format(symbol=symbol))
    values = _clean_numeric_series(frame, date_column="DATE", value_column=_cboe_value_column(frame, symbol))
    if values.empty:
        return values
    mask = _date_mask(values.index.to_series(index=values.index), start=start, end=end)
    return values.loc[mask]


def fetch_cboe_put_call_ratio(kind: str, *, start: str | None = None, end: str | None = None) -> pd.Series:
    kind = str(kind or "").strip().lower()
    if not kind:
        raise ValueError("kind is required")
    frame = pd.read_csv(CBOE_PUT_CALL_URL.format(kind=kind), skiprows=2)
    values = _clean_numeric_series(frame, date_column="DATE", value_column="P/C Ratio")
    if values.empty:
        return values
    mask = _date_mask(values.index.to_series(index=values.index), start=start, end=end)
    return values.loc[mask]


def read_manual_context(path: str | Path) -> pd.DataFrame:
    manual_path = Path(path)
    if not manual_path.exists():
        raise FileNotFoundError(f"manual context file not found: {manual_path}")
    if manual_path.suffix.lower() == ".csv":
        frame = pd.read_csv(manual_path)
    elif manual_path.suffix.lower() in {".json", ".jsonl"}:
        frame = pd.read_json(manual_path, orient="records", lines=manual_path.suffix.lower() == ".jsonl")
    else:
        raise ValueError("manual context must be .csv, .json, or .jsonl")
    if "as_of" not in frame.columns:
        raise ValueError("manual context missing required column: as_of")
    frame = frame.copy()
    frame["as_of"] = pd.to_datetime(frame["as_of"], errors="coerce").dt.tz_localize(None).dt.normalize()
    frame = frame.dropna(subset=["as_of"]).drop_duplicates(subset=["as_of"], keep="last").sort_values("as_of")
    return frame


def _merge_series(frame: pd.DataFrame, column: str, series: pd.Series, *, prefer_new: bool = True) -> pd.DataFrame:
    column = str(column or "").strip()
    if not column or series.empty:
        return frame
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return frame
    values.name = column
    merged = frame.join(values, how="outer", rsuffix="__new")
    new_column = f"{column}__new"
    if new_column in merged.columns:
        existing = pd.to_numeric(merged[column], errors="coerce")
        incoming = pd.to_numeric(merged[new_column], errors="coerce")
        merged[column] = incoming.combine_first(existing) if prefer_new else existing.combine_first(incoming)
        merged = merged.drop(columns=[new_column])
    return merged.sort_index()


def _merge_manual_context(frame: pd.DataFrame, manual_context: pd.DataFrame | None) -> pd.DataFrame:
    if manual_context is None or manual_context.empty:
        return frame
    manual = manual_context.copy()
    manual["as_of"] = pd.to_datetime(manual["as_of"], errors="coerce").dt.tz_localize(None).dt.normalize()
    manual = manual.dropna(subset=["as_of"]).drop_duplicates("as_of", keep="last").set_index("as_of").sort_index()
    for column in manual.columns:
        frame = _merge_series(frame, str(column), manual[column], prefer_new=True)
    return frame


def _add_derived_columns(frame: pd.DataFrame, *, return_lookback_days: int, delta_lookback_days: int) -> pd.DataFrame:
    result = frame.copy().sort_index()
    if {"vix", "vix3m"} <= set(result.columns):
        denominator = pd.to_numeric(result["vix3m"], errors="coerce")
        result["vix_vix3m_ratio"] = pd.to_numeric(result["vix"], errors="coerce") / denominator.where(denominator > 0.0)
    if "hy_oas" in result.columns:
        result["hy_oas_delta_63d"] = pd.to_numeric(result["hy_oas"], errors="coerce").diff(int(delta_lookback_days))
    if "ig_oas" in result.columns:
        result["ig_oas_delta_63d"] = pd.to_numeric(result["ig_oas"], errors="coerce").diff(int(delta_lookback_days))
    if "stlfsi4" in result.columns and "financial_stress" not in result.columns:
        result["financial_stress"] = pd.to_numeric(result["stlfsi4"], errors="coerce")
    if "ted_spread" in result.columns and "funding_stress" not in result.columns:
        result["funding_stress"] = pd.to_numeric(result["ted_spread"], errors="coerce")
    if "dollar_index" in result.columns:
        dollar = pd.to_numeric(result["dollar_index"], errors="coerce")
        result["dollar_index_return_21d"] = dollar / dollar.shift(int(return_lookback_days)) - 1.0
        result["dxy_return_21d"] = result["dollar_index_return_21d"]
    return result


def _bounded_ffill(frame: pd.DataFrame, *, max_staleness_days: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    max_staleness_days = int(max_staleness_days)
    if max_staleness_days < 0:
        return frame
    result = frame.sort_index().copy()
    index_dates = pd.Series(result.index, index=result.index)
    for column in result.columns:
        values = pd.to_numeric(result[column], errors="coerce")
        valid_dates = index_dates.where(values.notna()).ffill()
        filled = values.ffill()
        ages = (index_dates - valid_dates).dt.days
        result[column] = filled.where(ages <= max_staleness_days)
    return result


def _finalize_frame(
    frame: pd.DataFrame,
    *,
    start: str | None,
    end: str | None,
    empty_fields: Sequence[str],
    include_empty_fields: bool,
) -> pd.DataFrame:
    if frame.empty:
        result = pd.DataFrame(columns=["as_of"])
    else:
        result = frame.sort_index().copy()
        dates = result.index.to_series(index=result.index)
        mask = _date_mask(dates, start=start, end=end)
        result = result.loc[mask]
        result.index.name = "as_of"
        result = result.reset_index()
        result["as_of"] = pd.to_datetime(result["as_of"], errors="coerce").dt.strftime("%Y-%m-%d")
    if include_empty_fields:
        for column in empty_fields:
            if column not in result.columns:
                result[column] = pd.NA
    non_date_columns = [column for column in result.columns if column != "as_of"]
    result = result.dropna(how="all", subset=non_date_columns) if non_date_columns else result
    ordered_columns = ["as_of"] + sorted(column for column in result.columns if column != "as_of")
    return result.loc[:, ordered_columns].reset_index(drop=True)


def build_macro_external_context(
    *,
    start: str | None = DEFAULT_START_DATE,
    end: str | None = None,
    fred_series: Mapping[str, str] = DEFAULT_FRED_SERIES,
    cboe_index_series: Mapping[str, str] = DEFAULT_CBOE_INDEX_SERIES,
    cboe_put_call_series: Mapping[str, str] = DEFAULT_CBOE_PUT_CALL_SERIES,
    manual_context: pd.DataFrame | None = None,
    include_empty_fields: bool = False,
    return_lookback_days: int = 21,
    delta_lookback_days: int = 63,
    max_field_staleness_days: int = 10,
    fred_reader: Callable[..., pd.Series] = fetch_fred_series,
    cboe_index_reader: Callable[..., pd.Series] = fetch_cboe_index_history,
    cboe_put_call_reader: Callable[..., pd.Series] = fetch_cboe_put_call_ratio,
) -> tuple[pd.DataFrame, list[SourceCoverage]]:
    frame = pd.DataFrame()
    frame.index = pd.DatetimeIndex([], name="as_of")
    coverage: list[SourceCoverage] = []

    for series_id, column in fred_series.items():
        source = f"fred:{series_id}"
        try:
            values = fred_reader(series_id, start=start, end=end)
            frame = _merge_series(frame, column, values, prefer_new=False)
            coverage.append(_coverage(source, column, values))
        except Exception as exc:  # pragma: no cover - exact network failures vary by environment
            coverage.append(SourceCoverage(source=source, column=column, status="error", message=str(exc)))

    for symbol, column in cboe_index_series.items():
        source = f"cboe_index:{symbol}"
        try:
            values = cboe_index_reader(symbol, start=start, end=end)
            frame = _merge_series(frame, column, values, prefer_new=True)
            coverage.append(_coverage(source, column, values))
        except Exception as exc:  # pragma: no cover - exact network failures vary by environment
            coverage.append(SourceCoverage(source=source, column=column, status="error", message=str(exc)))

    for kind, column in cboe_put_call_series.items():
        source = f"cboe_put_call:{kind}"
        try:
            values = cboe_put_call_reader(kind, start=start, end=end)
            frame = _merge_series(frame, column, values, prefer_new=True)
            coverage.append(_coverage(source, column, values))
        except Exception as exc:  # pragma: no cover - exact network failures vary by environment
            coverage.append(SourceCoverage(source=source, column=column, status="error", message=str(exc)))

    frame = _merge_manual_context(frame, manual_context)
    frame = _add_derived_columns(
        frame,
        return_lookback_days=int(return_lookback_days),
        delta_lookback_days=int(delta_lookback_days),
    )
    frame = _bounded_ffill(frame, max_staleness_days=int(max_field_staleness_days))
    result = _finalize_frame(
        frame,
        start=start,
        end=end,
        empty_fields=DEFAULT_EMPTY_EXTERNAL_FIELDS,
        include_empty_fields=include_empty_fields,
    )
    return result, coverage


def write_macro_external_context_outputs(
    frame: pd.DataFrame,
    coverage: Sequence[SourceCoverage],
    output_path: str | Path,
    *,
    include_manifest: bool = True,
) -> dict[str, Path]:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False)
    paths = {"external_context": target}
    if include_manifest:
        manifest_path = target.with_suffix(target.suffix + ".manifest.json")
        manifest = {
            "schema_version": "macro_external_context.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "output_path": str(target),
            "rows": int(frame.shape[0]),
            "columns": list(frame.columns),
            "coverage": [coverage_item.__dict__ for coverage_item in coverage],
            "notes": [
                "FRED and CBOE public data are populated when available.",
                (
                    "CNN Fear & Greed, AAII, NAAIM, Pentagon pizza, MOVE, and breadth fields can be "
                    "supplied through manual_context."
                ),
                (
                    "ICE BofA OAS coverage follows the public FRED graph endpoint; if FRED limits "
                    "history, archived local OAS data should be supplied through manual_context."
                ),
            ],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        paths["manifest"] = manifest_path
    return paths


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build macro risk governor external context from public hard-data sources."
    )
    parser.add_argument("--start", default=DEFAULT_START_DATE, help="Earliest as_of date to include.")
    parser.add_argument(
        "--end",
        default=None,
        help="Latest as_of date to include. Defaults to latest available source rows.",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Output CSV path.")
    parser.add_argument(
        "--manual-context",
        default=None,
        help=(
            "Optional CSV/JSON/JSONL with as_of plus extra fields. Values override downloaded columns "
            "on matching dates."
        ),
    )
    parser.add_argument(
        "--include-empty-fields",
        action="store_true",
        help="Include known manually sourced columns even when no values are downloaded.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write the companion manifest JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    manual_context = read_manual_context(args.manual_context) if args.manual_context else None
    frame, coverage = build_macro_external_context(
        start=args.start,
        end=args.end,
        manual_context=manual_context,
        include_empty_fields=bool(args.include_empty_fields),
    )
    paths = write_macro_external_context_outputs(
        frame,
        coverage,
        args.output,
        include_manifest=not bool(args.no_manifest),
    )
    ok_sources = sum(1 for item in coverage if item.status == "ok")
    error_sources = sum(1 for item in coverage if item.status == "error")
    print(
        f"wrote {paths['external_context']} rows={len(frame)} columns={len(frame.columns)} "
        f"sources_ok={ok_sources} sources_error={error_sources}",
        flush=True,
    )
    if "manifest" in paths:
        print(f"wrote {paths['manifest']}", flush=True)
    return 0


__all__ = [
    "DEFAULT_CBOE_INDEX_SERIES",
    "DEFAULT_CBOE_PUT_CALL_SERIES",
    "DEFAULT_FRED_SERIES",
    "SourceCoverage",
    "build_macro_external_context",
    "fetch_cboe_index_history",
    "fetch_cboe_put_call_ratio",
    "fetch_fred_series",
    "read_manual_context",
    "write_macro_external_context_outputs",
]


if __name__ == "__main__":
    raise SystemExit(main())
