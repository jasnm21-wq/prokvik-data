# Prokvik Data

Generated/import-review data files for Prokvik.

## Vehicle Lookup

Use:

vehicle-lookup/vehicle_lookup_import_ready.csv

Known good state:
- 8126 lines
- 0 needs_review
- 0 unknown rows

This file was cleaned and is ready for Supabase import.

## Film Catalog

Current film catalog files are review-stage files from the film crawler/import workflow.

Files:
- film-catalog/build_film_catalog.py
- film-catalog/film_sources.csv
- film-catalog/film_sources_full_backup.csv
- film-catalog/film_line_urls_review.csv
- film-catalog/film_names_review.csv
- film-catalog/film_catalog_review.csv

Important:
- Do not import film_catalog_review.csv blindly.
- Review rows marked needs_review before importing into Supabase.
- Keep film_sources_full_backup.csv as the crawler source backup.
