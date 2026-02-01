"""Robinclaw CLI."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Robinclaw - AI Agent Trading Platform")
    subparsers = parser.add_subparsers(dest="command")
    
    # Server command
    server = subparsers.add_parser("serve", help="Run the web server")
    server.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    server.add_argument("--port", type=int, default=8000, help="Port to bind to")
    
    # Prices command
    subparsers.add_parser("prices", help="Show current market prices")
    
    args = parser.parse_args()
    
    if args.command == "serve":
        from robinclaw.web.app import run_server
        run_server(host=args.host, port=args.port)
    
    elif args.command == "prices":
        import httpx
        resp = httpx.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "allMids"},
        )
        prices = resp.json()
        # Show top coins
        top_coins = ["BTC", "ETH", "SOL", "AVAX", "ARB", "OP", "MATIC", "DOGE", "LINK"]
        print("\\n  Hyperliquid Perpetual Prices\\n  " + "=" * 30)
        for coin in top_coins:
            if coin in prices:
                price = float(prices[coin])
                print(f"  {coin:8} ${price:>12,.2f}")
        print()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
