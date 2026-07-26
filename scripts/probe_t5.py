import json, sys
data = json.load(open("thirumanthiram_verses.json", encoding="utf-8"))
verses = data if isinstance(data, list) else (data.get("verses") or data.get("EMBEDDED_VERSES"))
print("total entries:", len(verses))
by = {v["verse_number"]: v for v in verses}
nums = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [1495, 1525, 1536, 1429, 1430]
for n in nums:
    v = by.get(n, {})
    print("----", n, "----")
    print("  title:", (v.get("english_title", "") or "")[:75])
    print("  tr   :", (v.get("english_translation", "") or "")[:90].replace("\n", " / "))
