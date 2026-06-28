from __future__ import annotations

import asyncio

from perpdex_bot.rise import RisePublicCollector, find_rise_market


class FakeRiseClient:
    def __init__(self) -> None:
        self.paths = type("Paths", (), {"orderbook": "/book", "markets": "/markets"})()
        self.settings = type("Settings", (), {"orderbook_depth_limit": 100})()
        self.requests: list[tuple[str, dict[str, object] | None]] = []

    async def get_json(self, path: str, params: dict[str, object] | None = None):
        self.requests.append((path, params))
        if path == "/markets":
            return {
                "data": [
                    {
                        "market_id": "1",
                        "symbol": "BTC/USDC",
                        "mark_price": "100025",
                        "index_price": "100020",
                        "current_funding_rate": "0.00008",
                        "next_funding_time": "1720028800000000000",
                    }
                ]
            }
        if path == "/book":
            assert params == {"market_id": 1, "limit": 100}
            return {
                "data": {
                    "bids": [["99950", "1.5"], ["100000", "2"]],
                    "asks": [["100100", "1"], ["100050", "3"]],
                    "timestamp": "1720028700000000000",
                }
            }
        raise AssertionError(f"Unexpected path: {path}")


def test_rise_market_lookup_keeps_internal_btc_perp() -> None:
    market = find_rise_market(
        {
            "data": [
                {
                    "market_id": "1",
                    "symbol": "BTC/USDC",
                }
            ]
        },
        "BTC-PERP",
    )

    assert market is not None
    assert market.market_id == 1
    assert market.display_name == "BTC/USDC"


def test_rise_collector_builds_phase1_models() -> None:
    client = FakeRiseClient()
    collector = RisePublicCollector(client=client)  # type: ignore[arg-type]

    result = asyncio.run(collector.collect_once("BTC-PERP"))

    assert result.snapshot.exchange_id == "Rise"
    assert result.snapshot.symbol == "BTC-PERP"
    assert result.snapshot.best_bid == 100000.0
    assert result.snapshot.best_ask == 100050.0
    assert result.snapshot.mark_price == 100025.0
    assert result.snapshot.index_price == 100020.0
    assert len(result.snapshot.bids) == 2
    assert len(result.snapshot.asks) == 2
    assert [item.rate for item in result.funding_rates] == [0.00008]
    assert result.funding_rates[0].next_funding_time.year == 2024
    assert client.requests[0] == ("/markets", None)
