#!/usr/bin/env python3
"""Refresh one customer-facing model year from NHTSA vPIC.

The refresh is intentionally stricter than the audit report:
- NHTSA make names must exactly match the requested customer-facing make.
- Commercial/heavy rows are excluded.
- Customer-facing classes are limited to coupe, sedan, suv, truck, van.
- Reviewed make/model corrections are applied after the model-year replacement.

The script writes a reviewed model-year snapshot, an idempotent hosted SQL sync file,
and (with --write) updates the canonical vehicle_lookup_import_ready.csv atomically.
"""

from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path

from apply_vehicle_lookup_corrections import apply_corrections, load_corrections
from audit_vehicle_lookup_against_nhtsa import (
    FRONTEND_MAKES,
    fetch_nhtsa_models,
    is_likely_commercial_model,
    norm_make,
)


MODULE_DIR = Path(__file__).parent
DEFAULT_LOOKUP = MODULE_DIR / "vehicle_lookup_import_ready.csv"
DEFAULT_CORRECTIONS = MODULE_DIR / "corrections"
DEFAULT_MODEL_YEAR_DIR = MODULE_DIR / "model-years"
CANONICAL_CLASSES = {"coupe", "sedan", "suv", "truck", "van"}
PRICING_BY_CLASS = {
    "coupe": "Coupe",
    "sedan": "Sedan",
    "suv": "SUV",
    "truck": "Truck",
    "van": "Van",
}


def key_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


# These models are normal vans even when vPIC reports a broader MPV/truck type.
VAN_MODELS = {
    "carnival",
    "express",
    "grand caravan",
    "odyssey",
    "pacifica",
    "promaster 1500",
    "promaster 2500",
    "promaster 3500",
    "savana",
    "sienna",
    "sprinter",
    "transit",
    "voyager",
    "esprinter",
}

# Stable two-door/coupe customer pricing clarifications.
COUPE_MODELS = {
    "911",
    "430i",
    "brz",
    "cle",
    "cooper convertible",
    "corvette",
    "gr86",
    "lc",
    "m2",
    "m240i",
    "m4",
    "m440i",
    "mustang",
    "mustang gtd",
    "mx-5",
    "nissan z",
    "prelude",
    "sl-class",
    "supra",
    "cybercab",
}

# Crossovers/SUVs that vPIC sometimes exposes as Passenger Car rather than MPV.
SUV_MODELS = {
    "bZ".lower(),
    "bZ Woodland".lower(),
    "c-hr",
    "corolla cross",
    "countryman",
    "crown signia",
    "ec40",
    "eqe-class suv",
    "eqs-class suv",
    "ev3",
    "ev6",
    "ev9",
    "ex30",
    "ex30 cc",
    "ex40",
    "ex60",
    "ex90",
    "g-class",
    "glc-class",
    "grand wagoneer",
    "grand wagoneer l",
    "gravity",
    "gv60",
    "gv60 magma",
    "gv70",
    "gv80",
    "hummer ev suv",
    "ioniq 5",
    "ioniq 5 n",
    "ioniq 9",
    "kona",
    "mustang mach-e",
    "nexo",
    "niro",
    "outlander",
    "outlander sport",
    "prologue",
    "qx80",
    "recon",
    "solterra",
    "trailseeker",
    "tx",
    "uncharted",
    "v60cc",
    "v90cc",
    "venue",
    "wagoneer s",
}

TRUCK_MODELS = {
    "hummer ev pickup",
}

# Explicit customer-facing exclusions beyond the general commercial detector.
EXCLUDED_MODEL_KEYS = {
    "brightdrop",
    "edv",
    "f-600",
    "f600",
    "gt mkii",
    "rcv",
    "semi",
    "xcient",
}

VOLVO_COMMERCIAL_MODEL_KEYS = {
    "cab behind engine",
    "cab over engine ht",
    "cab over engine lt",
    "f12 w/f7 cab",
    "f6 w/f7 cab",
    "vah",
    "vhd",
    "vnl (4)",
    "vnr (4)",
    "vnx (4)",
    "vs",
    "vt",
}


def nhtsa_make_matches(requested_make: str, row_make: str) -> bool:
    """Reject vPIC partial-make matches such as Ford -> Stanford Customs."""
    return norm_make(requested_make) == norm_make(row_make)


def is_customer_facing_model(make: str, model: str) -> bool:
    model_key = key_text(model)
    if not model_key:
        return False
    if model_key in EXCLUDED_MODEL_KEYS:
        return False
    if norm_make(make) == "volvo" and model_key in VOLVO_COMMERCIAL_MODEL_KEYS:
        return False
    return not is_likely_commercial_model(make, model)


def classify_customer_vehicle(model: str, vehicle_type: str) -> tuple[str, str]:
    model_key = key_text(model)

    if model_key in VAN_MODELS:
        vehicle_class = "van"
    elif model_key in TRUCK_MODELS:
        vehicle_class = "truck"
    elif model_key in SUV_MODELS:
        vehicle_class = "suv"
    elif model_key in COUPE_MODELS:
        vehicle_class = "coupe"
    else:
        type_key = key_text(vehicle_type)
        if type_key == "truck":
            vehicle_class = "truck"
        elif type_key == "multipurpose passenger vehicle (mpv)":
            vehicle_class = "suv"
        else:
            vehicle_class = "sedan"

    if vehicle_class not in CANONICAL_CLASSES:
        raise ValueError(f"Unsupported customer vehicle class: {vehicle_class}")
    return vehicle_class, PRICING_BY_CLASS[vehicle_class]


def build_snapshot(year: int, cache_dir: Path, refresh_cache: bool, sleep: float) -> list[dict[str, str]]:
    by_identity: dict[tuple[str, str], dict[str, str]] = {}

    for make in FRONTEND_MAKES:
        nhtsa_rows, error = fetch_nhtsa_models(
            make=make,
            year=year,
            cache_dir=cache_dir,
            sleep_seconds=sleep,
            refresh=refresh_cache,
        )
        if error:
            raise RuntimeError(f"NHTSA vPIC failed for {year} {make}: {error}")

        for item in nhtsa_rows:
            row_make = item.get("Make_Name") or item.get("MakeName") or ""
            if not nhtsa_make_matches(make, row_make):
                continue

            model = (item.get("Model_Name") or item.get("ModelName") or "").strip()
            if not is_customer_facing_model(make, model):
                continue

            vehicle_class, pricing_group = classify_customer_vehicle(
                model,
                item.get("vehicle_type_filter", ""),
            )
            identity = (key_text(make), key_text(model))
            candidate = {
                "year": str(year),
                "make": make,
                "model": model,
                "vehicle_class": vehicle_class,
                "pricing_group": pricing_group,
                "classification_source": f"nhtsa_vpic_{year}_reviewed",
                "review_status": "ok",
                "is_commercial": "false",
            }

            previous = by_identity.get(identity)
            if previous and previous != candidate:
                raise ValueError(
                    f"Conflicting NHTSA rows for {year} {make} {model}: "
                    f"{previous} vs {candidate}"
                )
            by_identity[identity] = candidate

    return sorted(
        by_identity.values(),
        key=lambda row: (row["make"].lower(), row["model"].lower()),
    )


def read_catalog(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def merge_model_year(
    lookup_path: Path,
    year: int,
    snapshot_rows: list[dict[str, str]],
    corrections_dir: Path,
    output_path: Path,
) -> dict[str, int]:
    fieldnames, current_rows = read_catalog(lookup_path)
    required = {
        "year", "make", "model", "vehicle_class", "pricing_group",
        "classification_source", "review_status", "is_commercial",
    }
    missing = required - set(fieldnames)
    if missing:
        raise ValueError(f"Canonical lookup missing columns: {sorted(missing)}")

    kept_rows = [row for row in current_rows if int(row["year"]) != year]
    merged_rows = kept_rows + [
        {field: row.get(field, "") for field in fieldnames}
        for row in snapshot_rows
    ]
    merged_rows.sort(key=lambda row: (int(row["year"]), row["make"].lower(), row["model"].lower()))

    identities: set[tuple[str, str, str]] = set()
    for row in merged_rows:
        identity = (row["year"], key_text(row["make"]), key_text(row["model"]))
        if identity in identities:
            raise ValueError(f"Duplicate vehicle identity after refresh: {identity}")
        identities.add(identity)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.", suffix=".pre-corrections", dir=output_path.parent,
        delete=False,
    ) as temporary:
        pre_corrections = Path(temporary.name)

    try:
        write_rows(pre_corrections, fieldnames, merged_rows)
        apply_result = apply_corrections(pre_corrections, corrections_dir, output_path)
    finally:
        pre_corrections.unlink(missing_ok=True)

    return {
        "before_rows": len(current_rows),
        "after_rows": len(merged_rows),
        "year_rows": len(snapshot_rows),
        "correction_keys": apply_result["correction_keys"],
        "correction_changed_rows": apply_result["changed_rows"],
    }


def sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_hosted_sql(
    year: int,
    snapshot_rows: list[dict[str, str]],
    corrections_dir: Path,
) -> str:
    values = ",\n".join(
        "  (" + ", ".join([
            str(year),
            sql_quote(row["make"]),
            sql_quote(row["model"]),
            sql_quote(row["vehicle_class"]),
            sql_quote(row["pricing_group"]),
            sql_quote(row["classification_source"]),
            sql_quote(row["review_status"]),
            "false",
        ]) + ")"
        for row in snapshot_rows
    )

    keep_pairs = ",\n".join(
        f"  ({sql_quote(key_text(row['make']))}, {sql_quote(key_text(row['model']))})"
        for row in snapshot_rows
    )

    correction_sql = []
    for (_make_key, _model_key), correction in sorted(load_corrections(corrections_dir).items()):
        make = correction["make"]
        model = correction["model"]
        assignments = []
        for column in (
            "vehicle_class", "pricing_group", "classification_source",
            "review_status", "is_commercial",
        ):
            value = correction.get(column, "")
            if value == "":
                continue
            if column == "is_commercial":
                assignments.append(f"{column} = {value.lower()}")
            else:
                assignments.append(f"{column} = {sql_quote(value)}")
        correction_sql.append(
            "update public.vehicle_lookup\n"
            f"set {', '.join(assignments)}\n"
            f"where lower(trim(make)) = {sql_quote(key_text(make))}\n"
            f"  and lower(trim(model)) = {sql_quote(key_text(model))};"
        )

    return f"""-- Generated by vehicle-lookup/refresh_vehicle_model_year.py.
-- Customer-facing {year} model-year refresh from NHTSA vPIC with reviewed Prokvik classifications.
-- Exact make matching prevents partial manufacturer contamination.

begin;

with reviewed_rows (
  year, make, model, vehicle_class, pricing_group,
  classification_source, review_status, is_commercial
) as (
values
{values}
)
insert into public.vehicle_lookup (
  year, make, model, vehicle_class, pricing_group,
  classification_source, review_status, is_commercial
)
select * from reviewed_rows
on conflict (year, make, model) do update set
  vehicle_class = excluded.vehicle_class,
  pricing_group = excluded.pricing_group,
  classification_source = excluded.classification_source,
  review_status = excluded.review_status,
  is_commercial = excluded.is_commercial;

-- Remove model-year rows that are no longer in the reviewed current vPIC snapshot.
delete from public.vehicle_lookup
where year = {year}
  and (lower(trim(make)), lower(trim(model))) not in (
values
{keep_pairs}
  );

-- Apply reviewed make/model class clarifications across model years.
{chr(10).join(correction_sql)}

commit;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2027)
    parser.add_argument("--lookup", type=Path, default=DEFAULT_LOOKUP)
    parser.add_argument("--corrections-dir", type=Path, default=DEFAULT_CORRECTIONS)
    parser.add_argument("--model-year-dir", type=Path, default=DEFAULT_MODEL_YEAR_DIR)
    parser.add_argument("--cache-dir", type=Path, default=MODULE_DIR / ".nhtsa-cache")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--write", action="store_true", help="Replace canonical CSV after validation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = build_snapshot(args.year, args.cache_dir, args.refresh_cache, args.sleep)
    if not snapshot:
        raise SystemExit(f"No customer-facing NHTSA rows found for {args.year}")

    snapshot_path = args.model_year_dir / f"{args.year}_reviewed.csv"
    sql_path = args.model_year_dir / f"{args.year}_hosted.sql"
    snapshot_fields = [
        "year", "make", "model", "vehicle_class", "pricing_group",
        "classification_source", "review_status", "is_commercial",
    ]
    write_rows(snapshot_path, snapshot_fields, snapshot)
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(
        build_hosted_sql(args.year, snapshot, args.corrections_dir),
        encoding="utf-8",
    )

    target = args.lookup
    with tempfile.NamedTemporaryFile(
        prefix=f".{args.lookup.name}.", suffix=".refresh", dir=args.lookup.parent,
        delete=False,
    ) as temporary:
        merged_path = Path(temporary.name)

    try:
        result = merge_model_year(
            args.lookup, args.year, snapshot, args.corrections_dir, merged_path,
        )
        if args.write:
            merged_path.replace(target)
    finally:
        merged_path.unlink(missing_ok=True)

    print(
        f"Reviewed {result['year_rows']} customer-facing {args.year} rows; "
        f"catalog {result['before_rows']} -> {result['after_rows']} rows; "
        f"{result['correction_changed_rows']} rows received reviewed class corrections."
    )
    print(f"Snapshot: {snapshot_path}")
    print(f"Hosted SQL: {sql_path}")
    if not args.write:
        print("Canonical CSV not changed (pass --write to replace it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
