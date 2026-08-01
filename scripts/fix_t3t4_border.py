#!/usr/bin/env python3
"""
fix_t3t4_border.py -- move the 6 Chandra-Yoga verses (878-883) that spilled
across the T3/T4 border back into Tantra Three, section CHANDRA YOGA.

Only touches the `tantra` and `section` fields (extract_verses.apply refuses
these), scoped to verses 878-883, in all three files. Keeps each verse's own
english_title/translation/notes. Verifies parse + entry count, backs up.

    wsl python3 fix_t3t4_border.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_verses as ev

VERSES = list(range(873, 884))          # 873..883 inclusive (whole spilled run)
SET = {"tantra": "Tantra Three", "section": "CHANDRA YOGA"}
# Idempotent: sets both fields to the canonical values regardless of prior
# value, so it also (a) fixes the 876 "CHANDRA TOGA" typo and (b) repairs
# flipbook.html's stale 873-877 = Tantra Four/AJAPA divergence from index.html.


def patch_blob(blob, path):
    for n in VERSES:
        span = ev.verse_span(blob, n)
        if span is None:
            raise ValueError("verse %d not found in %s" % (n, path))
        s, e = span
        chunk = blob[s:e]
        for field, val in SET.items():
            repl = '"%s":%s' % (field, json.dumps(val, ensure_ascii=False))
            chunk, cnt = ev._field_re(field).subn(lambda _m: repl, chunk, count=1)
            if cnt != 1:
                raise ValueError('field "%s" not found for verse %d in %s'
                                 % (field, n, path))
        blob = blob[:s] + chunk + blob[e:]
    return blob


def patch_html_file(path):
    html = ev.read_text(path)
    a, b = ev.extract_blob_span(html)
    new_blob = patch_blob(html[a:b + 1], os.path.basename(path))
    return html[:a] + new_blob + html[b + 1:]


def main():
    # ---- phase 1: build + verify in memory ---- #
    new_html = {}
    for path in ev.HTML_FILES:
        orig = ev.node_entry_count(path)
        patched = patch_html_file(path)
        new_html[path] = (patched, orig)

    data = json.load(open(ev.JSON_MIRROR, encoding="utf-8"))
    orig_json = len(data)
    idx = {o["verse_number"]: o for o in data}
    for n in VERSES:
        if n not in idx:
            ev.die("verse %d missing from JSON mirror" % n)
        idx[n].update(SET)
    if len(data) != orig_json:
        ev.die("JSON mirror count changed")

    for path, (patched, orig) in new_html.items():
        tmp = path + ".tmp"
        open(tmp, "w", encoding="utf-8").write(patched)
        new = ev.node_entry_count(tmp)
        if new != orig:
            os.remove(tmp)
            ev.die("%s count changed %d->%d" % (os.path.basename(path), orig, new))
        new_html[path] = (tmp, orig)

    # ---- phase 2: back up + commit ---- #
    ts = ev.timestamp()
    for path, (tmp, orig) in new_html.items():
        bak = "%s.%s.bak" % (path, ts)
        os.replace(path, bak)
        os.replace(tmp, path)
        print("  %-14s patched (%d entries)  backup: %s"
              % (os.path.basename(path), orig, os.path.basename(bak)))

    jbak = "%s.%s.bak" % (ev.JSON_MIRROR, ts)
    os.replace(ev.JSON_MIRROR, jbak)
    with open(ev.JSON_MIRROR, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("  %-14s patched (%d entries)  backup: %s"
          % (os.path.basename(ev.JSON_MIRROR), orig_json, os.path.basename(jbak)))
    print("done. moved verses %d-%d -> %s" % (VERSES[0], VERSES[-1], SET))


if __name__ == "__main__":
    main()
