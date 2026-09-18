"""Regression tests for Sortino fail-closed branches (#43).

Empty downside observations and zero downside deviation make the ratio
undefined: no claim can verify against them. Unparseable claims must
verdict, never raise.
"""

import pytest

from qwed_finance.risk_guard import RiskGuard


def _guard() -> RiskGuard:
    return RiskGuard()


@pytest.mark.parametrize("claim", ["-999", "0", "999999", "infinite"])
def test_empty_downside_never_verifies(claim):
    result = _guard().verify_sortino_ratio(
        portfolio_return=0.02,
        target_return=0.06,
        downside_returns=[],
        llm_sortino=claim,
    )
    assert result.verified is False
    assert "UNVERIFIABLE" in result.computed_value


@pytest.mark.parametrize("claim", ["999", "11", "1000000"])
def test_zero_deviation_never_verifies(claim):
    result = _guard().verify_sortino_ratio(
        portfolio_return=0.10,
        target_return=0.06,
        downside_returns=[0.06, 0.06],
        llm_sortino=claim,
    )
    assert result.verified is False
    assert "UNVERIFIABLE" in result.computed_value


def test_unparseable_claim_verdicts_without_raising():
    result = _guard().verify_sortino_ratio(
        portfolio_return=0.02,
        target_return=0.06,
        downside_returns=[],
        llm_sortino="not-a-number!!",
    )
    assert result.verified is False


@pytest.mark.parametrize("claim", ["nan", "sNaN", "Infinity", "-Infinity"])
def test_nonfinite_claim_verdicts_without_raising(claim):
    result = _guard().verify_sortino_ratio(
        portfolio_return=0.15,
        target_return=0.06,
        downside_returns=[0.01, 0.02, -0.01],
        llm_sortino=claim,
    )
    assert result.verified is False
    assert "UNVERIFIABLE" in result.computed_value


def test_extreme_finite_claim_verdicts_without_raising():
    result = _guard().verify_sortino_ratio(
        portfolio_return=0.15,
        target_return=0.06,
        downside_returns=[0.01, 0.02, -0.01],
        llm_sortino="1e999999",
    )
    assert result.verified is False
    assert "UNVERIFIABLE" in result.computed_value


def test_matching_claim_still_verifies():
    result = _guard().verify_sortino_ratio(
        portfolio_return=0.15,
        target_return=0.06,
        downside_returns=[0.01, 0.02, -0.01],
        llm_sortino="1.6432",
    )
    assert result.verified is True
