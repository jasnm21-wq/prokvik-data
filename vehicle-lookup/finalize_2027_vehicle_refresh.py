#!/usr/bin/env python3
"""Generate and finalize the reviewed 2027 Prokvik vehicle catalog."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from apply_vehicle_lookup_corrections import load_corrections, normalize_key
from refresh_vehicle_model_year import (
    DEFAULT_LOOKUP,
    DEFAULT_MODEL_YEAR_DIR,
    build_hosted_sql,
    build_snapshot,
    merge_model_year,
    write_rows,
)


MODULE_DIR = Path(__file__).parent
BASE_CORRECTIONS = MODULE_DIR / "corrections"
CLASS_CORRECTIONS = MODULE_DIR / "classification-corrections"

# vPIC can contain exact-make rows that are technically registered data but are not
# useful customer-facing production choices for Prokvik's shop selector.
EXCLUDED_IDENTITIES = {
    ("ford", "'34"),
}

# Keep customer-facing model labels clean instead of exposing NHTSA platform/type
# suffixes that customers do not normally use when identifying their vehicle.
MODEL_ALIASES = {
    ("alfa romeo", "giulia (952)"): "Giulia",
    ("nissan", "ariya mpv"): "Ariya",
    ("nissan", "kicks mpv"): "Kicks",
    ("toyota", "prius prime (phev)"): "Prius Prime",
    ("toyota", "rav4 prime (phev)"): "RAV4 Prime",
}


def combined_corrections_dir(root: Path) -> Path:
    combined = root / "combined-corrections"
    combined.mkdir(parents=True, exist_ok=True)
    for source_dir in (BASE_CORRECTIONS, CLASS_CORRECTIONS):
        for path in sorted(source_dir.glob("*.csv")):
            target = combined / f"{source_dir.name}__{path.name}"
            shutil.copyfile(path, target)
    return combined


def review_snapshot(
    snapshot: list[dict[str, str]],
    corrections_dir: Path,
) -> list[dict[str, str]]:
    corrections = load_corrections(corrections_dir)
    reviewed: dict[tuple[str, str], dict[str, str]] = {}

    for source in snapshot:
        row = dict(source)
        raw_identity = (
            normalize_key(row["make"]),
            normalize_key(row["model"]),
        )
        if raw_identity in EXCLUDED_IDENTITIES:
            continue

        alias = MODEL_ALIASES.get(raw_identity)
        if alias:
            row["model"] = alias

        identity = (
            normalize_key(row["make"]),
            normalize_key(row["model"]),
        )
        correction = corrections.get(identity)
        if correction:
            for column in (
                "vehicle_class",
                "pricing_group",
                "classification_source",
                "review_status",
                "is_commercial",
            ):
                value = correction.get(column, "")
                if value:
                    row[column] = value

        if identity in reviewed:
            raise ValueError(
                f"Duplicate reviewed 2027 identity after normalization: {identity}"
            )
        reviewed[identity] = row

    return sorted(
        reviewed.values(),
        key=lambda row: (row["make"].lower(), row["model"].lower()),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookup", type=Path, default=DEFAULT_LOOKUP)
    parser.add_argument("--model-year-dir", type=Path, default=DEFAULT_MODEL_YEAR_DIR)
    parser.add_argument("--cache-dir", type=Path, default=MODULE_DIR / ".nhtsa-cache")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    year = 2027
    raw_snapshot = build_snapshot(year, args.cache_dir, args.refresh_cache, args.sleep)
    if not raw_snapshot:
        raise SystemExit("No reviewed 2027 vehicle rows were generated")

    snapshot_fields = [
        "year", "make", "model", "vehicle_class", "pricing_group",
        "classification_source", "review_status", "is_commercial",
    ]
    snapshot_path = args.model_year_dir / "2027_reviewed.csv"
    sql_path = args.model_year_dir / "2027_hosted.sql"

    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        combined = combined_corrections_dir(temp_root)
        snapshot = review_snapshot(raw_snapshot, combined)
        write_rows(snapshot_path, snapshot_fields, snapshot)

        merged = temp_root / "vehicle_lookup_import_ready.csv"
        result = merge_model_year(
            args.lookup,
            year,
            snapshot,
            combined,
            merged,
        )
        sql_path.parent.mkdir(parents=True, exist_ok=True)
        sql_path.write_text(
            build_hosted_sql(year, snapshot, combined),
            encoding="utf-8",
        )
        if args.write:
            merged.replace(args.lookup)

    print(
        f"2027 finalized: {result['year_rows']} customer-facing rows; "
        f"catalog {result['before_rows']} -> {result['after_rows']} rows; "
        f"{result['correction_changed_rows']} rows corrected from reviewed manifests."
    )
    print(f"Snapshot: {snapshot_path}")
    print(f"Hosted SQL: {sql_path}")
    if not args.write:
        print("Canonical CSV was not replaced; pass --write to finalize it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
