"""Regression tests for GHSA-q8r4-6gpp-5fx2.

MySQL executes the body of /*! ... */ comments (MariaDB also /*M! ... */),
while the SQL parser drops them as ordinary comments. Tables and columns
inside such a comment were invisible to the allow-list and PII checks.
"""

import pytest

from qwed_finance.cross_guard import CrossGuard
from qwed_finance.query_guard import QueryGuard, QueryRisk

EXECUTABLE_COMMENT_QUERIES = [
    "SELECT a FROM t1 /*!50000 , t2 */",
    "SELECT a FROM t1 /*! , t2 */",
    "SELECT a /*!50000 , ssn */ FROM t1",
    "SELECT a FROM t1 /*M!100000 , t2 */",
    "SELECT a FROM t1 /*m! , t2 */",
    "/*!SELECT ssn FROM t2*/ SELECT a FROM t1",
]


@pytest.mark.parametrize("sql", EXECUTABLE_COMMENT_QUERIES)
def test_readonly_check_rejects_executable_comments(sql):
    result = QueryGuard().verify_readonly_safety(sql)
    assert result.safe is False
    assert result.risk_level == QueryRisk.HIGH
    assert any("Executable comment" in v for v in result.violations)


def test_table_allow_list_cannot_be_bypassed():
    result = QueryGuard().verify_table_access(
        "SELECT a FROM t1 /*!50000 , t2 */", {"t1"}
    )
    assert result.safe is False


def test_pii_protection_cannot_be_bypassed():
    result = CrossGuard().verify_query_with_pii_protection(
        "SELECT a /*!50000 , ssn */ FROM t1", ["t1"], ["ssn"]
    )
    assert result.passed is False


def test_column_check_cannot_be_bypassed():
    result = QueryGuard().verify_column_access(
        "SELECT a /*!50000 , ssn */ FROM t1", {"ssn"}
    )
    assert result.safe is False


@pytest.mark.parametrize("sql", EXECUTABLE_COMMENT_QUERIES)
def test_sanitize_refuses_executable_comments(sql):
    result = QueryGuard().sanitize_query(sql)
    assert result.safe is False
    assert result.sanitized_query is None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t1 /* plain comment */",
        "SELECT a FROM t1 -- trailing comment",
        "SELECT /*+ MAX_EXECUTION_TIME(1000) */ a FROM t1",
        "SELECT a FROM t1 WHERE note = 'ok'",
    ],
)
def test_ordinary_comments_and_hints_still_pass(sql):
    result = QueryGuard().verify_table_access(sql, {"t1"})
    assert result.safe is True
