#!/usr/bin/env python3
"""
gen_tantra_map.py — generate a section/verse map markdown for a given Tantra.

Usage:
    python3 gen_tantra_map.py [tantra_name] [output_file]

Defaults:
    tantra_name  = "Tantra Two"
    output_file  = tantra2_map.md  (written next to this script's parent dir)

Examples:
    python3 gen_tantra_map.py "Tantra Two" tantra2_map.md
    python3 gen_tantra_map.py "Tantra One" tantra1_map.md
"""

import json
import sys
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tirumantiram/
VERSES_FILE = os.path.join(BASE, 'thirumanthiram_verses.json')

# --- Args ---
tantra_name = sys.argv[1] if len(sys.argv) > 1 else 'Tantra Two'
output_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, 'tantra2_map.md')
if not os.path.isabs(output_file):
    output_file = os.path.join(BASE, output_file)

# --- Load data ---
with open(VERSES_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

verses = [v for v in data if v.get('tantra') == tantra_name]

if not verses:
    print(f'ERROR: No verses found for tantra="{tantra_name}"')
    print('Available tantras:', sorted(set(v.get('tantra','') for v in data)))
    sys.exit(1)

# --- Build section map ---
seen = {}
order = []
for v in verses:
    s = v.get('section', '')
    if s not in seen:
        seen[s] = {
            'first_verse': v['verse_number'],
            'last_verse':  v['verse_number'],
            'count':       0,
            'intro_note':  v.get('notes', ''),
            'verses':      []
        }
        order.append(s)
    seen[s]['last_verse'] = v['verse_number']
    seen[s]['count'] += 1
    seen[s]['verses'].append({
        'verse':        v['verse_number'],
        'english_title': v.get('english_title', ''),
        'tamil_line1':  v.get('tamil', '').split('\n')[0] if v.get('tamil') else ''
    })

first_v = verses[0]['verse_number']
last_v  = verses[-1]['verse_number']
total   = len(verses)
n_secs  = len(order)

# Tamil tantra name map
tamil_names = {
    'Tantra One':   'முதல் தந்திரம் (Muthal Tantiram)',
    'Tantra Two':   'இரண்டாம் தந்திரம் (Irantam Tantiram)',
    'Tantra Three': 'மூன்றாம் தந்திரம் (Munram Tantiram)',
    'Tantra Four':  'நான்காம் தந்திரம் (Nankam Tantiram)',
    'Tantra Five':  'ஐந்தாம் தந்திரம் (Aintam Tantiram)',
    'Tantra Six':   'ஆறாம் தந்திரம் (Aram Tantiram)',
    'Tantra Seven': 'ஏழாம் தந்திரம் (Ezam Tantiram)',
    'Tantra Eight': 'எட்டாம் தந்திரம் (Ettam Tantiram)',
    'Tantra Nine':  'ஒன்பதாம் தந்திரம் (Onpatam Tantiram)',
}
tamil_label = tamil_names.get(tantra_name, tantra_name)

# --- Build markdown ---
lines = []
lines.append(f'# {tantra_name} — Section & Verse Map')
lines.append('')
lines.append(f'**Tantra:** {tantra_name} · {tamil_label}')
lines.append(f'**Verses:** {first_v}–{last_v} · {total} verses total · {n_secs} sections')
lines.append('')
lines.append('---')
lines.append('')

# Summary table
lines.append('## Summary Table')
lines.append('')
lines.append('| # | Section (English) | Verses | Count |')
lines.append('|---|-------------------|--------|-------|')
for i, s in enumerate(order, 1):
    info = seen[s]
    vrange = str(info['first_verse'])
    if info['last_verse'] != info['first_verse']:
        vrange += '–' + str(info['last_verse'])
    lines.append(f"| {i} | {s.title()} | {vrange} | {info['count']} |")
lines.append('')
lines.append('---')
lines.append('')

# Detailed breakdown
lines.append('## Detailed Section Breakdown')
lines.append('')
for i, s in enumerate(order, 1):
    info = seen[s]
    vrange = str(info['first_verse'])
    if info['last_verse'] != info['first_verse']:
        vrange += '–' + str(info['last_verse'])
    count_str = str(info['count']) + ' verse' + ('s' if info['count'] > 1 else '')
    lines.append(f'### {i}. {s.title()}')
    lines.append('')
    lines.append(f'**Verses:** {vrange}   ·   {count_str}')
    if info['intro_note']:
        lines.append('')
        lines.append('> ' + info['intro_note'])
    lines.append('')
    lines.append('| Verse | English Title | Tamil (First Line) |')
    lines.append('|------:|--------------|-------------------|')
    for vv in info['verses']:
        lines.append(f"| {vv['verse']} | {vv['english_title']} | {vv['tamil_line1']} |")
    lines.append('')

# --- Write output ---
with open(output_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f'Done — {tantra_name}: {total} verses, {n_secs} sections')
print(f'Written to: {output_file}')
