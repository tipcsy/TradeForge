"""A kijelzesi ut fajl-olvasasa NE fussa a lemezt koronkent.

LELET (2026-08-27). A 2.0 sor minden kepfrissitesnel, SORONKENT megnyitotta es
JSON-kent beparse-olta a strategia parameter-fajljat (`_live2_quality`), plusz
stat-olta a done-markert (`opt_done_date`). 12 par x 2 strategia = 24 fajlmuvelet
3 masodpercenkent, a FO SZALON. Amig egy 672 futasos hangolas nyomta a lemezt,
ezek beragadtak: a fo szal 93,5 mp-re megallt, a program befagyottnak latszott.

Ez a teszt a `core.fs_cache.FileCache` szerzodeset orzi: TTL alatt NULLA
fajlmuvelet, TTL utan is csak `stat()`, es olvasas CSAK ha a fajl valtozott.
"""
import io
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core.fs_cache import FileCache

# ── ora-seam: a teszt nem alszik ────────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


tmp = Path(tempfile.mkdtemp(prefix="tf_fscache_"))
f = tmp / "params.json"
f.write_text('{"v": 1}', encoding="utf-8")

loads = {"n": 0}


def loader(p):
    loads["n"] += 1
    return io.open(p, encoding="utf-8").read()


clk = Clock()
c = FileCache(ttl=10.0, clock=clk)

v1 = c.get(f, loader)
check_("elso hivas beolvas", v1 == '{"v": 1}' and loads["n"] == 1)

# TTL-en belul: a lemezhez HOZZA SEM nyulunk (ez a lenyeg)
st0 = c.counters()["stats"]
for _ in range(50):
    c.get(f, loader)
check_("TTL alatt 50 hivas -> 0 tovabbi olvasas", loads["n"] == 1)
check_("...es 0 tovabbi stat() sem", c.counters()["stats"] == st0,
       f"{c.counters()['stats']} vs {st0}")

# TTL lejar, de a fajl NEM valtozott -> stat igen, olvasas nem
clk.advance(11)
c.get(f, loader)
check_("TTL utan valtozatlan fajl -> stat igen, olvasas NEM", loads["n"] == 1)
check_("...a stat szamlalo viszont nott", c.counters()["stats"] == st0 + 1)

# a fajl valtozik -> ujra olvas
clk.advance(11)
f.write_text('{"v": 2}', encoding="utf-8")
os.utime(f, (clk.t + 5, clk.t + 5))          # az mtime biztosan uj legyen
v2 = c.get(f, loader)
check_("valtozott fajl -> ujraolvas", loads["n"] == 2 and v2 == '{"v": 2}',
       f"loads={loads['n']} v={v2}")

# hianyzo fajl -> default, es nem szall el
clk.advance(11)
missing = tmp / "nincs.json"
check_("hianyzo fajl -> default", c.get(missing, loader, default=None) is None)
_st = c.counters()["stats"]
for _ in range(10):
    c.get(missing, loader, default="X")
check_("...es a hianyt is cache-eli (TTL alatt nincs ujabb stat)",
       c.counters()["stats"] == _st, f"{c.counters()['stats']} vs {_st}")

# elszallo loader -> default, a hivo nem kap kivetelt
def boom(p):
    raise RuntimeError("serult fajl")


clk.advance(11)
bad = tmp / "bad.json"
bad.write_text("{{{", encoding="utf-8")
check_("elszallo loader -> default, nem kivetel",
       c.get(bad, boom, default="—") == "—")

# invalidate: a hivo TUDJA, hogy valtozott
f.write_text('{"v": 3}', encoding="utf-8")
c.invalidate(f)
n_before = loads["n"]
c.get(f, loader)
check_("invalidate utan azonnal ujraolvas", loads["n"] == n_before + 1)

# a merteke: 24 sor x 20 frissites TTL-en belul = 24 olvasas, nem 480
c2 = FileCache(ttl=10.0, clock=clk)
files = []
for i in range(24):
    q = tmp / f"row{i}.json"
    q.write_text("{}", encoding="utf-8")
    files.append(q)
loads["n"] = 0
for _ in range(20):
    for q in files:
        c2.get(q, loader)
check_("24 sor x 20 frissites -> 24 olvasas (nem 480)", loads["n"] == 24,
       str(loads["n"]))

# ── a hivo oldal tenyleg ezen at megy-e ────────────────────────────────────
src = io.open(ROOT / "dashboard" / "gui.py", encoding="utf-8").read()
check_("a gui hasznalja a FileCache-t", "_DISPLAY_FS_CACHE" in src)
i_q = src.find("def _live2_quality")
body = src[i_q:i_q + 1600]
check_("_live2_quality a cache-en at olvas", "_DISPLAY_FS_CACHE.get" in body)
check_("...es nincs benne kozvetlen open()",
       "with open(p, encoding" not in body)
i_d = src.find("def opt_done_date")
check_("opt_done_date is a cache-en at megy",
       "_DISPLAY_FS_CACHE.get" in src[i_d:i_d + 900])

import shutil
shutil.rmtree(tmp, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
