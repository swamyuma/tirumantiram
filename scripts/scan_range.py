#!/usr/bin/env python3
"""scan_range.py LO HI -- flag OCR-garbage verses in [LO,HI] (same heuristics
as scan_t5.py, generalized). Reads the JSON mirror in the repo root."""
import json, re, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data = json.load(open(os.path.join(ROOT, "thirumanthiram_verses.json"), encoding="utf-8"))
verses = data if isinstance(data, list) else (data.get("verses") or data.get("EMBEDDED_VERSES"))
by = {v["verse_number"]: v for v in verses}

LO, HI = int(sys.argv[1]), int(sys.argv[2])

def is_bad(v):
    t = (v.get("english_title", "") or "").strip()
    tr = (v.get("english_translation", "") or "").strip()
    reasons = []
    if re.fullmatch(r"[\d\-\.\s]+", t):
        reasons.append("num-title")
    if len(t) < 3:
        reasons.append("short-title")
    if not tr:
        reasons.append("empty-tr")
    if t and len(t) > 8 and t.lower() in tr.lower()[:len(t)+40]:
        reasons.append("title-in-tr")
    if re.search(r"[஀-௿]", t):
        reasons.append("tamil-in-title")
    return reasons

flagged = []
for n in range(LO, HI + 1):
    v = by.get(n)
    if not v:
        print("MISSING", n); continue
    r = is_bad(v)
    if r:
        flagged.append(n)
        print(f"{n}: {','.join(r):20s} | title={ (v.get('english_title','') or '')[:50]!r}")
print("\nFLAGGED:", flagged)
print("count:", len(flagged))
