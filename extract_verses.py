#!/usr/bin/env python3
"""
extract_verses.py  --  Thirumanthiram verse extraction helper.

Runs in WSL (Python 3.12).  Automates the mechanical parts of the
verse-by-verse re-extraction workflow; the Tamil/English text itself is
still read from the rendered PDF pages by eye (vision), because OCR
scrambles Natarajan's two-column layout.

Three subcommands:

  render   -- render PDF pages to PNG so the pages can be read by eye.
  scaffold -- pull the *current* entries for a verse range out of index.html
              into an editable JSON file (only overwrite the fields you want).
  apply    -- patch index.html, flipbook.html AND thirumanthiram_verses.json
              from an edited JSON file, then verify each still parses and the
              entry count is unchanged.

Typical run (next batch, printed pages ~45-46 => physical 67-68):

    wsl python3 extract_verses.py render   --first 67 --last 68
    # (read the PNGs, edit verses.json)
    wsl python3 extract_verses.py scaffold --from 151 --to 165 --out verses.json
    # ... fill in english_title / english_translation in verses.json ...
    wsl python3 extract_verses.py apply    --in verses.json
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PDF         = os.path.join(SCRIPT_DIR, "Thirumanthiram_English_Natarajan_Archive.pdf")
HTML_FILES  = [os.path.join(SCRIPT_DIR, "index.html"),
               os.path.join(SCRIPT_DIR, "flipbook.html")]
JSON_MIRROR = os.path.join(SCRIPT_DIR, "thirumanthiram_verses.json")
PAGES_DIR   = os.path.join(SCRIPT_DIR, "_pages")

# physical PDF page number  ==  printed page number + PAGE_OFFSET
# (invocation / verse 0 is printed page 3 == physical page 25)
PAGE_OFFSET = 22

# fields this tool is allowed to touch; Tamil is left alone unless you
# explicitly include it in the JSON.
FIELDS = ["tamil", "english_title", "english_translation", "notes"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def wsl_to_win(path):
    """/mnt/c/Users/... -> C:\\Users\\... so the path can be opened on Windows."""
    m = re.match(r"^/mnt/([a-z])/(.*)$", os.path.abspath(path))
    if not m:
        return path
    return m.group(1).upper() + ":\\" + m.group(2).replace("/", "\\")


def extract_blob_span(html):
    """Return (start, end) so html[start:end+1] is the EMBEDDED_VERSES array
    literal '[...]' (ends with '];</script>')."""
    i = html.index("EMBEDDED_VERSES")
    a = html.index("[", i)
    sc = html.index("</script>", a)
    b = html.rindex("]", a, sc)
    return a, b


def verse_span(blob, n):
    """Return (start, end) of the object for verse_number n within the blob,
    or None. The object literally begins with {"verse_number":n, and ends just
    before the next ,{"verse_number": (or the end of the array)."""
    key = '{"verse_number":%d,' % n
    start = blob.find(key)
    if start == -1:
        return None
    nxt = blob.find(',{"verse_number":', start + 1)
    end = nxt if nxt != -1 else len(blob)
    return start, end


# matches "field":"<json-escaped value>"  (tolerates whitespace after the colon
# and the invalid \e escape used in a front-matter entry)
def _field_re(field):
    return re.compile(r'"' + re.escape(field) + r'":\s*"(?:[^"\\]|\\.)*"')


def node_entry_count(path):
    """Load the EMBEDDED_VERSES blob the same way the app does
    (new Function, NOT JSON.parse) and return the entry count. Raises on any
    parse error."""
    js = (
        "const fs=require('fs');"
        "const s=fs.readFileSync(process.argv[1],'utf8');"
        "const i=s.indexOf('EMBEDDED_VERSES');"
        "const a=s.indexOf('[',i);"
        "const sc=s.indexOf('</script>',a);"
        "const arr=s.slice(a,s.lastIndexOf(']',sc)+1);"
        "const v=new Function('return '+arr)();"
        "process.stdout.write(String(v.length));"
    )
    r = subprocess.run(["node", "-e", js, path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("node parse failed for %s:\n%s" % (path, r.stderr))
    return int(r.stdout.strip())


def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def cmd_render(args):
    if not os.path.exists(PDF):
        die("PDF not found: " + PDF)
    first, last = args.first, args.last
    if args.printed:
        first += PAGE_OFFSET
        last += PAGE_OFFSET
        print("printed %d-%d -> physical %d-%d (offset +%d)"
              % (args.first, args.last, first, last, PAGE_OFFSET))
    if last < first:
        die("--last must be >= --first")

    os.makedirs(PAGES_DIR, exist_ok=True)
    prefix = os.path.join(PAGES_DIR, "pg")
    cmd = ["pdftoppm", "-png", "-r", str(args.dpi),
           "-f", str(first), "-l", str(last), PDF, prefix]
    print("running:", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        die("pdftoppm failed (exit %d)" % r.returncode)

    produced = sorted(f for f in os.listdir(PAGES_DIR)
                      if f.startswith("pg") and f.endswith(".png"))
    print("\nrendered %d page(s) at %d dpi:" % (last - first + 1, args.dpi))
    for f in produced:
        print("  " + wsl_to_win(os.path.join(PAGES_DIR, f)))
    print("\nreminder: physical page N == printed page N-%d" % PAGE_OFFSET)


# --------------------------------------------------------------------------- #
# scaffold
# --------------------------------------------------------------------------- #
def _decode_json_string(escaped):
    """Turn the captured escaped value back into a real string. Falls back to
    the raw text if it contains a non-JSON escape (e.g. \\e)."""
    try:
        return json.loads('"' + escaped + '"')
    except json.JSONDecodeError:
        return escaped


def _field_value(chunk, field):
    """Return the decoded value of `field` within a verse object slice, or
    None if the field is absent."""
    m = _field_re(field).search(chunk)
    if not m:
        return None
    raw = m.group(0)
    inner = raw[raw.index(':') + 1:].lstrip()[1:-1]  # drop key, colon, quotes
    return _decode_json_string(inner)


def iter_verses(blob):
    """Yield (verse_number, start, end) for every object in the blob, in file
    order. end is the start of the next object (or the blob end)."""
    starts = [m.start() for m in re.finditer(r'\{"verse_number":(-?\d+),', blob)]
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(blob)
        n = int(re.match(r'\{"verse_number":(-?\d+),', blob[s:]).group(1))
        yield n, s, e


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _load_blob():
    html = read_text(HTML_FILES[0])          # index.html is source of truth
    a, b = extract_blob_span(html)
    return html[a:b + 1]


def cmd_tantras(args):
    """List every tantra/section with its verse range and count."""
    blob = _load_blob()
    order, groups = [], {}
    for n, s, e in iter_verses(blob):
        t = _field_value(blob[s:e], "tantra") or "(none)"
        if t not in groups:
            groups[t] = []
            order.append(t)
        groups[t].append(n)
    print("%-16s %6s   %s" % ("TANTRA", "COUNT", "VERSE RANGE"))
    for t in order:
        ns = groups[t]
        print("%-16s %6d   %d .. %d" % (t, len(ns), min(ns), max(ns)))
    print("\nscaffold one with:  scaffold --tantra \"Tantra Two\"")


def cmd_scaffold(args):
    blob = _load_blob()

    if args.tantra:
        targets = [(n, s, e) for n, s, e in iter_verses(blob)
                   if _field_value(blob[s:e], "tantra") == args.tantra]
        if not targets:
            die('no verses found with tantra=%r (see the "tantras" command)'
                % args.tantra)
        missing = []
    else:
        if args.frm is None or args.to is None:
            die("give --tantra NAME, or both --from and --to")
        if args.to < args.frm:
            die("--to must be >= --from")
        spans = {n: (s, e) for n, s, e in iter_verses(blob)}
        want = range(args.frm, args.to + 1)
        targets = [(n, spans[n][0], spans[n][1]) for n in want if n in spans]
        missing = [n for n in want if n not in spans]

    # default output filename: per-tantra slug, else a verse range
    out = args.out
    if out is None:
        out = os.path.join(SCRIPT_DIR,
                           (_slug(args.tantra) + ".json") if args.tantra
                           else "verses_%d-%d.json" % (args.frm, args.to))

    entries = []
    for n, s, e in targets:
        chunk = blob[s:e]
        entry = {"verse_number": n}
        for field in FIELDS:
            val = _field_value(chunk, field)
            if val is not None:
                entry[field] = val
        entries.append(entry)

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    label = ('tantra %r' % args.tantra) if args.tantra \
            else ('verses %d-%d' % (args.frm, args.to))
    print("wrote %d verse(s) for %s to %s"
          % (len(entries), label, wsl_to_win(out)))
    if entries:
        print("  verse range: %d .. %d" % (entries[0]["verse_number"],
                                            entries[-1]["verse_number"]))
    if missing:
        print("NOT found (skipped):", missing)
    print("fix the english_title / english_translation fields, then run "
          "'apply --in %s'" % os.path.basename(out))


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def _patch_html(html, verses, path):
    """Return patched html. Raises ValueError on any missing verse/field."""
    a, b = extract_blob_span(html)
    blob = html[a:b + 1]
    for verse in verses:
        n = verse["verse_number"]
        span = verse_span(blob, n)          # recompute each time (positions shift)
        if span is None:
            raise ValueError("verse %d not found in %s" % (n, path))
        s, e = span
        chunk = blob[s:e]
        for field in FIELDS:
            if field not in verse:
                continue
            repl = '"%s":%s' % (field, json.dumps(verse[field], ensure_ascii=False))
            chunk, cnt = _field_re(field).subn(lambda _m: repl, chunk, count=1)
            if cnt != 1:
                raise ValueError('field "%s" not found for verse %d in %s'
                                 % (field, n, path))
        blob = blob[:s] + chunk + blob[e:]
    return html[:a] + blob + html[b + 1:]


def cmd_apply(args):
    with open(args.infile, "r", encoding="utf-8") as fh:
        verses = json.load(fh)
    if not isinstance(verses, list) or not verses:
        die("input JSON must be a non-empty array of verse objects")
    for v in verses:
        if "verse_number" not in v:
            die("every entry needs a verse_number: " + json.dumps(v)[:80])
        extra = [k for k in v if k not in FIELDS and k != "verse_number"]
        if extra:
            die("verse %s has fields this tool will not touch: %s"
                % (v["verse_number"], extra))

    nums = [v["verse_number"] for v in verses]
    print("applying %d verse(s): %s" % (len(verses), nums))

    # ---- phase 1: build + verify everything in memory, write nothing yet ---- #
    new_html = {}
    for path in HTML_FILES:
        html = read_text(path)
        orig = node_entry_count(path)
        try:
            patched = _patch_html(html, verses, os.path.basename(path))
        except ValueError as ex:
            die(str(ex))
        new_html[path] = (patched, orig)

    data = json.load(open(JSON_MIRROR, "r", encoding="utf-8"))
    orig_json = len(data)
    index = {o["verse_number"]: o for o in data}
    for verse in verses:
        n = verse["verse_number"]
        if n not in index:
            die("verse %d missing from %s" % (n, os.path.basename(JSON_MIRROR)))
        for field in FIELDS:
            if field in verse:
                index[n][field] = verse[field]
    if len(data) != orig_json:
        die("JSON mirror entry count changed (%d -> %d)" % (orig_json, len(data)))

    # verify the patched HTML parses and keeps its count, via a temp file
    for path, (patched, orig) in new_html.items():
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(patched)
        try:
            new = node_entry_count(tmp)
        except RuntimeError as ex:
            os.remove(tmp)
            die(str(ex))
        if new != orig:
            os.remove(tmp)
            die("%s entry count changed (%d -> %d) -- aborting"
                % (os.path.basename(path), orig, new))
        new_html[path] = (tmp, orig)  # tmp now holds the verified content

    # ---- phase 2: back up originals and commit the writes ---- #
    ts = timestamp()
    for path, (tmp, orig) in new_html.items():
        bak = "%s.%s.bak" % (path, ts)
        os.replace(path, bak)   # move original aside
        os.replace(tmp, path)   # move verified temp into place
        print("  %-14s patched (%d entries)  backup: %s"
              % (os.path.basename(path), orig, os.path.basename(bak)))

    jbak = "%s.%s.bak" % (JSON_MIRROR, ts)
    os.replace(JSON_MIRROR, jbak)
    with open(JSON_MIRROR, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("  %-14s patched (%d entries)  backup: %s"
          % (os.path.basename(JSON_MIRROR), orig_json, os.path.basename(jbak)))
    print("done.")


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="render PDF pages to PNG")
    r.add_argument("--first", type=int, required=True, help="first page")
    r.add_argument("--last", type=int, required=True, help="last page")
    r.add_argument("--printed", action="store_true",
                   help="treat --first/--last as printed page numbers (adds +%d)"
                        % PAGE_OFFSET)
    r.add_argument("--dpi", type=int, default=200, help="render resolution (default 200)")
    r.set_defaults(func=cmd_render)

    t = sub.add_parser("tantras", help="list tantras with verse ranges/counts")
    t.set_defaults(func=cmd_tantras)

    s = sub.add_parser("scaffold",
                       help="dump current entries for a tantra or verse range")
    s.add_argument("--tantra", help='exact tantra name, e.g. "Tantra Two"')
    s.add_argument("--from", dest="frm", type=int,
                   help="first verse (ignored if --tantra given)")
    s.add_argument("--to", type=int,
                   help="last verse (ignored if --tantra given)")
    s.add_argument("--out", default=None,
                   help="output file (default: <tantra-slug>.json or "
                        "verses_<from>-<to>.json)")
    s.set_defaults(func=cmd_scaffold)

    a = sub.add_parser("apply", help="patch HTML + JSON from an edited JSON file")
    a.add_argument("--in", dest="infile", required=True)
    a.set_defaults(func=cmd_apply)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
