#!/usr/bin/env python3
"""
t4_tool.py -- driver for the Tantra Four (873-1418) page-by-page re-read.

Tantra Four is the hard one: its English drift WANDERS (no uniform shift works),
so every verse must be checked against the printed Natarajan page. This script
automates the plumbing around that manual reading. It's a thin wrapper over
extract_verses.py (which must sit next to it) and runs the SAME way -- in WSL:

    cd "/mnt/c/Users/umasu/Documents/gate-files/tnarch-downloads/tirumantiram"
    python3 t4_tool.py <command>

...or from PowerShell prefix each line with `wsl `, e.g. `wsl python3 t4_tool.py scan`.

Typical session
---------------
    python3 t4_tool.py render        # render all T4 pages to _pages/ (once)
    python3 t4_tool.py scaffold      # create tantra_four.json (once)
    python3 t4_tool.py scan          # see which verses still look wrong + their page
    python3 t4_tool.py page 200      # list the verses on physical page 200, open the PNG,
                                     #   then fix those entries in tantra_four.json
    python3 t4_tool.py apply         # write the fixes to all 3 files (verified + backed up)

Repeat page -> edit -> scan until `scan` reports 0 suspects, then `apply`.
`apply` is safe to run repeatedly; fill the JSON over several sittings.

Commands
--------
  render [--first P --last P] [--dpi N] [--force]
        Render the T4 physical page range (default 149-245) to _pages/pg-NNN.png.
        Skips pages already present unless --force. Read the PNGs by eye.
  scaffold [--force]
        Dump the CURRENT Tantra Four entries to tantra_four.json for editing.
        Refuses to clobber an existing file unless --force (so you don't lose edits).
  scan [--all]
        Flag verses that still look like OCR garbage / are unedited, with the
        physical page to read for each. Reads your in-progress tantra_four.json if
        present, else the live data. --all lists every verse, not just suspects.
  page P
        Show the verses estimated to be on physical page P (printed page P-22),
        with their current English title -- your worklist for that one PNG.
  map [--verse N | --page P]
        Print the verse<->page estimate (whole tantra, or one lookup).
  apply
        Run `extract_verses.py apply --in tantra_four.json`.

Page-number hints are ESTIMATES (calibrated ~5.94 verses/printed page from two
known anchors). The printed number is on every page image -- trust that and, to
sharpen future hints, append observed "physical_page<TAB>verse" lines to
t4_pagemap.tsv (the script interpolates through whatever anchors it finds there).
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_verses as ev   # reuse blob parsing, render offset, apply, etc.

T4_NAME   = "Tantra Four"
T4_LO, T4_HI = 873, 1418
JSON_FILE = os.path.join(ev.SCRIPT_DIR, "tantra_four.json")
PAGEMAP   = os.path.join(ev.SCRIPT_DIR, "t4_pagemap.tsv")

# Calibration anchors: (physical_page, verse_number), from pages already read.
#   pg-238 (printed 214) -> verse 1388 ;  pg-256 (printed 232) -> verse 1495
# Extra observations in t4_pagemap.tsv are merged in and take precedence.
BUILTIN_ANCHORS = [(238, 1388), (256, 1495)]


# --------------------------------------------------------------------------- #
# verse <-> physical-page estimate (piecewise-linear through the anchors)
# --------------------------------------------------------------------------- #
def _anchors():
    pts = dict(BUILTIN_ANCHORS)
    if os.path.exists(PAGEMAP):
        for ln in open(PAGEMAP, encoding="utf-8"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = re.split(r"[\s,]+", ln)
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                pts[int(parts[0])] = int(parts[1])   # page -> verse (file wins)
    return sorted(pts.items())                        # by page


def _interp(x, pts, xi, yi):
    """Piecewise-linear interpolate/extrapolate y at x, given sorted (xi,yi) pts."""
    xs = [p[xi] for p in pts]
    ys = [p[yi] for p in pts]
    if len(pts) == 1:
        return ys[0]
    if x <= xs[0]:
        i, j = 0, 1
    elif x >= xs[-1]:
        i, j = len(xs) - 2, len(xs) - 1
    else:
        j = next(k for k in range(1, len(xs)) if xs[k] >= x)
        i = j - 1
    if xs[j] == xs[i]:
        return ys[i]
    return ys[i] + (ys[j] - ys[i]) * (x - xs[i]) / (xs[j] - xs[i])


def page_of_verse(n):
    pts = _anchors()                       # (page, verse)
    vp = sorted((v, p) for p, v in pts)    # (verse, page)
    return int(round(_interp(n, vp, 0, 1)))


def verse_of_page(p):
    pts = _anchors()                       # (page, verse)
    return int(round(_interp(p, pts, 0, 1)))


# --------------------------------------------------------------------------- #
# data access
# --------------------------------------------------------------------------- #
def _live_entries():
    """Current T4 verses from the live data (index.html blob)."""
    blob = ev._load_blob()
    out = {}
    for n, s, e in ev.iter_verses(blob):
        if T4_LO <= n <= T4_HI:
            ch = blob[s:e]
            out[n] = {f: (ev._field_value(ch, f) or "") for f in ev.FIELDS}
    return out


def _working_entries():
    """Prefer the in-progress tantra_four.json (so scan reflects your edits);
    fall back to live data. Returns {n: {field: value}}."""
    if os.path.exists(JSON_FILE):
        data = json.load(open(JSON_FILE, encoding="utf-8"))
        return {v["verse_number"]: {f: v.get(f, "") for f in ev.FIELDS}
                for v in data if T4_LO <= v["verse_number"] <= T4_HI}, "tantra_four.json"
    return _live_entries(), "live data"


def _tamil1(v):
    return (v.get("tamil", "") or "").split("\n")[0]


def is_suspect(v):
    t  = (v.get("english_title", "") or "").strip()
    tr = (v.get("english_translation", "") or "").strip()
    r = []
    if re.fullmatch(r"[\d\-\.\s]*", t):        r.append("num/empty-title")
    elif len(t) < 3:                           r.append("short-title")
    if not tr:                                 r.append("empty-tr")
    if re.search(r"[஀-௿]", t):       r.append("tamil-in-title")
    if t and len(t) > 8 and t.lower() in tr.lower()[:len(t) + 40]:
        r.append("title-in-tr")
    return r


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_render(a):
    first = a.first if a.first is not None else page_of_verse(T4_LO) - 2
    last  = a.last  if a.last  is not None else page_of_verse(T4_HI) + 2
    os.makedirs(ev.PAGES_DIR, exist_ok=True)
    have = set(os.listdir(ev.PAGES_DIR))
    todo = [p for p in range(first, last + 1)
            if a.force or f"pg-{p:03d}.png" not in have]
    if not todo:
        print("all pages %d-%d already rendered (use --force to redo)" % (first, last))
        return
    # render contiguous runs in one pdftoppm call each
    runs, run = [], [todo[0]]
    for p in todo[1:]:
        if p == run[-1] + 1:
            run.append(p)
        else:
            runs.append(run); run = [p]
    runs.append(run)
    for run in runs:
        cmd = ["pdftoppm", "-png", "-r", str(a.dpi),
               "-f", str(run[0]), "-l", str(run[-1]), ev.PDF,
               os.path.join(ev.PAGES_DIR, "pg")]
        print("running:", " ".join(cmd))
        if subprocess.run(cmd).returncode != 0:
            ev.die("pdftoppm failed for pages %d-%d" % (run[0], run[-1]))
    print("\nrendered %d page(s). physical page N == printed page N-%d."
          % (sum(len(r) for r in runs), ev.PAGE_OFFSET))
    print("open them from:", ev.wsl_to_win(ev.PAGES_DIR))


def cmd_scaffold(a):
    if os.path.exists(JSON_FILE) and not a.force:
        ev.die("tantra_four.json already exists -- edit it, or pass --force to "
               "overwrite (you will lose any edits in it).")
    ns = argparse.Namespace(tantra=T4_NAME, frm=None, to=None, out=JSON_FILE)
    ev.cmd_scaffold(ns)


def cmd_scan(a):
    entries, src = _working_entries()
    rows = []
    for n in range(T4_LO, T4_HI + 1):
        v = entries.get(n)
        if v is None:
            rows.append((n, page_of_verse(n), ["MISSING"], "")); continue
        s = is_suspect(v)
        if s or a.all:
            rows.append((n, page_of_verse(n), s, (v.get("english_title", "") or "")[:46]))
    suspects = [r for r in rows if r[2]]
    print("source: %s   |   %d/%d verses flagged\n" % (src, len(suspects),
          T4_HI - T4_LO + 1))
    print("%-6s %-5s %-22s %s" % ("VERSE", "PAGE", "FLAGS", "CURRENT TITLE"))
    for n, pg, flags, title in (rows if a.all else suspects):
        print("%-6d %-5s %-22s %s"
              % (n, ("pg-%d" % pg), ",".join(flags) if flags else "ok", title))
    if not a.all:
        print("\nphysical pages needing work:",
              sorted({r[1] for r in suspects}))


def cmd_page(a):
    p = a.page
    entries, src = _working_entries()
    lo = verse_of_page(p - 1) + 1
    hi = verse_of_page(p + 1)
    lo = max(lo, T4_LO); hi = min(hi, T4_HI)
    png = os.path.join(ev.PAGES_DIR, "pg-%03d.png" % p)
    print("physical page %d  (printed page %d)" % (p, p - ev.PAGE_OFFSET))
    print("image:", ev.wsl_to_win(png), "(exists)" if os.path.exists(png)
          else "(NOT rendered -- run: python3 t4_tool.py render)")
    print("estimated verses on this page: %d .. %d   [source: %s]\n" % (lo, hi, src))
    print("%-6s %-5s %-46s %s" % ("VERSE", "FLAG", "CURRENT TITLE", "TAMIL (line 1)"))
    for n in range(lo, hi + 1):
        v = entries.get(n, {})
        flag = "!" if is_suspect(v) else " "
        print("%-6d  %-4s %-46s %s"
              % (n, flag, (v.get("english_title", "") or "")[:46], _tamil1(v)[:30]))
    print("\nedit these entries in tantra_four.json, then: python3 t4_tool.py scan")


def cmd_map(a):
    if a.verse is not None:
        print("verse %d  ~=  physical page %d  (printed %d)"
              % (a.verse, page_of_verse(a.verse), page_of_verse(a.verse) - ev.PAGE_OFFSET))
        return
    if a.page is not None:
        print("physical page %d  ~=  verse %d" % (a.page, verse_of_page(a.page)))
        return
    print("anchors (physical_page -> verse):", _anchors())
    print("%-6s %-6s" % ("VERSE", "PAGE"))
    for n in range(T4_LO, T4_HI + 1, 10):
        print("%-6d pg-%d" % (n, page_of_verse(n)))


def cmd_apply(a):
    if not os.path.exists(JSON_FILE):
        ev.die("tantra_four.json not found -- run: python3 t4_tool.py scaffold")
    subprocess.run([sys.executable, os.path.join(ev.SCRIPT_DIR, "extract_verses.py"),
                    "apply", "--in", JSON_FILE], check=False)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="render T4 pages to PNG")
    r.add_argument("--first", type=int, default=None)
    r.add_argument("--last", type=int, default=None)
    r.add_argument("--dpi", type=int, default=200)
    r.add_argument("--force", action="store_true", help="re-render existing pages")
    r.set_defaults(func=cmd_render)

    s = sub.add_parser("scaffold", help="create tantra_four.json")
    s.add_argument("--force", action="store_true", help="overwrite existing file")
    s.set_defaults(func=cmd_scaffold)

    sc = sub.add_parser("scan", help="flag suspect/unedited verses + their page")
    sc.add_argument("--all", action="store_true", help="list every verse")
    sc.set_defaults(func=cmd_scan)

    pg = sub.add_parser("page", help="list the verses on a physical page")
    pg.add_argument("page", type=int)
    pg.set_defaults(func=cmd_page)

    m = sub.add_parser("map", help="verse<->page estimate")
    m.add_argument("--verse", type=int)
    m.add_argument("--page", type=int)
    m.set_defaults(func=cmd_map)

    ap = sub.add_parser("apply", help="apply tantra_four.json to all 3 files")
    ap.set_defaults(func=cmd_apply)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
