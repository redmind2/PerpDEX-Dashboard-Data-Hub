from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .mock_data import seed_mock_data
from .models import FundingRate, MarketSnapshot
from .repositories import MarketDataRepository


@dataclass(frozen=True)
class PublicAPISettings:
    timeout_seconds: float = 10.0
    retries: int = 3
    retry_backoff_seconds: float = 1.0
    request_spacing_seconds: float = 0.25
    orderbook_depth_limit: int = 100
    orderbook_granularity: float = 0.1


@dataclass(frozen=True)
class CollectorResult:
    snapshot: MarketSnapshot
    funding_rates: tuple[FundingRate, ...]


class Collector(ABC):
    exchange_id: str

    @abstractmethod
    async def collect_once(self, symbol: str) -> CollectorResult:
        """Fetch one public market-data sample for an internal symbol."""


class LivePublicCollector(Collector, ABC):
    """Base class for collectors that only read public, unsigned endpoints."""


class MockCollector(Collector):
    exchange_id = "Mock"

    def __init__(self, repo: MarketDataRepository) -> None:
        self.repo = repo

    async def collect_once(self, symbol: str) -> CollectorResult:
        await seed_mock_data(self.repo, symbols=(symbol,), exchanges=(self.exchange_id,))
        snapshot = await self.repo.latest_snapshot(self.exchange_id, symbol)
        funding = await self.repo.funding_history(self.exchange_id, symbol, limit=24)
        if snapshot is None:
            raise RuntimeError("Mock data collection did not create a snapshot")
        return CollectorResult(snapshot=snapshot, funding_rates=tuple(funding))
