# Prokvik Automotive Film Catalog

## Purpose

`automotive_film_catalog.csv` is the authoritative source for known automotive
film product lines and their suggested AI film categories.

The exact film product and AI category are separate:

- `product_line`: the product selected and sold by the shop
- `canonical_film_type`: Prokvik's suggested category for AI matching and
  ordered pricing displays

The shop may override the suggested category in its tenant pricing. The saved
tenant pricing value remains authoritative for AI quoting.

## Controlled categories

1. Dyed
2. Carbon
3. Metalized
4. Ceramic
5. Super Ceramic
6. Crystalline

`Super Ceramic` is a Prokvik premium ceramic sales category. It does not claim
that the manufacturer uses that exact phrase.

## Unknown products

A product absent from the verified catalog must not be guessed from its name.
The shop must select the AI film category manually before the row can be used
for automatic AI quoting.

## Brand registry

`automotive_film_brands.csv` records both mapped brands and brands awaiting
product-level review.

Rows marked `needs_product_review` are an internal research backlog. They must
not create automatic product classifications.

## Historical safety

Catalog updates do not rewrite historical jobs, proposals, invoices, pricing
snapshots, signed documents, or warranties.
