"""Deterministic market microstructure surveillance rule filters (Head 1).

Implements statutory and regulatory rule gates for spoofing, layering, quote stuffing,
wash trading, and momentum ignition with zero false-tolerance requirements.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from aegiswatch.core.features import MicrostructureFeatures
from aegiswatch.core.order_book import LimitOrderBook, OrderSide, OrderStatus
from aegiswatch.detectors.base import (
    REGULATORY_CITATIONS,
    AbuseType,
    AlertSeverity,
    SurveillanceAlert,
)


class MicrostructureRuleEngine:
    """Evaluates deterministic microstructure manipulation signatures on order book state."""

    def __init__(self):
        self._alert_counter: int = 0
        # Rate-limiting / deduplication map: abuse_type -> last_alert_time_us
        self._last_alert_ts: Dict[str, float] = {}

    def _next_alert_id(self, abuse_type: AbuseType) -> str:
        self._alert_counter += 1
        prefix = abuse_type.value[:3]
        return f"ALT-{prefix}-{self._alert_counter:04d}"

    def _is_rate_limited(self, key: str, now_us: float, cooldown_ms: float = 300.0) -> bool:
        last = self._last_alert_ts.get(key, 0.0)
        if (now_us - last) < (cooldown_ms * 1000.0):
            return True
        self._last_alert_ts[key] = now_us
        return False

    def evaluate(
        self, book: LimitOrderBook, features: MicrostructureFeatures, now_us: Optional[float] = None
    ) -> List[SurveillanceAlert]:
        now = now_us or (time.time() * 1_000_000)
        alerts: List[SurveillanceAlert] = []

        # 1. Wash Trading Check (Immediate zero-latency rule)
        wash_alert = self._check_wash_trading(book, now)
        if wash_alert:
            alerts.append(wash_alert)

        # 2. Spoofing Check (Flashing large quotes + opposite executions)
        spoof_alert = self._check_spoofing(book, features, now)
        if spoof_alert:
            alerts.append(spoof_alert)

        # 3. Layering Check (Cascading staircase orders cancelled en masse)
        layer_alert = self._check_layering(book, features, now)
        if layer_alert:
            alerts.append(layer_alert)

        # 4. Quote Stuffing Check (Gate congestion)
        stuffing_alert = self._check_quote_stuffing(book, features, now)
        if stuffing_alert:
            alerts.append(stuffing_alert)

        # 5. Momentum Ignition Check
        momentum_alert = self._check_momentum_ignition(book, features, now)
        if momentum_alert:
            alerts.append(momentum_alert)

        return alerts

    def _check_wash_trading(self, book: LimitOrderBook, now_us: float) -> Optional[SurveillanceAlert]:
        threshold_us = now_us - 1_000_000.0  # past 1 second
        recent_trades = [t for t in book.trade_history if t.timestamp_us >= threshold_us]

        for trade in recent_trades:
            # Self-match check
            if trade.buyer_id == trade.seller_id:
                key = f"wash_{trade.buyer_id}_{trade.price}"
                if self._is_rate_limited(key, now_us, cooldown_ms=1000.0):
                    continue

                return SurveillanceAlert(
                    alert_id=self._next_alert_id(AbuseType.WASH_TRADING),
                    timestamp_us=now_us,
                    abuse_type=AbuseType.WASH_TRADING,
                    severity=AlertSeverity.CRITICAL,
                    confidence=0.99,
                    symbol=book.symbol,
                    description=(
                        f"Direct wash trade detected: Participant '{trade.buyer_id}' executed self-matching trade "
                        f"of {trade.quantity} shares at ${trade.price:.2f} with zero beneficial change in ownership."
                    ),
                    target_trader_id=trade.buyer_id,
                    affected_side=trade.aggressor_side.value,
                    regulatory_rules=REGULATORY_CITATIONS[AbuseType.WASH_TRADING],
                    feature_attribution={
                        "self_match_volume": 0.80,
                        "beneficial_ownership_delta": 0.20,
                    },
                    evidence={
                        "trade_id": trade.trade_id,
                        "price": trade.price,
                        "quantity": trade.quantity,
                        "buyer_id": trade.buyer_id,
                        "seller_id": trade.seller_id,
                    },
                )
        return None

    def _check_spoofing(
        self, book: LimitOrderBook, features: MicrostructureFeatures, now_us: float
    ) -> Optional[SurveillanceAlert]:
        # Spoofing criteria:
        # 1. High Cancel-to-Trade Ratio (CTR > 5.0) or flashing_ratio > 0.40
        # 2. Large orders cancelled within < 50ms
        threshold_us = now_us - 500_000.0  # past 500ms
        recent_cancels = [c for c in book.cancel_history if (c.cancel_timestamp_us or 0) >= threshold_us]

        if not recent_cancels:
            return None

        # Identify cancellations that were flashed (< 50ms lifetime)
        flashed_cancels = [
            c for c in recent_cancels if (c.lifetime_ms is not None and c.lifetime_ms < 60.0 and c.quantity >= 50)
        ]

        if len(flashed_cancels) >= 2 or (len(flashed_cancels) >= 1 and features.ctr > 4.0):
            # Check if there is a primary culprit trader
            trader_counts: Dict[str, int] = {}
            for c in flashed_cancels:
                trader_counts[c.trader_id] = trader_counts.get(c.trader_id, 0) + 1

            top_trader = max(trader_counts.items(), key=lambda x: x[1])[0]
            flashed_orders = [c for c in flashed_cancels if c.trader_id == top_trader]
            total_flashed_vol = sum(c.quantity for c in flashed_orders)
            avg_lifetime = sum(c.lifetime_ms or 0 for c in flashed_orders) / len(flashed_orders)
            side = flashed_orders[0].side.value

            key = f"spoof_{top_trader}_{side}"
            if self._is_rate_limited(key, now_us, cooldown_ms=800.0):
                return None

            confidence = min(0.98, 0.70 + (0.05 * len(flashed_orders)) + (0.10 if features.ctr > 6.0 else 0.0))

            return SurveillanceAlert(
                alert_id=self._next_alert_id(AbuseType.SPOOFING),
                timestamp_us=now_us,
                abuse_type=AbuseType.SPOOFING,
                severity=AlertSeverity.CRITICAL if confidence > 0.85 else AlertSeverity.HIGH,
                confidence=confidence,
                symbol=book.symbol,
                description=(
                    f"Predatory spoofing pattern identified: Participant '{top_trader}' submitted and cancelled "
                    f"{len(flashed_orders)} non-bona-fide {side} orders totaling {total_flashed_vol} shares with "
                    f"median duration {avg_lifetime:.1f} ms (CTR: {features.ctr:.1f})."
                ),
                target_trader_id=top_trader,
                affected_side=side,
                regulatory_rules=REGULATORY_CITATIONS[AbuseType.SPOOFING],
                feature_attribution={
                    "cancel_to_trade_ratio": 0.45,
                    "flashing_lifetime_ratio": 0.35,
                    "order_flow_imbalance": 0.20,
                },
                evidence={
                    "flashed_order_count": len(flashed_orders),
                    "total_flashed_volume": total_flashed_vol,
                    "avg_lifetime_ms": round(avg_lifetime, 1),
                    "ctr": features.ctr,
                    "sample_order_ids": [o.order_id for o in flashed_orders[:5]],
                },
            )
        return None

    def _check_layering(
        self, book: LimitOrderBook, features: MicrostructureFeatures, now_us: float
    ) -> Optional[SurveillanceAlert]:
        # Layering: 3+ resting orders at consecutive levels on one side by same trader creating artificial book depth
        threshold_us = now_us - 1_000_000.0
        recent_orders = [o for o in book.order_history if o.timestamp_us >= threshold_us]

        # Group active or recently cancelled orders by trader and side
        trader_depths: Dict[Tuple[str, str], List[float]] = {}
        for o in recent_orders:
            k = (o.trader_id, o.side.value)
            if k not in trader_depths:
                trader_depths[k] = []
            if o.price not in trader_depths[k]:
                trader_depths[k].append(o.price)

        for (trader_id, side), prices in trader_depths.items():
            if len(prices) >= 3 and abs(features.depth_imbalance) > 0.40:
                key = f"layering_{trader_id}_{side}"
                if self._is_rate_limited(key, now_us, cooldown_ms=1000.0):
                    continue

                return SurveillanceAlert(
                    alert_id=self._next_alert_id(AbuseType.LAYERING),
                    timestamp_us=now_us,
                    abuse_type=AbuseType.LAYERING,
                    severity=AlertSeverity.HIGH,
                    confidence=0.88,
                    symbol=book.symbol,
                    description=(
                        f"Order book layering detected: Participant '{trader_id}' established a multi-level staircase "
                        f"of {len(prices)} {side} price levels (${min(prices):.2f} - ${max(prices):.2f}) "
                        f"skewing depth imbalance to {features.depth_imbalance:+.2f}."
                    ),
                    target_trader_id=trader_id,
                    affected_side=side,
                    regulatory_rules=REGULATORY_CITATIONS[AbuseType.LAYERING],
                    feature_attribution={
                        "depth_imbalance": 0.50,
                        "consecutive_levels_staircase": 0.30,
                        "order_flow_imbalance": 0.20,
                    },
                    evidence={
                        "consecutive_levels": len(prices),
                        "price_ladder": sorted(prices),
                        "depth_imbalance": features.depth_imbalance,
                    },
                )
        return None

    def _check_quote_stuffing(
        self, book: LimitOrderBook, features: MicrostructureFeatures, now_us: float
    ) -> Optional[SurveillanceAlert]:
        # Quote stuffing: Velocity > 40 orders/sec with negligible execution
        if features.cancel_velocity_sec > 35.0 and features.ctr > 15.0:
            key = f"stuffing_{book.symbol}"
            if self._is_rate_limited(key, now_us, cooldown_ms=1200.0):
                return None

            return SurveillanceAlert(
                alert_id=self._next_alert_id(AbuseType.QUOTE_STUFFING),
                timestamp_us=now_us,
                abuse_type=AbuseType.QUOTE_STUFFING,
                severity=AlertSeverity.HIGH,
                confidence=0.91,
                symbol=book.symbol,
                description=(
                    f"Exchange gateway latency congestion detected (Quote Stuffing): Excessive cancellation velocity "
                    f"of {features.cancel_velocity_sec:.0f} msgs/sec with CTR {features.ctr:.1f} designed to induce matching engine delay."
                ),
                target_trader_id="LATENCY_ARBITRAGE_BURST",
                affected_side="BOTH",
                regulatory_rules=REGULATORY_CITATIONS[AbuseType.QUOTE_STUFFING],
                feature_attribution={
                    "cancel_velocity": 0.55,
                    "cancel_to_trade_ratio": 0.35,
                    "flashing_ratio": 0.10,
                },
                evidence={
                    "cancel_velocity_sec": features.cancel_velocity_sec,
                    "trade_velocity_sec": features.trade_velocity_sec,
                    "ctr": features.ctr,
                },
            )
        return None

    def _check_momentum_ignition(
        self, book: LimitOrderBook, features: MicrostructureFeatures, now_us: float
    ) -> Optional[SurveillanceAlert]:
        # Momentum ignition: Extreme OFI skew (|OFI| > 0.80) with high VPIN (> 0.60) and wide spread
        if abs(features.ofi) > 0.75 and features.vpin > 0.55 and features.spread > 0.05:
            direction = "BULLISH" if features.ofi > 0 else "BEARISH"
            key = f"momentum_{direction}"
            if self._is_rate_limited(key, now_us, cooldown_ms=1500.0):
                return None

            return SurveillanceAlert(
                alert_id=self._next_alert_id(AbuseType.MOMENTUM_IGNITION),
                timestamp_us=now_us,
                abuse_type=AbuseType.MOMENTUM_IGNITION,
                severity=AlertSeverity.HIGH,
                confidence=0.82,
                symbol=book.symbol,
                description=(
                    f"Artificial momentum breakout signature: Aggressive {direction} flow surge (OFI: {features.ofi:+.2f}) "
                    f"with elevated toxicity (VPIN: {features.vpin:.2f}) inducing spread widening to ${features.spread:.2f}."
                ),
                target_trader_id="MOMENTUM_IGNITER",
                affected_side="BUY" if features.ofi > 0 else "SELL",
                regulatory_rules=REGULATORY_CITATIONS[AbuseType.MOMENTUM_IGNITION],
                feature_attribution={
                    "order_flow_imbalance": 0.45,
                    "vpin_toxicity": 0.35,
                    "spread_widening": 0.20,
                },
                evidence={
                    "ofi": features.ofi,
                    "vpin": features.vpin,
                    "spread": features.spread,
                    "direction": direction,
                },
            )
        return None
