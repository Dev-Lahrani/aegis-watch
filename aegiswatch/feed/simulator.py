"""Real-time institutional market tick feed simulator with live market abuse injectors."""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any, Callable, Dict, List, Optional

from aegiswatch.core.features import FeatureExtractor, MicrostructureFeatures
from aegiswatch.core.order_book import LimitOrderBook, OrderSide, Trade
from aegiswatch.detectors.ensemble import PipelineResult, SurveillancePipeline


class MarketFeedSimulator:
    """Simulates realistic high-frequency order book dynamics with triggerable abuse scenarios."""

    def __init__(
        self,
        symbol: str = "NVDA",
        base_price: float = 180.00,
        tick_interval_ms: float = 50.0,
    ):
        self.symbol = symbol
        self.base_price = base_price
        self.tick_interval_ms = tick_interval_ms

        self.book = LimitOrderBook(symbol=symbol)
        self.feature_extractor = FeatureExtractor(window_ms=1000.0)
        self.pipeline = SurveillancePipeline()

        self.is_running: bool = False
        self._order_counter: int = 0
        self._task: Optional[asyncio.Task] = None
        self._listeners: List[Callable[[Dict[str, Any]], Any]] = []

        # Current mid-price random walk
        self._current_mid = base_price
        self._initialize_book()

    def _next_order_id(self, prefix: str = "ORD") -> str:
        self._order_counter += 1
        return f"{prefix}_{self._order_counter:06d}"

    def _initialize_book(self) -> None:
        """Seed initial realistic 10-level bid/ask depth."""
        self.book.clear()
        self._current_mid = self.base_price

        # Bids: from mid - 0.01 down
        for i in range(1, 11):
            price = round(self._current_mid - (i * 0.01), 2)
            vol = random.randint(100, 450)
            self.book.add_order(self._next_order_id("INIT_BID"), f"MM_{i%3+1}", OrderSide.BUY, price, vol)

        # Asks: from mid + 0.01 up
        for i in range(1, 11):
            price = round(self._current_mid + (i * 0.01), 2)
            vol = random.randint(100, 450)
            self.book.add_order(self._next_order_id("INIT_ASK"), f"MM_{i%3+1}", OrderSide.SELL, price, vol)

    def subscribe(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._simulation_loop())

    async def stop(self) -> None:
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _simulation_loop(self) -> None:
        """Main market generation loop running at high frequency."""
        while self.is_running:
            try:
                await self._generate_normal_market_tick()
                packet = self._process_and_package_state()
                # Notify all subscribers
                for listener in list(self._listeners):
                    try:
                        res = listener(packet)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass
                await asyncio.sleep(self.tick_interval_ms / 1000.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[MarketFeedSimulator Error] {e}")
                await asyncio.sleep(0.1)

    async def _generate_normal_market_tick(self) -> None:
        """Simulate realistic Poisson arrivals of quotes, trades, and cancel refreshes."""
        now_us = time.time() * 1_000_000

        # Gentle Brownian walk on mid price
        drift = random.gauss(0, 0.005)
        self._current_mid = max(10.0, round(self._current_mid + drift, 2))

        best_bid = self.book.get_best_bid() or (self._current_mid - 0.01)
        best_ask = self.book.get_best_ask() or (self._current_mid + 0.01)

        # 1. Maintain inside spread if too wide
        if (best_ask - best_bid) > 0.04:
            new_bid = round(best_bid + 0.01, 2)
            self.book.add_order(self._next_order_id("MM_TIGHTEN"), "MM_CITADEL", OrderSide.BUY, new_bid, 100, now_us)

        # 2. Random liquidity refill at top levels
        dice = random.random()
        if dice < 0.45:
            # Add resting bid
            offset = random.choice([0.01, 0.02, 0.03, 0.04])
            p = round(best_bid - offset, 2)
            qty = random.randint(50, 300)
            trader = random.choice(["MM_JANE", "MM_VIRTU", "RETAIL_FLOW"])
            self.book.add_order(self._next_order_id("B_NORMAL"), trader, OrderSide.BUY, p, qty, now_us)

        elif dice < 0.90:
            # Add resting ask
            offset = random.choice([0.01, 0.02, 0.03, 0.04])
            p = round(best_ask + offset, 2)
            qty = random.randint(50, 300)
            trader = random.choice(["MM_JANE", "MM_VIRTU", "RETAIL_FLOW"])
            self.book.add_order(self._next_order_id("A_NORMAL"), trader, OrderSide.SELL, p, qty, now_us)

        # 3. Occasional crossing trade execution
        if random.random() < 0.35:
            side = OrderSide.BUY if random.random() > 0.5 else OrderSide.SELL
            aggr_price = best_ask if side == OrderSide.BUY else best_bid
            qty = random.choice([25, 50, 100])
            taker_traders = ["FIDELITY_FUND", "BLACKROCK_INDEX", "VANGUARD_ETF", "BRIDGEWATER_MACRO", "RETAIL_FLOW_B"]
            taker_id = random.choice(taker_traders)
            self.book.add_order(self._next_order_id("TRADE_FILL"), taker_id, side, aggr_price, qty, now_us)

        # 4. Clean up distant/stale orders if depth is too deep
        if len(self.book._sorted_bid_prices) > 15:
            deepest_p = self.book._sorted_bid_prices[-1]
            if deepest_p in self.book.bids and self.book.bids[deepest_p].orders:
                stale_order = self.book.bids[deepest_p].orders[0]
                self.book.cancel_order(stale_order.order_id, now_us)

        if len(self.book._sorted_ask_prices) > 15:
            deepest_p = self.book._sorted_ask_prices[-1]
            if deepest_p in self.book.asks and self.book.asks[deepest_p].orders:
                stale_order = self.book.asks[deepest_p].orders[0]
                self.book.cancel_order(stale_order.order_id, now_us)

    def _process_and_package_state(self) -> Dict[str, Any]:
        """Compute microstructure features, evaluate surveillance pipeline, and package state."""
        now_us = time.time() * 1_000_000
        features = self.feature_extractor.compute(self.book, now_us)
        pipeline_res = self.pipeline.process_tick(self.book, features, now_us)

        depth = self.book.get_l2_depth(levels=10)
        recent_trades = [
            {
                "trade_id": t.trade_id,
                "price": t.price,
                "quantity": t.quantity,
                "aggressor_side": t.aggressor_side.value,
                "time_iso": time.strftime("%H:%M:%S", time.gmtime(t.timestamp_us / 1_000_000)),
            }
            for t in list(self.book.trade_history)[-12:]
        ]

        return {
            "type": "MARKET_TICK",
            "symbol": self.symbol,
            "timestamp_us": now_us,
            "mid_price": self.book.get_mid_price() or self._current_mid,
            "best_bid": self.book.get_best_bid(),
            "best_ask": self.book.get_best_ask(),
            "spread": self.book.get_spread() or 0.01,
            "microprice": self.book.get_microprice() or self._current_mid,
            "depth": depth,
            "features": {
                "depth_imbalance": features.depth_imbalance,
                "ofi": features.ofi,
                "ctr": features.ctr,
                "flashing_ratio": features.flashing_ratio,
                "vpin": features.vpin,
                "trade_velocity": features.trade_velocity_sec,
                "cancel_velocity": features.cancel_velocity_sec,
            },
            "surveillance": {
                "anomaly_score": pipeline_res.anomaly_score,
                "new_alerts": [a.to_dict() for a in pipeline_res.alerts],
                "attributions": pipeline_res.feature_attributions,
                "pipeline_latency_us": pipeline_res.latency_us,
            },
            "recent_trades": recent_trades,
            "system_stats": self.pipeline.get_stats(),
        }

    # =========================================================================
    # ABUSE SCENARIOS INJECTION (For Live Demo & Stress-Testing)
    # =========================================================================

    async def inject_spoofing(
        self, side: str = "BUY", volume: int = 1200, count: int = 3, cancel_delay_ms: float = 30.0
    ) -> Dict[str, Any]:
        """Inject predatory spoofing: post massive phantom orders, fill opposite, immediately cancel."""
        now_us = time.time() * 1_000_000
        spoof_side = OrderSide(side.upper())
        target_side = OrderSide.SELL if spoof_side == OrderSide.BUY else OrderSide.BUY

        best_bid = self.book.get_best_bid() or self._current_mid
        best_ask = self.book.get_best_ask() or self._current_mid
        base_p = best_bid if spoof_side == OrderSide.BUY else best_ask

        # 1. Place large phantom orders 2-4 ticks behind
        spoof_ids = []
        for i in range(count):
            offset = 0.01 * (i + 1)
            p = round(base_p - offset, 2) if spoof_side == OrderSide.BUY else round(base_p + offset, 2)
            oid = self._next_order_id("SPOOF")
            spoof_ids.append(oid)
            self.book.add_order(oid, "PREDATORY_ALGO_X", spoof_side, p, volume, now_us)

        # 2. Execute trade on opposite side
        exec_price = best_ask if target_side == OrderSide.BUY else best_bid
        self.book.add_order(
            self._next_order_id("FILL"), "PREDATORY_ALGO_X", target_side, exec_price, 200, now_us + 5_000
        )

        # 3. Cancel the phantom orders after microsecond delay
        await asyncio.sleep(cancel_delay_ms / 1000.0)
        cancel_ts = time.time() * 1_000_000
        for oid in spoof_ids:
            self.book.cancel_order(oid, cancel_ts)

        return {
            "scenario": "SPOOFING",
            "spoof_orders": spoof_ids,
            "volume_per_order": volume,
            "cancel_delay_ms": cancel_delay_ms,
            "trader_id": "PREDATORY_ALGO_X",
        }

    async def inject_layering(self, side: str = "SELL", levels: int = 4, volume: int = 800) -> Dict[str, Any]:
        """Inject multi-level order book layering creating artificial depth pressure."""
        now_us = time.time() * 1_000_000
        layer_side = OrderSide(side.upper())
        best_price = self.book.get_best_ask() if layer_side == OrderSide.SELL else self.book.get_best_bid()
        best_p = best_price or self._current_mid

        layer_ids = []
        for i in range(levels):
            step = (i + 1) * 0.01
            p = round(best_p + step, 2) if layer_side == OrderSide.SELL else round(best_p - step, 2)
            oid = self._next_order_id("LAYER")
            layer_ids.append(oid)
            self.book.add_order(oid, "LAYER_SYNDICATE_B", layer_side, p, volume, now_us)

        # Let it rest for 150ms then pull all orders
        await asyncio.sleep(0.15)
        cancel_ts = time.time() * 1_000_000
        for oid in layer_ids:
            self.book.cancel_order(oid, cancel_ts)

        return {
            "scenario": "LAYERING",
            "layer_orders": layer_ids,
            "levels": levels,
            "volume_per_level": volume,
            "trader_id": "LAYER_SYNDICATE_B",
        }

    async def inject_quote_stuffing(self, burst_count: int = 50) -> Dict[str, Any]:
        """Inject high-frequency latency quote stuffing burst."""
        best_bid = self.book.get_best_bid() or self._current_mid
        now_us = time.time() * 1_000_000

        stuffed_ids = []
        for i in range(burst_count):
            p = round(best_bid - (0.01 * (i % 5 + 1)), 2)
            oid = self._next_order_id("STUFF")
            stuffed_ids.append(oid)
            self.book.add_order(oid, "LATENCY_BURST_BOT", OrderSide.BUY, p, 10, now_us)
            # Cancel almost immediately (0-2ms)
            self.book.cancel_order(oid, now_us + 1_000)

        return {
            "scenario": "QUOTE_STUFFING",
            "burst_count": burst_count,
            "trader_id": "LATENCY_BURST_BOT",
        }

    async def inject_wash_trading(self, volume: int = 500, trades_count: int = 3) -> Dict[str, Any]:
        """Inject self-matching wash trades between identical participant accounts."""
        mid = self.book.get_mid_price() or self._current_mid
        now_us = time.time() * 1_000_000
        wash_trader = "WASH_POOL_ACCOUNT_77"

        trade_ids = []
        for i in range(trades_count):
            p = round(mid, 2)
            # Post resting sell
            sell_id = self._next_order_id("WASH_S")
            self.book.add_order(sell_id, wash_trader, OrderSide.SELL, p, volume, now_us)
            # Immediate crossing buy from same trader
            buy_id = self._next_order_id("WASH_B")
            _, trades = self.book.add_order(buy_id, wash_trader, OrderSide.BUY, p, volume, now_us + 500)
            for t in trades:
                trade_ids.append(t.trade_id)

        return {
            "scenario": "WASH_TRADING",
            "trades_count": len(trade_ids),
            "trade_ids": trade_ids,
            "trader_id": wash_trader,
            "volume_per_trade": volume,
        }

    async def inject_momentum_ignition(self, direction: str = "BULLISH") -> Dict[str, Any]:
        """Inject aggressive liquidity sweep driving price breakout."""
        now_us = time.time() * 1_000_000
        side = OrderSide.BUY if direction.upper() == "BULLISH" else OrderSide.SELL
        sweep_price = (
            round((self.book.get_best_ask() or self._current_mid) + 0.15, 2)
            if side == OrderSide.BUY
            else round((self.book.get_best_bid() or self._current_mid) - 0.15, 2)
        )

        _, trades = self.book.add_order(self._next_order_id("MOM_IGNITE"), "MOMENTUM_IGNITER", side, sweep_price, 1500, now_us)

        return {
            "scenario": "MOMENTUM_IGNITION",
            "direction": direction,
            "sweep_price": sweep_price,
            "trades_filled": len(trades),
        }
