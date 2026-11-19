"""Export the explicitly reviewed application subset, without tenant data."""

import argparse
import hashlib
import json
from pathlib import Path

from build_library import COEFFICIENTS, PERCENTAGES, build, ensure, read_json, unique


def application_catalog(library, review):
    digest = hashlib.sha256(json.dumps(library, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ensure(review["library_sha256"] == digest, "Source library changed. Re-review approval selections and pin the new fingerprint.")
    sources, methods = library["sources"], library["methods"]
    aliases = {row["brand"]: row["aliases"].split("|") if row["aliases"] else []
               for row in library["brands"]}
    products = {}
    for row in library["products"]:
        key = row["brand"], row["product_line"]
        products[key] = {
            "brand": key[0], "series": key[1], "technology": row["canonical_film_type"],
            "brand_aliases": aliases[key[0]], "series_aliases": row["aliases"].split("|") if row["aliases"] else [],
            "status": row["status"], "homepage": row["source_url"],
        }
    used_sources = set()
    used_methods = set()
    conflicts = {(r["brand"], r["product_line"], r["shade"], r["metric"]) for r in library["discrepancies"]}
    warnings = {(r["brand"], r["product_line"], r["shade"], r["source"]) for r in library["validation_warnings"]}
    material = unique(
        library["records"],
        lambda r: (r["brand"], r["product_line"], r["nominal_shade"], r["source"], r["method"]),
    )
    used_fields = set()
    for rule in review["measurements"]:
        brand, series, source, method = (rule[k] for k in ("brand", "product_line", "source", "method"))
        product = products[brand, series]
        for shade in rule["shades"]:
            row = material[brand, series, shade, source, method]
            ensure(product["status"] == "current" and row["evidence"] == "reviewed_chart"
                   and not row.get("notes") and methods[method]["basis"] != "unknown"
                   and (brand, series, shade, source) not in warnings,
                   f"Approval uses an unresolved or historical measurement: {brand}/{series}/{shade}")
            fields = {}
            for field in rule["fields"]:
                key = brand, series, shade, field
                ensure(key not in conflicts and key not in used_fields, f"Conflicting or duplicate approval: {key}")
                fields[field] = row["measurements"][field]
                used_fields.add(key)
            product.setdefault("measurements", []).append({
                "shade": shade, "source": source, "method": method, "generation": row["generation"],
                "page": row["page"], "values": fields,
            })
            used_sources.add(source)
            used_methods.add(method)
    for brand, series, source in review["product_facts"]:
        matches = [r for r in library["facts"] if (r["brand"], r["product_line"], r["source"]) == (brand, series, source)]
        ensure(len(matches) == 1, f"Unknown product fact {brand}/{series}/{source}")
        row = matches[0]
        ensure(products[brand, series]["status"] == "current",
               f"Product copy cannot be approved for a historical line: {brand}/{series}")
        products[brand, series]["facts"] = {
            k: row[k] for k in ("source", "construction", "description", "available_shades", "roll_sizes") if row[k]
        }
        used_sources.add(source)
    for brand, series, source in review["warranties"]:
        matches = [r for r in library["warranties"] if r["brand"] == brand and series in r["products"] and r["source"] == source]
        ensure(len(matches) == 1 and matches[0]["evidence"] == "terms", f"Unapproved warranty {brand}/{series}/{source}")
        products[brand, series]["manufacturer_warranty"] = {
            k: matches[0][k] for k in ("source", "duration", "market", "coverage", "restrictions", "transfer")
        }
        used_sources.add(source)

    source_links = {}
    for source in sorted(used_sources):
        record = sources[source]
        source_links[source] = {key: record[key] for key in ("url", "revision", "sha256", "paths") if record.get(key)}
    # Match verified reprints without changing the original snapshot's provenance.
    for local, online in (("L56", "W-formulaone-chart"), ("L57", "W-llumar-chart")):
        if local in source_links:
            source_links[local]["url"] = sources[online]["url"]
    return {
        "format": 1,
        "library_revision": review["library_revision"],
        "library_sha256": digest,
        "approval_sha256": hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest(),
        "override_fields": {
            **{field: "%" for field in sorted(PERCENTAGES)},
            **{field: "ratio" for field in sorted(COEFFICIENTS)},
            "thickness_mil": "mil", "ply_count": "plies", "u_factor": "W/m²·K",
        },
        "products": list(products.values()),
        "methods": {key: methods[key] for key in sorted(used_methods)},
        "sources": source_links,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = application_catalog(build(), read_json("application-review.json"))
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
