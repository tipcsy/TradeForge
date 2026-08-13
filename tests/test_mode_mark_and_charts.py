"""„V"/„J" jelolo + nyitott MT5-chart eszlelese.

Harom keres:
  1. a jelzesek elott legyen egy betu: JELEZ vagy VALODI kereskedest indit,
  2. az OPT kerüljön le a sorbeli vezerlesrol,
  3. lassuk, hogy az MT5-on nyitva van-e a chart.

⚠ MIERT KELL AZ 1. ES A 3.: a ket allapot ranezesre AZONOS volt — ugyanaz a
potty-sor, ugyanaz a zold Play gomb —, pedig az egyik penzt mozgat, a masik nem.
Es ami meg rosszabb: „csak jelzes" modban a jelzes CSAK az MT5 charton latszik.
Ha ahhoz a parhoz nincs nyitott chart a TradeForgeViz-cel, a jelzes SEHOL nem
jelenik meg — a program dolgozik, es semmi nem tortenik. Errol eddig semmi nem
szolt.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from dashboard import live_row as lr
from core import mt_charts as mc

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A JELOLO ────────────────────────────────────────────────────────────
from dashboard import theme as th

check("valodi kereskedes -> „V”",
      lr._mode_mark({"mode": "live", "live": True}) == ("V", th.FG_GREEN))
# ⚠ A BETU ONMAGABAN eleg — a SZIN hordozza az uzenetet. A felkialtojel csak
# zsufolta a cellat (a pottyokre csuszott), es nem mondott tobbet a szinnel.
check("csak jelzes, van chart -> „J” ZOLDEN",
      lr._mode_mark({"mode": "signal", "live": True, "chart_open": True})
      == ("J", th.FG_GREEN))
# ⚠ EZ A LENYEG: jelzes-mod NYITOTT CHART NELKUL — a jelzes sehova nem jut el.
check("csak jelzes, NINCS chart -> „J” PIROSAN",
      lr._mode_mark({"mode": "signal", "live": True, "chart_open": False})
      == ("J", th.FG_RED))
check("a jelolo MINDIG egy karakter (nincs felkialtojel)",
      all(len(lr._mode_mark(x)[0]) <= 1 for x in (
          {"mode": "live", "live": True},
          {"mode": "signal", "live": True, "chart_open": True},
          {"mode": "signal", "live": True, "chart_open": False},
          {"mode": "signal", "live": False})))
# Ami nem fut, ott a mod kerdese pillanatnyilag nem dont semmit.
check("allitva -> halvany, nincs riasztas",
      lr._mode_mark({"mode": "signal", "live": False, "chart_open": False})[1]
      == th.FG_GRAY_DIM)
check("valodi modban a chart hianya NEM riaszt (a bot ugy is kereskedik)",
      lr._mode_mark({"mode": "live", "live": True, "chart_open": False})
      == ("V", th.FG_GREEN))
check("ismeretlen mod -> nincs betu", lr._mode_mark({})[0] == "")
# ⚠ Ha nem tudjuk (nincs adat), NE riasszunk: a hamis riasztas ugyanolyan rossz,
# mint a hianyzo — par kor utan senki nem nezne.
check("hianyzo chart-adat -> nem riaszt",
      lr._mode_mark({"mode": "signal", "live": True}) == ("J", th.FG_GREEN))


# ── 2. AZ OPT LEKERULT A SORBELI VEZERLESROL ──────────────────────────────
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception:
    TK = False

if TK:
    from dashboard import canvas_cells as cc
    d = lr.demo_row()
    d["strategies"][0]["mode"] = "signal"
    d["strategies"][0]["chart_open"] = False
    cells = cc.cells_for(d, {})
    ctrl = next(c for k, c in cells.items() if k.endswith("|ctrl"))
    # ⚠ Az OPT egy sorbeli gombrol orakra inditott valamit, amirol a felulet
    # semmit nem mondott. Az optimalizalas a Futtatas lapon indul, ahol LATOD,
    # mi fog tortenni (idoszakok, kapuk, hangolt dimenziok, keresesi ter).
    check("a vezerlesben CSAK a Play/Stop maradt",
          [p[0] for p in ctrl.parts] == ["run"], str([p[0] for p in ctrl.parts]))
    stages = next(c for k, c in cells.items() if k.endswith("|stages"))
    check("a jelzes-cella viszi a betut", stages.text == "J", stages.text)
    check("...es a szinet is", stages.fg == th.FG_RED)

    # ⚠ A BETU NEM CSUSZHAT RA A KERETRE. Elso nekifutasra a mar kozepre tett
    # potty-blokk BALJARA kerult, es a keret pont ott kezdodik (`sx-4`) — a
    # kepernyon osszefolytak. Most a betu es a pottyok EGYUTT kerulnek kozepre.
    import copy as _copy
    from dashboard import canvas_table as _ct
    _root = tk.Tk(); _root.withdraw()
    from dashboard import theme as _th2
    _th2._FONTS.clear()
    _f = _th2.fonts()
    _rows = []
    for _sym, _fr in (("AAA", "blocked"), ("BBB", "reduced")):
        _r = _copy.deepcopy(lr.demo_row()); _r["symbol"] = _sym
        _s0 = _r["strategies"][0]
        _s0.update(mode="signal", live=True, chart_open=False, frame=_fr)
        _rows.append(_r)
    _tbl = _ct.CanvasTable(_root, _f, rows=_rows, collapsed={})
    _root.update_idletasks()
    _bad = []
    for _i in range(len(_rows)):
        _ids = _tbl._items.get((_i, "wpr_sma|stages")) or []
        _bc = _tbl._bc["mid"]
        _tx = [t for t in _ids if _bc.type(t) == "text"]
        _rc = [t for t in _ids if _bc.type(t) == "rectangle"]
        if _tx and _rc:
            if _bc.bbox(_tx[0])[2] > _bc.bbox(_rc[-1])[0]:
                _bad.append(_rows[_i]["symbol"])
    check("a betu NEM log ra a keretre", not _bad, str(_bad))
    # Az oszlop mintaszovege birja el a betut is.
    check("a „stages” oszlop mintaja szamol a betuvel",
          "V" in lr._SAMPLE["stages"][1], lr._SAMPLE["stages"][1])
    _root.destroy()
else:
    check("nincs tkinter (a cella-tesztek kihagyva)", True)


# ── 3. AZ ELETJEL beolvasasa ──────────────────────────────────────────────
tmp = Path(tempfile.mkdtemp(prefix="mtcharts_test_"))
_orig = mc.common_dir
mc.common_dir = lambda: tmp
try:
    check("ures mappa -> nincs nyitott chart", mc.open_charts() == [])

    (tmp / (mc.PREFIX + "GOLD_1.txt")).write_text(
        "ALIVE;GOLD;1;wpr_sma;2026.08.13 10:00:00;1786000000", encoding="utf-8")
    ch = mc.open_charts()
    check("egy eletjel -> egy nyitott chart", len(ch) == 1, str(ch))
    check("a szimbolum a TARTALOMBOL jon", ch[0]["symbol"] == "GOLD", str(ch[0]))
    check("az idosik es a strategia is", ch[0]["timeframe"] == "1"
          and ch[0]["strategia" if False else "strategy"] == "wpr_sma", str(ch[0]))
    check("open_symbols halmazt ad", mc.open_symbols() == {"GOLD"})
    check("is_open igaz ra", mc.is_open("GOLD") and not mc.is_open("Ger40"))

    # ⚠ A SZIMBOLUM TARTALMAZHAT ALAHUZAST (pl. US_500) — a NEVBOL bontva
    # elhasalna. Ezert olvassuk a tartalmat.
    (tmp / (mc.PREFIX + "US_500_15_wpr.txt")).write_text(
        "ALIVE;US_500;15;wpr;2026.08.13 10:00:00;1786000000", encoding="utf-8")
    check("alahuzasos szimbolum is helyes", "US_500" in mc.open_symbols(),
          str(mc.open_symbols()))

    # ⚠ AZ IDOT A FAJL KORABOL vesszuk, nem a benne levo idobelyegbol: a
    # terminal SZERVER-idot ir, ami orakkal elterhet a gep orajatol.
    old = tmp / (mc.PREFIX + "Ger40_5.txt")
    old.write_text("ALIVE;Ger40;5;;2026.08.13 10:00:00;1786000000", encoding="utf-8")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    check("a REGI eletjel nem szamit nyitottnak",
          "Ger40" not in mc.open_symbols(), str(mc.open_symbols()))
    check("...de nagyobb turessel igen",
          "Ger40" in mc.open_symbols(max_age_sec=7200))

    # A takaritas kuszobe SOKKAL nagyobb: egy par percre megakadt terminal
    # fajljat eldobni azt jelentene, hogy a chart „bezarult", holott csak lassu.
    n = mc.cleanup_stale(max_age_sec=1800)
    check("a nagyon regit takaritja", n == 1 and not old.exists(), str(n))
    check("...az eloket nem bantja", mc.open_symbols() == {"GOLD", "US_500"},
          str(mc.open_symbols()))

    # Serult fajl: ne robbanjon, essen vissza a nevre.
    (tmp / (mc.PREFIX + "EURUSD_60.txt")).write_text("szemet", encoding="utf-8")
    check("serult eletjel sem robban", "EURUSD_60" in mc.open_symbols(),
          str(mc.open_symbols()))
finally:
    mc.common_dir = _orig
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── 4. Az INDIKATOR oldala: ir es TOROL ───────────────────────────────────
_viz = (ROOT / "mt5" / "TradeForgeViz.mq5").read_text(encoding="utf-8")
check("az indikator ir eletjelet", "WriteHeartbeat" in _viz)
check("...induláskor is (nem kell a timerre varni)",
      _viz.index("WriteHeartbeat();") < _viz.index("void OnTimer()"))
# ⚠ Chart bezarasakor TOROLNI kell: nelkule a fajl KORA dontene, tehat percekig
# „elonek" latszana egy bezart chart.
check("...es bezaraskor TORLI", "FileDelete" in _viz and "OnDeinit" in _viz)
check("peldanyonkent KULON fajl (szimbolum + idosik)",
      '"TFV_ALIVE_" + _Symbol + "_" + IntegerToString((int)Period())' in _viz)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
