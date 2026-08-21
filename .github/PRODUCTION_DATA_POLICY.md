# Production data change policy

`main` is the canonical production data branch for Prokvik-maintained catalog data.

## Required change path

1. Create a non-`main` branch.
2. Change only the intended catalog/correction files.
3. Open a pull request into `main`.
4. Wait for `Data integrity gate` to pass.
5. Review the diff before merge.
6. Merge the pull request; do not force-push or rewrite `main` history.

## Validation

The PR gate validates the automotive film catalog, vehicle lookup corrections, vehicle correction tests, and CSV structural integrity.

The exact required GitHub status check name is `Data integrity gate`. Branch protection for `main` should require that check before merge.

Generated application artifacts remain versioned in their owning frontend/backend repositories. Data changes that require regenerated artifacts must be followed by the normal frontend/backend PR gates before production deployment.

## Emergency changes

Emergency fixes still use a branch and pull request. Do not bypass validation by editing `main` directly.
