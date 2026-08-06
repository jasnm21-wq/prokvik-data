#!/usr/bin/env python3
"""Apply reviewed make/model corrections to the canonical vehicle lookup CSV."""

from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path


DEFAULT_LOOKUP = Path(__file__).with_name("vehicle_lookup_import_ready.csv")
DEFAULT_CORRECTIONS_DIR = Path(__file__).with_name("corrections")
CORRECTABLE_COLUMNS = (
    "vehicle_class",
    "pricing_group",
    "classification_source",
    "review_status",
    "is_commercial",
)


def normalize_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def load_corrections(corrections_dir: Path) -> dict[tuple[str, str], dict[str, str]]:
    corrections: dict[tuple[str, str], dict[str, str]] = {}

    for path in sorted(corrections_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"make", "model", "vehicle_class", "pricing_group"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{path} is missing columns: {sorted(missing)}")

            for row in reader:
                key = (
                    normalize_key(row.get("make", "")),
                    normalize_key(row.get("model", "")),
                )
                if not all(key):
                    raise ValueError(
                        f"{path} contains a correction without make/model: {row}"
                    )
                if key in corrections:
                    raise ValueError(
                        f"Duplicate vehicle correction for {key[0]} {key[1]}"
                    )
                corrections[key] = row

    if not corrections:
        raise ValueError(f"No correction CSV files found under {corrections_dir}")

    return corrections


def apply_corrections(
    lookup_path: Path,
    corrections_dir: Path,
    output_path: Path,
) -> dict[str, int]:
    corrections = load_corrections(corrections_dir)

    with lookup_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        required = {
            "make",
            "model",
            *CORRECTABLE_COLUMNS,
        }
        missing = required - set(fieldnames)
        if missing:
            raise ValueError(f"{lookup_path} is missing columns: {sorted(missing)}")
        rows = list(reader)

    matched_keys: set[tuple[str, str]] = set()
    changed_rows = 0

    for row in rows:
        key = (
            normalize_key(row.get("make", "")),
            normalize_key(row.get("model", "")),
        )
        correction = corrections.get(key)
        if not correction:
            continue

        matched_keys.add(key)
        row_changed = False

        for column in CORRECTABLE_COLUMNS:
            next_value = correction.get(column, "")
            if next_value != "" and row.get(column, "") != next_value:
                row[column] = next_value
                row_changed = True

        if row_changed:
            changed_rows += 1

    missing_keys = sorted(set(corrections) - matched_keys)
    if missing_keys:
        formatted = ", ".join(
            f"{make} {model}" for make, model in missing_keys
        )
        raise ValueError(
            f"Corrections did not match the canonical lookup: {formatted}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\r\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    return {
        "correction_keys": len(corrections),
        "changed_rows": changed_rows,
        "total_rows": len(rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookup", type=Path, default=DEFAULT_LOOKUP)
    parser.add_argument(
        "--corrections-dir",
        type=Path,
        default=DEFAULT_CORRECTIONS_DIR,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Atomically replace the input lookup after all corrections validate.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.in_place and args.output:
        raise SystemExit("Use either --in-place or --output, not both")

    if args.in_place:
        with tempfile.NamedTemporaryFile(
            prefix=f".{args.lookup.name}.",
            suffix=".tmp",
            dir=args.lookup.parent,
            delete=False,
        ) as temporary:
            output_path = Path(temporary.name)

        try:
            result = apply_corrections(
                args.lookup,
                args.corrections_dir,
                output_path,
            )
            output_path.replace(args.lookup)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        final_path = args.lookup
    else:
        final_path = args.output or args.lookup.with_name(
            f"{args.lookup.stem}_corrected{args.lookup.suffix}"
        )
        result = apply_corrections(
            args.lookup,
            args.corrections_dir,
            final_path,
        )

    print(
        "Applied "
        f"{result['correction_keys']} correction keys to "
        f"{result['changed_rows']} changed rows; wrote "
        f"{result['total_rows']} rows to {final_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
