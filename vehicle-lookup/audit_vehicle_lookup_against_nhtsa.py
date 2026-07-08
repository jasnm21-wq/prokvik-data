#!/usr/bin/env python3
"""
Audit Prokvik vehicle lookup rows against NHTSA vPIC by make + model year.

This does not modify vehicle_lookup_import_ready.csv.
It writes review reports under vehicle-lookup/audit-output/.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


FRONTEND_MAKES = [
    "Acura", "Alfa Romeo", "Audi", "Bentley", "BMW", "Buick", "Cadillac",
    "Chevrolet", "Chrysler", "Dodge", "Fiat", "Ford", "Genesis", "GMC",
    "Honda", "Hyundai", "Infiniti", "Jaguar", "Jeep", "Kia", "Land Rover",
    "Lexus", "Lincoln", "Lucid", "Mazda", "Mercedes-Benz", "Mini",
    "Mitsubishi", "Nissan", "Polestar", "Porsche", "Ram", "Rivian",
    "Subaru", "Tesla", "Toyota", "Volkswagen", "Volvo",
]

ADDITIONAL_REVIEW_MAKES = [
    "Aston Martin", "Ferrari", "Hummer", "Isuzu", "Lamborghini", "Lotus",
    "Maserati", "Maybach", "McLaren", "Mercury", "Oldsmobile", "Pontiac",
    "Rolls-Royce", "Saab", "Saturn", "Scion", "Smart", "Suzuki",
]

# Customer-facing booking should only use normal shop-relevant vehicle types.
# This filters out most motorcycles, powersports, buses, trailers, and incomplete chassis rows.
ALLOWED_NHTSA_VEHICLE_TYPES = [
    "Passenger Car",
    "Multipurpose Passenger Vehicle (MPV)",
    "Truck",
]


def norm_make(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def norm_model(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"\bhybrid\b|\bphev\b|\bev\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_model(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm_model(value))


def is_likely_commercial_model(make: str, model: str) -> bool:
    raw = f"{make} {model}".lower()

    commercial_terms = [
        "cab chassis", "chassis cab", "cutaway", "incomplete", "strip chassis",
        "low cab forward", "conventional", "tractor", "school bus", "shuttle bus",
        "step van", "box truck", "straight truck",
    ]

    commercial_models = [
        "f-450", "f450", "f-550", "f550", "f-650", "f650", "f-750", "f750",
        "silverado 4500", "silverado 5500", "silverado 6500",
        "ram 4500", "ram 5500",
        "npr", "nqr", "nrr", "fuso", "ecanter",
        "hino", "lcf",
        "vn", "vnl", "vnr", "vhd", "vah", "vt", "fe", "wg", "wheb", "wah",
    ]

    return any(term in raw for term in commercial_terms) or any(model_key in raw for model_key in commercial_models)


def guess_vehicle_class(make: str, model: str) -> tuple[str, str]:
    raw = f"{make} {model}".lower()
    model_key = compact_model(model)

    exact_sedan_models = {
        "ilx", "tlx", "rlx", "cl", "tsx", "integra", "giulia952", "giulia",
        "air", "model3", "models", "etron", "etrongt", "rsetrongt", "setrongt",
    }
    exact_coupe_models = {
        "4c", "8ccompetizionespider", "rsx", "nsx", "roadster",
    }
    exact_suv_models = {
        "adx", "mdx", "rdx", "zdx", "stelvio", "tonale", "gravity",
        "modelx", "modely",
    }

    if model_key in exact_sedan_models:
        return "sedan", "Sedan"
    if model_key in exact_coupe_models:
        return "coupe", "Coupe"
    if model_key in exact_suv_models:
        return "suv", "SUV"

    truck_patterns = [
        "f-150", "f150", "f-250", "f250", "f-350", "f350", "silverado",
        "sierra", "ram 1500", "ram 2500", "ram 3500", "tacoma", "tundra",
        "frontier", "titan", "colorado", "canyon", "ranger", "maverick",
        "ridgeline", "gladiator", "santa cruz", "cybertruck",
    ]
    van_patterns = [
        "sienna", "odyssey", "pacifica", "voyager", "caravan", "carnival",
        "transit", "sprinter", "metris", "promaster", "savana", "express",
        "nv200", "nv cargo", "nv passenger", "e-150", "e-250", "e-350",
    ]
    suv_patterns = [
        "gravity", "model x", "model y", "rz", "ux", "nx", "rx", "gx", "lx",
        "zdx", "rdx", "mdx", "adx", "q3", "q4", "q5", "q6", "q7", "q8",
        "x1", "x2", "x3", "x4", "x5", "x6", "x7", "ix", "xm", "enclave",
        "encore", "envision", "envista", "escalade", "lyriq", "optiq",
        "vistiq", "equinox", "suburban", "tahoe", "traverse", "trailblazer",
        "trax", "blazer", "pilot", "passport", "cr-v", "crv", "hr-v", "hrv",
        "wrangler", "cherokee", "compass", "renegade", "wagoneer", "soul",
        "sorento", "sportage", "telluride", "seltos", "ev6", "ev9", "navigator",
        "aviator", "nautilus", "corsair", "cx-", "outlander", "rogue", "murano",
        "armada", "pathfinder", "kicks", "ariya", "macan", "cayenne", "ascent",
        "forester", "outback", "crosstrek", "rav4", "highlander", "venza",
        "sequoia", "4runner", "land cruiser", "corolla cross", "bz4x",
        "tiguan", "atlas", "id.4", "taos", "id. buzz", "xc", "ex30", "ex90",
        "ec40", "ex40", "bronco", "escape", "edge", "explorer", "expedition",
        "terrain", "acadia", "yukon", "santa fe", "tucson", "palisade",
    ]
    coupe_patterns = [
        "corvette", "camaro", "mustang", "miata", "mx-5", "brz", "gr86",
        "supra", "911", "boxster", "cayman", "z4", "m2", "m4", "amg gt",
        "rc", "lc", "nsx", "roadster",
    ]

    if any(p in raw for p in truck_patterns):
        return "truck", "Truck"
    if any(p in raw for p in van_patterns):
        return "van", "Van"
    if any(p in raw for p in suv_patterns):
        return "suv", "SUV"
    if any(p in raw for p in coupe_patterns):
        return "coupe", "Coupe"
    return "sedan", "Sedan"


def load_local_lookup(csv_path: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing CSV: {csv_path}")

    rows = []
    by_make_year = defaultdict(set)
    display_by_make_year = defaultdict(set)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"year", "make", "model"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {sorted(missing)}")

        for row in reader:
            try:
                year = int(row["year"])
            except (TypeError, ValueError):
                continue

            make_key = norm_make(row.get("make", ""))
            model = row.get("model", "")
            model_key = compact_model(model)
            if not make_key or not model_key:
                continue

            rows.append(row)
            by_make_year[(year, make_key)].add(model_key)
            display_by_make_year[(year, make_key)].add(model)

    return rows, by_make_year, display_by_make_year


def nhtsa_cache_path(cache_dir: Path, make: str, year: int, vehicle_type: str) -> Path:
    safe_make = re.sub(r"[^a-z0-9]+", "_", norm_make(make)).strip("_")
    safe_type = re.sub(r"[^a-z0-9]+", "_", norm_make(vehicle_type)).strip("_")
    return cache_dir / "typed" / f"{year}_{safe_make}_{safe_type}.json"


def fetch_nhtsa_models_for_type(
    make: str,
    year: int,
    vehicle_type: str,
    cache_dir: Path,
    sleep_seconds: float,
    refresh: bool,
):
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = nhtsa_cache_path(cache_dir, make, year, vehicle_type)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not refresh:
        with cache_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("Results", []), None

    url = (
        "https://vpic.nhtsa.dot.gov/api/vehicles/"
        f"GetModelsForMakeYear/make/{quote(make)}/modelyear/{year}/"
        f"vehicletype/{quote(vehicle_type)}?format=json"
    )

    try:
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        return payload.get("Results", []), None
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return [], str(exc)


def fetch_nhtsa_models(make: str, year: int, cache_dir: Path, sleep_seconds: float, refresh: bool):
    merged = {}
    errors = []

    for vehicle_type in ALLOWED_NHTSA_VEHICLE_TYPES:
        rows, error = fetch_nhtsa_models_for_type(
            make=make,
            year=year,
            vehicle_type=vehicle_type,
            cache_dir=cache_dir,
            sleep_seconds=sleep_seconds,
            refresh=refresh,
        )
        if error:
            errors.append(f"{vehicle_type}: {error}")
            continue

        for row in rows:
            model_name = row.get("Model_Name") or row.get("ModelName") or ""
            model_id = row.get("Model_ID", "")
            key = f"{model_id}:{compact_model(model_name)}"
            if key and key not in merged:
                row = dict(row)
                row["vehicle_type_filter"] = vehicle_type
                merged[key] = row

    return list(merged.values()), "; ".join(errors) if errors else None


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def parse_args() -> argparse.Namespace:
    current_year = datetime.now().year
    parser = argparse.ArgumentParser(description="Audit vehicle lookup rows against NHTSA vPIC")
    parser.add_argument("--csv", default="vehicle-lookup/vehicle_lookup_import_ready.csv")
    parser.add_argument("--output-dir", default="vehicle-lookup/audit-output")
    parser.add_argument("--cache-dir", default="vehicle-lookup/.nhtsa-cache")
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=current_year + 1)
    parser.add_argument("--makes", default="", help="Comma-separated make list. Defaults to frontend selector makes.")
    parser.add_argument("--include-candidate-makes", action="store_true", help="Also check common discontinued/luxury makes not in the selector.")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv)
    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir)

    rows, local_models, local_display_models = load_local_lookup(csv_path)

    if args.makes.strip():
        makes = [m.strip() for m in args.makes.split(",") if m.strip()]
    else:
        makes = list(FRONTEND_MAKES)

    if args.include_candidate_makes:
        makes = sorted(set(makes) | set(ADDITIONAL_REVIEW_MAKES), key=str.lower)

    selector_make_keys = {norm_make(m) for m in FRONTEND_MAKES}

    summary_rows = []
    missing_make_years = []
    missing_models = []
    extra_local_models = []
    missing_selector_makes_by_year = []
    api_errors = []

    for make in makes:
        make_key = norm_make(make)

        for year in range(args.start_year, args.end_year + 1):
            nhtsa_rows, error = fetch_nhtsa_models(
                make=make,
                year=year,
                cache_dir=cache_dir,
                sleep_seconds=args.sleep,
                refresh=args.refresh_cache,
            )

            if error:
                api_errors.append({"year": year, "make": make, "error": error})
                continue

            nhtsa_models = {}
            for item in nhtsa_rows:
                model_name = item.get("Model_Name") or item.get("ModelName") or ""
                model_key = compact_model(model_name)
                if model_key:
                    nhtsa_models[model_key] = item

            local_set = local_models.get((year, make_key), set())
            local_display = sorted(local_display_models.get((year, make_key), set()))
            nhtsa_model_names = sorted(
                (item.get("Model_Name") or item.get("ModelName") or "").strip()
                for item in nhtsa_models.values()
                if (item.get("Model_Name") or item.get("ModelName") or "").strip()
            )

            summary_rows.append({
                "year": year,
                "make": make,
                "make_in_selector": "yes" if make_key in selector_make_keys else "no",
                "local_model_count": len(local_set),
                "nhtsa_model_count": len(nhtsa_models),
                "missing_model_count": len([k for k in nhtsa_models if k not in local_set]),
                "extra_local_model_count": len([k for k in local_set if k not in nhtsa_models]) if nhtsa_models else "",
            })

            if nhtsa_models and not local_set:
                missing_make_years.append({
                    "year": year,
                    "make": make,
                    "make_in_selector": "yes" if make_key in selector_make_keys else "no",
                    "nhtsa_model_count": len(nhtsa_models),
                    "nhtsa_models_sample": "; ".join(nhtsa_model_names[:25]),
                })

                if make_key in selector_make_keys:
                    missing_selector_makes_by_year.append({
                        "year": year,
                        "make": make,
                        "nhtsa_model_count": len(nhtsa_models),
                        "nhtsa_models_sample": "; ".join(nhtsa_model_names[:25]),
                    })

            for model_key, item in sorted(nhtsa_models.items(), key=lambda kv: (kv[1].get("Model_Name") or kv[1].get("ModelName") or "")):
                if model_key in local_set:
                    continue
                model_name = item.get("Model_Name") or item.get("ModelName") or ""
                if is_likely_commercial_model(make, model_name):
                    continue
                guessed_class, guessed_group = guess_vehicle_class(make, model_name)
                missing_models.append({
                    "year": year,
                    "make": make,
                    "make_in_selector": "yes" if make_key in selector_make_keys else "no",
                    "nhtsa_make_name": item.get("Make_Name", ""),
                    "nhtsa_model_id": item.get("Model_ID", ""),
                    "nhtsa_model_name": model_name,
                    "local_models_for_make_year": "; ".join(local_display[:25]),
                    "suggested_vehicle_class": guessed_class,
                    "suggested_pricing_group": guessed_group,
                    "review_status": "needs_review",
                    "note": "Review before importing. NHTSA names can differ from shop-friendly names.",
                })

            for local_key in sorted(local_set):
                if nhtsa_models and local_key not in nhtsa_models:
                    extra_local_models.append({
                        "year": year,
                        "make": make,
                        "make_in_selector": "yes" if make_key in selector_make_keys else "no",
                        "local_model_key": local_key,
                        "local_models_for_make_year": "; ".join(local_display[:25]),
                        "nhtsa_models_sample": "; ".join(nhtsa_model_names[:25]),
                        "note": "May be a name variant, old NHTSA row, or manually added commercial/legacy row.",
                    })

    write_csv(output_dir / "summary_by_make_year.csv", summary_rows, [
        "year", "make", "make_in_selector", "local_model_count", "nhtsa_model_count",
        "missing_model_count", "extra_local_model_count",
    ])
    write_csv(output_dir / "missing_make_years.csv", missing_make_years, [
        "year", "make", "make_in_selector", "nhtsa_model_count", "nhtsa_models_sample",
    ])
    write_csv(output_dir / "missing_models.csv", missing_models, [
        "year", "make", "make_in_selector", "nhtsa_make_name", "nhtsa_model_id",
        "nhtsa_model_name", "local_models_for_make_year", "suggested_vehicle_class",
        "suggested_pricing_group", "review_status", "note",
    ])
    write_csv(output_dir / "extra_local_models.csv", extra_local_models, [
        "year", "make", "make_in_selector", "local_model_key", "local_models_for_make_year",
        "nhtsa_models_sample", "note",
    ])
    write_csv(output_dir / "missing_selector_makes_by_year.csv", missing_selector_makes_by_year, [
        "year", "make", "nhtsa_model_count", "nhtsa_models_sample",
    ])
    write_csv(output_dir / "api_errors.csv", api_errors, ["year", "make", "error"])

    summary = {
        "csv_rows": len(rows),
        "audited_make_count": len(makes),
        "year_range": f"{args.start_year}-{args.end_year}",
        "missing_make_year_count": len(missing_make_years),
        "missing_model_count": len(missing_models),
        "extra_local_model_count": len(extra_local_models),
        "missing_selector_make_year_count": len(missing_selector_makes_by_year),
        "api_error_count": len(api_errors),
        "output_dir": str(output_dir),
    }

    (output_dir / "audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("✅ Vehicle lookup audit complete")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print()
    print("Review these files:")
    print(f"- {output_dir / 'missing_make_years.csv'}")
    print(f"- {output_dir / 'missing_models.csv'}")
    print(f"- {output_dir / 'missing_selector_makes_by_year.csv'}")
    print(f"- {output_dir / 'extra_local_models.csv'}")
    print(f"- {output_dir / 'api_errors.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
