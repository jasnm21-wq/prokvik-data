# Manufacturer specification library

Phase 1 adds source-specific evidence to the existing Prokvik automotive film catalog. The canonical identifier remains the pair of columns `brand` and `product_line` in the parent catalog. Product aliases and active versus legacy identities remain defined there. This library does not update application behavior.

## Build the review

Run these commands from the repository root. Generation requires Python 3.10 or newer and uses only the standard library.

```bash
python3 film-catalog/specification-library/build_library.py \
  --originals "$HOME/Documents/Film Specs" \
  --output "$HOME/.local/share/prokvik/film-spec-library/phase1"
firefox "$HOME/.local/share/prokvik/film-spec-library/phase1/review.html"
```

Omit `--originals` when the documents are unavailable. The build keeps source references and verifies the catalog relationships, but opening local source files and checking their exact bytes requires the source collection.

The build creates a self-contained browser viewer, normalized JSON, and coverage CSVs for every registered manufacturer and catalog product. A shade count includes a reported shade label even when the source has not published measured VLT. The product report includes a separate count of shades with measurements. “Missing numeric fields” includes fields that a source may not meaningfully publish. A manufacturer-level warranty record is a reference until the issuing document identifies the relevant product, region, conditions, and installer.

## Inputs and provenance

- `local-sources.json` inventories every supplied file by relative path, SHA-256, page count, manufacturer, product references, and revision where available. Identical byte content has a single entry and retains all paths. Web references have independently tracked URLs and downloaded PDFs have SHA-256 fingerprints.
- `parsed-tables.json` and `parsed-public-tables.json` are committed snapshots extracted from fingerprinted PDFs. `reviewed-tables.txt` contains rows directly transcribed from image-based or web tables. `row-notes.json` adds source-specific footnotes and explicit withholding decisions. A local item marked “Mapped reference” has a reviewed identity and source location. The full numeric table has not been independently re-extracted.
- `methods.json` documents measurement basis, substrate, test standard, known wavelengths, and uncertainties. Each exported row has a source and method. Browser comparisons retain those conditions. The library does not treat publication-only IR headings as interchangeable with standardized metrics.
- `manufacturer-research.tsv` covers all recognized manufacturers, including missing and inaccessible documentation. `supplemental-sources.tsv` records additional official documents, including architectural discoveries. Architectural sources do not enter the automotive data export as numeric film rows.
- `product-facts.tsv` and `warranties.tsv` capture construction, ordering evidence, benefit summaries, duration, market and restrictions. Explicit nonnumeric findings remain visible even when performance data is absent.
- Earlier `automotive_film_specs.csv` rows retain their published readings, source, status and wording. They are labeled as inherited evidence. A published list of available shades is not treated as measured VLT.

## Reproduce extraction

Run Poppler, ImageMagick, Tesseract and `file` locally only against read-only inputs. Extraction writes PDFs' text, rendered pages and OCR into a separate destination. Inspect the rendered tables and footnotes before adding or changing transcribed values.

```bash
python3 film-catalog/specification-library/extract_local.py \
  "$HOME/Documents/Film Specs" /tmp/film-evidence --render-and-ocr

python3 film-catalog/specification-library/capture_tables.py \
  "$HOME/Documents/Film Specs" /tmp/parsed-tables.json
cmp /tmp/parsed-tables.json film-catalog/specification-library/parsed-tables.json
```

To verify the 54 transcribed FormulaOne and LLumar rows against their official PDFs and regenerate the Nexfil snapshot, supply a directory containing those three fingerprinted public PDFs named by source ID (`W-formulaone-chart.pdf`, `W-llumar-chart.pdf`, `W-nexfil-chart.pdf`). The source registry supplies their URLs.

```bash
python3 film-catalog/specification-library/capture_tables.py \
  "$HOME/Documents/Film Specs" /tmp/parsed-tables.json \
  --public-pdfs /path/to/fingerprinted/public-documents \
  --public-output /tmp/parsed-public-tables.json
cmp /tmp/parsed-public-tables.json film-catalog/specification-library/parsed-public-tables.json
python3 -m unittest discover -s film-catalog/specification-library -v
```

## Phase 2 approval boundaries

Select an authoritative, product-specific revision and comparable test basis before surfacing numbers in customer-facing outputs. Review all same-method disagreements, glass and wavelength omissions, printed solar-energy totals outside rounding tolerance, and product identity conflicts. Expose only approved fields. Preserve historical data in the reference library and keep manufacturer warranties distinct from a shop's own warranty.

Current open questions include the different Supreme IR results in Johnson's two charts, Global's QDP Ceramic Charcoal values with unknown comparability, the STEK ICY construction conflict, UCA's unusual printed wavelength unit, conflicting ASWF Classic Pro and XPEL transfer wording, and several unverified roll sizes. The manufacturer and product coverage reports record remaining access and data limitations.
