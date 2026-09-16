"""Unsupervised Machine Learning & Statistical Outlier Surveillance Engine (Head 2).

Uses an adaptive Isolation Forest and rolling multivariate z-score attribution to catch
emergent, non-linear market manipulation without requiring labeled historical datasets.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest

from aegiswatch.core.features import MicrostructureFeatures
from aegiswatch.detectors.base import (
    REGULATORY_CITATIONS,
    AbuseType,
    AlertSeverity,
    SurveillanceAlert,
)


class MLAnomalyDetector:
    """Unsupervised multivariate anomaly detector on streaming microstructure vectors."""

    def __init__(self, buffer_size: int = 500, update_interval: int = 50):
        self.buffer_size = buffer_size
        self.update_interval = update_interval
        self._feature_buffer: Deque[np.ndarray] = deque(maxlen=buffer_size)
        self._counter: int = 0
        self._alert_counter: int = 0
        self._last_alert_ts: float = 0.0

        # Isolation Forest instance
        self.model: Optional[IsolationForest] = None
        self._is_fitted: bool = False

        # Rolling statistics for z-score attribution
        self._means: Optional[np.ndarray] = None
        self._stds: Optional[np.ndarray] = None

        # Pre-seed with realistic baseline distributions so model is warm on boot
        self._bootstrap_baseline()

    def _bootstrap_baseline(self) -> None:
        """Bootstrap the model with 200 synthetic normal-market microstructure ticks."""
        np.random.seed(42)
        # Features: [spread, depth_imbalance, ofi, ctr_scaled, flashing_ratio, vpin, trade_vel, cancel_vel]
        normal_samples = []
        for _ in range(200):
            spread = np.random.uniform(0.01, 0.04)
            depth_imb = np.random.normal(0.0, 0.15)
            ofi = np.random.normal(0.0, 0.10)
            ctr = np.random.uniform(0.05, 0.30)  # low cancel to trade
            flashing = np.random.uniform(0.0, 0.08)  # minimal flashing
            vpin = np.random.uniform(0.12, 0.28)  # low toxicity
            trade_vel = np.random.uniform(0.05, 0.25)
            cancel_vel = np.random.uniform(0.05, 0.25)
            normal_samples.append([spread, depth_imb, ofi, ctr, flashing, vpin, trade_vel, cancel_vel])

        baseline_arr = np.array(normal_samples, dtype=np.float32)
        for row in baseline_arr:
            self._feature_buffer.append(row)

        self._fit_model()

    def _fit_model(self) -> None:
        if len(self._feature_buffer) < 50:
            return

        X = np.array(list(self._feature_buffer), dtype=np.float32)
        self._means = np.mean(X, axis=0)
        self._stds = np.std(X, axis=0) + 1e-6

        self.model = IsolationForest(
            n_estimators=60,
            contamination=0.03,
            max_samples=min(256, len(X)),
            random_state=42,
            n_jobs=1,
        )
        self.model.fit(X)
        self._is_fitted = True

    def evaluate(
        self, features: MicrostructureFeatures, symbol: str, now_us: Optional[float] = None
    ) -> Tuple[Optional[SurveillanceAlert], float, Dict[str, float]]:
        """Evaluate feature vector, returning optional alert, anomaly score (0-1), and factor attributions."""
        now = now_us or (time.time() * 1_000_000)
        vec = features.to_array()
        self._feature_buffer.append(vec)
        self._counter += 1

        # Periodically refit on rolling background
        if self._counter % self.update_interval == 0:
            self._fit_model()

        if not self._is_fitted or self.model is None or self._means is None or self._stds is None:
            return None, 0.0, {}

        # 1. Compute Isolation Forest anomaly score
        # decision_function returns negative for outliers, positive for inliers
        dec_val = float(self.model.decision_function(vec.reshape(1, -1))[0])
        # Map to 0.0 (normal) -> 1.0 (extreme anomaly)
        raw_anomaly_score = 0.5 - (dec_val * 1.8)
        anomaly_score = float(np.clip(raw_anomaly_score, 0.0, 1.0))

        # 2. Compute multivariate z-score attribution
        z_scores = np.abs((vec - self._means) / self._stds)
        feature_names = MicrostructureFeatures.feature_names()

        # Normalize z-scores into percentage contributions
        total_z = float(np.sum(z_scores))
        if total_z > 0:
            attributions = {name: float(z / total_z) for name, z in zip(feature_names, z_scores)}
        else:
            attributions = {name: 1.0 / len(feature_names) for name in feature_names}

        # Sort attributions descending
        sorted_attr = dict(sorted(attributions.items(), key=lambda item: item[1], reverse=True))

        # 3. Trigger alert if statistical outlier is severe and debounced
        alert: Optional[SurveillanceAlert] = None
        max_z = float(np.max(z_scores))

        if anomaly_score >= 0.72 and max_z >= 2.5:
            # Debounce ML alerts to at most 1 per 1.5 seconds
            if (now - self._last_alert_ts) >= 1_500_000.0:
                self._last_alert_ts = now
                self._alert_counter += 1

                top_feat, top_pct = next(iter(sorted_attr.items()))
                severity = AlertSeverity.CRITICAL if anomaly_score > 0.85 else AlertSeverity.HIGH

                alert = SurveillanceAlert(
                    alert_id=f"ALT-ML-{self._alert_counter:04d}",
                    timestamp_us=now,
                    abuse_type=AbuseType.ANOMALOUS_MICROSTRUCTURE,
                    severity=severity,
                    confidence=round(anomaly_score, 4),
                    symbol=symbol,
                    description=(
                        f"Unsupervised multivariate anomaly detected: Order book behavior deviated significantly from "
                        f"baseline (Anomaly Score: {anomaly_score:.2f}, Max Z-Score: {max_z:.1f}σ). Primary driver: "
                        f"'{top_feat}' ({top_pct * 100:.1f}% contribution)."
                    ),
                    target_trader_id="UNCLASSIFIED_ANOMALY",
                    affected_side="MARKET",
                    regulatory_rules=REGULATORY_CITATIONS[AbuseType.ANOMALOUS_MICROSTRUCTURE],
                    feature_attribution=sorted_attr,
                    evidence={
                        "anomaly_score": round(anomaly_score, 4),
                        "max_z_score": round(max_z, 2),
                        "vector": [round(float(v), 4) for v in vec],
                        "top_factors": list(sorted_attr.items())[:3],
                    },
                )

        return alert, anomaly_score, sorted_attr
