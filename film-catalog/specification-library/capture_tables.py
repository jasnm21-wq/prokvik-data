#!/usr/bin/env python3
"""Extract supported text PDFs and combine directly transcribed image tables.

Only run after checking the chart headers and footnotes against the rendered
page. New or revised PDFs require a new source citation and verification.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
OPTICS = "measured_vlt_pct vlr_exterior_pct vlr_interior_pct uv_rejection tser_pct glare_reduction_pct"
XPEL_FIELDS = (
    "thickness_mil measured_vlt_pct vlr_unspecified_pct tser_pct irer_pct solar_transmittance_pct "
    "solar_reflectance_pct solar_absorbance_pct uv_rejection glare_reduction_pct shading_coefficient irr_pct"
)
STEK_FIELDS = (
    "measured_vlt_pct vlr_unspecified_pct solar_transmittance_pct solar_reflectance_pct "
    "solar_absorbance_pct sirr_pct irer_pct uv_rejection glare_reduction_pct tser_pct"
)


def block(document, brand, series, page, method, fields, rows, **details):
    return {"source": document, "brand": brand, "product_line": series, "page": page, "method": method,
            "fields": fields.split(), "rows": rows, **details}


def three_m(doc, layout, code, series, page, irer_first=False, generation=None):
    fields = "irer_pct irr_pct" if irer_first else "irr_pct irer_pct"
    matches = re.findall(r"^[ \t]*" + re.escape(code) + r" (\d+) +((?:[\d.]+%[ \t]*){8})$", layout, re.M)
    if not matches or len(matches) % 2:
        raise ValueError(f"{doc}: expected two complete substrate tables")
    halfway = len(matches) // 2
    if [shade for shade, _ in matches[:halfway]] != [shade for shade, _ in matches[halfway:]]:
        raise ValueError(f"{doc}: shade lists differ between substrate tables")
    for index, (method, subset) in enumerate(zip(("3m_auto75", "3m_clear89"),
                                                (matches[:halfway], matches[halfway:]))):
        rows = [[shade, *values.split()] for shade, values in subset]
        optics = fields.split()
        irer_idx = 7 + optics.index("irer_pct")
        irr_idx = 7 + optics.index("irr_pct")
        details = {"generation": generation} if generation else {}
        yield block(doc, "3M", series, page, method, OPTICS + " irer_pct",
                    [row[:7] + [row[irer_idx]] for row in rows], **details)
        if index == 0:
            other = [[shade, *values.split()] for shade, values in matches[halfway:]]
            if [[r[0], r[irr_idx]] for r in rows] != [[r[0], r[irr_idx]] for r in other]:
                raise ValueError(f"{doc}: reconcile differing film-with-liner readings")
            yield block(doc, "3M", series, page, "3m_liner", "irr_pct",
                        [[row[0], row[irr_idx]] for row in rows], **details)


def xpel(doc, layout):
    products = {"XR PLUS": "PRIME XR Plus", "XR Black": "PRIME XR Black", "XR Blue": "PRIME XR Blue",
                "HP Black": "PRIME HP", "CS Black": "PRIME CS"}
    out = {}
    for page, text in enumerate(layout.split("\f"), 1):
        for label, shade, value in re.findall(
                r"^\s*(XR PLUS|XR Black|XR Blue|HP Black|CS Black) (\d+) +(.+)$", text, re.M):
            value = re.sub(r"^(\d+(?:\.\d+)?)\s+Mil?\b", r"\1", value)
            out.setdefault((page, products[label]), []).append([str(int(shade)), *value.split()])
    for (page, product), rows in out.items():
        yield block(doc, "XPEL", product, page, "xpel", XPEL_FIELDS, rows)


def stek(doc, layout):
    for product, label in (("VISION 70", "VISION 70S"), ("NEX", "NEX"), ("SMART", "SMART"),
                           ("ACTION", "ACTION"), ("ICY", "ICY")):
        rows = []
        for line in layout.split("\f")[0].splitlines():
            match = re.match(r"^\s*" + re.escape(label) + (r" +(\d+) +(.*)" if label != "VISION 70S" else r"() +(.*)"), line)
            if match and match.group(2).strip():
                rows.append([str(int(match.group(1) or "70")), *re.sub(r"≥\s+", "≥", match.group(2)).split()])
        # The text layer places two labels on their own lines.
        if product in {"SMART", "ACTION"}:
            if product == "SMART":
                match = re.search(r"^[ \t]+([0-9][^\n]*)\n[ \t]*SMART 70[ \t]*$", layout, re.M)
                shade = "70"
            else:
                match = re.search(r"^[ \t]*ACTION 05[ \t]*\n[ \t]*([0-9][^\n]*)$", layout, re.M)
                shade = "5"
            if match and not any(row[0] == shade for row in rows):
                rows.append([shade, *re.sub(r"≥\s+", "≥", match.group(1)).split()])
        if rows:
            yield block(doc, "STEK", product, 1, "stek", STEK_FIELDS, rows)


def uca(doc, layout):
    fields = "measured_vlt_pct tser_pct irr_pct uv_rejection"
    items = {"UCA CARBON": "UCArbon Series", "UCA THERMAL IR": "Thermal IR Series",
             "UCA REDZONE IR": "Redzone IR Series"}
    for label, product in items.items():
        text = re.search(r"^ " + label + r"([^\n]*)\n([^\n]*\n){4}", layout, re.M)[0]
        columns = [re.findall(r"\d+", line) for line in text.strip().splitlines()]
        rows = list(map(list, zip(*columns, strict=True)))
        yield block(doc, "UCA Window Film", product, 1, "uca", fields, rows)


def madico(doc, layout):
    fields = (
        "measured_vlt_pct vlr_unspecified_pct glare_reduction_pct solar_transmittance_pct "
        "solar_reflectance_pct solar_absorbance_pct shading_coefficient shgc u_factor uv_rejection "
        "tser_pct irr_pct irer_pct"
    )
    names = {"NC": "Black Pearl Nano-Ceramic", "HP": "Black Pearl HP", "NR": "Black Pearl Non-Reflective",
             "Wincos": "WINCOS", "Shadow": "Shadow", "Onyx": "Onyx", "Charcool": "Charcool", "GP Max": "GP Max"}
    for page, text in enumerate(layout.split("\f"), 1):
        tables = {}
        for label, shade, values in re.findall(
                r"^(?:Black Pearl®\n)?(NC|HP|NR|Wincos®|Shadow|Onyx®|Charcool®|GP Max)[ \t\n]+"
                r"(\d+) ([^\n]+)$", text, re.M):
            product = names[label.rstrip("®")]
            row = [str(int(shade)), *re.sub(r"≥\s+", "≥", values).split()]
            if product == "Black Pearl Nano-Ceramic" and shade == "10":
                # The printed chart itself reads .0.45. Hold just this cell.
                if row[7] != ".0.45":
                    raise ValueError("Madico NC 10 shading coefficient changed")
                row[7] = "-"
            tables.setdefault(product, []).append(row)
        for product, rows in tables.items():
            yield block(doc, "Madico", product, page, "madico", fields, rows)


def johnson(doc, layout):
    prefixes = {"SMT": "Summit", "SUPR": "Supreme IR", "IR": "InsulatIR",
                "MN": "Marathon", "RN": "Renegade", "RG": "Ray Guard Carbon", "PX": "PlexShade"}
    fields = "measured_vlt_pct tser_pct vlr_unspecified_pct shading_coefficient shgc glare_reduction_pct "
    if doc == "L33":
        fields += "solar_ir_absorption_pct "
    fields += "irer_pct sirr_pct"
    tables = {}
    for prefix, shade, values in re.findall(
            r"^(SMT|SUPR|IR|MN|RN|RG|PX) (\d+) ([^\n]+)$", layout.split("\f")[0], re.M):
        tables.setdefault(prefixes[prefix], []).append([str(int(shade)), *values.split()])
    for product, rows in tables.items():
        yield block(doc, "Johnson Window Films", product, 1, "johnson", fields, rows)


def solarfx(doc, layout):
    fields = (
        "measured_vlt_pct vlr_interior_pct solar_transmittance_pct solar_reflectance_pct "
        "solar_absorbance_pct uv_rejection tser_pct glare_reduction_pct irr_pct"
    )
    rows = [[str(int(shade)), *values.split()] for shade, values in re.findall(
        r"^[ \t]*BLACK FX3 (\d+) +([^\n]+)$", layout, re.M
    )]
    yield block(doc, "SolarFX", "Black FX3 Series", 1, "unknown", fields, rows)


def nexfil(doc, layout):
    labels = {
        "PROFESSIONAL BLACK": "Professional", "PREMIUM BLACK": "Premium",
        "CENTURION": "CENTURION IR30", "NUVO": "NUVO IR55",
        "LUX": "LUX IR80", "ONYVA": "ONYVA IR90",
    }
    fields = (
        "solar_transmittance_pct solar_absorbance_pct solar_reflectance_pct measured_vlt_pct "
        "visible_absorbance_pct vlr_interior_pct vlr_exterior_pct uv_rejection shading_coefficient "
        "irr_pct tser_pct glare_reduction_pct emissivity u_factor"
    )
    tables = {}
    for line in layout.splitlines():
        match = re.match(r"^(" + "|".join(labels) + r")[ \t]+(\d{2}(?:%|\d{2}))[ \t]+(.+)$", line)
        if match:
            shade = str(int(match[2][:2]))
            tables.setdefault(labels[match[1]], []).append([shade, *match[3].split()])
    for product, rows in tables.items():
        yield block(doc, "Nexfil", product, 1, "nexfil", fields, rows)


def verify_eastman_reprints(root, hashes):
    """Reconcile the manually transcribed originals with official PDF text."""
    from build_library import reviewed_tables

    tables = list(reviewed_tables())
    total = 0
    for local, web in (("L56", "W-formulaone-chart"), ("L57", "W-llumar-chart")):
        expected = {(t["product_line"], int(row[0])): row[1:] for t in tables if t["source"] == local for row in t["rows"]}
        names = sorted({x[0] for x in expected})
        pattern = re.compile(r"^[ \t]*(" + "|".join(names) + r") (\d+)\b.*?[ \t]{2,}(\d+(?:[ \t]+>?\d+){6})[ \t]*$")
        pdf = pdf_layout(root, {"id": web, "paths": [web + ".pdf"], "sha256": hashes[web]})
        # Footnote-marked IRX rows span two text lines on the official PDF.
        pdf = re.sub(r"(‡)[ \t]*\n[ \t]+(?=\d+[ \t]+\d+)", r"\1  ", pdf)
        found = {}
        for line in pdf.splitlines():
            if match := pattern.match(line):
                found[(match[1], int(match[2]))] = match[3].split()
        if expected != found:
            mismatch = {key for key in set(expected) | set(found) if expected.get(key) != found.get(key)}
            raise ValueError(f"{local} and {web} differ for {sorted(mismatch)}")
        total += len(expected)
    print(f"Matched {total} transcribed Eastman shade rows to fingerprinted manufacturer PDFs")


def extract(root, sources):
    by_key = {source["id"]: source for source in sources}
    for source, prefix, series, page, switched, generation in [
        ("L01", "Ceramic IR", "Ceramic IR", 1, False, None),
        ("L02", "Obsidian", "Obsidian", 1, False, None),
        ("L04", "CS IR", "Color Stable Series", 2, True, "CS IR"),
        ("L05", "CR BLK", "Crystalline", 2, True, "Crystalline Black"),
    ]:
        yield from three_m(source, pdf_layout(root, by_key[source]), prefix, series, page, switched, generation)
    for source, parser, raw in (
        ("L03", solarfx, False), ("L32", johnson, True), ("L33", johnson, True),
        ("L34", madico, True), ("L52", stek, False), ("L54", uca, False), ("L55", xpel, False),
    ):
        yield from parser(source, pdf_layout(root, by_key[source], raw=raw))


def pdf_layout(root, source, *, raw=False):
    import hashlib

    path = root / source["paths"][0]
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError(f"{source['id']}: original fingerprint differs from reviewed source")
    return subprocess.check_output(["pdftotext", "-raw" if raw else "-layout", path, "-"], text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--public-pdfs", type=Path, help="also verify Eastman reprints and extract Nexfil")
    parser.add_argument("--public-output", type=Path, help="destination for the public parsed table snapshot")
    args = parser.parse_args()
    if bool(args.public_pdfs) != bool(args.public_output):
        parser.error("--public-pdfs and --public-output are required together")
    if any(args.root.resolve() in (target.resolve(), *target.resolve().parents)
           for target in (args.output, args.public_output) if target):
        parser.error("Output must be outside the originals")
    sources = json.loads((HERE / "local-sources.json").read_text())
    args.output.write_text(json.dumps(list(extract(args.root, sources)), ensure_ascii=False, indent=2) + "\n")
    if args.public_pdfs:
        hashes = json.loads((HERE / "public-document-hashes.json").read_text())
        verify_eastman_reprints(args.public_pdfs, hashes)
        source = "W-nexfil-chart"
        layout = pdf_layout(args.public_pdfs, {"id": source, "paths": [source + ".pdf"], "sha256": hashes[source]})
        args.public_output.write_text(json.dumps(list(nexfil(source, layout)), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
