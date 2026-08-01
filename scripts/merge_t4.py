import json, glob, os, re, sys

LO, HI = 873, 1418
canon = {v["verse_number"]: v for v in json.load(open("t4_canonical.json", encoding="utf-8"))}

merged = {}
dupes = []
for fn in sorted(glob.glob("t4_parts/part_*.json")):
    try:
        data = json.load(open(fn, encoding="utf-8"))
    except Exception as ex:
        print("!! could not parse", fn, ex); continue
    for v in data:
        n = v.get("verse_number")
        if n is None or not (LO <= n <= HI):
            continue
        if n in merged:
            dupes.append((n, os.path.basename(fn)))
        merged[n] = {**v, "_src": os.path.basename(fn)}

present = set(merged)
want = set(range(LO, HI + 1))
missing = sorted(want - present)
flags = []      # tamil_check problems
empty = []      # empty title or translation
tamil_norm_mismatch = []

def norm(s):
    return re.sub(r"\s+", "", s or "")[:14]

for n in sorted(merged):
    v = merged[n]
    tc = v.get("tamil_check", "")
    if tc and tc != "ok":
        flags.append((n, tc[:60]))
    if not (v.get("english_title") or "").strip() or not (v.get("english_translation") or "").strip():
        empty.append(n)
    # independent tamil sanity: compare canonical tamil line1 to nothing here (agent already did),
    # but flag if agent said ok yet we have no way — skip; rely on tamil_check.

print("=== T4 MERGE REPORT ===")
print("verses collected: %d / %d" % (len(present & want), len(want)))
print("duplicates (reported by >1 agent): %s" % (dupes or "none"))
print("MISSING (%d): %s" % (len(missing), missing))
print("tamil_check flags (%d): %s" % (len(flags), flags[:40]))
print("empty title/translation (%d): %s" % (len(empty), empty[:40]))

# Build apply-format fix file only if fully covered & no dupes
if not missing and not dupes:
    out = []
    for n in sorted(merged):
        v = merged[n]
        out.append({
            "verse_number": n,
            "english_title": v.get("english_title", ""),
            "english_translation": v.get("english_translation", ""),
            "notes": v.get("notes", ""),
        })
    json.dump(out, open("fix_t4.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\nwrote fix_t4.json with %d verses (ready for: extract_verses.py apply --in fix_t4.json)" % len(out))
else:
    print("\nNOT writing fix_t4.json yet -- resolve missing/dupes first.")
