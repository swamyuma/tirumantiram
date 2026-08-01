import json, sys
sys.path.insert(0, ".")
import extract_verses as ev
blob = ev._load_blob()
out = []
for n, s, e in ev.iter_verses(blob):
    if 873 <= n <= 1418:
        ch = blob[s:e]
        out.append({
            "verse_number": n,
            "tamil": ev._field_value(ch, "tamil") or "",
            "cur_title": ev._field_value(ch, "english_title") or "",
        })
json.dump(out, open("t4_canonical.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("dumped", len(out), "verses ->", out[0]["verse_number"], "..", out[-1]["verse_number"])
