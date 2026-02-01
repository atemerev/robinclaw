"""Database models for Robinclaw."""

import sqlite3
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import json

DB_PATH = Path(__file__).parent / "robinclaw.db"


@dataclass
class Agent:
    id: str
    name: str
    wallet_address: str
    private_key_encrypted: str  # AES encrypted
    api_key_hash: str  # SHA256 hash of API key (we never store plain API key)
    
    deposit_amount: float
    deposit_tx: Optional[str]
    created_at: datetime
    status: str  # 'pending_deposit', 'active', 'closed'
    
    # Populated on close
    closed_at: Optional[datetime] = None
    final_equity: Optional[float] = None
    final_pnl: Optional[float] = None
    final_pnl_pct: Optional[float] = None
    withdrawal_tx: Optional[str] = None
    withdrawal_address: Optional[str] = None


@dataclass
class Trade:
    id: int
    agent_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    size: float
    price: float
    realized_pnl: float
    timestamp: datetime


def init_db():
    """Initialize the database schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            wallet_address TEXT NOT NULL UNIQUE,
            private_key_encrypted TEXT NOT NULL,
            api_key_hash TEXT NOT NULL,
            deposit_amount REAL NOT NULL,
            deposit_tx TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_deposit',
            closed_at TEXT,
            final_equity REAL,
            final_pnl REAL,
            final_pnl_pct REAL,
            withdrawal_tx TEXT,
            withdrawal_address TEXT
        )
    """)
    
    # Migration: add api_key_hash column if it doesn't exist
    try:
        c.execute("ALTER TABLE agents ADD COLUMN api_key_hash TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            size REAL NOT NULL,
            price REAL NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        )
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades(agent_id)
    """)
    
    conn.commit()
    conn.close()


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_agent(agent: Agent) -> Agent:
    """Insert a new agent."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO agents (id, name, wallet_address, private_key_encrypted, api_key_hash,
                          deposit_amount, deposit_tx, created_at, status, withdrawal_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (agent.id, agent.name, agent.wallet_address, agent.private_key_encrypted,
          agent.api_key_hash, agent.deposit_amount, agent.deposit_tx, 
          agent.created_at.isoformat(), agent.status, agent.withdrawal_address))
    conn.commit()
    conn.close()
    return agent


def get_agent(agent_id: str) -> Optional[Agent]:
    """Get agent by ID."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_agent(row)


def get_agent_by_name(name: str) -> Optional[Agent]:
    """Get agent by name."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM agents WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_agent(row)


def get_agent_by_api_key_hash(api_key_hash: str) -> Optional[Agent]:
    """Get agent by API key hash."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM agents WHERE api_key_hash = ?", (api_key_hash,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_agent(row)


def get_active_agents() -> list[Agent]:
    """Get all active agents."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM agents WHERE status = 'active' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [_row_to_agent(row) for row in rows]


def get_closed_agents() -> list[Agent]:
    """Get all closed agents (hall of fame)."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM agents 
        WHERE status = 'closed' 
        ORDER BY final_pnl_pct DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [_row_to_agent(row) for row in rows]


def update_agent_status(agent_id: str, status: str, **kwargs):
    """Update agent status and optional fields."""
    conn = get_db()
    c = conn.cursor()
    
    updates = ["status = ?"]
    values = [status]
    
    for key, value in kwargs.items():
        if value is not None:
            updates.append(f"{key} = ?")
            if isinstance(value, datetime):
                values.append(value.isoformat())
            else:
                values.append(value)
    
    values.append(agent_id)
    c.execute(f"UPDATE agents SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def record_trade(trade: Trade):
    """Record a trade."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades (agent_id, symbol, side, size, price, realized_pnl, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (trade.agent_id, trade.symbol, trade.side, trade.size, 
          trade.price, trade.realized_pnl, trade.timestamp.isoformat()))
    conn.commit()
    conn.close()


def get_agent_trades(agent_id: str) -> list[Trade]:
    """Get all trades for an agent."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM trades WHERE agent_id = ? ORDER BY timestamp DESC
    """, (agent_id,))
    rows = c.fetchall()
    conn.close()
    return [_row_to_trade(row) for row in rows]


def get_agent_stats(agent_id: str) -> dict:
    """Get trading stats for an agent."""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
            SUM(realized_pnl) as total_pnl
        FROM trades WHERE agent_id = ?
    """, (agent_id,))
    row = c.fetchone()
    conn.close()
    
    total = row['total_trades'] or 0
    wins = row['winning_trades'] or 0
    pnl = row['total_pnl'] or 0
    
    return {
        'total_trades': total,
        'winning_trades': wins,
        'win_rate': (wins / total * 100) if total > 0 else 0,
        'total_pnl': pnl
    }


def _row_to_agent(row) -> Agent:
    return Agent(
        id=row['id'],
        name=row['name'],
        wallet_address=row['wallet_address'],
        private_key_encrypted=row['private_key_encrypted'],
        api_key_hash=row['api_key_hash'] or '',
        deposit_amount=row['deposit_amount'],
        deposit_tx=row['deposit_tx'],
        created_at=datetime.fromisoformat(row['created_at']),
        status=row['status'],
        closed_at=datetime.fromisoformat(row['closed_at']) if row['closed_at'] else None,
        final_equity=row['final_equity'],
        final_pnl=row['final_pnl'],
        final_pnl_pct=row['final_pnl_pct'],
        withdrawal_tx=row['withdrawal_tx'],
        withdrawal_address=row['withdrawal_address']
    )


def _row_to_trade(row) -> Trade:
    return Trade(
        id=row['id'],
        agent_id=row['agent_id'],
        symbol=row['symbol'],
        side=row['side'],
        size=row['size'],
        price=row['price'],
        realized_pnl=row['realized_pnl'],
        timestamp=datetime.fromisoformat(row['timestamp'])
    )


# Initialize on import
init_db()
