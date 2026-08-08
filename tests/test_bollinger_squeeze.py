"""
Bollinger Squeeze & Breakout — a stratégia BEKÖTÉSE a vázba.

⚠ A modul elso valtozata egy KITALALT interfeszre irodott (`EntryPlan`,
`compute(md)`, `bt_entry(md, i, params)`, `md.bars` mint DataFrame) — a 8
kotelezo metodusbol 6 hianyzott, es a `Strategy` be sem tudta tolteni. Az ok: a
`new-strategy` skill csak a metodusNEVEKET sorolta fel, alairasok es adatformak
nelkul, ES egy elavult nevet is tartalmazott (`sl_tp_pips` — a v1.67.0-s
pip→pont migracio ota `sl_tp_points`). A skill azota javitva.

Ez a teszt azt orzi, hogy a modul a VALODI interfeszen all, es a jel-lanc
vegigmegy a motoron.
"""

import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

import pandas as pd                                     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "bollinger_squeeze_breakout"
_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


# ---------------------------------------------------------------------------
print("== Regisztracio es interfesz ==")
from strategy import (registered_strategy_names, get_strategy_by_name)   # noqa: E402
from strategy.base import Strategy                                       # noqa: E402

check("auto-felderites megtalalja", NAME in registered_strategy_names(),
      str(registered_strategy_names()))
s = get_strategy_by_name(NAME)
check("betoltodik", s is not None)
check("a Strategy leszarmazottja", isinstance(s, Strategy))
check("NINCS absztrakt metodus hianyban", not getattr(type(s), "__abstractmethods__", None),
      str(sorted(getattr(type(s), "__abstractmethods__", set()))))

# A regi vazlat maradvanyai NE legyenek benne
_src = (ROOT / "strategy" / "bollinger_squeeze.py").read_text(encoding="utf-8")
check("nem hivatkozik a nem letezo EntryPlan-re", "EntryPlan" not in _src)
check("nem hasznalja a nem letezo sl_tp_pips-et", "sl_tp_pips" not in _src)

# ---------------------------------------------------------------------------
print("== Konfiguracio ==")
raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
from strategy.settings import config_for_strategy                        # noqa: E402
cfg = config_for_strategy(raw, NAME)

cfg_file = ROOT / "strategy" / "config" / f"{NAME}.json"
check("van strategia-config fajl", cfg_file.exists(), str(cfg_file.name))
base = s.base_params(cfg)
for k in ("bb_period", "bw_percentile", "ema_fast", "sl_atr_mult", "tp_rr"):
    check(f"a(z) {k!r} a base_params-ban", k in base)
check("az atr_period NEM a strategia configjabol jon",
      "atr_period" not in json.loads(cfg_file.read_text(encoding="utf-8"))["indicators"],
      "az a kozos execution config-e")

check("EGYEDI magic (nem utkozik a tobbivel)",
      len({get_strategy_by_name(n).magic(cfg)
           for n in registered_strategy_names()}) == len(registered_strategy_names()),
      str({n: get_strategy_by_name(n).magic(cfg) for n in registered_strategy_names()}))

check("a kenyszerek szurnek: ema_fast < ema_slow",
      s.constraints_ok({**base, "ema_fast": 50, "ema_slow": 200})
      and not s.constraints_ok({**base, "ema_fast": 300, "ema_slow": 50}))
check("...es a %B kuszobok sorrendje",
      not s.constraints_ok({**base, "pb_long_threshold": 0.0,
                            "pb_short_threshold": 1.0}))

# ⚠ Az IRANY-VETO a KAPUKE. Merve (5 par, hangolatlan): az EMA-szuro felezi a
# kotesszamot ugy, hogy a talalati aranyt NEM javitja (27,1% vele / 28,7% nelkule),
# az Egyutt-kapu viszont mindket esetben javit. Ezert az alap KI — ha valaki
# visszaallitja `true`-ra, ez a teszt szol.
check("a trend-szuro alapbol KI (az irany-veto a kapuke)",
      base.get("require_trend_alignment") is False,
      str(base.get("require_trend_alignment")))
check("...de a parameter MEGMARAD (kutatasra allithato)",
      "require_trend_alignment" in base)
# ── A JEL IDOSIKJA ────────────────────────────────────────────────────────
# A tananyag (Obsidian) szerint M15-on a squeeze "nem er ra feltoltodni", ezert
# ott sok a hamis kitores. Merve (7 par, HAROM kulon 6 honapos idoszak,
# hangolatlan parameterekkel): M15 mindharomban VESZTESEG (-133/-691/-487$,
# 23-29% talalat), M60 mindharomban NYERESEG (+1709/+1438/+1737$, 52-58%).
# Ezert az alap 60 perc — ha valaki 15-re allitja, ez a teszt szol.
from strategy import bollinger_squeeze as _bsq                          # noqa: E402
check("a jel idosikja PARAMETER (nem beegetve)", "signal_tf_min" in base)
check("az alapertelmezes 60 perc (a meres szerint)",
      int(base["signal_tf_min"]) == 60, str(base.get("signal_tf_min")))
check("a modul alapja is 60", _bsq.DEFAULT_TF_MIN == 60)
check("csak ertelmes idosikok engedettek",
      set(_bsq.ALLOWED_TF_MIN) == {15, 30, 60, 120, 240}, str(_bsq.ALLOWED_TF_MIN))

# ⚠ A warmup a LETOLTOTT M15-ben ertendo, az indikatorok viszont a JEL-idosikon
# elnek: a gyertyaszamot fel kell szorozni. Enelkul H1-en negyszer kevesebb adat
# jutna, a leghosszabb ablak vegig NaN maradna, es a strategia NEMAN hallgatna.
_w15 = s.warmup_bars({**base, "signal_tf_min": 15}, "M15")
_w60 = s.warmup_bars({**base, "signal_tf_min": 60}, "M15")
check("a warmup az idosikkal aranyosan no", _w60 == _w15 * 4, f"{_w15} -> {_w60}")
check("a jel-warmup is skalazodik",
      s.signal_warmup_bars({**base, "signal_tf_min": 60}, "M15")
      > s.signal_warmup_bars({**base, "signal_tf_min": 15}, "M15"))

check("van leirasa (docs/<nev>.md)", s.doc_path().exists(), s.doc_path().name)
check("a leiras nem ures", len((s.doc_text() or "").strip()) > 200)

# ---------------------------------------------------------------------------
print("== Indikatorok es jel igazi adaton ==")
from core.execution_params import load_execution_params                  # noqa: E402
SYM = "Ger40"
_ok_data = (ROOT / "data" / "m15" / f"{SYM}.parquet").exists()
if not _ok_data:
    print("  (kihagyva: nincs adat)")
else:
    prm = {**(load_execution_params(SYM, cfg) or {}), **base}
    m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{SYM}.parquet").iloc[-8000:]
    m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{SYM}.parquet").iloc[-20000:]
    ind, lo = s.bt_indicators(m15, m1, prm)

    for c in ("bb_ub", "bb_lb", "bb_bw", "bb_pb", "kc_ub", "kc_lb",
              "squeeze", "squeeze_off", "atr"):
        check(f"a(z) {c!r} oszlop megvan", c in ind.columns)
    check("az M1 frame VALTOZATLAN (nincs ra szukseg)", lo is m1)

    sq = float(ind["squeeze"].mean())
    check("a squeeze ERTELMES aranyban all fenn (nem 0%, nem 100%)",
          0.005 < sq < 0.60, f"{100*sq:.1f}%")
    check("van feloldas", int(ind["squeeze_off"].sum()) > 0,
          str(int(ind["squeeze_off"].sum())))

    # ⚠ NINCS LOOK-AHEAD: a jovo levagasa nem valtoztathat a korabbi sorokon
    ind_short = s.bt_indicators(m15.iloc[:-500], m1, prm)[0]
    n = len(ind_short) - 300
    same = bool((ind["squeeze"].to_numpy()[:n] ==
                 ind_short["squeeze"].to_numpy()[:n]).all())
    check("a JOVO levagasa nem valtoztat a multon (nincs look-ahead)", same)

    # A jel-lanc: M15 allapot -> M1 kezbesites
    st = s.bt_new_state(SYM)
    n_sig = {"BUY": 0, "SELL": 0}
    for i in range(len(ind) - 1):
        st = s.bt_on_high_close(st, ind.iloc[i], prm)
        sig = s.bt_on_low_close(st, None, None, prm)
        if sig in n_sig:
            n_sig[sig] += 1
    total = sum(n_sig.values())
    print(f"     jelek: {n_sig}  (ossz {total})")
    check("szuletik jel", total > 0, str(n_sig))
    check("MINDKET irany elofordul", n_sig["BUY"] > 0 and n_sig["SELL"] > 0)
    check("a jel nem tulzottan surun szol (nem minden gyertyan)",
          total < len(ind) * 0.05, f"{100*total/len(ind):.2f}% a gyertyaknak")

    # EGY jel EGY feloldasi ablakbol (a kitores tobbi gyertyaja ne tuzeljen ujra)
    check("kevesebb jel, mint feloldas", total <= int(ind["squeeze_off"].sum()),
          f"{total} jel / {int(ind['squeeze_off'].sum())} feloldas")

    # A trend-szuro BEKAPCSOLVA tenyleg kevesebb jelet ad (nem holt kapcsolo)
    st2 = s.bt_new_state(SYM)
    prm2 = {**prm, "require_trend_alignment": True}
    n2 = 0
    for i in range(len(ind) - 1):
        st2 = s.bt_on_high_close(st2, ind.iloc[i], prm2)
        if s.bt_on_low_close(st2, None, None, prm2) in ("BUY", "SELL"):
            n2 += 1
    print(f"     trend-szuroval: {n2} jel  (nelkule {total})")
    check("a trend-szuro BEKAPCSOLVA kevesebb jelet ad", n2 < total, f"{n2} < {total}")

    # SL/TP PONTBAN
    row = ind.iloc[-2]
    pt = cfg["pairs"][SYM]["point_size"]
    plan = s.sl_tp_points(row, prm, pt)
    check("sl_tp_points ad tervet", plan is not None)
    if plan:
        sl, tp = plan
        check("az SL POZITIV, PONTBAN", sl > 0 and math.isfinite(sl), f"{sl:.0f}")
        check("a TP = SL x tp_rr", abs(tp - sl * prm["tp_rr"]) < 1e-6)
        check("a merete ertelmes (nem 0, nem abszurd)", 10 < sl < 1e6, f"{sl:.0f}")
    check("ATR nelkul NINCS terv (nem talal ki meretet)",
          s.sl_tp_points({"atr": float("nan")}, prm, pt) is None)
    check("bt_entry ugyanazt adja, ha a vol-szuro ki van kapcsolva",
          s.bt_entry(row, {**prm, "atr_min_pct": 0, "atr_max_pct": 0}, pt) == plan)

    # ── A MOTORON is vegigmegy ────────────────────────────────────────────
    from trading.backtest import run_pair                                # noqa: E402
    r = run_pair(SYM, m15, m1, prm, cfg["pairs"][SYM], cfg["trading"], 1000.0,
                 strategy=s, cfg=cfg)
    summ = r.summary(1000.0) or {}
    print(f"     backtest: n={summ.get('trades', 0)} "
          f"WR={100*summ.get('win_rate', 0):.1f}% P&L={summ.get('total_pnl', 0):+.0f}$")
    check("a backtest-motor lefuttatja", summ.get("trades", 0) > 0,
          str(summ.get("trades")))
    check("a kotesek mindket iranyban", len({t.direction for t in r.trades}) == 2)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
