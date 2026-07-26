#!/usr/bin/env python3
"""
build_t9.py -- Rebuild Tantra Nine verse records from Drive-OCR page text.

Reads the per-page .txt files produced by drive_ocr.gs, reassembles them into
verse records in index.html's format, and reports what changed.

Usage (from WSL):
    python3 scripts/build_t9.py --dir _pages_ocr
    python3 scripts/build_t9.py --dir _pages_ocr --first 433 --last 492
    python3 scripts/build_t9.py --dir _pages_ocr --apply      # rewrite index.html

Outputs:
    t9_rebuilt.json   full verse records, ready to review
    t9_report.txt     per-verse CHANGED/SAME plus anything that failed to match

HOW IT WORKS
    The OCR loses reading order: verse numbers land before or after their
    English, and two-column pages interleave. So numbers are NOT trusted as
    the anchor. Instead every Tamil block is fuzzy-matched against the Tamil
    already in index.html (which is correct and correctly numbered), and the
    English that follows a Tamil block is assigned to that block's verse --
    which is exactly how the printed page is laid out:

        <tamil verse>  <number>
        <english title>
        <english translation>

    Pages are concatenated in page order before parsing, so a verse whose
    Tamil ends one page and whose English begins the next still resolves.
"""

import argparse
import difflib
import json
import os
import re
import shutil
import sys
import time

TAMIL_CH = re.compile(r'[஀-௿]')
LATIN_CH = re.compile(r'[A-Za-z]')
VERSE_NUM = re.compile(r'\b([12][0-9]{3}|30[0-9]{2})\b')
# "1. குருமட தரிசனம்" -- a numbered Tamil section heading. Kept short so a
# verse line that happens to start with a digit is not mistaken for one.
SECTION_TA = re.compile(r'^(\d{1,2})\s*[.)]\s*(.{2,40})$')

T9_FIRST, T9_LAST = 2649, 3047      # Tantra Nine proper; 2648 closes Tantra Eight
PARSE_FIRST = 2648                  # include the boundary verse


# ── index.html I/O ───────────────────────────────────────────────────────

def read_embedded_verses(index_path):
    """Pull the EMBEDDED_VERSES array out of index.html."""
    with open(index_path, encoding='utf-8') as f:
        html = f.read()

    decl = html.find('EMBEDDED_VERSES')
    if decl < 0:
        raise SystemExit('EMBEDDED_VERSES not found in ' + index_path)
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
    raise SystemExit('unterminated EMBEDDED_VERSES array')


def write_embedded_verses(index_path, html, start, end, verses):
    """Replace the array in place, keeping a timestamped backup."""
    backup = '%s.%s.bak' % (index_path, time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(index_path, backup)
    payload = json.dumps(verses, ensure_ascii=False, separators=(',', ':'))
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html[:start] + payload + html[end + 1:])
    return backup


# ── page text -> token stream ────────────────────────────────────────────

def page_files(directory, first, last):
    """The pg-NNN.txt files in numeric page order."""
    found = []
    for name in os.listdir(directory):
        m = re.match(r'pg-0*(\d+)\.txt$', name)
        if not m:
            continue
        n = int(m.group(1))
        if first <= n <= last:
            found.append((n, os.path.join(directory, name)))
    found.sort()
    return found


def is_section_heading(text):
    """Section names are printed in full caps; verse titles are title case."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return False
    if 'TANTRA' in text.upper():          # running page header, not a section
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.85


def clean_line(line):
    """Drop running headers and bare page numbers."""
    s = line.strip()
    if not s:
        return ''
    if re.fullmatch(r'\d{1,3}', s):                       # page folio
        return ''
    if re.search(r'Tantra\s+(Eight|Nine)\s+Concluded', s, re.I):
        return ''
    if 'முடிவு' in s and 'பெற்றது' in s:      # "<n>th Tantra concluded"
        return ''
    # OCR reads the ordinal's final consonant as either ம் or ந்.
    s = re.sub(r'(ஒன்பதா[ம்ந்]+|எட்டா[ம்ந்]+)\s*தந்திரம்', ' ', s)
    s = re.sub(r'TANTRA\s+(NINE|EIGHT)', ' ', s, flags=re.I)
    # Verso running head. In caps, so is_section_heading() would otherwise
    # adopt it as a section name for every verse on the page.
    s = re.sub(r'TIRUMANTIRAM', ' ', s, flags=re.I)
    s = re.sub(r'திருமந்திரம்', ' ', s)
    return s.strip()


def split_runs(line):
    """Split a line into Tamil / Latin runs, keeping punctuation attached."""
    runs = []
    buf = ''
    mode = None
    for ch in line:
        if TAMIL_CH.match(ch):
            new = 'ta'
        elif LATIN_CH.match(ch):
            new = 'en'
        else:
            buf += ch                    # neutral: spaces, digits, punctuation
            continue
        if mode is None:
            mode = new
        elif new != mode:
            runs.append((mode, buf))
            buf = ''
            mode = new
        buf += ch
    if mode is not None:
        runs.append((mode, buf))
    return runs


def tokenize(pages):
    """
    Turn all pages into a flat stream of ('ta'|'en'|'num'|'sec_en'|'sec_ta', v).
    Numbers are lifted out of whatever run they were glued to.
    """
    stream = []
    for _, path in pages:
        with open(path, encoding='utf-8') as f:
            for raw in f:
                line = clean_line(raw)
                if not line:
                    continue

                for mode, text in split_runs(line):
                    nums = VERSE_NUM.findall(text)
                    text = VERSE_NUM.sub(' ', text)
                    text = re.sub(r'\s+', ' ', text).strip(' .,;:')

                    # Section headings are detected per run, not per line: the
                    # Tamil heading and its English caps heading often share
                    # one OCR line ("13.ஊழ் FATE").
                    m = SECTION_TA.match(text) if mode == 'ta' else None
                    if m and TAMIL_CH.search(m.group(2)):
                        stream.append(('sec_ta', m.group(2).strip()))
                    elif mode == 'en' and re.fullmatch(r'T\s*[-~.]?\s*\d{1,3}', text):
                        pass            # running-head artifact, e.g. "T-57"
                    elif mode == 'en' and is_section_heading(text):
                        stream.append(('sec_en', text))
                    elif text and len(text) > 1:
                        stream.append((mode, text))
                    for n in nums:
                        stream.append(('num', int(n)))
    return stream


# ── token stream -> verse blocks ─────────────────────────────────────────

def group_blocks(stream):
    """
    A block starts at each Tamil run and collects the English runs that follow
    it, plus the first verse number seen. Consecutive Tamil runs are joined:
    a verse's four lines may be split across OCR lines.
    """
    blocks = []
    cur = None
    for kind, val in stream:
        if kind == 'ta':
            if cur is not None and not cur['en'] and cur['num'] is None:
                cur['ta'] += ' ' + val        # same verse, wrapped
                continue
            cur = {'ta': val, 'num': None, 'en': [], 'sec_en': None, 'sec_ta': None}
            blocks.append(cur)
        elif kind == 'num':
            if cur is not None and cur['num'] is None:
                cur['num'] = val
        elif kind == 'en':
            if cur is not None:
                cur['en'].append(val)
        elif kind in ('sec_en', 'sec_ta'):
            # Headings apply to the verses that follow.
            blocks.append({'ta': None, 'num': None, 'en': [],
                           'sec_en': val if kind == 'sec_en' else None,
                           'sec_ta': val if kind == 'sec_ta' else None})
            cur = None
    return blocks


def norm_tamil(s):
    """Comparable form: Tamil letters only."""
    return ''.join(TAMIL_CH.findall(s or ''))


MATCH_MIN = 0.70        # accept a Tamil block as this verse at or above this
HINT_MIN = 0.60         # lower bar when the page's own number agrees


def match_verse(block_ta, candidates, hint=None):
    """
    Best-matching verse number for a Tamil block. `candidates` maps
    verse_number -> normalised Tamil. A number read off the page is used as a
    hint but never overrides a clearly better text match.

    No prefix screening: the printed edition breaks words differently from
    index.html (`மூல னுரைசெய்த` vs `மூலன் உரைசெய்த`), so the leading
    characters routinely disagree even for a perfect match. difflib's own
    quick_ratio/real_quick_ratio are the screen instead -- they are upper
    bounds on ratio(), so skipping on them can never discard a real match.
    """
    target = norm_tamil(block_ta)
    if len(target) < 8:
        return None, 0.0

    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(target)     # difflib caches seq2, so set it once

    def cover(text):
        """
        Fraction of THIS BLOCK's characters found in `text`, in order.
        Coverage, not similarity: a two-column page break can split one
        verse's Tamil into two blocks, and each half must still match the
        verse it came from even though it is only half its length.
        """
        sm.set_seq1(text)
        if sm.real_quick_ratio() < 0.4:
            return 0.0
        return sum(m.size for m in sm.get_matching_blocks()) / len(target)

    if hint in candidates:
        c = cover(candidates[hint])
        if c >= HINT_MIN:
            return hint, c

    best, best_c = None, 0.0
    for num, text in candidates.items():
        if len(text) + 24 < len(target):    # too short to contain the block
            continue
        c = cover(text)
        if c > best_c:
            best, best_c = num, c
    if best_c < MATCH_MIN:
        return None, best_c
    return best, best_c


# ── main ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', required=True, help='folder of pg-NNN.txt OCR files')
    ap.add_argument('--index', default='index.html')
    ap.add_argument('--first', type=int, default=433, help='first page to read')
    ap.add_argument('--last', type=int, default=492, help='last page to read')
    ap.add_argument('--out', default='t9_rebuilt.json')
    ap.add_argument('--report', default='t9_report.txt')
    ap.add_argument('--manual', default=None,
                    help='JSON list of hand-verified partial records to merge '
                         'over the OCR result (for pages the OCR missed)')
    ap.add_argument('--apply', action='store_true',
                    help='write the rebuilt records back into index.html')
    args = ap.parse_args()

    html, start, end, verses = read_embedded_verses(args.index)
    by_num = {int(v['verse_number']): v for v in verses
              if str(v.get('verse_number', '')).lstrip('-').isdigit()}

    candidates = {n: norm_tamil(v.get('tamil'))
                  for n, v in by_num.items()
                  if PARSE_FIRST <= n <= T9_LAST and norm_tamil(v.get('tamil'))}
    if not candidates:
        raise SystemExit('no Tamil found for verses %d-%d in %s'
                         % (PARSE_FIRST, T9_LAST, args.index))

    pages = page_files(args.dir, args.first, args.last)
    if not pages:
        raise SystemExit('no pg-NNN.txt files in %s for pages %d-%d'
                         % (args.dir, args.first, args.last))
    print('reading %d page files: pg-%03d .. pg-%03d'
          % (len(pages), pages[0][0], pages[-1][0]))

    blocks = group_blocks(tokenize(pages))

    section_en, section_ta = '', ''
    rebuilt, unmatched, weak, fragments = {}, [], [], []

    for b in blocks:
        if b['ta'] is None:
            if b['sec_en']:
                section_en = b['sec_en']
            if b['sec_ta']:
                section_ta = b['sec_ta']
            continue

        num, score = match_verse(b['ta'], candidates, b['num'])
        if num is None:
            # Short leftovers are headings or line fragments, not lost verses;
            # keep them out of the failure list so real misses stand out.
            if len(norm_tamil(b['ta'])) < 25:
                fragments.append(b['ta'][:50])
            else:
                unmatched.append((b['num'], b['ta'][:60], round(score, 2)))
            continue
        if score < 0.85:
            weak.append((num, round(score, 2)))

        if num in rebuilt:
            # A second block for a verse already seen: its Tamil was split by a
            # column break. Fold this block's English into the existing record
            # rather than overwriting it.
            prev, extra = rebuilt[num], list(b['en'])
            if extra and not prev['english_title']:
                prev['english_title'] = extra.pop(0)
            if extra:
                prev['english_translation'] = (
                    prev['english_translation'] + '\n' + '\n'.join(extra)).strip()
            continue

        title = b['en'][0] if b['en'] else ''
        body = '\n'.join(b['en'][1:]) if len(b['en']) > 1 else ''

        old = by_num[num]
        rebuilt[num] = {
            'verse_number': num,
            'tamil': old.get('tamil', ''),          # trusted, not re-OCR'd
            'tamil_title': section_ta,
            'english_title': title,
            'english_translation': body,
            'notes': old.get('notes', ''),          # preserved
            'section': section_en or old.get('section', ''),
            'tantra': 'Tantra Eight' if num <= 2648 else 'Tantra Nine',
        }

    # ── hand-verified patches win over the OCR ──
    if args.manual:
        with open(args.manual, encoding='utf-8') as f:
            patches = json.load(f)
        for patch in patches:
            n = int(patch['verse_number'])
            old = by_num.get(n, {})
            base = rebuilt.get(n) or {
                'verse_number': n,
                'tamil': old.get('tamil', ''),
                'tamil_title': '',
                'english_title': '',
                'english_translation': '',
                'notes': old.get('notes', ''),
                'section': old.get('section', ''),
                'tantra': 'Tantra Eight' if n <= 2648 else 'Tantra Nine',
            }
            base.update({k: v for k, v in patch.items() if k != 'verse_number'})
            rebuilt[n] = base
        print('merged %d hand-verified records from %s'
              % (len(patches), args.manual))

    # ── report ──
    lines = []
    changed = same = empty = 0
    for n in sorted(rebuilt):
        new, old = rebuilt[n], by_num[n]
        if not new['english_translation']:
            empty += 1
            lines.append('%d  EMPTY-ENGLISH  title=%r' % (n, new['english_title']))
            continue
        if (new['english_title'].strip() != (old.get('english_title') or '').strip()
                or new['english_translation'].strip()
                != (old.get('english_translation') or '').strip()):
            changed += 1
            lines.append('%d  CHANGED' % n)
            lines.append('    old title: %s' % (old.get('english_title') or ''))
            lines.append('    new title: %s' % new['english_title'])
        else:
            same += 1
            lines.append('%d  same' % n)

    missing = [n for n in sorted(candidates) if n not in rebuilt]
    if missing:
        lines.append('\nNOT REBUILT (%d): %s'
                     % (len(missing), ', '.join(map(str, missing))))
    if unmatched:
        lines.append('\nUNMATCHED TAMIL BLOCKS (%d):' % len(unmatched))
        for num, snippet, score in unmatched:
            lines.append('    num=%s score=%.2f  %s' % (num, score, snippet))
    if weak:
        lines.append('\nWEAK MATCHES, verify these (%d):' % len(weak))
        for n, s in weak:
            lines.append('    %d  score=%.2f' % (n, s))
    if fragments:
        lines.append('\nSHORT BLOCKS IGNORED (%d) -- headings/fragments:'
                     % len(fragments))
        for text in fragments:
            lines.append('    %s' % text)

    with open(args.report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump([rebuilt[n] for n in sorted(rebuilt)], f,
                  ensure_ascii=False, indent=1)
        f.write('\n')

    print('rebuilt %d verses: %d changed, %d unchanged, %d empty English'
          % (len(rebuilt), changed, same, empty))
    print('not rebuilt: %d   unmatched blocks: %d   weak matches: %d'
          % (len(missing), len(unmatched), len(weak)))
    print('wrote %s and %s' % (args.out, args.report))

    if not args.apply:
        print('\nreview the JSON, then re-run with --apply to update index.html')
        return

    # Only write verses that came out complete. Incomplete ones are left
    # exactly as they are so a partial parse can never destroy good data.
    incomplete = sorted(n for n, v in rebuilt.items()
                        if not v['english_title'].strip()
                        or not v['english_translation'].strip())
    if incomplete:
        print('\nskipping %d incomplete verses, left untouched in index.html:'
              % len(incomplete))
        print('  ' + ', '.join(map(str, incomplete)))

    written = 0
    for i, v in enumerate(verses):
        n = v.get('verse_number')
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n in rebuilt and n not in incomplete:
            verses[i] = rebuilt[n]
            written += 1
    print('writing %d verses' % written)

    backup = write_embedded_verses(args.index, html, start, end, verses)
    print('applied to %s (backup: %s)' % (args.index, backup))


if __name__ == '__main__':
    main()
