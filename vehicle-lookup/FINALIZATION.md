# Vehicle lookup finalization and annual model-year refresh

The canonical customer-facing catalog is `vehicle-lookup/vehicle_lookup_import_ready.csv`.

Prokvik exposes exactly five vehicle classes and matching pricing groups:

| vehicle_class | pricing_group | Customer meaning |
| --- | --- | --- |
| `coupe` | `Coupe` | Two-door cars |
| `sedan` | `Sedan` | Four-door cars and other passenger cars that are not SUVs/trucks/vans |
| `suv` | `SUV` | Crossovers and SUVs |
| `truck` | `Truck` | Customer-serviceable pickup trucks |
| `van` | `Van` | Customer-serviceable vans/minivans |

Reviewed make/model corrections live under:

- `vehicle-lookup/corrections/*.csv` for the original correction gate.
- `vehicle-lookup/classification-corrections/*.csv` for reviewed customer-facing class clarifications.

## 2027 refresh

The reviewed 2027 source snapshot is `vehicle-lookup/model-years/2027_reviewed.csv`, and the idempotent hosted database sync is `vehicle-lookup/model-years/2027_hosted.sql`.

The September 5, 2026 refresh uses live NHTSA vPIC model-year data but does **not** import raw vPIC output directly. The refresh pipeline:

1. Requires an exact normalized NHTSA manufacturer match. This prevents partial-name contamination such as `Ford` matching `Stanford Customs`, `Mini` matching `Mini Big Trucks`, or `Land Rover` matching `Land Rover Santana`.
2. Excludes obvious commercial/heavy-only vehicles while retaining normal shop vehicles such as F-150/F-250/F-350, Silverado/Sierra, Ram pickups, Tacoma/Tundra, Transit, Sprinter, Express/Savana, and ProMaster.
3. Normalizes customer-facing model labels where NHTSA exposes internal/type suffixes.
4. Applies reviewed vehicle-class clarifications before the model-year snapshot is finalized.
5. Replaces only the target model year in the canonical CSV and preserves all other model-year rows and their ordering.
6. Rejects duplicate `(year, make, model)` identities.

The reviewed 2027 snapshot contains **306 customer-facing rows**. Replacing the previous incomplete/stale 2027 rows brings the canonical catalog to **8,871 rows**.

To regenerate the reviewed 2027 artifacts from current vPIC data:

```bash
python vehicle-lookup/finalize_2027_vehicle_refresh.py \
  --refresh-cache \
  --write
```

Then run the complete vehicle lookup validation suite:

```bash
python vehicle-lookup/validate_vehicle_lookup_corrections.py
python -m unittest discover \
  -s vehicle-lookup \
  -p 'test_*.py' \
  -v
```

Before importing into hosted Supabase, confirm that:

- the reviewed snapshot contains only `coupe`, `sedan`, `suv`, `truck`, and `van`;
- no commercial/heavy-only rows remain;
- exact-manufacturer contamination is absent;
- customer-facing aliases are applied;
- the correction validator reports zero pending original correction changes;
- the unit tests pass;
- the generated hosted SQL is reviewed together with the snapshot and canonical CSV.

## Correction-only finalization

For an ordinary reviewed correction that does not add/delete model-year rows, run:

```bash
python vehicle-lookup/validate_vehicle_lookup_corrections.py --write
python -m unittest discover \
  -s vehicle-lookup \
  -p 'test_vehicle_lookup_corrections.py'
```

The correction validator writes its temporary file beside the canonical CSV so the final replacement remains atomic on Linux filesystems. It compares every canonical row before and after correction and rejects changes to row count, column order, year/make/model identity, protected columns, or any make/model not present in the original reviewed correction manifest.

Commit the resulting canonical CSV together with the reviewed manifests, model-year snapshot/SQL (when applicable), and tests. Do not import regenerated data into hosted Supabase until finalization passes.
