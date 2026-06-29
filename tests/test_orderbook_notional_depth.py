from __future__ import annotations

from datetime import datetime, timezone

import pytest

from perpdex_bot.collectors import trim_snapshot_to_notional_depth
from perpdex_bot.models import BookSide, MarketSnapshot, OrderBookLevel


def test_trim_snapshot_to_notional_depth_keeps_levels_until_target_is_reached() -> None:
    snapshot = _snapshot(
        bids=(
            OrderBookLevel(BookSide.BID, price=100.0, size=400.0, level_index=0),
            OrderBookLevel(BookSide.BID, price=99.0, size=350.0, level_index=1),
            OrderBookLevel(BookSide.BID, price=98.0, size=500.0, level_index=2),
        ),
        asks=(
            OrderBookLevel(BookSide.ASK, price=101.0, size=300.0, level_index=0),
            OrderBookLevel(BookSide.ASK, price=102.0, size=700.0, level_index=1),
            OrderBookLevel(BookSide.ASK, price=103.0, size=900.0, level_index=2),
        ),
    )

    trimmed = trim_snapshot_to_notional_depth(snapshot, 100_000)

    assert len(trimmed.bids) == 3
    assert len(trimmed.asks) == 2
    assert sum(level.notional for level in trimmed.bids) >= 100_000
    assert sum(level.notional for level in trimmed.asks) >= 100_000


def test_trim_snapshot_to_notional_depth_keeps_first_level_when_it_exceeds_target() -> None:
    snapshot = _snapshot(
        bids=(
            OrderBookLevel(BookSide.BID, price=100.0, size=2_000.0, level_index=0),
            OrderBookLevel(BookSide.BID, price=99.0, size=350.0, level_index=1),
        ),
        asks=(
            OrderBookLevel(BookSide.ASK, price=101.0, size=1_500.0, level_index=0),
            OrderBookLevel(BookSide.ASK, price=102.0, size=700.0, level_index=1),
        ),
    )

    trimmed = trim_snapshot_to_notional_depth(snapshot, 100_000)

    assert len(trimmed.bids) == 1
    assert len(trimmed.asks) == 1


def test_trim_snapshot_to_notional_depth_rejects_zero_or_negative_target() -> None:
    with pytest.raises(ValueError):
        trim_snapshot_to_notional_depth(_snapshot(), 0)


def _snapshot(
    bids: tuple[OrderBookLevel, ...] = (
        OrderBookLevel(BookSide.BID, price=100.0, size=1.0, level_index=0),
    ),
    asks: tuple[OrderBookLevel, ...] = (
        OrderBookLevel(BookSide.ASK, price=101.0, size=1.0, level_index=0),
    ),
) -> MarketSnapshot:
    return MarketSnapshot(
        exchange_id="Test",
        symbol="BTC-PERP",
        timestamp=datetime(2026, 6, 29, tzinfo=timezone.utc),
        mark_price=100.5,
        index_price=100.4,
        best_bid=100.0,
        best_ask=101.0,
        bids=bids,
        asks=asks,
    )
