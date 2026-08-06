#!/usr/bin/env python3
"""Validate that reviewed vehicle corrections change only approved catalog rows."""

from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path

from apply_vehicle_lookup_corrections import (
    CORRECTABLE_COLUMNS,
    DEFAULT_CORRECTIONS_DIR,
    DEFAULT_LOOKUP,
    apply_corrections,
    load_corrections,
    normalize_key,
)

IDENTITY_COLUMNS = ("year", "make", "model")


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def row_identity(row: dict[str, str]) -> tuple[str, str, str]:
    return tuple(
        str(row.get(column, "")).strip()
        for column in IDENTITY_COLUMNS
    )


def validate_delta(
    before_path: Path,
    after_path: Path,
    corrections_dir: Path,
) -> dict[str, int]:
    before_fields, before_rows = read_rows(before_path)
    after_fields, after_rows = read_rows(after_path)

    if before_fields != after_fields:
        raise ValueError("Correction changed the canonical CSV column contract")
    if len(before_rows) != len(after_rows):
        raise ValueError(
            f"Correction changed row count: {len(before_rows)} -> {len(after_rows)}"
        )

    corrections = load_corrections(corrections_dir)
    changed_rows = 0
    observed_keys: set[tuple[str, str]] = set()

    for index, (before, after) in enumerate(
        zip(before_rows, after_rows, strict=True),
    ):
        before_identity = row_identity(before)
        after_identity = row_identity(after)
        if before_identity != after_identity:
            raise ValueError(
                f"Correction changed row identity at line {index + 2}: "
                f"{before_identity} -> {after_identity}"
            )

        changed_columns = {
            column
            for column in before_fields
            if before.get(column, "") != after.get(column, "")
        }
        if not changed_columns:
            continue

        changed_rows += 1
        key = (
            normalize_key(before.get("make", "")),
            normalize_key(before.get("model", "")),
        )
        observed_keys.add(key)

        if key not in corrections:
            raise ValueError(
                "Unexpected catalog change outside reviewed corrections: "
                f"{before_identity} changed {sorted(changed_columns)}"
            )
        if not changed_columns.issubset(CORRECTABLE_COLUMNS):
            raise ValueError(
                f"Correction changed protected columns for {before_identity}: "
                f"{sorted(changed_columns)}"
            )

        correction = corrections[key]
        for column in CORRECTABLE_COLUMNS:
            expected = correction.get(column, "")
            if expected and after.get(column, "") != expected:
                raise ValueError(
                    f"Correction did not set {before_identity} "
                    f"{column} to {expected!r}"
                )

    catalog_keys = {
        (
            normalize_key(row.get("make", "")),
            normalize_key(row.get("model", "")),
        )
        for row in before_rows
    }
    missing_catalog_keys = set(corrections) - catalog_keys
    if missing_catalog_keys:
        formatted = ", ".join(
            f"{make} {model}"
            for make, model in sorted(missing_catalog_keys)
        )
        raise ValueError(
            f"Reviewed corrections are absent from the catalog: {formatted}"
        )

    already_correct_keys = set(corrections) - observed_keys

    return {
        "total_rows": len(before_rows),
        "changed_rows": changed_rows,
        "correction_keys": len(corrections),
        "already_correct_keys": len(already_correct_keys),
    }


def regenerate_and_validate(
    lookup_path: Path,
    corrections_dir: Path,
    write: bool = False,
) -> dict[str, int]:
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / lookup_path.name
        apply_result = apply_corrections(
            lookup_path,
            corrections_dir,
            output_path,
        )
        validation = validate_delta(
            lookup_path,
            output_path,
            corrections_dir,
        )

        if write:
            output_path.replace(lookup_path)

    return {**apply_result, **validation}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookup", type=Path, default=DEFAULT_LOOKUP)
    parser.add_argument(
        "--corrections-dir",
        type=Path,
        default=DEFAULT_CORRECTIONS_DIR,
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically replace the canonical CSV after the complete delta validates.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = regenerate_and_validate(
        args.lookup,
        args.corrections_dir,
        write=args.write,
    )
    action = "updated" if args.write else "validated"
    print(
        f"Full catalog {action}: {result['total_rows']} rows, "
        f"{result['changed_rows']} changed rows, "
        f"{result['correction_keys']} reviewed model corrections, "
        f"{result['already_correct_keys']} already-correct model keys."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
