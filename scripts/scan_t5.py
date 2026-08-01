import json, re
data = json.load(open("thirumanthiram_verses.json", encoding="utf-8"))
verses = data if isinstance(data, list) else (data.get("verses") or data.get("EMBEDDED_VERSES"))
by = {v["verse_number"]: v for v in verses}

LO, HI = 1419, 1572

def is_bad(v):
    t = (v.get("english_title", "") or "").strip()
    tr = (v.get("english_translation", "") or "").strip()
    reasons = []
    # title looks like a page/verse number or junk
    if re.fullmatch(r"[\d\-\.\s]+", t):
        reasons.append("num-title")
    if len(t) < 3:
        reasons.append("short-title")
    if not tr:
        reasons.append("empty-tr")
    # title text appears inside translation (merge artifact)
    if t and len(t) > 8 and t.lower() in tr.lower()[:len(t)+40]:
        reasons.append("title-in-tr")
    # non-latin junk in title
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
        print(f"{n}: {','.join(r):20s} | title={ (v.get('english_title','') or '')[:45]!r}")
print("\nFLAGGED:", flagged)
print("count:", len(flagged))
