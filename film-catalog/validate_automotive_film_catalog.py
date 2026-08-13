#!/usr/bin/env python3

import csv
from collections import Counter
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
BRANDS_PATH = BASE_DIR / "automotive_film_brands.csv"
CATALOG_PATH = BASE_DIR / "automotive_film_catalog.csv"
COVERAGE_PATH = BASE_DIR / "automotive_film_spec_coverage.csv"
SPECS_PATH = BASE_DIR / "automotive_film_specs.csv"

ALLOWED_TYPES = {
    "Dyed": 10,
    "Carbon": 20,
    "Metalized": 30,
    "Ceramic": 40,
    "Super Ceramic": 50,
    "Crystalline": 60,
}

ALLOWED_BRAND_STATUSES = {"mapped", "needs_product_review"}
ALLOWED_PRODUCT_STATUSES = {"current", "legacy"}
ALLOWED_COVERAGE_STATUSES = {
    "verified_shade_level",
    "verified_product_level",
    "partial",
    "conflicting",
    "catalog_only",
    "legacy_reference",
}
ALLOWED_SPEC_SCOPES = {"shade", "product"}
ALLOWED_SPEC_STATUSES = {
    "verified",
    "verified_product_level",
    "partial",
    "conflicting",
}
NON_TINT_BRAND_TOKENS = {"exoshield"}
NON_STANDARD_TINT_PRODUCT_TOKENS = {
    "action safety",
    "safety security",
    "security film",
}
SPEC_FACT_FIELDS = {
    "measured_vlt_pct",
    "vlr_exterior_pct",
    "vlr_interior_pct",
    "uv_rejection",
    "tser_pct",
    "tser_range",
    "glare_reduction_pct",
    "ir_primary_value",
    "ir_secondary_value",
    "solar_transmittance_pct",
    "solar_reflectance_pct",
    "solar_absorbance_pct",
    "shading_coefficient",
    "shgc",
    "thickness_mil",
    "construction",
    "warranty",
}


def clean(value):
    return " ".join(str(value or "").split()).strip()


def key_text(value):
    return clean(value).casefold()


def read_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def duplicate_values(values):
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def validate_required_files(errors):
    for path in (BRANDS_PATH, CATALOG_PATH, COVERAGE_PATH, SPECS_PATH):
        if not path.exists():
            errors.append(f"Missing required catalog file: {path.name}")


def validate_brands(errors, rows):
    names = [clean(row.get("brand")) for row in rows]

    for duplicate in duplicate_values(name.casefold() for name in names if name):
        errors.append(f"Duplicate brand: {duplicate}")

    for index, row in enumerate(rows, start=2):
        brand = clean(row.get("brand"))
        status = clean(row.get("catalog_status"))

        if not brand:
            errors.append(f"brands.csv row {index}: missing brand")
        if status not in ALLOWED_BRAND_STATUSES:
            errors.append(
                f"brands.csv row {index}: invalid catalog_status {status!r}"
            )
        if any(token in key_text(brand) for token in NON_TINT_BRAND_TOKENS):
            errors.append(
                f"brands.csv row {index}: exterior/non-tint brand {brand!r} does not belong in the automotive tint catalog"
            )


def validate_products(errors, brands, rows):
    brand_lookup = {
        key_text(row.get("brand")): row
        for row in brands
        if clean(row.get("brand"))
    }
    product_keys = []

    for index, row in enumerate(rows, start=2):
        brand = clean(row.get("brand"))
        product = clean(row.get("product_line"))
        film_type = clean(row.get("canonical_film_type"))
        status = clean(row.get("status"))
        order_text = clean(row.get("type_order"))
        key = (key_text(brand), key_text(product))
        product_keys.append(key)

        if not brand or not product:
            errors.append(
                f"catalog.csv row {index}: brand and product_line are required"
            )

        brand_row = brand_lookup.get(key_text(brand))
        if not brand_row:
            errors.append(f"catalog.csv row {index}: unknown brand {brand!r}")
        elif clean(brand_row.get("catalog_status")) != "mapped":
            errors.append(
                f"catalog.csv row {index}: product {brand} / {product} belongs to review-only brand"
            )

        if film_type not in ALLOWED_TYPES:
            errors.append(
                f"catalog.csv row {index}: invalid canonical_film_type {film_type!r}"
            )
        else:
            try:
                order = int(order_text)
            except ValueError:
                order = None
            if order != ALLOWED_TYPES[film_type]:
                errors.append(
                    f"catalog.csv row {index}: type_order {order_text!r} does not match {film_type}"
                )

        if status not in ALLOWED_PRODUCT_STATUSES:
            errors.append(f"catalog.csv row {index}: invalid status {status!r}")

        product_text = key_text(product)
        if any(token in product_text for token in NON_STANDARD_TINT_PRODUCT_TOKENS):
            errors.append(
                f"catalog.csv row {index}: safety/security product {product!r} must be modeled outside standard tint"
            )

    for duplicate in duplicate_values(product_keys):
        errors.append(f"Duplicate catalog product: {duplicate}")

    return set(product_keys)


def validate_coverage(errors, product_keys, rows):
    coverage_keys = []

    for index, row in enumerate(rows, start=2):
        key = (key_text(row.get("brand")), key_text(row.get("product_line")))
        coverage_keys.append(key)
        status = clean(row.get("spec_status"))

        if key not in product_keys:
            errors.append(f"coverage.csv row {index}: unknown product {key}")
        if status not in ALLOWED_COVERAGE_STATUSES:
            errors.append(
                f"coverage.csv row {index}: invalid spec_status {status!r}"
            )
        if not clean(row.get("verified_at")):
            errors.append(f"coverage.csv row {index}: verified_at is required")

    for duplicate in duplicate_values(coverage_keys):
        errors.append(f"Duplicate coverage product: {duplicate}")

    coverage_key_set = set(coverage_keys)
    for key in sorted(product_keys - coverage_key_set):
        errors.append(f"Missing coverage row for catalog product: {key}")
    for key in sorted(coverage_key_set - product_keys):
        errors.append(f"Coverage row has no catalog product: {key}")


def validate_specs(errors, product_keys, rows):
    seen_rows = set()

    for index, row in enumerate(rows, start=2):
        brand = clean(row.get("brand"))
        product = clean(row.get("product_line"))
        scope = clean(row.get("record_scope"))
        shade = clean(row.get("nominal_shade"))
        source_kind = clean(row.get("source_kind"))
        source_url = clean(row.get("source_url"))
        verified_at = clean(row.get("verified_at"))
        data_status = clean(row.get("data_status"))
        product_key = (key_text(brand), key_text(product))

        if product_key not in product_keys:
            errors.append(
                f"specs.csv row {index}: unknown product {brand!r} / {product!r}"
            )
        if scope not in ALLOWED_SPEC_SCOPES:
            errors.append(
                f"specs.csv row {index}: invalid record_scope {scope!r}"
            )
        if scope == "shade" and not shade:
            errors.append(
                f"specs.csv row {index}: shade record requires nominal_shade"
            )
        if scope == "product" and shade:
            errors.append(
                f"specs.csv row {index}: product record must not set nominal_shade"
            )
        if data_status not in ALLOWED_SPEC_STATUSES:
            errors.append(
                f"specs.csv row {index}: invalid data_status {data_status!r}"
            )
        if not source_kind or not source_url:
            errors.append(
                f"specs.csv row {index}: source_kind and source_url are required"
            )
        if not verified_at:
            errors.append(f"specs.csv row {index}: verified_at is required")

        if not any(clean(row.get(field)) for field in SPEC_FACT_FIELDS):
            errors.append(
                f"specs.csv row {index}: no factual specification fields are populated"
            )

        primary_metric = clean(row.get("ir_primary_metric"))
        primary_value = clean(row.get("ir_primary_value"))
        secondary_metric = clean(row.get("ir_secondary_metric"))
        secondary_value = clean(row.get("ir_secondary_value"))
        if bool(primary_metric) != bool(primary_value):
            errors.append(
                f"specs.csv row {index}: primary IR metric/value must be populated together"
            )
        if bool(secondary_metric) != bool(secondary_value):
            errors.append(
                f"specs.csv row {index}: secondary IR metric/value must be populated together"
            )

        identity = (
            product_key,
            scope.casefold(),
            shade.casefold(),
            source_kind.casefold(),
            source_url.casefold(),
            clean(row.get("source_date")).casefold(),
        )
        if identity in seen_rows:
            errors.append(
                f"specs.csv row {index}: duplicate source-specific spec record for {brand} / {product} / {shade or 'product'}"
            )
        seen_rows.add(identity)


def main():
    errors = []
    validate_required_files(errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    brands = read_rows(BRANDS_PATH)
    products = read_rows(CATALOG_PATH)
    coverage = read_rows(COVERAGE_PATH)
    specs = read_rows(SPECS_PATH)

    validate_brands(errors, brands)
    product_keys = validate_products(errors, brands, products)
    validate_coverage(errors, product_keys, coverage)
    validate_specs(errors, product_keys, specs)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print()
        print(f"Validation failed with {len(errors)} error(s).")
        return 1

    coverage_counts = Counter(clean(row.get("spec_status")) for row in coverage)
    spec_status_counts = Counter(clean(row.get("data_status")) for row in specs)

    print("Automotive film catalog validation passed.")
    print(f"Brands: {len(brands)}")
    print(f"Products: {len(products)}")
    print(f"Coverage rows: {len(coverage)}")
    print(f"Normalized spec records: {len(specs)}")
    print(f"Coverage statuses: {dict(sorted(coverage_counts.items()))}")
    print(f"Spec record statuses: {dict(sorted(spec_status_counts.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
