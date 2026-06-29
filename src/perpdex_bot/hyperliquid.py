from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .collectors import CollectorResult, LivePublicCollector, PublicAPISettings
from .models import BookSide, FundingRate, MarketSnapshot, OrderBookLevel


HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True)
class HyperliquidMarket:
    coin: str
    dex: str = ""


HYPERLIQUID_MARKETS = {
    "BTC-PERP": HyperliquidMarket("BTC"),
    "ETH-PERP": HyperliquidMarket("ETH"),
    "SOL-PERP": HyperliquidMarket("SOL"),
    "HYPE-PERP": HyperliquidMarket("HYPE"),
    "SAMSUNG-PERP": HyperliquidMarket("xyz:SMSN", "xyz"),
    "SKHYNICS-PERP": HyperliquidMarket("xyz:SKHX", "xyz"),
    "EWY-PERP": HyperliquidMarket("xyz:EWY", "xyz"),
    "WTIOIL-PERP": HyperliquidMarket("cash:WTI", "cash"),
    "BRENTOIL-PERP": HyperliquidMarket("xyz:BRENTOIL", "xyz"),
    "GOLD-PERP": HyperliquidMarket("xyz:GOLD", "xyz"),
    "SILVER-PERP": HyperliquidMarket("xyz:SILVER", "xyz"),
}


class HyperliquidPublicClient:
    def __init__(
        self,
        info_url: str = HYPERLIQUID_INFO_URL,
        settings: PublicAPISettings | None = None,
    ) -> None:
        self.info_url = info_url
        self.settings = settings or PublicAPISettings()
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()

    async def post_info(self, payload: dict[str, object]) -> Any:
        await self._respect_spacing()
        for attempt in range(1, self.settings.retries + 1):
            try:
                return await asyncio.to_thread(self._post_info_sync, payload)
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
                    raise RuntimeError(f"Hyperliquid public API request failed: {exc}") from exc
                await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("Hyperliquid public API request failed after retries")

    def _post_info_sync(self, payload: dict[str, object]) -> Any:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.info_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "perpdex-data-hub-public-collector/0.1",
            },
            method="POST",
        )
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


class HyperliquidPublicCollector(LivePublicCollector):
    exchange_id = "Hyperliquid"

    def __init__(self, client: HyperliquidPublicClient | None = None) -> None:
        self.client = client or HyperliquidPublicClient()

    async def collect_once(self, symbol: str) -> CollectorResult:
        market = to_hyperliquid_market(symbol)
        meta_payload, book = await asyncio.gather(
            self.client.post_info(_meta_payload(market.dex)),
            self.client.post_info({"type": "l2Book", "coin": market.coin}),
        )
        context = find_hyperliquid_context(meta_payload, market.coin)
        if context is None:
            raise ValueError(f"Hyperliquid market context was not found for {symbol}")
        timestamp = _timestamp_from_payload(book)
        snapshot = snapshot_from_hyperliquid_payload(
            self.exchange_id,
            symbol,
            timestamp,
            context,
            book,
        )
        funding = funding_from_hyperliquid_context(self.exchange_id, symbol, timestamp, context)
        return CollectorResult(snapshot=snapshot, funding_rates=() if funding is None else (funding,))


def to_hyperliquid_market(symbol: str) -> HyperliquidMarket:
    normalized = _normalize_symbol(symbol)
    market = HYPERLIQUID_MARKETS.get(normalized)
    if market is None:
        raise ValueError(f"Unsupported Hyperliquid public market: {symbol}")
    return market


def find_hyperliquid_context(payload: object, coin: str) -> dict[str, Any] | None:
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    meta, contexts = payload[0], payload[1]
    if not isinstance(meta, dict) or not isinstance(contexts, list):
        return None
    universe = meta.get("universe")
    if not isinstance(universe, list):
        return None
    for idx, asset in enumerate(universe):
        if not isinstance(asset, dict):
            continue
        if _normalize_coin(str(asset.get("name", ""))) == _normalize_coin(coin):
            context = contexts[idx] if idx < len(contexts) else None
            return context if isinstance(context, dict) else None
    return None


def snapshot_from_hyperliquid_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    context: dict[str, Any],
    book: dict[str, Any],
) -> MarketSnapshot:
    bids = _levels(_book_side(book, 0), BookSide.BID)
    asks = _levels(_book_side(book, 1), BookSide.ASK)
    if not bids or not asks:
        raise ValueError("Hyperliquid l2Book response did not include both bids and asks")

    mark_price = _number_from(context, "markPx")
    index_price = _number_from(context, "oraclePx")
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


def funding_from_hyperliquid_context(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    context: dict[str, Any],
) -> FundingRate | None:
    rate = _number_from(context, "funding")
    if rate is None:
        return None
    return FundingRate(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        rate=rate,
        next_funding_time=timestamp + timedelta(hours=1),
    )


def _meta_payload(dex: str) -> dict[str, object]:
    payload: dict[str, object] = {"type": "metaAndAssetCtxs"}
    if dex:
        payload["dex"] = dex
    return payload


def _book_side(book: dict[str, Any], side_index: int) -> object:
    levels = book.get("levels")
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
        price = _number_from(level, "px", "price")
        size = _number_from(level, "sz", "size")
        if price is not None and size is not None:
            return price, size
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0]), float(level[1])
    return None


def _timestamp_from_payload(payload: object) -> datetime:
    if isinstance(payload, dict):
        raw = payload.get("time")
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
    if raw > 10_000_000_000:
        seconds = raw / 1_000
    else:
        seconds = raw
    return datetime.fromtimestamp(seconds, timezone.utc)


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "-").replace("/", "-")


def _normalize_coin(coin: str) -> str:
    return coin.upper().replace("_", "-")
