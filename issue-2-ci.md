## CI: Test matrix, linting, security scanning, and CodeQL config

**Labels:** `enhancement`, `ci`, `good first issue`

### The problem

Right now the CI runs tests on a single Python version (3.11), no linting, no dependency security scan, and the CodeQL config is the generic GitHub template.

Other QWED repos (qwed-ucp, qwed-verification) have a 3.10/3.11/3.12 test matrix, ruff linting in CI, pip-audit for dependency vulnerabilities, and a codeql-config.yml that excludes examples/ from false-positive alerts. qwed-finance should be consistent.

Specifically:

**tests.yml — single Python version**
Only `python-version: '3.11'`. The pyproject.toml says `requires-python = ">=3.10"` but we never test on 3.10 or 3.12. A matrix with all three would catch version-specific issues before they hit users.

**No lint job**
ruff and black are in `[dev]` dependencies but never run in CI. A separate lint job would catch formatting and import issues before PR review.

**No dependency security scan**
qwed-ucp runs `pip-audit` in CI to check for vulnerable packages. qwed-finance has sympy, mpmath, z3-solver, sqlglot, jsonschema as dependencies — any of these could have CVEs. No scan running.

**CodeQL — no config file**
The current codeql.yml is the default GitHub template without any customization. No queries (no `security-extended,security-and-quality`), no `paths-ignore`, no config file. This means CodeQL might miss things or flag false positives in tests/examples with no way to suppress them.

**SonarCloud installs pytest wrong**
`sonar.yml` runs `pip install pytest==8.* pytest-cov==5.*` and then `pip install -e .` separately. This bypasses the `[dev]` extras pattern used everywhere else. Should just use `pip install -e ".[dev]"` like tests.yml does.

### What to do

1. Change `tests.yml` to a matrix with `3.10`, `3.11`, `3.12`
2. Add a `lint` job to `tests.yml` that runs `ruff check` and `ruff format --check`
3. Add a `security-scan` job that runs `pip-audit`
4. Create `.github/codeql/codeql-config.yml` with paths-ignore for examples/
5. Update `codeql.yml` to reference the config and add `queries: security-extended,security-and-quality`
6. Fix `sonar.yml` to use `pip install -e ".[dev]"` instead of the two-step install

### Files to touch

- `.github/workflows/tests.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/sonar.yml`
- `.github/codeql/codeql-config.yml` (new)

### Acceptance criteria

- CI runs tests on 3.10, 3.11, 3.12
- CI has a lint job that fails on ruff violations
- CI has a pip-audit job that fails on vulnerable deps
- CodeQL has a config file excluding examples/
- SonarCloud uses `.[dev]` pattern for install
