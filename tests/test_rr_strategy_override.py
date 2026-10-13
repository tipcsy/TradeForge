"""Kockázatcsökkentés: a pár ALAPJA + stratégiánkénti FELÜLÍRÁS (2026-10-13).

Tibi: „az egyes stratégiáknak lehet külön kiszállójuk". Eddig a kiszállás PÁRONKÉNT
élt: egy páron futó két stratégia osztozott rajta. Most a pár bejegyzése alatt
egy `strategies` blokk tartja a stratégiánkénti ELTÉRÉST; a lekérdezők `strategy`
paramétere azt fésüli rá az örökölt pár-alapra. `strategy=None` → a régi viselkedés.

⚠ Ideiglenes fájlba ír — a valódi data/risk_mode.json-hoz nem nyúl.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import rr_state as R, risk_reduction as RR             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


_valodi_path, _valodi_state = R.PATH, dict(R._state)
_valodi_risky = R._sync_risky
R.PATH = Path(tempfile.mkdtemp()) / "risk_mode.json"
R._sync_risky = lambda s, p: None            # a valódi risky_mode.json-t se írjuk
R._state.clear()
try:
    S = "Ger40"
    R.set_preset(S, RR.PRESET_OFF)
    R._set(S, breakeven_r=1.0, trail_distance_atr=0.4)
    check("felülírás nélkül minden stratégia a pár alapját kapja",
          R.spec_for(S, "csilla")["preset"] == RR.PRESET_OFF
          and R.spec_for(S, "csilla")["breakeven_r"] == 1.0)

    R.set_preset(S, RR.PRESET_SHIELD, strategy="csilla")
    R.set_runner(S, RR.RUNNER_EXIT, strategy="csilla")
    check("a csilla saját presetet kap", R.spec_for(S, "csilla")["preset"] == RR.PRESET_SHIELD)
    check("...és saját runnert", R.spec_for(S, "csilla")["runner_stop"] == RR.RUNNER_EXIT)
    check("...a többi kulcsot ÖRÖKLI (BE 1 R, trailing-táv)",
          R.spec_for(S, "csilla")["breakeven_r"] == 1.0
          and R.spec_for(S, "csilla")["trail_distance_atr"] == 0.4)
    check("a wpr_sma (nincs felülírása) a pár alapját kapja",
          R.spec_for(S, "wpr_sma")["preset"] == RR.PRESET_OFF
          and R.spec_for(S, "wpr_sma")["runner_stop"] != RR.RUNNER_EXIT)
    check("stratégia nélkül (régi hívók) a pár alapja — VÁLTOZATLAN",
          R.spec_for(S)["preset"] == RR.PRESET_OFF)
    check("a felülírás CSAK az eltérést tárolja",
          R.override_of(S, "csilla") == {"preset": RR.PRESET_SHIELD,
                                         "runner": RR.RUNNER_EXIT}, R.override_of(S, "csilla"))
    check("a felülírt stratégiák listája", R.overridden_strategies(S) == ["csilla"])

    # a kiszállási jel beállítása kulcsonként öröklődik
    R.set_exit_config(S, indicator="wpr", st_period=10)
    R.set_exit_config(S, strategy="csilla", indicator="supertrend")
    ex = R.get_exit_config(S, "csilla")
    check("kiszállási jel: a felülírt kulcs nyer, a többi öröklődik",
          ex["indicator"] == "supertrend" and ex["st_period"] == 10, ex)
    check("...és a csilla runnere miatt be van kapcsolva", ex["enabled"] is True)
    check("a pár alapjának jele érintetlen", R.get_exit_config(S)["indicator"] == "wpr")

    # a pár alapjának változása a NEM felülírt kulcson átjön a stratégiára
    R._set(S, breakeven_r=2.0)
    check("a pár alapjának változása átjön (örökölt kulcs)",
          R.spec_for(S, "csilla")["breakeven_r"] == 2.0)
    R._set(S, "csilla", breakeven_r=0.5)
    check("...a stratégián felülírt kulcsot viszont NEM írja felül",
          R.spec_for(S, "csilla")["breakeven_r"] == 0.5 and R.spec_for(S)["breakeven_r"] == 2.0)

    # mentés → újratöltés
    raw = json.loads(R.PATH.read_text(encoding="utf-8"))
    check("a fájlban a pár alatt `strategies` blokk", "strategies" in raw[S]
          and raw[S]["strategies"]["csilla"]["preset"] == RR.PRESET_SHIELD, raw[S])
    R._state.clear()
    R.load()
    check("újratöltés után ugyanaz", R.spec_for(S, "csilla")["preset"] == RR.PRESET_SHIELD
          and R.spec_for(S, "csilla")["breakeven_r"] == 0.5)

    # vissza örököltre
    R.clear_override(S, "csilla", keys=["breakeven_r"])
    check("egy kulcs törlése → az a kulcs újra örökölt",
          R.spec_for(S, "csilla")["breakeven_r"] == 2.0
          and R.spec_for(S, "csilla")["preset"] == RR.PRESET_SHIELD)
    R.clear_override(S, "csilla")
    check("az egész törlése → minden örökölt", R.spec_for(S, "csilla")["preset"] == RR.PRESET_OFF
          and R.overridden_strategies(S) == [])
    check("...és a `strategies` blokk el is tűnik a fájlból",
          "strategies" not in json.loads(R.PATH.read_text(encoding="utf-8"))[S])

    # régi formátum (sima string) és ismeretlen pár
    R._state.clear()
    R.PATH.write_text(json.dumps({"GOLD": "shield"}), encoding="utf-8")
    R.load()
    check("a régi fájlformátum változatlanul olvasható",
          R.spec_for("GOLD", "wpr_sma")["preset"] == RR.PRESET_SHIELD)
    check("ismeretlen pár + stratégia → alap", R.spec_for("XYZ", "csilla")["preset"] == RR.PRESET_OFF)

    # ── a backtest ugyanígy old fel ────────────────────────────────────────
    R.set_preset("GOLD", RR.PRESET_FIBO, strategy="csilla")
    from trading import backtest as BT
    check("backtest: a futó stratégia felülírását kapja",
          BT._rr_spec(None, False, "GOLD", "csilla")["preset"] == RR.PRESET_FIBO)
    check("backtest: másik stratégia a pár alapját",
          BT._rr_spec(None, False, "GOLD", "wpr_sma")["preset"] == RR.PRESET_SHIELD)
    check("backtest: stratégia nélkül a pár alapját (régi hívók)",
          BT._rr_spec(None, False, "GOLD")["preset"] == RR.PRESET_SHIELD)
finally:
    R.PATH = _valodi_path
    R._sync_risky = _valodi_risky
    R._state.clear()
    R._state.update(_valodi_state)

_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor a stratégia nevével kérdez", "rr_state.spec_for(symbol, strategy.name)" in _src)
_bsrc = (ROOT / "trading" / "backtest.py").read_text(encoding="utf-8")
check("a portfólió-backtest is", "_pair_auto_rr(sym, pair_risky.get(cell, False), _sn)" in _bsrc
      and 'getattr(strategy, "name", "")' in _bsrc)

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
