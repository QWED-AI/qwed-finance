"""
TradingGuard — Deterministic verification for autonomous trading payloads.

Verifies order parameters (tick size, volume limits, contract types, price bounds)
before they hit market execution APIs. Prevents hallucinated trade parameters
from causing financial losses.

Uses Python's Decimal for exact arithmetic — no IEEE-754 floating-point
surprises in financial-critical code.
"""

from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class ContractType(str, Enum):
    """Supported contract types for prediction markets."""
    BINARY = "binary"
    CATEGORICAL = "categorical"


class OrderSide(str, Enum):
    """Order direction."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class MarketRules:
    """
    Configuration for a specific market's constraints.
    All monetary values use Decimal for symbolic precision.
    """
    tick_size: Decimal
    min_price: Decimal = Decimal("0.01")
    max_price: Decimal = Decimal("0.99")
    max_contracts: int = 1000
    allowed_contract_types: List[str] = field(
        default_factory=lambda: ["binary", "categorical"]
    )


@dataclass
class TradingResult:
    """Result of a trade verification check."""
    verified: bool
    market_id: str = ""
    risk: str = ""
    message: str = ""
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    verification_mode: str = "DETERMINISTIC"


class TradingGuard:
    """
    Verifies autonomous trading payloads for prediction markets
    (e.g., Kalshi, Polymarket) and traditional order books.

    Ensures:
    - Price is a valid multiple of the tick size
    - Volume is within market limits
    - Contract type is valid for the target market
    - Price is within allowed bounds
    - Order side is valid

    All arithmetic uses Decimal to prevent floating-point drift.
    """

    def __init__(self, market_rules: Optional[Dict[str, MarketRules]] = None):
        """
        Args:
            market_rules: Mapping of market_id → MarketRules.
                          If None, a strict default rule set is used.
        """
        self._rules: Dict[str, MarketRules] = market_rules or {}

    def register_market(self, market_id: str, rules: MarketRules) -> None:
        """Register rules for a specific market."""
        if not isinstance(market_id, str) or not market_id.strip():
            raise ValueError("market_id must be a non-empty string")
        self._rules[market_id] = rules

    def verify_order(
        self,
        market_id: str,
        contract_type: str,
        price: Decimal | str | int,
        volume: int,
        side: str = "buy",
    ) -> TradingResult:
        """
        Verify a single order against market rules.

        Args:
            market_id: Target market identifier.
            contract_type: "binary" or "categorical".
            price: Order price. Accepts Decimal, str, or int.
                   Floats are explicitly rejected.
            volume: Number of contracts.
            side: "buy" or "sell".

        Returns:
            TradingResult with verification status and details.

        Raises:
            TypeError: If price is a float (use Decimal or str instead).
        """
        if isinstance(price, float):
            raise TypeError(
                "Floats are not permitted for price. "
                "Use Decimal or str for symbolic precision."
            )

        # --- Convert price to Decimal ---
        try:
            price_dec = Decimal(str(price))
        except (InvalidOperation, ValueError):
            return TradingResult(
                verified=False,
                market_id=market_id,
                risk="INVALID_PRICE",
                message=f"Cannot parse price: {price!r}",
                checks_failed=["price_parse"],
            )

        # --- Resolve market rules ---
        rules = self._rules.get(market_id)
        if rules is None:
            return TradingResult(
                verified=False,
                market_id=market_id,
                risk="UNKNOWN_MARKET",
                message=f"No rules registered for market: {market_id}",
                checks_failed=["market_lookup"],
            )

        # --- Run all checks ---
        checks_passed: List[str] = []
        checks_failed: List[str] = []

        self._check_contract_type(contract_type, rules, checks_passed, checks_failed)
        self._check_order_side(side, checks_passed, checks_failed)
        self._check_tick_size(price_dec, rules, checks_passed, checks_failed)
        self._check_price_bounds(price_dec, rules, checks_passed, checks_failed)
        self._check_volume(volume, rules, checks_passed, checks_failed)

        # --- Build result ---
        if checks_failed:
            failure_details = self._build_failure_message(
                checks_failed, price_dec, rules, contract_type, volume, side
            )
            risk = self._classify_risk(checks_failed)
            return TradingResult(
                verified=False,
                market_id=market_id,
                risk=risk,
                message=failure_details,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )

        return TradingResult(
            verified=True,
            market_id=market_id,
            message="All trade parameters verified",
            checks_passed=checks_passed,
        )

    # ----- Individual check methods -----

    @staticmethod
    def _check_contract_type(
        contract_type: str, rules: MarketRules,
        passed: List[str], failed: List[str],
    ) -> None:
        if contract_type not in rules.allowed_contract_types:
            failed.append("contract_type")
        else:
            passed.append("contract_type")

    @staticmethod
    def _check_order_side(
        side: str, passed: List[str], failed: List[str],
    ) -> None:
        valid_sides = {"buy", "sell"}
        if side.lower() not in valid_sides:
            failed.append("order_side")
        else:
            passed.append("order_side")

    @staticmethod
    def _check_tick_size(
        price: Decimal, rules: MarketRules,
        passed: List[str], failed: List[str],
    ) -> None:
        if rules.tick_size > 0 and price % rules.tick_size != 0:
            failed.append("tick_size")
        else:
            passed.append("tick_size")

    @staticmethod
    def _check_price_bounds(
        price: Decimal, rules: MarketRules,
        passed: List[str], failed: List[str],
    ) -> None:
        if price < rules.min_price or price > rules.max_price:
            failed.append("price_bounds")
        else:
            passed.append("price_bounds")

    @staticmethod
    def _check_volume(
        volume: int, rules: MarketRules,
        passed: List[str], failed: List[str],
    ) -> None:
        if not isinstance(volume, int) or volume < 1:
            failed.append("volume_min")
        elif volume > rules.max_contracts:
            failed.append("volume_max")
        else:
            passed.append("volume")

    def verify_order_batch(
        self, orders: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Verify a batch of orders. Returns summary and individual results.

        Each order dict must contain: market_id, contract_type, price, volume.
        Optional: side (defaults to "buy").
        """
        results = []
        passed = 0
        failed = 0

        for order in orders:
            result = self.verify_order(
                market_id=order["market_id"],
                contract_type=order["contract_type"],
                price=order["price"],
                volume=order["volume"],
                side=order.get("side", "buy"),
            )
            results.append(result)
            if result.verified:
                passed += 1
            else:
                failed += 1

        return {
            "total": len(orders),
            "passed": passed,
            "failed": failed,
            "results": results,
            "all_verified": failed == 0,
        }

    # ----- Private helpers -----

    @staticmethod
    def _classify_risk(failed_checks: List[str]) -> str:
        """Map failed checks to a risk category."""
        if "tick_size" in failed_checks:
            return "TICK_SIZE_MISMATCH"
        if "price_bounds" in failed_checks:
            return "PRICE_OUT_OF_BOUNDS"
        if "volume_max" in failed_checks or "volume_min" in failed_checks:
            return "VOLUME_VIOLATION"
        if "contract_type" in failed_checks:
            return "INVALID_CONTRACT_TYPE"
        if "order_side" in failed_checks:
            return "INVALID_ORDER_SIDE"
        return "TRADE_VERIFICATION_FAILED"

    @staticmethod
    def _build_failure_message(
        failed: List[str],
        price: Decimal,
        rules: MarketRules,
        contract_type: str,
        volume: int,
        side: str,
    ) -> str:
        """Build a human-readable failure message."""
        parts = []
        if "tick_size" in failed:
            parts.append(
                f"Price {price} is not a multiple of tick size {rules.tick_size}"
            )
        if "price_bounds" in failed:
            parts.append(
                f"Price {price} outside bounds [{rules.min_price}, {rules.max_price}]"
            )
        if "volume_max" in failed:
            parts.append(
                f"Volume {volume} exceeds max {rules.max_contracts}"
            )
        if "volume_min" in failed:
            parts.append(f"Volume must be a positive integer, got {volume}")
        if "contract_type" in failed:
            parts.append(
                f"Invalid contract type '{contract_type}', "
                f"allowed: {rules.allowed_contract_types}"
            )
        if "order_side" in failed:
            parts.append(f"Invalid order side '{side}', allowed: buy, sell")
        return "; ".join(parts) if parts else "Trade verification failed"
