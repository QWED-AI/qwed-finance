"""Shared checks for numeric inputs and claims in the risk and bond guards.

A guard verifies a claim only by recomputing it, so an input the formula
cannot evaluate, a claim that cannot be read, or a computed value the
comparison cannot scale against must never verify (#98). These helpers
turn each of those into an ``UnverifiableError`` reason, which the guard
returns as ``verified=False`` instead of raising.
"""

import numbers
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

    Any real number type is accepted — int, float, Decimal, and types
    registered as ``numbers.Real`` such as NumPy's ``int64`` and ``float32``,
    which main read through ``str()`` too. bool is refused although it is an
    int subclass (``True`` would read as 1); NumPy's ``bool_`` is not a real
    number and is refused with everything else, and a non-integral rational
    such as ``Fraction`` is refused rather than rounded. NaN and Infinity are
    refused because they compare false against every bound or poison the
    arithmetic. With ``minimum``, the value must be at least it, or strictly
    above it when ``exclusive``.
    """
    if isinstance(value, bool) or not isinstance(value, (numbers.Real, Decimal)):
        raise UnverifiableError(f"{name} must be a number")
    if isinstance(value, numbers.Rational) and not isinstance(value, numbers.Integral):
        # A Fraction is a real number, but its str() ("3/2") is not a
        # Decimal, and converting it by division would round: 1/12 years
        # read to 50 digits counts no monthly period.
        raise UnverifiableError(
            f"{name} must be an int, float or Decimal, not {type(value).__name__}"
        )
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
            return claimed.copy_abs() < quantum / 2, None
        difference_pct = abs(computed - claimed) / abs(computed) * 100
        return difference_pct <= tolerance_pct, difference_pct
    except DecimalException:
        raise UnverifiableError("value outside verifiable range") from None


def positive_int(value: Any, name: str) -> int:
    """Read a count that must be a whole number above zero.

    Any integral type is accepted (int, NumPy's ``int64``); bool is refused,
    and so is a float, even an integral one such as ``2.0``.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < 1:
        raise UnverifiableError(f"{name} must be a positive integer")
    return int(value)


# Longest refused claim echoed back in a result.
MAX_SHOWN_CLAIM = 80


def shown(raw: Any) -> str:
    """A refused claim as it may be echoed back in a result: one line, short.

    A refused claim is untrusted text, and callers print results — the
    GitHub Action writes them to its log, where a line starting with ``::``
    is a workflow command. A string is rendered with ``str.__repr__``, which
    escapes every line break and other non-printable character, so the echo
    is always a single line, and which a str subclass cannot override. Any
    other value is a fixed placeholder: its repr is caller code that may
    raise, inject a line break (through ``__repr__`` or a class name) or be
    unrepresentable (an int past the digit limit). The text is then cut to
    MAX_SHOWN_CLAIM characters.
    """
    if not isinstance(raw, str):
        return "<non-string claim>"
    text = str.__repr__(raw)
    if len(text) > MAX_SHOWN_CLAIM:
        text = text[: MAX_SHOWN_CLAIM - 3] + "..."
    return text
