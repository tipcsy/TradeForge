"""
A TANITO CIMKE es a BACKTEST ugyanazt mondja ugyanarra a gyertyara.

Ha ez elcsuszik, a modell ELERHETETLEN kimenetre tanul: olyan kotesekre kap
jutalmat, amiket a vegrehajtas soha nem tud leszallitani. 2026-08-08-an pontosan
ez tortent EURCHF-en:

    a cimke szerint  55,2% nyert    a backtest szerint 17,8%
    egyetertes 59,2%  |  az elteresek 41%-a mind a 21:45-22:30 savbol

Az ok: a cimke a BELEPO bar spreadjet fagyasztotta ra az egesz utra. A 23h-s
rollover (EURCHF-en 103 pont spread a 15-16 pontos median helyett) a short
stopjat kiuti a bid elmozdulasa NELKUL is — a backtest ezt latja, a cimke nem.
Es mivel a modell ido-jellemzot is kapott, pont ezt az orat tanulta meg "jonak".

A javitas utan az egyetertes 85,1%. A maradek ~15% szerkezeti: a cimke M15
high/low-t lat, a backtest M1 sorrendet — azonos baron belul mas lehet, melyik
szint utott elobb. A teszt ezert nem 100%-ot var, hanem KUSZOBOT, es azt allitja,
hogy a ket TALALATI ARANY kozel van.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

import numpy as np                                       # noqa: E402
import pandas as pd                                      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


# ---------------------------------------------------------------------------
print("== A cimke szerkezete (szintetikus, pontosan ellenorizheto) ==")
from strategy import ml_train as mt                      # noqa: E402

n = 60
idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
# Sik piac, majd egy LEFELE mozgas: a short TP-nek utnie kell... ha nincs spread
close = np.full(n, 100.0)
close[10:] = 100.0
df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                   "close": close, "atr14": np.full(n, 1.0)}, index=idx)
df.loc[df.index[5:12], "low"] = 96.0          # eleg mely a short TP-hez

p = {"dynamic_sltp": True, "sl_atr_mult": 1.0, "tp_rr_ratio": 2.0}

# spread nelkul: a short nyer
lab0 = mt.label_outcomes(df.copy(), p, point_size=1.0, lookahead=20, spread_points=0.0)
check("spread nelkul a short cimke tuzel", int(lab0["label_short"].iloc[0]) == 1)

# ...ugyanaz, de az UTON hatalmas spread: a stopot kiuti, tehat NEM nyer
df_sp = df.copy()
df_sp["avg_spread"] = 0.05
df_sp.loc[df_sp.index[1:4], "avg_spread"] = 3.0     # rollover-szeru kiugras
lab1 = mt.label_outcomes(df_sp, p, point_size=1.0, lookahead=20, spread_points=0.0)
check("az UTON kiugro spread kiuti a short stopjat",
      int(lab1["label_short"].iloc[0]) == 0,
      "a belepo bar spreadje kicsi, a 2. bare nagy")

# A BELEPO bar spreadje a LONG-ot dragitja (ask-on nyit)
df_e = df.copy()
df_e["avg_spread"] = 0.02
df_e.loc[df_e.index[0], "avg_spread"] = 2.0
df_e.loc[df_e.index[1:12], "high"] = 102.5          # long TP eppen elerheto lenne
lab2 = mt.label_outcomes(df_e, p, point_size=1.0, lookahead=20, spread_points=0.0)
lab2b = mt.label_outcomes(df.assign(avg_spread=0.02), p, point_size=1.0,
                          lookahead=20, spread_points=0.0)
check("a belepo bar spreadje a LONG belepot rontja",
      int(lab2["label_long"].iloc[0]) == 0, "2.0 spread a nyitobaron")

check("avg_spread nelkul a fix spread lep eletbe",
      mt.label_outcomes(df.copy(), p, 1.0, 20, spread_points=5.0)["label_short"].iloc[0] == 0)

# ---------------------------------------------------------------------------
print("== Eles paritas: cimke vs backtest UGYANAZOKON a koteseken ==")
SYM = "EURCHF"        # ezen a paron a legrosszabb a rollover-torzitas
_ok_data = ((ROOT / "data" / "m1" / f"{SYM}.parquet").exists()
            and (ROOT / "data" / "optimized_params" / "ml_ai" / f"{SYM}.json").exists())
if not _ok_data:
    print("  (kihagyva: nincs adat)")
else:
    from strategy import get_strategy_by_name, ml_features as mlf   # noqa: E402
    from strategy.settings import config_for_strategy               # noqa: E402
    from core.execution_params import load_execution_params         # noqa: E402
    from trading.backtest import run_pair                           # noqa: E402

    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = config_for_strategy(raw, "ml_ai")
    strat = get_strategy_by_name("ml_ai")
    pc = cfg["pairs"][SYM]
    pip = float(pc["point_size"])
    prm = json.loads((ROOT / "data" / "optimized_params" / "ml_ai" /
                      f"{SYM}.json").read_text(encoding="utf-8")).get("params") or {}
    prm = {**(load_execution_params(SYM, cfg) or {}), **prm}

    m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{SYM}.parquet")
    m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{SYM}.parquet")
    r = run_pair(SYM, m15, m1, prm, pc, cfg["trading"], 1000.0, strategy=strat,
                 test_start="2026-01-01", test_end="2026-08-07", cfg=cfg)
    tr = [t for t in r.trades if t.close_time is not None]

    if len(tr) < 20:
        print(f"  (kihagyva: csak {len(tr)} kotes — a modell alig tuzel)")
    else:
        f = mlf.build_feature_frame(m15, pip)
        f = mt.label_outcomes(f, prm, pip, 32,
                              float(pc.get("backtest_spread_points", 0) or 0))
        agree = 0
        lab_w = bt_w = 0
        for t in tr:
            prev = f.index[f.index <= t.open_time]
            if not len(prev):
                continue
            lc = "label_long" if t.direction == "BUY" else "label_short"
            lv = int(f.loc[prev[-1], lc])
            bv = 1 if t.status == "tp" else 0
            lab_w += lv
            bt_w += bv
            agree += (lv == bv)
        n_t = len(tr)
        print(f"     cimke {100*lab_w/n_t:.1f}%  |  backtest {100*bt_w/n_t:.1f}%  "
              f"|  egyetertes {100*agree/n_t:.1f}%   (n={n_t})")
        check("az egyetertes legalabb 75%", agree / n_t >= 0.75,
              f"{100*agree/n_t:.1f}%")
        check("a ket talalati arany 12 szazalekponton belul",
              abs(lab_w - bt_w) / n_t <= 0.12,
              f"{100*abs(lab_w-bt_w)/n_t:.1f} szazalekpont")

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
