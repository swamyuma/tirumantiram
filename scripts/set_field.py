#!/usr/bin/env python3
"""set_field.py -- rewrite an arbitrary string field for verse ranges across
all three files (index.html, flipbook.html, thirumanthiram_verses.json).

Generalizes set_sections.py (which only does `section`). Use it for fields
that extract_verses.py apply does not touch -- e.g. `tantra` (the Tantra label)
or `section`. It ONLY sets the one named field; every other field is untouched.

Input JSON: a list of ranges, each assigning one value to [from,to]:
    [{"from":538,"to":548,"value":"Tantra Two"}, ...]
Ranges must be non-overlapping; any verse not covered keeps its current value.

Same safety model as extract_verses.py apply / set_sections.py: builds and
verifies everything in memory (node re-parse + unchanged entry count), backs up
each file (timestamped .bak), and refuses to write on any mismatch. Re-runnable.

    python3 set_field.py --field tantra --in fix_tantra.json --dry-run
    python3 set_field.py --field tantra --in fix_tantra.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_verses as ev


def expand(ranges):
    """[{from,to,value}] -> {verse_number: value}, checking overlaps."""
    out = {}
    for r in ranges:
        a, b, v = r["from"], r["to"], r["value"]
        if b < a:
            ev.die("bad range %d-%d" % (a, b))
        for n in range(a, b + 1):
            if n in out:
                ev.die("verse %d covered by two ranges" % n)
            out[n] = v
    return out


def patch_html_field(html, field, want, path):
    """Return patched html with `field` set per `want` {verse_number: value}.
    Raises on any missing verse / missing field."""
    a, b = ev.extract_blob_span(html)
    blob = html[a:b + 1]
    field_re = ev._field_re(field)
    for n in sorted(want):
        span = ev.verse_span(blob, n)
        if span is None:
            raise ValueError("verse %d not found in %s" % (n, path))
        s, e = span
        chunk = blob[s:e]
        repl = '"%s":%s' % (field, json.dumps(want[n], ensure_ascii=False))
        chunk, cnt = field_re.subn(lambda _m: repl, chunk, count=1)
        if cnt != 1:
            raise ValueError('%s field not found for verse %d in %s'
                             % (field, n, path))
        blob = blob[:s] + chunk + blob[e:]
    return html[:a] + blob + html[b + 1:]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--field", required=True, help="field name, e.g. tantra")
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="verify only; write nothing")
    args = ap.parse_args()

    with open(args.infile, "r", encoding="utf-8") as fh:
        ranges = json.load(fh)
    want = expand(ranges)
    print("setting %s on %d verse(s): %d..%d across %d range(s)"
          % (args.field, len(want), min(want), max(want), len(ranges)))

    # ---- phase 1: build + verify in memory ---- #
    new_html = {}
    for path in ev.HTML_FILES:
        html = ev.read_text(path)
        orig = ev.node_entry_count(path)
        try:
            patched = patch_html_field(html, args.field, want, os.path.basename(path))
        except ValueError as ex:
            ev.die(str(ex))
        new_html[path] = (patched, orig)

    # The JSON mirror was removed from the working tree in the repo cleanup
    # (commit ebb5d32); patch it only if it is actually there.
    data = None
    orig_json = None
    if os.path.exists(ev.JSON_MIRROR):
        data = json.load(open(ev.JSON_MIRROR, "r", encoding="utf-8"))
        orig_json = len(data)
        index = {o["verse_number"]: o for o in data}
        for n, v in want.items():
            if n not in index:
                ev.die("verse %d missing from JSON mirror" % n)
            index[n][args.field] = v
        if len(data) != orig_json:
            ev.die("JSON mirror entry count changed")
    else:
        print("  note: %s absent -- patching the HTML files only"
              % os.path.basename(ev.JSON_MIRROR))

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
        print("dry-run OK: %d file(s) would stay valid with %d entries."
              % (len(new_html) + (1 if data is not None else 0), orig))
        return

    # ---- phase 2: back up and commit writes ---- #
    ts = ev.timestamp()
    for path, (tmp, orig) in new_html.items():
        bak = "%s.%s.bak" % (path, ts)
        os.replace(path, bak)
        os.replace(tmp, path)
        print("  %-14s %s set (%d entries)  backup: %s"
              % (os.path.basename(path), args.field, orig, os.path.basename(bak)))
    if data is not None:
        jbak = "%s.%s.bak" % (ev.JSON_MIRROR, ts)
        os.replace(ev.JSON_MIRROR, jbak)
        with open(ev.JSON_MIRROR, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print("  %-14s %s set (%d entries)  backup: %s"
              % (os.path.basename(ev.JSON_MIRROR), args.field, orig_json,
                 os.path.basename(jbak)))
    print("done.")


if __name__ == "__main__":
    main()
