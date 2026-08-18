"""A jelolt-lista gyorsitotar: mikor szabad UJRAHASZNALNI?

A `build_signal_series` a draga felet (indikatorok + M15/M1 allapotgepek) egyszer
szamolja ki, es egy VEGREHAJTASI sopres (sl_atr_mult x tp_rr ...) tobb futasa
ujrahasznalja. Ez egy ALLITAS: hogy a vegrehajtasi parameterek nem valtoztatjak
meg a tarolt dolgot.

⚠ Az allitas EROSEBB, mint a jelolt-listae: a gyorsitotar az INDIKATOR-TABLAKAT
is tarolja. Egy parameter tehat csak akkor lehet "execution", ha sem az
allapotgepek kimeneteert, sem a `bt_indicators` OSZLOPAIT nem valtoztatja.

Ez nem elmeleti finomsag. Az `atr_baseline_bars` vegrehajtasinak volt minositve,
holott a `bt_indicators` abbol szamolja az `atr_avg` oszlopot -> a sopres nemán
HAMIS eredmenyt adott volna. Ez a teszt azt a besorolast bukta volna el.

A ket hibairany nem egyenrangu:
    folosleges ujraszamolas = lassu
    teves ujrahasznalas     = HAMIS
Ezert az ismeretlen kulcs "signal", es elteresnel a `run_pair` NEM epit csendben
ujra, hanem hibat dob.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core import applog
applog.harden_console()

from strategy import get_strategy_by_name
from strategy.settings import (load_strategy_config, param_class,
                               SIGNAL_PARAM, EXEC_PARAM)
from trading import backtest as bt

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── Szintetikus, de REALISZTIKUS adat (a jelzeshez mozgas kell) ──────────────
rng = np.random.default_rng(20260811)


def _bars(n, freq):
    px = 25000 + np.cumsum(rng.normal(0, 4.0, n))
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": px,
                         "high": px + np.abs(rng.normal(0, 3.0, n)),
                         "low":  px - np.abs(rng.normal(0, 3.0, n)),
                         "close": px, "volume": 1.0}, index=idx)


M15 = _bars(1400, "15min")
M1 = _bars(1400 * 15, "1min")
PAIR_CFG = {"point_size": 0.01, "pv1_point": 1.0, "min_lot": 0.01,
            "lot_step": 0.01, "backtest_spread_points": 1.5,
            "sess_start": 0, "sess_end": 24}
TRADING_CFG = {"max_open_slots": 4, "account_risk_pct": 1.0,
               "risk_percent": 1.0, "daily_loss_limit_percent": 100.0,
               "daily_loss_limit_pct": 100.0}

BASE = {"sma_period": 200, "wpr_m15_period": 21, "wpr_m1_period": 21,
        "wpr_m15_sell_extreme": -20, "wpr_m15_buy_extreme": -80,
        "wpr_m15_sell_trigger": -40, "wpr_m15_buy_trigger": -60,
        "wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
        "wpr_m1_sell_trigger": -50, "wpr_m1_buy_trigger": -50,
        "sl_atr_mult": 2.0, "tp_rr_ratio": 1.0,
        "atr_period": 14, "atr_min_pct": 0.5, "atr_max_pct": 3.0,
        "atr_avg_ref": 10.0, "atr_baseline_bars": 0}

ST = get_strategy_by_name("wpr_sma")


def _series(params, allowed_hours=None):
    return bt.build_signal_series("TEST", M15, M1, params, PAIR_CFG,
                                  strategy=ST, allowed_hours=allowed_hours)


REF = _series(BASE)
check("a generalt adaton szuletik jelolt (a teszt ertelmes)",
      len(REF.signals) > 0, f"{len(REF.signals)} jel")


# ── 1. AZ INVARIANS: vegrehajtasi param nem erinti a TAROLT dolgot ──────────
# Nem csak a jelolt-listat — az INDIKATOR-TABLAKAT sem. Minden stratégia minden
# vegrehajtasi parameterere, generikus perturbacioval.
def _perturb(v):
    if isinstance(v, bool):
        return (not v)
    if isinstance(v, (int, float)):
        return type(v)(v * 2 + 1) if v else type(v)(3)
    return v


def _frames_equal(a, b):
    return a[0].equals(b[0]) and a[1].equals(b[1])


for sname in ("wpr_sma", "bollinger_squeeze_breakout"):
    st = get_strategy_by_name(sname)
    scfg = load_strategy_config(sname)
    meta = ((scfg.get("param_meta") or {}).get("params") or {})
    exec_keys = [k for k in meta if param_class(scfg, k) == EXEC_PARAM]
    check(f"{sname}: van vegrehajtasi parameter (a teszt ertelmes)",
          len(exec_keys) > 0, str(exec_keys))

    # A stratégia sajat alap-parameterei + a mieink (ami hianyzik, defaultol)
    try:
        base = {**BASE, **{k: (meta[k] or {}).get("default", BASE.get(k))
                           for k in meta if (meta[k] or {}).get("default") is not None}}
    except Exception:
        base = dict(BASE)
    base = {k: v for k, v in base.items() if not isinstance(v, (dict, list))}
    base = {**base, "symbol": "TEST", "point_size": 0.01}

    try:
        ref_frames = st.bt_indicators(M15, M1, base)
    except Exception as ex:
        check(f"{sname}: bt_indicators fut az alap-parameterekkel", False, str(ex))
        continue

    bad = []
    for k in exec_keys:
        p = dict(base)
        p[k] = _perturb(base.get(k, (meta[k] or {}).get("default", 1)))
        if p[k] == base.get(k):
            continue                      # nem sikerult elmozditani — kihagyjuk
        try:
            f = st.bt_indicators(M15, M1, p)
        except Exception as ex:
            bad.append(f"{k}: hiba {type(ex).__name__}")
            continue
        if not _frames_equal(ref_frames, f):
            cols = [c for c in ref_frames[0].columns
                    if c in f[0].columns and not ref_frames[0][c].equals(f[0][c])]
            bad.append(f"{k} -> {cols or 'M1/oszlopkeszlet'}")
    check(f"{sname}: EGYETLEN vegrehajtasi param sem valtoztatja az INDIKATOR-tablat",
          not bad, "; ".join(bad))


# ── 2. …es a JELOLT-LISTAT sem (wpr_sma, vegponttol vegpontig) ──────────────
for k, v in (("sl_atr_mult", 4.0), ("tp_rr_ratio", 2.5),
             ("atr_min_pct", 0.0), ("atr_max_pct", 99.0)):
    p = dict(BASE); p[k] = v
    s = _series(p)
    check(f"EXECUTION {k}: a jelolt-lista VALTOZATLAN", s.signals == REF.signals)
    check(f"EXECUTION {k}: a gyorsitotar HASZNALHATO ra", REF.for_params(
        bt._prepare_params("TEST", p, PAIR_CFG)))


# ── 3. JEL-param -> a gyorsitotar NEM hasznalhato (es tenyleg mas is) ───────
for k, v in (("sma_period", 120), ("wpr_m1_buy_trigger", -35), ("wpr_m15_period", 9),
             ("atr_period", 30), ("atr_baseline_bars", 500)):
    p = dict(BASE); p[k] = v
    check(f"SIGNAL {k}: a gyorsitotar NEM hasznalhato",
          not REF.for_params(bt._prepare_params("TEST", p, PAIR_CFG)))

# az atr_baseline_bars kulon: EZ volt a valos felreminosites
_p = dict(BASE); _p["atr_baseline_bars"] = 500
_f_ref = ST.bt_indicators(M15, M1, {**BASE, "symbol": "TEST", "point_size": 0.01})
_f_new = ST.bt_indicators(M15, M1, {**_p, "symbol": "TEST", "point_size": 0.01})
check("atr_baseline_bars TENYLEG megvaltoztatja az indikator-tablat "
      "(ezert jel-osztaly)", not _frames_equal(_f_ref, _f_new))
check("atr_baseline_bars besorolasa = signal",
      param_class(load_strategy_config("wpr_sma"), "atr_baseline_bars") == SIGNAL_PARAM)


# ── 4. Ismeretlen kulcs: a BIZTONSAGOS ag (bekerul a lenyomatba) ────────────
_p = dict(BASE); _p["valami_uj_parameter"] = 7
check("ismeretlen kulcs -> a gyorsitotar NEM hasznalhato (drága, biztonsagos ag)",
      not REF.for_params(bt._prepare_params("TEST", _p, PAIR_CFG)))


# ── 5. Az ora-szuro is a gyorsitotar AZONOSSAGA (no_trade_resets_signal) ────
_ph = {**BASE, "no_trade_resets_signal": True}
_ref_h = _series(_ph, allowed_hours=set(range(8, 18)))
check("mas ora-szuro -> NEM hasznalhato ujra",
      not _ref_h.for_params(bt._prepare_params("TEST", _ph, PAIR_CFG),
                            allowed_hours=set(range(9, 18))))
check("ugyanaz az ora-szuro -> hasznalhato",
      _ref_h.for_params(bt._prepare_params("TEST", _ph, PAIR_CFG),
                        allowed_hours=set(range(8, 18))))


# ── 6. A LENYEG: a gyorsitotarral futtatott run_pair BITAZONOS ─────────────
def _key(res):
    return [(str(t.open_time), t.direction, round(t.open_price, 8),
             round(t.sl, 8), round(t.tp, 8), round(t.pnl_usd, 8),
             t.status, str(t.close_time), round(t.lot, 8)) for t in res.trades]


for label, kw in (("alap", {}),
                  ("kapukkal", {"exec_gates": True, "cfg": {"pairs": {}}}),
                  ("ora-szurovel", {"allowed_hours": set(range(6, 20))})):
    p = dict(BASE)
    ah = kw.get("allowed_hours")
    full = bt.run_pair("TEST", M15, M1, p, PAIR_CFG, TRADING_CFG, 10000.,
                       strategy=ST, **kw)
    ss = _series(p, allowed_hours=ah)
    cached = bt.run_pair("TEST", M15, M1, p, PAIR_CFG, TRADING_CFG, 10000.,
                         strategy=ST, signal_series=ss, **kw)
    check(f"run_pair({label}): a gyorsitotaras futas BITAZONOS",
          _key(full) == _key(cached),
          f"{len(full.trades)} vs {len(cached.trades)} kotes")

# vegrehajtasi param megvaltoztatva — a gyorsitotar ujrahasznalva
for k, v in (("sl_atr_mult", 3.5), ("tp_rr_ratio", 2.0)):
    p = dict(BASE); p[k] = v
    full = bt.run_pair("TEST", M15, M1, p, PAIR_CFG, TRADING_CFG, 10000., strategy=ST)
    cached = bt.run_pair("TEST", M15, M1, p, PAIR_CFG, TRADING_CFG, 10000.,
                         strategy=ST, signal_series=REF)
    check(f"SOPRES {k}={v}: a gyorsitotarazott futas BITAZONOS a teljessel",
          _key(full) == _key(cached), f"{len(full.trades)} vs {len(cached.trades)}")


# ── 6b. AZ IDOSZAK is az azonossag resze ───────────────────────────────────
# ⚠ Gyorsitotarbol a run_pair a TAROLT tablakat hasznalja, tehat a
# test_start/test_end argumentumat figyelmen kivul hagyja. Mas idoszakra epult
# listaval csendben a REGI idoszakot futtatna le — a felhasznalo pedig az ujat
# latna a fejlecen. Ez a legalattomosabb valtozata a "csendes hamis"-nak.
_ref_span = bt.build_signal_series("TEST", M15, M1, BASE, PAIR_CFG, strategy=ST,
                                   test_start="2026-01-05")
check("mas idoszak -> a gyorsitotar NEM hasznalhato",
      not _ref_span.for_params(bt._prepare_params("TEST", BASE, PAIR_CFG),
                               test_start="2026-01-08"))
check("ugyanaz az idoszak -> hasznalhato",
      _ref_span.for_params(bt._prepare_params("TEST", BASE, PAIR_CFG),
                           test_start="2026-01-05"))
try:
    bt.run_pair("TEST", M15, M1, BASE, PAIR_CFG, TRADING_CFG, 10000.,
                strategy=ST, signal_series=_ref_span, test_start="2026-01-08")
    check("mas idoszakra epult lista -> hibat dob", False, "nem dobott hibat")
except ValueError:
    check("mas idoszakra epult lista -> hibat dob", True)


# ── 6c. signal_series_cached: a szabaly EGY helyen el ──────────────────────
# A hivoknak (backtest-ablak, optimalizalo) nem kell tudniuk, mi jel- es mi
# vegrehajtasi parameter — csak ezt hivjak, es megkapjak, hogy ujrahasznalt-e.
_c = None
_seq = [("elso futas", {}, None, False),
        ("csak SL valtozott", {"sl_atr_mult": 3.0}, None, True),
        ("csak TP valtozott", {"sl_atr_mult": 3.0, "tp_rr_ratio": 2.2}, None, True),
        ("ugyanaz megint", {"sl_atr_mult": 3.0, "tp_rr_ratio": 2.2}, None, True),
        ("JEL valtozott", {"sl_atr_mult": 3.0, "sma_period": 120}, None, False),
        ("IDOSZAK valtozott", {"sl_atr_mult": 3.0, "sma_period": 120},
         "2026-01-05", False)]
for _label, _mod, _ts, _want in _seq:
    _c, _reused = bt.signal_series_cached(_c, "TEST", M15, M1, {**BASE, **_mod},
                                          PAIR_CFG, strategy=ST, test_start=_ts)
    check(f"signal_series_cached: {_label} -> "
          f"{'ujrahasznal' if _want else 'ujraszamol'}", _reused == _want)


# ── 7. Elteres eseten HANGOS hiba, nem csendes ujraepites ──────────────────
try:
    bt.run_pair("TEST", M15, M1, {**BASE, "sma_period": 50}, PAIR_CFG,
                TRADING_CFG, 10000., strategy=ST, signal_series=REF)
    check("rossz jelolt-lista -> hibat dob (nem szamol csendben masat)", False,
          "nem dobott hibat")
except ValueError:
    check("rossz jelolt-lista -> hibat dob (nem szamol csendben masat)", True)
except Exception as ex:
    check("rossz jelolt-lista -> ValueError", False, f"{type(ex).__name__}: {ex}")


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
