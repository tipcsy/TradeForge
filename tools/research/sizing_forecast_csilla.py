"""MEGERŐSÍTŐ MÉRÉS: előrejelzett mozgékonyság szerinti méretezés a `csilla`
belépőin — előregisztrált (2026-09-16, a vault „Előrejelzett mozgékonyság
szerinti méretezés" jegyzet megerősítő szakasza).

KÖTÉS-HALMAZ: `csilla_rules.entry_table` (D1+W1, M15-törés, M1-zászló), fix
1,5 ATR15 stop, MINDEN óra, 5 tick-instrumentum, a labor rögzített
kilépésével (BE 0,67 R, 2 R csúszó, 5 nap, spread + swap), egyszerre egy
pozíció páronként. Az első két év kimarad (nincs mintán kívüli előrejelzés).

MÉRETEZŐ: `event_time.forecast_A` log RV_240 a belépéskor, mintán kívül;
fordított KAUZÁLIS rang (≥ 30 előzmény), 0,5–1,5×. Egyetlen kar számít.

ELFOGADÁS (egy szabály): ≥ +0,005 R/kötés az egyenleteshez ≥ 3/5 páron ÉS
az évek ≥ 60 %-ában pozitív az összesített különbség. Nincs második olvasat.

Tájékoztató: múltbeli ATR15-arány, 0,25–1,75× sáv, RV_60.

Futtatás:
    python tools/research/sizing_forecast_csilla.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import lab
import event_time as ET
from strategies import csilla_rules as sw
from sizing_forecast import _weights, _wmean

SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40"]
STOP_ATR, BE_AT_R, TRAIL_R, MAX_HOLD = 1.5, 0.67, 2.0, 5 * 1440
D_EQ, YEAR_FRAC, INSTR_MIN = 0.005, 0.60, 3


def trades_for(sym: str) -> pd.DataFrame:
    m1 = lab.load_m1(sym)
    ps = float(lab.PAIRS[sym]["point_size"])
    et = sw.entry_table(m1, stop_atr=STOP_ATR).drop_duplicates("i", keep="first")
    idx = et.i.to_numpy(int)
    tr = lab.simulate(m1, idx, et.dir.to_numpy(int), et.sl_abs.to_numpy(float) / ps,
                      np.zeros(len(et)), point_size=ps, max_hold=MAX_HOLD,
                      be_at_r=BE_AT_R, trail_r=TRAIL_R, one_at_a_time=True,
                      pair_cfg=lab.PAIRS[sym])
    a15 = et.set_index("i").atr15
    # múltbeli ATR15-arány: az ATR15 / a megelőző 200 nap mediánja (tájékoztató)
    hi = sw.resample(m1, 15)
    atr15 = pd.Series(sw.atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                             hi["close"].to_numpy(float), 14), index=hi.index)
    med = atr15.rolling(200 * 96, min_periods=2000).median()
    t_open = m1.index[tr["i_open"]]
    j = np.searchsorted(hi.index.to_numpy(), t_open.to_numpy(), side="right") - 1
    ratio = (atr15.to_numpy()[j] / med.to_numpy()[j])
    return pd.DataFrame({"sym": sym, "t": t_open, "R": tr["r"],
                         "t_ms": (t_open.astype("int64") // 10**6).astype(np.int64),
                         "atr_arany": ratio})


def main():
    pd.set_option("display.width", 250)
    parts = []
    for sym in SYMS:
        d = trades_for(sym)
        d["fc_rv240"] = ET.forecast_A(sym, d.t_ms.to_numpy(), 240)
        d["fc_rv60"] = ET.forecast_A(sym, d.t_ms.to_numpy(), 60)
        parts.append(d)
        print(f"   {sym}: {len(d)} kötés, R={d.R.mean():+.4f}, előrejelzéssel {int(np.isfinite(d.fc_rv240).sum())}",
              flush=True)
    df = pd.concat(parts, ignore_index=True).sort_values(["sym", "t"]).reset_index(drop=True)
    d = df[np.isfinite(df.fc_rv240) & np.isfinite(df.fc_rv60)].reset_index(drop=True)
    print(f"\n   összesen {len(d):,} kötés az első két év nélkül, egyenletes R = {d.R.mean():+.4f}")

    rows = []
    for causal in (True, False):
        for lo, hi in ((0.5, 1.5), (0.25, 1.75)):
            per = {}
            for arm in ("fc_rv240", "fc_rv60", "atr_arany"):
                w = np.full(len(d), np.nan)
                for sym in SYMS:
                    m = (d.sym == sym).to_numpy()
                    w[m] = _weights(d.loc[m, arm].to_numpy(float), lo, hi, causal)
                d[f"w_{arm}"] = w
                per[arm] = {sym: _wmean(w[(d.sym == sym).to_numpy()], d.R.to_numpy()[(d.sym == sym).to_numpy()])
                            - d.R[d.sym == sym].mean() for sym in SYMS}
                per[arm]["ÖSSZ"] = _wmean(w, d.R.to_numpy()) - d.R.mean()
            ev = d.groupby(d.t.dt.year).apply(
                lambda z: _wmean(z["w_fc_rv240"].to_numpy(), z.R.to_numpy()) - z.R.mean(),
                include_groups=False)
            tag = f"rang={'kauzális' if causal else 'teljes'}, sáv {lo}–{hi}×"
            print(f"\n── {tag} — súlyozott − egyenletes R/kötés ──")
            print(pd.DataFrame(per).round(4).to_string())
            n_ok = sum(per["fc_rv240"][s] >= D_EQ for s in SYMS)
            rows.append({"változat": tag, "fc240 − egyenl.": per["fc_rv240"]["ÖSSZ"],
                         "párok ≥+0,005": f"{n_ok}/5", "évek poz.": f"{int((ev > 0).sum())}/{len(ev)}",
                         "évek%": (ev > 0).mean(), "atr_arany − egyenl.": per["atr_arany"]["ÖSSZ"]})
            if causal and (lo, hi) == (0.5, 1.5):
                verdict = (n_ok >= INSTR_MIN) and ((ev > 0).mean() >= YEAR_FRAC)
                print("   évenként (fc240 − egyenl.): " + "  ".join(f"{y}:{v:+.3f}" for y, v in ev.items()))
    print("\n════ ÖSSZESÍTVE ════")
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print("\n════ ELFOGADÁS — az EGYETLEN szabály: kauzális rang, 0,5–1,5×, ≥+0,005 ≥3/5 páron ÉS évek ≥60 % ════")
    print("   → " + ("ÁTMENT" if verdict else "BUKOTT"))


if __name__ == "__main__":
    main()
