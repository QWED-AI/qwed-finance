"""QueryGuard reports a top-level mutation once.

The keyword scan and the SQLGlot AST both found a top-level DELETE, INSERT or
UPDATE and both wrote "Mutation detected: <KIND> statement", so the violation
appeared twice (found while checking the finance docs). Only matches against
the keyword scan are dropped: separate AST findings, such as two mutating
subqueries, all stay, and the verdict and risk level do not change.
"""

import pytest

from qwed_finance import CrossGuard, QueryGuard
from qwed_finance.query_guard import QueryRisk


@pytest.mark.parametrize(
    "sql, violation",
    [
        ("DELETE FROM users WHERE id=1", "Mutation detected: DELETE statement"),
        ("INSERT INTO transactions VALUES (1)", "Mutation detected: INSERT statement"),
        ("UPDATE accounts SET balance = 0", "Mutation detected: UPDATE statement"),
    ],
)
def test_top_level_mutation_is_reported_once(sql, violation):
    result = QueryGuard().verify_readonly_safety(sql)
    assert result.safe is False
    assert result.risk_level == QueryRisk.HIGH
    assert result.violations == [violation]


def test_drop_keeps_both_distinct_messages_and_stays_critical():
    result = QueryGuard().verify_readonly_safety("DROP TABLE users")
    assert result.safe is False
    assert result.risk_level == QueryRisk.CRITICAL
    assert result.violations == [
        "Mutation detected: DROP statement",
        "CRITICAL: DROP statement detected!",
    ]


def test_separate_mutating_subqueries_are_all_kept():
    sql = (
        "WITH a AS (DELETE FROM t RETURNING *), "
        "b AS (DELETE FROM u RETURNING *) SELECT * FROM a"
    )
    result = QueryGuard().verify_readonly_safety(sql)
    assert result.safe is False
    assert result.violations.count("Mutation detected in subquery: delete statement") == 2


def test_cross_guard_pii_path_reports_once():
    result = CrossGuard().verify_query_with_pii_protection(
        "DELETE FROM users", allowed_tables={"users"}, pii_columns={"ssn"}
    )
    assert result.violations.count("Mutation detected: DELETE statement") == 1


def test_read_only_query_still_passes():
    result = QueryGuard().verify_readonly_safety("SELECT id FROM accounts")
    assert result.safe is True
    assert result.violations == []
