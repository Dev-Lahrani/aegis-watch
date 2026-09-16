"""Unified Dual-Head Surveillance Pipeline ensemble."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from aegiswatch.core.features import MicrostructureFeatures
from aegiswatch.core.order_book import LimitOrderBook
from aegiswatch.detectors.base import SurveillanceAlert
from aegiswatch.detectors.ml_detector import MLAnomalyDetector
from aegiswatch.detectors.rules import MicrostructureRuleEngine


@dataclass
class PipelineResult:
    alerts: List[SurveillanceAlert]
    anomaly_score: float  # 0.0 to 1.0 composite threat index
    feature_attributions: Dict[str, float]
    latency_us: float
    total_evaluated: int


class SurveillancePipeline:
    """Combines deterministic statutory rule filters (Head 1) and unsupervised ML outlier models (Head 2)."""

    def __init__(self):
        self.rules_engine = MicrostructureRuleEngine()
        self.ml_detector = MLAnomalyDetector()

        self.alert_history: Deque[SurveillanceAlert] = deque(maxlen=200)
        self.alert_map: Dict[str, SurveillanceAlert] = {}
        self.total_evaluated: int = 0
        self._latencies_us: Deque[float] = deque(maxlen=1000)

    def process_tick(
        self, book: LimitOrderBook, features: MicrostructureFeatures, now_us: Optional[float] = None
    ) -> PipelineResult:
        start_t = time.perf_counter()
        now = now_us or (time.time() * 1_000_000)
        self.total_evaluated += 1

        # 1. Run Head 1 (Deterministic Rules)
        rule_alerts = self.rules_engine.evaluate(book, features, now)

        # 2. Run Head 2 (ML Anomaly Detector)
        ml_alert, ml_score, ml_attr = self.ml_detector.evaluate(features, book.symbol, now)

        all_alerts: List[SurveillanceAlert] = list(rule_alerts)
        if ml_alert and not any(a.abuse_type == ml_alert.abuse_type for a in rule_alerts):
            all_alerts.append(ml_alert)

        # Calculate composite threat score
        composite_score = ml_score
        if rule_alerts:
            # Deterministic rule elevates threat score to critical level
            composite_score = max(composite_score, 0.95)

        # Store alerts in history
        for alert in all_alerts:
            self.alert_history.appendleft(alert)
            self.alert_map[alert.alert_id] = alert

        latency_us = (time.perf_counter() - start_t) * 1_000_000
        self._latencies_us.append(latency_us)

        return PipelineResult(
            alerts=all_alerts,
            anomaly_score=round(composite_score, 4),
            feature_attributions=ml_attr,
            latency_us=round(latency_us, 2),
            total_evaluated=self.total_evaluated,
        )

    def get_alert(self, alert_id: str) -> Optional[SurveillanceAlert]:
        return self.alert_map.get(alert_id)

    def get_recent_alerts(self, limit: int = 50) -> List[Dict]:
        return [a.to_dict() for a in list(self.alert_history)[:limit]]

    def get_stats(self) -> Dict:
        median_lat = float(sorted(self._latencies_us)[len(self._latencies_us) // 2]) if self._latencies_us else 0.0
        return {
            "total_evaluated_ticks": self.total_evaluated,
            "total_alerts_emitted": len(self.alert_history),
            "median_latency_us": round(median_lat, 1),
            "median_latency_ms": round(median_lat / 1000.0, 3),
            "p99_latency_us": (
                round(float(sorted(self._latencies_us)[int(len(self._latencies_us) * 0.99)]), 1)
                if self._latencies_us
                else 0.0
            ),
        }
