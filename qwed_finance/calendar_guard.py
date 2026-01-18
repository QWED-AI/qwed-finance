"""
Calendar Guard - Deterministic day count conventions for interest accrual
Handles 30/360, Actual/360, Actual/365, Actual/Actual conventions
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Tuple
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


class DayCountConvention(Enum):
    """Standard day count conventions used in finance"""
    ACTUAL_360 = "Actual/360"      # T-Bills, Commercial Paper
    ACTUAL_365 = "Actual/365"      # UK gilts, some bonds
    ACTUAL_ACTUAL = "Actual/Actual" # US Treasury bonds
    THIRTY_360 = "30/360"          # Corporate bonds, mortgages (US)
    THIRTY_360_EU = "30E/360"      # Eurobonds


@dataclass
class CalendarResult:
    """Result of a calendar/day count verification"""
    verified: bool
    llm_days: Optional[int]
    computed_days: int
    convention_used: str
    day_count_fraction: Optional[str] = None
    interest_amount: Optional[str] = None
    proof: Optional[str] = None


class CalendarGuard:
    """
    Deterministic day count verification for interest calculations.
    Prevents LLM hallucinations in date-based financial calculations.
    """
    
    def __init__(self, holiday_calendar: Optional[List[date]] = None):
        """
        Initialize the Calendar Guard.
        
        Args:
            holiday_calendar: List of holiday dates to exclude from business days
        """
        self.holidays = set(holiday_calendar or [])
        
        # Default US federal holidays (approximate - should be fetched from calendar library)
        self.default_us_holidays = self._generate_us_holidays(2024, 2030)
    
    def _generate_us_holidays(self, start_year: int, end_year: int) -> set:
        """Generate approximate US federal holiday dates"""
        holidays = set()
        for year in range(start_year, end_year + 1):
            # Fixed holidays (approximate)
            holidays.add(date(year, 1, 1))    # New Year's Day
            holidays.add(date(year, 7, 4))    # Independence Day
            holidays.add(date(year, 12, 25))  # Christmas
            # Note: In production, use `holidays` library for accurate dates
        return holidays
    
    # ==================== Day Count Calculations ====================
    
    def verify_day_count(
        self,
        start_date: date,
        end_date: date,
        llm_days: int,
        convention: DayCountConvention = DayCountConvention.ACTUAL_360
    ) -> CalendarResult:
        """
        Verify LLM's day count calculation against the specified convention.
        
        Args:
            start_date: Start date of accrual period
            end_date: End date of accrual period
            llm_days: Number of days claimed by LLM
            convention: Day count convention to use
            
        Returns:
            CalendarResult with verification status
        """
        computed_days = self._calculate_days(start_date, end_date, convention)
        
        return CalendarResult(
            verified=(llm_days == computed_days),
            llm_days=llm_days,
            computed_days=computed_days,
            convention_used=convention.value,
            proof=f"{convention.value}: {start_date} to {end_date} = {computed_days} days"
        )
    
    def _calculate_days(
        self,
        start: date,
        end: date,
        convention: DayCountConvention
    ) -> int:
        """Calculate number of days based on convention"""
        
        if convention == DayCountConvention.ACTUAL_360:
            return (end - start).days
            
        elif convention == DayCountConvention.ACTUAL_365:
            return (end - start).days
            
        elif convention == DayCountConvention.ACTUAL_ACTUAL:
            return (end - start).days
            
        elif convention == DayCountConvention.THIRTY_360:
            return self._thirty_360_days(start, end, european=False)
            
        elif convention == DayCountConvention.THIRTY_360_EU:
            return self._thirty_360_days(start, end, european=True)
        
        return (end - start).days
    
    def _thirty_360_days(self, start: date, end: date, european: bool = False) -> int:
        """
        Calculate days using 30/360 convention.
        
        US 30/360:
        - If start day is 31, change to 30
        - If end day is 31 AND start day is 30 or 31, change end to 30
        
        European 30E/360:
        - If either day is 31, change to 30
        """
        d1 = start.day
        m1 = start.month
        y1 = start.year
        
        d2 = end.day
        m2 = end.month
        y2 = end.year
        
        if european:
            # 30E/360 (Eurobond)
            if d1 == 31:
                d1 = 30
            if d2 == 31:
                d2 = 30
        else:
            # US 30/360
            if d1 == 31:
                d1 = 30
            if d2 == 31 and d1 >= 30:
                d2 = 30
        
        return 360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1)
    
    # ==================== Day Count Fraction ====================
    
    def verify_day_count_fraction(
        self,
        start_date: date,
        end_date: date,
        llm_fraction: float,
        convention: DayCountConvention = DayCountConvention.ACTUAL_360,
        tolerance: float = 0.0001
    ) -> CalendarResult:
        """
        Verify the day count fraction used for interest accrual.
        
        Args:
            start_date: Start of accrual period
            end_date: End of accrual period
            llm_fraction: Fraction claimed by LLM (e.g., 0.5 for 6 months)
            convention: Day count convention
            tolerance: Acceptable difference
            
        Returns:
            CalendarResult
        """
        days = self._calculate_days(start_date, end_date, convention)
        
        # Calculate denominator based on convention
        if convention in [DayCountConvention.ACTUAL_360, DayCountConvention.THIRTY_360]:
            denominator = 360
        elif convention == DayCountConvention.ACTUAL_365:
            denominator = 365
        else:  # ACTUAL_ACTUAL
            # Check if leap year
            year = start_date.year
            is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            denominator = 366 if is_leap else 365
        
        computed_fraction = days / denominator
        difference = abs(llm_fraction - computed_fraction)
        
        return CalendarResult(
            verified=(difference <= tolerance),
            llm_days=int(llm_fraction * denominator),
            computed_days=days,
            convention_used=convention.value,
            day_count_fraction=f"{days}/{denominator} = {computed_fraction:.6f}",
            proof=f"Computed: {computed_fraction:.6f}, LLM: {llm_fraction:.6f}, Diff: {difference:.6f}"
        )
    
    # ==================== Interest Accrual ====================
    
    def verify_accrued_interest(
        self,
        principal: float,
        annual_rate: float,
        start_date: date,
        end_date: date,
        llm_interest: str,
        convention: DayCountConvention = DayCountConvention.THIRTY_360
    ) -> CalendarResult:
        """
        Verify accrued interest calculation.
        
        Interest = Principal × Rate × DayCountFraction
        
        Args:
            principal: Face value / principal amount
            annual_rate: Annual coupon/interest rate (e.g., 0.05 for 5%)
            start_date: Start of accrual period
            end_date: End of accrual period
            llm_interest: LLM's calculated interest
            convention: Day count convention
            
        Returns:
            CalendarResult with interest verification
        """
        days = self._calculate_days(start_date, end_date, convention)
        
        # Get denominator
        if convention in [DayCountConvention.ACTUAL_360, DayCountConvention.THIRTY_360, 
                         DayCountConvention.THIRTY_360_EU]:
            denominator = 360
        elif convention == DayCountConvention.ACTUAL_365:
            denominator = 365
        else:
            denominator = 365  # Simplified for ACTUAL_ACTUAL
        
        # Calculate interest
        fraction = Decimal(str(days)) / Decimal(str(denominator))
        computed_interest = Decimal(str(principal)) * Decimal(str(annual_rate)) * fraction
        computed_interest = computed_interest.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Parse LLM interest
        import re
        llm_clean = re.sub(r'[$,\s]', '', llm_interest)
        llm_decimal = Decimal(llm_clean)
        
        difference = abs(llm_decimal - computed_interest)
        tolerance = Decimal('0.01')  # 1 cent tolerance
        
        return CalendarResult(
            verified=(difference <= tolerance),
            llm_days=days,
            computed_days=days,
            convention_used=convention.value,
            day_count_fraction=f"{days}/{denominator}",
            interest_amount=f"${computed_interest}",
            proof=f"Interest = ${principal} × {annual_rate} × ({days}/{denominator}) = ${computed_interest}"
        )
    
    # ==================== Business Day Verification ====================
    
    def verify_business_day(
        self,
        proposed_date: date,
        llm_says_business_day: bool,
        use_us_holidays: bool = True
    ) -> CalendarResult:
        """
        Verify if a date is a valid business day.
        
        Args:
            proposed_date: Date to check
            llm_says_business_day: LLM's claim (True = business day)
            use_us_holidays: Include US federal holidays
            
        Returns:
            CalendarResult
        """
        holidays = self.holidays
        if use_us_holidays:
            holidays = holidays.union(self.default_us_holidays)
        
        # Check if weekend
        is_weekend = proposed_date.weekday() >= 5  # Saturday=5, Sunday=6
        
        # Check if holiday
        is_holiday = proposed_date in holidays
        
        is_business_day = not (is_weekend or is_holiday)
        
        verified = (llm_says_business_day == is_business_day)
        
        reason = []
        if is_weekend:
            reason.append("weekend")
        if is_holiday:
            reason.append("holiday")
        
        return CalendarResult(
            verified=verified,
            llm_days=1 if llm_says_business_day else 0,
            computed_days=1 if is_business_day else 0,
            convention_used="Business Day",
            proof=f"{proposed_date} is {'NOT ' if not is_business_day else ''}a business day" +
                  (f" ({', '.join(reason)})" if reason else "")
        )
    
    def get_next_business_day(
        self,
        from_date: date,
        use_us_holidays: bool = True
    ) -> date:
        """
        Get the next valid business day.
        
        Args:
            from_date: Starting date
            use_us_holidays: Include US federal holidays
            
        Returns:
            Next business day
        """
        holidays = self.holidays
        if use_us_holidays:
            holidays = holidays.union(self.default_us_holidays)
        
        current = from_date
        while True:
            is_weekend = current.weekday() >= 5
            is_holiday = current in holidays
            
            if not is_weekend and not is_holiday:
                return current
            
            current += timedelta(days=1)
