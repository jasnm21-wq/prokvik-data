# Vehicle lookup correction finalization

Reviewed corrections live under `vehicle-lookup/corrections/*.csv`.

Before committing or importing a regenerated vehicle catalog, run:

```bash
python vehicle-lookup/validate_vehicle_lookup_corrections.py --write
python -m unittest vehicle-lookup/test_vehicle_lookup_corrections.py
```

The validator compares every canonical row before and after correction. It rejects changes to row count, column order, year/make/model identity, protected columns, or any make/model not present in a reviewed correction manifest.

Commit the resulting `vehicle-lookup/vehicle_lookup_import_ready.csv` together with the correction manifest and tests. Do not import regenerated data into hosted Supabase until this finalization passes.
