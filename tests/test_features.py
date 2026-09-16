"""Unit tests for Microstructure Feature Extractor."""

import pytest
from aegiswatch.core.features import FeatureExtractor, MicrostructureFeatures
from aegiswatch.core.order_book import LimitOrderBook, OrderSide


def test_feature_extractor_baseline():
    book = LimitOrderBook("NVDA")
    extractor = FeatureExtractor(window_ms=1000)

    # Empty book initial feature extraction
    feats = extractor.compute(book)
    assert isinstance(feats, MicrostructureFeatures)
    assert feats.ctr == 0.0
    assert feats.flashing_ratio == 0.0
    assert feats.depth_imbalance == 0.0

    arr = feats.to_array()
    assert len(arr) == 8
    assert len(MicrostructureFeatures.feature_names()) == 8


def test_depth_imbalance_and_ofi():
    book = LimitOrderBook("NVDA")
    extractor = FeatureExtractor(window_ms=1000)

    # Establish initial book
    book.add_order("BID_1", "TRADER_1", OrderSide.BUY, 100.0, 100)
    book.add_order("ASK_1", "TRADER_2", OrderSide.SELL, 100.2, 50)

    feats1 = extractor.compute(book)
    # Bid depth 100, ask depth 50 -> imbalance (100 - 50) / 150 = 0.3333
    assert feats1.depth_imbalance > 0.3
    assert feats1.spread == 0.2


def test_cancel_to_trade_ratio_and_flashing():
    book = LimitOrderBook("NVDA")
    extractor = FeatureExtractor(window_ms=1000)

    # Add 10 orders, cancel 9 of them almost immediately
    for i in range(10):
        oid = f"ORD_{i}"
        book.add_order(oid, "SPOOFER", OrderSide.BUY, 99.0 + (i * 0.01), 100)

    for i in range(9):
        book.cancel_order(f"ORD_{i}")

    # Add one trade
    book.add_order("ASK_REST", "SELLER", OrderSide.SELL, 101.0, 50)
    book.add_order("BUY_TAKE", "BUYER", OrderSide.BUY, 101.0, 50)

    feats = extractor.compute(book)
    # 9 cancels, 1 trade -> CTR = 9.0
    assert feats.ctr == 9.0
    assert feats.flashing_ratio > 0.5  # rapid cancellations
