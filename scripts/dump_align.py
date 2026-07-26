#!/usr/bin/env python3
"""dump_align.py -- dump per-tantra alignment-check slices for the drift map.

For each verse writes: number, Tamil quatrain, currently-stored English title,
and the first ~2 lines of the stored English translation. A Tamil-reading agent
compares english[N] against tamil[N] (and neighbours) to find the local
english-vs-Tamil offset. Output: one .txt per chunk under OUTDIR."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_align")
d = json.load(open(os.path.join(ROOT, "thirumanthiram_verses.json"), encoding="utf-8"))
by = {v["verse_number"]: v for v in d}

# (name, lo, hi, chunk_size) -- split big tantras so each agent gets <= ~260 verses
TANTRAS = [("T1",113,327),("T2",328,548),("T3",549,883),("T4",884,1418),
           ("T5",1419,1572),("T6",1573,1705),("T7",1706,2123),
           ("T8",2124,2647),("T9",2648,3047)]
CHUNK = 260

os.makedirs(OUTDIR, exist_ok=True)
manifest = []
for name, lo, hi in TANTRAS:
    verses = [n for n in range(lo, hi+1) if n in by]
    for ci in range(0, len(verses), CHUNK):
        chunk = verses[ci:ci+CHUNK]
        # include 3 verses of left context (for offset detection at the top edge)
        ctx_lo = max(lo, chunk[0]-3)
        alln = [n for n in range(ctx_lo, chunk[-1]+1) if n in by]
        label = "%s_%d_%d" % (name, chunk[0], chunk[-1])
        path = os.path.join(OUTDIR, "align_%s.txt" % label)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# %s verses %d-%d (context from %d)\n\n" % (name, chunk[0], chunk[-1], ctx_lo))
            for n in alln:
                v = by[n]
                tamil = " / ".join((v.get("tamil","") or "").split("\n"))
                title = (v.get("english_title","") or "").replace("\n"," ")
                tr = (v.get("english_translation","") or "").split("\n")
                tr1 = " / ".join([x for x in tr if x.strip()][:2])
                fh.write("[%d]\n  TA: %s\n  EN_TITLE: %s\n  EN_TR: %s\n\n" % (n, tamil, title, tr1[:160]))
        manifest.append((label, chunk[0], chunk[-1], len(chunk)))

print("wrote %d chunk files to %s" % (len(manifest), OUTDIR))
for label, a, b, cnt in manifest:
    print("  %-14s %d-%d (%d verses)" % (label, a, b, cnt))
