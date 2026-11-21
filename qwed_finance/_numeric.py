"""Shared checks for numeric inputs and claims in the risk and bond guards.

A guard verifies a claim only by recomputing it, so an input the formula
cannot evaluate, a claim that cannot be read, or a computed value the
comparison cannot scale against must never verify (#98). These helpers
turn each of those into an ``UnverifiableError`` reason, which the guard
returns as ``verified=False`` instead of raising.
"""

from decimal import Decimal, DecimalException
from typing import Any, Callable, Optional, Tuple


class UnverifiableError(ValueError):
    """An input or claim that cannot be verified; the message is the reason."""


def number(
    value: Any,
    name: str,
    *,
    minimum: Optional[Decimal] = None,
    exclusive: bool = False,
) -> Decimal:
    """Read a numeric input as Decimal, refusing what the formula cannot use.

    bool is refused although it is an int subclass (``True`` would read as
    1), and so are NaN and Infinity, which compare false against every bound
    or poison the arithmetic. With ``minimum``, the value must be at least
    it, or strictly above it when ``exclusive``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise UnverifiableError(f"{name} must be a number")
    try:
        result = Decimal(str(value))
    except (DecimalException, ValueError):
        # str() of an int past the digit limit raises ValueError.
        raise UnverifiableError(f"{name} must be a number") from None
    if not result.is_finite():
        raise UnverifiableError(f"{name} must be finite")
    if minimum is not None:
        if exclusive and result <= minimum:
            raise UnverifiableError(f"{name} must be > {minimum}")
        if not exclusive and result < minimum:
            raise UnverifiableError(f"{name} must be >= {minimum}")
    return result


def claim(parse: Callable[[str], Decimal], raw: Any) -> Decimal:
    """Parse a claimed value with ``parse``, refusing unreadable or non-finite text.

    Decimal accepts "NaN" and "Infinity" at parse time; either would crash
    the comparison or the formatting later instead of producing a verdict.
    """
    if not isinstance(raw, str):
        raise UnverifiableError("unparseable claim")
    try:
        value = parse(raw)
    except (DecimalException, ValueError, TypeError):
        raise UnverifiableError("unparseable claim") from None
    if not value.is_finite():
        raise UnverifiableError("non-finite claim")
    return value


def within_tolerance(
    computed: Decimal,
    claimed: Decimal,
    tolerance_pct: Decimal,
    quantum: Decimal,
) -> Tuple[bool, Optional[Decimal]]:
    """Compare a claim with the computed value.

    A non-zero computed value is compared relatively, scaled by its absolute
    value so a negative result compares correctly. A computed value of
    exactly zero has no scale: a relative difference would divide by zero,
    and the old code skipped the comparison, which verified any claim
    (#98). Zero is compared absolutely instead — the claim verifies only if
    it rounds to zero at ``quantum``, the precision the result is reported
    in.

    Returns ``(verified, difference_pct)``; ``difference_pct`` is None for
    the absolute comparison. A claim too large to compare raises
    ``UnverifiableError``.
    """
    try:
        if computed == 0:
            return abs(claimed) < quantum / 2, None
        difference_pct = abs(computed - claimed) / abs(computed) * 100
        return difference_pct <= tolerance_pct, difference_pct
    except DecimalException:
        raise UnverifiableError("claim outside verifiable range") from None


def positive_int(value: Any, name: str) -> int:
    """Read a count that must be a whole number above zero (bool refused)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise UnverifiableError(f"{name} must be a positive integer")
    return value


# Longest refused claim echoed back in a result.
MAX_SHOWN_CLAIM = 80


def shown(raw: Any) -> str:
    """A refused claim as it may be echoed back in a result: one line, short.

    A refused claim is untrusted text, and callers print results — the
    GitHub Action writes them to its log, where a line starting with ``::``
    is a workflow command. repr() escapes every line break and other
    non-printable character, so the echo is always a single line; it is
    then cut to MAX_SHOWN_CLAIM characters.
    """
    text = repr(raw)
    if len(text) > MAX_SHOWN_CLAIM:
        text = text[: MAX_SHOWN_CLAIM - 3] + "..."
    return text
