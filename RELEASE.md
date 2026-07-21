# Release Process

## Version Bump Checklist

When bumping the version (e.g., `2.1.0` → `2.2.0`), update all of the following:

- `qwed_finance/__init__.py` — `__version__`
- `pyproject.toml` — `version` field
- `npm/package.json` — `version` field
- `action_entrypoint.py` — imports `__version__` from `qwed_finance` (automatic)
- `.github/workflows/qwed-verify.yml` — pin SHA and comment

## Creating a Release

1. Create a new branch `release/vX.Y.Z`
2. Update all version locations listed above
3. Open a PR to `main`
4. After merge, tag the merge commit: `git tag vX.Y.Z <sha>`
5. Push the tag: `git push origin vX.Y.Z`
6. Create a GitHub Release from the tag
