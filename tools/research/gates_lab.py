"""A rendszer SAJAT kapui, bar-onkent kiszamolva - kutatasi hasznalatra.

Nem ujrairom oket: a `core.regime`, `gates.tf_align`, `gates.spread_gate`,
`gates.momentum`, `gates.cost_gate` fuggvenyeit hivom, ugyanazokkal az
alapertekekkel, mint a motor. Igy amit itt merek, az atvihето elesbe.
"""
from __future__ import annotations

# A repobol futtathato: a projekt gyokere ES a testvermodulok a sys.path-ra.
import sys as _sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import sys
import numpy as np
import pandas as pd
from pathlib import Path


import lab
from core import regime as _regime
from gates import momentum as _mom
from gates import spread_gate as _sg
from gates import cost_gate as _cg

# A kapuk alapertelmezett hatokoret a config adja; itt a DOKUMENTALT alapokat
# hasznaljuk (core/execution_params.DEFAULTS + gates.MARKET_ADVERSE_DEFAULT).
EXEC = {"atr_period": 14, "max_spread_atr_ratio": 0.20, "min_spread_mult": 1.5}
ADVERSE = {"dead", "uncertain"}                    # gates.MARKET_ADVERSE_DEFAULT
ADVERSE_WIDE = {"dead", "uncertain", "ranging"}    # amit nehany par hasznal
VOL_MIN, VOL_MAX = 0.60, 2.00                      # atr / atr_baseline savja


_BUILT = {}


def build(sym: str, tf: int = 15) -> dict:
    """M15 vaz + minden kapu allapota bar-onkent (KAUZALIS: csak zart gyertya).

    GYORSITOTARAZVA: a hosszu (tick-bol epitett) mintan egy epites 1-2 perc, es
    a kapu-ablacio + a ket (kapus/kapu nelkuli) valtozat kulonben 36-szor futna
    le ugyanarra a szimbolumra."""
    if (sym, tf) in _BUILT:
        return _BUILT[(sym, tf)]
    out = _build(sym, tf)
    _BUILT[(sym, tf)] = out
    return out


def _build(sym: str, tf: int = 15) -> dict:
    m1 = lab.load_m1(sym)
    d = lab.resample(m1, tf)
    ps = lab.PAIRS[sym]["point_size"]
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    atr = lab.atr(h, l, c, 14)
    atr = np.where(atr > 0, atr, np.nan)
    sp_pts = d["close_spread"].to_numpy(float) / ps
    _av = d["avg_spread"].to_numpy(float) / ps
    sp_pts = np.where(np.isfinite(sp_pts) & (sp_pts > 0), sp_pts, _av)

    G = {}

    # ── 1. PIAC (regime osztalyozo) ────────────────────────────────────────
    cat = _regime.classify(d[["high", "low", "close"]]).to_numpy()
    G["piac"] = ~np.isin(cat, list(ADVERSE))
    G["piac_szigoru"] = ~np.isin(cat, list(ADVERSE_WIDE))
    G["_cat"] = cat

    # ── 2. SPREAD ──────────────────────────────────────────────────────────
    normal = float(np.nanmedian(sp_pts))
    ok = np.zeros(len(c), bool)
    for i in range(len(c)):
        if np.isfinite(sp_pts[i]) and np.isfinite(atr[i]):
            ok[i] = _sg.spread_ok(sp_pts[i], atr[i], ps, EXEC, normal)[0]
    G["spread"] = ok

    # ── 3. IDOSIK-EGYUTTALLAS (M1/M5/M15 SMA100 elojele) ───────────────────
    sig = {}
    for m in (1, 5, 15):
        dd = m1 if m == 1 else lab.resample(m1, m)
        cc = dd["close"]
        s = np.sign(cc - cc.rolling(100).mean())
        sig[m] = s.reindex(d.index, method="ffill").to_numpy()
    al = sig[1] + sig[5] + sig[15]
    G["_tf_dir"] = np.where(al == 3, 1, np.where(al == -3, -1, 0))
    G["egyuttallas"] = G["_tf_dir"] != 0          # iranyt is ad -> lasd lent

    # ── 4. VOLATILITAS (atr / gordulo alapmerce savja) ─────────────────────
    base = pd.Series(atr).rolling(2000, min_periods=200).mean().bfill().to_numpy()
    ratio = atr / np.where(base > 0, base, np.nan)
    G["volatilitas"] = (ratio >= VOL_MIN) & (ratio <= VOL_MAX)

    # ── 5. LENDULET (alapjarat-szuro) ──────────────────────────────────────
    p = dict(_mom.DEFAULTS)
    rpm = np.full(len(c), np.nan)
    win = max(p["sma_slow"], p["vol_window"]) + 2
    for i in range(win, len(c)):
        rpm[i] = _mom.rpm_sma(c[i - win + 1:i + 1].tolist(), p)
    G["_rpm"] = rpm
    G["lendulet"] = np.abs(rpm) >= p["idle_threshold"]

    # ── 6. SZEP CHART (a tananyag SCS-e) ───────────────────────────────────
    import exp_struct as XS
    F, _a, _c = XS.structure_features(d)
    G["_scs"] = F["SCS_ok"]
    G["_pos"] = F["pos_robust"]
    G["szep_chart"] = F["SCS_ok"] >= 0.7

    return dict(d=d, c=c, h=h, l=l, atr=atr, sp_pts=sp_pts, ps=ps,
                gates=G, sym=sym, tf=tf,
                is_m=np.asarray(d.index <= pd.Timestamp("2025-10-31", tz="UTC")))


def cost_gate_mask(C, sl_pts, tp_pts, cap=0.35):
    """A KOLTSEG kapu csak a belepo-terv ismereteben dol el."""
    out = np.zeros(len(C["c"]), bool)
    for i in range(len(C["c"])):
        if np.isfinite(sl_pts[i]) and sl_pts[i] > 0:
            out[i] = not _cg.failed(sl_pts[i], tp_pts[i], C["sp_pts"][i], cap)
    return out
