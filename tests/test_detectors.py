"""Unit tests for Surveillance Detectors and Ensemble Pipeline."""

import time
import pytest
from aegiswatch.core.features import FeatureExtractor
from aegiswatch.core.order_book import LimitOrderBook, OrderSide
from aegiswatch.detectors.base import AbuseType, AlertSeverity
from aegiswatch.detectors.ensemble import SurveillancePipeline
from aegiswatch.detectors.ml_detector import MLAnomalyDetector
from aegiswatch.detectors.rules import MicrostructureRuleEngine


def test_wash_trading_detector():
    book = LimitOrderBook("NVDA")
    features_extractor = FeatureExtractor()
    engine = MicrostructureRuleEngine()

    # Create self-matched trade (same buyer and seller)
    book.add_order("ORD_REST", "BAD_TRADER", OrderSide.SELL, 150.00, 100)
    book.add_order("ORD_TAKE", "BAD_TRADER", OrderSide.BUY, 150.00, 100)

    feats = features_extractor.compute(book)
    alerts = engine.evaluate(book, feats)

    assert len(alerts) >= 1
    wash_alert = next(a for a in alerts if a.abuse_type == AbuseType.WASH_TRADING)
    assert wash_alert.severity == AlertSeverity.CRITICAL
    assert wash_alert.target_trader_id == "BAD_TRADER"
    assert "Dodd-Frank" in "".join(wash_alert.regulatory_rules) or "1934" in "".join(wash_alert.regulatory_rules)


def test_spoofing_detector():
    book = LimitOrderBook("NVDA")
    features_extractor = FeatureExtractor(window_ms=500)
    engine = MicrostructureRuleEngine()

    # Normal resting asks
    book.add_order("ASK_NORMAL", "MM_1", OrderSide.SELL, 150.20, 100)

    # Spoofer places 3 large fake buy orders at depth
    now_us = time.time() * 1_000_000
    book.add_order("SPOOF_1", "SPOOFER_X", OrderSide.BUY, 150.00, 500, timestamp_us=now_us)
    book.add_order("SPOOF_2", "SPOOFER_X", OrderSide.BUY, 149.95, 500, timestamp_us=now_us)

    # Spoofer quickly cancels them (15ms later)
    book.cancel_order("SPOOF_1", timestamp_us=now_us + 15_000)
    book.cancel_order("SPOOF_2", timestamp_us=now_us + 20_000)

    # Execute a trade
    book.add_order("BUY_FILL", "BUYER", OrderSide.BUY, 150.20, 50, timestamp_us=now_us + 25_000)

    feats = features_extractor.compute(book, timestamp_us=now_us + 30_000)
    alerts = engine.evaluate(book, feats, now_us=now_us + 30_000)

    spoof_alerts = [a for a in alerts if a.abuse_type == AbuseType.SPOOFING]
    assert len(spoof_alerts) >= 1
    alert = spoof_alerts[0]
    assert alert.target_trader_id == "SPOOFER_X"
    assert alert.evidence["flashed_order_count"] >= 2


def test_pipeline_integration_and_latency():
    book = LimitOrderBook("NVDA")
    features_extractor = FeatureExtractor()
    pipeline = SurveillancePipeline()

    book.add_order("B1", "T1", OrderSide.BUY, 100.0, 50)
    book.add_order("A1", "T2", OrderSide.SELL, 100.1, 50)

    feats = features_extractor.compute(book)
    res = pipeline.process_tick(book, feats)

    assert 0.0 <= res.anomaly_score <= 1.0
    assert res.latency_us > 0.0
    assert res.total_evaluated == 1

    stats = pipeline.get_stats()
    assert "median_latency_us" in stats
    assert stats["total_evaluated_ticks"] == 1
