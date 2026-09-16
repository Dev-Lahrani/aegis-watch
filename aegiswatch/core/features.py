"""Quantitative market microstructure feature engineering for high-frequency surveillance.

Computes Order Flow Imbalance (OFI), Cancel-to-Trade Ratio (CTR), Volume-Synchronized
Probability of Toxicity (VPIN), Depth Imbalance, and Lifetime Flashing statistics.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import numpy as np

from aegiswatch.core.order_book import LimitOrderBook, OrderSide


@dataclass
class MicrostructureFeatures:
    timestamp_us: float
    mid_price: float
    spread: float
    depth_imbalance: float  # -1.0 to 1.0
    ofi: float  # Order Flow Imbalance (-1.0 to 1.0 normalized)
    ctr: float  # Cancel-to-Trade Ratio
    flashing_ratio: float  # Ratio of cancels with lifetime < 50ms (0.0 to 1.0)
    vpin: float  # Volume-Synchronized Probability of Toxicity (0.0 to 1.0)
    trade_velocity_sec: float
    cancel_velocity_sec: float
    total_bid_depth: int
    total_ask_depth: int

    def to_array(self) -> np.ndarray:
        """Convert to numerical feature vector for ML anomaly detection."""
        return np.array(
            [
                self.spread,
                self.depth_imbalance,
                self.ofi,
                min(self.ctr, 100.0) / 100.0,  # capped and scaled
                self.flashing_ratio,
                self.vpin,
                min(self.trade_velocity_sec, 500.0) / 500.0,
                min(self.cancel_velocity_sec, 1000.0) / 1000.0,
            ],
            dtype=np.float32,
        )

    @classmethod
    def feature_names(cls) -> List[str]:
        return [
            "spread",
            "depth_imbalance",
            "ofi",
            "cancel_to_trade_ratio",
            "flashing_ratio",
            "vpin_toxicity",
            "trade_velocity",
            "cancel_velocity",
        ]


class FeatureExtractor:
    """Extracts sliding-window microstructure metrics from a LimitOrderBook."""

    def __init__(self, window_ms: float = 1000.0, vpin_bucket_vol: int = 500, vpin_buckets: int = 10):
        self.window_ms = window_ms
        self.vpin_bucket_vol = vpin_bucket_vol
        self.vpin_buckets = vpin_buckets

        # Previous top-of-book state for Cont-Kukanov OFI
        self._prev_best_bid: Optional[float] = None
        self._prev_bid_size: int = 0
        self._prev_best_ask: Optional[float] = None
        self._prev_ask_size: int = 0

        # Rolling OFI accumulator
        self._ofi_history: Deque[Tuple[float, float]] = deque(maxlen=2000)  # (timestamp_us, ofi_value)

        # VPIN calculation state: list of (buy_vol, sell_vol) per completed bucket
        self._completed_buckets: Deque[Tuple[int, int]] = deque(maxlen=vpin_buckets)
        self._curr_bucket_buy: int = 0
        self._curr_bucket_sell: int = 0

    def compute(self, book: LimitOrderBook, timestamp_us: Optional[float] = None) -> MicrostructureFeatures:
        now = timestamp_us or (time.time() * 1_000_000)
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        mid_price = book.get_mid_price() or 100.0
        spread = book.get_spread() or 0.01

        # 1. Depth Imbalance at top 5 levels
        bid_depth = book.get_total_bid_depth(levels=5)
        ask_depth = book.get_total_ask_depth(levels=5)
        total_depth = bid_depth + ask_depth
        depth_imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0.0

        # 2. Cont, Kukanov & Stoikov (2014) Order Flow Imbalance (OFI)
        curr_bid_size = book.bids[best_bid].total_volume if (best_bid and best_bid in book.bids) else 0
        curr_ask_size = book.asks[best_ask].total_volume if (best_ask and best_ask in book.asks) else 0

        delta_bid = 0.0
        if best_bid is not None and self._prev_best_bid is not None:
            if best_bid > self._prev_best_bid:
                delta_bid = curr_bid_size
            elif best_bid == self._prev_best_bid:
                delta_bid = curr_bid_size - self._prev_bid_size
            else:
                delta_bid = -self._prev_bid_size

        delta_ask = 0.0
        if best_ask is not None and self._prev_best_ask is not None:
            if best_ask < self._prev_best_ask:
                delta_ask = curr_ask_size
            elif best_ask == self._prev_best_ask:
                delta_ask = curr_ask_size - self._prev_ask_size
            else:
                delta_ask = -self._prev_ask_size

        raw_ofi = delta_bid - delta_ask
        self._prev_best_bid = best_bid
        self._prev_bid_size = curr_bid_size
        self._prev_best_ask = best_ask
        self._prev_ask_size = curr_ask_size

        self._ofi_history.append((now, raw_ofi))

        # Normalized rolling OFI over window
        threshold_us = now - (self.window_ms * 1000.0)
        recent_ofis = [val for ts, val in self._ofi_history if ts >= threshold_us]
        if recent_ofis:
            sum_ofi = sum(recent_ofis)
            norm_factor = max(1.0, float(total_depth))
            norm_ofi = float(np.clip(sum_ofi / norm_factor, -1.0, 1.0))
        else:
            norm_ofi = 0.0

        # 3. Cancel-to-Trade Ratio (CTR) and Flashing Intensity in window
        recent_cancels = [c for c in book.cancel_history if (c.cancel_timestamp_us or 0) >= threshold_us]
        recent_trades = [t for t in book.trade_history if t.timestamp_us >= threshold_us]

        num_cancels = len(recent_cancels)
        num_trades = len(recent_trades)
        ctr = float(num_cancels) / max(1.0, float(num_trades))

        # Flashing: orders cancelled in < 50ms
        fast_cancels = sum(1 for c in recent_cancels if (c.lifetime_ms is not None and c.lifetime_ms < 50.0))
        flashing_ratio = float(fast_cancels) / float(num_cancels) if num_cancels > 0 else 0.0

        # 4. Velocities per second
        window_sec = max(0.001, self.window_ms / 1000.0)
        trade_velocity = num_trades / window_sec
        cancel_velocity = num_cancels / window_sec

        # 5. VPIN calculation (Volume-Synchronized Probability of Toxicity)
        vpin = self._update_vpin(recent_trades)

        return MicrostructureFeatures(
            timestamp_us=now,
            mid_price=round(mid_price, 4),
            spread=round(spread, 4),
            depth_imbalance=round(depth_imbalance, 4),
            ofi=round(norm_ofi, 4),
            ctr=round(ctr, 2),
            flashing_ratio=round(flashing_ratio, 4),
            vpin=round(vpin, 4),
            trade_velocity_sec=round(trade_velocity, 1),
            cancel_velocity_sec=round(cancel_velocity, 1),
            total_bid_depth=bid_depth,
            total_ask_depth=ask_depth,
        )

    def _update_vpin(self, recent_trades: List) -> float:
        """Calculate Volume-Synchronized Probability of Toxicity (Easley et al., 2012)."""
        for trade in recent_trades:
            vol = trade.quantity
            is_buy = trade.aggressor_side == OrderSide.BUY

            rem_bucket_capacity = self.vpin_bucket_vol - (self._curr_bucket_buy + self._curr_bucket_sell)
            if vol <= rem_bucket_capacity:
                if is_buy:
                    self._curr_bucket_buy += vol
                else:
                    self._curr_bucket_sell += vol
            else:
                # Complete current bucket
                fill_vol = rem_bucket_capacity
                if is_buy:
                    self._curr_bucket_buy += fill_vol
                else:
                    self._curr_bucket_sell += fill_vol

                self._completed_buckets.append((self._curr_bucket_buy, self._curr_bucket_sell))

                # Start new bucket with remaining
                leftover = vol - fill_vol
                self._curr_bucket_buy = leftover if is_buy else 0
                self._curr_bucket_sell = 0 if is_buy else leftover

        if not self._completed_buckets:
            return 0.15  # Default baseline toxicity for quiet market

        # VPIN = sum(|V_buy - V_sell|) / (N * V)
        total_imbalance = sum(abs(b - s) for b, s in self._completed_buckets)
        total_vol = len(self._completed_buckets) * self.vpin_bucket_vol
        return float(np.clip(total_imbalance / total_vol, 0.0, 1.0)) if total_vol > 0 else 0.15
