from __future__ import annotations

from datetime import datetime, timezone

from .calculations import estimate_slippage_grid
from .config import DEFAULT_SLIPPAGE_NOTIONALS, STALE_DATA_SECONDS
from .models import (
    AverageFundingRate,
    AverageSpread,
    CollectorMarketStatus,
    FundingRate,
    MarketOverviewRow,
    MarketSnapshot,
    SlippageEstimate,
)


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) <= 10:
        return f"${value:,.4f}"
    return f"${value:,.2f}"


def bps(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f} bps"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.5f}%"


def render_table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    all_rows = [headers, *[tuple(str(cell) for cell in row) for row in rows]]
    widths = [max(len(str(row[col])) for row in all_rows) for col in range(len(headers))]
    lines = []
    lines.append(" | ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(headers)))
    lines.append("-+-".join("-" * width for width in widths))
    for row in rows:
        lines.append(" | ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row)))
    return "\n".join(lines)


def render_snapshot(snapshot: MarketSnapshot) -> str:
    age = datetime.now(timezone.utc) - snapshot.timestamp
    age_seconds = age.total_seconds()
    rows = [
        ("exchange", snapshot.exchange_id),
        ("symbol", snapshot.symbol),
        ("timestamp", snapshot.timestamp.isoformat(timespec="seconds")),
        ("freshness", _freshness_label(age_seconds)),
        ("mark", money(snapshot.mark_price)),
        ("index", money(snapshot.index_price)),
        ("best bid", money(snapshot.best_bid)),
        ("best ask", money(snapshot.best_ask)),
        ("spread", money(snapshot.spread)),
        ("spread bps", bps(snapshot.spread_bps)),
    ]
    return render_table(("metric", "value"), rows)


def _freshness_label(age_seconds: float) -> str:
    label = f"{age_seconds:.0f}s old"
    if age_seconds >= STALE_DATA_SECONDS:
        return f"STALE WARNING: {label}"
    return label


def render_average_spreads(spreads: list[AverageSpread]) -> str:
    return render_table(
        ("window", "avg spread", "avg spread bps", "samples"),
        [
            (
                item.window,
                money(item.avg_spread),
                bps(item.avg_spread_bps),
                item.samples,
            )
            for item in spreads
        ],
    )


def render_funding_history(history: list[FundingRate]) -> str:
    return render_table(
        ("time", "exchange", "symbol", "rate", "next funding"),
        [
            (
                item.timestamp.isoformat(timespec="seconds"),
                item.exchange_id,
                item.symbol,
                pct(item.rate),
                item.next_funding_time.isoformat(timespec="seconds"),
            )
            for item in history
        ],
    )


def render_average_funding_rates(rates: list[AverageFundingRate]) -> str:
    return render_table(
        ("window", "avg rate", "min rate", "max rate", "samples"),
        [
            (
                item.window,
                pct(item.avg_rate),
                pct(item.min_rate),
                pct(item.max_rate),
                item.samples,
            )
            for item in rates
        ],
    )


def render_collector_status(statuses: list[CollectorMarketStatus]) -> str:
    if not statuses:
        return "No collector status rows found. Run `collect-live --once` first."
    return render_table(
        (
            "exchange",
            "symbol",
            "last success",
            "last failure",
            "failures",
            "next collection",
            "last error",
        ),
        [
            (
                item.exchange_id,
                item.symbol,
                _fmt_time(item.last_success_at),
                _fmt_time(item.last_failure_at),
                item.consecutive_failures,
                _fmt_time(item.next_collection_at),
                item.last_error or "",
            )
            for item in statuses
        ],
    )


def render_market_overview(rows: list[MarketOverviewRow], log_path: str | None = None) -> str:
    if not rows:
        return "No enabled markets found in config/markets.json."

    sections = [
        "PerpDEX Market Overview",
        render_table(
            (
                "exchange",
                "symbol",
                "status",
                "latest timestamp",
                "freshness",
                "mark",
                "best bid",
                "best ask",
                "spread",
                "spread bps",
                "funding",
                "failures",
                "last error",
            ),
            [_overview_row(item) for item in rows],
        ),
    ]
    if log_path:
        sections.extend(("", f"collector log: {log_path}"))
    return "\n".join(sections)


def _overview_row(item: MarketOverviewRow) -> tuple[object, ...]:
    snapshot = item.snapshot
    status = item.collector_status
    funding = item.latest_funding_rate
    if snapshot is None:
        market_status = "NO DATA"
        timestamp = "n/a"
        freshness = "n/a"
        mark = "n/a"
        best_bid = "n/a"
        best_ask = "n/a"
        spread = "n/a"
        spread_bps = "n/a"
    else:
        age_seconds = (datetime.now(timezone.utc) - snapshot.timestamp).total_seconds()
        market_status = "STALE" if age_seconds >= STALE_DATA_SECONDS else "OK"
        timestamp = _fmt_time(snapshot.timestamp)
        freshness = _freshness_label(age_seconds)
        mark = money(snapshot.mark_price)
        best_bid = money(snapshot.best_bid)
        best_ask = money(snapshot.best_ask)
        spread = money(snapshot.spread)
        spread_bps = bps(snapshot.spread_bps)

    if status and status.consecutive_failures > 0:
        market_status = f"{market_status}+FAIL"

    return (
        item.exchange_id,
        item.symbol,
        market_status,
        timestamp,
        freshness,
        mark,
        best_bid,
        best_ask,
        spread,
        spread_bps,
        pct(None if funding is None else funding.rate),
        "" if status is None else status.consecutive_failures,
        "" if status is None else status.last_error or "",
    )


def _fmt_time(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.isoformat(timespec="seconds")


def render_slippage(estimates: list[SlippageEstimate]) -> str:
    return render_table(
        ("side", "notional", "avg price", "slippage", "filled", "complete"),
        [
            (
                item.side.value,
                money(item.notional_usd),
                money(item.average_price),
                bps(item.slippage_bps),
                money(item.filled_notional),
                "yes" if item.complete else "no",
            )
            for item in estimates
        ],
    )


def render_dashboard(
    snapshot: MarketSnapshot,
    average_spreads: list[AverageSpread],
    average_funding_rates: list[AverageFundingRate],
) -> str:
    slippage = estimate_slippage_grid(
        DEFAULT_SLIPPAGE_NOTIONALS,
        reference_price=snapshot.mid_price,
        bids=snapshot.bids,
        asks=snapshot.asks,
    )
    sections = [
        "PerpDEX Dashboard",
        "",
        "[Current Market]",
        render_snapshot(snapshot),
        "",
        "[Average Spread]",
        render_average_spreads(average_spreads),
        "",
        "[Estimated Slippage]",
        render_slippage(slippage),
        "",
        "[Historical Average Funding Rate]",
        render_average_funding_rates(average_funding_rates),
    ]
    return "\n".join(sections)
