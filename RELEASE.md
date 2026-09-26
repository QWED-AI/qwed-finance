# Release Process

## Version Bump Checklist

When bumping the version (e.g., `2.1.0` → `3.0.0`), update all of the following:

- `qwed_finance/__init__.py` — `__version__` and the `vX.Y.Z` line in the module docstring
- `pyproject.toml` — `version` field
- `npm/package.json` — `version` field
- `npm/package-lock.json` — `version` field (both root and packages entry)
- `uv.lock` — root project `version` field
- `CHANGELOG.md` — new version section (Keep a Changelog format)
- `README.md` — GitHub Action usage example (`QWED-AI/qwed-finance@vX.Y.Z`) and a new `Released (vX.Y.Z)` roadmap section
- `action_entrypoint.py` — imports `__version__` from `qwed_finance` (automatic; the SARIF `"version"` field is the SARIF spec version, do not touch)
- `.github/workflows/qwed-verify.yml` — pin SHA and comment: **update this after the tag exists** (step 7 below — the SHA is unknowable before tagging)

## Creating a Release

1. Create a new branch `release/vX.Y.Z`
2. Update all version locations listed above (except the pin — see checklist note)
3. Open a PR to `main`
4. After merge, tag the merge commit: `git tag vX.Y.Z <sha>`
5. Push the tag: `git push origin vX.Y.Z`
6. Create a GitHub Release from the tag (publishes to PyPI via trusted publishing)
7. Open a pin-sync PR updating `.github/workflows/qwed-verify.yml` to the tagged SHA and comment `# vX.Y.Z`
8. Publish the npm package: `cd npm && npm ci && npm run build && npm publish` (`npm ci` first — devDependencies provide `tsc` on a fresh checkout)
