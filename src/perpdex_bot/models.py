from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class BookSide(StrEnum):
    BID = "bid"
    ASK = "ask"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class OrderBookLevel:
    side: BookSide
    price: float
    size: float
    level_index: int

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass(frozen=True)
class MarketSnapshot:
    exchange_id: str
    symbol: str
    timestamp: datetime
    mark_price: float
    index_price: float
    best_bid: float
    best_ask: float
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread_bps(self) -> float:
        return self.spread / self.mid_price * 10_000


@dataclass(frozen=True)
class FundingRate:
    exchange_id: str
    symbol: str
    timestamp: datetime
    rate: float
    next_funding_time: datetime


@dataclass(frozen=True)
class AverageSpread:
    window: str
    avg_spread: float | None
    avg_spread_bps: float | None
    samples: int


@dataclass(frozen=True)
class AverageFundingRate:
    window: str
    avg_rate: float | None
    min_rate: float | None
    max_rate: float | None
    samples: int


@dataclass(frozen=True)
class CollectorMarketStatus:
    exchange_id: str
    symbol: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    last_error: str | None
    next_collection_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class MarketOverviewRow:
    exchange_id: str
    symbol: str
    snapshot: MarketSnapshot | None
    latest_funding_rate: FundingRate | None
    collector_status: CollectorMarketStatus | None


@dataclass(frozen=True)
class SlippageEstimate:
    side: TradeSide
    notional_usd: float
    average_price: float | None
    reference_price: float
    slippage_bps: float | None
    filled_notional: float
    complete: bool


@dataclass(frozen=True)
class OrderSpreadEstimate:
    notional_usd: float
    average_buy_price: float | None
    average_sell_price: float | None
    spread: float | None
    spread_bps: float | None
    buy_filled_notional: float
    sell_filled_notional: float
    complete: bool
