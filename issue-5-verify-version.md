## Fix `qwed-verify.yml` and add version sync

**Labels:** `bug`, `ci`, `release`

### The problem

Two things that need fixing:

**GitHub Action pins to ancient version**
`.github/workflows/qwed-verify.yml` pins to `qwed-finance@8002d00bbea4fbd05d486e9d5860a0ea2ca81bfd` with a comment saying `# v1.1.4`. Current version is v2.1.0. This means anyone who follows the quickstart guide in the README gets an old version that doesn't have BondGuard, FXGuard, RiskGuard, or any of the Decimal migration fixes. The README tells people to use this workflow, but it runs the wrong version.

**No version sync across the repo**
The version string lives in multiple places and they're manually kept in sync. Currently:
- `pyproject.toml`: `version = "2.1.0"`
- `qwed_finance/__init__.py`: `__version__ = "2.1.0"`
- `action_entrypoint.py`: `print(f"🏦 QWED Finance Guard v2.0")` — hardcoded and outdated!
- `npm/package.json`: probably has its own version
- README examples mention `v2.0.0` and `v2.1.0` in various places

qwed-ucp solves this with a simple sync approach: `__version__` is the source of truth, README is manually bumped, and npm version is synced with a script. qwed-finance doesn't have this.

### What to do

1. Update `qwed-verify.yml` to pin to `@v2.1.0` (or the latest release tag)
   - Pin by tag not commit SHA for readability, but if security is a concern, pin to the SHA of the v2.1.0 tag and update the comment
2. Fix `action_entrypoint.py` line 361: change `"v2.0"` → `f"v{__version__}"` by importing version from the package
3. Check `npm/package.json` version and sync to 2.1.0 if stale
4. Add a quick note in RELEASE.md or CONTRIBUTING.md about bumping version in all locations

### Files to touch

- `.github/workflows/qwed-verify.yml`
- `action_entrypoint.py`
- (possibly) `npm/package.json`
- (possibly) `RELEASE.md` (new) or `CONTRIBUTING.md`

### Acceptance criteria

- `qwed-verify.yml` runs v2.1.0 of the action
- `action_entrypoint.py` prints the correct version from `__version__`
- npm package version matches 2.1.0
- Version bump process is documented somewhere
