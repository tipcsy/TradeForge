"""CSILLA — a stratégia-modul PARITÁSA a kutató-laborral (2026-09-15).

⚠ NEM ÜRES PARITÁS (`vacuous-parity-tests`): mindkét kar VALÓS adaton fut, a
belépők száma > 0 kötelező, és a két kart NEM ugyanaz a hívás adja — a labor
az M1-ből képzett M15-tel, a modul a motor `bt_indicators` útján kapja.

Amit őrzünk:
  1. regisztráció, interfész, config, docs, magic, i18n kulcsok;
  2. a modul belépői == a labor belépői (idő, irány, SL) UGYANAZON az M15-ön;
  3. a natív MT5 M15 kerettel (amit a motor élesben lát) az eltérés kicsi;
  4. a `run_pair` végigfut a forward-teszt kilépésével (breakeven_r 0,67,
     trailing 3 ATR, off preset), és van kötés;
  5. a napszak-szűrő (session_hours) él a motor-úton.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

NAME = "csilla"
_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------
print("== Regisztracio es interfesz ==")
from strategy import (registered_strategy_names, get_strategy_by_name)   # noqa: E402
from strategy.base import Strategy                                       # noqa: E402

check("auto-felderites megtalalja", NAME in registered_strategy_names(),
      str(registered_strategy_names()))
s = get_strategy_by_name(NAME)
check("betoltodik", s is not None)
check("a Strategy leszarmazottja", isinstance(s, Strategy))
check("NINCS absztrakt metodus hianyban", not getattr(type(s), "__abstractmethods__", None))

raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
from strategy.settings import config_for_strategy                        # noqa: E402
cfg = config_for_strategy(raw, NAME)
cfg_file = ROOT / "strategies" / "config" / f"{NAME}.json"
check("van strategia-config fajl", cfg_file.exists())
base = s.base_params(cfg)
for k in ("k_d1", "k_w1", "ttl_d1", "ttl_w1", "max_wait", "stop_atr", "tp_rr_ratio"):
    check(f"a(z) {k!r} a base_params-ban", k in base)
# ⚠ A napszak-sav NEM strategia-parameter: a keret strategia-hatokoru
# kereskedesi-ora kapuja (params_store.trade_hours). Az elso valtozat sajat
# `session_hours` parametert vitt — a Parameterek ablakban olvashatatlan
# tuple-kent jelent meg, es duplikalta a keret funkciojat.
check("NINCS session_hours parameter (a napszak a keret ora-kapuja)",
      "session_hours" not in base)
for v in base.values():
    check(f"minden parameter-ertek hashelheto ({type(v).__name__})", hash(v) is not None) if not isinstance(v, (int, float, str, bool, type(None))) else None
check("EGYEDI magic",
      len({get_strategy_by_name(n).magic(cfg) for n in registered_strategy_names()})
      == len(registered_strategy_names()))
check("van leirasa (docs/<nev>.md)", s.doc_path().exists(), s.doc_path().name)
check("a leiras nem ures", len((s.doc_text() or "").strip()) > 200)
from core.i18n import t as _t                                            # noqa: E402
for key in ("stage.cs_level", "stage.cs_break", "stage.cs_entry"):
    check(f"i18n kulcs {key}", _t(key) != key, _t(key))
check("a cellak kulcsa a STADIUM (szint/tores/belep)",
      {k for k, _ in s.columns()[0].stages} == {"szint", "tores", "belep"})

# ---------------------------------------------------------------------------
print("== Paritas a laborral, valos adaton ==")
SYM = "Ger40"
_m1p = ROOT / "data" / "m1" / f"{SYM}.parquet"
_m15p = ROOT / "data" / "m15" / f"{SYM}.parquet"
if not _m1p.exists():
    print("  (kihagyva: nincs adat)")
else:
    from strategies import csilla_rules as sw                                  # noqa: E402
    from core.execution_params import load_execution_params              # noqa: E402
    prm = {**(load_execution_params(SYM, cfg) or {}), **base,
           "symbol": SYM, "point_size": raw["pairs"][SYM]["point_size"]}

    m1_all = pd.read_parquet(_m1p)
    m1_all = m1_all[~m1_all.index.duplicated(keep="last")].sort_index()
    # a labor: a TELJES M1 (a szintek 1 evet neznek vissza) — az utolso ~500 nap
    m1_lab = m1_all[m1_all.index >= m1_all.index.max() - pd.Timedelta(days=800)]
    lab = sw.entry_table(m1_lab, base, stop_atr=float(base["stop_atr"]))
    lab = lab.drop_duplicates("i", keep="first")
    lab_t = m1_lab.index[lab.i.to_numpy(int)]
    check("a labor ad belepot (nem 0 vs 0)", len(lab) > 50, str(len(lab)))

    # a MODUL utja: bt_indicators(df_hi, df_lo) — UGYANAZ az M15 (az M1-bol
    # kepezve), a lo pedig az utolso 60 nap M1-e (mint egy backtest-ablak)
    hi_same = sw.resample(m1_lab, 15)
    lo = m1_lab[m1_lab.index >= m1_lab.index.max() - pd.Timedelta(days=60)]
    hi_i, lo_i = s.bt_indicators(hi_same, lo, prm)
    for c in ("cs_sig", "cs_sl"):
        check(f"a(z) {c!r} oszlop a lo keretben", c in lo_i.columns)
    check("a 'cs_atr_ref' oszlop a hi keretben", "cs_atr_ref" in hi_i.columns)
    mod = lo_i[lo_i["cs_sig"] != 0]
    # az ablak elso 3 orajat kihagyjuk: ott a lo keret ELOTT zart esemenyek
    # belepoi vannak, amiket a modul (helyesen) nem lat
    lab_w = lab[lab_t >= lo.index[0] + pd.Timedelta(hours=3)]
    lab_w_t = m1_lab.index[lab_w.i.to_numpy(int)]
    check("a modul ad belepot az ablakban", len(mod) > 5, str(len(mod)))
    same_t = set(mod.index) == set(lab_w_t)
    check("UGYANAZOK a belepo-idopontok (modul == labor)", same_t,
          f"modul {len(mod)} / labor {len(lab_w)} / kozos {len(set(mod.index) & set(lab_w_t))}")
    if same_t:
        lab_by_t = pd.Series(lab_w.dir.to_numpy(), index=lab_w_t)
        sl_by_t = pd.Series(lab_w.sl_abs.to_numpy(), index=lab_w_t)
        check("UGYANAZ az irany", bool((mod["cs_sig"].astype(int) == lab_by_t.reindex(mod.index)).all()))
        check("UGYANAZ a stop (arban, 1e-9)",
              bool(np.allclose(mod["cs_sl"].to_numpy(), sl_by_t.reindex(mod.index).to_numpy(), atol=1e-9)))
    # az SL a MOTOR utjan: sl_tp_points a hi soron, a belepo idejen
    _bad = 0
    for t_e, r_ in mod.iterrows():
        hrow = hi_i[hi_i.index <= t_e].iloc[-1]
        plan = s.sl_tp_points(hrow, prm, prm["point_size"])
        if plan is None or abs(plan[0] * prm["point_size"] - float(r_["cs_sl"])) > 1e-6:
            _bad += 1
    check("sl_tp_points (a toresi ATR-bol) == a labor stopja minden belepon",
          _bad == 0, f"elteres: {_bad}/{len(mod)}")

    # a NATIV MT5 M15 kerettel (amit a motor elesben lat): kis elteres megengedett
    if _m15p.exists():
        m15n = pd.read_parquet(_m15p)
        m15n = m15n[~m15n.index.duplicated(keep="last")].sort_index()
        m15n = m15n[(m15n.index >= m1_lab.index[0]) & (m15n.index <= hi_same.index[-1])]
        hi_n, lo_n = s.bt_indicators(m15n, lo, prm)
        mod_n = set(lo_n[lo_n["cs_sig"] != 0].index)
        kozos = len(mod_n & set(lab_w_t))
        arany = kozos / max(1, len(lab_w_t))
        check("nativ M15-tel a belepok >= 80%-a egyezik", arany >= 0.8,
              f"{kozos}/{len(lab_w_t)} = {100*arany:.0f}% (modul {len(mod_n)})")

    # ── a strategia MINDEN oraban jelez; az ora-kapu a kerete ──────────
    st = s.bt_new_state(SYM)
    check("a strategia nem szur orara (minden belepo atmegy)",
          all(s.bt_on_low_close(st, None, r_, prm) != "NONE" for _, r_ in mod.iterrows()))

    # ── a MOTORON, a forward-teszt kilepesevel ─────────────────────────
    from trading.backtest import run_pair                                # noqa: E402
    from core import risk_reduction as rrm                               # noqa: E402
    # ⚠ Az rr-spec LAPOS szótár (mint `rr_state.spec_for`): a preset és a
    # kalibráció EGY szinten. Egy beágyazott {"preset","cfg"} alak némán az
    # alapértékeket adná (BE a 30 R-es célár felénél = soha).
    rr = {**rrm.default_config(), "preset": rrm.PRESET_OFF, "breakeven_r": 0.67,
          "trail_activation_atr": 3.0, "trail_distance_atr": 3.0}
    m15_bt = hi_same
    r = run_pair(SYM, m15_bt, lo, prm, raw["pairs"][SYM],
                 raw["trading"], 1000.0, strategy=s, rr=rr, cfg=raw)
    summ = r.summary(1000.0) or {}
    print(f"     backtest (sav nelkul, 60 nap): n={summ.get('trades', 0)} "
          f"WR={100*summ.get('win_rate', 0):.1f}% P&L={summ.get('total_pnl', 0):+.0f}$")
    check("a backtest-motor lefuttatja es kot", summ.get("trades", 0) > 0, str(summ.get("trades")))
    # a BE/trailing TENYLEG hat: a lezart kotesek kozott van BE-n/trailingen zart
    _st = [getattr(t, "status", "") for t in r.trades]
    check("van BE/trailing kilepes (a spec hat, nem az alapertek)",
          any(st not in ("sl", "tp", "open", "") for st in _st) or
          any(bool(getattr(t, "risk_free", False)) for t in r.trades), str(_st))
    # a Csilla-sav a KERET ora-kapujan at (allowed_hours), ahogy a motor is
    r2 = run_pair(SYM, m15_bt, lo, prm, raw["pairs"][SYM], raw["trading"], 1000.0,
                  strategy=s, rr=rr, cfg=raw, allowed_hours={8, 9, 10, 11})
    summ2 = r2.summary(1000.0) or {}
    print(f"     backtest (Csilla-sav 8-11): n={summ2.get('trades', 0)}")
    check("a savval KEVESEBB (vagy egyenlo) kotes", summ2.get("trades", 0) <= summ.get("trades", 0))
    check("a savos kotesek mind 8-11 kozott nyiltak",
          all(8 <= pd.Timestamp(t.open_time).hour <= 11 for t in r2.trades)
          if r2.trades and hasattr(r2.trades[0], "open_time") else True)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
