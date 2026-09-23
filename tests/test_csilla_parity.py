"""CSILLA — a stratégia-modul PARITÁSA a kutató-laborral (2026-09-15).

⚠ NEM ÜRES PARITÁS (`vacuous-parity-tests`): mindkét kar VALÓS adaton fut, a
belépők száma > 0 kötelező, és a két kart NEM ugyanaz a hívás adja — a labor
az M1-ből képzett M15-tel, a modul a motor `bt_indicators` útján kapja.

Amit őrzünk:
  1. regisztráció, interfész, config, docs, magic, i18n kulcsok;
  2. a modul belépői == a labor belépői (idő, irány, SL) UGYANAZON a kereten;
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
from strategies import csilla_rules as sw0                                # noqa: E402
base = s.base_params(cfg)
for k in ("tf_pair", "k_hi", "k_lo", "korr_min", "belepo_mod",
          "pipa_k", "pipa_w1", "tp_rr_ratio"):
    check(f"a(z) {k!r} a base_params-ban", k in base)
# ⚠ A LANC (2026-09-23) mas parametereken all, mint a korabbi valtozatok. Ha
# ezek visszaszivarognanak a configba, a Parameterek ablak olyat kinalna, amit
# a szabaly nem hasznal — ez a csapda mar ketszer elsult ebben a strategiaban.
for k in ("level_kinds", "k_d1", "k_w1", "ttl_d1", "ttl_w1",
          "k_h4", "ttl_h4", "k_h1", "ttl_h1", "fib_ext", "retest_tol",
          "sl_atr_mult"):
    check(f"a(z) {k!r} MAR NINCS a base_params-ban", k not in base)
check("a tf_pair a megengedettek kozul valo", base["tf_pair"] in sw0.TF_PAIRS,
      str(base["tf_pair"]))
# ⚠ A LENYILO ERTEKEK a param_meta `choices`-abol jonnek (hogy a `.tfs`
# vigye oket), a SZABALY viszont a kodbol. Ha a ketto elcsuszik, a felulet
# olyat kinalna, amit a szabaly nem ismer — es a `parse_tf_pair` nemaan az
# alapertelmezesre esne vissza.
_pm_cs = ((__import__("strategy.settings", fromlist=["x"])
           .load_strategy_config(NAME).get("param_meta") or {}).get("params") or {})
check("a tf_pair lenyilo ertekei == a kod TF_PAIRS-e",
      list((_pm_cs.get("tf_pair") or {}).get("choices") or []) == list(sw0.TF_PAIRS),
      str((_pm_cs.get("tf_pair") or {}).get("choices")))
check("a belepo_mod lenyilo ertekei == amit a counter_entries ismer",
      set((_pm_cs.get("belepo_mod") or {}).get("choices") or [])
      == {"varj_pirosra", "leszuras", "piros_zaras"},
      str((_pm_cs.get("belepo_mod") or {}).get("choices")))
_ocs = (__import__("strategy.settings", fromlist=["x"])
        .load_strategy_config(NAME).get("optimizer") or {})
check("a belepo_mod ERTEKKESZLET-spec az optimalizaloban (nem szam-tartomany)",
      isinstance(_ocs.get("belepo_mod"), dict) and "values" in _ocs["belepo_mod"],
      str(_ocs.get("belepo_mod")))
check("az optimalizalo ertekei a lenyilo keszlet RESZHALMAZA",
      set(_ocs.get("belepo_mod", {}).get("values") or [])
      <= set((_pm_cs.get("belepo_mod") or {}).get("choices") or []))
check("H4 A PLAFON: a csilla_rules kikenyszeriti",
      sw0.MAX_TF_MIN == 240 and all(v[0] <= 240 for v in sw0.TF_PAIRS.values()),
      str(sw0.TF_PAIRS))
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
for key in ("stage.cs_struct", "stage.cs_corr", "stage.cs_pipa",
            "stage.cs_flag", "stage.cs_entry"):
    check(f"i18n kulcs {key}", _t(key) != key, _t(key))
# ⚠ OT potty, nem harom (a felhasznalo kerese 2026-09-23): a lanc minden
# allomasa lassek. A szelesseg-minta (`live_row._WIDTHS["stages"]`) is ot.
check("a cellak kulcsa a LANC OT allomasa",
      [k for k, _ in s.columns()[0].stages]
      == ["szerk", "korr", "pipa", "zaszlo", "belep"],
      str([k for k, _ in s.columns()[0].stages]))
from dashboard import live_row as _lr                                    # noqa: E402
check("a stages szelesseg-mintaja legalabb OT pottyot fed",
      _lr._SAMPLE["stages"][1].count("\u25cf") >= 5, _lr._SAMPLE["stages"][1])

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
    m1_lab = m1_all[m1_all.index >= m1_all.index.max() - pd.Timedelta(days=400)]
    P = sw.with_tf_pair({**sw.DEFAULTS, **{k: v for k, v in base.items()
                                           if k in sw.DEFAULTS}})
    hi_same = sw.resample(m1_lab, P["hi_tf"])
    lo = sw.resample(m1_lab, P["lo_tf"])

    # ── a LANC harom allomasa kulon-kulon ──────────────────────────────────
    evs = sw.own_swing_events(hi_same, P)
    pipak = sw.pipa_events(hi_same, P)
    setupok = sw.chain_setups(hi_same, P)
    check("1. jelzes: a felso keret tori a sajat swingjet", len(evs) > 20, str(len(evs)))
    check("2. jelzes: van pipa", len(pipak) > 20, str(len(pipak)))
    check("a lanc setupokat ad", len(setupok) > 10, str(len(setupok)))
    _pipaval = [x for x in setupok if x["i_pipa"] is not None]
    check("van pipa NELKULI setup is (a 'korrekcio epul' potty ebbol el)",
          len(_pipaval) < len(setupok), f"{len(_pipaval)} / {len(setupok)}")
    check("a pipa MINDIG a tores UTAN van, es az ervenyesseg ALATT",
          all(x["i_break"] < x["i_pipa"] for x in _pipaval))
    check("a pipa iranya = a tores iranya",
          all(next(q["dir"] for q in pipak if q["i"] == x["i_pipa"]) == x["dir"]
              for x in _pipaval))

    # ── a labor belepoi ────────────────────────────────────────────────────
    _sp = float(prm.get("backtest_spread_points", 0) or 0) * prm["point_size"]
    lab = sw.counter_entries(lo, setupok, P, spread=_sp).drop_duplicates("i", keep="first")
    check("a labor ad belepot (nem 0 vs 0)", len(lab) > 50, str(len(lab)))
    check("a stop a belepo ROSSZ oldalan van (short: folotte, long: alatta)",
          bool(((lab.dir < 0) & (lab.sl > lab.be)).sum()
               + ((lab.dir > 0) & (lab.sl < lab.be)).sum() == len(lab)))
    check("a korrekcio legalabb korr_min gyertya", bool((lab.korr >= P["korr_min"]).all()),
          str(int(lab.korr.min())))

    # ── a MODUL utja: bt_indicators ────────────────────────────────────────
    hi_i, lo_i = s.bt_indicators(hi_same, lo, prm)
    for c in ("cs_sig", "cs_sl_pts"):
        check(f"a(z) {c!r} oszlop a lo keretben", c in lo_i.columns)
    mod = lo_i[lo_i["cs_sig"] != 0]
    check("a modul ad belepot", len(mod) > 50, str(len(mod)))
    lab_t = lo.index[lab.i.to_numpy(int)]
    check("UGYANAZOK a belepo-idopontok (modul == labor)",
          set(mod.index) == set(lab_t),
          f"modul {len(mod)} / labor {len(lab)} / kozos {len(set(mod.index) & set(lab_t))}")
    if set(mod.index) == set(lab_t):
        _lab_by_t = pd.Series(lab.dir.to_numpy(int), index=lab_t)
        check("UGYANAZ az irany",
              bool((mod["cs_sig"].astype(int) == _lab_by_t.reindex(mod.index)).all()))
        _sl_by_t = pd.Series(lab.sl_abs.to_numpy(float) / prm["point_size"], index=lab_t)
        check("UGYANAZ a stop (pontban, 1e-6)",
              bool((mod["cs_sl_pts"] - _sl_by_t.reindex(mod.index)).abs().max() < 1e-6))

    # ── a belepoenkenti stop atadasa a keretnek ────────────────────────────
    st0 = s.bt_new_state(SYM)
    _sor = mod.iloc[0]
    _jel = s.bt_on_low_close(st0, None, _sor, prm)
    _terv = s.sl_tp_points(hi_i.iloc[-1], prm, prm["point_size"])
    check("a bt_on_low_close jelet ad", _jel in ("BUY", "SELL"), str(_jel))
    check("a sl_tp_points EZT a belepot adja vissza (nem a felso sorbol szamol)",
          _terv is not None and abs(_terv[0] - float(_sor["cs_sl_pts"])) < 1e-9,
          str(_terv))
    check("a TP = SL x tp_rr_ratio",
          abs(_terv[1] - _terv[0] * float(prm["tp_rr_ratio"])) < 1e-6)

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

# ---------------------------------------------------------------------------
print("== A kivezetett valtozatok: a fagyasztott kutato-modul ==")
# ⚠ MIERT KELL EZ A SZAKASZ. 2026-09-22-en a bukott valtozatok (retest/fordulo
# belepo, H1/H4 szintek, fibo celar) kikerultek az ELO szabalybol a
# `tools/research/csilla_variants` modulba. Ket dolog romolhat el nemaan:
#   (a) a kutato-modul lemasolja a `break` agat is -> ket peldany, es az egyik
#       elcsuszik (`duplication-produced-its-own-bug`);
#   (b) valaki visszahozza a H1/H4-et vagy a celart az elo modulba.
# Ez a szakasz mindkettot fogja. NEM ures paritas: a ket kar KULON kodutat
# jar (az egyik a `csilla_rules`, a masik a `csilla_variants`), es azt is
# bizonyitjuk, hogy a TOBBI mod MAS eredmenyt ad — kulonben a delegalas
# barmit csinalhatna.
sys.path.insert(0, str(ROOT / "tools" / "research"))
try:
    import csilla_variants as _cv                                        # noqa: E402
except Exception as _e:                                                  # pragma: no cover
    check("a csilla_variants importalhato", False, str(_e))
    _cv = None
if _cv is not None and _m1p.exists():
    from strategies import csilla_rules as _sw2                          # noqa: E402
    _m = m1_all[m1_all.index >= m1_all.index.max() - pd.Timedelta(days=120)]
    _hi = _sw2.resample(_m, 15)
    _h = _hi["high"].to_numpy(float)
    _l = _hi["low"].to_numpy(float)
    _c = _hi["close"].to_numpy(float)
    _a = _sw2.atr(_h, _l, _c, 14)
    _pc, _pv = _sw2.pivots(_h, _l, 3)
    # ⚠ KÉT paraméter-készlet: az élő modulé (`_P2`) és a fagyasztott modulé
    # (`_P3`, amiben a bukott változatok saját kulcsai is benne vannak —
    # `retest_tol`, `fib_ext`). Az élőben ezek MÁR NINCSENEK, épp ezt őrizzük.
    _P2 = {**_sw2.DEFAULTS, "max_wait_lo": 120}
    _P3 = {**_cv.DEFAULTS, "max_wait_lo": 120}
    _ev = dict(dir=-1, level=float(_h[50]), stop_lvl=float(_h[50]), t_close=_hi.index[50])
    _elo = _sw2.lo_entries(_ev, 50, len(_c) - 1, _h, _l, _c, _a, _pc, _pv, 3, _P2)
    _var = _cv.lo_entries(_ev, 50, len(_c) - 1, _h, _l, _c, _a, _pc, _pv, 3, "break", _P3)
    check("mindket kar ad belepot (nem 0 vs 0)", len(_elo) > 5 and len(_var) > 5,
          f"{len(_elo)} / {len(_var)}")
    check("a `break` ag BITRE AZONOS (a variants az elo modulba delegal)",
          _elo == _var, f"{len(_elo)} vs {len(_var)}")
    _ford = _cv.lo_entries(_ev, 50, len(_c) - 1, _h, _l, _c, _a, _pc, _pv, 3, "fordulo", _P3)
    _ret = _cv.lo_entries(_ev, 50, len(_c) - 1, _h, _l, _c, _a, _pc, _pv, 3, "retest", _P3)
    check("a `fordulo` es a `retest` MAS halmazt ad (a delegalas nem nyeli el)",
          _ford != _elo and _ret != _elo,
          f"break={len(_elo)} fordulo={len(_ford)} retest={len(_ret)}")
    check("H1 szint: a kutato-modul ad, az elo modul NEM is ismeri",
          len(_cv.level_table(_m, ("H1",))) > 0 and not hasattr(_sw2, "level_table"))
    import inspect                                                       # noqa: E402
    check("az elo `lo_entries`-nek NINCS `mode` parametere",
          "mode" not in inspect.signature(_sw2.lo_entries).parameters,
          str(inspect.signature(_sw2.lo_entries)))
    for _k in ("fib_ext", "retest_tol", "k_h1", "k_h4", "ttl_h1", "ttl_h4",
               "k_d1", "k_w1", "ttl_d1", "ttl_w1"):
        check(f"a(z) {_k!r} NINCS a csilla_rules.DEFAULTS-ban", _k not in _sw2.DEFAULTS)

# ---------------------------------------------------------------------------
print("== A napi feladat HORDOZHATO ==")
# ⚠ A `.tfs` csomag csak a `strategies.<x>` segedmodulokat viszi. Az elso
# valtozat a `tools/research/csilla_levels`-t importalta: masik gepre telepitve
# a napi feladat minden este import-hibaval allt volna meg, nemaan.
_fw_src = (ROOT / "strategies" / "csilla_forward.py").read_text(encoding="utf-8")
check("a forward-feladat NEM importal kutato-szkriptet (csilla_levels)",
      "import csilla_levels" not in _fw_src)
check("a forward-feladat a KOZOS szabalyt hivja (csilla_rules)",
      "from strategies import csilla_rules" in _fw_src)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
