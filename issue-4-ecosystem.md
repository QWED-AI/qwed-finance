## QWED Ecosystem alignment: `.qwed.yml`, GitHub topics, uv.lock

**Labels:** `enhancement`, `devx`, `integration`

### The problem

qwed-finance is part of the QWED ecosystem but doesn't use any of the ecosystem infrastructure that other repos have. There's no `.qwed.yml` policy file, no GitHub topics set, no QWED Security check in the CI pipeline, and no lockfile for dependencies.

**No `.qwed.yml`**
qwed-verification has a `.qwed.yml` that configures policy for the QWED Security GitHub App scanner. Without one, QWED Security uses default rules, which may not match the intended policy for this repo. For example, we might want `treat_unknown_as_block: true` for a finance repo because silent failures in financial calculations are costly.

**No GitHub topics**
qwed-ucp has 15 topics (e.g., express-middleware, attestation). qwed-finance has none. This makes the repo harder to discover and doesn't signal to users what ecosystem tools it integrates with. Relevant topics: security, finance, banking, verification, fail-closed, sympy, z3, mitigation-framework.

**No QWED Security CI check**
Other QWED repos have QWED Security running as a check on every PR. qwed-finance doesn't. We should add the QWED Security check to the CI pipeline. Once the GitHub App is installed and a `.qwed.yml` is present, each PR will be automatically analyzed.

**No `uv.lock`**
qwed-ucp has a `uv.lock` file that pins all transitive dependencies with hashes. This ensures every install produces the same dependency tree. qwed-finance uses pip with only pyproject.toml which allows different minor/patch versions at install time. This can lead to "it works on my machine" issues and unexpected behavior from dependency updates.

### What to do

1. Create a `.qwed.yml` at repo root with sensible defaults for a finance repo:
   - `treat_unknown_as_block: true` (fail-closed for unrecognized files)
   - Let QWED Security resolve the actual policy keys
2. Add GitHub topics from the repo Settings page (not in code):
   - `security`, `finance`, `banking`, `verification`, `fail-closed`
   - `sympy`, `z3`, `data-validation`, `safety`
   - `middleware`, `safety,`, `artificial-intelligence`
3. Install the QWED Security GitHub App on the repo and set up required check
4. Run `uv lock` (or `uv sync --frozen --group dev`) to generate a `uv.lock` file
   - Note: should run on Linux rather than Windows to avoid platform marker drift)
5. Add `uv` to the Dockerfile for lockfile-based installs (future concern)

### Files to touch

- `.qwed.yml` (new)
- `uv.lock` (new, via `uv lock`)
- README (add QWED Security badge and ecosystem section — part of issue #1)
- No code changes needed

### Acceptance criteria

- `.qwed.yml` exists at repo root
- GitHub topics visible on repo page
- QWED Security listed in PR check status on subsequent PRs
- `uv.lock` exists and `uv sync --frozen` succeeds
- `uv.lock` and `pyproject.toml` versions match
