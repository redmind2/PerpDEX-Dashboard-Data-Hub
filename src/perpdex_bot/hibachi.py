from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .collectors import CollectorResult, LivePublicCollector, PublicAPISettings
from .models import BookSide, FundingRate, MarketSnapshot, OrderBookLevel


HIBACHI_DATA_BASE_URL = "https://data-api.hibachi.xyz"
HIBACHI_SYMBOLS = {
    "BTC-PERP": "BTC/USDT-P",
    "ETH-PERP": "ETH/USDT-P",
    "EUR-PERP": "EUR/USDT-P",
    "SOL-PERP": "SOL/USDT-P",
}
HIBACHI_ORDERBOOK_GRANULARITIES = {
    "EUR-PERP": 0.0001,
}


class HibachiPublicClient:
    def __init__(
        self,
        base_url: str = HIBACHI_DATA_BASE_URL,
        settings: PublicAPISettings | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.settings = settings or PublicAPISettings()
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()

    async def get_json(self, path: str, params: dict[str, object] | None = None) -> Any:
        await self._respect_spacing()
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        for attempt in range(1, self.settings.retries + 1):
            try:
                return await asyncio.to_thread(self._get_json_sync, url)
            except HTTPError as exc:
                if exc.code == 429 and attempt < self.settings.retries:
                    await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
                    continue
                if 500 <= exc.code < 600 and attempt < self.settings.retries:
                    await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
                    continue
                raise
            except (TimeoutError, URLError) as exc:
                if attempt >= self.settings.retries:
                    raise RuntimeError(f"Hibachi public API request failed: {exc}") from exc
                await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("Hibachi public API request failed after retries")

    def _get_json_sync(self, url: str) -> Any:
        request = Request(url, headers={"User-Agent": "perpdex-phase2a-public-collector/0.1"})
        with urlopen(request, timeout=self.settings.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))

    async def _respect_spacing(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self.settings.request_spacing_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()


class HibachiPublicCollector(LivePublicCollector):
    exchange_id = "Hibachi"

    def __init__(self, client: HibachiPublicClient | None = None) -> None:
        self.client = client or HibachiPublicClient()

    async def collect_once(self, symbol: str) -> CollectorResult:
        hibachi_symbol = to_hibachi_symbol(symbol)
        granularity = orderbook_granularity_for(symbol, self.client.settings.orderbook_granularity)
        orderbook, prices = await asyncio.gather(
            self.client.get_json(
                "/market/data/orderbook",
                {
                    "symbol": hibachi_symbol,
                    "depth": self.client.settings.orderbook_depth_limit,
                    "granularity": granularity,
                },
            ),
            self.client.get_json("/market/data/prices", {"symbol": hibachi_symbol}),
        )
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = _snapshot_from_payload(self.exchange_id, symbol, timestamp, orderbook, prices)
        funding = _funding_from_prices(self.exchange_id, symbol, timestamp, prices)
        return CollectorResult(snapshot=snapshot, funding_rates=(funding,))


def to_hibachi_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("_", "-").replace("/", "-")
    return HIBACHI_SYMBOLS.get(normalized, symbol)


def orderbook_granularity_for(symbol: str, default: float) -> float:
    normalized = symbol.upper().replace("_", "-").replace("/", "-")
    return HIBACHI_ORDERBOOK_GRANULARITIES.get(normalized, default)


def _snapshot_from_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    orderbook: dict[str, Any],
    prices: dict[str, Any],
) -> MarketSnapshot:
    bids = _levels(_orderbook_side_levels(orderbook, "bid"), BookSide.BID)
    asks = _levels(_orderbook_side_levels(orderbook, "ask"), BookSide.ASK)
    if not bids or not asks:
        raise ValueError("Hibachi orderbook response did not include both bids and asks")
    return MarketSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=float(prices["markPrice"]),
        index_price=float(prices["spotPrice"]),
        best_bid=bids[0].price,
        best_ask=asks[0].price,
        bids=bids,
        asks=asks,
    )


def _orderbook_side_levels(orderbook: object, side: str) -> object:
    if not isinstance(orderbook, dict):
        return ()
    side_payload = orderbook.get(side)
    if not isinstance(side_payload, dict):
        return ()
    return side_payload.get("levels", ())


def _levels(raw_levels: object, side: BookSide) -> tuple[OrderBookLevel, ...]:
    parsed = []
    for level in raw_levels if isinstance(raw_levels, list) else []:
        parsed.append((float(level["price"]), float(level["quantity"])))
    parsed.sort(key=lambda item: item[0], reverse=side == BookSide.BID)
    return tuple(
        OrderBookLevel(side=side, price=price, size=size, level_index=idx)
        for idx, (price, size) in enumerate(parsed)
    )


def _funding_from_prices(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    prices: dict[str, Any],
) -> FundingRate:
    estimation = prices["fundingRateEstimation"]
    return FundingRate(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        rate=float(estimation["estimatedFundingRate"]),
        next_funding_time=_epoch_to_datetime(estimation["nextFundingTimestamp"]),
    )


def _epoch_to_datetime(value: object) -> datetime:
    raw = float(value)
    if raw > 10_000_000_000_000:
        seconds = raw / 1_000_000
    elif raw > 10_000_000_000:
        seconds = raw / 1_000
    else:
        seconds = raw
    return datetime.fromtimestamp(seconds, timezone.utc)
