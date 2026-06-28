from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import BookSide, FundingRate, MarketSnapshot, OrderBookLevel
from .repositories import MarketDataRepository


@dataclass(frozen=True)
class MockSeedResult:
    snapshots: int
    funding_rates: int


SYMBOL_BASE_PRICES = {
    "BTC-PERP": 104_000.0,
    "ETH-PERP": 3_600.0,
}

EXCHANGES = ("Hibachi", "Hotstuff", "Evedex", "Rise")


async def seed_mock_data(
    repo: MarketDataRepository,
    symbols: tuple[str, ...] = ("BTC-PERP", "ETH-PERP"),
    exchanges: tuple[str, ...] = EXCHANGES,
    now: datetime | None = None,
    seed: int = 42,
) -> MockSeedResult:
    rng = random.Random(seed)
    current_time = now or datetime.now(timezone.utc)
    timestamps = _build_timestamps(current_time)
    snapshot_count = 0
    funding_count = 0

    for exchange in exchanges:
        exchange_offset = rng.uniform(-8, 8)
        for symbol in symbols:
            base_price = SYMBOL_BASE_PRICES.get(symbol, 1_000.0)
            for idx, timestamp in enumerate(timestamps):
                snapshot = _make_snapshot(
                    exchange=exchange,
                    symbol=symbol,
                    timestamp=timestamp,
                    base_price=base_price,
                    exchange_offset=exchange_offset,
                    step=idx,
                    rng=rng,
                )
                await repo.save_snapshot(snapshot)
                snapshot_count += 1

            funding_points = _funding_timestamps(current_time)
            for idx, timestamp in enumerate(funding_points):
                funding = _make_funding(exchange, symbol, timestamp, idx, rng)
                await repo.save_funding_rate(funding)
                funding_count += 1

    return MockSeedResult(snapshots=snapshot_count, funding_rates=funding_count)


def _build_timestamps(now: datetime) -> list[datetime]:
    start = now - timedelta(days=30)
    hourly = [start + timedelta(hours=i) for i in range(30 * 24)]
    recent = [now - timedelta(minutes=i) for i in range(120, -1, -1)]
    merged = sorted({value.replace(microsecond=0) for value in (*hourly, *recent, now)})
    return merged


def _funding_timestamps(now: datetime) -> list[datetime]:
    start = now - timedelta(days=30)
    return [start + timedelta(hours=8 * i) for i in range((30 * 24) // 8 + 1)]


def _make_snapshot(
    exchange: str,
    symbol: str,
    timestamp: datetime,
    base_price: float,
    exchange_offset: float,
    step: int,
    rng: random.Random,
) -> MarketSnapshot:
    wave = math.sin(step / 18) * base_price * 0.0015
    drift = math.sin(step / 210) * base_price * 0.004
    noise = rng.uniform(-base_price * 0.0004, base_price * 0.0004)
    mid = base_price + exchange_offset + wave + drift + noise
    spread_bps = 1.2 + abs(math.sin(step / 11)) * 2.8 + rng.uniform(0, 0.6)
    half_spread = mid * (spread_bps / 10_000) / 2
    best_bid = mid - half_spread
    best_ask = mid + half_spread
    bids = _levels(BookSide.BID, best_bid, rng)
    asks = _levels(BookSide.ASK, best_ask, rng)
    return MarketSnapshot(
        exchange_id=exchange,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=mid + rng.uniform(-half_spread, half_spread),
        index_price=mid + rng.uniform(-base_price * 0.0002, base_price * 0.0002),
        best_bid=best_bid,
        best_ask=best_ask,
        bids=bids,
        asks=asks,
    )


def _levels(side: BookSide, top_price: float, rng: random.Random) -> tuple[OrderBookLevel, ...]:
    levels: list[OrderBookLevel] = []
    price = top_price
    for idx in range(40):
        step_bps = 0.8 + idx * 0.55 + rng.uniform(0, 0.25)
        if idx > 0:
            price = top_price * (1 - step_bps / 10_000 if side == BookSide.BID else 1 + step_bps / 10_000)
        target_notional = 35_000 + idx * 18_000 + rng.uniform(0, 12_000)
        size = target_notional / price
        levels.append(OrderBookLevel(side=side, price=price, size=size, level_index=idx))
    return tuple(levels)


def _make_funding(
    exchange: str,
    symbol: str,
    timestamp: datetime,
    step: int,
    rng: random.Random,
) -> FundingRate:
    rate = 0.00004 * math.sin(step / 4) + rng.uniform(-0.000025, 0.000025)
    return FundingRate(
        exchange_id=exchange,
        symbol=symbol,
        timestamp=timestamp,
        rate=rate,
        next_funding_time=timestamp + timedelta(hours=8),
    )
