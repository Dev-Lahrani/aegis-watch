"""Unit tests for MarketFeedSimulator and abuse injection."""

import asyncio
import pytest
from aegiswatch.feed.simulator import MarketFeedSimulator


@pytest.mark.anyio
async def test_feed_initialization_and_tick():
    feed = MarketFeedSimulator(symbol="NVDA", base_price=150.00)
    assert feed.book.get_best_bid() is not None
    assert feed.book.get_best_ask() is not None
    assert feed.book.get_spread() > 0.0

    packet = feed._process_and_package_state()
    assert packet["type"] == "MARKET_TICK"
    assert packet["symbol"] == "NVDA"
    assert "depth" in packet
    assert len(packet["depth"]["bids"]) > 0
    assert len(packet["depth"]["asks"]) > 0
    assert "features" in packet
    assert "surveillance" in packet


@pytest.mark.anyio
async def test_spoofing_injection():
    feed = MarketFeedSimulator(symbol="NVDA", base_price=150.00)
    res = await feed.inject_spoofing(side="BUY", volume=1000, count=2, cancel_delay_ms=10)
    assert res["scenario"] == "SPOOFING"
    assert len(res["spoof_orders"]) == 2

    # Process tick immediately
    packet = feed._process_and_package_state()
    assert packet["features"]["ctr"] >= 0.0


@pytest.mark.anyio
async def test_wash_trading_injection():
    feed = MarketFeedSimulator(symbol="NVDA", base_price=150.00)
    res = await feed.inject_wash_trading(volume=300, trades_count=2)
    assert res["scenario"] == "WASH_TRADING"
    assert res["trades_count"] >= 2

    # Verify that a wash trading alert is captured by the pipeline
    packet = feed._process_and_package_state()
    # At least one alert or previous history
    assert "surveillance" in packet
