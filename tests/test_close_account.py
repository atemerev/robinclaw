"""Tests for close-account endpoint and related model functions."""

import hashlib
import os
import sys
import tempfile
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Create test DB BEFORE importing models
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test.db")
os.environ["ROBINCLAW_DB_PATH"] = TEST_DB_PATH

# Patch DB_PATH in models before it's imported by the app
import models
models.DB_PATH = TEST_DB_PATH
models.init_db()


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset the database for each test."""
    # Clear and reinit
    if os.path.exists(TEST_DB_PATH):
        os.unlink(TEST_DB_PATH)
    models.init_db()
    yield


# Test API key - must start with "rc_"
TEST_API_KEY = "rc_test_api_key_12345"
TEST_API_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()


@pytest.fixture
def sample_agent():
    """Create a sample agent for testing."""
    from models import create_agent, Agent
    
    agent = Agent(
        id="test-agent-123",
        name="TestAgent",
        wallet_address="0x1234567890abcdef1234567890abcdef12345678",
        private_key_encrypted="encrypted_key_here",
        api_key_hash=TEST_API_KEY_HASH,
        deposit_amount=1000.0,
        deposit_tx="0xdeposit123",
        created_at=datetime.now(UTC),
        status="active",
    )
    create_agent(agent)
    return agent


class TestUpdateAgentStatus:
    """Tests for update_agent_status helper function."""
    
    def test_update_status_only(self, sample_agent):
        """Test updating just the status field."""
        from models import update_agent_status, get_agent
        
        update_agent_status(sample_agent.id, "closed")
        
        agent = get_agent(sample_agent.id)
        assert agent.status == "closed"
    
    def test_update_with_kwargs(self, sample_agent):
        """Test updating status with additional fields."""
        from models import update_agent_status, get_agent
        
        now = datetime.now(UTC)
        update_agent_status(
            sample_agent.id,
            "closed",
            final_equity=1500.0,
            final_pnl=500.0,
            final_pnl_pct=50.0,
            closed_at=now,
        )
        
        agent = get_agent(sample_agent.id)
        assert agent.status == "closed"
        assert agent.final_equity == 1500.0
        assert agent.final_pnl == 500.0
        assert agent.final_pnl_pct == 50.0
        assert agent.closed_at is not None
    
    def test_update_ignores_none_values(self, sample_agent):
        """Test that None kwargs are ignored."""
        from models import update_agent_status, get_agent
        
        update_agent_status(
            sample_agent.id,
            "closed",
            final_equity=1200.0,
            final_pnl=None,  # Should be ignored
        )
        
        agent = get_agent(sample_agent.id)
        assert agent.final_equity == 1200.0
        assert agent.final_pnl is None


class TestCloseAccountEndpoint:
    """Tests for the /api/close-account endpoint."""
    
    @pytest.fixture
    def mock_trader(self):
        """Create a mock trader with configurable responses."""
        trader = MagicMock()
        
        # Default: no positions, no orders
        trader.get_positions.return_value = []
        trader.cancel_all_orders.return_value = 0
        trader.get_balance.return_value = {
            "account_value": 1500.0,
            "withdrawable": 1500.0,
        }
        
        return trader
    
    @pytest.fixture
    def client(self, sample_agent, mock_trader):
        """Create test client with mocked trader."""
        from fastapi.testclient import TestClient
        
        with patch("robinclaw.web.app.create_trader", return_value=mock_trader):
            from robinclaw.web.app import app
            yield TestClient(app)
    
    def test_close_account_success(self, client, sample_agent, mock_trader):
        """Test successful account closure with no positions."""
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["final_balance"] == 1500.0
        assert data["final_pnl"] == 500.0  # 1500 - 1000 deposit
    
    def test_close_account_with_positions(self, client, sample_agent, mock_trader):
        """Test account closure with open positions."""
        # Mock an open position
        position = MagicMock()
        position.symbol = "BTC"
        position.size = "0.1"
        position.unrealized_pnl = 50.0
        mock_trader.get_positions.return_value = [position]
        
        close_result = MagicMock()
        close_result.success = True
        mock_trader.close_position.return_value = close_result
        
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert len(data["results"]["positions_closed"]) == 1
        assert data["results"]["positions_closed"][0]["symbol"] == "BTC"
    
    def test_close_account_partial_failure(self, client, sample_agent, mock_trader):
        """Test account closure with failed position close."""
        position = MagicMock()
        position.symbol = "ETH"
        position.size = "1.0"
        mock_trader.get_positions.return_value = [position]
        
        close_result = MagicMock()
        close_result.success = False
        close_result.message = "Insufficient liquidity"
        mock_trader.close_position.return_value = close_result
        
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"
        assert "errors" in data["results"]
        assert len(data["results"]["errors"]) == 1
    
    def test_close_account_already_closed(self, client, sample_agent):
        """Test closing an already-closed account."""
        from models import update_agent_status
        update_agent_status(sample_agent.id, "closed")
        
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 400
        assert "already closed" in response.json()["detail"].lower()
    
    def test_close_account_invalid_api_key(self, client):
        """Test with invalid API key."""
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": "rc_invalid_key"},
        )
        
        assert response.status_code == 401
    
    def test_close_account_bad_api_key_format(self, client):
        """Test with API key missing rc_ prefix."""
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": "invalid-key-no-prefix"},
        )
        
        assert response.status_code == 401
        assert "format" in response.json()["detail"].lower()
    
    def test_close_account_missing_api_key(self, client):
        """Test without API key header."""
        response = client.post("/api/close-account")
        
        assert response.status_code == 401
    
    def test_pnl_calculation_with_profit(self, client, sample_agent, mock_trader):
        """Test P&L calculation when profitable."""
        mock_trader.get_balance.return_value = {
            "account_value": 2000.0,
            "withdrawable": 2000.0,
        }
        
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["final_pnl"] == 1000.0  # 2000 - 1000 deposit
    
    def test_pnl_calculation_with_loss(self, client, sample_agent, mock_trader):
        """Test P&L calculation when at a loss."""
        mock_trader.get_balance.return_value = {
            "account_value": 800.0,
            "withdrawable": 800.0,
        }
        
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["final_pnl"] == -200.0  # 800 - 1000 deposit
    
    def test_db_updated_on_close(self, client, sample_agent, mock_trader):
        """Test that database is properly updated on close."""
        from models import get_agent
        
        mock_trader.get_balance.return_value = {
            "account_value": 1500.0,
            "withdrawable": 1500.0,
        }
        
        response = client.post(
            "/api/close-account",
            headers={"X-API-Key": TEST_API_KEY},
        )
        
        assert response.status_code == 200
        
        # Verify DB state
        agent = get_agent(sample_agent.id)
        assert agent.status == "closed"
        assert agent.final_equity == 1500.0
        assert agent.final_pnl == 500.0
        assert agent.final_pnl_pct == 50.0  # 500/1000 * 100
        assert agent.closed_at is not None


class TestApiKeyValidation:
    """Tests for API key authentication."""
    
    def test_valid_api_key_hash(self, sample_agent):
        """Test that API key is properly hashed and matched."""
        from models import get_agent_by_api_key_hash
        
        agent = get_agent_by_api_key_hash(TEST_API_KEY_HASH)
        assert agent is not None
        assert agent.id == sample_agent.id
    
    def test_invalid_api_key_hash(self, sample_agent):
        """Test that wrong API key returns None."""
        from models import get_agent_by_api_key_hash
        
        wrong_hash = hashlib.sha256(b"rc_wrong_key").hexdigest()
        agent = get_agent_by_api_key_hash(wrong_hash)
        assert agent is None
