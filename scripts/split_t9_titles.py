#!/usr/bin/env python3
"""
split_t9_titles.py -- Repair verse titles that swallowed the first lines of
their translation.

Drive's OCR sometimes puts a verse's title and the opening of its translation
on one line, so build_t9.py cannot tell where the title ends and stores the
whole run as english_title.

The pre-rebuild data is the cure: its titles came from a properly line-split
source, so every clean title exists there as a string -- just, for drifted
verses, filed under the wrong verse number. So for each over-long title we
look for the longest known title that is a prefix of it, cut there, and push
the remainder back onto the front of the translation.

Usage (from WSL):
    python3 scripts/split_t9_titles.py --backup index.html.20260725-165811.bak
    python3 scripts/split_t9_titles.py --backup <file> --apply
"""

import argparse
import json
import re
import shutil
import time

FIRST, LAST = 2648, 3047
LONG_TITLE = 45          # titles longer than this are suspect (median is 30)
MIN_PREFIX = 10          # ignore absurdly short prefix matches


def load(path):
    with open(path, encoding='utf-8') as f:
        html = f.read()
    decl = html.find('EMBEDDED_VERSES')
    if decl < 0:
        raise SystemExit('EMBEDDED_VERSES not found in ' + path)
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
                return html, start, i, json.loads(html[start:i + 1])
    raise SystemExit('unterminated array in ' + path)


def norm(s):
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


def cut_at(original, n_norm):
    """Cut `original` after its first n_norm normalised characters."""
    seen = 0
    for i, ch in enumerate(original):
        if re.match(r'[A-Za-z0-9]', ch):
            seen += 1
            if seen == n_norm:
                return original[:i + 1], original[i + 1:]
    return original, ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backup', required=True,
                    help='pre-rebuild index.html.*.bak holding clean titles')
    ap.add_argument('--index', default='index.html')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    _, _, _, old = load(args.backup)
    known = []
    for v in old:
        t = (v.get('english_title') or '').strip()
        if len(norm(t)) >= MIN_PREFIX:
            known.append((norm(t), t))
    # Longest first, so the most specific title wins.
    known.sort(key=lambda p: -len(p[0]))
    print('known clean titles: %d' % len(known))

    html, start, end, verses = load(args.index)

    fixed, unfixed = [], []
    for v in verses:
        try:
            n = int(v.get('verse_number'))
        except (TypeError, ValueError):
            continue
        if not (FIRST <= n <= LAST):
            continue
        title = (v.get('english_title') or '').strip()
        if len(title) <= LONG_TITLE:
            continue

        nt = norm(title)
        hit = None
        for kn, kt in known:
            if len(kn) < len(nt) and nt.startswith(kn):
                hit = kn
                break
        if hit is None:
            unfixed.append((n, len(title)))
            continue

        head, tail = cut_at(title, len(hit))
        tail = tail.strip(' .;,')
        if not tail:
            unfixed.append((n, len(title)))
            continue

        body = (v.get('english_translation') or '').strip()
        v['english_title'] = head.strip()
        v['english_translation'] = (tail + '\n' + body).strip() if body else tail
        fixed.append((n, head.strip()))

    print('\nsplit %d titles:' % len(fixed))
    for n, t in fixed[:20]:
        print('  %d  %s' % (n, t))
    if len(fixed) > 20:
        print('  ... and %d more' % (len(fixed) - 20))
    if unfixed:
        print('\nstill long, no known prefix matched (%d):' % len(unfixed))
        for n, ln in unfixed:
            print('  %d  (%d chars)' % (n, ln))

    if not args.apply:
        print('\nre-run with --apply to write these changes')
        return

    dest = '%s.%s.bak' % (args.index, time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(args.index, dest)
    payload = json.dumps(verses, ensure_ascii=False, separators=(',', ':'))
    with open(args.index, 'w', encoding='utf-8') as f:
        f.write(html[:start] + payload + html[end + 1:])
    print('\napplied to %s (backup: %s)' % (args.index, dest))


if __name__ == '__main__':
    main()
