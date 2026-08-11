"""Attekintes: mi ennek a parnak az ALLAPOTA — egy kepernyon.

A keres: "az elso oldalon csak egy dashboard-szeru dolog lehetne, ahol latod,
hogy mikor kereskedik, meg a minoseget, meg ilyeneket".

⚠ A lap ERTEKE nem a metrikak megismetlese — azok maskepp is lathatok. Az ertek a
FIGYELMEZTETESEK: azok az allapotok, amikben minden RENDBEN LATSZIK, kozben nem.
Ezek ma mind NEMAK, es a felhasznalo ezek alapjan kereskedik eles (demo)
szamlan. Ezert van rajtuk teszt.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from core import overview as ov
from core import gates as gt

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


CFG = {"pairs": {"TEST": {}}, "optimizer": {"exec_gates": True},
       "gates": {gt.SPREAD: {"default": gt.EFFECT_BLOCK}}}
OK_TS = {"trades": 500, "win_rate": 0.35, "total_pnl": 100.0,
         "max_drawdown": 0.12, "profit_factor": 1.3}


def _warn_texts(data, state="live", mode="live", cfg=None):
    return [w["text"] for w in ov.warnings(cfg or CFG, "TEST", "wpr_sma",
                                           data, state, mode)]


def _sevs(data, state="live", mode="live", cfg=None):
    return {w["sev"] for w in ov.warnings(cfg or CFG, "TEST", "wpr_sma",
                                          data, state, mode)}


# ── 1. Ora-profil ──────────────────────────────────────────────────────────
# ⚠ A mentett alak oranként {"pnl":…, "count":…} — nem puszta szam. Ha ezt
# elvetenenk, a sav URES lenne, es ugy latszana, hogy "nincs adat".
_ts = {"hourly_pnl": {"9": {"pnl": 12.5, "count": 40},
                      "10": {"pnl": -3.0, "count": 7}}}
_p = ov.hour_profile(_ts, None)
check("24 ora all elo", len(_p) == 24)
check("a szotar-alakbol kiolvassa a P&L-t", _p[9]["pnl"] == 12.5)
# A KOTESSZAM kulon kell: "enyhen minuszos 3 kotesbol" (zaj) vs "enyhen minuszos
# 300 kotesbol" (rendszeres veszteseg) — ELLENTETES teendo.
check("...es a KOTESSZAMOT is", _p[9]["count"] == 40 and _p[10]["count"] == 7)
check("adat nelkuli ora -> None (nem 0)", _p[0]["pnl"] is None)
check("regi, PUSZTA SZAM alak is mukodik",
      ov.hour_profile({"hourly_pnl": {"5": -7.5}}, None)[5]["pnl"] == -7.5)
_lim = ov.hour_profile(_ts, [9, 10, 11])
check("ora-szuro nelkul MINDEN ora engedett",
      all(h["allowed"] for h in ov.hour_profile(_ts, None)))
check("ora-szuroval csak a felsoroltak", _lim[9]["allowed"] and not _lim[0]["allowed"])
check("romlott ora-kulcs nem robban",
      len(ov.hour_profile({"hourly_pnl": {"x": 1, "9": "abc"}}, None)) == 24)


# ── 2. A FIGYELMEZTETESEK — a lap valodi haszna ───────────────────────────
# (a) Nincs mentett parameter, de a par EL -> ez a legsulyosabb.
check("nincs parameter + EL -> KOCKAZAT",
      ov.SEV_RISK in _sevs({"test_summary": {}}, state="live"))
check("nincs parameter + allitva -> csak figyelmeztetes",
      ov.SEV_RISK not in _sevs({"test_summary": {}}, state="stopped"))

# (b) KEZI szerkesztes az optimalizalas utan: a mentett minosites mar MAS
# beallitashoz tartozik, mint amivel kereskedsz — a feluleten megis a regi
# minosites latszik. Ez a legkonnyebben eszrevetlen felreertes.
_edited = {"params": {"a": 1}, "test_summary": OK_TS,
           "optimized_at": _iso(10), "manually_edited_at": _iso(2)}
check("kezi szerkesztes az optimalizalas UTAN -> szol",
      any("KÉZZEL" in t for t in _warn_texts(_edited)))
_clean = {"params": {"a": 1}, "test_summary": OK_TS,
          "optimized_at": _iso(2), "manually_edited_at": _iso(10)}
check("kezi szerkesztes az optimalizalas ELOTT -> NEM szol (nem zajong)",
      not any("KÉZZEL" in t for t in _warn_texts(_clean)))

# (c) Kapu-elteres: mas vilagban optimalizaltunk, mint amiben kereskedunk.
_gapped = {"params": {"a": 1}, "test_summary": OK_TS, "exec_gates": False}
check("kapu-elteres -> KOCKAZAT",
      any("KAPUK NÉLKÜL" in t for t in _warn_texts(_gapped)) and
      ov.SEV_RISK in _sevs(_gapped))
check("egyezo kapu-beallitas -> nem szol",
      not any("kapu" in t.lower() and "futott" in t for t in
              _warn_texts({"params": {"a": 1}, "test_summary": OK_TS,
                           "exec_gates": True})))

# (d) ⚠ 100% FOLOTTI visszaeses: a szimulalt szamla LENULLAZODOTT volna. A
# felulet eddig ezt ugyanolyan szurke szazalekkent irta ki, mint egy 8%-osat.
_blown = {"params": {"a": 1},
          "test_summary": {**OK_TS, "max_drawdown": 1.625}}
check("100% feletti visszaeses -> KOCKAZAT (lenullazodott volna)",
      ov.SEV_RISK in _sevs(_blown) and
      any("lenullázódott" in t for t in _warn_texts(_blown)))
check("normal visszaeses -> nem szol",
      not any("lenullázódott" in t for t in _warn_texts(
          {"params": {"a": 1}, "test_summary": OK_TS})))

# (e) Kevés kotes / szennyezett OOS / csak jelzes
check("kevés kotes -> szol",
      any("Kevés kötés" in t for t in _warn_texts(
          {"params": {"a": 1}, "test_summary": {**OK_TS, "trades": 12}})))
# ⚠ A mentett minosites a walk-forward VIZSGA-ablakaibol jon — de az optimalizalo
# EPPEN azokon valasztott. Merve: a szennyezett OOS 2,51x-esre fujt.
check("a szennyezett OOS-t mindig kimondja",
      any("nem független mérés" in t for t in
          _warn_texts({"params": {"a": 1}, "test_summary": OK_TS})))
check("„csak jelzés” modot kiirja",
      any("csak jelzés" in t for t in
          _warn_texts({"params": {"a": 1}, "test_summary": OK_TS}, mode="signal")))

# (f) Egyetlen kapu sincs bekapcsolva
_nogates = {"pairs": {"TEST": {}}, "optimizer": {"exec_gates": True},
            "gates": {k: {"default": gt.EFFECT_NONE} for k in gt.KEYS}}
check("nincs bekapcsolt kapu -> szol",
      any("kapu sincs" in t for t in
          _warn_texts({"params": {"a": 1}, "test_summary": OK_TS}, cfg=_nogates)))

# (g) Sorrend: a KOCKAZAT all elol (a felulet igy elobb mutatja a sulyosat)
_multi = ov.warnings(CFG, "TEST", "wpr_sma", _blown, "live", "live")
check("a kockazatos figyelmeztetes all ELOL",
      _multi[0]["sev"] == ov.SEV_RISK, str([w["sev"] for w in _multi]))

# (h) Az EGESZSEGES eset ne zajongjon: csak az OOS-tajekoztatas maradjon.
_healthy = _warn_texts({"params": {"a": 1}, "test_summary": OK_TS,
                        "optimized_at": _iso(3), "exec_gates": True})
check("egeszseges allapotban csak 1 (tajekoztato) uzenet",
      len(_healthy) == 1, str(_healthy))


# ── 3. A teljes terv ──────────────────────────────────────────────────────
class _S:
    name = "wpr_sma"


_full = ov.build(CFG, "TEST", _S(), {"params": {"a": 1}, "test_summary": OK_TS,
                                     "optimized_at": _iso(5)})
check("a terv minden mezot ad",
      all(k in _full for k in ("state", "mode", "grade", "summary", "hours",
                               "gates", "warnings", "optimized_age_days")))
check("a minoseg SZIN-NEVET ad (nem Tk-szint)",
      _full.get("grade_color_name") in ("red", "green", "yellow", "muted",
                                        "orange", "white", "dim", "blue"),
      str(_full.get("grade_color_name")))
check("az optimalizalas KORA napokban", 4.5 < (_full["optimized_age_days"] or 0) < 5.5,
      str(_full["optimized_age_days"]))
check("ures adaton sem robban", ov.build(CFG, "TEST", _S(), {}) is not None)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
