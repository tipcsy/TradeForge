"""A `trend_pullback` chart-rajza — és hogy AZT rajzolja, amivel dönt.

⚠ A KÉRÉS (2026-08-31): a felhasználó a „H1 felső sáv fölött" kör jelentését
kérdezte, majd kérte, hogy a vonal a charton is látszódjon — ugyanúgy
be/kikapcsolhatóan, mint a többinél.

A KÖR NEM TUDJA MEGMUTATNI, MENNYIRE VAN KÖZEL AZ ÁR. Ég vagy nem ég; a
percek 3-6%-án ég. Hogy az ár 20 vagy 400 ponttal van a sáv alatt, abból nem
derül ki — a chartra rajzolt vonalból igen.

A TESZT LÉNYEGE A PARITÁS: a kirajzolt felső sáv PONTOSAN az a szám, amit a
feltétel használ (`c60 > EMA + k·ATR`). Ha a rajz és a döntés két külön
képletből jönne, a chart magabiztosan mutatna valamit, ami nem az, ami alapján
a motor kereskedik — ez a projekt visszatérő hibaosztálya (viz ↔ backtest
paritás, TFBANDS-romlás).

⚠ AZ ALSÓ SÁV SZÁNDÉKOSAN HIÁNYZIK. A stratégia LONG-ONLY, és egyedül a FELSŐ
sáv szerepel a feltételben. Egy alsó vonal azt sugallná, hogy az is számít.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import strategies.trend_pullback as T
from strategy import get_strategy_by_name
from strategy.base import MarketData
from strategy.settings import config_for_strategy, load_config
from trading.live_trader import default_params, strategy_params

SN = "trend_pullback"
st = get_strategy_by_name(SN)
cfg = load_config("config.json")
cs = config_for_strategy(cfg, SN)

SYM = "UsaTec"
_pq1 = ROOT / "data" / "m1" / f"{SYM}.parquet"
if not _pq1.exists():
    print(f"      (nincs {SYM} M1 parquet — a teszt kimarad)")
    print()
    print("0/0 teszt PASS")
    sys.exit(0)

p = strategy_params(SYM, SN, cs, fallback=default_params(st, cs))
p = {**p, "symbol": SYM, "point_size": cfg["pairs"][SYM]["point_size"]}

w1 = st.visual_lookback_bars(p, "M1")
w15 = st.visual_lookback_bars(p, "M15")
d1 = pd.read_parquet(_pq1).tail(w1)
d15 = pd.read_parquet(ROOT / "data" / "m15" / f"{SYM}.parquet").tail(w15)
md = MarketData(symbol=SYM, params=p, bars={"M1": d1, "M15": d15})
objs = st.visual_objects(md)

check("a stratégia RAJZOL a chartra", bool(objs), f"{len(objs)} objektum")

# ── 1. A két vonal ─────────────────────────────────────────────────────
_nev = [str(getattr(o, "name", "")) for o in objs if getattr(o, "name", "")]
_mid = [o for o in objs if str(getattr(o, "name", "")).startswith("tpk_mid")]
_up = [o for o in objs if str(getattr(o, "name", "")).startswith("tpk_up")]
check("kirajzolódik a KÖZÉPVONAL (EMA)", bool(_mid), f"{len(_mid)} szakasz")
check("kirajzolódik a FELSŐ SÁV", bool(_up), f"{len(_up)} szakasz")
check("⚠ ALSÓ sáv NINCS (a stratégia long-only)",
      not [o for o in objs if "low" in str(getattr(o, "name", "")).lower()])

# ⚠ Az MT5 objektumokat a NEVÜK azonosítja: két azonos név a chart némán
# felülírja egymást. A `tp_<idő>` a take-profit vonalé — a Keltner-vonal NEM
# vihet `tp_` előtagot.
check("⚠ minden objektum-név EGYEDI",
      len(_nev) == len(set(_nev)), f"{len(_nev) - len(set(_nev))} ütközés")
check("⚠ a Keltner-vonal nem ütközik a take-profit nevével",
      not [n for n in _nev if n.startswith("tp_")
           and not n.startswith("tpk_")
           and not n.split("_", 1)[1].isdigit()])

# ── 2. PARITÁS: a rajz = a döntés ──────────────────────────────────────
# ⚠ EZ A TESZT LELKE. A kirajzolt felső sáv utolsó pontja pontosan az a
# küszöb, amivel a `_stage_masks` a „trend" kört meggyújtja.
per = int(p.get("keltner_period", 14) or 14)
mul = float(p.get("keltner_mult", 2.0) or 2.0)
d60 = T._resample(d1, T.TF_TREND)
c60 = d60["close"].to_numpy(float)
_ema = T._ema(c60, per)
_atr = T._atr(d60["high"].to_numpy(float), d60["low"].to_numpy(float), c60, per)
_felso = _ema + mul * _atr

_utolso_up = max(_up, key=lambda o: o.t2)
check("⚠ a kirajzolt FELSŐ SÁV = a feltétel küszöbe",
      abs(_utolso_up.p2 - _felso[-1]) < 1e-6,
      f"rajz {_utolso_up.p2:.2f} vs feltétel {_felso[-1]:.2f}")
_utolso_mid = max(_mid, key=lambda o: o.t2)
check("...és a középvonal = az EMA",
      abs(_utolso_mid.p2 - _ema[-1]) < 1e-6,
      f"rajz {_utolso_mid.p2:.2f} vs EMA {_ema[-1]:.2f}")

# ── 3. A SÁV a H1-feltételt mutatja ────────────────────────────────────
_bs = [o for o in objs if type(o).__name__ == "BarState"]
check("van állapot-sáv", bool(_bs), f"{len(_bs)} rekord")
_m = T._stage_masks(d1, p)
_idx = d1.index
_hiba = 0
for o in _bs:
    _i = _idx.get_indexer([pd.Timestamp(o.t, unit="s", tz="UTC")], method="nearest")[0]
    if bool(_m["trend"][_i]) != bool(o.window):
        _hiba += 1
check("⚠ a sáv PONTOSAN a trend-feltételt követi", _hiba == 0,
      f"{_hiba} eltérés {len(_bs)} rekordból")
# ⚠ …és nem világít mindig: egy állandó sáv nem jelzés, hanem dísz.
_vil = sum(1 for o in _bs if o.window)
check("...és nem dísz (nem világít végig)", 0 < _vil < len(_bs) * 0.5,
      f"{100 * _vil / len(_bs):.1f}%")

# ── 4. A BELÉPŐ-jelölők ────────────────────────────────────────────────
_sig = [o for o in objs if str(getattr(o, "name", "")).startswith("m1sig")]
_sl = [o for o in objs if str(getattr(o, "name", "")).startswith("sl_")]
_tp = [o for o in objs if str(getattr(o, "name", "")).startswith("tp_")]
check("vannak belépő-jelölők", bool(_sig), f"{len(_sig)} db")
# ⚠ MINDEGYIKNEK legyen SL/TP vonala. A méret az M15 ATR-ből jön: ha az M15
# ablak sekélyebb, mint a rajzolt szakasz, a régebbi jelölők NÉMÁN vonal
# nélkül maradnának (mérve: 17-ből 2-nek volt csak).
# ⚠ 2026-08-31 ÓTA a jelölő KÉTFÉLE: ami ténylegesen kötne (színes, vastag
# vonal + SL/TP), és ami egy még NYITOTT pozíció miatt kimarad (vékony szürke
# vonal, SL/TP NÉLKÜL — az kötést sugallna). Az eredeti lelet ettől érvényben
# marad, csak a KÖTŐ jelölőkre vonatkozik: a sekély M15 ablaknál a régebbi
# belépők NÉMÁN vonal nélkül maradtak (17-ből 2-nek volt csak).
_kot = [o for o in _sig if getattr(o, "color", "") != "muted"]
_kim = [o for o in _sig if getattr(o, "color", "") == "muted"]
check("⚠ a jelölők egy része KIMARAD (nyitott pozíció miatt)",
      0 < len(_kim) < len(_sig), f"{len(_kot)} kötne / {len(_sig)} jelzés")
check("⚠ MINDEN KÖTŐ jelölőhöz tartozik SL vonal", len(_sl) == len(_kot),
      f"{len(_sl)} SL / {len(_kot)} kötő jelölő")
check("⚠ ...és TP vonal is", len(_tp) == len(_kot),
      f"{len(_tp)} TP / {len(_kot)} kötő jelölő")
check("⚠ ...a KIMARADÓ jelölő viszont vékony és szürke",
      all(getattr(o, "width", 0) == 1 for o in _kim))

# A jelölők a MOTOR jelével egyeznek (ugyanaz a `signal_column`, nem másolat).
_sc = T.signal_column(d1, p)
_elek = {int(_idx[i].timestamp()) + 60
         for i in range(1, len(_idx) - 1)
         if bool(_sc[i]) and not bool(_sc[i - 1])}
_rajz = {int(o.t1) for o in _sig}
check("⚠ a jelölők a MOTOR jeléből jönnek (nem külön képletből)",
      _rajz <= _elek, f"{len(_rajz - _elek)} olyan jelölő, ami nem felfutó él")

# ── 5. Be/kikapcsolható ────────────────────────────────────────────────
# ⚠ A „K" gomb a RAJZOT kapcsolja, nem a TÖRTÉNÉST: a belépő-rekord akkor is
# a naplóba megy, ha a jelölők ki vannak kapcsolva — különben a chart
# előzménye csendben lyukas lenne azokon az időszakokon.
_recs = []
md2 = MarketData(symbol=SYM, params=p, bars={"M1": d1, "M15": d15},
                 show_signals=False)
md2.on_entry_record = _recs.append
_objs2 = st.visual_objects(md2)
check("kikapcsolva NINCS belépő-jelölő",
      not [o for o in _objs2 if str(getattr(o, "name", "")).startswith("m1sig")])
check("⚠ ...de a belépő-REKORD attól még keletkezik (napló)",
      len(_recs) == len(_sig), f"{len(_recs)} rekord / {len(_sig)} jelölő")
check("a Keltner-vonalak kikapcsolva IS látszanak (nem jelölők)",
      bool([o for o in _objs2 if str(getattr(o, "name", "")).startswith("tpk_")]))

# A stratégia-szintű be/ki a közös `viz_prefs` (pár + stratégia) — nem itt.
from core import viz_prefs as _vp
_c = {"pairs": {SYM: {}}}
_vp.set_on(_c, SYM, SN, _vp.VIZ, False)
check("⚠ a stratégia-szintű ki/be a KÖZÖS viz_prefs-en megy",
      _vp.viz_on(_c, SYM, SN) is False)
_vp.set_on(_c, SYM, SN, _vp.VIZ, True)
check("...és visszakapcsolható", _vp.viz_on(_c, SYM, SN) is True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
