from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import (
    DEFAULT_COLLECTOR_LOG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_MARKET_CONFIG_PATH,
    DEFAULT_SLIPPAGE_NOTIONALS,
    MARKET_RETENTION_DAYS,
    MARKET_SNAPSHOT_INTERVAL_SECONDS,
    MarketConfig,
    load_market_config,
)
from .calculations import estimate_slippage_grid
from .dashboard import (
    render_average_spreads,
    render_average_funding_rates,
    render_collector_status,
    render_dashboard,
    render_funding_history,
    render_market_overview,
    render_slippage,
    render_snapshot,
)
from .db import AsyncSQLite
from .collectors import LivePublicCollector, PublicAPISettings
from .exchanges import create_public_collector, supported_public_exchanges
from .mock_data import seed_mock_data
from .models import CollectorMarketStatus, MarketOverviewRow, utc_now
from .repositories import MarketDataRepository


LOGGER = logging.getLogger("perpdex_bot.collector")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PerpDEX public market data hub CLI")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create or migrate the local SQLite database schema")

    seed = sub.add_parser("seed-mock", help="Insert deterministic mock market and funding data")
    seed.add_argument("--seed", type=int, default=42, help="Random seed for deterministic mock data")

    collect_live = sub.add_parser("collect-live", help="Collect public exchange data into SQLite")
    collect_live.add_argument("--exchange", default="Hibachi", choices=supported_public_exchanges())
    collect_live.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="Internal symbol, for example BTC-PERP. Can be passed more than once.",
    )
    collect_live.add_argument("--config", type=Path, default=DEFAULT_MARKET_CONFIG_PATH)
    collect_live.add_argument("--interval", type=int, default=MARKET_SNAPSHOT_INTERVAL_SECONDS)
    collect_live.add_argument("--once", action="store_true", help="Collect one sample and exit")
    collect_live.add_argument("--depth", type=int, default=100)
    collect_live.add_argument("--granularity", type=float, default=0.1)
    collect_live.add_argument("--timeout", type=float, default=10.0)
    collect_live.add_argument("--retries", type=int, default=3)
    collect_live.add_argument("--log-file", type=Path, default=DEFAULT_COLLECTOR_LOG_PATH)

    dashboard = sub.add_parser("dashboard", help="Show current market, spread, funding, and slippage")
    _add_market_filters(dashboard)

    spreads = sub.add_parser("spreads", help="Show current and average spreads")
    _add_market_filters(spreads)

    funding = sub.add_parser("funding", help="Show historical average funding rates")
    _add_market_filters(funding)

    funding_history = sub.add_parser("funding-history", help="Show raw funding history rows")
    _add_market_filters(funding_history)
    funding_history.add_argument("--limit", type=int, default=24)

    slippage = sub.add_parser("slippage", help="Show $10k to $1M estimated slippage")
    _add_market_filters(slippage)

    prune = sub.add_parser("prune", help="Delete market/orderbook data older than retention")
    prune.add_argument("--days", type=int, default=MARKET_RETENTION_DAYS)

    sub.add_parser("storage", help="Show DB row counts and retention policy")

    collector_status = sub.add_parser("collector-status", help="Show public collector health by market")
    _add_optional_market_filters(collector_status)
    collector_status.add_argument("--failed-only", action="store_true", help="Only show markets with active failures")

    status = sub.add_parser("status", help="Alias for collector-status")
    _add_optional_market_filters(status)
    status.add_argument("--failed-only", action="store_true", help="Only show markets with active failures")

    overview = sub.add_parser("overview", help="Show enabled markets in one public-data overview")
    overview.add_argument("--config", type=Path, default=DEFAULT_MARKET_CONFIG_PATH)
    overview.add_argument("--failed-only", action="store_true", help="Only show markets with active failures")
    overview.add_argument("--log-file", type=Path, default=DEFAULT_COLLECTOR_LOG_PATH)

    markets = sub.add_parser("markets", help="Alias for overview")
    markets.add_argument("--config", type=Path, default=DEFAULT_MARKET_CONFIG_PATH)
    markets.add_argument("--failed-only", action="store_true", help="Only show markets with active failures")
    markets.add_argument("--log-file", type=Path, default=DEFAULT_COLLECTOR_LOG_PATH)
    return parser


def _add_market_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--exchange", default=None, help="Exchange id filter, for example GRVT")
    parser.add_argument("--symbol", default="BTC-PERP", help="Internal symbol, for example BTC-PERP")


def _add_optional_market_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--exchange", default=None, help="Exchange id filter, for example Hibachi")
    parser.add_argument("--symbol", default=None, help="Internal symbol, for example BTC-PERP")


async def run(args: argparse.Namespace) -> None:
    async with AsyncSQLite(args.db) as db:
        await db.initialize()
        repo = MarketDataRepository(db)

        if args.command == "init-db":
            print(f"Initialized database: {args.db}")
            return

        if args.command == "seed-mock":
            result = await seed_mock_data(repo, seed=args.seed)
            print(
                "Seeded mock data: "
                f"{result.snapshots:,} market snapshots, "
                f"{result.funding_rates:,} funding rates"
            )
            return

        if args.command == "collect-live":
            await _run_live_collection(args, repo)
            return

        if args.command == "prune":
            deleted = await repo.prune_market_data(args.days)
            print(f"Pruned {deleted:,} market snapshots older than {args.days} days")
            return

        if args.command == "storage":
            snapshots = await repo.snapshot_count()
            levels = await repo.orderbook_level_count()
            funding = await repo.funding_count()
            print("DB Storage")
            print(f"- market snapshots: {snapshots:,}")
            print(f"- orderbook levels: {levels:,}")
            print(f"- funding rates: {funding:,}")
            print(f"- default market retention: {MARKET_RETENTION_DAYS} days")
            print("- intended market collection cadence: 60 seconds")
            return

        if args.command in {"collector-status", "status"}:
            statuses = await repo.collector_statuses(args.exchange, args.symbol)
            if args.failed_only:
                statuses = [item for item in statuses if item.consecutive_failures > 0]
                if not statuses:
                    print("No markets with active collector failures.")
                    return
            print(render_collector_status(statuses))
            return

        if args.command in {"overview", "markets"}:
            rows = await _market_overview_rows(args, repo)
            if args.failed_only:
                rows = [
                    item
                    for item in rows
                    if item.collector_status is not None
                    and item.collector_status.consecutive_failures > 0
                ]
                if not rows:
                    print("No markets with active collector failures.")
                    return
            print(render_market_overview(rows, str(args.log_file)))
            return

        snapshot = await repo.latest_snapshot(args.exchange, args.symbol)
        if snapshot is None:
            raise SystemExit("No market data found. Run `perpdex seed-mock` first.")

        if args.command == "dashboard":
            average_spreads = await repo.average_spreads(args.exchange, args.symbol)
            funding = await repo.average_funding_rates(args.exchange, args.symbol)
            print(render_dashboard(snapshot, average_spreads, funding))
            return

        if args.command == "spreads":
            average_spreads = await repo.average_spreads(args.exchange, args.symbol)
            print("[Current Spread]")
            print(render_snapshot(snapshot))
            print()
            print("[Average Spread]")
            print(render_average_spreads(average_spreads))
            return

        if args.command == "funding":
            history = await repo.average_funding_rates(args.exchange, args.symbol)
            print("[Historical Average Funding Rate]")
            print(render_average_funding_rates(history))
            return

        if args.command == "funding-history":
            history = await repo.funding_history(args.exchange, args.symbol, args.limit)
            print(render_funding_history(history))
            return

        if args.command == "slippage":
            estimates = estimate_slippage_grid(
                DEFAULT_SLIPPAGE_NOTIONALS,
                reference_price=snapshot.mid_price,
                bids=snapshot.bids,
                asks=snapshot.asks,
            )
            print(render_slippage(estimates))
            return

        raise SystemExit(f"Unknown command: {args.command}")


async def _run_live_collection(args: argparse.Namespace, repo: MarketDataRepository) -> None:
    _configure_collector_logging(args.log_file)
    settings = PublicAPISettings(
        timeout_seconds=args.timeout,
        retries=args.retries,
        orderbook_depth_limit=args.depth,
        orderbook_granularity=args.granularity,
    )
    collector = create_public_collector(args.exchange, settings)

    markets = _market_targets(args)
    while True:
        pass_started_at = utc_now()
        next_collection_at = pass_started_at + _seconds(args.interval)
        for market in markets:
            if market.exchange_id != collector.exchange_id:
                continue
            for symbol in market.symbols:
                await _collect_market_once(
                    collector=collector,
                    repo=repo,
                    symbol=symbol,
                    next_collection_at=next_collection_at,
                )
        if args.once:
            return
        await asyncio.sleep(args.interval)


async def _collect_market_once(
    collector: LivePublicCollector,
    repo: MarketDataRepository,
    symbol: str,
    next_collection_at: datetime,
) -> None:
    exchange_id = collector.exchange_id
    try:
        result = await collector.collect_once(symbol)
        await repo.save_snapshot(result.snapshot)
        saved_funding = 0
        for funding in result.funding_rates:
            if await repo.save_funding_rate_if_new(funding) is not None:
                saved_funding += 1
        collected_at = utc_now()
        await repo.mark_collection_success(
            result.snapshot.exchange_id,
            result.snapshot.symbol,
            collected_at,
            next_collection_at,
        )
        message = (
            "Collected public data: "
            f"{result.snapshot.exchange_id} {result.snapshot.symbol} "
            f"spread={result.snapshot.spread_bps:.2f} bps "
            f"funding_rows={saved_funding}"
        )
        LOGGER.info(message)
        print(message)
    except Exception as exc:
        failed_at = utc_now()
        error_message = f"{type(exc).__name__}: {exc}"
        await repo.mark_collection_failure(
            exchange_id,
            symbol,
            failed_at,
            error_message,
            next_collection_at,
        )
        LOGGER.exception("Failed to collect public data: %s %s", exchange_id, symbol)
        print(f"Collection failed: {exchange_id} {symbol} error={error_message}")


def _market_targets(args: argparse.Namespace) -> list[MarketConfig]:
    if args.symbol:
        return [MarketConfig(exchange_id=args.exchange, symbols=tuple(_normalize_symbols(args.symbol)))]
    markets = [
        market
        for market in load_market_config(args.config)
        if market.exchange_id == args.exchange
    ]
    if not markets:
        raise SystemExit(f"No enabled markets found for exchange {args.exchange} in {args.config}")
    return markets


async def _market_overview_rows(
    args: argparse.Namespace,
    repo: MarketDataRepository,
) -> list[MarketOverviewRow]:
    rows: list[MarketOverviewRow] = []
    for market in load_market_config(args.config):
        for symbol in market.symbols:
            statuses = await repo.collector_statuses(market.exchange_id, symbol)
            rows.append(
                MarketOverviewRow(
                    exchange_id=market.exchange_id,
                    symbol=symbol,
                    snapshot=await repo.latest_snapshot(market.exchange_id, symbol),
                    latest_funding_rate=await repo.latest_funding_rate(market.exchange_id, symbol),
                    collector_status=_first_status(statuses),
                )
            )
    return rows


def _first_status(statuses: list[CollectorMarketStatus]) -> CollectorMarketStatus | None:
    return statuses[0] if statuses else None


def _normalize_symbols(raw_symbols: list[str]) -> list[str]:
    symbols: list[str] = []
    for raw in raw_symbols:
        symbols.extend(part.strip().upper() for part in raw.split(",") if part.strip())
    return symbols


def _seconds(value: int) -> timedelta:
    return timedelta(seconds=value)


def _configure_collector_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    LOGGER.addHandler(handler)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))
