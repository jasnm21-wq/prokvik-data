#!/usr/bin/env python3
"""Read originals without changing them. Store renders and OCR outside the catalog."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def extract(root, output, inspect):
    def capture(path):
        contents = path.read_bytes()
        digest = hashlib.sha256(contents).hexdigest()
        fmt = subprocess.check_output(["file", "-b", "--mime-type", path], text=True).strip()
        evidence = output / digest
        evidence.mkdir(exist_ok=True)
        if fmt == "application/pdf":
            metadata = subprocess.check_output(["pdfinfo", path], text=True)
            pages = int(next(line.split(":")[1] for line in metadata.splitlines() if line.startswith("Pages:")))
            subprocess.run(["pdftotext", "-layout", path, evidence / "layout.txt"], check=True)
            if inspect:
                subprocess.run(["pdftoppm", "-scale-to", "1800", "-png", path, evidence / "page"], check=True)
        elif fmt.startswith("image/"):
            pages = 1
            if inspect:
                subprocess.run(["magick", path, "-auto-orient", evidence / "page-1.png"], check=True)
        else:
            pages = None
        if inspect:
            for image in sorted(evidence.glob("page-*.png")):
                txt = subprocess.check_output(["tesseract", image, "stdout", "--psm", "6"], stderr=subprocess.DEVNULL)
                image.with_suffix(".txt").write_bytes(txt)
        return {"path": path.relative_to(root).as_posix(), "sha256": digest, "bytes": len(contents),
                "pages": pages, "media_type": fmt}

    paths = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    output.mkdir(parents=True, exist_ok=True)
    # Identical files share one evidence directory and are read sequentially to avoid concurrent output collisions.
    rows = [capture(path) for path in paths]
    (output / "inventory.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--render-and-ocr", action="store_true")
    args = parser.parse_args()
    root, output = args.root.resolve(strict=True), args.output.resolve()
    if output == root or root in output.parents:
        parser.error("Output must be outside the originals")
    print(f"Inventoried {len(extract(root, output, args.render_and_ocr))} files")


if __name__ == "__main__":
    main()
