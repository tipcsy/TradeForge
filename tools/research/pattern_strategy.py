"""KUTATASI HARNESS: a holdout-keresesbol jott mintak a VALODI motoron.

A `search.py`/`holdout.py` merese JELZES-MINOSEGET mer: minden M5 gyertyat
onalloan ertekel, es nincs benne slot-korlat, atfedo kotes-kizaras, orakapu,
vegrehajtasi kapu. A valodi szam a `trading.backtest.run_pair`-bol jon.

⚠ EZ A FAJL SZANDEKOSAN NEM A `strategy/` MAPPABAN VAN. A `strategy/__init__.py`
auto-felderiti az ottani modulokat, es a felhasznalo dashboardjan azonnal
megjelenne egy fel-kesz kutatasi strategia. A felhasznalo VALIDACIOT kert, nem
elesitest — ha a lelet megall, akkor lesz belole rendes modul.

A MINTA-NYELV (a search.py-bol):
    "M240:donchian14_kitores_fel + M15:obv14>sma"
Egy ESEMENY + egy vagy ket ALLAPOT, mind (idosik, nev) parral azonositva.
A kiertekeles ugyanazokkal a fuggvenyekkel megy, mint a keresesnel
(`signal_lib._allapotok` / `_esemenyek`), tehat nincs ket kulon implementacio,
ami elcsuszhatna egymastol.

LOOK-AHEAD: a magasabb idosik jelet a bar ZARASA utani elso M1 gyertyatol
hasznaljuk (`searchsorted` a zarasi idokre) — ugyanaz a vedelem, mint a
signal_lib-ben, es ugyanaz az onteszt vonatkozik ra.
"""

from __future__ import annotations

import re
import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import lab
import signal_lib
from strategy.base import Cell, MarkerColumn, Strategy, Timeframe

_TF_RE = re.compile(r"^M(\d+):(.+)$")
_P_RE = re.compile(r"(\d+)")


def _param_of(nev: str) -> int:
    """A jel nevebe agyazott parameter (pl. 'sma50_atlepes_fel' -> 50)."""
    m = _P_RE.search(nev)
    return int(m.group(1)) if m else 14


def maszk(m1: pd.DataFrame, mintazat: str) -> np.ndarray:
    """A mintazat boolean maszkja az M1 sorokra, look-ahead nelkul."""
    reszek = [r.strip() for r in mintazat.split("+")]
    out = np.ones(len(m1), dtype=bool)
    for i, resz in enumerate(reszek):
        mm = _TF_RE.match(resz)
        if not mm:
            raise ValueError(f"ertelmezhetetlen jel: {resz!r}")
        tf, nev = int(mm.group(1)), mm.group(2)
        d = lab.resample(m1, tf) if tf > 1 else m1
        p = _param_of(nev)
        tabla = (signal_lib._esemenyek(d, p) if i == 0
                 else signal_lib._allapotok(d, p))
        if nev not in tabla:
            raise KeyError(f"ismeretlen jel: M{tf}:{nev}")
        v = np.asarray(tabla[nev])
        # a bar ZARASA utan valik ervenyesse — ez a look-ahead elleni vedelem
        zaras = d.index + pd.Timedelta(minutes=tf)
        j = np.searchsorted(zaras, m1.index, side="right") - 1
        ok = j >= 0
        col = np.zeros(len(m1), dtype=bool)
        jj = np.where(ok, j, 0)
        col[ok] = np.where(np.isfinite(v[jj[ok]].astype(float)), v[jj[ok]], False)
        out &= col
    return out


class PatternStrategy(Strategy):
    """Egyetlen mintazatot futtat a valodi motoron. Csak kutatasra."""

    name = "__kutatas_mintazat"          # a ketto alahuzas jelzi: nem produkcio
    default_sl_method = "atr"

    def __init__(self, mintazat: str, irany: str = "BUY"):
        self.mintazat = mintazat
        self.irany = irany

    # ── vaz-interfesz (a motor keri, de kutatasban nem hasznaljuk) ──────────
    def timeframes(self):
        return [Timeframe("M15", 15), Timeframe("M1", 1)]

    def columns(self):
        return [MarkerColumn("marks", "Minta", stages=["jel"])]

    def warmup_bars(self, params, tf):
        return 300 if tf == "M15" else 300

    def bt_warmup(self, params, tf):
        # a mintazat H4/200-as jeleket is hasznalhat -> boven merjuk
        return 3000 if tf == "M1" else 300

    def compute_display(self, md):
        return {"jel": Cell("-", "muted")}

    def new_signal_state(self, symbol):
        return None

    def on_bar_close(self, state, md):
        return state, "NONE"

    def base_params(self, cfg):
        return {"sl_atr_mult": 1.5, "tp_rr_ratio": 2.0, "atr_period": 14}

    def param_space(self, cfg, base, method, max_trials):
        return []

    # ── backtest-hookok ────────────────────────────────────────────────────
    def bt_indicators(self, df_hi, df_lo, params):
        hi = df_hi.copy()
        hi["atr"] = lab.atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                            hi["close"].to_numpy(float),
                            int(params.get("atr_period", 14) or 14))
        lo = df_lo.copy()
        lo["_jel"] = maszk(df_lo, self.mintazat)
        return hi, lo

    def bt_new_state(self, symbol):
        return None

    def bt_on_high_close(self, state, hi_row, params):
        return state

    def bt_on_low_close(self, state, prev_lo_row, lo_row, params):
        # A minta ALLAPOT-jellegu: az elso olyan M1 baron lepunk be, ahol IGAZ
        # lett (elozo hamis) — kulonben egy tobb-oras allapot minden percben
        # ujra jelezne. Ez a "felfegyverez -> tuzel" minta megfeleloje.
        try:
            most = bool(lo_row["_jel"])
            elozo = bool(prev_lo_row["_jel"]) if prev_lo_row is not None else False
        except Exception:
            return "NONE"
        return self.irany if (most and not elozo) else "NONE"

    def sl_tp_points(self, hi_row, params, point_size):
        a = hi_row.get("atr", float("nan"))
        if a is None or not np.isfinite(a) or a <= 0:
            return None
        sl = (float(params.get("sl_atr_mult", 1.5)) * float(a)) / point_size
        return sl, sl * float(params.get("tp_rr_ratio", 2.0))

    def bt_entry(self, hi_row, params, point_size):
        return self.sl_tp_points(hi_row, params, point_size)
