"""
Az EGYÜTTÁLLÁS idősíkjai STRATÉGIÁNKÉNT eltérhetnek.

⚠ MIÉRT. A kapu azt kérdezi: „egyetértenek-e az idősíkok az irányban?" — de hogy
MELYIK idősíkok, az a stratégiától függ. A `wpr_sma` M15-ös jelet ad, oda az
M1/M5/M15 hármas illik; a `bollinger_squeeze_breakout` viszont H1-en dönt, ahol
ugyanez a hármas ZAJT mér, nem kontextust. Egy közös lista az egyik stratégiának
biztosan rosszul szolgál.

Az öröklés a LEGSZŰKEBBTŐL a legtágabbig:

    pár + stratégia  →  pár  →  globális + stratégia  →  globális

`strategy=None` → a pár közös beállítása (a meglévő hívók így változatlanok).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

from gates import tf_align as tfa                    # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


BSQ = "bollinger_squeeze_breakout"

# ---------------------------------------------------------------------------
print("== Öröklés ==")

CFG = {
    "tf_align": {"enabled": True, "timeframes": [1, 5, 15], "sma_period": 100,
                 "per_strategy": {BSQ: {"timeframes": [60, 240, 1440]}}},
    "pairs": {
        "Ger40": {"tf_align": {"sma_period": 50}},
        "GOLD":  {"tf_align": {"timeframes": [5, 15, 60],
                               "per_strategy": {BSQ: {"timeframes": [240, 1440],
                                                      "sma_period": 20}}}},
        "EURUSD": {},
    },
}

en, tfs, sma, _g = tfa.config_for(CFG, "Ger40")
check("strategia NELKUL a par kozos beallitasa", tfs == [1, 5, 15] and sma == 50,
      f"{tfs} / {sma}")
check("...a `wpr_sma`-nak ugyanez (nincs sajat blokkja)",
      tfa.config_for(CFG, "Ger40", "wpr_sma")[1] == [1, 5, 15])

_, tfs_b, sma_b, _ = tfa.config_for(CFG, "Ger40", BSQ)
check("a GLOBALIS per_strategy felulirja az idosikokat", tfs_b == [60, 240, 1440],
      str(tfs_b))
check("...de a PAR sma_period-ja tovabb el (kulcsonkenti olvasztas)", sma_b == 50,
      str(sma_b))

_, tfs_g, sma_g, _ = tfa.config_for(CFG, "GOLD", BSQ)
check("a PAR per_strategy-je a legerosebb", tfs_g == [240, 1440] and sma_g == 20,
      f"{tfs_g} / {sma_g}")
check("ugyanezen a paron mas strategia a par kozoset kapja",
      tfa.config_for(CFG, "GOLD", "wpr_sma")[1] == [5, 15, 60],
      str(tfa.config_for(CFG, "GOLD", "wpr_sma")[1]))

check("par-blokk nelkul a globalis ervenyes",
      tfa.config_for(CFG, "EURUSD", BSQ)[1] == [60, 240, 1440])
check("ismeretlen strategia -> a kozos beallitas",
      tfa.config_for(CFG, "Ger40", "nincs_ilyen")[1] == [1, 5, 15])

# ⚠ VISSZAFELE KOMPATIBILITAS: per_strategy NELKULI config valtozatlanul mukodik
OLD = {"tf_align": {"enabled": True, "timeframes": [1, 5, 15], "sma_period": 100},
       "pairs": {"X": {}}}
check("regi (per_strategy nelkuli) config valtozatlan",
      tfa.config_for(OLD, "X") == tfa.config_for(OLD, "X", BSQ),
      str(tfa.config_for(OLD, "X")[:3]))

# A viz-kapcsolo is strategia-tudatos
VIZ = {"tf_align": {"enabled": True, "viz": True,
                    "per_strategy": {BSQ: {"viz": False}}}, "pairs": {"X": {}}}
check("a viz-kapcsolo is felulirhato strategiankent",
      tfa.viz_on(VIZ, "X") is True and tfa.viz_on(VIZ, "X", BSQ) is False)

# ---------------------------------------------------------------------------
print("== A hasznalati helyek atadjak a strategiat ==")
for mod, needle in (("trading/backtest.py", "config_for(cfg, symbol, strategy_name)"),
                    ("trading/live_trader.py", "config_for(_run_cfg, symbol, strategy_name)")):
    src = (pathlib.Path(__file__).resolve().parents[1] / mod).read_text(encoding="utf-8")
    check(f"{mod}: a kapu a strategiaval kerdez", needle in src)

# ---------------------------------------------------------------------------
print("== A MERES, ami miatt a kapu alapbol KI van ==")
# 7 par, HAROM kulon 6 honapos idoszak, M60-as bollinger, hangolatlan parameterek:
#
#   kapu KI             290/318/319 kotes  57,9/54,1/52,0%   OSSZ +4884$
#   Egyutt M1/M5/M15    251/273/254        55,0/52,4/49,6%   OSSZ +3733$
#   Egyutt M15/H1/H4    142/146/149                          OSSZ +1995$
#   Egyutt H1/H4/D1      93/114/109        53,8/45,6/54,1%   OSSZ +1483$
#
# A kapu HARMADARA vagja a kotesszamot ES a talalati aranyt SEM javitja. Ez a
# szerkezet keszen all (barmely strategia kaphat sajat idosikokat), de a
# bollingeren a meres szerint KART okoz — ezert a hatasa alapbol `none` marad.
from core import gates as _g                          # noqa: E402
import json                                           # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
real = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
eff = {sym: _g.effect_for(real, sym, BSQ, _g.TF_ALIGN)
       for sym in (real.get("pairs") or {}) if isinstance(real["pairs"][sym], dict)}
check("a bollinger TF-kapuja SEHOL nincs bekapcsolva (a meres szerint artana)",
      all(v == _g.EFFECT_NONE for v in eff.values()),
      str({k: v for k, v in eff.items() if v != _g.EFFECT_NONE}) or "mind none")

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
