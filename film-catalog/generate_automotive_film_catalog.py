#!/usr/bin/env python3

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BRANDS_PATH = SCRIPT_DIR / "automotive_film_brands.csv"
CATALOG_PATH = SCRIPT_DIR / "automotive_film_catalog.csv"
MANIFEST_PATH = SCRIPT_DIR / "automotive_film_catalog.manifest.json"

TYPE_ORDER = {
    "Dyed": 10,
    "Carbon": 20,
    "Metalized": 30,
    "Ceramic": 40,
    "Super Ceramic": 50,
    "Crystalline": 60,
}


def clean(value):
    return " ".join(str(value or "").split()).strip()


def split_aliases(value):
    return [
        clean(alias)
        for alias in str(value or "").split("|")
        if clean(alias)
    ]


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def source_sha256():
    digest = hashlib.sha256()

    for path in (BRANDS_PATH, CATALOG_PATH):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    return digest.hexdigest()


def normalized_brands(rows):
    return [
        {
            "brand": clean(row.get("brand")),
            "aliases": split_aliases(row.get("aliases")),
            "official_url": clean(row.get("official_url")),
            "catalog_status": clean(row.get("catalog_status")),
            "notes": clean(row.get("notes")),
        }
        for row in rows
    ]


def normalized_products(rows):
    result = []

    for row in rows:
        result.append({
            "brand": clean(row.get("brand")),
            "product_line": clean(row.get("product_line")),
            "canonical_film_type": clean(row.get("canonical_film_type")),
            "type_order": int(clean(row.get("type_order"))),
            "aliases": split_aliases(row.get("aliases")),
            "status": clean(row.get("status")),
            "source_url": clean(row.get("source_url")),
            "verified_at": clean(row.get("verified_at")),
            "notes": clean(row.get("notes")),
        })

    return result


def compact_json_rows(rows):
    return "[\n" + "\n".join(
        "  " + json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
        ) + ","
        for row in rows
    ) + "\n]"


def compact_python_rows(rows):
    return "(\n" + "\n".join(
        f"    {tuple(row)!r},"
        for row in rows
    ) + "\n)"


def build_javascript(source_hash, brands, products):
    brand_rows = [
        [
            brand["brand"],
            brand["aliases"],
            brand["official_url"],
            brand["catalog_status"],
            brand["notes"],
        ]
        for brand in brands
    ]
    product_rows = [
        [
            product["brand"],
            product["product_line"],
            product["canonical_film_type"],
            product["type_order"],
            product["aliases"],
            product["status"],
            product["source_url"],
            product["verified_at"],
            product["notes"],
        ]
        for product in products
    ]

    return """// AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY.
// Source:
//   prokvik-data/film-catalog/automotive_film_brands.csv
//   prokvik-data/film-catalog/automotive_film_catalog.csv
//
// Regenerate with:
//   python film-catalog/generate_automotive_film_catalog.py \\
//     --frontend-root ~/obsidian-saas-app \\
//     --backend-root ~/obsidian-saas

export const FILM_CATALOG_SOURCE_SHA256 = %s

export const FILM_TYPE_ORDER = Object.freeze(%s)

const AUTOMOTIVE_FILM_BRAND_ROWS = Object.freeze(
%s
)

const AUTOMOTIVE_FILM_PRODUCT_ROWS = Object.freeze(
%s
)

export const AUTOMOTIVE_FILM_BRANDS = Object.freeze(
  AUTOMOTIVE_FILM_BRAND_ROWS.map(
    ([brand, aliases, official_url, catalog_status, notes]) => ({
      brand,
      aliases,
      official_url,
      catalog_status,
      notes,
    })
  )
)

export const AUTOMOTIVE_FILM_PRODUCTS = Object.freeze(
  AUTOMOTIVE_FILM_PRODUCT_ROWS.map(
    ([
      brand,
      product_line,
      canonical_film_type,
      type_order,
      aliases,
      status,
      source_url,
      verified_at,
      notes,
    ]) => ({
      brand,
      product_line,
      canonical_film_type,
      type_order,
      aliases,
      status,
      source_url,
      verified_at,
      notes,
    })
  )
)
""" % (
        json.dumps(source_hash),
        json.dumps(TYPE_ORDER, ensure_ascii=False),
        compact_json_rows(brand_rows),
        compact_json_rows(product_rows),
    )


def build_python(source_hash, brands, products):
    brand_rows = [
        (
            brand["brand"],
            tuple(brand["aliases"]),
            brand["official_url"],
            brand["catalog_status"],
            brand["notes"],
        )
        for brand in brands
    ]
    product_rows = [
        (
            product["brand"],
            product["product_line"],
            product["canonical_film_type"],
            product["type_order"],
            tuple(product["aliases"]),
            product["status"],
            product["source_url"],
            product["verified_at"],
            product["notes"],
        )
        for product in products
    ]

    return '''"""AUTO-GENERATED automotive film catalog.

Do not edit this file directly.

Source:
    prokvik-data/film-catalog/automotive_film_brands.csv
    prokvik-data/film-catalog/automotive_film_catalog.csv
"""

FILM_CATALOG_SOURCE_SHA256 = %r

FILM_TYPE_ORDER = %r

_AUTOMOTIVE_FILM_BRAND_ROWS = %s

_AUTOMOTIVE_FILM_PRODUCT_ROWS = %s

AUTOMOTIVE_FILM_BRANDS = tuple(
    {
        "brand": brand,
        "aliases": list(aliases),
        "official_url": official_url,
        "catalog_status": catalog_status,
        "notes": notes,
    }
    for brand, aliases, official_url, catalog_status, notes in _AUTOMOTIVE_FILM_BRAND_ROWS
)

AUTOMOTIVE_FILM_PRODUCTS = tuple(
    {
        "brand": brand,
        "product_line": product_line,
        "canonical_film_type": canonical_film_type,
        "type_order": type_order,
        "aliases": list(aliases),
        "status": status,
        "source_url": source_url,
        "verified_at": verified_at,
        "notes": notes,
    }
    for (
        brand,
        product_line,
        canonical_film_type,
        type_order,
        aliases,
        status,
        source_url,
        verified_at,
        notes,
    ) in _AUTOMOTIVE_FILM_PRODUCT_ROWS
)
''' % (
        source_hash,
        TYPE_ORDER,
        compact_python_rows(brand_rows),
        compact_python_rows(product_rows),
    )


def build_manifest(source_hash, brands, products):
    type_counts = Counter(
        product["canonical_film_type"]
        for product in products
    )
    product_status_counts = Counter(
        product["status"]
        for product in products
    )
    brand_status_counts = Counter(
        brand["catalog_status"]
        for brand in brands
    )
    verified_dates = sorted({
        product["verified_at"]
        for product in products
        if product["verified_at"]
    })

    return {
        "source_sha256": source_hash,
        "brand_count": len(brands),
        "product_count": len(products),
        "film_type_order": TYPE_ORDER,
        "products_by_film_type": {
            film_type: type_counts.get(film_type, 0)
            for film_type in TYPE_ORDER
        },
        "brands_by_status": dict(sorted(brand_status_counts.items())),
        "products_by_status": dict(sorted(product_status_counts.items())),
        "verified_dates": verified_dates,
    }


def write_or_check(path, content, check):
    if check:
        if not path.exists():
            print(f"DRIFT: missing generated file: {path}")
            return False

        if path.read_text(encoding="utf-8") != content:
            print(f"DRIFT: generated file differs: {path}")
            return False

        print(f"OK: {path}")
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Wrote {path}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--frontend-root",
        default="~/obsidian-saas-app",
        help="Path to the Prokvik frontend repository.",
    )
    parser.add_argument(
        "--backend-root",
        default="~/obsidian-saas",
        help="Path to the Prokvik backend repository.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify generated files without modifying them.",
    )
    args = parser.parse_args()

    frontend_root = Path(args.frontend_root).expanduser().resolve()
    backend_root = Path(args.backend_root).expanduser().resolve()

    if not BRANDS_PATH.exists() or not CATALOG_PATH.exists():
        print("Catalog source files are missing.", file=sys.stderr)
        return 1

    brands = normalized_brands(read_csv(BRANDS_PATH))
    products = normalized_products(read_csv(CATALOG_PATH))
    source_hash = source_sha256()

    javascript_path = (
        frontend_root
        / "src"
        / "lib"
        / "generatedAutomotiveFilmCatalog.js"
    )
    python_path = (
        backend_root
        / "core"
        / "generated_automotive_film_catalog.py"
    )
    manifest = build_manifest(source_hash, brands, products)

    results = [
        write_or_check(
            javascript_path,
            build_javascript(source_hash, brands, products),
            args.check,
        ),
        write_or_check(
            python_path,
            build_python(source_hash, brands, products),
            args.check,
        ),
        write_or_check(
            MANIFEST_PATH,
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            ) + "\n",
            args.check,
        ),
    ]

    if not all(results):
        return 1

    print()
    print(f"Catalog SHA-256: {source_hash}")
    print(f"Brands: {len(brands)}")
    print(f"Products: {len(products)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
