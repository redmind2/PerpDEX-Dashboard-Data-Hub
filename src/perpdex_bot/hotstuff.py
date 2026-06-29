from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .collectors import CollectorResult, LivePublicCollector, PublicAPISettings
from .models import BookSide, FundingRate, MarketSnapshot, OrderBookLevel


HOTSTUFF_INFO_URL = "https://api.hotstuff.trade/info"
HOTSTUFF_SYMBOLS = {
    "BTC-PERP": "BTC-PERP",
    "ETH-PERP": "ETH-PERP",
    "HYPE-PERP": "HYPE-PERP",
    "SOL-PERP": "SOL-PERP",
    "SILVER-PERP": "SILVER-PERP",
    "WTIOIL-PERP": "WTIOIL-PERP",
    "GOLD-PERP": "GOLD-PERP",
    "BRENTOIL-PERP": "BRENTOIL-PERP",
}


class HotstuffPublicClient:
    def __init__(
        self,
        info_url: str = HOTSTUFF_INFO_URL,
        settings: PublicAPISettings | None = None,
    ) -> None:
        self.info_url = info_url
        self.settings = settings or PublicAPISettings()
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()

    async def post_info(self, method: str, params: dict[str, object]) -> Any:
        await self._respect_spacing()
        payload = {"method": method, "params": params}
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
                    raise RuntimeError(f"Hotstuff public API request failed: {exc}") from exc
                await asyncio.sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("Hotstuff public API request failed after retries")

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


class HotstuffPublicCollector(LivePublicCollector):
    exchange_id = "Hotstuff"

    def __init__(self, client: HotstuffPublicClient | None = None) -> None:
        self.client = client or HotstuffPublicClient()

    async def collect_once(self, symbol: str) -> CollectorResult:
        hotstuff_symbol = to_hotstuff_symbol(symbol)
        ticker_payload, orderbook = await asyncio.gather(
            self.client.post_info("ticker", {"symbol": hotstuff_symbol}),
            self.client.post_info("orderbook", {"symbol": hotstuff_symbol}),
        )
        ticker = find_hotstuff_ticker(ticker_payload, hotstuff_symbol)
        if ticker is None:
            raise ValueError(f"Hotstuff ticker was not found for {symbol}")
        timestamp = _timestamp_from_payload(orderbook, ticker)
        snapshot = snapshot_from_hotstuff_payload(
            self.exchange_id,
            symbol,
            timestamp,
            ticker,
            orderbook,
        )
        funding = funding_from_hotstuff_ticker(self.exchange_id, symbol, timestamp, ticker)
        return CollectorResult(snapshot=snapshot, funding_rates=() if funding is None else (funding,))


def to_hotstuff_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    return HOTSTUFF_SYMBOLS.get(normalized, normalized)


def find_hotstuff_ticker(payload: object, symbol: str) -> dict[str, Any] | None:
    normalized = _normalize_symbol(symbol)
    for ticker in _ticker_items(payload):
        if _normalize_symbol(str(ticker.get("symbol", ""))) == normalized:
            return ticker
    return None


def snapshot_from_hotstuff_payload(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    ticker: dict[str, Any],
    orderbook: dict[str, Any],
) -> MarketSnapshot:
    bids = _levels(orderbook.get("bids"), BookSide.BID)
    asks = _levels(orderbook.get("asks"), BookSide.ASK)
    if not bids or not asks:
        raise ValueError("Hotstuff orderbook response did not include both bids and asks")

    mark_price = _number_from(ticker, "mark_price")
    index_price = _number_from(ticker, "index_price")
    return MarketSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        mark_price=mark_price if mark_price is not None else (bids[0].price + asks[0].price) / 2,
        index_price=index_price if index_price is not None else mark_price or (bids[0].price + asks[0].price) / 2,
        best_bid=bids[0].price,
        best_ask=asks[0].price,
        bids=bids,
        asks=asks,
    )


def funding_from_hotstuff_ticker(
    exchange_id: str,
    symbol: str,
    timestamp: datetime,
    ticker: dict[str, Any],
) -> FundingRate | None:
    rate = _number_from(ticker, "funding_rate")
    if rate is None:
        return None
    return FundingRate(
        exchange_id=exchange_id,
        symbol=symbol,
        timestamp=timestamp,
        rate=rate,
        next_funding_time=timestamp + timedelta(hours=1),
    )


def _ticker_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if "symbol" in payload:
            return [payload]
    return []


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
        price = _number_from(level, "price", "p", "px")
        size = _number_from(level, "size", "quantity", "qty", "q", "amount")
        if price is not None and size is not None:
            return price, size
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return float(level[0]), float(level[1])
    return None


def _timestamp_from_payload(*payloads: object) -> datetime:
    for payload in payloads:
        if isinstance(payload, dict):
            raw = _first_present(payload, "timestamp", "last_updated", "time")
            if raw is not None:
                return _to_datetime(raw)
    return datetime.now(timezone.utc).replace(microsecond=0)


def _number_from(payload: dict[str, Any], *keys: str) -> float | None:
    value = _first_present(payload, *keys)
    if value in (None, ""):
        return None
    return float(value)


def _first_present(payload: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _to_datetime(value: object) -> datetime:
    if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raw = float(value)
    if raw > 10_000_000_000:
        seconds = raw / 1_000
    else:
        seconds = raw
    return datetime.fromtimestamp(seconds, timezone.utc)


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "-").replace("/", "-")
