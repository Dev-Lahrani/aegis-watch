"""High-performance Limit Order Book (LOB) matching engine with microsecond order tracking."""

from __future__ import annotations

import bisect
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass
class Order:
    order_id: str
    trader_id: str
    side: OrderSide
    price: float
    quantity: int
    filled_qty: int = 0
    timestamp_us: float = 0.0
    cancel_timestamp_us: Optional[float] = None
    status: OrderStatus = OrderStatus.ACTIVE

    @property
    def remaining_qty(self) -> int:
        return max(0, self.quantity - self.filled_qty)

    @property
    def lifetime_ms(self) -> Optional[float]:
        if self.cancel_timestamp_us is not None:
            return max(0.0, (self.cancel_timestamp_us - self.timestamp_us) / 1000.0)
        return None


@dataclass
class Trade:
    trade_id: str
    timestamp_us: float
    price: float
    quantity: int
    buyer_id: str
    seller_id: str
    maker_order_id: str
    taker_order_id: str
    aggressor_side: OrderSide


class PriceLevel:
    """Represents a single price level containing a FIFO queue of resting limit orders."""

    __slots__ = ("price", "orders", "total_volume")

    def __init__(self, price: float):
        self.price = round(price, 4)
        self.orders: Deque[Order] = deque()
        self.total_volume: int = 0

    def add_order(self, order: Order) -> None:
        self.orders.append(order)
        self.total_volume += order.remaining_qty

    def remove_order(self, order: Order) -> bool:
        try:
            self.orders.remove(order)
            self.total_volume -= order.remaining_qty
            return True
        except ValueError:
            return False

    def is_empty(self) -> bool:
        return len(self.orders) == 0


class LimitOrderBook:
    """Double-sided Limit Order Book maintaining price-time priority and microsecond metrics."""

    def __init__(self, symbol: str = "NVDA"):
        self.symbol = symbol
        self.bids: Dict[float, PriceLevel] = {}
        self.asks: Dict[float, PriceLevel] = {}
        self._sorted_bid_prices: List[float] = []  # descending
        self._sorted_ask_prices: List[float] = []  # ascending

        self.order_map: Dict[str, Order] = {}
        self.trade_history: Deque[Trade] = deque(maxlen=5000)
        self.cancel_history: Deque[Order] = deque(maxlen=5000)
        self.order_history: Deque[Order] = deque(maxlen=10000)

        self._trade_counter: int = 0

    def _now_us(self) -> float:
        return time.time() * 1_000_000

    def get_best_bid(self) -> Optional[float]:
        return self._sorted_bid_prices[0] if self._sorted_bid_prices else None

    def get_best_ask(self) -> Optional[float]:
        return self._sorted_ask_prices[0] if self._sorted_ask_prices else None

    def get_mid_price(self) -> Optional[float]:
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is not None and best_ask is not None:
            return round((best_bid + best_ask) / 2.0, 4)
        return best_bid or best_ask

    def get_spread(self) -> Optional[float]:
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is not None and best_ask is not None:
            return round(best_ask - best_bid, 4)
        return None

    def get_microprice(self) -> Optional[float]:
        """Volume-weighted mid price at top-of-book."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is not None and best_ask is not None:
            bid_vol = self.bids[best_bid].total_volume
            ask_vol = self.asks[best_ask].total_volume
            total = bid_vol + ask_vol
            if total > 0:
                return round((best_bid * ask_vol + best_ask * bid_vol) / total, 4)
        return self.get_mid_price()

    def add_order(
        self,
        order_id: str,
        trader_id: str,
        side: OrderSide | str,
        price: float,
        quantity: int,
        timestamp_us: Optional[float] = None,
    ) -> Tuple[Order, List[Trade]]:
        """Submit a new limit order, execute any crossing liquidity, and rest the remainder."""
        side_enum = OrderSide(side) if isinstance(side, str) else side
        price = round(price, 4)
        now = timestamp_us or self._now_us()

        order = Order(
            order_id=order_id,
            trader_id=trader_id,
            side=side_enum,
            price=price,
            quantity=quantity,
            timestamp_us=now,
        )
        self.order_map[order_id] = order
        self.order_history.append(order)

        executed_trades: List[Trade] = []

        # Execute crossing orders
        if side_enum == OrderSide.BUY:
            while order.remaining_qty > 0 and self._sorted_ask_prices:
                best_ask = self._sorted_ask_prices[0]
                if price < best_ask:
                    break  # no more crossing matches

                level = self.asks[best_ask]
                trades = self._match_against_level(order, level, now, OrderSide.BUY)
                executed_trades.extend(trades)

                if level.is_empty():
                    del self.asks[best_ask]
                    self._sorted_ask_prices.pop(0)

            if order.remaining_qty > 0:
                self._insert_bid(order)

        else:  # SELL
            while order.remaining_qty > 0 and self._sorted_bid_prices:
                best_bid = self._sorted_bid_prices[0]
                if price > best_bid:
                    break

                level = self.bids[best_bid]
                trades = self._match_against_level(order, level, now, OrderSide.SELL)
                executed_trades.extend(trades)

                if level.is_empty():
                    del self.bids[best_bid]
                    self._sorted_bid_prices.pop(0)

            if order.remaining_qty > 0:
                self._insert_sell(order)

        # Update order status
        if order.remaining_qty == 0:
            order.status = OrderStatus.FILLED
        elif order.filled_qty > 0:
            order.status = OrderStatus.PARTIALLY_FILLED

        return order, executed_trades

    def _match_against_level(
        self, taker_order: Order, level: PriceLevel, timestamp_us: float, aggressor_side: OrderSide
    ) -> List[Trade]:
        trades: List[Trade] = []
        while taker_order.remaining_qty > 0 and level.orders:
            maker_order = level.orders[0]
            match_qty = min(taker_order.remaining_qty, maker_order.remaining_qty)

            taker_order.filled_qty += match_qty
            maker_order.filled_qty += match_qty
            level.total_volume -= match_qty

            self._trade_counter += 1
            trade = Trade(
                trade_id=f"TRD_{self._trade_counter}_{int(timestamp_us)}",
                timestamp_us=timestamp_us,
                price=level.price,
                quantity=match_qty,
                buyer_id=taker_order.trader_id if aggressor_side == OrderSide.BUY else maker_order.trader_id,
                seller_id=maker_order.trader_id if aggressor_side == OrderSide.BUY else taker_order.trader_id,
                maker_order_id=maker_order.order_id,
                taker_order_id=taker_order.order_id,
                aggressor_side=aggressor_side,
            )
            trades.append(trade)
            self.trade_history.append(trade)

            if maker_order.remaining_qty == 0:
                maker_order.status = OrderStatus.FILLED
                level.orders.popleft()
            else:
                maker_order.status = OrderStatus.PARTIALLY_FILLED

        return trades

    def _insert_bid(self, order: Order) -> None:
        price = order.price
        if price not in self.bids:
            self.bids[price] = PriceLevel(price)
            # Insert descending: find location where item should be placed
            # Invert for bisect
            idx = bisect.bisect_left([-p for p in self._sorted_bid_prices], -price)
            self._sorted_bid_prices.insert(idx, price)
        self.bids[price].add_order(order)

    def _insert_sell(self, order: Order) -> None:
        price = order.price
        if price not in self.asks:
            self.asks[price] = PriceLevel(price)
            idx = bisect.bisect_left(self._sorted_ask_prices, price)
            self._sorted_ask_prices.insert(idx, price)
        self.asks[price].add_order(order)

    def cancel_order(self, order_id: str, timestamp_us: Optional[float] = None) -> Optional[Order]:
        """Cancel an active resting order from the book."""
        if order_id not in self.order_map:
            return None

        order = self.order_map[order_id]
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return None

        now = timestamp_us or self._now_us()
        order.cancel_timestamp_us = now
        order.status = OrderStatus.CANCELLED

        target_dict = self.bids if order.side == OrderSide.BUY else self.asks
        target_list = self._sorted_bid_prices if order.side == OrderSide.BUY else self._sorted_ask_prices

        if order.price in target_dict:
            level = target_dict[order.price]
            level.remove_order(order)
            if level.is_empty():
                del target_dict[order.price]
                target_list.remove(order.price)

        self.cancel_history.append(order)
        return order

    def get_l2_depth(self, levels: int = 10) -> Dict[str, List[List[float]]]:
        """Return top-N bids and asks depth: [[price, size], ...]."""
        bid_depth: List[List[float]] = []
        for p in self._sorted_bid_prices[:levels]:
            bid_depth.append([p, float(self.bids[p].total_volume)])

        ask_depth: List[List[float]] = []
        for p in self._sorted_ask_prices[:levels]:
            ask_depth.append([p, float(self.asks[p].total_volume)])

        return {"bids": bid_depth, "asks": ask_depth}

    def get_total_bid_depth(self, levels: int = 10) -> int:
        return sum(self.bids[p].total_volume for p in self._sorted_bid_prices[:levels])

    def get_total_ask_depth(self, levels: int = 10) -> int:
        return sum(self.asks[p].total_volume for p in self._sorted_ask_prices[:levels])

    def get_recent_orders(self, window_ms: float = 1000.0) -> List[Order]:
        now_us = self._now_us()
        threshold = now_us - (window_ms * 1000.0)
        return [o for o in self.order_history if o.timestamp_us >= threshold]

    def get_recent_trades(self, window_ms: float = 1000.0) -> List[Trade]:
        now_us = self._now_us()
        threshold = now_us - (window_ms * 1000.0)
        return [t for t in self.trade_history if t.timestamp_us >= threshold]

    def clear(self) -> None:
        """Clear book for testing or reset."""
        self.bids.clear()
        self.asks.clear()
        self._sorted_bid_prices.clear()
        self._sorted_ask_prices.clear()
        self.order_map.clear()
        self.trade_history.clear()
        self.cancel_history.clear()
        self.order_history.clear()
