#!/usr/bin/env python3
"""Validate and export Phase 1 source-specific evidence for the existing catalog."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parent
REVIEWED = "2026-11-18"
PERCENTAGES = {
    "measured_vlt_pct", "vlr_unspecified_pct", "vlr_exterior_pct", "vlr_interior_pct",
    "uv_rejection", "uv_transmittance_pct", "tser_pct", "glare_reduction_pct", "privacy_pct",
    "irr_pct", "irer_pct", "sirr_pct", "irr_short_pct", "irr_long_pct", "solar_transmittance_pct", "solar_reflectance_pct",
    "solar_absorbance_pct", "solar_ir_absorption_pct", "narrow_band_ir_as_published_pct",
    "ir_aswf_78_25_pct", "ir_aswf_09_10_pct", "ssir_as_published_pct", "visible_absorbance_pct",
}
COEFFICIENTS = {"shgc", "shading_coefficient", "emissivity"}
NUMERIC = PERCENTAGES | COEFFICIENTS | {"thickness_mil", "ply_count", "u_factor"}
NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
VALUE = re.compile(rf"(?:[<>]=?|[≥≤~≈])?\s*({NUMBER})\s*(%)?(\+)?")
SHA256 = re.compile(r"[a-f0-9]{64}")
SHADE = re.compile(rf"({NUMBER})(?::([\w .+-]+))?")


def read_json(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def read_csv(name):
    with (CATALOG / f"automotive_film_{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def rows(name, columns):
    for i, line in enumerate((HERE / name).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) != len(columns):
            raise ValueError(f"{name}:{i} invalid column count")
        yield dict(zip(columns, fields, strict=True))


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def unique(records, key):
    index = {}
    for record in records:
        k = key(record)
        ensure(k not in index, f"Duplicate record {k!r}")
        index[k] = record
    return index


def https(url):
    parsed = urlsplit(url)
    ensure(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
           and not parsed.password, f"Invalid source URL {url!r}")


def normalized_shade(value):
    match = SHADE.fullmatch(value)
    ensure(match is not None and Decimal(match[1]) <= 100, f"Invalid shade {value!r}")
    return format(Decimal(match[1]).normalize(), "f") + (f":{match[2]}" if match[2] else "")


def check_value(field, raw):
    match = VALUE.fullmatch(raw)
    ensure(match is not None, f"Invalid {field} value {raw!r}")
    value = Decimal(match[1])
    if field in PERCENTAGES:
        ensure(value <= 100, f"Out-of-range {field}: {raw!r}")
    elif field in COEFFICIENTS:
        ensure(not match[3], f"Unexpected plus qualifier in {field}: {raw!r}")
        # Shading coefficient is a ratio against reference glass and can exceed 1.
        limit = Decimal("1.25") if field == "shading_coefficient" else 1
        ensure(not match[2] and value <= limit, f"Invalid {field}: {raw!r}")
    else:
        ensure(not match[2] and not match[3] and value > 0, f"Invalid {field}: {raw!r}")
        ensure(field != "ply_count" or value == value.to_integral_value(), f"Invalid ply count {raw!r}")
    return re.sub(r"[\s%]", "", raw)


def reviewed_tables():
    current = None
    for line in (HERE / "reviewed-tables.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if "|" in line:
            source, brand, product, page, method, fields = line.split("|")
            current = {"source": source, "brand": brand, "product_line": product,
                       "page": int(page) if page else None, "method": method, "fields": fields.split(), "rows": []}
            yield current
        else:
            ensure(current is not None, "Data row has no table header")
            current["rows"].append(line.split())


def from_reviewed_tables(products, sources, methods):
    for table in [*read_json("parsed-tables.json"), *read_json("parsed-public-tables.json"), *reviewed_tables()]:
        key = (table["brand"], table["product_line"])
        source = sources[table["source"]]
        ensure(key in products and key[0] == source["brand"], f"Invalid product/source relationship {key}")
        if source["kind"] == "local":
            ensure(key[1] in source["products"], f"Local source has no matching product {key}")
        method, fields = table["method"], table["fields"]
        ensure(method in methods, f"Unknown method {method}")
        ensure(len(set(fields)) == len(fields) and set(fields) <= NUMERIC, f"Unknown fields in {key}: {fields}")
        page = table["page"]
        if source.get("pages") is not None:
            ensure(isinstance(page, int) and 1 <= page <= source["pages"], f"Invalid page {page}: {source['id']}")
        ensure(table["rows"], f"Table is empty: {key}")
        for i, values in enumerate(table["rows"], 1):
            label, *cells = values
            ensure(len(cells) == len(fields), f"{source['id']}: malformed row {key}, {label}")
            measurements = {f: check_value(f, v) for f, v in zip(fields, cells) if v != "-"}
            ensure(measurements, f"Empty spec row for {key}, {label}")
            yield {"brand": key[0], "product_line": key[1], "nominal_shade": normalized_shade(label) if label != "series" else None,
                   "source_shade": label if label != "series" else None, "method": method, "source": source["id"], "page": page,
                   "generation": table.get("generation"), "measurements": measurements,
                   "evidence": "reviewed_chart", "locator": f"Page {page} · row {i}" if page else f"Table row {i}"}


def check_reported_percentage(value):
    match = re.fullmatch(rf"({NUMBER})[-–]({NUMBER})", value)
    if match:
        ensure(Decimal(match[1]) <= Decimal(match[2]) <= 100, f"Invalid percentage range {value!r}")
    else:
        cleaned = value.removeprefix("up to ").removesuffix(" (all)")
        check_value("irr_pct", cleaned)



def existing_specs(sources, products):
    """Carry forward the exact catalog values and original provenance."""
    for row in read_csv("specs"):
        brand, product = row["brand"], row["product_line"]
        ensure((brand, product) in products, f"Unknown product {brand}/{product}")
        url = row["source_url"]
        https(url)
        source_id = "C-" + hashlib.sha256(f"{brand}\n{url}\n{row['source_date']}".encode()).hexdigest()[:16]
        sources.setdefault(source_id, {"id": source_id, "brand": brand, "kind": "existing_catalog",
                                       "url": url, "revision": row["source_date"] or None,
                                       "verified_at": row["verified_at"], "scope": "automotive"})
        measurements = {}
        offered = row["measured_vlt_pct"] if "|" in row["measured_vlt_pct"] and row["record_scope"] == "product" else ""
        for field in sorted(NUMERIC):
            if field == "measured_vlt_pct" and offered:
                continue
            value = (row.get(field) or "").strip()
            if value:
                measurements[field] = check_value(field, value)
        if row["tser_range"].strip():
            check_reported_percentage(row["tser_range"])
        # Ambiguous legacy infrared labels are preserved verbatim with the original wavelength.
        ir = [
            {"label": row[f"ir_{which}_metric"], "value": row[f"ir_{which}_value"],
             "wavelength_nm": row[f"ir_{which}_wavelength_nm"] or None}
            for which in ("primary", "secondary") if row[f"ir_{which}_value"]
        ]
        for metric in ir:
            check_reported_percentage(metric["value"])
        label = row["nominal_shade"]
        yield {"brand": brand, "product_line": product, "nominal_shade": normalized_shade(label) if label else None,
               "source_shade": label or None, "source": source_id, "page": None, "method": "unknown",
               "evidence": "existing_catalog", "measurements": measurements, "published_ir": ir,
               "available_shades": [normalized_shade(option) for option in offered.split("|")] if offered else [],
               "reported_substrate": row["substrate"] or None, "reported_test_standard": row["test_standard"] or None,
               "tser_range": row["tser_range"] or None, "construction": row["construction"] or None,
               "warranty_summary": row["warranty"] or None, "generation": None,
               "prior_status": row["data_status"], "notes": row["notes"] or None}


def find_discrepancies(records, methods):
    by_measurement = defaultdict(list)
    for row in records:
        if row["nominal_shade"] is None:
            continue
        for field, value in row["measurements"].items():
            by_measurement[row["brand"], row["product_line"], row["generation"], row["nominal_shade"], field].append((row, value))
    issues = []
    for (brand, product, generation, shade, metric), values in sorted(by_measurement.items(), key=lambda pair: str(pair[0])):
        pairs = {}
        for i, (a, av) in enumerate(values):
            for b, bv in values[i + 1:]:
                # Precision is preserved in records; 4 and 4.0 are the same measurement.
                no_trailing_zeros = lambda v: re.sub(r"(\.\d*?)0+$", r"\1", v).rstrip(".")
                if no_trailing_zeros(av) == no_trailing_zeros(bv):
                    continue
                if a["method"] == b["method"] and methods[a["method"]]["basis"] != "unknown":
                    reason = "conflicting_same_method"
                elif methods[a["method"]]["basis"] == "unknown" or methods[b["method"]]["basis"] == "unknown":
                    reason = "unresolved_method_difference"
                else:
                    continue
                for row, value in ((a, av), (b, bv)):
                    pairs.setdefault(reason, set()).add((row["source"], row["method"], value))
        for kind, options in pairs.items():
            issues.append({"brand": brand, "product_line": product, "generation": generation, "shade": shade,
                           "metric": metric, "kind": kind, "alternatives": [
                               {"source": source, "method": method, "value": value}
                               for source, method, value in sorted(options)
                           ]})
    return issues


def solar_balance_warnings(records):
    """Flag printed values that cannot balance to rounding precision."""
    metrics = ("solar_transmittance_pct", "solar_reflectance_pct", "solar_absorbance_pct")
    for row in records:
        readings = [row["measurements"].get(metric) for metric in metrics]
        if not all(v and re.fullmatch(NUMBER, v) for v in readings):
            continue
        total = sum(Decimal(v) for v in readings)
        if not Decimal("98") <= total <= Decimal("102"):
            yield {"brand": row["brand"], "product_line": row["product_line"], "shade": row["nominal_shade"],
                   "source": row["source"], "page": row["page"], "metric": "solar_balance",
                   "total": str(total), "readings": dict(zip(metrics, readings, strict=True))}

def build(original_root=None):
    brands = unique(read_csv("brands"), lambda row: row["brand"])
    products = unique(read_csv("catalog"), lambda row: (row["brand"], row["product_line"]))
    research = list(rows("manufacturer-research.tsv", ("brand", "status", "url", "notes")))
    ensure(set(unique(research, lambda r: r["brand"])) == set(brands), "Every registered manufacturer needs research")
    local = read_json("local-sources.json")
    unique(local, lambda s: s["sha256"])
    for source in local:
        ensure(SHA256.fullmatch(source["sha256"]) and source["pages"] > 0, f"Invalid local source {source['id']}")
        ensure(source["paths"] and all((source["brand"], p) in products for p in source["products"]),
               f"Unrecognized local product {source['id']}")
        for path in source["paths"]:
            rel = PurePosixPath(path)
            ensure(not rel.is_absolute() and ".." not in rel.parts, f"Unsafe local source path {path}")
            if original_root:
                original = (original_root / path).resolve(strict=True)
                ensure(original.is_relative_to(original_root), f"Local source outside originals: {path}")
                ensure(hashlib.sha256(original.read_bytes()).hexdigest() == source["sha256"], f"Changed original {path}")
    web = list(rows("supplemental-sources.tsv", ("id", "brand", "subject", "url", "revision", "scope")))
    web.extend({"id": f"R-{r['brand']}", "brand": r["brand"], "url": r["url"], "subject": "Manufacturer research",
                "revision": None, "scope": "automotive", "review_status": r["status"]} for r in research)
    hashes = read_json("public-document-hashes.json")
    for source in web:
        https(source["url"])
        ensure(source["scope"] in {"automotive", "architectural", "mixed"}, f"Unknown source scope {source['scope']}")
        source.update(kind="official_web", verified_at=REVIEWED)
        if source["id"] in hashes:
            ensure(SHA256.fullmatch(hashes[source["id"]]), f"Invalid public source fingerprint {source['id']}")
            source["sha256"] = hashes[source["id"]]
    ensure(set(hashes) <= {s["id"] for s in web}, "Unreferenced public source fingerprint")
    sources = unique([*local, *web], lambda row: row["id"])
    for source in sources.values():
        ensure(source["brand"] in brands, f"Unknown manufacturer {source['brand']}")
        date.fromisoformat(source["verified_at"])
    paths = unique(({"path": p} for source in local for p in source["paths"]), lambda r: r["path"])
    if original_root:
        files = {path.relative_to(original_root).as_posix() for path in original_root.rglob("*")
                 if path.is_file() and not path.is_symlink()}
        ensure(files == set(paths), f"Original inventory differs from source registry: {files ^ set(paths)}")
    methods = read_json("methods.json")
    for key, method in methods.items():
        ensure(method["basis"] in {"unknown", "film_only", "film_on_glass", "film_with_liner"},
               f"Invalid measurement basis: {key}")
        for metric, band in method.get("wavelength_nm", {}).items():
            limits = band.split("–")
            ensure(metric in PERCENTAGES and len(limits) <= 2 and all(n.isdigit() and int(n) > 0 for n in limits)
                   and limits == sorted(limits, key=int), f"Invalid wavelength: {key}/{metric}")
    records = [*from_reviewed_tables(products, sources, methods), *existing_specs(sources, products)]
    unique(records, lambda r: (r["brand"], r["product_line"], r["nominal_shade"], r["source"], r["method"], r["generation"]))
    discrepancies = find_discrepancies(records, methods)
    warnings = list(solar_balance_warnings(records))
    for record in records:
        record["method_review_required"] = methods[record["method"]]["basis"] == "unknown"
    for annotation in read_json("row-notes.json"):
        for shade in annotation["shades"]:
            matches = [r for r in records if r["source"] == annotation["source"]
                       and r["product_line"] == annotation["product_line"] and r["nominal_shade"] == shade]
            ensure(len(matches) == 1, f"Unresolved row annotation: {annotation}, shade {shade}")
            matches[0]["notes"] = annotation["note"]

    facts = list(rows("product-facts.tsv", ("source", "brand", "product_line", "construction", "description", "roll_sizes", "notes", "available_shades")))
    warranties = list(rows("warranties.tsv", ("source", "brand", "products", "duration", "market", "coverage",
                                              "restrictions", "transfer", "evidence")))
    for fact in facts:
        ensure((fact["brand"], fact["product_line"]) in products, f"Unknown product {fact}")
        choices = fact["available_shades"]
        fact["available_shades"] = [normalized_shade(s) for s in choices.split(";")] if choices else []
        ensure(len(fact["available_shades"]) == len(set(fact["available_shades"])), f"Duplicate shade in {fact}")
    for warranty in warranties:
        warranty["products"] = warranty["products"].split(";") if warranty["products"] else []
        ensure(all((warranty["brand"], p) in products for p in warranty["products"]), f"Unknown product in {warranty}")
        ensure(warranty["duration"] and warranty["restrictions"], f"Missing warranty conditions {warranty}")
    for row in facts + warranties:
        ensure(sources[row["source"]]["brand"] == row["brand"], f"Incorrect source reference {row}")
    ensure(all(w["evidence"] in {"terms", "overview", "historical_terms", "conflicting_terms"}
               for w in warranties), "Unknown warranty evidence status")
    unique(warranties, lambda row: (row["source"], row["brand"], tuple(row["products"])))
    unique(facts, lambda row: (row["source"], row["brand"], row["product_line"]))

    shade_variants = {
        (r["brand"], r["product_line"], r["generation"], shade)
        for r in records for shade in ([r["nominal_shade"]] if r["nominal_shade"] else r.get("available_shades", []))
    }
    shade_variants.update((f["brand"], f["product_line"], None, shade) for f in facts for shade in f["available_shades"])
    counts = {
        "manufacturers": len(brands), "series": len(products), "shade_variants": len(shade_variants),
        "specification_records": len(records), "reviewed_specification_records": sum(r["evidence"] == "reviewed_chart" for r in records),
        "warranty_records": len(warranties), "local_documents": len(local),
        "local_files": sum(len(s["paths"]) for s in local), "rendered_pages": sum(s["pages"] for s in local),
        "official_references": len(web), "public_document_hashes": len(hashes),
        "discrepancies": len(discrepancies),
        "same_method_conflicts": sum(i["kind"] == "conflicting_same_method" for i in discrepancies),
        "solar_balance_warnings": len(warnings),
        "sources_with_known_basis": len({r["source"] for r in records if not r["method_review_required"]}),
        "series_with_spec_records": len({(r["brand"], r["product_line"]) for r in records}),
        "series_with_shade_measurements": len({(r["brand"], r["product_line"]) for r in records
                                              if r["nominal_shade"] and r["measurements"]}),
        "manufacturers_with_spec_records": len({r["brand"] for r in records}),
        "manufacturers_with_warranty_records": len({r["brand"] for r in warranties}),
    }
    return {"counts": counts, "brands": list(brands.values()), "products": list(products.values()), "sources": sources,
            "research": research, "methods": methods, "records": records, "warranties": warranties, "facts": facts,
            "discrepancies": discrepancies, "validation_warnings": warnings}


def export(library, output, root=None):
    output.mkdir(parents=True, exist_ok=True)
    (output / "film-specification-library.json").write_text(json.dumps(library, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    product_rows = []
    for p in library["products"]:
        brand, product = p["brand"], p["product_line"]
        specs = [r for r in library["records"] if r["brand"] == brand and r["product_line"] == product]
        discrepancies = [r for r in library["discrepancies"] if r["brand"] == brand and r["product_line"] == product]
        warnings = [r for r in library["validation_warnings"] if r["brand"] == brand and r["product_line"] == product]
        observed = set().union(*(r["measurements"] for r in specs))
        facts = [f for f in library["facts"] if f["brand"] == brand and f["product_line"] == product]
        offered = {s for r in specs + facts for s in r.get("available_shades", [])}
        measured = {r["nominal_shade"] for r in specs if r["nominal_shade"] and r["measurements"]}
        product_rows.append((brand, product, p["status"], len(specs), sum(r["evidence"] == "reviewed_chart" for r in specs),
                             len(offered | measured), len(measured), len(discrepancies), len(warnings),
                             "; ".join(sorted(NUMERIC - observed)),
                             sum(w["brand"] == brand and product in w["products"] for w in library["warranties"]),
                             any(f["roll_sizes"] for f in facts)))
    with (output / "product-coverage.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("manufacturer", "product", "status", "spec_records", "reviewed_specs", "nominal_shades",
                         "measured_shades", "discrepancies", "data_warnings", "missing_numeric_fields", "product_warranty_records", "roll_sizes_present"))
        writer.writerows(product_rows)
    with (output / "manufacturer-coverage.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("manufacturer", "series", "with_specs", "with_reviewed_specs", "warranty_records",
                         "local_documents", "research_status", "official_url", "outstanding"))
        for research in library["research"]:
            brand = research["brand"]
            entries = [row for row in product_rows if row[0] == brand]
            writer.writerow((brand, len(entries), sum(bool(p[3]) for p in entries), sum(bool(p[4]) for p in entries),
                             sum(w["brand"] == brand for w in library["warranties"]),
                             sum(s["kind"] == "local" and s["brand"] == brand for s in library["sources"].values()),
                             research["status"], research["url"], research["notes"]))
    data = {**library, "originals_uri": root.as_uri() if root else None}
    template = (HERE / "review.html").read_text(encoding="utf-8")
    (output / "review.html").write_text(template.replace("__LIBRARY__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")),
                                       encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, help="verify local SHA-256 fingerprints and enable local source links")
    parser.add_argument("--output", type=Path, help="export normalized JSON, coverage CSVs, and static viewer")
    args = parser.parse_args()
    root = args.originals.resolve(strict=True) if args.originals else None
    if args.output and root and (args.output.resolve() == root or root in args.output.resolve().parents):
        parser.error("Export must be outside the originals")
    library = build(root)
    print(json.dumps(library["counts"], sort_keys=True))
    if args.output:
        export(library, args.output, root)


if __name__ == "__main__":
    main()
