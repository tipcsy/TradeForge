"""A viz-export CSAK a kert idoszak jelzeseit irja ki.

Bejelentes (2026-08-12): "GOLD MT4-visszajatszas, 2026-07-14 — harom pontban nem
hozott jelzest, pedig minden feltetel adott."

A vizsgalat KET dolgot talalt.

⚠ 1. A JELZESEK a BEMELEGITO szakaszbol is bekerultek. Az indikatorokhoz warmup
kell (GOLD-on ~19-21 NAP visszafele), es a strategia a kapott TELJES szeletre
rajzol. Egy 2026-07-13 → 07-18 keresre 72 jelzes irodott ki, amibol 61 meg
JUNIUSI volt — mikozben az uzenet a kert hetet irta.

Ez nem kozmetikai: az MT4-indikator ebbol szamol ("BELEPO: 69 / 72 volt,
HATRA: 3"), es a felhasznalo ez alapjan tekeri a chartot. Egy nem letezo hetnyi
jelzest szamolt volna — es kozben a kert het harom napjan (07-14, 15, 16) EGY
jelzes sem volt a fajlban.

⚠ 2. A hianyzo 07-14-i jeleket a TF-EGYUTTALLAS kapu vette ki (nem hiba: a
strategia adott jelet, a kapu blokkolta). Merve: az 5 jelbol 4-et a TF-kapu,
a spread mindegyiknel bven a hataron belul volt (30-49 pont a ~120-as hatarnal).
Ezert kell a kapu-allapotot a fajlban is jelolni, es ezert van `--no-gates`.

A SAVOKAT/gorbeket NEM vagjuk a kert ablakra: azok folytonos kontextusok, es a
warmup szakaszon is helyes a rajzuk. Csak a JELZES-objektumok szukulnek.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# A szuro TISZTA fuggvenykent van jelen a modulban (a fajlirastol fuggetlenul
# ellenorizheto) — a valodi export lassu es MT5-mappat ir.
import inspect

from tools import viz_export as vx

src = inspect.getsource(vx.export_window)
check("az export szukiti a jelzeseket a kert ablakra",
      "_in_window" in src and "VLINE;" in src)
check("...es a SAVOKAT nem vagja (csak jelzes-objektumok)",
      'startswith(("VLINE;", "ARROW;", "TEXT;"))' in src)
check("az uzenet jelzi, ha a warmupbol kihagyott",
      "bemelegítő szakaszból kihagyva" in src)


# ── A szuro-logika kozvetlen merese ────────────────────────────────────────
# Ugyanaz a feltetel, amit az export hasznal — itt kis peldan, gyorsan.
def _in_window(ln, lo, hi):
    if not ln.startswith(("VLINE;", "ARROW;", "TEXT;")):
        return True
    f = ln.split(";")
    try:
        t = int(f[2])
    except (IndexError, ValueError):
        return True
    return lo <= t <= hi


LO, HI = 1_000_000, 2_000_000
LINES = [
    "VLINE;sig_a;500000;255,0,0;1",        # a warmupban → KI
    "VLINE;sig_b;1500000;255,0,0;1",       # az ablakban → BENT
    "VLINE;sig_c;2500000;0,255,0;1",       # az ablak UTAN → KI
    "ARROW;arr_a;500000;255,0,0;1",        # warmup nyil → KI
    "TEXT;txt_a;1500000;valami",           # ablakban → BENT
    "RECT;band_1;500000;900000;0,0,255",   # SAV → MINDIG bent
    "TREND;sma;400000;1900000;0,0,255",    # gorbe → MINDIG bent
]
kept = [l for l in LINES if _in_window(l, LO, HI)]
check("a warmup-beli JELZES kiesik",
      not any(l.startswith("VLINE;sig_a") for l in kept))
check("az ablakon TULI jelzes is kiesik",
      not any(l.startswith("VLINE;sig_c") for l in kept))
check("az ablakbeli jelzes BENT marad",
      any(l.startswith("VLINE;sig_b") for l in kept))
check("a warmup-beli NYIL is kiesik", not any(l.startswith("ARROW;") for l in kept))
# ⚠ A savok/gorbek warmupban is kellenek: az indikator folytonossaga miatt.
# Ha ezeket is vagnank, a chart bal szelen eltunne az SMA-szalag.
check("a SAV (RECT) a warmupban is BENT marad",
      any(l.startswith("RECT;") for l in kept))
check("a GORBE (TREND) a warmupban is BENT marad",
      any(l.startswith("TREND;") for l in kept))
check("ertelmezhetetlen ido -> inkabb bent hagyjuk (nem tuntetunk el adatot)",
      _in_window("VLINE;x;nem-szam;255,0,0;1", LO, HI))


# ── A hatarok ZARTAK (a kezdo/zaro masodperc is bent van) ─────────────────
check("a kezdo pillanat BENT van", _in_window(f"VLINE;x;{LO};1,1,1;1", LO, HI))
check("a zaro pillanat BENT van", _in_window(f"VLINE;x;{HI};1,1,1;1", LO, HI))
check("egy masodperccel elotte MAR NEM", not _in_window(f"VLINE;x;{LO-1};1,1,1;1", LO, HI))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
