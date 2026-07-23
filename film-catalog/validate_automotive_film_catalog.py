#!/usr/bin/env python3

import csv
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BRANDS_PATH = ROOT / "automotive_film_brands.csv"
CATALOG_PATH = ROOT / "automotive_film_catalog.csv"

ALLOWED_TYPES = {
    "Dyed": 10,
    "Carbon": 20,
    "Metalized": 30,
    "Ceramic": 40,
    "Super Ceramic": 50,
    "Crystalline": 60,
}

ALLOWED_PRODUCT_STATUSES = {
    "current",
    "legacy",
    "discontinued",
}

ALLOWED_BRAND_STATUSES = {
    "mapped",
    "needs_product_review",
}


def clean(value):
    return " ".join(str(value or "").split()).strip()


def normalize(value):
    return clean(value).casefold()


def split_aliases(value):
    return [
        clean(alias)
        for alias in str(value or "").split("|")
        if clean(alias)
    ]


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def fail(errors):
    print("\nCATALOG VALIDATION FAILED")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)


def main():
    errors = []

    for required in (BRANDS_PATH, CATALOG_PATH):
        if not required.exists():
            errors.append(f"Missing required file: {required}")

    if errors:
        fail(errors)

    brands = read_csv(BRANDS_PATH)
    products = read_csv(CATALOG_PATH)

    brand_map = {}
    brand_alias_owner = {}

    for index, row in enumerate(brands, start=2):
        brand = clean(row.get("brand"))
        status = clean(row.get("catalog_status"))

        if not brand:
            errors.append(f"{BRANDS_PATH.name}:{index}: blank brand")
            continue

        key = normalize(brand)
        if key in brand_map:
            errors.append(
                f"{BRANDS_PATH.name}:{index}: duplicate brand {brand!r}"
            )
        brand_map[key] = row

        if status not in ALLOWED_BRAND_STATUSES:
            errors.append(
                f"{BRANDS_PATH.name}:{index}: invalid catalog_status "
                f"{status!r} for {brand!r}"
            )

        for alias in [brand, *split_aliases(row.get("aliases"))]:
            alias_key = normalize(alias)
            existing = brand_alias_owner.get(alias_key)

            if existing and existing != brand:
                errors.append(
                    f"{BRANDS_PATH.name}:{index}: brand alias {alias!r} "
                    f"collides between {existing!r} and {brand!r}"
                )
            brand_alias_owner[alias_key] = brand

    product_key_owner = {}
    alias_owner_by_brand = {}
    type_counts = Counter()
    brand_product_counts = Counter()
    status_counts = Counter()

    for index, row in enumerate(products, start=2):
        brand = clean(row.get("brand"))
        product = clean(row.get("product_line"))
        film_type = clean(row.get("canonical_film_type"))
        status = clean(row.get("status"))
        source_url = clean(row.get("source_url"))
        verified_at = clean(row.get("verified_at"))

        if not brand:
            errors.append(f"{CATALOG_PATH.name}:{index}: blank brand")
        if not product:
            errors.append(f"{CATALOG_PATH.name}:{index}: blank product_line")

        brand_key = normalize(brand)
        product_key = normalize(product)

        if brand_key not in brand_map:
            errors.append(
                f"{CATALOG_PATH.name}:{index}: brand {brand!r} "
                "is missing from the brand registry"
            )
        elif clean(brand_map[brand_key].get("catalog_status")) != "mapped":
            errors.append(
                f"{CATALOG_PATH.name}:{index}: brand {brand!r} has products "
                "but is not marked mapped"
            )

        compound_key = (brand_key, product_key)
        if compound_key in product_key_owner:
            errors.append(
                f"{CATALOG_PATH.name}:{index}: duplicate product "
                f"{brand!r} / {product!r}"
            )
        product_key_owner[compound_key] = index

        if film_type not in ALLOWED_TYPES:
            errors.append(
                f"{CATALOG_PATH.name}:{index}: invalid film type "
                f"{film_type!r} for {brand!r} / {product!r}"
            )
        else:
            expected_order = ALLOWED_TYPES[film_type]
            try:
                actual_order = int(clean(row.get("type_order")))
            except ValueError:
                actual_order = None

            if actual_order != expected_order:
                errors.append(
                    f"{CATALOG_PATH.name}:{index}: type_order must be "
                    f"{expected_order} for {film_type!r}"
                )

        if status not in ALLOWED_PRODUCT_STATUSES:
            errors.append(
                f"{CATALOG_PATH.name}:{index}: invalid product status "
                f"{status!r}"
            )

        if not source_url.startswith(("https://", "http://")):
            errors.append(
                f"{CATALOG_PATH.name}:{index}: missing or invalid source_url "
                f"for {brand!r} / {product!r}"
            )

        try:
            verified_date = date.fromisoformat(verified_at)
            if verified_date > date.today():
                errors.append(
                    f"{CATALOG_PATH.name}:{index}: verified_at is in the future"
                )
        except ValueError:
            errors.append(
                f"{CATALOG_PATH.name}:{index}: invalid verified_at "
                f"{verified_at!r}"
            )

        local_aliases = set()

        for alias in [product, *split_aliases(row.get("aliases"))]:
            alias_key = normalize(alias)

            if alias_key in local_aliases:
                errors.append(
                    f"{CATALOG_PATH.name}:{index}: duplicate alias "
                    f"{alias!r} within {brand!r} / {product!r}"
                )
                continue

            local_aliases.add(alias_key)
            alias_compound = (brand_key, alias_key)
            existing = alias_owner_by_brand.get(alias_compound)

            if existing and existing != product:
                errors.append(
                    f"{CATALOG_PATH.name}:{index}: alias {alias!r} under "
                    f"{brand!r} collides between {existing!r} and {product!r}"
                )

            alias_owner_by_brand[alias_compound] = product

        type_counts[film_type] += 1
        brand_product_counts[brand] += 1
        status_counts[status] += 1

    mapped_brands = {
        clean(row.get("brand"))
        for row in brands
        if clean(row.get("catalog_status")) == "mapped"
    }

    for brand in sorted(mapped_brands):
        if brand_product_counts[brand] == 0:
            errors.append(
                f"{BRANDS_PATH.name}: brand {brand!r} is marked mapped "
                "but has no product rows"
            )

    if errors:
        fail(errors)

    print("AUTOMOTIVE FILM CATALOG VALID")
    print(f"Brands in registry: {len(brands)}")
    print(f"Mapped brands: {len(mapped_brands)}")
    print(
        "Brands awaiting product review: "
        f"{sum(1 for row in brands if clean(row.get('catalog_status')) == 'needs_product_review')}"
    )
    print(f"Verified products: {len(products)}")

    print("\nProducts by AI film type:")
    for film_type, order in sorted(ALLOWED_TYPES.items(), key=lambda item: item[1]):
        print(f"  {film_type}: {type_counts[film_type]}")

    print("\nProducts by brand:")
    for brand, count in sorted(
        brand_product_counts.items(),
        key=lambda item: item[0].casefold(),
    ):
        print(f"  {brand}: {count}")

    print("\nProduct statuses:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
