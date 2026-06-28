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


RISE_CHAIN_NAME = "RISE"
RISE_CHAIN_ID = 4153
RISE_CHAIN_ID_HEX = "0x1039"
RISE_NATIVE_CURRENCY = "ETH"
RISE_EXPLORER_URL = "https://explorer.risechain.com/"
RISE_HTTP_RPC_URL = "https://rpc.risechain.com"
RISE_WEBSOCKET_RPC_URL = "wss://rpc.risechain.com/ws"
RISE_PUBLIC_BASE_URL = "https://api.testnet.rise.trade"
RISE_MARKETS_PATH = "/v1/markets"
RISE_ORDERBOOK_PATH = "/v1/orderbook"
RISE_MARKET_IDS = {
    "BTC-PERP": 1,
}
RISE_MARKET_DISPLAY_NAMES = {
    "BTC-PERP": "BTC/USDC",
}


@dataclass(frozen=True)
class RiseEndpointPaths:
    markets: str = RISE_MARKETS_PATH
    orderbook: str = RISE_ORDERBOOK_PATH


@dataclass(frozen=True)
class RiseMarket:
    market_id: int
    display_name: str
    payload: dict[str, Any]


class RisePublicClient:
    def __init__(
        self,
        base_url: str = RISE_PUBLIC_BASE_URL,
        settings: PublicAPISettings | None = None,
        paths: RiseEndpointPaths | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.settings = settings or PublicAPISettings()
        self.paths = paths or RiseEndpointPaths()
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
                    raise RuntimeError(f"Rise public API request failed: {exc}") from exc
                await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("Rise public API request failed after retries")

    def _get_json_sync(self, url: str) -> Any:
        request = Request(url, headers={"User-Agent": "perpdex-phase2e-public-collector/0.1"})
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


class RisePublicCollector(LivePublicCollector):
    exchange_id = "Rise"

    def __init__(self, client: RisePublicClient | None = None) -> None:
        self.client = client or RisePublicClient()

    async def collect_once(self, symbol: str) -> CollectorResult:
        market = await self._market_for(symbol)
        orderbook = await self.client.get_json(
            self.client.paths.orderbook,
            {
                "market_id": market.market_id,
                "limit": self.client.settings.orderbook_depth_limit,
            },
        )
        timestamp = _timestamp_from_payload(market.payload, orderbook)
        snapshot = snapshot_from_rise_payload(self.exchange_id, symbol, timestamp, orderbook, market)
        funding = funding_from_rise_market(self.exchange_id, symbol, timestamp, market.payload)
        return CollectorResult(
            snapshot=snapshot,
            funding_rates=() if funding is None else (funding,),
        )

    async def _market_for(self, symbol: str) -> RiseMarket:
        markets = await self.client.get_json(self.client.paths.markets)
        market = find_rise_market(markets, symbol)
        if market is None:
            market_id = RISE_MARKET_IDS.get(_normalize_symbol(symbol))
            display_name = RISE_MARKET_DISPLAY_NAMES.get(_normalize_symbol(symbol), symbol)
            if market_id is None:
                raise ValueError(f"Rise market was not found for {symbol}")
            return RiseMarket(market_id=market_id, display_name=display_name, payload={})
        return market


def find_rise_market(payload: object, symbol: str) -> RiseMarket | None:
    normalized = _normalize_symbol(symbol)
    expected_display = RISE_MARKET_DISPLAY_NAMES.get(normalized, normalized)
    for market in _market_items(_payload_data(payload)):
        display_name = _market_display_name(market)
        market_id = _market_id(market)
        if market_id is None:
            continue
        candidates = {
            _normalize_symbol(display_name),
            _normalize_symbol(str(_first_present(market, "symbol", "name", "market_name", "ticker") or "")),
            _normalize_symbol(str(_first_present(market, "pair", "product", "display_name") or "")),
        }
        if _normalize_symbol(expected_display) in candidates or normalized in candidates:
            return RiseMarket(market_id=market_id, display_name=display_name, payload=market)
    return None


def snapshot_from_rise_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    orderbook: dict[str, Any],
    market: RiseMarket,
) -> MarketSnapshot:
    book = _payload_data(orderbook)
    info = market.payload
    bids = _levels(_first_present(book, "bids", "bid", "buy"), BookSide.BID)
    asks = _levels(_first_present(book, "asks", "ask", "sell"), BookSide.ASK)
    if not bids or not asks:
        raise ValueError("Rise orderbook response did not include both bids and asks")

    mark_price = _number_from(info, "mark_price", "markPrice", "mark", "last_price", "lastPrice")
    index_price = _number_from(info, "index_price", "indexPrice", "oracle_price", "oraclePrice")
    mid_price = (bids[0].price + asks[0].price) / 2
    return MarketSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=mark_price if mark_price is not None else mid_price,
        index_price=index_price if index_price is not None else mark_price or mid_price,
        best_bid=bids[0].price,
        best_ask=asks[0].price,
        bids=bids,
        asks=asks,
    )


def funding_from_rise_market(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    market: dict[str, Any],
) -> FundingRate | None:
    rate = _number_from(
        market,
        "current_funding_rate",
        "currentFundingRate",
        "funding_rate",
        "fundingRate",
        "next_funding_rate",
        "nextFundingRate",
    )
    if rate is None:
        return None

    next_funding_raw = _first_present(
        market,
        "next_funding_time",
        "nextFundingTime",
        "next_funding_timestamp",
        "nextFundingTimestamp",
    )
    next_funding_time = (
        _to_datetime(next_funding_raw)
        if next_funding_raw is not None
        else timestamp + timedelta(hours=8)
    )
    return FundingRate(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        rate=rate,
        next_funding_time=next_funding_time,
    )


def _payload_data(payload: object) -> object:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, (dict, list)):
            return data
        result = payload.get("result")
        if isinstance(result, (dict, list)):
            return result
        return payload
    return {}


def _market_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("markets", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _market_id(market: dict[str, Any]) -> int | None:
    value = _first_present(market, "market_id", "marketId", "id")
    if value is None:
        return None
    return int(value)


def _market_display_name(market: dict[str, Any]) -> str:
    explicit = _first_present(market, "display_name", "displayName", "symbol", "name", "market_name")
    if explicit is not None:
        return str(explicit)
    base = _first_present(market, "base_asset", "baseAsset", "base")
    quote = _first_present(market, "quote_asset", "quoteAsset", "quote")
    if base is not None and quote is not None:
        return f"{base}/{quote}"
    return ""


def _timestamp_from_payload(*payloads: object) -> datetime:
    for payload in payloads:
        data = _payload_data(payload)
        if isinstance(data, dict):
            raw = _first_present(data, "timestamp", "time", "updated_at", "updatedAt")
            if raw is not None:
                return _to_datetime(raw)
    return datetime.now(timezone.utc).replace(microsecond=0)


def _first_present(payload: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _levels(raw_levels: object, side: BookSide) -> tuple[OrderBookLevel, ...]:
    parsed: list[tuple[float, float]] = []
    levels = raw_levels.get("levels", []) if isinstance(raw_levels, dict) else raw_levels
    for level in levels if isinstance(levels, list) else []:
        parsed_level = _level(level)
        if parsed_level is not None:
            parsed.append(parsed_level)
    parsed.sort(key=lambda item: item[0], reverse=side == BookSide.BID)
    return tuple(
        OrderBookLevel(side=side, price=price, size=size, level_index=idx)
        for idx, (price, size) in enumerate(parsed)
    )


def _level(level: object) -> tuple[float, float] | None:
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0]), float(level[1])
    if isinstance(level, dict):
        price = _number_from(level, "price", "p", "px")
        size = _number_from(level, "size", "quantity", "qty", "q", "amount")
        if price is not None and size is not None:
            return price, size
    return None


def _number_from(payload: dict[str, Any], *keys: str) -> float | None:
    value = _first_present(payload, *keys)
    if value is None:
        return None
    return float(value)


def _to_datetime(value: object) -> datetime:
    if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raw = float(value)
    if raw > 10_000_000_000_000_000:
        seconds = raw / 1_000_000_000
    elif raw > 10_000_000_000_000:
        seconds = raw / 1_000_000
    elif raw > 10_000_000_000:
        seconds = raw / 1_000
    else:
        seconds = raw
    return datetime.fromtimestamp(seconds, timezone.utc)


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "-").replace("/", "-")
