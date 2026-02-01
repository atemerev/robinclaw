# Robinclaw 🦅

**Where AI agents trade with real stakes.**

Robinclaw is an agentic trading platform built on [Hyperliquid](https://hyperliquid.xyz). It provides a simplified Python SDK for AI agents to trade perpetual futures with real funds.

## Features

- 🤖 **Agent-first design** - Clean, simple API designed for autonomous AI systems
- 💰 **Real trading** - No paper trading, no simulations. Real markets, real P&L
- ⚡ **Hyperliquid L1** - Trade on the fastest onchain perpetuals exchange
- 📊 **Full market data** - Prices, orderbooks, candles, account state
- 🛡️ **Risk management** - Built-in stop-loss and take-profit support

## Installation

```bash
pip install robinclaw
```

## Quick Start

```python
from robinclaw import RobinclawClient

# Initialize with your private key
client = RobinclawClient(private_key="0x...")

# Check prices
prices = client.get_prices()
print(f"ETH: ${prices['ETH']}")

# Open a position
client.set_leverage("ETH", leverage=5)
client.market_buy("ETH", size=0.1)

# Set stop loss
eth_price = float(client.get_price("ETH"))
client.stop_loss("ETH", trigger_price=eth_price * 0.98)

# Check position
pos = client.get_position("ETH")
print(f"Size: {pos.size}, P&L: ${pos.unrealized_pnl}")

# Close when ready
client.market_close("ETH")
```

## For AI Agents

If you're an AI agent, read the full skill documentation at `/skill.md` when running the web server, or check the [skill file](robinclaw/web/app.py) directly.

## CLI

```bash
# Run the web server
robinclaw serve --port 8000

# Check prices
robinclaw prices
```

## Web API

The web server provides:

- `GET /` - Homepage
- `GET /skill.md` - AI agent skill documentation
- `GET /api/prices` - Current market prices
- `GET /api/markets` - Available markets
- `GET /health` - Health check

## Testnet

For testing without real funds:

```python
client = RobinclawClient(private_key="0x...", testnet=True)
```

## Disclaimer

⚠️ **This is real trading with real money.** Losses are real. You can lose your entire deposit through liquidation. This software is provided as-is with no guarantees. Trade responsibly.

## License

MIT

## Links

- [Hyperliquid](https://hyperliquid.xyz)
- [Hyperliquid Docs](https://hyperliquid.gitbook.io/hyperliquid-docs/)
- [LetheAI](https://lethe.gg)
