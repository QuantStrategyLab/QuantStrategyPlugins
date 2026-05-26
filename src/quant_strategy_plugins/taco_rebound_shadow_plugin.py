from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .artifacts import write_json
from .plugin_signal_utils import bool_at, flatten_for_csv, json_scalar, normalize_close, resolve_signal_date
from .russell_1000_multi_factor_defensive_snapshot import read_table
from .taco_panic_rebound_overlay_compare import (
    DEFAULT_ATTACK_SYMBOL,
    DEFAULT_BENCHMARK_SYMBOL,
    DEFAULT_PRICE_CRISIS_GUARD_DRAWDOWN,
    DEFAULT_PRICE_CRISIS_GUARD_MA_DAYS,
    DEFAULT_PRICE_CRISIS_GUARD_MA_SLOPE_DAYS,
    build_price_crisis_guard_signal,
    build_price_stress_scan,
    filter_events_by_price_stress,
)
from .taco_panic_rebound_research import (
    DEFAULT_EVENT_SET,
    EVENT_KIND_SOFTENING,
    TRADE_WAR_EVENT_SETS,
    TradeWarEvent,
    resolve_trade_war_event_set,
)
from .yfinance_prices import download_price_history

SCHEMA_VERSION = "taco_rebound_shadow.v2"
SHADOW_MODE = "shadow"
TACO_REBOUND_PROFILE = "taco_rebound_shadow"
ROUTE_TACO_REBOUND = "taco_rebound"
ACTION_NOTIFY_MANUAL_REVIEW = "notify_manual_review"
ACTION_WATCH_ONLY = "watch_only"
ACTION_NO_ACTION = "no_action"
DEFAULT_OUTPUT_DIR = "data/output/taco_rebound_shadow"
DEFAULT_START_DATE = "2018-01-01"
DEFAULT_MAX_PRICE_AGE_DAYS = 4
DEFAULT_ACTIVE_SIGNAL_DAYS = 10
DEFAULT_REQUIRE_REBOUND_CONFIRMATION = True
DEFAULT_CONFIRMATION_LOOKBACK_DAYS = 5
DEFAULT_MIN_CONFIRMATION_TRADING_DAYS_AFTER_EVENT = 1
DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW = 0.015
DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW = 0.04
DEFAULT_MIN_BENCHMARK_3D_RETURN = 0.0
HARD_DEFENSE_BREAK_BEAR_REGIONS = frozenset({"iran_middle_east"})


def _next_index_date(index: pd.DatetimeIndex, raw_date: str | pd.Timestamp) -> pd.Timestamp | None:
    date = pd.Timestamp(raw_date).tz_localize(None).normalize()
    candidates = index[index >= date]
    if candidates.empty:
        return None
    return pd.Timestamp(candidates[0]).normalize()


def _event_allows_hard_defense(event: TradeWarEvent | None) -> bool:
    if event is None or event.kind != EVENT_KIND_SOFTENING:
        return False
    return str(event.region).strip().lower() in HARD_DEFENSE_BREAK_BEAR_REGIONS


def _event_notice_priority(event: TradeWarEvent) -> tuple[int, int, str]:
    kind_priority = 1 if event.kind == EVENT_KIND_SOFTENING else 0
    region_priority = 1 if str(event.region).strip().lower() in HARD_DEFENSE_BREAK_BEAR_REGIONS else 0
    return kind_priority, region_priority, str(event.event_date)


def _active_recognized_events(
    events: Sequence[TradeWarEvent],
    *,
    index: pd.DatetimeIndex,
    signal_date: pd.Timestamp,
    active_signal_days: int,
) -> tuple[tuple[TradeWarEvent, pd.Timestamp], ...]:
    active: list[tuple[TradeWarEvent, pd.Timestamp]] = []
    for event in sorted(events, key=lambda item: item.event_date):
        event_signal_date = _next_index_date(index, event.event_date)
        if event_signal_date is None:
            continue
        if event_signal_date <= signal_date <= event_signal_date + pd.Timedelta(days=int(active_signal_days)):
            active.append((event, event_signal_date))
    return tuple(active)


def _trading_day_distance(
    index: pd.DatetimeIndex,
    *,
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp,
) -> int | None:
    if start_date is None:
        return None
    try:
        start_pos = int(index.get_loc(pd.Timestamp(start_date).normalize()))
        end_pos = int(index.get_loc(pd.Timestamp(end_date).normalize()))
    except KeyError:
        return None
    return max(0, end_pos - start_pos)


def _build_rebound_confirmation(
    close: pd.DataFrame,
    *,
    signal_date: pd.Timestamp,
    selected_event_signal_date: pd.Timestamp | None,
    benchmark_symbol: str,
    attack_symbol: str,
    lookback_days: int,
    min_trading_days_after_event: int,
    min_benchmark_rebound_from_low: float,
    min_attack_rebound_from_low: float,
    min_benchmark_3d_return: float,
) -> dict[str, Any]:
    index = pd.DatetimeIndex(close.index).sort_values()
    trading_days_after_event = _trading_day_distance(
        index,
        start_date=selected_event_signal_date,
        end_date=signal_date,
    )
    if signal_date not in index:
        return {
            "confirmed": False,
            "reason": "signal date missing from price index",
            "trading_days_after_event": trading_days_after_event,
        }

    signal_pos = int(index.get_loc(signal_date))
    lookback_start = max(0, signal_pos - max(1, int(lookback_days)) + 1)
    window_index = index[lookback_start : signal_pos + 1]
    benchmark = pd.to_numeric(close[benchmark_symbol].reindex(window_index), errors="coerce")
    attack = pd.to_numeric(close[attack_symbol].reindex(window_index), errors="coerce")
    benchmark_close = float(benchmark.iloc[-1]) if benchmark.notna().any() else float("nan")
    attack_close = float(attack.iloc[-1]) if attack.notna().any() else float("nan")
    benchmark_low = float(benchmark.min()) if benchmark.notna().any() else float("nan")
    attack_low = float(attack.min()) if attack.notna().any() else float("nan")
    benchmark_rebound_from_low = benchmark_close / benchmark_low - 1.0 if benchmark_low > 0 else float("nan")
    attack_rebound_from_low = attack_close / attack_low - 1.0 if attack_low > 0 else float("nan")
    if signal_pos >= 3:
        benchmark_3d_base = float(close[benchmark_symbol].iloc[signal_pos - 3])
        benchmark_3d_return = benchmark_close / benchmark_3d_base - 1.0 if benchmark_3d_base > 0 else float("nan")
    else:
        benchmark_3d_return = float("nan")

    reasons: list[str] = []
    if trading_days_after_event is None or trading_days_after_event < int(min_trading_days_after_event):
        reasons.append("waiting for post-event trading confirmation")
    if pd.isna(benchmark_rebound_from_low) or benchmark_rebound_from_low < float(min_benchmark_rebound_from_low):
        reasons.append("benchmark rebound from recent low below threshold")
    if pd.isna(attack_rebound_from_low) or attack_rebound_from_low < float(min_attack_rebound_from_low):
        reasons.append("attack rebound from recent low below threshold")
    if pd.isna(benchmark_3d_return) or benchmark_3d_return < float(min_benchmark_3d_return):
        reasons.append("benchmark 3d return below threshold")

    return {
        "confirmed": not reasons,
        "reason": "; ".join(reasons),
        "lookback_days": int(lookback_days),
        "trading_days_after_event": trading_days_after_event,
        "min_trading_days_after_event": int(min_trading_days_after_event),
        "benchmark_symbol": benchmark_symbol,
        "attack_symbol": attack_symbol,
        "benchmark_rebound_from_recent_low": benchmark_rebound_from_low,
        "attack_rebound_from_recent_low": attack_rebound_from_low,
        "benchmark_3d_return": benchmark_3d_return,
        "min_benchmark_rebound_from_low": float(min_benchmark_rebound_from_low),
        "min_attack_rebound_from_low": float(min_attack_rebound_from_low),
        "min_benchmark_3d_return": float(min_benchmark_3d_return),
    }


def build_taco_rebound_shadow_signal(
    price_history,
    *,
    events: Sequence[TradeWarEvent] = (),
    as_of: str | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    attack_symbol: str = DEFAULT_ATTACK_SYMBOL,
    active_signal_days: int = DEFAULT_ACTIVE_SIGNAL_DAYS,
    suppress_when_price_crisis_guard_active: bool = True,
    crisis_guard_drawdown: float = DEFAULT_PRICE_CRISIS_GUARD_DRAWDOWN,
    crisis_guard_ma_days: int = DEFAULT_PRICE_CRISIS_GUARD_MA_DAYS,
    crisis_guard_ma_slope_days: int = DEFAULT_PRICE_CRISIS_GUARD_MA_SLOPE_DAYS,
    max_price_age_days: int = DEFAULT_MAX_PRICE_AGE_DAYS,
    require_rebound_confirmation: bool = DEFAULT_REQUIRE_REBOUND_CONFIRMATION,
    confirmation_lookback_days: int = DEFAULT_CONFIRMATION_LOOKBACK_DAYS,
    min_confirmation_trading_days_after_event: int = DEFAULT_MIN_CONFIRMATION_TRADING_DAYS_AFTER_EVENT,
    min_benchmark_rebound_from_low: float = DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW,
    min_attack_rebound_from_low: float = DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW,
    min_benchmark_3d_return: float = DEFAULT_MIN_BENCHMARK_3D_RETURN,
) -> dict[str, Any]:
    close = normalize_close(price_history)
    benchmark_symbol = str(benchmark_symbol).strip().upper()
    attack_symbol = str(attack_symbol).strip().upper()
    if end_date is not None:
        close = close.loc[close.index <= pd.Timestamp(end_date).tz_localize(None).normalize()].copy()
    requested_date, signal_date = resolve_signal_date(close, as_of)
    signal_iso = signal_date.date().isoformat()
    latest_price_date = pd.Timestamp(close.index.max()).normalize()
    price_age_days = int((requested_date - signal_date).days)

    kill_reasons: list[str] = []
    if benchmark_symbol not in close.columns:
        kill_reasons.append(f"missing benchmark price data: {benchmark_symbol}")
    if attack_symbol not in close.columns:
        kill_reasons.append(f"missing attack price data: {attack_symbol}")
    if price_age_days > int(max_price_age_days):
        kill_reasons.append(
            f"price data stale: signal_as_of={signal_iso}, requested_as_of={requested_date.date().isoformat()}"
        )

    scan_active = False
    crisis_guard_active = False
    recognized_events: tuple[TradeWarEvent, ...] = ()
    active_events: tuple[tuple[TradeWarEvent, pd.Timestamp], ...] = ()
    if not kill_reasons:
        scan_days = build_price_stress_scan(
            close,
            start_date=start_date,
            end_date=signal_iso,
            benchmark_symbol=benchmark_symbol,
            attack_symbol=attack_symbol,
        )
        scan_active = bool_at(scan_days, signal_date)
        recognized_events = filter_events_by_price_stress(events, scan_days)
        active_events = _active_recognized_events(
            recognized_events,
            index=pd.DatetimeIndex(scan_days.index),
            signal_date=signal_date,
            active_signal_days=int(active_signal_days),
        )
        if bool(suppress_when_price_crisis_guard_active):
            crisis_guard = build_price_crisis_guard_signal(
                close,
                start_date=start_date,
                end_date=signal_iso,
                benchmark_symbol=benchmark_symbol,
                drawdown_threshold=float(crisis_guard_drawdown),
                ma_days=int(crisis_guard_ma_days),
                ma_slope_days=int(crisis_guard_ma_slope_days),
            )
            crisis_guard_active = bool_at(crisis_guard, signal_date)

    selected_event: TradeWarEvent | None = None
    selected_event_signal_date: pd.Timestamp | None = None
    for event, event_signal_date in active_events:
        if selected_event is None or _event_notice_priority(event) >= _event_notice_priority(selected_event):
            selected_event = event
            selected_event_signal_date = event_signal_date

    event_context_active = bool(
        selected_event is not None and selected_event.kind == EVENT_KIND_SOFTENING and not crisis_guard_active
    )
    rebound_confirmation = (
        _build_rebound_confirmation(
            close,
            signal_date=signal_date,
            selected_event_signal_date=selected_event_signal_date,
            benchmark_symbol=benchmark_symbol,
            attack_symbol=attack_symbol,
            lookback_days=int(confirmation_lookback_days),
            min_trading_days_after_event=int(min_confirmation_trading_days_after_event),
            min_benchmark_rebound_from_low=float(min_benchmark_rebound_from_low),
            min_attack_rebound_from_low=float(min_attack_rebound_from_low),
            min_benchmark_3d_return=float(min_benchmark_3d_return),
        )
        if event_context_active
        else {"confirmed": False, "reason": "no active softening/de-escalation event context"}
    )
    rebound_confirmed = bool(rebound_confirmation.get("confirmed")) or not bool(require_rebound_confirmation)
    rebound_context_active = bool(event_context_active and rebound_confirmed)
    manual_review_required = rebound_context_active
    canonical_route = ROUTE_TACO_REBOUND if manual_review_required else "no_action"
    suggested_action = ACTION_NOTIFY_MANUAL_REVIEW if manual_review_required else ACTION_NO_ACTION
    would_trade_if_enabled = False
    event_rebound_break_bear = bool(manual_review_required and _event_allows_hard_defense(selected_event))
    suppression_reason = ""
    notification_reason = ""
    if manual_review_required:
        notification_reason = (
            "event rebound context confirmed"
            if bool(require_rebound_confirmation)
            else "event rebound context active; rebound confirmation disabled"
        )
    if active_events and not manual_review_required:
        suggested_action = ACTION_WATCH_ONLY
        if event_context_active and bool(require_rebound_confirmation):
            suppression_reason = "rebound confirmation pending"
        else:
            suppression_reason = "active event is not a softening/de-escalation rebound context"
    if crisis_guard_active:
        canonical_route = "no_action"
        suggested_action = ACTION_WATCH_ONLY
        manual_review_required = False
        rebound_context_active = False
        event_context_active = False
        event_rebound_break_bear = False
        suppression_reason = "price crisis guard active"
        notification_reason = ""
        rebound_confirmation = {"confirmed": False, "reason": "price crisis guard active"}
    if kill_reasons:
        canonical_route = "no_action"
        suggested_action = ACTION_WATCH_ONLY
        manual_review_required = False
        rebound_context_active = False
        event_context_active = False
        event_rebound_break_bear = False
        suppression_reason = "; ".join(kill_reasons)
        notification_reason = ""
        rebound_confirmation = {"confirmed": False, "reason": suppression_reason}

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "as_of": signal_iso,
        "mode": SHADOW_MODE,
        "schema_version": SCHEMA_VERSION,
        "profile": TACO_REBOUND_PROFILE,
        "canonical_route": canonical_route,
        "suggested_action": suggested_action,
        "manual_review_required": manual_review_required,
        "notification_reason": notification_reason,
        "rebound_context_active": rebound_context_active,
        "event_context_active": event_context_active,
        "rebound_confirmation": rebound_confirmation,
        "event_rebound_break_bear": event_rebound_break_bear,
        "would_trade_if_enabled": would_trade_if_enabled,
        "price_stress_scan_active": scan_active,
        "price_crisis_guard_active": crisis_guard_active,
        "active_signal_days": int(active_signal_days),
        "suppression_reason": suppression_reason,
        "selected_event": (
            {
                "event_id": selected_event.event_id,
                "event_date": selected_event.event_date,
                "signal_date": selected_event_signal_date.date().isoformat()
                if selected_event_signal_date is not None
                else None,
                "kind": selected_event.kind,
                "region": selected_event.region,
                "title": selected_event.title,
                "source": selected_event.source,
                "source_url": selected_event.source_url,
            }
            if selected_event is not None
            else None
        ),
        "recognized_event_ids": [event.event_id for event in recognized_events],
        "active_event_ids": [event.event_id for event, _signal_date in active_events],
        "data_freshness": {
            "requested_as_of": requested_date.date().isoformat(),
            "signal_as_of": signal_iso,
            "prices_as_of": latest_price_date.date().isoformat(),
            "price_age_days": price_age_days,
            "max_price_age_days": int(max_price_age_days),
        },
        "execution_controls": {
            "capital_impact": "none",
            "broker_order_allowed": False,
            "live_allocation_mutation_allowed": False,
            "log_namespace": TACO_REBOUND_PROFILE,
            "notification_profile": "manual_review_only",
            "intended_strategy_role": "event_rebound_notification",
            "selection_allowed": False,
            "position_sizing_allowed": False,
            "allocation_recommendation_allowed": False,
            "hard_defense_override_signal_allowed": False,
        },
        "generated_at": generated_at,
    }
    return json_scalar(payload)


def write_taco_rebound_shadow_outputs(payload: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
    output_root = Path(output_dir)
    signal_date = str(payload["as_of"])
    signal_dir = output_root / "signals"
    audit_dir = output_root / "audit"
    latest_path = output_root / "latest_signal.json"
    dated_json_path = signal_dir / f"{signal_date}.json"
    dated_csv_path = signal_dir / f"{signal_date}.csv"
    evidence_csv_path = audit_dir / f"{signal_date}_evidence.csv"

    write_json(latest_path, payload)
    write_json(dated_json_path, payload)
    signal_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([flatten_for_csv(payload)]).to_csv(dated_csv_path, index=False)

    evidence_payload = {
        "as_of": payload.get("as_of"),
        "canonical_route": payload.get("canonical_route"),
        "suggested_action": payload.get("suggested_action"),
        "manual_review_required": payload.get("manual_review_required"),
        "notification_reason": payload.get("notification_reason"),
        "rebound_context_active": payload.get("rebound_context_active"),
        "event_context_active": payload.get("event_context_active"),
        "event_rebound_break_bear": payload.get("event_rebound_break_bear"),
        **flatten_for_csv(payload.get("rebound_confirmation", {})),
        **flatten_for_csv(payload.get("data_freshness", {})),
        **flatten_for_csv(payload.get("selected_event") or {}),
    }
    pd.DataFrame([evidence_payload]).to_csv(evidence_csv_path, index=False)
    return {
        "latest_signal": latest_path,
        "signal_json": dated_json_path,
        "signal_csv": dated_csv_path,
        "evidence_csv": evidence_csv_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the log-only TACO rebound shadow signal.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--prices", help="Existing long price-history CSV with symbol/as_of/close columns")
    input_group.add_argument("--download", action="store_true", help="Download adjusted price history through yfinance")
    parser.add_argument("--mode", choices=(SHADOW_MODE,), default=SHADOW_MODE)
    parser.add_argument("--event-set", choices=tuple(sorted(TRADE_WAR_EVENT_SETS)), default=DEFAULT_EVENT_SET)
    parser.add_argument("--as-of", default=None, help="Requested signal date; defaults to the latest price date")
    parser.add_argument("--price-start", default=DEFAULT_START_DATE)
    parser.add_argument("--price-end", default=None)
    parser.add_argument("--download-proxy", default=None, help="Optional yfinance proxy URL; YFINANCE_PROXY also works")
    parser.add_argument("--start", dest="start_date", default=DEFAULT_START_DATE)
    parser.add_argument("--end", dest="end_date", default=None)
    parser.add_argument("--benchmark-symbol", default=DEFAULT_BENCHMARK_SYMBOL)
    parser.add_argument("--attack-symbol", default=DEFAULT_ATTACK_SYMBOL)
    parser.add_argument("--active-signal-days", type=int, default=DEFAULT_ACTIVE_SIGNAL_DAYS)
    parser.add_argument(
        "--disable-rebound-confirmation",
        action="store_true",
        help="Notify on active softening/de-escalation context without post-event price confirmation.",
    )
    parser.add_argument("--confirmation-lookback-days", type=int, default=DEFAULT_CONFIRMATION_LOOKBACK_DAYS)
    parser.add_argument(
        "--min-confirmation-trading-days-after-event",
        type=int,
        default=DEFAULT_MIN_CONFIRMATION_TRADING_DAYS_AFTER_EVENT,
    )
    parser.add_argument(
        "--min-benchmark-rebound-from-low",
        type=float,
        default=DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW,
    )
    parser.add_argument("--min-attack-rebound-from-low", type=float, default=DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW)
    parser.add_argument("--min-benchmark-3d-return", type=float, default=DEFAULT_MIN_BENCHMARK_3D_RETURN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.download:
        input_dir = Path(args.output_dir) / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        prices_path = input_dir / "taco_rebound_shadow_price_history.csv"
        prices = download_price_history(
            [args.benchmark_symbol, args.attack_symbol],
            start=args.price_start,
            end=args.price_end,
            proxy=args.download_proxy,
        )
        prices.to_csv(prices_path, index=False)
        price_history = prices
    else:
        price_history = read_table(args.prices)

    payload = build_taco_rebound_shadow_signal(
        price_history,
        events=resolve_trade_war_event_set(args.event_set),
        as_of=args.as_of,
        start_date=args.start_date,
        end_date=args.end_date,
        benchmark_symbol=args.benchmark_symbol,
        attack_symbol=args.attack_symbol,
        active_signal_days=args.active_signal_days,
        require_rebound_confirmation=not args.disable_rebound_confirmation,
        confirmation_lookback_days=args.confirmation_lookback_days,
        min_confirmation_trading_days_after_event=args.min_confirmation_trading_days_after_event,
        min_benchmark_rebound_from_low=args.min_benchmark_rebound_from_low,
        min_attack_rebound_from_low=args.min_attack_rebound_from_low,
        min_benchmark_3d_return=args.min_benchmark_3d_return,
    )
    paths = write_taco_rebound_shadow_outputs(payload, args.output_dir)
    print(
        "wrote TACO rebound shadow signal "
        f"as_of={payload['as_of']} route={payload['canonical_route']} "
        f"action={payload['suggested_action']} latest={paths['latest_signal']}"
    )
    return 0


__all__ = [
    "ACTION_NOTIFY_MANUAL_REVIEW",
    "ROUTE_TACO_REBOUND",
    "SCHEMA_VERSION",
    "TACO_REBOUND_PROFILE",
    "build_taco_rebound_shadow_signal",
    "main",
    "write_taco_rebound_shadow_outputs",
]
