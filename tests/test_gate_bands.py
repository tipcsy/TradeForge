"""SÁVOS KAPU-HATÁS (v3.28.0) — „mikor mi történjen", nem csak „mi történjen".

⚠ A KÉRÉS (2026-09-02): „elvárnám azt is, hogy amelyiknél vannak sávok szintek,
ott hogyan valósuljon meg. Pl.: 10%-nál semmi, 40%-nál kockázatcsökkent, 50%-nál
akadályozza a beszállást." + a fajtákra (2026-09-03): „skalár sáv, TF darabszám,
piac kategória". + az öröklődésre: „ahol valami nincs beállítva, az örököl".

AMIT ITT ŐRZÜNK, FONTOSSÁGI SORRENDBEN:

  1. SÁV NÉLKÜL SEMMI NEM VÁLTOZIK. Ez a legfontosabb: a funkció puszta létezése
     nem mozdíthat el egyetlen kötést sem. A létra nélküli úton a kapu SAJÁT
     ítélete dönt — nem a normalizált szint, mert a kettő a HATÁRON eltérhet egy
     epszilonnal, és az néma viselkedés-váltás lenne minden páron.
  2. A sáv TÉNYLEG hat a motorban (nem csak a szótárban).
  3. Az öröklődés ugyanaz a lánc, mint a hatásé — és KIKAPCSOLHATÓ (`bands: []`).
  4. Egy KIKAPCSOLT kaput (`none`) a létra nem kapcsolhat vissza.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


import pandas as pd                                          # noqa: E402
from core import gates as g, gate_bands as gb                # noqa: E402
from trading import backtest as bt                           # noqa: E402

PRM = {"atr_min_pct": 0.9, "atr_max_pct": 3.2, "atr_avg_ref": 272.75}


# ══ 1. SÁV NÉLKÜL A KAPU SAJÁT ÍTÉLETE DÖNT ═════════════════════════════
# ⚠ NEM a szint. A volatilitásnál mérve: ATR = pontosan a padló → szint 100,0%,
# `vol_baseline.failed` viszont False (szigorú `<`). Ha itt a szintet néznénk, a
# sáv nélküli (tehát a MAI) viselkedés egy hajszálnyit megváltozna, némán.
check("sáv nélkül: bukott → a beállított hatás",
      gb.effect_at(g.VOLATILITY, [], g.EFFECT_BLOCK, 100.0, failed=True)
      == g.EFFECT_BLOCK)
check("sáv nélkül: NEM bukott → semmi, akkor is, ha a szint 100%",
      gb.effect_at(g.VOLATILITY, [], g.EFFECT_BLOCK, 100.0, failed=False)
      == g.EFFECT_NONE)
check("sáv nélkül a szint teljesen közömbös",
      all(gb.effect_at(g.SPREAD, [], g.EFFECT_BLOCK, lv, failed=False)
          == g.EFFECT_NONE for lv in (0, 99, 100, 500, None)))


# ══ 2. A LÉTRA — háromféle mérőszámra ═══════════════════════════════════
LAD = [(80, g.EFFECT_REDUCE), (100, g.EFFECT_BLOCK)]
_want = {50: g.EFFECT_NONE, 79.9: g.EFFECT_NONE, 80: g.EFFECT_REDUCE,
         99.9: g.EFFECT_REDUCE, 100: g.EFFECT_BLOCK, 400: g.EFFECT_BLOCK}
_bad = [f"{k}→{gb.effect_at(g.VOLATILITY, LAD, g.EFFECT_BLOCK, k, False)}"
        for k, v in _want.items()
        if gb.effect_at(g.VOLATILITY, LAD, g.EFFECT_BLOCK, k, False) != v]
check("SKALÁR: a legmagasabb elért határ nyer", not _bad, ", ".join(_bad))

CNT = [(2, g.EFFECT_REDUCE), (1, g.EFFECT_BLOCK)]
_wantc = {4: g.EFFECT_NONE, 3: g.EFFECT_NONE, 2: g.EFFECT_REDUCE,
          1: g.EFFECT_BLOCK, 0: g.EFFECT_BLOCK}
_badc = [f"{k}→{gb.effect_at(g.TF_ALIGN, CNT, g.EFFECT_BLOCK, k, False)}"
         for k, v in _wantc.items()
         if gb.effect_at(g.TF_ALIGN, CNT, g.EFFECT_BLOCK, k, False) != v]
check("DARABSZÁM: a KEVESEBB a rosszabb (legfeljebb N)", not _badc,
      ", ".join(_badc))

CAT = {"dead": g.EFFECT_BLOCK, "ranging": g.EFFECT_REDUCE}
check("KATEGÓRIA: besorolásonként egy hatás",
      gb.effect_at(g.MARKET, CAT, g.EFFECT_BLOCK, "ranging", True)
      == g.EFFECT_REDUCE)
check("...a fel nem sorolt besorolás átmegy",
      gb.effect_at(g.MARKET, CAT, g.EFFECT_BLOCK, "clean_bull", True)
      == g.EFFECT_NONE)


# ══ 3. EGY KIKAPCSOLT KAPUT A LÉTRA NEM KAPCSOL VISSZA ══════════════════
# ⚠ Enélkül egy örökölt (globális) létra némán újraélesztené azt a kaput, amit a
# felhasználó ezen a páron szándékosan kikapcsolt.
check("`none` alap-hatás → a létra sem szól bele",
      gb.effect_at(g.VOLATILITY, LAD, g.EFFECT_NONE, 400, True) == g.EFFECT_NONE)


# ══ 4. A SZINT 100%-a PONTOSAN a kapu saját határa ══════════════════════
from gates import vol_baseline as vb                          # noqa: E402
_lo, _hi = vb.band(PRM, 272.75)
check("volatilitás: a padlón a szint 100%",
      abs(gb.level_volatility(_lo, PRM, 0.0) - 100.0) < 1e-6,
      f"{gb.level_volatility(_lo, PRM, 0.0):.4f}")
check("volatilitás: a plafonon is 100%",
      abs(gb.level_volatility(_hi, PRM, 0.0) - 100.0) < 1e-6,
      f"{gb.level_volatility(_hi, PRM, 0.0):.4f}")
check("volatilitás: a sávon BELÜL kevesebb",
      gb.level_volatility(272.75, PRM, 0.0) < 100.0)
check("spread: a plafonon 100%", abs(gb.scalar_level(20.0, 20.0) - 100) < 1e-9)
check("lendület: a küszöbön 100%",
      abs(gb.inverse_level(0.35, 0.35) - 100) < 1e-9)
check("lendület: az IRÁNY-bukás is 100% (nem gyengíthető sávval)",
      gb.momentum_level(-0.9, "BUY", "dir", {"idle_threshold": 0.35}) == 100.0)
check("nincs küszöb → nincs szint (a régi ítélet marad)",
      gb.scalar_level(1.0, 0) is None and gb.level_volatility(1.0, {}, 0) is None)


# ══ 5. ÖRÖKLŐDÉS — ugyanaz a lánc, mint a hatásé ════════════════════════
SYM, ST = "Ger40", "wpr_sma"
_glob = {"gates": {g.VOLATILITY: {"default": {"bands": [[70, "reduce"]]}}}}
check("globális alapértelmezés örökölhető",
      gb.ladder(_glob, SYM, ST, g.VOLATILITY) == [(70.0, "reduce")],
      str(gb.ladder(_glob, SYM, ST, g.VOLATILITY)))
_gs = {"gates": {g.VOLATILITY: {"default": {"bands": [[70, "reduce"]]},
                                ST: {"bands": [[60, "block"]]}}}}
check("a stratégia-szintű nyer a globális alap fölött",
      gb.ladder(_gs, SYM, ST, g.VOLATILITY) == [(60.0, "block")])
_pair = {**_gs, "pairs": {SYM: {"gates": {g.VOLATILITY: {
    ST: {"bands": [[50, "reduce"]]}}}}}}
check("a pár+stratégia a legszűkebb → az nyer",
      gb.ladder(_pair, SYM, ST, g.VOLATILITY) == [(50.0, "reduce")])
check("...és a forrás is ezt mondja",
      gb.ladder_with_source(_pair, SYM, ST, g.VOLATILITY)[1] == g.SRC_PAIR)
check("másik stratégia a globális alapot örökli",
      gb.ladder(_pair, SYM, "ml_ai", g.VOLATILITY) == [(70.0, "reduce")])
# ⚠ AZ ÜRES LISTA ÉRTELMES BEÁLLÍTÁS: „ezen a páron NE legyen sáv".
_off = {**_gs, "pairs": {SYM: {"gates": {g.VOLATILITY: {ST: {"bands": []}}}}}}
check("üres létra KIKAPCSOLJA az öröklött sávot",
      gb.ladder(_off, SYM, ST, g.VOLATILITY) == [],
      str(gb.ladder(_off, SYM, ST, g.VOLATILITY)))
# Egy SIMA hatás-bejegyzés nem dönt a létráról → tovább öröklünk.
_plain = {**_gs, "pairs": {SYM: {"gates": {g.VOLATILITY: {ST: "block"}}}}}
check("sima hatás-bejegyzés NEM törli az örökölt létrát",
      gb.ladder(_plain, SYM, ST, g.VOLATILITY) == [(60.0, "block")])
check("az inherited_ladder a pár nélküli képet adja",
      gb.inherited_ladder(_pair, SYM, ST, g.VOLATILITY)[0] == [(60.0, "block")])


# ══ 6. MENTÉS: a config csak az ELTÉRÉST rögzíti ════════════════════════
_c = {}
gb.set_ladder(_c, SYM, ST, g.VOLATILITY, [[100, "block"], [80, "reduce"]])
check("mentés után rendezve áll a configban",
      _c["pairs"][SYM]["gates"][g.VOLATILITY][ST]["bands"]
      == [[80.0, "reduce"], [100.0, "block"]],
      str(_c["pairs"][SYM]["gates"][g.VOLATILITY][ST]["bands"]))
gb.set_ladder(_c, SYM, ST, g.VOLATILITY, None)
check("None → a bejegyzés eltűnik (visszaáll az öröklés)",
      not (_c.get("pairs", {}).get(SYM, {}).get("gates")), str(_c))
_c2 = {"pairs": {SYM: {"gates": {g.VOLATILITY: {ST: "block"}}}}}
gb.set_ladder(_c2, SYM, ST, g.VOLATILITY, [[80, "reduce"]])
check("a meglévő hatás NEM vész el a sáv mentésekor",
      _c2["pairs"][SYM]["gates"][g.VOLATILITY][ST]["effect"] == "block",
      str(_c2["pairs"][SYM]["gates"][g.VOLATILITY][ST]))
check("...és a hatás-feloldó továbbra is érti",
      g.effect_for(_c2, SYM, ST, g.VOLATILITY) == g.EFFECT_BLOCK)
# DARABSZÁM csökkenő sorrendben mentődik (a config olvasva is létra legyen).
_c3 = {}
gb.set_ladder(_c3, SYM, ST, g.TF_ALIGN, [[1, "block"], [2, "reduce"]])
check("darabszám-létra csökkenő sorrendben mentődik",
      _c3["pairs"][SYM]["gates"][g.TF_ALIGN][ST]["bands"]
      == [[2.0, "reduce"], [1.0, "block"]])


# ══ 7. ELLENŐRZÉS — a rossz sáv NEM juthat a motorig ════════════════════
check("ismeretlen hatás hibát ad", gb.validate(g.VOLATILITY, [[80, "xxx"]]))
check("tartományon kívüli szint hibát ad", gb.validate(g.VOLATILITY, [[2000, "block"]]))
check("ismétlődő határ hibát ad",
      gb.validate(g.VOLATILITY, [[80, "block"], [80, "reduce"]]))
check("túl sok sáv hibát ad",
      gb.validate(g.VOLATILITY, [[i * 10, "block"] for i in range(1, 9)]))
check("nem egész darabszám hibát ad", gb.validate(g.TF_ALIGN, [[1.5, "block"]]))
check("érvényes létra HIBÁTLAN", not gb.validate(g.VOLATILITY, LAD))


# ══ 8. A MOTOR: a sáv tényleg hat ═══════════════════════════════════════
# Ugyanaz a minimál váz, mint a `test_volatility_gate.py`-ban. Az ATR a padló
# ALATT van (0,51×), tehát a szint ~175% — egy 100%-os `block` sáv blokkol, egy
# 150%-os `reduce` sáv viszont FELEZ, nem blokkol.
def _run(bands, effect="block"):
    idx1 = pd.date_range("2025-03-03 08:00", periods=400, freq="1min", tz="UTC")
    idx15 = pd.date_range("2025-03-03 08:00", periods=40, freq="15min", tz="UTC")
    m1 = pd.DataFrame({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0,
                       "avg_spread": 0.01, "close_spread": 0.01}, index=idx1)
    m15 = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
                       index=idx15)

    class S:
        name = "wpr_sma"
        default_sl_method = "atr"

        def timeframes(self):
            from strategy.base import Timeframe
            return [Timeframe("M15", 15), Timeframe("M1", 1)]

        def bt_indicators(self, hi, lo, p):
            hi = hi.copy()
            hi["atr"] = 140.19          # 0,51× a 272,75-os mércének
            hi["atr_avg"] = 272.75
            return hi, lo

        def bt_warmup(self, p, tf):
            return 0

        def bt_new_state(self, sym):
            return {}

        def bt_on_high_close(self, st, row, p):
            return st

        def bt_on_low_close(self, st, prev, row, p):
            return "BUY" if row.name == idx1[100] else "NONE"

        def bt_entry(self, row, p, ps):
            return (100.0, 200.0)

    entry = {"effect": effect}
    if bands is not None:
        entry["bands"] = bands
    cfg = {"gates": {"volatility": {"default": entry},
                     "spread": {"default": "none"},
                     "tf_align": {"default": "none"}}}
    pair_cfg = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01,
                "lot_step": 0.01, "backtest_spread_points": 1.0}
    return bt.run_pair("T", m15, m1, dict(PRM), pair_cfg,
                       {"account_risk_pct": 0.02, "max_open_slots": 1},
                       10000.0, strategy=S(), cfg=cfg, exec_gates=True)


_no_band = _run(None)
_reduce_band = _run([[150, "reduce"]])
_high_band = _run([[300, "block"]])
check("sáv nélkül BLOKKOL (a v3.28.0 előtti viselkedés)", not _no_band.trades)
check("150%-os `reduce` sáv → VAN kötés (a szint ~175%)",
      bool(_reduce_band.trades), f"{len(_reduce_band.trades)} kotes")
check("300%-os sáv → a 175%-os szint NEM éri el, nincs hatás",
      bool(_high_band.trades), f"{len(_high_band.trades)} kotes")
_l_red = _reduce_band.trades[0].lot if _reduce_band.trades else None
_l_full = _high_band.trades[0].lot if _high_band.trades else None
check("...és a `reduce` sáv FELEZI a lotot",
      _l_red and _l_full and abs(_l_red - _l_full * g.REDUCE_RISK_FACTOR) < 1e-9,
      f"{_l_full} -> {_l_red}")


# ══ 9. A FELÜLET: Hatás fül, + Sáv, Törlés, mentés ══════════════════════
try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as _ex:
    print(f"SKIP  a felületi rész (nincs képernyő: {_ex})")
    _root = None

if _root is not None:
    from dashboard import gate_dialog as gd

    cfg = {"pairs": {SYM: {"point_size": 0.1}},
           "gates": {g.VOLATILITY: {"default": "block"}}}
    d = gd.GateDialog(_root, cfg, SYM, g.VOLATILITY, [ST])
    check("van HATÁS fül", "effect" in {n for n, _l in d._shell.tabs}
          if hasattr(d._shell, "tabs") else True)
    check("induláskor nincs sáv-sor", len(d._band_rows[ST]) == 0)
    d._add_band_row(ST, gb.SCALAR)
    d._add_band_row(ST, gb.SCALAR)
    check("a `+ Sáv` két sort ad", len(d._band_rows[ST]) == 2)
    d._drop_band_row(ST, d._band_rows[ST][0])
    check("a Törlés eltávolítja a sort a NYILVÁNTARTÁSBÓL is",
          len(d._band_rows[ST]) == 1)
    d._band_rows[ST][0][0].delete(0, "end")
    d._band_rows[ST][0][0].insert(0, "80")
    d._band_rows[ST][0][1].set(g.EFFECT_LABEL[g.EFFECT_REDUCE])
    check("az űrlap visszaadja a sávot",
          d.raw_bands()[ST] == [[80.0, "reduce"]], str(d.raw_bands()))
    d._save()
    check("mentés után a configban ott a sáv",
          gb.ladder(cfg, SYM, ST, g.VOLATILITY) == [(80.0, "reduce")],
          str(gb.ladder(cfg, SYM, ST, g.VOLATILITY)))

    # ⚠ A HIBÁS SÁV NEM MENTŐDIK — és a RÉSZLEGES mentés is tilos.
    cfg2 = {"pairs": {SYM: {"point_size": 0.1}}}
    d2 = gd.GateDialog(_root, cfg2, SYM, g.VOLATILITY, [ST])
    d2._add_band_row(ST, gb.SCALAR)
    d2._band_rows[ST][0][0].insert(0, "5000")
    d2._save()
    check("a tartományon kívüli sáv NEM kerül a configba",
          not gb.ladder(cfg2, SYM, ST, g.VOLATILITY),
          str(gb.ladder(cfg2, SYM, ST, g.VOLATILITY)))
    check("...és az ablak KIÍRJA az okot",
          "%" in d2.lbl_err.cget("text") or d2.lbl_err.cget("text") != "",
          d2.lbl_err.cget("text")[:70])
    _root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
