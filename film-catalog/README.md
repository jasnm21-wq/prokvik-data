# Automotive Film Catalog

This directory is the canonical Prokvik source for automotive window-film brands, product lines, classifications, and verified performance data.

## Source files

- `automotive_film_brands.csv` — recognized manufacturer registry.
- `automotive_film_catalog.csv` — canonical product line and Prokvik film-category mapping.
- `automotive_film_spec_coverage.csv` — audit of how much authoritative performance data is available for each canonical product.
- `automotive_film_specs.csv` — shade-level manufacturer-published performance values. Missing values stay blank.
- `automotive_film_default_content.csv` — conservative customer-facing default copy that shops may override.
- `automotive_film_catalog.manifest.json` — generated counts and source fingerprint.

## Accuracy rules

1. Manufacturer technical data sheets and manufacturer product pages are the only canonical numeric sources.
2. Do not infer, average, interpolate, or back-fill an unpublished value.
3. Preserve the manufacturer's comparison operator (`>99`, `>=99`, etc.) instead of normalizing it to a stronger claim.
4. Store nominal shade separately from measured VLT.
5. Infrared figures must retain the manufacturer's metric and wavelength/test method when published. IRR, IRER, and SIRR are not interchangeable.
6. Preserve substrate/test-standard qualifiers when published.
7. When current manufacturer sources conflict, mark the product `conflicting` and keep the conflicting values source-specific rather than choosing or averaging them.
8. A product may remain available in Pricing even when no verified performance values are available. Customer-facing proposals must omit unverified numeric claims.
9. Shop-edited descriptions/specifications are tenant overrides and must never be silently overwritten by catalog refreshes.
10. Exterior windshield-protection film, PPF, safety/security film, and architectural film are separate product families and do not belong in the normal automotive tint matrix.

## Coverage statuses

- `verified_shade_level` — authoritative values are available for individual shades.
- `verified_product_level` — only product-level ranges/maxima or non-shade-specific values are verified.
- `partial` — identity/construction/available shades are verified, but useful performance metrics are incomplete.
- `conflicting` — current authoritative sources disagree.
- `catalog_only` — product identity/classification is verified but performance data has not been captured.
- `legacy_reference` — retained for historical tenant data, not current onboarding.

## Generation

After changing the brand or product catalog, regenerate frontend/backend artifacts:

```bash
python film-catalog/generate_automotive_film_catalog.py \
  --frontend-root ~/obsidian-saas-app \
  --backend-root ~/obsidian-saas
```

Then verify drift with:

```bash
python film-catalog/generate_automotive_film_catalog.py \
  --frontend-root ~/obsidian-saas-app \
  --backend-root ~/obsidian-saas \
  --check
```

Run `validate_automotive_film_catalog.py` before merge.
