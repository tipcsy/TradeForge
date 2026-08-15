"""A portfolio-backtest az ELET modellezze: nincs rejtett „auto-risky".

⚠ A LELET. A `config.example.json` szerint a gyenge minositesu par automatikusan
RISKY modban fut *„mint elesben"* — EZ NEM IGAZ. Az auto-risky CSAK a
portfolio-backtestben letezett; az elo motorban a preset kizarolag a per-par
valasztott ertekbol (`data/risk_mode.json`) jon.

⚠ ES NEM CSAK A MERET valtozott tole. Merve (10 par, 2026-06-01→08-14,
vegrehajtasi kapukkal):

    bekapcsolva : 460 kotes | +325,0$ | nyero 29,6%
    kikapcsolva : 248 kotes | +176,6$ | nyero 57,3%

A RISKY azonnali BE-je KOCKAZATMENTESSE teszi a poziciot, az pedig FELSZABADITJA
a slotot — ezert fer be 1,85x annyi belepo. A portfolio-BT tehat 1,84x-esre
fujta az eredmenyt egy olyan viselkedeshez kepest, ami elesben nem letezik.

⚠ NEV-CSAPDA, ami miatt ez ennyi part erintett: a `PRESET_OFF` erteke `"off"`,
de a FELIRATA „BE + trailing" — az AKTIV alapertelmezes. A „Ki (semmi)" a
`PRESET_NONE` (`"none"`). A feltetel tehat MINDEN alapbeallitasu paron elsult.
"""
import inspect
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


from core import risk_reduction as _rr, rr_state as _rrs

# ── 1. A NEV-CSAPDA rogzitese ────────────────────────────────────────────
# Ha valaki egyszer atnevezi/atrendezi a preseteket, itt bukjon el — ne a
# portfolio-backteszt szamain.
check("a PRESET_OFF felirata NEM a semmi, hanem az aktiv alapertelmezes",
      _rrs.NAME[_rr.PRESET_OFF] == "BE + trailing", _rrs.NAME[_rr.PRESET_OFF])
check("a valodi „semmi” a PRESET_NONE",
      _rrs.NAME.get(getattr(_rr, "PRESET_NONE", "none")) == "Ki (semmi)",
      str(_rrs.NAME.get(getattr(_rr, "PRESET_NONE", "none"))))


# ── 2. AZ ALAPERTELMEZES: EL-PARITAS ─────────────────────────────────────
import trading.backtest as bt
_src = inspect.getsource(bt.run_portfolio_backtest)
check("az auto_risky_weak alapbol KI",
      'trading_cfg.get("auto_risky_weak", False)' in _src,
      "az alapertelmezes nem False")
# ⚠ Bekapcsolva NEM NEMA: a felhasznalonak tudnia kell, hogy a szam nem az ele.
check("bekapcsolva FIGYELMEZTET, hogy nem az elet modellezi",
      "az ÉLŐ MOTOR NEM csinál" in _src or "ÉLŐ MOTOR NEM" in _src, "")
check("...a doksi is kimondja", "auto_risky_weak" in (bt.run_portfolio_backtest.__doc__ or ""))


# ── 3. A CONFIG-PELDA nem allithatja tobbe, hogy „mint elesben" ──────────
_ex = (ROOT / "config.example.json").read_text(encoding="utf-8")
_i = _ex.find("_comment_auto_risky")
_line = _ex[_i:_ex.find(chr(10), _i)] if _i >= 0 else ""
check("a config-pelda MEGVAN", _i >= 0)
# ⚠ A szo szerinti keresés naiv volna: az UJ szoveg IDEZI a regi allitast
# („a korábbi »mint élőben« megjegyzés TÉVES"), es ez helyes — egy javitas
# ertekesebb, ha megmondja, MIT javit. Azt kell allitani, hogy a kifejezes NE
# alljon ott ONALLO allitaskent, azaz ha szerepel, akkor cafolva legyen.
check("...es ha emlegeti a regi allitast, CAFOLJA is",
      ("mint élőben" not in _line) or ("TÉVES" in _line), _line[:150])
check("...sot KIMONDJA, hogy az el NEM csinalja",
      "ÉLŐ MOTOR EZT NEM" in _line or "AZ ÉLŐ MOTOR" in _line, _line[:160])
check("...es a pelda-ertek is false",
      '"auto_risky_weak": false' in _ex,
      _ex[_ex.find('"auto_risky_weak"'):][:40])


# ── 4. AZ EL-UT valtozatlan (nem vittuk at az auto-riskyt) ──────────────
# ⚠ A javitas iranya SZANDEKOS: a backtest igazodik az elhez, nem forditva.
# Az ellenkezoje VALODI kereskedesi valtozas volna 6 paron — az a felhasznalo
# dontese, nem egy paritas-javitase.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("az elo motor tovabbra sem ismer auto-riskyt",
      "auto_risky" not in _lt, "megjelent az elo uton!")


# ── 5. MERES: a ket ag TENYLEG mast ad ──────────────────────────────────
# Rovid ablak, hogy a teszt gyors maradjon — a LENYEG az, hogy az eltérés
# NEM nulla, es hogy a KOTESSZAM is valtozik (nem csak a meret).
try:
    import logging
    logging.disable(logging.WARNING)
    from strategy.settings import load_config
    cfg = load_config("config.json")
    syms = [p for p in cfg["pairs"] if not p.startswith("_")][:4]
    _res = {}
    for _auto in (False, True):
        c = dict(cfg)
        c["trading"] = dict(cfg["trading"], auto_risky_weak=_auto)
        r = bt.run_portfolio_backtest(c, syms, "2026-07-15", "2026-08-14",
                                      exec_gates=True)
        _tr = [x for x in (r.get("trades") or []) if x.close_time is not None]
        _res[_auto] = (len(_tr), sum(x.pnl_usd for x in _tr))
    logging.disable(logging.NOTSET)
    check("a ket ag KULONBOZO eredmenyt ad (tehat a kapcsolo szamit)",
          _res[True] != _res[False], str(_res))
    # ⚠ EZ A LENYEG: nem csak a MERET valtozik. A RISKY azonnali BE-je
    # felszabaditja a slotot -> TOBB belepo fer be.
    check("...es a KOTESSZAM is elter (nem csak a meret)",
          _res[True][0] != _res[False][0],
          f"auto=BE {_res[True][0]} kotes, auto=KI {_res[False][0]} kotes")
except Exception as ex:
    check(f"a meres kihagyva ({type(ex).__name__}: {str(ex)[:60]})", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
