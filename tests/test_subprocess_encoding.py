"""Az alfolyamat kimenete UGYANABBAN a kodolasban erkezzen, ahogy olvassuk.

Bejelentes: "a program nem jeleniti meg rendesen a logokat, tele van ekezetek es
nyilak helyett ? karakterekkel".

Gyoker: a szulo `encoding="utf-8"`-cal olvasta a gyerek stdout-jat, a gyerek
viszont Windowson a CSORE irva a TERULETI kodolast hasznalja
(`locale.getpreferredencoding`, magyar rendszeren cp1250). A ket oldal tehat
NEMAN mas kodolast hasznalt.

⚠ Es nem csak "csunya" volt: merve, egy `→` (jobbra nyil) a gyereket
UnicodeEncodeError-ral MEGOLTE volna, mert a cp1250 nem tudja kodolni. A
letoltes ilyenkor nyom nelkul elszallt volna.

Javitas: `PYTHONIOENCODING=utf-8` a gyerek kornyezeteben.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A kod TENYLEG beallitja a gyerek kodolasat ────────────────────────────
SRC = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
pos = SRC.index("def _start_history_download(")
blk = SRC[pos:pos + 4000]
check("a letolto alfolyamat env-et kap", "env=_env" in blk)
check("  ...es abban PYTHONIOENCODING=utf-8 van",
      'PYTHONIOENCODING="utf-8"' in blk)
check("a szulo tovabbra is utf-8-cal olvas (a ketto EGYUTT ervenyes)",
      'encoding="utf-8"' in blk)
check("az os.environ-t OROKLI (nem cseréli le a kornyezetet)",
      "dict(os.environ" in blk)

# ── 2. FUNKCIONALIS: valodi alfolyamat, ekezet + nyil ────────────────────────
# Pont olyan uzenet, mint a letoltoe: em-dash, jobbra nyil, ekezetek.
MSG = "Euro50 M15 — gap 9h → frissítés (natív bar)..."
CHILD = f"print({MSG!r})"


def run(env):
    return subprocess.run([sys.executable, "-u", "-c", CHILD],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", env=env)


env_fix = dict(os.environ, PYTHONIOENCODING="utf-8")
out_fix = run(env_fix).stdout.strip()
check("a javitassal a szoveg EPEN erkezik", out_fix == MSG, out_fix[:60])
check("  ...es nincs benne csere-karakter", "�" not in out_fix)

# A regi viselkedes CSAK Windowson romlik el (mashol az alap is utf-8) — ezert
# ott csak azt allitjuk, hogy a javitott ag jo.
env_old = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
res_old = run(env_old)
if os.name == "nt":
    broken = ("�" in res_old.stdout) or ("UnicodeEncodeError" in res_old.stdout)
    check("Windowson a javitas NELKUL romlik/elszall (a hiba valos)", broken,
          "hibatlan volt" if not broken else "")
else:
    check("nem-Windows: a regi ag is jo (nincs mit bizonyitani)", True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
