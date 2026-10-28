"""Step 10: regenerate twice with the same seed and compare row counts + SHA-256 checksums.
Usage: python scripts/reproduce.py --scale starter"""
import argparse, json, shutil, sys, tempfile, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.pipeline import run
from config.settings import SEED, SCALES
ap = argparse.ArgumentParser(); ap.add_argument("--scale", default="starter", choices=SCALES); ap.add_argument("--seed", type=int, default=SEED); a = ap.parse_args()
res = []
for k in (1, 2):
    d = tempfile.mkdtemp(prefix=f"repro{k}_"); _, m = run(a.scale, d, a.seed); res.append({f["file"]: (f["rows"], f["sha256"]) for f in m["files"]}); shutil.rmtree(d)
bad = [f for f in res[0] if res[0][f] != res[1].get(f)]
print(f"{'file':55s} rows      sha256(run1)  match")
for f, (n, h) in res[0].items(): print(f"{f:55s} {n:<9d} {h[:12]}  {'OK' if f not in bad else 'MISMATCH'}")
print("REPRODUCIBLE" if not bad and res[0].keys() == res[1].keys() else f"NOT REPRODUCIBLE: {bad}"); sys.exit(1 if bad else 0)
