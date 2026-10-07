"""István stratégiája — TREND_CORRECTION_BREAK (2026-10-07).

Obsidian: „Stratégiák/István féle stratégia". H1 trend -> M15 megerősítés ->
M5 ellenirányú korrekció trendvonala -> lezárt M5 gyertyás törés -> M1
megerősítés -> belépés, SL a korrekció széle mögött, TP = 2R, nincs BE /
trailing / részleges zárás, instrumentumonként 1 pozíció.

ELŐRE RÖGZÍTVE (futtatás előtt, a felhasználó döntéseivel 2026-10-07):
  * Szerkezet: pivot k=3 minden idősíkon (swing_mtf.structure): +1 = HH+HL,
    -1 = LH+LL, 0 = vegyes. A felső idősík állapota csak LEZÁRT gyertyából.
  * Trend: H1 állapot == M15 állapot == irány (0 -> nincs kötés).
  * M5 korrekció (LONG): az utolsó két igazolt M5 pivot-csúcs CSÖKKENŐ (P2 < P1)
    -> trendvonal P1-P2-n át, előre vetítve. SHORT tükör (két emelkedő völgy).
  * Törés: az első M5 ZÁRÓÁR a vonal fölött (long) a P2 igazolása után; egy
    vonal (P1,P2 pár) legfeljebb egy setup.
  * M1 megerősítés: a törő M5 zárása után 15 percen belül az első lezárt M1,
    amelyik az előző M1 csúcsa fölött zár (short: mélypontja alatt). Belépés
    ennek a zárásán (BUY ask = bid + spread, SELL bid). Ha előtte az ár eléri
    az SL-t, a setup elvész.
  * SL: long a korrekció legalacsonyabb bid-mélye (P1-től a törésig); short a
    korrekció legmagasabb bid-csúcsa + a belépéskori spread. Nincs min/max
    stop-szűrő (a jegyzet nem ad) — a stop/ATR csak diagnosztika.
  * TP = 2R. A „min RR >= 2" fix 2R-nél mindig igaz -> nem szűr.
  * Kilépés: CSAK SL/TP, M1-en; ha egy M1-en mindkettő -> SL (konzervatív).
    Swap: minden átlépett fal-óra éjfél 1 éj, csütörtökre virradó 3x, mai ráta.
  * Kockázat 0,25%: USD-nézet = 10 000-es számla, kötésenként fix 25 (R x 25).
  * Kontroll: TÜKÖR (ugyanaz a belépő, ellenirány, ugyanakkora stop / 2R).
  * ÍTÉLET (README-protokoll): t >= 2 (napra klaszterezve), az évek >= 60%-a
    pozitív, >= 3 instrumentum pozitív — nettó, swappal.
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
from swing_mtf import structure, htf_at, pivots
from istvan_ind import gann_state, nonlag
from core import bar_sanity

SYMS = ["GOLD", "UsaTec", "Ger40", "EURUSD", "Usa500"]
K = 3
M1_WINDOW = 15      # perc a törés után
TP_R = 2.0
USD_PER_R = 25.0    # 10 000 x 0,25%


def _exit(side, entry, sl, tp, i0, mh, ml, msp, mday):
    """Első M1 (i0-tól), ahol SL vagy TP teljesül. -> (exit_px, idx, kind)."""
    n = len(mh)
    step = 2000
    j = i0
    while j < n:
        e = min(n, j + step)
        if side == 1:
            hs = ml[j:e] <= sl
            ht = mh[j:e] >= tp
        else:
            hs = mh[j:e] + msp[j:e] >= sl
            ht = ml[j:e] + msp[j:e] <= tp
        any_ = hs | ht
        if any_.any():
            k = int(np.argmax(any_))
            if hs[k]:
                return sl, j + k, "SL"
            return tp, j + k, "TP"
        j = e
        step = min(step * 2, 200_000)
    return np.nan, n - 1, "OPEN"


TRENDS = ("swing", "gann", "nonlag", "both")
VERSIONS = ("v1_tline", "v2_ema", "v3_ema_wpr")
EMA_N, EMA_SHIFT = 13, 5
WPR_N, WPR_LOOK = 14, 12


def _trend_states(df, k=K):
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    g = gann_state(h, l, c, 10)
    nl = nonlag(c, 40, 4, 1.0)[1]
    return dict(swing=structure(df, k)[0], gann=g, nonlag=nl,
                both=np.where(g == nl, g, 0).astype(np.int8))


def prep(sym, k=K):
    m1 = lab.load_m1(sym)
    if m1.index.tz is not None:      # fal-óra "UTC" címkével -> csak a címkét vesszük le
        m1 = m1.tz_localize(None)
    # törött árak ki (a data/ 2026-10-07 óta javítva; ez a régi/más bróker adatára véd)
    m1 = bar_sanity.clean_bars(m1, sym, "M1")
    d5 = lab.resample(m1, 5)
    h15 = lab.resample(m1, 15)
    h60 = lab.resample(m1, 60)
    D = dict(sym=sym, k=k, d5=d5)
    D["h"] = h = d5["high"].to_numpy(float)
    D["l"] = l = d5["low"].to_numpy(float)
    D["c"] = c = d5["close"].to_numpy(float)
    D["a5"] = lab.atr(h, l, c, 14)
    D["close5"] = close5 = (d5.index + pd.Timedelta(minutes=5)).to_numpy()
    t15, t60 = _trend_states(h15, k), _trend_states(h60, k)
    D["trend"] = {m: (htf_at(close5, h60, 60, [t60[m]])[0], htf_at(close5, h15, 15, [t15[m]])[0])
                  for m in TRENDS}
    D["ih"], D["il"] = pivots(h, l, k)
    D["mt"] = m1.index.to_numpy()
    D["mh"] = m1["high"].to_numpy(float); D["ml"] = m1["low"].to_numpy(float)
    D["mc"] = m1["close"].to_numpy(float)
    msp = m1["avg_spread"].to_numpy(float)
    D["msp"] = np.where(np.isfinite(msp), msp, np.nanmedian(msp))
    D["mday"] = m1.index.normalize().to_numpy()
    return D


def signals_tline(D):
    """V1: M5 korrekciós trendvonal első záró-törése -> (i, side, sl_ext, line)."""
    h, l, c, ih, il, k = D["h"], D["l"], D["c"], D["ih"], D["il"], D["k"]
    ph, pl, used = [], [], {1: None, -1: None}
    ev = []
    for i in range(k, len(c)):
        p = i - k                      # a pivot k gyertyával később igazolt
        if ih[p]:
            ph.append((p, h[p]))
        if il[p]:
            pl.append((p, l[p]))
        for side in (1, -1):
            piv = ph if side == 1 else pl
            if len(piv) < 2:
                continue
            (i1, p1), (i2, p2) = piv[-2], piv[-1]
            if (side == 1 and not p2 < p1) or (side == -1 and not p2 > p1):
                continue
            if (i1, i2) == used[side] or i - 1 < i2 + k:
                continue
            slope = (p2 - p1) / (i2 - i1)
            line_i = p2 + slope * (i - i2)
            line_prev = p2 + slope * (i - 1 - i2)
            brk = (c[i] > line_i and c[i - 1] <= line_prev) if side == 1 else \
                  (c[i] < line_i and c[i - 1] >= line_prev)
            if not brk:
                continue
            used[side] = (i1, i2)
            ext = l[i1:i + 1].min() if side == 1 else h[i1:i + 1].max()
            ev.append((i, side, ext, line_i))
    return ev


def signals_ema(D, wpr_filter=False):
    """V2: EMA13 x EMA13[i-5] kereszt M5-ön; V3: + WPR(14) az elmúlt 12 gyertyában
    extrém zónában járt (long: < -80, short: > -20). SL: a legutóbbi IGAZOLT M5
    swing a belépő rossz oldalán."""
    h, l, c, ih, il, k = D["h"], D["l"], D["c"], D["ih"], D["il"], D["k"]
    e = pd.Series(c).ewm(span=EMA_N, adjust=False).mean().to_numpy()
    es = np.r_[np.full(EMA_SHIFT, np.nan), e[:-EMA_SHIFT]]
    w = lab.wpr(h, l, c, WPR_N)
    wmin = pd.Series(w).rolling(WPR_LOOK).min().to_numpy()
    wmax = pd.Series(w).rolling(WPR_LOOK).max().to_numpy()
    ev = []
    lows, highs = [], []
    for i in range(k, len(c)):
        p = i - k
        if ih[p]:
            highs.append(h[p])
        if il[p]:
            lows.append(l[p])
        if i < 50:
            continue
        side = 0
        if e[i] > es[i] and e[i - 1] <= es[i - 1]:
            side = 1
        elif e[i] < es[i] and e[i - 1] >= es[i - 1]:
            side = -1
        if side == 0:
            continue
        if wpr_filter and not ((side == 1 and wmin[i] < -80) or (side == -1 and wmax[i] > -20)):
            continue
        ext = np.nan
        for v in reversed(lows if side == 1 else highs):
            if (side == 1 and v < c[i]) or (side == -1 and v > c[i]):
                ext = v
                break
        if np.isnan(ext):
            continue
        ev.append((i, side, ext, e[i]))
    return ev


def execute(D, events, trend_mode):
    sym, d5, a5, close5 = D["sym"], D["d5"], D["a5"], D["close5"]
    s60, s15 = D["trend"][trend_mode]
    mt, mh, ml, mc, msp, mday = D["mt"], D["mh"], D["ml"], D["mc"], D["msp"], D["mday"]
    pc = lab.PAIRS[sym]
    busy_until = np.datetime64("1970-01-01")
    setups, trades = [], []
    for i, side, corr_ext, line_i in events:
            trend_ok = s60[i] == side and s15[i] == side
            rec = dict(sym=sym, time=d5.index[i], side=side, h1=int(s60[i]),
                       m15=int(s15[i]), line=line_i, corr_ext=corr_ext,
                       trend_ok=trend_ok, atr5=a5[i])
            if not trend_ok:
                setups.append(rec | dict(status="trend_nem"))
                continue
            t_close = close5[i]
            if t_close < busy_until:
                setups.append(rec | dict(status="foglalt"))
                continue
            j0 = np.searchsorted(mt, t_close)            # első M1 a törés után
            j1 = np.searchsorted(mt, t_close + np.timedelta64(M1_WINDOW, "m"))
            ent = None
            for j in range(max(j0, 1), min(j1, len(mc))):
                if side == 1 and ml[j] <= corr_ext:
                    break
                if side == -1 and mh[j] + msp[j] >= corr_ext + msp[j]:
                    break
                if (side == 1 and mc[j] > mh[j - 1]) or (side == -1 and mc[j] < ml[j - 1]):
                    ent = j
                    break
            if ent is None:
                setups.append(rec | dict(status="nincs_m1"))
                continue
            sp_e = msp[ent]
            entry = mc[ent] + sp_e if side == 1 else mc[ent]
            sl = corr_ext if side == 1 else corr_ext + sp_e
            risk = (entry - sl) * side
            if not risk > 0:
                setups.append(rec | dict(status="rossz_stop"))
                continue
            setups.append(rec | dict(status="kotes"))
            res = {}
            for mir in (False, True):
                sd = -side if mir else side
                if mir:
                    # tükör: ugyanaz a pillanat, ellenirány, azonos stop-táv
                    e_m = mc[ent] if sd == -1 else mc[ent] + sp_e
                    s_m = e_m - sd * risk
                else:
                    e_m, s_m = entry, sl
                tp = e_m + sd * TP_R * risk
                px, xi, kind = _exit(sd, e_m, s_m, tp, ent + 1, mh, ml, msp, mday)
                if kind == "OPEN":
                    px = mc[-1] + (msp[-1] if sd == -1 else 0.0)
                gross_px = (px - e_m) * sd / risk
                days = pd.date_range(pd.Timestamp(mday[ent]), pd.Timestamp(mday[xi]), freq="D")[1:]
                nights = sum(3 if dd.dayofweek == 3 else 1 for dd in days)
                swp = pc.get("swap_long_per_lot" if sd == 1 else "swap_short_per_lot") or 0.0
                risk_money = risk / pc["point_size"] * pc["pv1_point"]
                swap_r = swp * nights / risk_money
                res[mir] = dict(R=gross_px + swap_r, R_px=gross_px, swap=swap_r,
                                kind=kind, exit_time=mt[xi], nights=nights)
            busy_until = res[False]["exit_time"]
            o = res[False]
            trades.append(dict(
                sym=sym, time=pd.Timestamp(mt[ent]), break_time=d5.index[i] + pd.Timedelta(minutes=5),
                side=side, h1=int(s60[i]), m15=int(s15[i]), line=line_i,
                entry=entry, sl=sl, tp=entry + side * TP_R * risk, risk=risk,
                stop_atr=risk / a5[i] if a5[i] > 0 else np.nan,
                cost=sp_e / risk, R=o["R"], R_px=o["R_px"], swap=o["swap"],
                kind=o["kind"], exit_time=pd.Timestamp(o["exit_time"]), nights=o["nights"],
                R_mir=res[True]["R"], R_mir_px=res[True]["R_px"]))
    return pd.DataFrame(trades), pd.DataFrame(setups)


def tstat(x, days):
    """Napra klaszterezett t: a napi összegek átlaga / se."""
    s = pd.Series(np.asarray(x)).groupby(np.asarray(days)).sum()
    if len(s) < 3:
        return np.nan
    m = len(x) / len(s)
    return float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))) if s.std() > 0 else np.nan


def report(tr: pd.DataFrame, st: pd.DataFrame) -> str:
    out = []
    tr = tr[tr["kind"] != "OPEN"].copy()
    tr["year"] = tr["time"].dt.year
    tr["day"] = tr["time"].dt.normalize()

    def row(g, name):
        return dict(csoport=name, n=len(g), win=(g["kind"] == "TP").mean(),
                    R=g["R"].mean(), R_px=g["R_px"].mean(), swap=g["swap"].mean(),
                    cost=g["cost"].median(), mir=g["R_mir"].mean(),
                    t=tstat(g["R"], g["day"]), USD=g["R"].sum() * USD_PER_R)

    rows = [row(tr, "ÖSSZES")]
    rows += [row(g, s) for s, g in tr.groupby("sym")]
    rows += [row(g, "long" if s == 1 else "short") for s, g in tr.groupby("side")]
    out.append(pd.DataFrame(rows).round(3).to_string(index=False))
    yr = tr.groupby("year").agg(n=("R", "size"), R=("R", "mean"), USD=("R", lambda x: x.sum() * USD_PER_R))
    out.append("\nÉvenként:\n" + yr.round(3).to_string())
    py = tr.pivot_table(index="year", columns="sym", values="R", aggfunc="mean")
    out.append("\nÉv x instrumentum (R/kötés):\n" + py.round(3).to_string())
    tr["stop_q"] = pd.qcut(tr["stop_atr"], 5, labels=False, duplicates="drop")
    sq = tr.groupby("stop_q").agg(stop_atr=("stop_atr", "median"), cost=("cost", "median"),
                                  n=("R", "size"), R=("R", "mean"), R_px=("R_px", "mean"))
    out.append("\nStop/ATR5 ötödök (diagnosztika):\n" + sq.round(3).to_string())
    out.append("\nSetup-tölcsér:\n" + st.groupby(["sym", "status"]).size().unstack(fill_value=0).to_string())
    a = rows[0]
    pos_y = (yr["R"] > 0).mean()
    pos_s = sum(r["R"] > 0 for r in rows[1:1 + tr["sym"].nunique()])
    out.append(f"\nPROTOKOLL: t={a['t']:.2f} (>=2: {'✓' if a['t'] >= 2 else '✗'}) | "
               f"pozitív év {pos_y:.0%} (>=60%: {'✓' if pos_y >= .6 else '✗'}) | "
               f"pozitív instr. {pos_s} (>=3: {'✓' if pos_s >= 3 else '✗'})")
    return "\n".join(out)


if __name__ == "__main__":
    T, S = [], []
    for s in SYMS:
        D = prep(s)
        ev = {"v1_tline": signals_tline(D), "v2_ema": signals_ema(D),
              "v3_ema_wpr": signals_ema(D, wpr_filter=True)}
        for v in VERSIONS:
            for tm in TRENDS:
                t, st = execute(D, ev[v], tm)
                t["version"] = v; t["trend"] = tm
                st["version"] = v; st["trend"] = tm
                T.append(t); S.append(st)
        print(s, {v: len(x) for v, x in ev.items()}, flush=True)
    tr = pd.concat(T, ignore_index=True)
    st = pd.concat(S, ignore_index=True)
    tr.to_parquet(ROOT / "data" / "istvan_tcb_trades.parquet")
    st.to_parquet(ROOT / "data" / "istvan_tcb_setups.parquet")
    summ, full = [], []
    for (v, tm), g in tr.groupby(["version", "trend"]):
        g2 = g[g["kind"] != "OPEN"]
        yr = g2.groupby(g2["time"].dt.year)["R"].mean()
        ps = g2.groupby("sym")["R"].mean()
        summ.append(dict(verzio=v, trend=tm, n=len(g2), win=(g2["kind"] == "TP").mean(),
                         R=g2["R"].mean(), R_px=g2["R_px"].mean(), cost=g2["cost"].median(),
                         tukor=g2["R_mir"].mean(),
                         t=tstat(g2["R"], g2["time"].dt.normalize()),
                         poz_ev=f"{(yr > 0).sum()}/{len(yr)}", poz_instr=f"{(ps > 0).sum()}/{len(ps)}",
                         USD=g2["R"].sum() * USD_PER_R))
        full.append(f"\n===== {v} | trend={tm} =====\n" +
                    report(g, st[(st.version == v) & (st.trend == tm)]))
    txt = pd.DataFrame(summ).round(3).to_string(index=False)
    print(txt)
    (ROOT / "data" / "istvan_tcb_report.txt").write_text(txt + "\n" + "\n".join(full), encoding="utf-8")
