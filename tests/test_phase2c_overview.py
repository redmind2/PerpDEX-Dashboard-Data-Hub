from __future__ import annotations

from datetime import datetime, timedelta, timezone

from perpdex_bot.dashboard import render_market_overview
from perpdex_bot.models import (
    BookSide,
    CollectorMarketStatus,
    FundingRate,
    MarketOverviewRow,
    MarketSnapshot,
    OrderBookLevel,
)


def _snapshot(symbol: str, timestamp: datetime, exchange_id: str = "Hibachi") -> MarketSnapshot:
    return MarketSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=100.5,
        index_price=100.25,
        best_bid=100.0,
        best_ask=101.0,
        bids=(OrderBookLevel(BookSide.BID, price=100.0, size=1.0, level_index=0),),
        asks=(OrderBookLevel(BookSide.ASK, price=101.0, size=1.0, level_index=0),),
    )


def test_overview_renderer_shows_latest_market_values() -> None:
    now = datetime.now(timezone.utc)
    output = render_market_overview(
        [
            MarketOverviewRow(
                exchange_id="Hibachi",
                symbol="BTC-PERP",
                snapshot=_snapshot("BTC-PERP", now),
                latest_funding_rate=FundingRate(
                    exchange_id="Hibachi",
                    symbol="BTC-PERP",
                    timestamp=now,
                    rate=0.0001,
                    next_funding_time=now + timedelta(hours=8),
                ),
                collector_status=None,
            )
        ],
        "data/logs/collector.log",
    )

    assert "PerpDEX Market Overview" in output
    assert "BTC-PERP" in output
    assert "OK" in output
    assert "$100.50" in output
    assert "$100.00" in output
    assert "$101.00" in output
    assert "99.50 bps" in output
    assert "0.01000%" in output
    assert "collector log: data/logs/collector.log" in output


def test_overview_renderer_marks_stale_market() -> None:
    old = datetime.now(timezone.utc) - timedelta(minutes=4)
    output = render_market_overview(
        [
            MarketOverviewRow(
                exchange_id="Hibachi",
                symbol="ETH-PERP",
                snapshot=_snapshot("ETH-PERP", old),
                latest_funding_rate=None,
                collector_status=None,
            )
        ]
    )

    assert "ETH-PERP" in output
    assert "STALE" in output
    assert "STALE WARNING" in output


def test_overview_renderer_marks_failed_market() -> None:
    now = datetime.now(timezone.utc)
    output = render_market_overview(
        [
            MarketOverviewRow(
                exchange_id="Hibachi",
                symbol="EUR-PERP",
                snapshot=_snapshot("EUR-PERP", now),
                latest_funding_rate=None,
                collector_status=CollectorMarketStatus(
                    exchange_id="Hibachi",
                    symbol="EUR-PERP",
                    last_success_at=now - timedelta(minutes=1),
                    last_failure_at=now,
                    consecutive_failures=2,
                    last_error="ValueError: bad orderbook",
                    next_collection_at=now + timedelta(minutes=1),
                    updated_at=now,
                ),
            )
        ]
    )

    assert "EUR-PERP" in output
    assert "OK+FAIL" in output
    assert "ValueError: bad orderbook" in output
    assert "2" in output


def test_overview_renderer_shows_no_data_market() -> None:
    output = render_market_overview(
        [
            MarketOverviewRow(
                exchange_id="Hibachi",
                symbol="BTC-PERP",
                snapshot=None,
                latest_funding_rate=None,
                collector_status=None,
            )
        ]
    )

    assert "BTC-PERP" in output
    assert "NO DATA" in output


def test_overview_renderer_shows_multiple_exchanges() -> None:
    now = datetime.now(timezone.utc)
    output = render_market_overview(
        [
            MarketOverviewRow(
                exchange_id="Hibachi",
                symbol="BTC-PERP",
                snapshot=_snapshot("BTC-PERP", now, "Hibachi"),
                latest_funding_rate=None,
                collector_status=None,
            ),
            MarketOverviewRow(
                exchange_id="Rise",
                symbol="BTC-PERP",
                snapshot=_snapshot("BTC-PERP", now, "Rise"),
                latest_funding_rate=FundingRate(
                    exchange_id="Rise",
                    symbol="BTC-PERP",
                    timestamp=now,
                    rate=0.00008,
                    next_funding_time=now + timedelta(hours=8),
                ),
                collector_status=None,
            ),
        ]
    )

    assert "Hibachi" in output
    assert "Rise" in output
    assert output.count("BTC-PERP") == 2
    assert "0.00800%" in output
