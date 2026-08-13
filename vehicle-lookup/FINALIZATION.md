# Vehicle lookup correction finalization

Reviewed corrections live under `vehicle-lookup/corrections/*.csv`.

Before committing or importing a regenerated vehicle catalog, run:

```bash
python vehicle-lookup/validate_vehicle_lookup_corrections.py --write
python -m unittest discover \
  -s vehicle-lookup \
  -p 'test_vehicle_lookup_corrections.py'
```

The current canonical catalog contains 8,593 rows. The Infiniti correction changes 46 rows across five reviewed make/model keys before regeneration. After the regenerated CSV is written, a second validation must report zero remaining changes and all five correction keys already correct.

The validator writes its temporary file beside the canonical CSV so the final replacement remains atomic on Linux filesystems. It compares every canonical row before and after correction and rejects changes to row count, column order, year/make/model identity, protected columns, or any make/model not present in a reviewed correction manifest.

Commit the resulting `vehicle-lookup/vehicle_lookup_import_ready.csv` together with the correction manifest and tests. Do not import regenerated data into hosted Supabase until this finalization passes.
