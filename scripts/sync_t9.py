#!/usr/bin/env python3
"""
sync_t9.py -- Propagate the repaired Tantra Nine records from index.html into
the other two copies of the verse data: flipbook.html and
thirumanthiram_verses.json.

build_t9.py only writes index.html. The reader ships three copies of the same
data, so they must be kept in step or the flipbook shows the old drifted text.

Only these fields are copied, for verses 2648-3047:
    english_title, english_translation, section, tamil_title, tantra
`tamil` and `notes` are left alone in every file.

Usage (from WSL):
    python3 scripts/sync_t9.py
    python3 scripts/sync_t9.py --apply
"""

import argparse
import json
import shutil
import time

FIRST, LAST = 2648, 3047
FIELDS = ('english_title', 'english_translation', 'section', 'tamil_title',
          'tantra')


def find_array(html):
    """Locate the EMBEDDED_VERSES array; return (start, end_inclusive)."""
    decl = html.find('EMBEDDED_VERSES')
    if decl < 0:
        return None, None
    start = html.index('[', decl)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        c = html[i]
        if esc:
            esc = False
            continue
        if c == '\\':
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                return start, i
    return None, None


def load_html(path):
    with open(path, encoding='utf-8') as f:
        html = f.read()
    start, end = find_array(html)
    if start is None:
        raise SystemExit('EMBEDDED_VERSES not found in ' + path)
    return html, start, end, json.loads(html[start:end + 1])


def patch(records, source):
    """Copy FIELDS from `source` (num -> record) into `records`. Returns count."""
    changed = 0
    for v in records:
        try:
            n = int(v.get('verse_number'))
        except (TypeError, ValueError):
            continue
        if not (FIRST <= n <= LAST) or n not in source:
            continue
        src = source[n]
        before = {k: v.get(k) for k in FIELDS}
        for k in FIELDS:
            if k in src:
                v[k] = src[k]
        if any(v.get(k) != before[k] for k in FIELDS):
            changed += 1
    return changed


def backup(path):
    dest = '%s.%s.bak' % (path, time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(path, dest)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', default='index.html')
    ap.add_argument('--flipbook', default='flipbook.html')
    ap.add_argument('--json', default='thirumanthiram_verses.json')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    _, _, _, src_records = load_html(args.index)
    source = {}
    for v in src_records:
        try:
            n = int(v.get('verse_number'))
        except (TypeError, ValueError):
            continue
        if FIRST <= n <= LAST:
            source[n] = v
    print('source: %d T9 records from %s' % (len(source), args.index))

    # ── flipbook.html ──
    html, start, end, records = load_html(args.flipbook)
    n_before = len(records)
    changed = patch(records, source)
    print('%s: %d of %d records would change' % (args.flipbook, changed, n_before))
    if args.apply and changed:
        payload = json.dumps(records, ensure_ascii=False, separators=(',', ':'))
        if len(records) != n_before:
            raise SystemExit('record count changed -- refusing to write')
        dest = backup(args.flipbook)
        with open(args.flipbook, 'w', encoding='utf-8') as f:
            f.write(html[:start] + payload + html[end + 1:])
        print('  written (backup: %s)' % dest)

    # ── thirumanthiram_verses.json ──
    with open(args.json, encoding='utf-8') as f:
        data = json.load(f)
    records = data['verses'] if isinstance(data, dict) and 'verses' in data else data
    n_before = len(records)
    changed = patch(records, source)
    print('%s: %d of %d records would change' % (args.json, changed, n_before))
    if args.apply and changed:
        if len(records) != n_before:
            raise SystemExit('record count changed -- refusing to write')
        dest = backup(args.json)
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write('\n')
        print('  written (backup: %s)' % dest)

    if not args.apply:
        print('\nre-run with --apply to write')


if __name__ == '__main__':
    main()
