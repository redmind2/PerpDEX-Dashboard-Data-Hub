from __future__ import annotations

import asyncio

from perpdex_bot.pacifica import (
    DEFAULT_PACIFICA_ORDERBOOK_AGG_LEVEL,
    PacificaPublicCollector,
    pacifica_orderbook_agg_level,
    to_pacifica_market,
)


class FakePacificaClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def market_info(self, api_symbol: str):
        self.requests.append(("market_info", api_symbol))
        assert api_symbol == "XAU"
        return {
            "symbol": "XAU",
            "instrument_type": "perpetual",
            "funding_rate": "0.0000125",
        }

    async def price_info(self, api_symbol: str):
        self.requests.append(("price_info", api_symbol))
        assert api_symbol == "XAU"
        return {
            "symbol": "XAU",
            "timestamp": 1_782_718_606_183,
            "mark": "4063.5",
            "oracle": "4063.198764",
            "funding": "0.0000125",
        }

    async def order_book(self, api_symbol: str, agg_level: int | None = None):
        self.requests.append(("order_book", f"{api_symbol}:{agg_level}"))
        assert api_symbol == "XAU"
        assert agg_level == DEFAULT_PACIFICA_ORDERBOOK_AGG_LEVEL
        return {
            "s": "XAU",
            "t": 1_782_718_609_369,
            "l": [
                [
                    {"p": "4063.4", "a": "2.5", "n": 2},
                    {"p": "4063.3", "a": "1.0", "n": 1},
                ],
                [
                    {"p": "4063.5", "a": "3.5", "n": 3},
                    {"p": "4063.6", "a": "1.2", "n": 1},
                ],
            ],
        }


def test_pacifica_symbol_mapping_keeps_requested_aliases() -> None:
    assert to_pacifica_market("BTC-PERP").api_symbol == "BTC"
    assert to_pacifica_market("HYPE-PERP").api_symbol == "HYPE"
    assert to_pacifica_market("GOLD-PERP").api_symbol == "XAU"
    assert to_pacifica_market("PAXG-PERP").api_symbol == "PAXG"
    assert to_pacifica_market("CL-PERP").api_symbol == "CL"
    assert to_pacifica_market("SILVER-PERP").api_symbol == "XAG"
    assert to_pacifica_market("SKHYNIX-PERP").api_symbol == "SKHYNIX"
    assert to_pacifica_market("SAMSUNG-PERP").api_symbol == "SAMSUNG"


def test_pacifica_collector_builds_phase1_models() -> None:
    client = FakePacificaClient()
    collector = PacificaPublicCollector(client=client)  # type: ignore[arg-type]

    result = asyncio.run(collector.collect_once("GOLD-PERP"))

    assert result.snapshot.exchange_id == "Pacifica"
    assert result.snapshot.symbol == "GOLD-PERP"
    assert result.snapshot.best_bid == 4063.4
    assert result.snapshot.best_ask == 4063.5
    assert result.snapshot.mark_price == 4063.5
    assert result.snapshot.index_price == 4063.198764
    assert len(result.snapshot.bids) == 2
    assert len(result.snapshot.asks) == 2
    assert [item.rate for item in result.funding_rates] == [0.0000125]
    assert client.requests == [
        ("market_info", "XAU"),
        ("price_info", "XAU"),
        ("order_book", "XAU:100"),
    ]


def test_pacifica_orderbook_agg_level_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("PERPDEX_PACIFICA_ORDERBOOK_AGG_LEVEL", "1000")

    assert pacifica_orderbook_agg_level() == 1000
