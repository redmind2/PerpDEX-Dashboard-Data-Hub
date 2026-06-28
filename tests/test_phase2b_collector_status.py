from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from perpdex_bot.config import DEFAULT_LIVE_MARKETS, load_market_config
from perpdex_bot.dashboard import render_average_spreads, render_collector_status, render_snapshot
from perpdex_bot.db import AsyncSQLite
from perpdex_bot.models import AverageSpread, BookSide, MarketSnapshot, OrderBookLevel
from perpdex_bot.repositories import MarketDataRepository


def test_market_config_loads_hibachi_symbols(tmp_path) -> None:
    config_path = tmp_path / "markets.json"
    config_path.write_text(
        """
        {
          "markets": [
            {
              "exchange": "Hibachi",
              "enabled": true,
              "symbols": ["btc-perp", "ETH-PERP", "EUR-PERP"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    configs = load_market_config(config_path)

    assert len(configs) == 1
    assert configs[0].exchange_id == "Hibachi"
    assert configs[0].symbols == ("BTC-PERP", "ETH-PERP", "EUR-PERP")


def test_market_config_loads_multiple_exchanges(tmp_path) -> None:
    config_path = tmp_path / "markets.json"
    config_path.write_text(
        """
        {
          "markets": [
            {"exchange": "Hibachi", "enabled": true, "symbols": ["BTC-PERP"]},
            {"exchange": "Rise", "enabled": true, "symbols": ["btc-perp"]}
          ]
        }
        """,
        encoding="utf-8",
    )

    configs = load_market_config(config_path)

    assert [(item.exchange_id, item.symbols) for item in configs] == [
        ("Hibachi", ("BTC-PERP",)),
        ("Rise", ("BTC-PERP",)),
    ]


def test_market_config_defaults_when_file_is_missing(tmp_path) -> None:
    configs = load_market_config(tmp_path / "missing.json")

    assert configs[0].exchange_id == "Hibachi"
    assert configs[0].symbols == DEFAULT_LIVE_MARKETS


def test_collector_status_tracks_success_and_failures(tmp_path) -> None:
    async def scenario() -> None:
        async with AsyncSQLite(tmp_path / "status.sqlite") as db:
            await db.initialize()
            repo = MarketDataRepository(db)
            now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
            next_at = now + timedelta(seconds=60)

            await repo.mark_collection_failure(
                "Hibachi",
                "ETH-PERP",
                now,
                "RuntimeError: first failure",
                next_at,
            )
            await repo.mark_collection_failure(
                "Hibachi",
                "ETH-PERP",
                now + timedelta(seconds=1),
                "RuntimeError: second failure",
                next_at + timedelta(seconds=1),
            )
            statuses = await repo.collector_statuses("Hibachi", "ETH-PERP")

            assert statuses[0].consecutive_failures == 2
            assert statuses[0].last_success_at is None
            assert statuses[0].last_error == "RuntimeError: second failure"

            await repo.mark_collection_success(
                "Hibachi",
                "ETH-PERP",
                now + timedelta(seconds=2),
                next_at + timedelta(seconds=2),
            )
            statuses = await repo.collector_statuses("Hibachi", "ETH-PERP")

            assert statuses[0].consecutive_failures == 0
            assert statuses[0].last_success_at == now + timedelta(seconds=2)
            assert statuses[0].last_error is None

    asyncio.run(scenario())


def test_collector_status_renderer_includes_error() -> None:
    async def scenario() -> str:
        async with AsyncSQLite(":memory:") as db:
            await db.initialize()
            repo = MarketDataRepository(db)
            now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
            await repo.mark_collection_failure(
                "Hibachi",
                "SOL-PERP",
                now,
                "ValueError: bad payload",
                now + timedelta(seconds=60),
            )
            return render_collector_status(await repo.collector_statuses())

    output = asyncio.run(scenario())

    assert "SOL-PERP" in output
    assert "ValueError: bad payload" in output


def test_stale_snapshot_warning_is_rendered() -> None:
    old = datetime.now(timezone.utc) - timedelta(minutes=4)
    snapshot = MarketSnapshot(
        exchange_id="Hibachi",
        symbol="BTC-PERP",
        timestamp=old,
        mark_price=100.0,
        index_price=99.5,
        best_bid=99.0,
        best_ask=101.0,
        bids=(OrderBookLevel(BookSide.BID, price=99.0, size=1.0, level_index=0),),
        asks=(OrderBookLevel(BookSide.ASK, price=101.0, size=1.0, level_index=0),),
    )

    assert "STALE WARNING" in render_snapshot(snapshot)


def test_small_market_values_show_four_decimals() -> None:
    now = datetime.now(timezone.utc)
    snapshot = MarketSnapshot(
        exchange_id="Hibachi",
        symbol="EUR-PERP",
        timestamp=now,
        mark_price=1.14047,
        index_price=1.14003,
        best_bid=1.14047,
        best_ask=1.14048,
        bids=(OrderBookLevel(BookSide.BID, price=1.14047, size=1.0, level_index=0),),
        asks=(OrderBookLevel(BookSide.ASK, price=1.14048, size=1.0, level_index=0),),
    )

    rendered_snapshot = render_snapshot(snapshot)
    rendered_spreads = render_average_spreads(
        [AverageSpread("1m", avg_spread=0.00001, avg_spread_bps=0.0877, samples=1)]
    )

    assert "$1.1405" in rendered_snapshot
    assert "$0.0000" in rendered_spreads
    assert "0.09 bps" in rendered_spreads
