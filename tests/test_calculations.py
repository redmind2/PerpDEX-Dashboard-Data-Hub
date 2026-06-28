from perpdex_bot.calculations import estimate_slippage
from perpdex_bot.models import BookSide, OrderBookLevel, TradeSide


def test_buy_slippage_consumes_asks() -> None:
    asks = (
        OrderBookLevel(BookSide.ASK, price=101, size=1, level_index=0),
        OrderBookLevel(BookSide.ASK, price=102, size=1, level_index=1),
    )
    result = estimate_slippage(TradeSide.BUY, 150, 100, bids=(), asks=asks)

    assert result.complete
    assert result.average_price is not None
    assert result.average_price > 101
    assert result.slippage_bps is not None
    assert result.slippage_bps > 0


def test_sell_slippage_consumes_bids() -> None:
    bids = (
        OrderBookLevel(BookSide.BID, price=99, size=1, level_index=0),
        OrderBookLevel(BookSide.BID, price=98, size=1, level_index=1),
    )
    result = estimate_slippage(TradeSide.SELL, 150, 100, bids=bids, asks=())

    assert result.complete
    assert result.average_price is not None
    assert result.average_price < 99
    assert result.slippage_bps is not None
    assert result.slippage_bps > 0

