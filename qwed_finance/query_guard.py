"""
Query Guard - SQL safety verification using AST analysis
Ensures LLM-generated SQL queries are read-only and access only allowed tables
"""

from dataclasses import dataclass
from typing import List, Optional, Set
from enum import Enum


class QueryRisk(Enum):
    """Risk levels for SQL queries"""
    SAFE = "safe"           # SELECT only, allowed tables
    MEDIUM = "medium"       # SELECT with subqueries or joins
    HIGH = "high"           # Mutation detected (UPDATE/DELETE)
    CRITICAL = "critical"   # DROP/TRUNCATE detected


@dataclass
class QueryResult:
    """Result of a SQL query verification"""
    safe: bool
    risk_level: QueryRisk
    query_type: str
    tables_accessed: List[str]
    violations: List[str]
    sanitized_query: Optional[str] = None


class QueryGuard:
    """
    Deterministic SQL safety verification using AST analysis.
    Prevents LLM-generated queries from mutating data or accessing restricted tables.
    """
    
    def __init__(self, allowed_tables: Optional[Set[str]] = None):
        """
        Initialize the Query Guard.
        
        Args:
            allowed_tables: Set of table names the AI is allowed to query.
                           If None, all tables are allowed (only mutation check).
        """
        self.allowed_tables = allowed_tables
        self._sqlglot_available = self._check_sqlglot()
        
        # Dangerous SQL keywords that indicate mutations
        self.mutation_keywords = {
            "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
            "ALTER", "CREATE", "REPLACE", "MERGE", "UPSERT"
        }
        
        # Keywords that require extra scrutiny
        self.warning_keywords = {
            "GRANT", "REVOKE", "EXECUTE", "CALL", "EXEC"
        }
    
    def _check_sqlglot(self) -> bool:
        """Check if SQLGlot is available"""
        try:
            import sqlglot
            return True
        except ImportError:
            return False
    
    # ==================== Read-Only Safety ====================
    
    def verify_readonly_safety(self, sql_query: str) -> QueryResult:
        """
        Verify that a SQL query is read-only (no mutations).
        
        Args:
            sql_query: The SQL query to validate
            
        Returns:
            QueryResult with safety status
        """
        violations = []
        query_type = "UNKNOWN"
        tables = []
        
        # Normalize query
        sql_upper = sql_query.upper().strip()
        
        # Quick check for mutation keywords
        for keyword in self.mutation_keywords:
            if keyword in sql_upper.split():
                violations.append(f"Mutation detected: {keyword} statement")
        
        for keyword in self.warning_keywords:
            if keyword in sql_upper.split():
                violations.append(f"Dangerous operation: {keyword}")
        
        # Use SQLGlot for proper AST analysis if available
        if self._sqlglot_available:
            ast_result = self._analyze_with_sqlglot(sql_query)
            query_type = ast_result["query_type"]
            tables = ast_result["tables"]
            violations.extend(ast_result["violations"])
        else:
            # Fallback: basic parsing
            query_type = self._detect_query_type(sql_upper)
            tables = self._extract_tables_basic(sql_query)
        
        # Determine risk level
        if any("DROP" in v or "TRUNCATE" in v for v in violations):
            risk = QueryRisk.CRITICAL
        elif len(violations) > 0:
            risk = QueryRisk.HIGH
        elif "JOIN" in sql_upper or "SUBQUERY" in query_type:
            risk = QueryRisk.MEDIUM
        else:
            risk = QueryRisk.SAFE
        
        return QueryResult(
            safe=len(violations) == 0,
            risk_level=risk,
            query_type=query_type,
            tables_accessed=tables,
            violations=violations
        )
    
    def _analyze_with_sqlglot(self, sql_query: str) -> dict:
        """Use SQLGlot for AST-based analysis"""
        import sqlglot
        from sqlglot import exp
        
        result = {
            "query_type": "UNKNOWN",
            "tables": [],
            "violations": []
        }
        
        try:
            parsed = sqlglot.parse_one(sql_query)
            
            # Determine query type from AST
            if isinstance(parsed, exp.Select):
                result["query_type"] = "SELECT"
            elif isinstance(parsed, exp.Insert):
                result["query_type"] = "INSERT"
                result["violations"].append("Mutation detected: INSERT statement")
            elif isinstance(parsed, exp.Update):
                result["query_type"] = "UPDATE"
                result["violations"].append("Mutation detected: UPDATE statement")
            elif isinstance(parsed, exp.Delete):
                result["query_type"] = "DELETE"
                result["violations"].append("Mutation detected: DELETE statement")
            elif isinstance(parsed, exp.Drop):
                result["query_type"] = "DROP"
                result["violations"].append("CRITICAL: DROP statement detected!")
            elif isinstance(parsed, exp.Create):
                result["query_type"] = "CREATE"
                result["violations"].append("DDL detected: CREATE statement")
            
            # Extract table names
            for table in parsed.find_all(exp.Table):
                result["tables"].append(table.name)
            
        except Exception as e:
            result["violations"].append(f"SQL parse error: {str(e)}")
        
        return result
    
    def _detect_query_type(self, sql_upper: str) -> str:
        """Fallback query type detection"""
        if sql_upper.startswith("SELECT"):
            return "SELECT"
        elif sql_upper.startswith("INSERT"):
            return "INSERT"
        elif sql_upper.startswith("UPDATE"):
            return "UPDATE"
        elif sql_upper.startswith("DELETE"):
            return "DELETE"
        elif sql_upper.startswith("DROP"):
            return "DROP"
        elif sql_upper.startswith("CREATE"):
            return "CREATE"
        return "UNKNOWN"
    
    def _extract_tables_basic(self, sql_query: str) -> List[str]:
        """Basic table extraction without SQLGlot"""
        import re
        
        # Find tables after FROM and JOIN
        pattern = r'(?:FROM|JOIN)\s+([`"\']?[\w\.]+[`"\']?)'
        matches = re.findall(pattern, sql_query, re.IGNORECASE)
        
        # Clean up quotes
        tables = [m.strip('`"\'') for m in matches]
        return list(set(tables))
    
    # ==================== Table Access Control ====================
    
    def verify_table_access(
        self,
        sql_query: str,
        allowed_tables: Optional[Set[str]] = None
    ) -> QueryResult:
        """
        Verify that a SQL query only accesses allowed tables.
        
        Args:
            sql_query: The SQL query to validate
            allowed_tables: Set of allowed table names (overrides instance default)
            
        Returns:
            QueryResult with access verification
        """
        allowed = allowed_tables or self.allowed_tables
        
        # First check read-only safety
        result = self.verify_readonly_safety(sql_query)
        
        # If no table restrictions, return the readonly result
        if allowed is None:
            return result
        
        # Check table access
        violations = list(result.violations)  # Copy existing violations
        
        for table in result.tables_accessed:
            table_lower = table.lower()
            if table_lower not in {t.lower() for t in allowed}:
                violations.append(f"Unauthorized table access: {table}")
        
        # Update risk level if table violations found
        risk = result.risk_level
        if any("Unauthorized" in v for v in violations):
            risk = QueryRisk.HIGH if risk == QueryRisk.SAFE else risk
        
        return QueryResult(
            safe=len(violations) == 0,
            risk_level=risk,
            query_type=result.query_type,
            tables_accessed=result.tables_accessed,
            violations=violations
        )
    
    # ==================== Column Access Control ====================
    
    def verify_column_access(
        self,
        sql_query: str,
        restricted_columns: Set[str]
    ) -> QueryResult:
        """
        Verify that a SQL query doesn't access restricted columns (PII).
        
        Args:
            sql_query: The SQL query to validate
            restricted_columns: Set of column names that are restricted
            
        Returns:
            QueryResult with column access verification
        """
        result = self.verify_readonly_safety(sql_query)
        violations = list(result.violations)
        
        # Extract columns from query
        columns = self._extract_columns(sql_query)
        
        for col in columns:
            col_lower = col.lower()
            if col_lower in {c.lower() for c in restricted_columns}:
                violations.append(f"Restricted column access: {col}")
        
        risk = result.risk_level
        if any("Restricted column" in v for v in violations):
            risk = QueryRisk.HIGH
        
        return QueryResult(
            safe=len(violations) == 0,
            risk_level=risk,
            query_type=result.query_type,
            tables_accessed=result.tables_accessed,
            violations=violations
        )
    
    def _extract_columns(self, sql_query: str) -> List[str]:
        """Extract column names from SQL query"""
        if self._sqlglot_available:
            import sqlglot
            from sqlglot import exp
            
            columns = []
            try:
                parsed = sqlglot.parse_one(sql_query)
                for col in parsed.find_all(exp.Column):
                    columns.append(col.name)
            except:
                pass
            return columns
        else:
            # Fallback: basic SELECT column extraction
            import re
            match = re.search(r'SELECT\s+(.+?)\s+FROM', sql_query, re.IGNORECASE)
            if match:
                cols = match.group(1).split(',')
                return [c.strip().split('.')[-1] for c in cols if c.strip() != '*']
            return []
    
    # ==================== SQL Injection Prevention ====================
    
    def verify_no_injection(
        self,
        sql_query: str,
        user_input: str
    ) -> QueryResult:
        """
        Verify that user input doesn't introduce SQL injection.
        
        Args:
            sql_query: The full SQL query
            user_input: The user-provided input that's in the query
            
        Returns:
            QueryResult with injection check
        """
        violations = []
        
        # Check for common injection patterns in user input
        injection_patterns = [
            r"'.*--",                    # Comment after quote
            r"'.*;\s*(DROP|DELETE|UPDATE|INSERT)",  # Chained statements
            r"'.*OR\s+'1'\s*=\s*'1",    # OR 1=1
            r"UNION\s+SELECT",           # UNION injection
            r";\s*DROP\s+TABLE",         # DROP TABLE injection
        ]
        
        import re
        for pattern in injection_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                violations.append(f"SQL injection pattern detected in user input")
                break
        
        # Check for multiple statements (statement stacking)
        if ";" in user_input and len(user_input.split(";")) > 1:
            violations.append("Multiple statements in user input (possible injection)")
        
        result = self.verify_readonly_safety(sql_query)
        violations.extend(result.violations)
        
        risk = QueryRisk.CRITICAL if len(violations) > 0 else result.risk_level
        
        return QueryResult(
            safe=len(violations) == 0,
            risk_level=risk,
            query_type=result.query_type,
            tables_accessed=result.tables_accessed,
            violations=violations
        )
    
    # ==================== Query Sanitization ====================
    
    def sanitize_query(self, sql_query: str) -> QueryResult:
        """
        Attempt to sanitize a query by removing dangerous elements.
        
        Args:
            sql_query: The SQL query to sanitize
            
        Returns:
            QueryResult with sanitized query if possible
        """
        result = self.verify_readonly_safety(sql_query)
        
        if result.safe:
            return QueryResult(
                safe=True,
                risk_level=result.risk_level,
                query_type=result.query_type,
                tables_accessed=result.tables_accessed,
                violations=[],
                sanitized_query=sql_query  # No changes needed
            )
        
        # If unsafe, try to extract just the SELECT part
        if self._sqlglot_available and result.query_type == "SELECT":
            import sqlglot
            try:
                # Re-transpile to normalized form
                sanitized = sqlglot.transpile(sql_query, pretty=True)[0]
                return QueryResult(
                    safe=True,
                    risk_level=QueryRisk.SAFE,
                    query_type="SELECT",
                    tables_accessed=result.tables_accessed,
                    violations=[],
                    sanitized_query=sanitized
                )
            except:
                pass
        
        # Cannot sanitize
        return QueryResult(
            safe=False,
            risk_level=result.risk_level,
            query_type=result.query_type,
            tables_accessed=result.tables_accessed,
            violations=result.violations + ["Could not sanitize query"],
            sanitized_query=None
        )
