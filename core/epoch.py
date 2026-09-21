"""Időbélyeg → int64 epoch, MÉRTÉKEGYSÉG-FÜGGETLENÜL.

⚠ MIÉRT VAN EZ KÜLÖN MODUL — egy megtörtént, NÉMA hiba miatt.

A `DatetimeIndex.values.astype("int64")` / `.asi8` / `.view("int64")` az index
SAJÁT felbontásában ad számot. A pandas 2.0 óta ez már nem mindig nanoszekundum:
a `pd.date_range(...)` a pandas 3-ban mikroszekundumos indexet ad, és egy
Parquet-körút is megőrizheti a más felbontást.

A motorban a `Timedelta.value` viszont MINDIG nanoszekundum. A kettő
összehasonlítása így 1000-szeres eltérést kap — és nem száll el, hanem
CSENDBEN mást számol. Mérve (2026-09-19, `tests/test_backtest_hot_path.py`,
pandas 3.0.6): a gyorsított backteszt-út **197 jelzés helyett 0-t** adott,
mert a `_t15_ns[...] + _delta_ns <= _t1_ns[i]` feltétel soha nem teljesült.

Ugyanez a hiba jött elő a kutató-laborban is (`tools/research/seq_stat.ns`):
ott egy 15 perces ablakból lett csendben 10 napos.

Ezért MINDEN időbélyeg-aritmetika ezen a két függvényen megy át. Ha az index
már nanoszekundumos, a hívás bitre ugyanazt adja, mint a régi kód — tehát a
meglévő eredmények nem változnak.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ns(idx) -> np.ndarray:
    """A `DatetimeIndex` NANOSZEKUNDUMBAN, int64 tömbként.

    Ez az a mértékegység, amiben a `pd.Timedelta.value` is van — tehát a
    kettő nyugodtan összeadható/összehasonlítható.
    """
    return np.asarray(pd.DatetimeIndex(idx).as_unit("ns").asi8, dtype="int64")


def sec(idx) -> np.ndarray:
    """A `DatetimeIndex` MÁSODPERCBEN (unix epoch), int64 tömbként.

    ⚠ Kerekít: csak ott szabad használni, ahol a másodperc a természetes
    felbontás (pl. a kapuk unix-időbélyegei). A gyertyahatár-aritmetika az
    `ns`-t használja, mert a másodpercre kerekítés egy nem egész másodperces
    idősík-deltánál NÉMÁN elcsúsztatná a határt.
    """
    return (ns(idx) // 1_000_000_000).astype(np.int64)
