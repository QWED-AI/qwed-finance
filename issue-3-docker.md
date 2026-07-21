## Dockerfile: Base image, dependencies, and .dockerignore

**Labels:** `enhancement`, `docker`, `security`

### The problem

The Dockerfile has a few issues that make it fragile and inconsistent with how other QWED repos build their containers.

**Python 3.14.6-slim**
This is a pre-release/very recent Python version. Not all pip packages may have wheels for it yet, and it's not available on all CI runners or build environments. Other QWED repos use 3.11 or 3.12 — stable, widely available. If we claim `requires-python = ">=3.10"` in pyproject.toml but ship a 3.14 image, that's inconsistent.

**`pip install /app pandas`**
Line 14 installs pandas from the local `/app` path, but pandas is not in `pyproject.toml` dependencies. This looks like dead code or a copy-paste error from another project. Either pandas is needed (add it to pyproject.toml) or this line should be removed.

**No `.dockerignore`**
Without a `.dockerignore`, the Docker build context includes `.git/`, `.pytest_cache/`, `__pycache__/`, tests/, examples/, and everything else. This bloats the image and potentially ships test data, cached files, and git history into production.

**No `uv` usage**
qwed-ucp uses `uv sync --frozen` with a `uv.lock` for reproducible builds. qwed-finance uses plain pip with no lockfile. uv is faster and more deterministic. Should consider switching.

**No `_safe_resolve()` sandbox**
qwed-verification's `action_entrypoint.py` uses `_safe_resolve()` to prevent path traversal when resolving file paths inside the container. qwed-finance's entrypoint just does `sys.path.insert(0, "/app")` with no validation. If someone passes a malicious path as a GitHub Action input, there's no guard.

**COPY ordering**
`COPY qwed_finance/ /app/qwed_finance/` happens before `RUN pip install...`. If `qwed_finance/` has a `setup.py` or `pyproject.toml`, pip might try to install it before dependencies are resolved. Standard practice is to copy `pyproject.toml` first, install deps, then copy source code.

### What to do

1. Change base image to `python:3.12-slim` (or 3.11-slim)
2. Either add pandas to `pyproject.toml` dependencies or remove the `pip install /app pandas` line
3. Add a `.dockerignore` excluding `.git`, `__pycache__`, `.pytest_cache`, `tests/`, `.github/`, `examples/`, `npm/`, `*.md`
4. Add `_safe_resolve()` to `action_entrypoint.py` for path validation
5. Reorder COPY instructions: pyproject.toml first, install deps, then copy source

### Files to touch

- `Dockerfile`
- `.dockerignore` (new)
- `action_entrypoint.py`

### Acceptance criteria

- Dockerfile builds cleanly with python:3.12-slim
- No pandas installed unless it's in pyproject.toml
- `.dockerignore` excludes build-context bloat
- `action_entrypoint.py` has `_safe_resolve()` for path safety
- COPY ordering follows layer caching best practice
