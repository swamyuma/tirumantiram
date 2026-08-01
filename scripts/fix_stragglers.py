#!/usr/bin/env python3
"""
fix_stragglers.py -- set up the T2/T3 "straggler" re-reads.

These verses have OCR-garbage English because their SOURCE slots were garbage /
missing in the original scan. A script cannot invent the correct text -- it has
to be READ off the Natarajan PDF pages by eye. So this script does everything
AROUND that manual read:

  1. prints a worklist: verse | est. page | current (broken) title | Tamil line1
  2. renders the estimated PDF pages to _pages/pg-NNN.png so you can read them
  3. scaffolds stragglers.json, pre-filled with each verse's CURRENT fields

Then YOU (no model usage needed):
  - open the rendered PNGs (paths are printed), OR the PDF itself, and find each
    verse by its PRINTED verse number; read Natarajan's title/translation/
    commentary for it
  - edit stragglers.json  (fix english_title / english_translation / notes;
    leave notes "" if the verse has no commentary block)
  - apply it to all 3 files (index.html, flipbook.html, thirumanthiram_verses.json):

        python3 extract_verses.py apply --in stragglers.json

    (apply backs up each file, verifies it still parses and the entry count is
     unchanged, and refuses to write otherwise. Safe to re-run.)

Run in WSL, from the project dir:

    python3 fix_stragglers.py               # worklist + render + scaffold
    python3 fix_stragglers.py --no-render   # skip rendering (pages already done)
    python3 fix_stragglers.py --margin 2    # render +/-2 pages around each estimate
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_verses as ev

# T2: 386, 418   |   T3: 592, 602, 653, 668, 677, 680, 699, 712, 828, 837
STRAGGLERS = [386, 418, 592, 602, 653, 668, 677, 680, 699, 712, 828, 837]
OUT = os.path.join(ev.SCRIPT_DIR, "stragglers.json")

# (physical_page, verse) anchors for a ROUGH page estimate. The printed verse
# number on each page image is the real authority -- these just tell you which
# PNG to open. From prior work: T1 108~pg39 / 325~pg71, T2 386~pg82 / 418~pg87,
# T4 1388~pg238 / 1495~pg256.  physical page N == printed page (N - 22).
ANCHORS = sorted([(39, 108), (71, 325), (82, 386), (87, 418),
                  (238, 1388), (256, 1495)])


def page_of_verse(n):
    """Piecewise-linear interpolate/extrapolate the physical page for verse n."""
    pts = sorted((v, p) for p, v in ANCHORS)     # (verse, page)
    xs = [v for v, _ in pts]
    ys = [p for _, p in pts]
    if n <= xs[0]:
        i, j = 0, 1
    elif n >= xs[-1]:
        i, j = len(xs) - 2, len(xs) - 1
    else:
        j = next(k for k in range(1, len(xs)) if xs[k] >= n)
        i = j - 1
    if xs[j] == xs[i]:
        return int(round(ys[i]))
    return int(round(ys[i] + (ys[j] - ys[i]) * (n - xs[i]) / (xs[j] - xs[i])))


def render_pages(pages, dpi=200):
    """Render the given physical pages (skipping ones already present) as
    _pages/pg-NNN.png, batching contiguous runs into one pdftoppm call."""
    os.makedirs(ev.PAGES_DIR, exist_ok=True)
    have = set(os.listdir(ev.PAGES_DIR))
    todo = sorted(p for p in pages if "pg-%03d.png" % p not in have)
    if not todo:
        print("  (all needed pages already rendered)")
        return
    runs, run = [], [todo[0]]
    for p in todo[1:]:
        if p == run[-1] + 1:
            run.append(p)
        else:
            runs.append(run)
            run = [p]
    runs.append(run)
    for run in runs:
        cmd = ["pdftoppm", "-png", "-r", str(dpi), "-f", str(run[0]),
               "-l", str(run[-1]), ev.PDF, os.path.join(ev.PAGES_DIR, "pg")]
        print("  running:", " ".join(cmd))
        if subprocess.run(cmd).returncode != 0:
            ev.die("pdftoppm failed for pages %d-%d" % (run[0], run[-1]))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-render", action="store_true",
                    help="do not render pages (just worklist + scaffold)")
    ap.add_argument("--margin", type=int, default=1,
                    help="render +/-N pages around each estimate (default 1)")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    blob = ev._load_blob()
    spans = {n: (s, e) for n, s, e in ev.iter_verses(blob)}

    # ---- worklist ---- #
    print("=== T2/T3 STRAGGLER WORKLIST ===")
    print("%-6s %-7s %-40s %s" % ("VERSE", "PAGE", "CURRENT TITLE (likely broken)",
                                  "TAMIL (line 1)"))
    pages_needed = set()
    entries = []
    for n in STRAGGLERS:
        if n not in spans:
            print("%-6d  !! not found in blob" % n)
            continue
        s, e = spans[n]
        chunk = blob[s:e]
        title = (ev._field_value(chunk, "english_title") or "")[:40]
        tamil1 = (ev._field_value(chunk, "tamil") or "").split("\n")[0][:30]
        pg = page_of_verse(n)
        print("%-6d pg-%-4d %-40s %s" % (n, pg, title, tamil1))
        for d in range(-args.margin, args.margin + 1):
            pages_needed.add(pg + d)
        entry = {"verse_number": n}
        for f in ev.FIELDS:
            v = ev._field_value(chunk, f)
            if v is not None:
                entry[f] = v
        entries.append(entry)

    print("\nphysical pages to read (printed page = physical - 22):",
          sorted(pages_needed))

    # ---- render ---- #
    if not args.no_render:
        print("\n=== RENDERING PAGES -> %s ===" % ev.wsl_to_win(ev.PAGES_DIR))
        render_pages(pages_needed, dpi=args.dpi)
    else:
        print("\n(skipping render; --no-render)")

    # ---- scaffold ---- #
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("\n=== SCAFFOLD WRITTEN ===")
    print("  %s  (%d verses, pre-filled with current fields)"
          % (ev.wsl_to_win(OUT), len(entries)))
    print("\nNext:")
    print("  1. open the PNGs above; find each verse by its PRINTED number")
    print("  2. fix english_title / english_translation / notes in stragglers.json")
    print("  3. python3 extract_verses.py apply --in stragglers.json")


if __name__ == "__main__":
    main()
