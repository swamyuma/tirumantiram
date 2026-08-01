#!/usr/bin/env python3
"""
extract_page.py -- Extract Tamil verses and English translations from a
rendered Thirumanthiram page PNG using Tesseract OCR.

Usage (from WSL):
    python3 extract_page.py 273
    python3 extract_page.py 273 --out out.json

Requires (install in WSL):
    sudo apt install tesseract-ocr tesseract-ocr-tam
    pip install pytesseract Pillow
"""

import argparse
import json
import os
import re
import sys

from PIL import Image
import pytesseract

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR  = os.path.join(SCRIPT_DIR, "_pages")


def find_image(page_num):
    """Locate the PNG for the given physical page number."""
    candidates = [
        os.path.join(PAGES_DIR, f"pg-{page_num:03d}.png"),
        os.path.join(PAGES_DIR, f"pg-{page_num:04d}.png"),
        os.path.join(PAGES_DIR, f"pg-{page_num}.png"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        f"No PNG found for page {page_num}. Tried:\n" +
        "\n".join(f"  {c}" for c in candidates)
    )


def split_columns(img):
    """Split image into left and right halves (two-column layout)."""
    w, h = img.size
    mid = w // 2
    left  = img.crop((0, 0, mid, h))
    right = img.crop((mid, 0, w, h))
    return left, right


def ocr_column(img, lang="tam+eng"):
    """Run Tesseract OCR on a column image."""
    # Use PSM 6 (assume a single uniform block of text) for column chunks
    config = "--psm 6"
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    return text


def is_tamil_line(line):
    """Check if a line contains mostly Tamil characters."""
    tamil_chars = sum(1 for c in line if '\u0B80' <= c <= '\u0BFF')
    return tamil_chars > len(line) * 0.3 if line.strip() else False


def parse_verses(raw_text):
    """
    Best-effort parse of OCR text into verse dicts.
    This is heuristic — review the output manually.
    """
    lines = raw_text.split("\n")
    verses = []
    current = None
    mode = None  # 'tamil', 'title', 'english', 'notes'

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect verse number (typically a 4-digit number at end of Tamil block)
        num_match = re.search(r'\b(\d{3,4})\s*$', stripped)

        if is_tamil_line(stripped):
            if current is None or (current.get("english_translation") and
                                    current.get("tamil")):
                # Start new verse
                current = {
                    "verse_number": 0,
                    "tamil": "",
                    "english_title": "",
                    "english_translation": "",
                    "notes": ""
                }
                verses.append(current)
                mode = "tamil"

            if mode != "tamil":
                mode = "tamil"
                if current.get("tamil"):
                    # New tamil block = new verse
                    current = {
                        "verse_number": 0,
                        "tamil": "",
                        "english_title": "",
                        "english_translation": "",
                        "notes": ""
                    }
                    verses.append(current)

            # Extract verse number if present at end
            if num_match:
                current["verse_number"] = int(num_match.group(1))
                tamil_line = stripped[:num_match.start()].rstrip()
            else:
                tamil_line = stripped

            if current["tamil"]:
                current["tamil"] += "\n" + tamil_line
            else:
                current["tamil"] = tamil_line

        elif current is not None:
            # English text
            if mode == "tamil":
                # First English line after Tamil = title
                current["english_title"] = stripped
                mode = "title"
            elif mode == "title":
                # Lines after title = translation
                current["english_translation"] = stripped
                mode = "english"
            elif mode == "english":
                # Check if this looks like a notes/commentary line
                if re.match(r'^(Mantras?\s+\d|[*•]|\w+,\s+\w+\s+\w+,)', stripped):
                    current["notes"] = stripped
                    mode = "notes"
                else:
                    current["english_translation"] += "\n" + stripped
            elif mode == "notes":
                current["notes"] += "\n" + stripped

    return verses


def main():
    parser = argparse.ArgumentParser(
        description="Extract Tamil & English from a Thirumanthiram page PNG using Tesseract OCR."
    )
    parser.add_argument("page", type=int, help="Physical page number (e.g. 273)")
    parser.add_argument("--out", type=str, default=None,
                        help="Output JSON file (default: extracted_pg_NNN.json)")
    parser.add_argument("--raw", action="store_true",
                        help="Also save raw OCR text alongside JSON")
    parser.add_argument("--lang", type=str, default="tam+eng",
                        help="Tesseract language(s) (default: tam+eng)")
    args = parser.parse_args()

    img_path = find_image(args.page)
    print(f"Page {args.page}: {img_path}")

    img = Image.open(img_path)
    print(f"  Size: {img.size[0]}x{img.size[1]}")

    # Split into columns and OCR each
    left_img, right_img = split_columns(img)

    print("  OCR left column...")
    left_text = ocr_column(left_img, lang=args.lang)

    print("  OCR right column...")
    right_text = ocr_column(right_img, lang=args.lang)

    raw_text = (
        "=== LEFT COLUMN ===\n" + left_text +
        "\n\n=== RIGHT COLUMN ===\n" + right_text
    )

    # Parse verses from each column
    left_verses  = parse_verses(left_text)
    right_verses = parse_verses(right_text)
    all_verses   = left_verses + right_verses

    print(f"\n  Found {len(all_verses)} verse(s):")
    for v in all_verses:
        print(f"    #{v['verse_number']}: {v['english_title'][:50]}")

    # Save
    out_base = args.out or os.path.join(
        SCRIPT_DIR, f"extracted_pg_{args.page:03d}.json"
    )

    with open(out_base, "w", encoding="utf-8") as f:
        json.dump(all_verses, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\n  JSON: {out_base}")

    if args.raw:
        raw_path = out_base.replace(".json", "_raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
        print(f"  Raw:  {raw_path}")

    print("\n⚠  Tesseract OCR on two-column Tamil/English is imperfect.")
    print("   Review the output and fix manually as needed.")


if __name__ == "__main__":
    main()
