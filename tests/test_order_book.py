"""Unit tests for LimitOrderBook engine."""

import pytest
from aegiswatch.core.order_book import LimitOrderBook, OrderSide, OrderStatus


def test_order_book_initialization():
    book = LimitOrderBook(symbol="NVDA")
    assert book.symbol == "NVDA"
    assert book.get_best_bid() is None
    assert book.get_best_ask() is None
    assert book.get_mid_price() is None


def test_add_resting_limit_orders():
    book = LimitOrderBook(symbol="NVDA")

    # Add buy orders at different price levels
    o1, trades1 = book.add_order("ORD_1", "TRADER_A", OrderSide.BUY, 100.00, 50)
    o2, trades2 = book.add_order("ORD_2", "TRADER_B", OrderSide.BUY, 100.25, 100)
    assert len(trades1) == 0
    assert len(trades2) == 0
    assert o1.status == OrderStatus.ACTIVE
    assert o2.status == OrderStatus.ACTIVE

    # Best bid should be highest price
    assert book.get_best_bid() == 100.25

    # Add sell orders
    o3, trades3 = book.add_order("ORD_3", "TRADER_C", OrderSide.SELL, 100.50, 40)
    o4, trades4 = book.add_order("ORD_4", "TRADER_D", OrderSide.SELL, 100.75, 80)
    assert len(trades3) == 0
    assert len(trades4) == 0

    assert book.get_best_ask() == 100.50
    assert book.get_spread() == 0.25
    assert book.get_mid_price() == 100.375


def test_order_execution_and_partial_fill():
    book = LimitOrderBook(symbol="NVDA")
    book.add_order("BID_1", "TRADER_A", OrderSide.BUY, 150.00, 100)
    book.add_order("BID_2", "TRADER_B", OrderSide.BUY, 149.90, 200)

    # Aggressive sell order crossing best bid
    taker_order, trades = book.add_order("ASK_AGG", "HFT_1", OrderSide.SELL, 150.00, 60)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.price == 150.00
    assert trade.quantity == 60
    assert trade.buyer_id == "TRADER_A"
    assert trade.seller_id == "HFT_1"
    assert taker_order.status == OrderStatus.FILLED
    assert taker_order.filled_qty == 60

    # Resting order partially filled
    maker_order = book.order_map["BID_1"]
    assert maker_order.status == OrderStatus.PARTIALLY_FILLED
    assert maker_order.remaining_qty == 40
    assert maker_order.filled_qty == 60


def test_multi_level_market_sweep():
    book = LimitOrderBook(symbol="NVDA")
    book.add_order("ASK_1", "SELLER_1", OrderSide.SELL, 200.00, 50)
    book.add_order("ASK_2", "SELLER_2", OrderSide.SELL, 200.10, 50)

    # Aggressive buy sweeps both levels
    taker_order, trades = book.add_order("BUY_SWEEP", "BUYER_1", OrderSide.BUY, 200.20, 120)

    assert len(trades) == 2
    assert trades[0].price == 200.00
    assert trades[0].quantity == 50
    assert trades[1].price == 200.10
    assert trades[1].quantity == 50

    # Remaining 20 shares rest as best bid
    assert taker_order.status == OrderStatus.PARTIALLY_FILLED
    assert taker_order.remaining_qty == 20
    assert book.get_best_bid() == 200.20
    assert book.get_best_ask() is None


def test_order_cancellation_and_depth():
    book = LimitOrderBook(symbol="NVDA")
    book.add_order("BID_1", "TRADER_A", OrderSide.BUY, 100.00, 50)
    book.add_order("BID_2", "TRADER_B", OrderSide.BUY, 100.00, 30)

    depth = book.get_l2_depth(levels=5)
    assert depth["bids"] == [[100.00, 80.0]]

    # Cancel first order
    cancelled = book.cancel_order("BID_1")
    assert cancelled is not None
    assert cancelled.status == OrderStatus.CANCELLED
    assert cancelled.lifetime_ms is not None

    depth_after = book.get_l2_depth(levels=5)
    assert depth_after["bids"] == [[100.00, 30.0]]

    # Cancel remaining order
    book.cancel_order("BID_2")
    assert book.get_best_bid() is None
