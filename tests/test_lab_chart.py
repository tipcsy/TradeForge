"""KÉZI LABORATÓRIUM 2. LÉPCSŐ — a chart-ablak.

⚠ A KÉRÉS (2026-08-31-2, a felhasználó válasza): „Igen, ez egy teljesen
független »program« legyen, de használja a program egyes moduljait úgy, hogy
NE KELETKEZZENEK BELŐLE MÁSOLATOK."

Ez a teszt elsősorban a MÁSOLAT-MENTESSÉGET őrzi. A projekt visszatérő
kárforrása a két forrás, ami külön romlik el: a `BacktestReplayer` v4 azért
készült, mert a korábbi verzió ÚJRASZIMULÁLT; a viz ↔ backtest paritás és a
TFBANDS-sáv 0%-os egyezése ugyanez a minta. Egy chart-ablak, ami a jelölőket
maga számolná ki, pontosan ide vezetne vissza — csak nagyobb felületen.

Ezért a labor:

  * a gyertyákat a `trading.backtest.load_data` parquetjéből veszi,
  * a rajzot a `live_trader.pair_visual_objects()`-ból kapja (ugyanaz a hívás,
    amiből az MT5-fájl készül, ugyanazokkal a kapukkal),
  * a színeket a `strategy.visual.COLORS`-ból,
  * a durvább idősíkot a meglévő `resample_ohlc`-ból.

⚠ A `pair_visual_objects` EMIATT lett kiemelve: a `pair_visual_lines` TAGELT
SZÖVEGES sorokat ad (az MT5-fájl formátuma). Ha a chart azokat parszolná
vissza, a formátum ismerete MÁSODSZOR jelenne meg a kódban.
"""
import ast
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import numpy as np
import pandas as pd

from strategy import visual as viz
from tools import lab_chart as lc

# ── 1. NINCS MÁSOLAT ──────────────────────────────────────────────────────
_src = (ROOT / "tools" / "lab_chart.py").read_text(encoding="utf-8")
_fa = ast.parse(_src)
_hivott = {n.func.id for n in ast.walk(_fa)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
_hivott |= {n.func.attr for n in ast.walk(_fa)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

check("a rajz a MOTOR objektumaiból jön (`pair_visual_objects`)",
      "pair_visual_objects" in _hivott)
check("a gyertyák a meglévő parquet-betöltőből (`load_data`)",
      "load_data" in _hivott)
check("a durvább idősík a meglévő átmintázóból (`resample_ohlc`)",
      "resample_ohlc" in _hivott)
check("a színek a `visual.COLORS`-ból", "viz.COLORS" in _src)

# ⚠ NEM parszolhatja vissza az MT5-fájl sorait — abból lenne a második forrás.
for _tilos in ("pair_visual_lines", "split(\";\")", "mt5_visual", "read_lines"):
    check(f"nem nyúl az MT5 fájlformátumhoz ({_tilos!r})", _tilos not in _src)
# ⚠ És nem számol saját indikátort/jelet sem.
for _tilos in ("def _wpr", "def _sma", "def _atr", "rolling("):
    check(f"nincs saját indikátor-számítás ({_tilos!r})", _tilos not in _src)

# ── 2. A KIEMELT VARRAT ───────────────────────────────────────────────────
from trading import live_trader as _lt

check("a `pair_visual_objects` létezik", hasattr(_lt, "pair_visual_objects"))
check("a `pair_visual_lines` megmaradt (MT5-út)",
      hasattr(_lt, "pair_visual_lines"))
_lt_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
_lines_fn = _lt_src.split("def pair_visual_lines", 1)[1].split("\ndef ", 1)[0]
check("a `pair_visual_lines` MÁR CSAK szövegesít (az objektumokat hívja)",
      "pair_visual_objects(" in _lines_fn and "tag_line" in _lines_fn)

# ── 3. SZÍNEK ─────────────────────────────────────────────────────────────
check("a zöld ugyanaz, mint az MT5-ön",
      lc.szin("green") == "#%02x%02x%02x" % viz.COLORS["green"])
check("ismeretlen színnév → fehér (nem hiba)",
      lc.szin("nincsilyen") == lc.szin("white"))

# ── 4. IDŐTENGELY: epoch → gyertya-index ──────────────────────────────────
_idx = pd.date_range("2026-08-27 00:00", periods=10, freq="15min", tz="UTC")
_t = lc.Idotengely(_idx)
# ⚠ A LEKÉPEZÉS GEOMETRIAI, NEM „BÁR KÖZEPE". A `j` indexű gyertya vizuálisan
# a [j-0.5, j+0.5) sávot foglalja el, és a `t_j` időpont ennek a BAL SZÉLE —
# ott kezdődik a gyertya. Az első tesztváltozatomban a bár közepét vártam (az
# MT5 konvenciója szerint), de az ELRONTANÁ a labor lényegét: egy M15-ös
# charton az M1-es belépő-jelölők mind a gyertya közepére torlódnának, holott
# épp az a kérdés, a gyertyán BELÜL mikor született a jel.
check("a gyertya nyitó ideje a gyertya BAL SZÉLÉRE esik",
      abs(_t.hol(int(_idx[3].timestamp())) - 2.5) < 0.01,
      str(_t.hol(int(_idx[3].timestamp()))))
_kozep = int(_idx[3].timestamp()) + 450          # a 15 perces bár fele
check("a gyertyán belüli idő a gyertya KÖZEPÉRE esik",
      abs(_t.hol(_kozep) - 3.0) < 0.01, str(_t.hol(_kozep)))
_veg = int(_idx[3].timestamp()) + 890            # majdnem a bár vége
# ⚠ A 3.5 HELYES, nem határhiba: a 3. gyertya jobb széle ÉS a 4. bal széle
# ugyanaz a pont. A leképezés a legközelebbi bárra kapcsol, tehát a bár
# második felében már a következő gyertya bal széléhez mér — a rajzolt hely
# folytonos, nem ugrik.
check("a bár vége a jobb szélére (= a következő bal szélére) esik",
      abs(_t.hol(_veg) - 3.5) < 0.02, str(_t.hol(_veg)))
# ⚠ A TÁVOLI IDŐ KIESIK, nem ragad a chart szélére — különben egy hónappal
# arrébbi jelölő itt ülne, és a kép hazudna.
check("a messzi időpont kiesik (None)",
      _t.hol(int(_idx[0].timestamp()) - 86400) is None)
check("az időszak utáni is kiesik",
      _t.hol(int(_idx[-1].timestamp()) + 86400) is None)

# ── 5. RAJZOLÁS (fej nélkül) ──────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_n = 40
_ar = 29000 + np.cumsum(np.random.default_rng(7).normal(0, 10, _n))
_df = pd.DataFrame({"open": _ar, "high": _ar + 8, "low": _ar - 8, "close": _ar},
                   index=pd.date_range("2026-08-27", periods=_n, freq="15min",
                                       tz="UTC"))
_fig, (_ax, _axs) = plt.subplots(2, 1)
lc.gyertyak(_ax, _df)
check("a gyertyák kirajzolódnak", len(_ax.collections) >= 2,
      str(len(_ax.collections)))

_te = lc.Idotengely(_df.index)
_t5 = int(_df.index[5].timestamp())
_t9 = int(_df.index[9].timestamp())
_objs = [
    viz.VLine("v", _t5, "red", 2),
    viz.Trend("tr", _t5, 29000.0, _t9, 29050.0, "green", 1, 0),
    viz.Rect("r", _t5, 29000.0, _t9, 29020.0, "blue", True),
    viz.Arrow("a", _t5, 29010.0, 233, "white", 1),
    viz.Text("tx", _t5, 29030.0, "proba", "yellow", 9),
    viz.Indicator("MA", "M15", 90),
    viz.BarState(t=_t5, dir=1, window=1),
    # ⚠ Ez esik ki: egy nappal korábbi.
    viz.VLine("regi", _t5 - 86400, "red", 1),
]
_db = lc.objektumok_rajza(_ax, _objs, _te)
check("öt geometriai objektum kirajzolva", _db["kirajzolt"] == 5, str(_db))
check("az időn kívüli KÜLÖN SZÁMOL (nem tűnik el némán)",
      _db["idon_kivul"] == 1, str(_db))
check("az Indicator nem geometria (nem a chartra kerül)",
      _db.get("Indicator") == 1, str(_db))

check("a sáv-állapot kirajzolódik", lc.allapot_sav(_axs, _objs, _te) == 1)
# ⚠ BarState nélkül a sáv REJTVE marad — üres tengely félrevezető lenne.
_ures_fig, _ures_ax = plt.subplots()
check("BarState nélkül a sáv rejtve",
      lc.allapot_sav(_ures_ax, [o for o in _objs
                                if not isinstance(o, viz.BarState)], _te) == 0
      and not _ures_ax.get_visible())

check("a kísérő panel az indikátort kiírja",
      any("MA M15(90)" in s for s in lc.kiserok(_objs)), str(lc.kiserok(_objs)))
plt.close("all")

# ── 6. IDŐSÍK-VÁLTÁS ──────────────────────────────────────────────────────
_m1 = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
                   index=pd.date_range("2026-08-27", periods=240, freq="1min",
                                       tz="UTC"))
_m15 = lc.chart_barok(_m1, None, 15) if False else None
check("M1 → az M1 táblát adja", lc.chart_barok(_m1, "M15DF", 1) is _m1)
check("M15 → az M15 táblát adja", lc.chart_barok(_m1, "M15DF", 15) == "M15DF")
_m5 = lc.chart_barok(_m1, None, 5)
check("M5 az M1-ből mintázódik", len(_m5) == 48, str(len(_m5)))
# ⚠ Az OHLC ne romoljon: a durvább gyertya nyitója az első M1 nyitója.
check("az átmintázott gyertya nyitója az első M1-é",
      float(_m5["open"].iloc[0]) == 1.0)

# ── 7. IDŐSZAK-VÁGÁS ──────────────────────────────────────────────────────
# ⚠ A határok NAIV időként érkeznek (ahogy a charton látod), az index viszont
# időzóna-tudatos. A `TypeError` a HATÁRON dőljön el, ne a rajzolás közben.
_v = lc._vag(_m1, "2026-08-27 01:00", "2026-08-27 02:00")
check("az időzóna-eltérés nem dob (naiv határ, tz-aware index)", len(_v) > 0)
check("a vágás a megadott szakaszt adja",
      str(_v.index[0])[:16] == "2026-08-27 01:00", str(_v.index[0]))
# ⚠ A CSAK DÁTUM végpont a nap VÉGÉT jelentse: „-ig 08-27" ne 00:00-nál vágjon.
_nap = lc._vag(_m1, "2026-08-27", "2026-08-27")
check("a csak dátumos -ig a nap végéig tart", len(_nap) == len(_m1),
      f"{len(_nap)} / {len(_m1)}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
