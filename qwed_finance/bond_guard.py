"""
Bond Guard - Fixed income verification for bond pricing
Deterministic verification for YTM, Duration, Convexity calculations

All financial math uses Decimal for exact arithmetic.
"""

from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, ROUND_HALF_UP, getcontext
from typing import Any, Callable, Optional, Tuple
from enum import Enum

from ._numeric import (
    UnverifiableError,
    claim,
    number,
    positive_int,
    shown,
    within_tolerance,
)

# Set precision high enough for Newton-Raphson convergence
getcontext().prec = 50

_ZERO = Decimal("0")

# Most coupon periods priced: 100 years of monthly coupons, the longest
# schedule in normal issuance (century bonds). The solver loops over every
# period on each iteration, so an unbounded maturity is an unbounded
# amount of work, and one large enough overflows the period count.
MAX_COUPON_PERIODS = 1200

# Price residual, relative to the bond's price, at which the yield solver
# counts as converged. An absolute residual (it was 1e-10) let a bond with
# a tiny face value converge at any yield: every price is within 1e-10.
_PRICE_RESIDUAL = Decimal("1e-13")


def _binary_float_type(value: Any) -> Optional[Callable[[float], Any]]:
    """The binary float type of a maturity, or None for an exact value.

    A Python float (and NumPy's float64, a float subclass) reads back as
    float; another NumPy floating scalar as its own type (float32, float16).
    int, Decimal and integral types are exact and get None, so their period
    count is never snapped. Only these known types are called: a caller's
    own numbers.Real is not.
    """
    if isinstance(value, float):
        return float
    try:
        import numpy
    except ImportError:  # pragma: no cover - numpy ships with pandas
        return None
    if isinstance(value, numpy.floating):
        return type(value)
    return None


class DayCountConvention(Enum):
    """Bond day count conventions"""
    THIRTY_360 = "30/360"
    ACTUAL_360 = "ACT/360"
    ACTUAL_365 = "ACT/365"
    ACTUAL_ACTUAL = "ACT/ACT"


@dataclass
class BondResult:
    """Result of a bond verification"""
    verified: bool
    llm_value: Optional[str]
    computed_value: str
    difference: Optional[str] = None
    formula_used: Optional[str] = None
    confidence: str = "SYMBOLIC_PROOF"
    details: Optional[dict] = None


class BondGuard:
    """
    Deterministic verification for bond calculations.
    Uses Newton-Raphson for YTM solving — 100% deterministic.

    All internal math uses Decimal for exact arithmetic,
    following the TradingGuard gold standard.
    """
    
    YTM_FORMULA = "Newton-Raphson YTM Solver"
    CONVEXITY_FORMULA = "Convexity = Σ(t(t+1) × PV(CFt)) / (P × (1+y)²)"

    def __init__(self, tolerance_pct: float = 0.5, max_iterations: int = 100):
        """
        Initialize the Bond Guard.
        
        Args:
            tolerance_pct: Acceptable % difference for verification
            max_iterations: Max iterations for YTM solver
        """
        self.tolerance_pct = Decimal(str(tolerance_pct))
        self.max_iterations = max_iterations
    
    def verify_ytm(
        self,
        face_value: float,
        coupon_rate: float,
        price: float,
        years_to_maturity: float,
        llm_ytm: str,
        frequency: int = 2  # Semi-annual default
    ) -> BondResult:
        """
        Verify Yield to Maturity calculation.
        
        YTM is the rate r where:
        Price = Σ (C / (1+r/n)^t) + (FV / (1+r/n)^n)
        
        Uses Newton-Raphson iteration for solving.
        
        Args:
            face_value: Par value of bond (e.g., 1000)
            coupon_rate: Annual coupon rate (e.g., 0.05 for 5%)
            price: Current market price
            years_to_maturity: Years until maturity
            frequency: Coupon payments per year (1=annual, 2=semi, 4=quarterly)
            llm_ytm: LLM's YTM answer (e.g., "5.25%" or "0.0525")
            
        Returns:
            BondResult with verification status
        """
        try:
            # Parse LLM's YTM
            llm_rate_d = claim(self._parse_rate, llm_ytm)

            # Convert inputs to Decimal at the boundary. A bond with no face
            # value, no price, no remaining life or no coupon period has no
            # yield to solve for: the solver would return its starting guess,
            # which any claim equal to that guess would match (#98).
            fv = number(face_value, "face_value", minimum=_ZERO, exclusive=True)
            cr = number(coupon_rate, "coupon_rate", minimum=_ZERO)
            p = number(price, "price", minimum=_ZERO, exclusive=True)
            years = number(
                years_to_maturity, "years_to_maturity", minimum=_ZERO, exclusive=True
            )
            frequency = positive_int(frequency, "frequency")
            freq = Decimal(frequency)

            # Calculate periodic values
            n_periods = self._coupon_periods(years, frequency, years_to_maturity)
            coupon_payment = (fv * cr) / freq

            # Newton-Raphson to find YTM
            computed_ytm, converged = self._solve_ytm_with_status(
                fv, coupon_payment, p, n_periods, frequency
            )
            if not converged:
                # The solver ran out of iterations without pricing the bond,
                # typically stuck at a bound of its range: the value it
                # returns is not the yield, and a claim equal to it must not
                # verify (#98, #100).
                raise UnverifiableError("yield solver did not converge")

            # Compare. A rate is reported to 0.0001 %, i.e. 0.000001.
            verified, diff_pct = within_tolerance(
                computed_ytm, llm_rate_d, self.tolerance_pct, Decimal("0.000001")
            )

            # Format output with quantized precision
            computed_pct = (computed_ytm * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            llm_pct = (llm_rate_d * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            return BondResult(
                verified=verified,
                llm_value=f"{llm_pct}%",
                computed_value=f"{computed_pct}%",
                difference=self._difference(
                    diff_pct, computed_pct, llm_pct, verified, Decimal("0.0001"), "%"
                ),
                formula_used=self.YTM_FORMULA,
                details={
                    "face_value": str(fv),
                    "coupon_rate": f"{cr * 100}%",
                    "price": str(p),
                    "periods": n_periods,
                    "frequency": frequency
                }
            )
        except UnverifiableError as reason:
            return self._unverifiable(llm_ytm, reason, self.YTM_FORMULA)
        except DecimalException:
            return self._unverifiable(
                llm_ytm, "value outside verifiable range", self.YTM_FORMULA
            )
    
    def _solve_ytm(
        self,
        face_value: Decimal,
        coupon: Decimal,
        price: Decimal,
        n_periods: int,
        frequency: int
    ) -> Decimal:
        """Newton-Raphson YTM solver using Decimal arithmetic."""
        return self._solve_ytm_with_status(
            face_value, coupon, price, n_periods, frequency
        )[0]

    def _solve_ytm_with_status(
        self,
        face_value: Decimal,
        coupon: Decimal,
        price: Decimal,
        n_periods: int,
        frequency: int
    ) -> Tuple[Decimal, bool]:
        """_solve_ytm, also reporting whether the solver converged.

        Returns ``(ytm, converged)``. ``converged`` is True only when the
        bond priced at ``ytm`` is within ``_PRICE_RESIDUAL`` of ``price``,
        relative to the price, so a bond with a tiny face value is held to
        the same precision as any other. Every candidate is checked,
        including the one the last allowed step produced; when none meets
        the residual, ``ytm`` is wherever the solver stopped.
        """
        freq = Decimal(str(frequency))
        
        # Initial guess (current yield)
        ytm = (coupon * freq) / price
        
        for _ in range(self.max_iterations):
            # Bond price at current ytm
            pv_coupons = Decimal("0")
            for t in range(1, n_periods + 1):
                pv_coupons += coupon / ((1 + ytm / freq) ** t)
            
            pv_face = face_value / ((1 + ytm / freq) ** n_periods)
            bond_price = pv_coupons + pv_face
            
            # Derivative (duration-based approximation)
            dpv = Decimal("0")
            for t in range(1, n_periods + 1):
                dpv -= Decimal(str(t)) * coupon / ((1 + ytm / freq) ** (t + 1)) / freq
            dpv -= Decimal(str(n_periods)) * face_value / ((1 + ytm / freq) ** (n_periods + 1)) / freq
            
            # Newton step
            diff = bond_price - price
            if abs(diff) <= price * _PRICE_RESIDUAL:
                return ytm, True
            
            if dpv != 0:
                ytm = ytm - diff / dpv
            
            # Keep YTM in a reasonable range for convergence
            # Upper bound 10.0 (1000%) supports distressed debt scenarios
            ytm = max(Decimal("0.0001"), min(ytm, Decimal("10")))
        
        # The last step's candidate has not been priced yet.
        final_price = self._bond_price(face_value, coupon, ytm, n_periods, freq)
        return ytm, abs(final_price - price) <= price * _PRICE_RESIDUAL

    @staticmethod
    def _bond_price(
        face_value: Decimal, coupon: Decimal, ytm: Decimal, n_periods: int, freq: Decimal
    ) -> Decimal:
        """Price of the bond at ``ytm``: discounted coupons plus face value."""
        pv_coupons = Decimal("0")
        for t in range(1, n_periods + 1):
            pv_coupons += coupon / ((1 + ytm / freq) ** t)
        return pv_coupons + face_value / ((1 + ytm / freq) ** n_periods)
    
    def verify_duration(
        self,
        face_value: float,
        coupon_rate: float,
        ytm: float,
        years_to_maturity: float,
        llm_duration: str,
        frequency: int = 2
    ) -> BondResult:
        """
        Verify Macaulay Duration calculation.
        
        Duration = Σ (t × PV(CFt)) / Price
        
        Duration measures interest rate sensitivity.
        
        Args:
            face_value: Par value of bond
            coupon_rate: Annual coupon rate
            ytm: Yield to maturity (annual)
            years_to_maturity: Years until maturity
            frequency: Coupon payments per year
            llm_duration: LLM's duration answer (in years)
            
        Returns:
            BondResult with verification status
        """
        # Parse LLM's duration
        llm_dur = Decimal(llm_duration.replace("years", "").replace("yrs", "").strip())
        
        # Convert to Decimal
        fv = Decimal(str(face_value))
        cr = Decimal(str(coupon_rate))
        y = Decimal(str(ytm))
        freq = Decimal(str(frequency))
        
        # Calculate duration
        n_periods = int(years_to_maturity * frequency)
        coupon_payment = (fv * cr) / freq
        periodic_rate = y / freq
        
        # Calculate price and weighted time
        weighted_time = Decimal("0")
        price = Decimal("0")
        
        for t in range(1, n_periods + 1):
            pv = coupon_payment / ((1 + periodic_rate) ** t)
            price += pv
            weighted_time += (Decimal(str(t)) / freq) * pv
        
        # Add face value
        pv_face = fv / ((1 + periodic_rate) ** n_periods)
        price += pv_face
        weighted_time += Decimal(str(years_to_maturity)) * pv_face
        
        # Macaulay duration
        computed_duration = weighted_time / price
        computed_dur_q = computed_duration.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed_dur_q - llm_dur)
        verified = diff <= Decimal("0.05")  # Within 0.05 years tolerance
        
        # Modified duration
        mod_duration = computed_duration / (1 + periodic_rate)
        mod_dur_q = mod_duration.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        return BondResult(
            verified=verified,
            llm_value=f"{llm_dur} years",
            computed_value=f"{computed_dur_q} years",
            difference=f"{diff.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)} years" if not verified else None,
            formula_used="Macaulay Duration = Σ(t × PV(CFt)) / Price",
            details={
                "price": f"${price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
                "modified_duration": f"{mod_dur_q} years"
            }
        )
    
    def verify_convexity(
        self,
        face_value: float,
        coupon_rate: float,
        ytm: float,
        years_to_maturity: float,
        llm_convexity: str,
        frequency: int = 2
    ) -> BondResult:
        """
        Verify Convexity calculation.
        
        Convexity = Σ (t(t+1) × PV(CFt)) / (Price × (1+y)²)
        
        Convexity measures curvature of price-yield relationship.
        
        Args:
            face_value: Par value of bond
            coupon_rate: Annual coupon rate
            ytm: Yield to maturity
            years_to_maturity: Years until maturity
            frequency: Coupon payments per year
            llm_convexity: LLM's convexity answer
            
        Returns:
            BondResult with verification status
        """
        try:
            return self._convexity(
                face_value, coupon_rate, ytm, years_to_maturity, llm_convexity, frequency
            )
        except UnverifiableError as reason:
            return self._unverifiable(llm_convexity, reason, self.CONVEXITY_FORMULA)
        except DecimalException:
            return self._unverifiable(
                llm_convexity, "value outside verifiable range", self.CONVEXITY_FORMULA
            )

    def _convexity(
        self,
        face_value: float,
        coupon_rate: float,
        ytm: float,
        years_to_maturity: float,
        llm_convexity: str,
        frequency: int,
    ) -> BondResult:
        """verify_convexity's computation; raises UnverifiableError on bad inputs."""
        # Parse LLM's convexity
        llm_conv = claim(
            lambda raw: Decimal(raw.replace("years²", "").strip()), llm_convexity
        )

        # Convert to Decimal. With no face value the price is zero and the
        # convexity divides by it; with no coupon period the sums are empty
        # and the convexity reads 0, which every claim used to match (#98).
        fv = number(face_value, "face_value", minimum=_ZERO, exclusive=True)
        cr = number(coupon_rate, "coupon_rate", minimum=_ZERO)
        y = number(ytm, "ytm")
        years = number(
            years_to_maturity, "years_to_maturity", minimum=_ZERO, exclusive=True
        )
        frequency = positive_int(frequency, "frequency")
        freq = Decimal(frequency)

        # Calculate convexity
        n_periods = self._coupon_periods(years, frequency, years_to_maturity)
        coupon_payment = (fv * cr) / freq
        periodic_rate = y / freq
        if 1 + periodic_rate <= 0:
            # A discount factor (1 + y/n) at or below zero divides by zero or
            # alternates in sign; there is no price to take convexity of.
            raise UnverifiableError("ytm must be > -frequency")
        
        # Calculate weighted sum and price
        weighted_sum = Decimal("0")
        price = Decimal("0")
        
        for t in range(1, n_periods + 1):
            td = Decimal(str(t))
            pv = coupon_payment / ((1 + periodic_rate) ** t)
            price += pv
            weighted_sum += td * (td + 1) * pv
        
        pv_face = fv / ((1 + periodic_rate) ** n_periods)
        price += pv_face
        nd = Decimal(str(n_periods))
        weighted_sum += nd * (nd + 1) * pv_face
        
        # Convexity in years
        computed_convexity = weighted_sum / (price * ((1 + periodic_rate) ** 2) * (freq ** 2))
        computed_conv_q = computed_convexity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        # Compare
        verified, diff_pct = within_tolerance(
            computed_convexity, llm_conv, self.tolerance_pct, Decimal("0.0001")
        )

        return BondResult(
            verified=verified,
            llm_value=f"{llm_conv}",
            computed_value=f"{computed_conv_q}",
            difference=self._difference(
                diff_pct, computed_conv_q, llm_conv, verified, Decimal("0.01"), ""
            ),
            formula_used=self.CONVEXITY_FORMULA
        )
    
    def verify_accrued_interest(
        self,
        face_value: float,
        coupon_rate: float,
        days_since_last_coupon: int,
        days_in_period: int,
        llm_accrued: str
    ) -> BondResult:
        """
        Verify Accrued Interest calculation.
        
        Accrued = (Days Since Coupon / Days in Period) × Coupon Payment
        
        Args:
            face_value: Par value
            coupon_rate: Annual coupon rate
            days_since_last_coupon: Days elapsed since last coupon
            days_in_period: Total days in coupon period
            llm_accrued: LLM's accrued interest answer
            
        Returns:
            BondResult with verification status
        """
        # Parse LLM's value
        llm_val = self._parse_money(llm_accrued)
        
        # Semi-annual coupon
        coupon = (face_value * coupon_rate) / 2
        
        # Accrued interest
        accrued = Decimal(str(days_since_last_coupon)) / Decimal(str(days_in_period)) * Decimal(str(coupon))
        computed = accrued.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Compare
        diff = abs(computed - llm_val)
        verified = diff <= Decimal("0.01")
        
        return BondResult(
            verified=verified,
            llm_value=f"${llm_val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            computed_value=f"${computed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            difference=f"${diff.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Accrued = (Days/Period) × Coupon"
        )
    
    def verify_dirty_price(
        self,
        clean_price: float,
        accrued_interest: float,
        llm_dirty: str
    ) -> BondResult:
        """
        Verify Dirty Price (Full Price) calculation.
        
        Dirty Price = Clean Price + Accrued Interest
        
        Args:
            clean_price: Quoted market price
            accrued_interest: Accrued interest
            llm_dirty: LLM's dirty price answer
            
        Returns:
            BondResult with verification status
        """
        llm_val = self._parse_money(llm_dirty)
        computed = Decimal(str(clean_price)) + Decimal(str(accrued_interest))
        computed = computed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        diff = abs(computed - llm_val)
        verified = diff <= Decimal("0.01")
        
        return BondResult(
            verified=verified,
            llm_value=f"${llm_val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            computed_value=f"${computed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}",
            difference=f"${diff.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}" if not verified else None,
            formula_used="Dirty Price = Clean Price + Accrued Interest"
        )
    
    @staticmethod
    def _coupon_periods(years: Decimal, frequency: int, raw_years: Any) -> int:
        """Whole coupon periods to maturity, from 1 to MAX_COUPON_PERIODS.

        Counted in Decimal from the validated maturity, so a finite maturity
        cannot overflow the count (``1e308 * 2`` is infinity in float). A
        float maturity carries representation error — 2/12 years is
        0.16666666666666666, and 12 periods of it 1.99...92. So when the
        count is not whole, the nearest whole count is taken only if that
        many periods, as a maturity in the input's own float type, *is* the
        input — 2/12 is two monthly periods, and np.float32(5/6) at six a
        year is five — and no neighbouring count is too, which would make
        the schedule ambiguous. A float that is a genuine fraction of a
        period, such as np.float16(8.3125) years (99.75 monthly periods),
        is truncated, not rounded up. A Decimal or int maturity is exact and
        never snapped. A maturity shorter than one period truncates to zero
        periods, which leaves nothing to price: pricing the stub of a
        partial period is #119, and until then such a bond is refused rather
        than verified against an empty sum.
        """
        periods = years * frequency
        read = _binary_float_type(raw_years)
        if read is not None:
            nearest = periods.to_integral_value(rounding=ROUND_HALF_EVEN)

            def is_input(count: Decimal) -> bool:
                # That many periods as a maturity, rounded to the input's
                # own float type, compared with the input itself.
                return count > 0 and read(float(count / frequency)) == raw_years

            if periods != nearest and is_input(nearest):
                if is_input(nearest - 1) or is_input(nearest + 1):
                    # The float cannot tell neighbouring counts apart;
                    # rounding would pick one of them.
                    raise UnverifiableError(
                        "maturity is too imprecise to count coupon periods"
                    )
                periods = nearest
        if periods > MAX_COUPON_PERIODS:
            raise UnverifiableError(
                f"maturity is longer than {MAX_COUPON_PERIODS} coupon periods"
            )
        n_periods = int(periods)
        if n_periods < 1:
            raise UnverifiableError("maturity is shorter than one coupon period")
        return n_periods

    @staticmethod
    def _unverifiable(raw_claim: Any, reason: Any, formula: str) -> BondResult:
        """A verdict for an input or claim the guard cannot verify (#98)."""
        return BondResult(
            verified=False,
            llm_value=shown(raw_claim),
            computed_value=f"UNVERIFIABLE ({reason})",
            formula_used=formula,
        )

    @staticmethod
    def _difference(
        diff_pct: Optional[Decimal],
        computed: Decimal,
        claimed: Decimal,
        verified: bool,
        quantum: Decimal,
        unit: str,
    ) -> Optional[str]:
        """How far a refused claim is from the computed value.

        A relative difference when the computed value is non-zero; the
        absolute amount, in the claim's own unit, when it is zero, where a
        percentage has no scale.
        """
        if verified:
            return None
        if diff_pct is None:
            return f"{abs(claimed - computed).quantize(quantum, rounding=ROUND_HALF_UP)}{unit}"
        return f"{diff_pct.quantize(quantum, rounding=ROUND_HALF_UP)}%"

    def _parse_rate(self, rate_str: str) -> Decimal:
        """Parse rate string to Decimal — fail-closed, no silent guessing.

        Rules:
          - "5.25%" or "5.25 %" → Decimal("0.0525")  (explicit percentage)
          - "0.0525"            → Decimal("0.0525")  (explicit decimal fraction)
          - "5.25" (no %)       → Decimal("5.25")    (no guessing; caller must include '%' for percent format)

        QWED philosophy: if format is ambiguous, do NOT guess.
        Callers must use explicit '%' suffix for percentage values.
        """
        rate_str = rate_str.strip()
        if "%" in rate_str:
            percent = Decimal(rate_str.replace("%", "").strip())
            if not percent.is_finite():
                return percent
            # Shift the exponent instead of dividing by 100: division rounds
            # to the context precision, so a long percentage claim could round
            # onto a comparison bound that its decimal-fraction spelling does
            # not reach, and the two would get different verdicts.
            sign, digits, exponent = percent.as_tuple()
            return Decimal((sign, digits, exponent - 2))
        # No % symbol: treat as decimal fraction (0.05 means 5%)
        return Decimal(rate_str)
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal"""
        import re
        cleaned = re.sub(r'[,$]', '', str(value).strip())
        return Decimal(cleaned)
