"""Tests for TradingGuard — tick size, volume, contract type, price bounds."""

import pytest
from decimal import Decimal
from qwed_finance.guards.trading_guard import (
    TradingGuard,
    TradingResult,
    MarketRules,
    ContractType,
    OrderSide,
)


@pytest.fixture
def guard() -> TradingGuard:
    """TradingGuard with two sample markets pre-registered."""
    g = TradingGuard()
    g.register_market(
        "PRES-2028-WIN",
        MarketRules(
            tick_size=Decimal("0.01"),
            min_price=Decimal("0.01"),
            max_price=Decimal("0.99"),
            max_contracts=500,
        ),
    )
    g.register_market(
        "BTC-100K",
        MarketRules(
            tick_size=Decimal("0.05"),
            min_price=Decimal("0.05"),
            max_price=Decimal("0.95"),
            max_contracts=100,
            allowed_contract_types=["binary"],
        ),
    )
    return g


# ── Happy path ──────────────────────────────────────────────

class TestVerifyOrderSuccess:

    def test_valid_binary_order(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.65"),
            volume=10,
            side="buy",
        )
        assert result.verified is True
        assert result.market_id == "PRES-2028-WIN"
        assert "tick_size" in result.checks_passed

    def test_valid_order_with_str_price(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="categorical",
            price="0.50",
            volume=1,
        )
        assert result.verified is True

    def test_valid_order_with_int_price(self, guard: TradingGuard):
        """int(0) edge is below min_price, but int prices that satisfy bounds pass."""
        # Register a special market that allows int-style prices
        guard.register_market(
            "INT-MKT",
            MarketRules(
                tick_size=Decimal("1"),
                min_price=Decimal("1"),
                max_price=Decimal("100"),
                max_contracts=50,
            ),
        )
        result = guard.verify_order(
            market_id="INT-MKT",
            contract_type="binary",
            price=5,
            volume=10,
        )
        assert result.verified is True

    def test_sell_side(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.30"),
            volume=50,
            side="sell",
        )
        assert result.verified is True
        assert "order_side" in result.checks_passed


# ── Tick size failures ──────────────────────────────────────

class TestTickSize:

    def test_tick_size_mismatch(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.653"),
            volume=10,
        )
        assert result.verified is False
        assert result.risk == "TICK_SIZE_MISMATCH"
        assert "tick_size" in result.checks_failed

    def test_tick_size_mismatch_larger_step(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="BTC-100K",
            contract_type="binary",
            price=Decimal("0.52"),
            volume=5,
        )
        assert result.verified is False
        assert result.risk == "TICK_SIZE_MISMATCH"

    def test_tick_size_exact_multiple(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="BTC-100K",
            contract_type="binary",
            price=Decimal("0.55"),
            volume=5,
        )
        assert result.verified is True


# ── Price bounds ────────────────────────────────────────────

class TestPriceBounds:

    def test_price_below_min(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.00"),
            volume=10,
        )
        assert result.verified is False
        assert "price_bounds" in result.checks_failed

    def test_price_above_max(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("1.00"),
            volume=10,
        )
        assert result.verified is False
        assert "price_bounds" in result.checks_failed

    def test_price_at_exact_boundary(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.99"),
            volume=1,
        )
        assert result.verified is True


# ── Volume limits ───────────────────────────────────────────

class TestVolumeLimits:

    def test_volume_exceeds_max(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.50"),
            volume=501,
        )
        assert result.verified is False
        assert result.risk == "VOLUME_VIOLATION"
        assert "volume_max" in result.checks_failed

    def test_volume_zero(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.50"),
            volume=0,
        )
        assert result.verified is False
        assert "volume_min" in result.checks_failed

    def test_volume_negative(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.50"),
            volume=-1,
        )
        assert result.verified is False


# ── Contract type & side ────────────────────────────────────

class TestContractAndSide:

    def test_invalid_contract_type(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="futures",
            price=Decimal("0.50"),
            volume=10,
        )
        assert result.verified is False
        assert result.risk == "INVALID_CONTRACT_TYPE"

    def test_market_restricted_contract_types(self, guard: TradingGuard):
        """BTC-100K only allows binary."""
        result = guard.verify_order(
            market_id="BTC-100K",
            contract_type="categorical",
            price=Decimal("0.50"),
            volume=5,
        )
        assert result.verified is False
        assert "contract_type" in result.checks_failed

    def test_invalid_side(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price=Decimal("0.50"),
            volume=10,
            side="short",
        )
        assert result.verified is False
        assert result.risk == "INVALID_ORDER_SIDE"


# ── Edge cases ──────────────────────────────────────────────

class TestEdgeCases:

    def test_float_price_raises_typeerror(self, guard: TradingGuard):
        with pytest.raises(TypeError, match="Floats are not permitted"):
            guard.verify_order(
                market_id="PRES-2028-WIN",
                contract_type="binary",
                price=0.65,
                volume=10,
            )

    def test_unknown_market(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="NONEXISTENT",
            contract_type="binary",
            price=Decimal("0.50"),
            volume=10,
        )
        assert result.verified is False
        assert result.risk == "UNKNOWN_MARKET"

    def test_invalid_price_string(self, guard: TradingGuard):
        result = guard.verify_order(
            market_id="PRES-2028-WIN",
            contract_type="binary",
            price="not-a-number",
            volume=10,
        )
        assert result.verified is False
        assert result.risk == "INVALID_PRICE"

    def test_register_empty_market_id_raises(self):
        g = TradingGuard()
        with pytest.raises(ValueError, match="non-empty"):
            g.register_market("", MarketRules(tick_size=Decimal("0.01")))


# ── Batch verification ──────────────────────────────────────

class TestBatchVerification:

    def test_batch_mixed(self, guard: TradingGuard):
        orders = [
            {"market_id": "PRES-2028-WIN", "contract_type": "binary",
             "price": Decimal("0.50"), "volume": 10},
            {"market_id": "PRES-2028-WIN", "contract_type": "binary",
             "price": Decimal("0.653"), "volume": 10},  # bad tick
        ]
        summary = guard.verify_order_batch(orders)
        assert summary["total"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["all_verified"] is False

    def test_batch_all_pass(self, guard: TradingGuard):
        orders = [
            {"market_id": "PRES-2028-WIN", "contract_type": "binary",
             "price": Decimal("0.50"), "volume": 10, "side": "buy"},
            {"market_id": "PRES-2028-WIN", "contract_type": "binary",
             "price": Decimal("0.75"), "volume": 5, "side": "sell"},
        ]
        summary = guard.verify_order_batch(orders)
        assert summary["all_verified"] is True
        assert summary["passed"] == 2
