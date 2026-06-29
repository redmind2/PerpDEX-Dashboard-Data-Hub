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


PACIFICA_API_BASE_URL = "https://api.pacifica.fi/api/v1"


@dataclass(frozen=True)
class PacificaMarket:
    api_symbol: str


PACIFICA_MARKETS = {
    "BTC-PERP": PacificaMarket("BTC"),
    "ETH-PERP": PacificaMarket("ETH"),
    "SOL-PERP": PacificaMarket("SOL"),
    "HYPE-PERP": PacificaMarket("HYPE"),
    "GOLD-PERP": PacificaMarket("XAU"),
    "XAU-PERP": PacificaMarket("XAU"),
    "PAXG-PERP": PacificaMarket("PAXG"),
    "CL-PERP": PacificaMarket("CL"),
    "SILVER-PERP": PacificaMarket("XAG"),
    "XAG-PERP": PacificaMarket("XAG"),
    "SKHYNIX-PERP": PacificaMarket("SKHYNIX"),
    "SKHYNICS-PERP": PacificaMarket("SKHYNIX"),
    "SAMSUNG-PERP": PacificaMarket("SAMSUNG"),
}


class PacificaPublicClient:
    def __init__(
        self,
        base_url: str = PACIFICA_API_BASE_URL,
        settings: PublicAPISettings | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.settings = settings or PublicAPISettings()
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._markets_by_symbol: dict[str, dict[str, Any]] | None = None
        self._prices_by_symbol: dict[str, dict[str, Any]] | None = None

    async def market_info(self, api_symbol: str) -> dict[str, Any] | None:
        markets = await self._market_infos()
        return markets.get(api_symbol.upper())

    async def price_info(self, api_symbol: str) -> dict[str, Any] | None:
        prices = await self._price_infos()
        return prices.get(api_symbol.upper())

    async def order_book(self, api_symbol: str) -> dict[str, Any]:
        payload = await self.get_json("book", {"symbol": api_symbol})
        if not isinstance(payload, dict):
            raise ValueError("Pacifica book response was not a JSON object")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Pacifica book response did not include data")
        return data

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
                    raise RuntimeError(f"Pacifica public API request failed: {exc}") from exc
                await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("Pacifica public API request failed after retries")

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

    async def _market_infos(self) -> dict[str, dict[str, Any]]:
        if self._markets_by_symbol is None:
            payload = await self.get_json("info")
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ValueError("Pacifica info response did not include market data")
            self._markets_by_symbol = {
                str(item.get("symbol", "")).upper(): item
                for item in data
                if isinstance(item, dict)
                and str(item.get("instrument_type", "")).lower() == "perpetual"
            }
        return self._markets_by_symbol

    async def _price_infos(self) -> dict[str, dict[str, Any]]:
        if self._prices_by_symbol is None:
            payload = await self.get_json("info/prices")
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ValueError("Pacifica info/prices response did not include price data")
            self._prices_by_symbol = {
                str(item.get("symbol", "")).upper(): item
                for item in data
                if isinstance(item, dict)
            }
        return self._prices_by_symbol

    async def _respect_spacing(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self.settings.request_spacing_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()


class PacificaPublicCollector(LivePublicCollector):
    exchange_id = "Pacifica"

    def __init__(self, client: PacificaPublicClient | None = None) -> None:
        self.client = client or PacificaPublicClient()

    async def collect_once(self, symbol: str) -> CollectorResult:
        market = to_pacifica_market(symbol)
        market_info, price_info, book = await asyncio.gather(
            self.client.market_info(market.api_symbol),
            self.client.price_info(market.api_symbol),
            self.client.order_book(market.api_symbol),
        )
        if market_info is None:
            raise ValueError(f"Pacifica market info was not found for {symbol}")
        if price_info is None:
            raise ValueError(f"Pacifica price info was not found for {symbol}")

        timestamp = _timestamp_from_payload(price_info, book)
        snapshot = snapshot_from_pacifica_payload(
            self.exchange_id,
            symbol,
            timestamp,
            price_info,
            book,
        )
        funding = funding_from_pacifica_payload(self.exchange_id, symbol, timestamp, price_info)
        return CollectorResult(snapshot=snapshot, funding_rates=() if funding is None else (funding,))


def to_pacifica_market(symbol: str) -> PacificaMarket:
    normalized = _normalize_symbol(symbol)
    market = PACIFICA_MARKETS.get(normalized)
    if market is None:
        raise ValueError(f"Unsupported Pacifica public market: {symbol}")
    return market


def snapshot_from_pacifica_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    price_info: dict[str, Any],
    book: dict[str, Any],
) -> MarketSnapshot:
    levels = book.get("l")
    bids = _levels(_book_side(levels, 0), BookSide.BID)
    asks = _levels(_book_side(levels, 1), BookSide.ASK)
    if not bids or not asks:
        raise ValueError("Pacifica book response did not include both bids and asks")

    mid_price = (bids[0].price + asks[0].price) / 2
    mark_price = _number_from(price_info, "mark") or mid_price
    index_price = _number_from(price_info, "oracle") or mark_price
    return MarketSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=mark_price,
        index_price=index_price,
        best_bid=bids[0].price,
        best_ask=asks[0].price,
        bids=bids,
        asks=asks,
    )


def funding_from_pacifica_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    price_info: dict[str, Any],
) -> FundingRate | None:
    rate = _number_from(price_info, "funding")
    if rate is None:
        return None
    return FundingRate(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        rate=rate,
        next_funding_time=timestamp + timedelta(hours=1),
    )


def _book_side(levels: object, side_index: int) -> object:
    if isinstance(levels, list) and len(levels) > side_index:
        return levels[side_index]
    return ()


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
        price = _number_from(level, "p", "price")
        size = _number_from(level, "a", "amount", "size")
        if price is not None and size is not None:
            return price, size
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0]), float(level[1])
    return None


def _timestamp_from_payload(price_info: dict[str, Any], book: dict[str, Any]) -> datetime:
    raw = price_info.get("timestamp") or book.get("t")
    if raw is not None:
        return _to_datetime(raw)
    return datetime.now(timezone.utc).replace(microsecond=0)


def _number_from(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return float(value)
    return None


def _to_datetime(value: object) -> datetime:
    raw = float(value)
    seconds = raw / 1_000 if raw > 10_000_000_000 else raw
    return datetime.fromtimestamp(seconds, timezone.utc)


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "-").replace("/", "-")
