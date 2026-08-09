"""A viz KIMENJEN egy MEGADOTT tol-ig ablakra is (MT4-es manualis visszajatszas).

Az elo viz mindig az „utolso N gyertyat" rajzolja. A manualis teszthez egy KONKRET
hetet kell visszajatszani, ezert a `pair_visual_lines` kapott egy `bars` seamet.

Miert seam es nem masolat: ha az export SAJAT rajzolo utat kapna, az elobb-utobb
elcsuszna az elotol — pont az a nema elteres-osztaly, amit a projekt irt (lasd az
optimalizalo↔el kapu- es rr-preset-elteresek).

Es miert `actual_trades=False` alapbol az exportban: a bot TENYLEGES belepoi a
manualis teszten a MEGFEJTEST jelentenek.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A seam LETEZIK es a helyes alapertekekkel ──────────────────────────────
import inspect
from trading.live_trader import pair_visual_lines

sig = inspect.signature(pair_visual_lines)
check("pair_visual_lines-nak van `bars` parametere", "bars" in sig.parameters)
check("  ...es alapbol None (az elo ut valtozatlan)",
      sig.parameters["bars"].default is None)
check("pair_visual_lines-nak van `actual_trades` parametere",
      "actual_trades" in sig.parameters)
check("  ...es alapbol True (az elo chart tovabbra is mutatja a koteseket)",
      sig.parameters["actual_trades"].default is True)

SRC = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a valos kotesek retege a kapcsolotol fugg",
      "if actual_trades and m1 is not None" in SRC)

# ── 2. Az export alapbol NEM mutatja a valos koteseket ────────────────────────
EXP = (ROOT / "tools" / "viz_export.py").read_text(encoding="utf-8")
check("az export --show-trades nelkul fut alapbol (store_true)",
      '"--show-trades", action="store_true"' in EXP)
check("az export a KOZOS pair_visual_lines-t hivja (nincs masolt rajzolo ut)",
      "from trading.live_trader import pair_visual_lines" in EXP
      and "pair_visual_lines(" in EXP)
check("az export a kozos VEGREHAJTASI reteget is ratolti (atr_period!)",
      "load_execution_params" in EXP)
check("az export WARMUPOT tolt a kert ablak ELE",
      "visual_lookback_bars" in EXP)
check("az export a parquet close_spread-jet `spread`-re nevezi",
      '"close_spread": "spread"' in EXP)

# ── 3. write_lines: kulon fajlnev (az elo viz ne irja felul) ─────────────────
from core import mt5_visual
from strategy.visual import PREFIX

tmp = Path(tempfile.mkdtemp(prefix="tfviz_"))
_orig_dir = mt5_visual.files_dir
mt5_visual.files_dir = lambda: tmp          # SOHA ne irjunk a valodi Common\Files-ba
try:
    p1 = mt5_visual.write_lines("TESTSYM", ["VLINE;x"], name_suffix="")
    p2 = mt5_visual.write_lines("TESTSYM", ["VLINE;y"], name_suffix="_BT")
    check("suffix nelkul a megszokott nev",
          p1 is not None and p1.name == f"{PREFIX}TESTSYM.csv",
          p1.name if p1 else "None")
    check("suffixszel KULON fajl (nem irja felul az elot)",
          p2 is not None and p2.name == f"{PREFIX}TESTSYM_BT.csv",
          p2.name if p2 else "None")
    check("a ket fajl kulon el", p1.exists() and p2.exists() and p1 != p2)
    check("a tartalom nem keveredett",
          p1.read_text().strip() == "VLINE;x" and p2.read_text().strip() == "VLINE;y")

    p3 = mt5_visual.write_lines("TESTSYM", ["VLINE;z"], clear_first=True, name_suffix="_BT")
    check("clear_first CLEAR sort tesz a pillanatkep ELE",
          p3.read_text().splitlines()[0] == "CLEAR")
finally:
    mt5_visual.files_dir = _orig_dir
    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()

# ── 4. files_dir: MT5 nelkul is legyen utja (offline export) ─────────────────
# A szonda merte (2026-08-09): a Common mappa KOZOS az MT4/MT5 kozott, es
# PORTABLE modban sem koltozik — ezert szabad erre visszaesni.
VIZ = (ROOT / "core" / "mt5_visual.py").read_text(encoding="utf-8")
check("files_dir-nek van APPDATA fallbackje (MT5 nelkuli export)",
      'os.environ.get("APPDATA")' in VIZ and "MetaQuotes" in VIZ)
check("az MT5 valasza tovabbra is ELSOBBSEGET elvez",
      VIZ.index("info.commondata_path") < VIZ.index('os.environ.get("APPDATA")'))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
