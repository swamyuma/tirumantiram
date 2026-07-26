#!/usr/bin/env python3
"""set_sections.py -- rewrite the `section` field for verse ranges across all
three files (index.html, flipbook.html, thirumanthiram_verses.json).

The `section` field is NOT touched by extract_verses.py apply (which only edits
tamil/english_title/english_translation/notes). This tool fixes section-label
drift: the section headings had drifted off the verses (e.g. Tantra Two's
labels were ~11 verses early after the old +11 English shift was never applied
to sections). Ground truth = the section start-verses read from the PDF.

Input JSON: a list of ranges, each assigning one section name to [from,to]:
    [{"from":337,"to":338,"section":"AGASTYAM"}, ...]
Ranges must be contiguous and non-overlapping within the span they cover; any
verse not covered keeps its current section.

Same safety model as extract_verses.py apply: builds + verifies everything in
memory (node re-parse + unchanged entry count), backs up each file (timestamped
.bak), and refuses to write on any mismatch. Safe to re-run.

    python3 set_sections.py --in t2_sections_fix.json
    python3 set_sections.py --in t2_sections_fix.json --dry-run
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_verses as ev


def expand(ranges):
    """[{from,to,section}] -> {verse_number: section}, checking overlaps."""
    out = {}
    for r in ranges:
        a, b, s = r["from"], r["to"], r["section"]
        if b < a:
            ev.die("bad range %d-%d" % (a, b))
        for n in range(a, b + 1):
            if n in out:
                ev.die("verse %d covered by two ranges" % n)
            out[n] = s
    return out


def patch_html_sections(html, want, path):
    """Return patched html with the `section` field set per `want`
    {verse_number: section}. Raises on any missing verse / section field."""
    a, b = ev.extract_blob_span(html)
    blob = html[a:b + 1]
    field_re = ev._field_re("section")
    for n in sorted(want):
        span = ev.verse_span(blob, n)
        if span is None:
            raise ValueError("verse %d not found in %s" % (n, path))
        s, e = span
        chunk = blob[s:e]
        repl = '"section":%s' % json.dumps(want[n], ensure_ascii=False)
        chunk, cnt = field_re.subn(lambda _m: repl, chunk, count=1)
        if cnt != 1:
            raise ValueError('section field not found for verse %d in %s' % (n, path))
        blob = blob[:s] + chunk + blob[e:]
    return html[:a] + blob + html[b + 1:]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="verify only; write nothing")
    args = ap.parse_args()

    with open(args.infile, "r", encoding="utf-8") as fh:
        ranges = json.load(fh)
    want = expand(ranges)
    print("setting section on %d verse(s): %d..%d across %d range(s)"
          % (len(want), min(want), max(want), len(ranges)))

    # ---- phase 1: build + verify in memory ---- #
    new_html = {}
    for path in ev.HTML_FILES:
        html = ev.read_text(path)
        orig = ev.node_entry_count(path)
        try:
            patched = patch_html_sections(html, want, os.path.basename(path))
        except ValueError as ex:
            ev.die(str(ex))
        new_html[path] = (patched, orig)

    data = json.load(open(ev.JSON_MIRROR, "r", encoding="utf-8"))
    orig_json = len(data)
    index = {o["verse_number"]: o for o in data}
    for n, s in want.items():
        if n not in index:
            ev.die("verse %d missing from JSON mirror" % n)
        index[n]["section"] = s
    if len(data) != orig_json:
        ev.die("JSON mirror entry count changed")

    # verify each patched HTML still parses with unchanged count, via temp file
    for path, (patched, orig) in new_html.items():
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(patched)
        try:
            new = ev.node_entry_count(tmp)
        except RuntimeError as ex:
            os.remove(tmp)
            ev.die(str(ex))
        if new != orig:
            os.remove(tmp)
            ev.die("%s entry count changed (%d -> %d)"
                   % (os.path.basename(path), orig, new))
        new_html[path] = (tmp, orig)

    if args.dry_run:
        for path, (tmp, orig) in new_html.items():
            os.remove(tmp)
        print("dry-run OK: all 3 files would stay valid with %d entries." % orig_json)
        return

    # ---- phase 2: back up and commit writes ---- #
    ts = ev.timestamp()
    for path, (tmp, orig) in new_html.items():
        bak = "%s.%s.bak" % (path, ts)
        os.replace(path, bak)
        os.replace(tmp, path)
        print("  %-14s sections set (%d entries)  backup: %s"
              % (os.path.basename(path), orig, os.path.basename(bak)))
    jbak = "%s.%s.bak" % (ev.JSON_MIRROR, ts)
    os.replace(ev.JSON_MIRROR, jbak)
    with open(ev.JSON_MIRROR, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("  %-14s sections set (%d entries)  backup: %s"
          % (os.path.basename(ev.JSON_MIRROR), orig_json, os.path.basename(jbak)))
    print("done.")


if __name__ == "__main__":
    main()
