"""
Robinclaw Trading Module - Hyperliquid SDK wrapper for agent trading.
"""

from typing import Optional, Literal
from dataclasses import dataclass
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants


@dataclass
class OrderResult:
    """Result of an order operation."""
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    filled_size: float = 0.0
    avg_price: float = 0.0


@dataclass  
class PositionInfo:
    """Current position information."""
    symbol: str
    size: float  # Positive = long, negative = short
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int


class AgentTrader:
    """Trading interface for a single agent."""
    
    def __init__(self, private_key: str, testnet: bool = False):
        """
        Initialize trader with agent's private key.
        
        Args:
            private_key: Agent's EVM private key (hex string with or without 0x prefix)
            testnet: Use testnet instead of mainnet
        """
        # Normalize private key
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
            
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        
        # Initialize Hyperliquid clients
        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self.info = Info(base_url, skip_ws=True)
        self.exchange = Exchange(self.account, base_url)
        
    def get_balance(self) -> dict:
        """Get account balance and margin info."""
        state = self.info.user_state(self.address)
        return {
            "account_value": float(state.get("marginSummary", {}).get("accountValue", 0)),
            "total_margin_used": float(state.get("marginSummary", {}).get("totalMarginUsed", 0)),
            "withdrawable": float(state.get("withdrawable", 0)),
        }
    
    def get_positions(self) -> list[PositionInfo]:
        """Get all open positions."""
        state = self.info.user_state(self.address)
        positions = []
        
        for pos in state.get("assetPositions", []):
            p = pos.get("position", {})
            size = float(p.get("szi", 0))
            if size != 0:
                leverage_info = p.get("leverage", {})
                lev = int(leverage_info.get("value", 1)) if isinstance(leverage_info, dict) else 1
                
                positions.append(PositionInfo(
                    symbol=p.get("coin", ""),
                    size=size,
                    entry_price=float(p.get("entryPx", 0)),
                    mark_price=float(p.get("positionValue", 0)) / abs(size) if size != 0 else 0,
                    unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                    leverage=lev,
                ))
        
        return positions
    
    def get_open_orders(self) -> list[dict]:
        """Get all open orders."""
        orders = self.info.open_orders(self.address)
        return [
            {
                "order_id": str(o.get("oid", "")),
                "symbol": o.get("coin", ""),
                "side": "buy" if o.get("side") == "B" else "sell",
                "size": float(o.get("sz", 0)),
                "price": float(o.get("limitPx", 0)),
                "order_type": o.get("orderType", "limit"),
            }
            for o in orders
        ]
    
    def market_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        size: float,
        slippage: float = 0.05,  # 5% slippage tolerance
    ) -> OrderResult:
        """
        Place a market order.
        
        Args:
            symbol: Trading pair (e.g., "BTC", "ETH")
            side: "buy" or "sell"
            size: Order size in base currency
            slippage: Slippage tolerance (0.05 = 5%)
        """
        try:
            is_buy = side == "buy"
            
            # Get current price for slippage calculation
            all_mids = self.info.all_mids()
            if symbol not in all_mids:
                return OrderResult(success=False, message=f"Unknown symbol: {symbol}")
            
            mid_price = float(all_mids[symbol])
            
            # Calculate limit price with slippage
            if is_buy:
                limit_price = mid_price * (1 + slippage)
            else:
                limit_price = mid_price * (1 - slippage)
            
            # Round price appropriately
            limit_price = round(limit_price, 2)
            
            # Place order using IOC (Immediate or Cancel) for market-like behavior
            result = self.exchange.order(
                symbol,
                is_buy,
                size,
                limit_price,
                {"limit": {"tif": "Ioc"}},  # IOC = market-like
            )
            
            if result.get("status") == "ok":
                response = result.get("response", {})
                data = response.get("data", {})
                statuses = data.get("statuses", [{}])
                
                if statuses and "filled" in statuses[0]:
                    filled = statuses[0]["filled"]
                    return OrderResult(
                        success=True,
                        order_id=str(filled.get("oid", "")),
                        message="Order filled",
                        filled_size=float(filled.get("totalSz", 0)),
                        avg_price=float(filled.get("avgPx", 0)),
                    )
                elif statuses and "resting" in statuses[0]:
                    resting = statuses[0]["resting"]
                    return OrderResult(
                        success=True,
                        order_id=str(resting.get("oid", "")),
                        message="Order placed (partial fill or resting)",
                    )
                else:
                    return OrderResult(
                        success=False,
                        message=f"Order not filled: {statuses}",
                    )
            else:
                return OrderResult(
                    success=False,
                    message=f"Order failed: {result}",
                )
                
        except Exception as e:
            return OrderResult(success=False, message=f"Error: {str(e)}")
    
    def limit_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        size: float,
        price: float,
        reduce_only: bool = False,
    ) -> OrderResult:
        """
        Place a limit order.
        
        Args:
            symbol: Trading pair
            side: "buy" or "sell"
            size: Order size
            price: Limit price
            reduce_only: If True, only reduce position
        """
        try:
            is_buy = side == "buy"
            
            order_type = {"limit": {"tif": "Gtc"}}  # Good till cancelled
            if reduce_only:
                order_type["limit"]["reduceOnly"] = True
            
            result = self.exchange.order(
                symbol,
                is_buy,
                size,
                price,
                order_type,
            )
            
            if result.get("status") == "ok":
                response = result.get("response", {})
                data = response.get("data", {})
                statuses = data.get("statuses", [{}])
                
                if statuses:
                    if "resting" in statuses[0]:
                        return OrderResult(
                            success=True,
                            order_id=str(statuses[0]["resting"].get("oid", "")),
                            message="Limit order placed",
                        )
                    elif "filled" in statuses[0]:
                        filled = statuses[0]["filled"]
                        return OrderResult(
                            success=True,
                            order_id=str(filled.get("oid", "")),
                            message="Order filled immediately",
                            filled_size=float(filled.get("totalSz", 0)),
                            avg_price=float(filled.get("avgPx", 0)),
                        )
                
                return OrderResult(success=False, message=f"Unexpected response: {statuses}")
            else:
                return OrderResult(success=False, message=f"Order failed: {result}")
                
        except Exception as e:
            return OrderResult(success=False, message=f"Error: {str(e)}")
    
    def close_position(self, symbol: str, slippage: float = 0.05) -> OrderResult:
        """
        Close entire position for a symbol.
        
        Args:
            symbol: Symbol to close position for
            slippage: Slippage tolerance for market close
        """
        positions = self.get_positions()
        position = next((p for p in positions if p.symbol == symbol), None)
        
        if not position:
            return OrderResult(success=False, message=f"No position in {symbol}")
        
        # Close by taking opposite side
        side = "sell" if position.size > 0 else "buy"
        size = abs(position.size)
        
        return self.market_order(symbol, side, size, slippage)
    
    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancel an open order."""
        try:
            result = self.exchange.cancel(symbol, order_id)
            return result.get("status") == "ok"
        except Exception:
            return False
    
    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancel all open orders, optionally filtered by symbol.
        
        Returns: Number of orders cancelled
        """
        orders = self.get_open_orders()
        if symbol:
            orders = [o for o in orders if o["symbol"] == symbol]
        
        cancelled = 0
        for order in orders:
            if self.cancel_order(order["symbol"], int(order["order_id"])):
                cancelled += 1
        
        return cancelled
    
    def set_leverage(self, symbol: str, leverage: int, is_cross: bool = True) -> bool:
        """
        Set leverage for a symbol.
        
        Args:
            symbol: Trading pair
            leverage: Leverage multiplier (1-100)
            is_cross: True for cross margin, False for isolated
        """
        try:
            result = self.exchange.update_leverage(leverage, symbol, is_cross)
            return result.get("status") == "ok"
        except Exception:
            return False


def create_trader(private_key: str, testnet: bool = False) -> AgentTrader:
    """Factory function to create an AgentTrader instance."""
    return AgentTrader(private_key, testnet)
