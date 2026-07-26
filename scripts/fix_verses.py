#!/usr/bin/env python3
"""
fix_verses.py -- set up a targeted re-read of an arbitrary list of verses.

General version of fix_stragglers.py: pass verse numbers on the command line
(e.g. the isolated OCR-garbage verses in a Tantra). A script cannot invent the
correct English -- it must be READ off the Natarajan PDF pages by eye -- so this
does the plumbing around that read:

  1. prints a worklist: verse | est. page | current (broken) title | Tamil line1
  2. renders the estimated PDF pages to _pages/pg-NNN.png so you can read them
  3. scaffolds an editable JSON, pre-filled with each verse's CURRENT fields

Then YOU (no model usage needed):
  - open the rendered PNGs (paths printed), find each verse by its PRINTED number
  - fix english_title / english_translation / notes in the scaffold JSON
    (leave notes "" if the verse has no commentary block)
  - apply to all 3 files (index.html, flipbook.html, thirumanthiram_verses.json):

        python3 extract_verses.py apply --in <scaffold.json>

    apply backs up each file, verifies it still parses with the same entry
    count, and refuses to write otherwise. Safe to re-run.

Run in WSL, from the project dir. Examples:

    python3 fix_verses.py 1592 1607 1643 1661 1667            # Tantra Six
    python3 fix_verses.py --out t6_fix.json 1592 1643 1661    # custom out name
    python3 fix_verses.py --no-render 1592 1643               # skip rendering
    python3 fix_verses.py --margin 2 1643                     # +/-2 pages
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_verses as ev

# (physical_page, verse) anchors for a ROUGH page estimate. The PRINTED verse
# number on each page image is the real authority -- these just say which PNG to
# open. Gathered from prior work across the book; physical page N == printed N-22.
#   invocation pg25=v0 | T1 pg39=v108 / pg71=v325 | T2 pg82=v386 / pg87=v418
#   T4 pg238=v1388 / pg256=v1495 | T6 start pg270=v1573
ANCHORS = sorted([(25, 0), (39, 108), (71, 325), (82, 386), (87, 418),
                  (238, 1388), (256, 1495), (270, 1573),
                  # T6 anchors observed 2026-07-22 (physical page N == printed N-24 here):
                  (273, 1592), (281, 1643), (284, 1661), (285, 1667),
                  # T7 span observed 2026-07-22: verses 1706..2123 spanned physical pp.295..354
                  # (~7 verses/page). Extends the estimate into T7/T8 territory.
                  (295, 1706), (354, 2123),
                  # T8 anchors observed 2026-07-23 (still ~7 verses/page; extends into T9):
                  (406, 2454), (433, 2644)])


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
    ap.add_argument("verses", nargs="+", type=int, help="verse numbers to re-read")
    ap.add_argument("--out", default=None, help="scaffold filename (default verses_fix.json)")
    ap.add_argument("--no-render", action="store_true", help="do not render pages")
    ap.add_argument("--margin", type=int, default=1, help="+/-N pages around each estimate (default 1)")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    out = args.out or os.path.join(ev.SCRIPT_DIR, "verses_fix.json")
    want = sorted(set(args.verses))

    blob = ev._load_blob()
    spans = {n: (s, e) for n, s, e in ev.iter_verses(blob)}

    print("=== WORKLIST ===")
    print("%-6s %-7s %-40s %s" % ("VERSE", "PAGE", "CURRENT TITLE (likely broken)",
                                  "TAMIL (line 1)"))
    pages_needed = set()
    entries = []
    for n in want:
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

    if not args.no_render:
        print("\n=== RENDERING -> %s ===" % ev.wsl_to_win(ev.PAGES_DIR))
        render_pages(pages_needed, dpi=args.dpi)
    else:
        print("\n(skipping render; --no-render)")

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("\n=== SCAFFOLD WRITTEN ===")
    print("  %s  (%d verses, pre-filled with current fields)"
          % (ev.wsl_to_win(out), len(entries)))
    print("\nNext:")
    print("  1. open the PNGs above; find each verse by its PRINTED number")
    print("  2. fix english_title / english_translation / notes in %s"
          % os.path.basename(out))
    print("  3. python3 extract_verses.py apply --in %s" % os.path.basename(out))


if __name__ == "__main__":
    main()
