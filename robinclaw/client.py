"""
Robinclaw Client - Simplified agentic interface to Hyperliquid.

This wraps the hyperliquid-python-sdk to provide a clean, agent-friendly API.
Agents can use this to trade with real funds on Hyperliquid L1.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Position:
    """Current position in a market."""
    coin: str
    size: Decimal  # Positive = long, negative = short
    entry_price: Decimal
    unrealized_pnl: Decimal
    margin_used: Decimal
    leverage: int
    liquidation_price: Decimal | None


@dataclass
class Order:
    """An open order."""
    oid: int
    coin: str
    side: Side
    size: Decimal
    price: Decimal
    filled: Decimal
    status: str
    timestamp: int


@dataclass
class Fill:
    """A trade fill."""
    coin: str
    side: Side
    size: Decimal
    price: Decimal
    fee: Decimal
    timestamp: int
    oid: int


@dataclass
class Balance:
    """Account balance summary."""
    equity: Decimal
    available: Decimal
    margin_used: Decimal
    unrealized_pnl: Decimal


class RobinclawClient:
    """
    Simplified trading client for AI agents.
    
    Usage:
        client = RobinclawClient(private_key="0x...")
        
        # Get market info
        prices = client.get_prices()
        
        # Open a position
        client.market_buy("ETH", size=0.1)
        
        # Check positions
        positions = client.get_positions()
        
        # Close position
        client.market_close("ETH")
    """
    
    def __init__(
        self,
        private_key: str,
        testnet: bool = False,
        vault_address: str | None = None,
    ):
        """
        Initialize the client.
        
        Args:
            private_key: Ethereum private key (hex string starting with 0x)
            testnet: Use testnet instead of mainnet
            vault_address: Optional vault to trade on behalf of
        """
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.vault_address = vault_address
        
        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        
        self.info = Info(base_url=base_url, skip_ws=True)
        self.exchange = Exchange(
            wallet=self.account,
            base_url=base_url,
            vault_address=vault_address,
        )
        
        self._meta: dict | None = None
    
    @property
    def meta(self) -> dict:
        """Get and cache market metadata."""
        if self._meta is None:
            self._meta = self.info.meta()
        return self._meta
    
    def _coin_to_index(self, coin: str) -> int:
        """Convert coin symbol to asset index."""
        for i, asset in enumerate(self.meta["universe"]):
            if asset["name"] == coin:
                return i
        raise ValueError(f"Unknown coin: {coin}")
    
    def _get_sz_decimals(self, coin: str) -> int:
        """Get size decimals for a coin."""
        idx = self._coin_to_index(coin)
        return self.meta["universe"][idx]["szDecimals"]
    
    def _round_size(self, coin: str, size: float) -> float:
        """Round size to valid precision for this coin."""
        decimals = self._get_sz_decimals(coin)
        return round(size, decimals)

    # ========== Market Data ==========
    
    def get_prices(self) -> dict[str, Decimal]:
        """Get current mid prices for all markets."""
        mids = self.info.all_mids()
        return {coin: Decimal(price) for coin, price in mids.items()}
    
    def get_price(self, coin: str) -> Decimal:
        """Get current mid price for a specific coin."""
        return self.get_prices()[coin]
    
    def get_orderbook(self, coin: str, depth: int = 10) -> dict:
        """
        Get L2 orderbook for a coin.
        
        Returns dict with 'bids' and 'asks', each a list of [price, size] pairs.
        """
        book = self.info.l2_snapshot(coin)
        return {
            "bids": [[Decimal(p["px"]), Decimal(p["sz"])] for p in book["levels"][0][:depth]],
            "asks": [[Decimal(p["px"]), Decimal(p["sz"])] for p in book["levels"][1][:depth]],
        }
    
    def get_candles(
        self,
        coin: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> list[dict]:
        """
        Get candlestick data.
        
        Args:
            coin: Market symbol
            interval: 1m, 5m, 15m, 1h, 4h, 1d, etc.
            limit: Number of candles (max 5000)
        
        Returns:
            List of candles with open, high, low, close, volume, timestamp
        """
        import time
        end_time = int(time.time() * 1000)
        # Estimate start time based on interval
        interval_ms = {
            "1m": 60_000, "5m": 300_000, "15m": 900_000,
            "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
        }.get(interval, 3_600_000)
        start_time = end_time - (limit * interval_ms)
        
        candles = self.info.candles_snapshot(coin, interval, start_time, end_time)
        return [
            {
                "timestamp": c["t"],
                "open": Decimal(c["o"]),
                "high": Decimal(c["h"]),
                "low": Decimal(c["l"]),
                "close": Decimal(c["c"]),
                "volume": Decimal(c["v"]),
            }
            for c in candles
        ]

    # ========== Account Info ==========
    
    def get_balance(self) -> Balance:
        """Get account balance summary."""
        state = self.info.user_state(self.address)
        margin = state["marginSummary"]
        return Balance(
            equity=Decimal(margin["accountValue"]),
            available=Decimal(margin["totalNtlPos"]),  # Note: this is position value
            margin_used=Decimal(margin["totalMarginUsed"]),
            unrealized_pnl=Decimal(state.get("crossMarginSummary", {}).get("totalUntrackedFunding", "0")),
        )
    
    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        state = self.info.user_state(self.address)
        positions = []
        for pos in state.get("assetPositions", []):
            p = pos["position"]
            size = Decimal(p["szi"])
            if size == 0:
                continue
            positions.append(Position(
                coin=p["coin"],
                size=size,
                entry_price=Decimal(p["entryPx"]) if p.get("entryPx") else Decimal(0),
                unrealized_pnl=Decimal(p["unrealizedPnl"]),
                margin_used=Decimal(p["marginUsed"]),
                leverage=int(float(p["leverage"]["value"])),
                liquidation_price=Decimal(p["liquidationPx"]) if p.get("liquidationPx") else None,
            ))
        return positions
    
    def get_position(self, coin: str) -> Position | None:
        """Get position for a specific coin, or None if no position."""
        for pos in self.get_positions():
            if pos.coin == coin:
                return pos
        return None
    
    def get_open_orders(self, coin: str | None = None) -> list[Order]:
        """Get open orders, optionally filtered by coin."""
        orders = self.info.open_orders(self.address)
        result = []
        for o in orders:
            if coin and o["coin"] != coin:
                continue
            result.append(Order(
                oid=o["oid"],
                coin=o["coin"],
                side=Side.BUY if o["side"] == "B" else Side.SELL,
                size=Decimal(o["sz"]),
                price=Decimal(o["limitPx"]),
                filled=Decimal(o.get("filledSz", "0")),
                status="open",
                timestamp=o["timestamp"],
            ))
        return result
    
    def get_fills(self, limit: int = 50) -> list[Fill]:
        """Get recent trade fills."""
        fills = self.info.user_fills(self.address)[:limit]
        return [
            Fill(
                coin=f["coin"],
                side=Side.BUY if f["side"] == "B" else Side.SELL,
                size=Decimal(f["sz"]),
                price=Decimal(f["px"]),
                fee=Decimal(f["fee"]),
                timestamp=f["time"],
                oid=f["oid"],
            )
            for f in fills
        ]

    # ========== Trading ==========
    
    def set_leverage(self, coin: str, leverage: int, cross: bool = True) -> dict:
        """
        Set leverage for a market.
        
        Args:
            coin: Market symbol
            leverage: Leverage multiplier (1-50 typically)
            cross: Use cross margin (True) or isolated (False)
        """
        return self.exchange.update_leverage(leverage, coin, is_cross=cross)
    
    def market_buy(self, coin: str, size: float, slippage: float = 0.05) -> dict:
        """
        Open a long position at market price.
        
        Args:
            coin: Market symbol (e.g., "ETH", "BTC")
            size: Position size in base asset
            slippage: Max slippage (default 5%)
        
        Returns:
            Order result with status
        """
        size = self._round_size(coin, size)
        return self.exchange.market_open(coin, True, size, slippage=slippage)
    
    def market_sell(self, coin: str, size: float, slippage: float = 0.05) -> dict:
        """
        Open a short position at market price.
        
        Args:
            coin: Market symbol
            size: Position size in base asset
            slippage: Max slippage (default 5%)
        """
        size = self._round_size(coin, size)
        return self.exchange.market_open(coin, False, size, slippage=slippage)
    
    def market_close(self, coin: str, slippage: float = 0.05) -> dict | None:
        """
        Close entire position in a market.
        
        Returns order result or None if no position.
        """
        pos = self.get_position(coin)
        if not pos or pos.size == 0:
            return None
        return self.exchange.market_close(coin, slippage=slippage)
    
    def limit_buy(
        self,
        coin: str,
        size: float,
        price: float,
        reduce_only: bool = False,
        post_only: bool = False,
    ) -> dict:
        """Place a limit buy order."""
        size = self._round_size(coin, size)
        order_type = {"limit": {"tif": "Gtc"}}
        if post_only:
            order_type = {"limit": {"tif": "Alo"}}  # Add-liquidity-only
        
        return self.exchange.order(
            coin=coin,
            is_buy=True,
            sz=size,
            limit_px=price,
            order_type=order_type,
            reduce_only=reduce_only,
        )
    
    def limit_sell(
        self,
        coin: str,
        size: float,
        price: float,
        reduce_only: bool = False,
        post_only: bool = False,
    ) -> dict:
        """Place a limit sell order."""
        size = self._round_size(coin, size)
        order_type = {"limit": {"tif": "Gtc"}}
        if post_only:
            order_type = {"limit": {"tif": "Alo"}}
        
        return self.exchange.order(
            coin=coin,
            is_buy=False,
            sz=size,
            limit_px=price,
            order_type=order_type,
            reduce_only=reduce_only,
        )
    
    def cancel_order(self, coin: str, oid: int) -> dict:
        """Cancel a specific order."""
        return self.exchange.cancel(coin, oid)
    
    def cancel_all_orders(self, coin: str | None = None) -> list[dict]:
        """Cancel all open orders, optionally filtered by coin."""
        orders = self.get_open_orders(coin)
        results = []
        for order in orders:
            results.append(self.cancel_order(order.coin, order.oid))
        return results
    
    def stop_loss(
        self,
        coin: str,
        trigger_price: float,
        size: float | None = None,
    ) -> dict:
        """
        Place a stop-loss order.
        
        Args:
            coin: Market symbol
            trigger_price: Price at which to trigger
            size: Size to close (defaults to full position)
        """
        if size is None:
            pos = self.get_position(coin)
            if not pos:
                raise ValueError(f"No position in {coin}")
            size = abs(float(pos.size))
        
        is_buy = (self.get_position(coin).size < 0)  # Buy to close short
        size = self._round_size(coin, size)
        
        return self.exchange.order(
            coin=coin,
            is_buy=is_buy,
            sz=size,
            limit_px=trigger_price,
            order_type={"trigger": {"triggerPx": str(trigger_price), "isMarket": True, "tpsl": "sl"}},
            reduce_only=True,
        )
    
    def take_profit(
        self,
        coin: str,
        trigger_price: float,
        size: float | None = None,
    ) -> dict:
        """
        Place a take-profit order.
        
        Args:
            coin: Market symbol
            trigger_price: Price at which to trigger
            size: Size to close (defaults to full position)
        """
        if size is None:
            pos = self.get_position(coin)
            if not pos:
                raise ValueError(f"No position in {coin}")
            size = abs(float(pos.size))
        
        is_buy = (self.get_position(coin).size < 0)  # Buy to close short
        size = self._round_size(coin, size)
        
        return self.exchange.order(
            coin=coin,
            is_buy=is_buy,
            sz=size,
            limit_px=trigger_price,
            order_type={"trigger": {"triggerPx": str(trigger_price), "isMarket": True, "tpsl": "tp"}},
            reduce_only=True,
        )
