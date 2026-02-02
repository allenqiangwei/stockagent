"""Tests for stop loss manager."""

import pytest
from src.risk_control.stop_loss_manager import (
    StopLossManager,
    StopLossResult,
    StopType,
    Position
)


class TestStopType:
    """Tests for StopType enum."""

    def test_stop_type_values(self):
        """Test stop type enum values."""
        assert StopType.NONE.value == "none"
        assert StopType.FIXED.value == "fixed"
        assert StopType.TRAILING.value == "trailing"
        assert StopType.PROFIT_LOCK.value == "profit_lock"


class TestPosition:
    """Tests for Position dataclass."""

    def test_position_creation(self):
        """Test position can be created."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=11.0,
            quantity=1000,
            entry_date="2024-01-15"
        )
        assert pos.stock_code == "000001.SZ"
        assert pos.entry_price == 10.0

    def test_position_pnl_pct(self):
        """Test P&L percentage calculation."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=12.0,
            quantity=1000,
            entry_date="2024-01-15"
        )
        assert pos.pnl_pct == 20.0  # (12-10)/10 * 100

    def test_position_pnl_value(self):
        """Test P&L value calculation."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=12.0,
            quantity=1000,
            entry_date="2024-01-15"
        )
        assert pos.pnl_value == 2000.0  # (12-10) * 1000

    def test_position_highest_price_tracking(self):
        """Test highest price tracking."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=12.0,
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=15.0
        )
        assert pos.highest_price == 15.0


class TestStopLossResult:
    """Tests for StopLossResult dataclass."""

    def test_result_creation(self):
        """Test result can be created."""
        result = StopLossResult(
            stock_code="000001.SZ",
            should_stop=True,
            stop_type=StopType.FIXED,
            stop_price=9.5,
            current_price=9.0,
            reason="Price below fixed stop loss"
        )
        assert result.should_stop
        assert result.stop_type == StopType.FIXED


class TestStopLossManager:
    """Tests for StopLossManager."""

    @pytest.fixture
    def manager(self):
        """Create manager with default settings."""
        return StopLossManager()

    def test_manager_initialization(self, manager):
        """Test manager initializes correctly."""
        assert manager.fixed_stop_pct == 0.05
        assert manager.atr_multiplier == 2.0

    def test_manager_custom_settings(self):
        """Test custom settings."""
        manager = StopLossManager(
            fixed_stop_pct=0.08,
            atr_multiplier=3.0
        )
        assert manager.fixed_stop_pct == 0.08
        assert manager.atr_multiplier == 3.0

    def test_fixed_stop_triggered(self, manager):
        """Test fixed stop loss triggers at -5%."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=9.4,  # -6%, below -5% threshold
            quantity=1000,
            entry_date="2024-01-15"
        )

        result = manager.check_stop_loss(pos, atr=0.3)

        assert result.should_stop
        assert result.stop_type == StopType.FIXED
        assert result.stop_price == 9.5  # 10 * (1 - 0.05)

    def test_no_stop_when_above_threshold(self, manager):
        """Test no stop when price is above all thresholds."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=10.5,  # +5%, no stop needed
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=10.5
        )

        result = manager.check_stop_loss(pos, atr=0.3)

        assert not result.should_stop
        assert result.stop_type == StopType.NONE

    def test_trailing_stop_triggered(self, manager):
        """Test trailing stop (2x ATR) triggers on pullback."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=11.2,  # Current price
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=12.0  # Was at 12, now at 11.2
        )

        # ATR = 0.5, trailing stop = highest - 2*ATR = 12 - 1.0 = 11.0
        # Current 11.2 > 11.0, so no stop
        result = manager.check_stop_loss(pos, atr=0.5)
        assert not result.should_stop

        # Now price drops further
        pos.current_price = 10.8  # Below trailing stop of 11.0
        result = manager.check_stop_loss(pos, atr=0.5)

        assert result.should_stop
        assert result.stop_type == StopType.TRAILING

    def test_profit_lock_tier1(self, manager):
        """Test tier 1 profit lock: 10% gain -> lock 5% profit."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=10.4,  # Current at +4%
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=11.0  # Was at +10%
        )

        # Tier 1: if highest reached +10%, stop at entry + 5% = 10.5
        # Current 10.4 < 10.5 -> should stop
        result = manager.check_stop_loss(pos, atr=0.3)

        assert result.should_stop
        assert result.stop_type == StopType.PROFIT_LOCK

    def test_profit_lock_tier2(self, manager):
        """Test tier 2 profit lock: 20% gain -> lock 10% profit."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=10.9,  # Current at +9%
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=12.0  # Was at +20%
        )

        # Tier 2: if highest reached +20%, stop at entry + 10% = 11.0
        # Current 10.9 < 11.0 -> should stop
        # Use ATR=1.0 so trailing stop (12.0 - 2.0 = 10.0) < profit lock (11.0)
        result = manager.check_stop_loss(pos, atr=1.0)

        assert result.should_stop
        assert result.stop_type == StopType.PROFIT_LOCK

    def test_profit_lock_tier3(self, manager):
        """Test tier 3 profit lock: 30% gain -> lock 20% profit."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=11.9,  # Current at +19%
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=13.0  # Was at +30%
        )

        # Tier 3: if highest reached +30%, stop at entry + 20% = 12.0
        # Current 11.9 < 12.0 -> should stop
        # Use ATR=1.0 so trailing stop (13.0 - 2.0 = 11.0) < profit lock (12.0)
        result = manager.check_stop_loss(pos, atr=1.0)

        assert result.should_stop
        assert result.stop_type == StopType.PROFIT_LOCK

    def test_most_restrictive_stop_used(self, manager):
        """Test that the most restrictive (highest) stop price is used."""
        # Position with significant gain and high ATR
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=11.0,
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=11.5  # +15% peak
        )

        # Fixed stop: 10 * 0.95 = 9.5
        # Trailing stop: 11.5 - 2*0.3 = 10.9
        # Profit lock (tier 1 at 10%): 10 * 1.05 = 10.5
        # Most restrictive is trailing at 10.9

        result = manager.check_stop_loss(pos, atr=0.3)

        # Current 11.0 > 10.9, so no stop yet
        assert not result.should_stop

    def test_calculate_stop_prices(self, manager):
        """Test getting all stop prices."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=11.0,
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=12.0
        )

        stops = manager.calculate_stop_prices(pos, atr=0.5)

        assert "fixed" in stops
        assert "trailing" in stops
        assert "profit_lock" in stops

        assert stops["fixed"] == pytest.approx(9.5, rel=0.01)
        assert stops["trailing"] == pytest.approx(11.0, rel=0.01)  # 12 - 2*0.5
        assert stops["profit_lock"] == pytest.approx(11.0, rel=0.01)  # tier 2

    def test_update_highest_price(self, manager):
        """Test highest price is updated correctly."""
        pos = Position(
            stock_code="000001.SZ",
            entry_price=10.0,
            current_price=11.0,
            quantity=1000,
            entry_date="2024-01-15",
            highest_price=10.5
        )

        # Should update highest
        manager.update_position(pos)
        assert pos.highest_price == 11.0

        # Lower price should not update
        pos.current_price = 10.8
        manager.update_position(pos)
        assert pos.highest_price == 11.0

    def test_check_batch(self, manager):
        """Test checking multiple positions."""
        positions = [
            Position("000001.SZ", 10.0, 9.4, 1000, "2024-01-15"),  # Stop
            Position("000002.SZ", 10.0, 10.5, 1000, "2024-01-15", highest_price=10.5),  # OK
        ]

        results = manager.check_batch(positions, atrs={"000001.SZ": 0.3, "000002.SZ": 0.3})

        assert len(results) == 2
        assert results[0].should_stop
        assert not results[1].should_stop
