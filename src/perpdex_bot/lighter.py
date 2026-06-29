from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .collectors import CollectorResult, LivePublicCollector, PublicAPISettings
from .models import BookSide, FundingRate, MarketSnapshot, OrderBookLevel


LIGHTER_API_BASE_URL = "https://mainnet.zklighter.elliot.ai/api/v1"


@dataclass(frozen=True)
class LighterMarket:
    api_symbol: str


LIGHTER_MARKETS = {
    "BTC-PERP": LighterMarket("BTC"),
    "ETH-PERP": LighterMarket("ETH"),
    "SOL-PERP": LighterMarket("SOL"),
    "HYPE-PERP": LighterMarket("HYPE"),
    "SAMSUNG-PERP": LighterMarket("SAMSUNGUSD"),
    "SAMSUNGUSD-PERP": LighterMarket("SAMSUNGUSD"),
    "SKHYNICS-PERP": LighterMarket("SKHYNIXUSD"),
    "SKHYNIX-PERP": LighterMarket("SKHYNIXUSD"),
    "SKHYNIXUSD-PERP": LighterMarket("SKHYNIXUSD"),
    "EWY-PERP": LighterMarket("EWY"),
    "WTI-PERP": LighterMarket("WTI"),
    "WTIOIL-PERP": LighterMarket("WTI"),
    "BRENT-PERP": LighterMarket("BRENTOIL"),
    "BRENTOIL-PERP": LighterMarket("BRENTOIL"),
    "XAU-PERP": LighterMarket("XAU"),
    "GOLD-PERP": LighterMarket("XAU"),
    "PAXG-PERP": LighterMarket("PAXG"),
    "XAG-PERP": LighterMarket("XAG"),
    "SILVER-PERP": LighterMarket("XAG"),
}


class LighterPublicClient:
    def __init__(
        self,
        base_url: str = LIGHTER_API_BASE_URL,
        settings: PublicAPISettings | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.settings = settings or PublicAPISettings()
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._details_by_symbol: dict[str, dict[str, Any]] | None = None
        self._funding_by_market_id: dict[int, dict[str, Any]] | None = None

    async def market_detail(self, api_symbol: str) -> dict[str, Any] | None:
        details = await self._market_details()
        return details.get(api_symbol.upper())

    async def order_book_orders(self, market_id: int, limit: int) -> dict[str, Any]:
        payload = await self.get_json(
            "orderBookOrders",
            {"market_id": market_id, "limit": min(max(limit, 1), 250)},
        )
        if not isinstance(payload, dict):
            raise ValueError("Lighter orderBookOrders response was not a JSON object")
        return payload

    async def funding_rate(self, market_id: int) -> dict[str, Any] | None:
        rates = await self._funding_rates()
        return rates.get(market_id)

    async def get_json(self, path: str, params: dict[str, object] | None = None) -> Any:
        await self._respect_spacing()
        for attempt in range(1, self.settings.retries + 1):
            try:
                return await asyncio.to_thread(self._get_json_sync, path, params or {})
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
                    raise RuntimeError(f"Lighter public API request failed: {exc}") from exc
                await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("Lighter public API request failed after retries")

    def _get_json_sync(self, path: str, params: dict[str, object]) -> Any:
        query = urlencode(params)
        url = f"{self.base_url}/{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(
            url,
            headers={"User-Agent": "perpdex-data-hub-public-collector/0.1"},
            method="GET",
        )
        with urlopen(request, timeout=self.settings.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))

    async def _market_details(self) -> dict[str, dict[str, Any]]:
        if self._details_by_symbol is None:
            payload = await self.get_json("orderBookDetails", {"filter": "perp"})
            details = payload.get("order_book_details") if isinstance(payload, dict) else None
            if not isinstance(details, list):
                raise ValueError("Lighter orderBookDetails response did not include markets")
            self._details_by_symbol = {
                str(detail.get("symbol", "")).upper(): detail
                for detail in details
                if isinstance(detail, dict)
            }
        return self._details_by_symbol

    async def _funding_rates(self) -> dict[int, dict[str, Any]]:
        if self._funding_by_market_id is None:
            payload = await self.get_json("funding-rates")
            rates = payload.get("funding_rates") if isinstance(payload, dict) else None
            if not isinstance(rates, list):
                raise ValueError("Lighter funding-rates response did not include rates")
            self._funding_by_market_id = {
                int(rate["market_id"]): rate
                for rate in rates
                if isinstance(rate, dict)
                and str(rate.get("exchange", "")).lower() == "lighter"
                and rate.get("market_id") is not None
            }
        return self._funding_by_market_id

    async def _respect_spacing(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self.settings.request_spacing_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()


class LighterPublicCollector(LivePublicCollector):
    exchange_id = "Lighter"

    def __init__(self, client: LighterPublicClient | None = None) -> None:
        self.client = client or LighterPublicClient()

    async def collect_once(self, symbol: str) -> CollectorResult:
        market = to_lighter_market(symbol)
        detail = await self.client.market_detail(market.api_symbol)
        if detail is None:
            raise ValueError(f"Lighter market detail was not found for {symbol}")
        if str(detail.get("status", "")).lower() != "active":
            raise ValueError(f"Lighter market is not active for {symbol}")

        market_id = int(detail["market_id"])
        orders, funding_payload = await asyncio.gather(
            self.client.order_book_orders(market_id, self.client.settings.orderbook_depth_limit),
            self.client.funding_rate(market_id),
        )
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = snapshot_from_lighter_payload(self.exchange_id, symbol, timestamp, detail, orders)
        funding = funding_from_lighter_payload(
            self.exchange_id,
            symbol,
            timestamp,
            funding_payload,
        )
        return CollectorResult(snapshot=snapshot, funding_rates=() if funding is None else (funding,))


def to_lighter_market(symbol: str) -> LighterMarket:
    normalized = _normalize_symbol(symbol)
    market = LIGHTER_MARKETS.get(normalized)
    if market is None:
        raise ValueError(f"Unsupported Lighter public market: {symbol}")
    return market


def snapshot_from_lighter_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    detail: dict[str, Any],
    orders: dict[str, Any],
) -> MarketSnapshot:
    bids = _levels(orders.get("bids"), BookSide.BID)
    asks = _levels(orders.get("asks"), BookSide.ASK)
    if not bids or not asks:
        raise ValueError("Lighter orderBookOrders response did not include both bids and asks")

    mid_price = (bids[0].price + asks[0].price) / 2
    last_trade_price = _number_from(detail, "last_trade_price")
    mark_price = last_trade_price if last_trade_price is not None else mid_price
    return MarketSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=mark_price,
        index_price=mark_price,
        best_bid=bids[0].price,
        best_ask=asks[0].price,
        bids=bids,
        asks=asks,
    )


def funding_from_lighter_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    payload: dict[str, Any] | None,
) -> FundingRate | None:
    if payload is None:
        return None
    rate = _number_from(payload, "rate")
    if rate is None:
        return None
    return FundingRate(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        rate=rate,
        next_funding_time=timestamp + timedelta(hours=1),
    )


def _levels(raw_levels: object, side: BookSide) -> tuple[OrderBookLevel, ...]:
    parsed: list[tuple[float, float]] = []
    for level in raw_levels if isinstance(raw_levels, list) else []:
        parsed_level = _level(level)
        if parsed_level is not None:
            parsed.append(parsed_level)
    parsed.sort(key=lambda item: item[0], reverse=side == BookSide.BID)
    return tuple(
        OrderBookLevel(side=side, price=price, size=size, level_index=idx)
        for idx, (price, size) in enumerate(parsed)
    )


def _level(level: object) -> tuple[float, float] | None:
    if isinstance(level, dict):
        price = _number_from(level, "price")
        size = _number_from(level, "remaining_base_amount", "initial_base_amount")
        if price is not None and size is not None:
            return price, size
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0]), float(level[1])
    return None


def _number_from(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return float(value)
    return None


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "-").replace("/", "-")
