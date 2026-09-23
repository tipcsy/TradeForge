"""CSILLA — A LEZÁRT VÁLTOZATOK (fagyasztott kutató-modul, 2026-09-22).

Ez a modul azt a kódot őrzi, ami a Csilla körül MÉRVE ÉS BUKOTT. Nem a
program része: a stratégia (`strategies/csilla.py`) és a `.tfs` csomag NEM
látja, és nem is hívja. A célja, hogy a lezárt kérdések ÚJRAFUTTATHATÓK
maradjanak — a jegyzetben álló számok mögött legyen kód —, miközben a
szállított stratégia csak azt viszi, ami fut.

MIT ŐRIZ, ÉS MIÉRT BUKOTT (a vault „Csilla beszállója — mérés" jegyzete):

  belépő-mód `retest`   a törés utáni első visszaérés a tört szintre
                        — az első 14 éves mérés 4 változatának egyike, mind
                        negatív (összesítve −0,217 R/kötés, 0/14 év).
  belépő-mód `fordulo`  a zászló csúcsa utáni első igazolt ellenoldali
                        M1-swing (2026-09-22, a felhasználó kérésére)
                        — −0,435 R/kötés, 6% találat, n = 212 000.
  H1 / H4 szintek       a „páros olvasat": a felső idősík SAJÁT csúcsát töri
                        — H1→M15 −0,049 R, H1→M1 −0,167 R, 0/14 év.
  fibo célár            a tört szinttől `fib_ext` × a láb hossza (a jegyzet
                        138,2%-a) — célár NÉLKÜL minden változat jobb volt
                        (−0,013 vs −0,068 R), és 14 éven egyetlen csomag sem
                        ért el 10–20 R-t.
  D1/W1 SZINT-RÉTEG     igazolt napi/heti swing-szintek élettartammal, amiket
                        az M15 tör — ez NEM a módszer volt, hanem az én
                        bevezetésem (2026-09-14). A felhasználó 2026-09-22-én
                        kimondta: Csilla EGY idősík-párt választ, és a felső a
                        SAJÁT csúcsát töri; a napi/heti chart csak egy opció
                        volt, amit nem kér — H4 a plafon, ez daytrade.
                        A backtestje amúgy is −0,068 R volt.
                        Az élő szabály helyette: `csilla_rules.own_swing_events`.

⚠ A `break` BELÉPŐT NEM MÁSOLJA LE: azt a `strategies.csilla_rules`-ból hívja.
Egy másodszor leírt élő szabály némán elcsúszik az elsőtől — a projekt ezt
háromszor tanulta meg (`duplication-produced-its-own-bug`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strategies import csilla_rules as sw          # noqa: E402

# ⚠ A SZINT-RÉTEG PARAMÉTEREI. Ezek 2026-09-22-én KIESTEK az élő
# `csilla_rules.DEFAULTS`-ból: a szabály azóta a felső idősík saját swingjét
# töri, és a szint-réteghez semmi köze. Az `sw.DEFAULTS`-ból csak a közös
# részek jönnek (k_hi/k_lo/max_wait/buffer_atr/min_sl_atr/stop_atr).
DEFAULTS = dict(sw.DEFAULTS, hi_tf=15, k_d1=2, k_w1=1, ttl_d1=90, ttl_w1=365,
                k_h4=3, ttl_h4=30, k_h1=3, ttl_h1=10,
                retest_tol=0.1, fib_ext=1.382)
KINDS = ("H1", "H4", "D1", "W1")


def parse_kinds(spec) -> tuple:
    """`"D1+W1"` / `"H4+D1"` / `("D1","W1")` → rendezett tuple a KINDS-ból."""
    if isinstance(spec, str):
        parts = [x.strip().upper() for x in spec.replace(",", "+").split("+")]
    else:
        parts = [str(x).strip().upper() for x in (spec or ())]
    return tuple(k for k in KINDS if k in parts) or ("D1", "W1")


def resample_week(df: pd.DataFrame) -> pd.DataFrame:
    o = df.resample("W", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"))
    return o.dropna(subset=["close"])


def _levels_of(d, k, bar_len, ttl, kind):
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    pc, pv = sw.pivots(h, l, k)
    out = []
    for j in np.flatnonzero(pc | pv):
        if j + k >= len(d):
            continue
        t_conf = d.index[j + k] + bar_len       # a k-adik követő gyertya ZÁRÁSA
        if pc[j]:
            out.append(dict(kind=kind, side=1, price=h[j], t_conf=t_conf,
                            t_exp=t_conf + ttl, j=j))
        if pv[j]:
            out.append(dict(kind=kind, side=-1, price=l[j], t_conf=t_conf,
                            t_exp=t_conf + ttl, j=j))
    return out


def level_table(m1: pd.DataFrame, kinds=("D1", "W1"), P: dict | None = None) -> pd.DataFrame:
    """[{kind, side(+1 ellenállás/−1 támasz), price, t_conf, t_exp, j}] —
    igazolt H1/H4/D1/W1 fraktál-swingek élettartammal."""
    P = {**DEFAULTS, **(P or {})}
    rows = []
    if "H1" in kinds:
        rows += _levels_of(sw.resample(m1, 60), P["k_h1"], pd.Timedelta(hours=1),
                           pd.Timedelta(days=P["ttl_h1"]), "H1")
    if "H4" in kinds:
        rows += _levels_of(sw.resample(m1, 240), P["k_h4"], pd.Timedelta(hours=4),
                           pd.Timedelta(days=P["ttl_h4"]), "H4")
    if "D1" in kinds:
        rows += _levels_of(sw.resample(m1, 1440), P["k_d1"], pd.Timedelta(days=1),
                           pd.Timedelta(days=P["ttl_d1"]), "D1")
    if "W1" in kinds:
        rows += _levels_of(resample_week(m1), P["k_w1"], pd.Timedelta(days=7),
                           pd.Timedelta(days=P["ttl_w1"]), "W1")
    if not rows:
        return pd.DataFrame(columns=["kind", "side", "price", "t_conf", "t_exp", "j"])
    return pd.DataFrame(rows).sort_values("t_conf").reset_index(drop=True)


def d1_trend_series(m1: pd.DataFrame, P: dict | None = None) -> pd.Series:
    """A D1-trend (+1/−1/0) a nap ZÁRÁSÁTÓL érvényes, k_d1-gyel igazolt
    swingekből — a szint-réteg címkéjéhez."""
    P = {**DEFAULTS, **(P or {})}
    d1 = sw.resample(m1, 1440)
    h = d1["high"].to_numpy(float)
    l = d1["low"].to_numpy(float)
    k = P["k_d1"]
    pc, pv = sw.pivots(h, l, k)
    tr = np.zeros(len(d1), dtype=int)
    sh, sl = [], []
    for i in range(k, len(d1)):
        j = i - k
        if pc[j]:
            sh.append(h[j])
        if pv[j]:
            sl.append(l[j])
        if len(sh) >= 2 and len(sl) >= 2:
            hh, hl = sh[-1] > sh[-2], sl[-1] > sl[-2]
            tr[i] = 1 if (hh and hl) else (-1 if (not hh and not hl) else 0)
    return pd.Series(tr, index=d1.index + pd.Timedelta(days=1))


# ── a `leg` (a fibo célárhoz) ───────────────────────────────────────────────
def hi_events(hi: pd.DataFrame, lv: pd.DataFrame, trend: pd.Series,
              d1_opp: pd.DataFrame, P: dict | None = None) -> list[dict]:
    """M15 zárás egy élő SZINTEN túl (a lezárt szint-réteg eseménye). Minden
    szint egyszer. `leg` a tört szint és a D1 ellenoldali utolsó igazolt
    swingje közti táv (a fibo célárhoz), `stop_lvl` a törés előtti utolsó
    igazolt ellenoldali M15-swing."""
    P = {**DEFAULTS, **(P or {})}
    c = hi.index
    close = hi["close"].to_numpy(float)
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    k = P["k_hi"]
    pc, pv = sw.pivots(h, l, k)
    sw_h: list[tuple[int, float]] = []
    sw_l: list[tuple[int, float]] = []
    t_open = c.to_numpy()
    t_close = (c + pd.Timedelta(minutes=P["hi_tf"])).to_numpy()
    lv_conf = lv["t_conf"].to_numpy()
    lv_exp = lv["t_exp"].to_numpy()
    lv_price = lv["price"].to_numpy(float)
    lv_side = lv["side"].to_numpy(int)
    lv_kind = lv["kind"].to_numpy()
    alive = np.zeros(len(lv), dtype=bool)
    broken = np.zeros(len(lv), dtype=bool)
    nxt = 0
    tr_t = trend.index.to_numpy()
    tr_v = trend.to_numpy()
    opp_t = d1_opp["t_conf"].to_numpy()
    opp_p = d1_opp["price"].to_numpy(float)
    opp_s = d1_opp["side"].to_numpy(int)
    out = []
    for i in range(k, len(hi)):
        j = i - k
        if pc[j]:
            sw_h.append((j, h[j]))
        if pv[j]:
            sw_l.append((j, l[j]))
        while nxt < len(lv) and lv_conf[nxt] <= t_open[i]:
            alive[nxt] = True
            nxt += 1
        cand = np.flatnonzero(alive & ~broken)
        if len(cand) == 0:
            continue
        cand = cand[lv_exp[cand] > t_open[i]]
        if len(cand) == 0:
            continue
        up = cand[(lv_side[cand] == 1) & (close[i] > lv_price[cand])]
        dn = cand[(lv_side[cand] == -1) & (close[i] < lv_price[cand])]
        ti = np.searchsorted(tr_t, t_open[i], side="right") - 1
        trend_now = int(tr_v[ti]) if ti >= 0 else 0
        for grp, d in ((up, 1), (dn, -1)):
            if len(grp) == 0:
                continue
            broken[grp] = True
            g = grp[np.argmin(np.abs(lv_price[grp] - close[i]))]
            lvl = float(lv_price[g])
            m = (opp_t <= t_open[i]) & (opp_s == -d)
            leg = abs(lvl - float(opp_p[m][-1])) if m.any() else 0.0
            if d > 0:
                stop_lvl = sw_l[-1][1] if sw_l else np.nan
            else:
                stop_lvl = sw_h[-1][1] if sw_h else np.nan
            lab_ = ("folyt" if trend_now == d else
                    "ford" if trend_now == -d else "nincs")
            out.append(dict(i=i, dir=d, level=lvl, leg=leg, kind=str(lv_kind[g]),
                            stop_lvl=stop_lvl, label=lab_, t_close=t_close[i]))
    return out


# ── a bukott belépő-módok ───────────────────────────────────────────────────
def lo_entries(ev: dict, start: int, end: int, h, l, c, atr1, pc, pv, k,
               mode: str, P: dict) -> list[dict]:
    """`mode`:
      `break`   — az ÉLŐ szabály (`csilla_rules.lo_entries`), ide csak átadjuk;
      `retest`  — a törés után az első visszaérés a tört szintre;
      `fordulo` — a zászló csúcsa utáni első IGAZOLT ellenoldali M1-swing
                  (long: völgy); belépő az igazolás gyertyáján (pivot + k),
                  stop a forduló-swing mögött. `b` = −1, mert nincs törés.
    """
    if mode == "break":
        return sw.lo_entries(ev, start, end, h, l, c, atr1, pc, pv, k, P)
    d = ev["dir"]
    out = []
    i = start
    while i <= end:
        piv = -1
        while i <= end:
            j = i - k
            if j >= start and ((d > 0 and pc[j]) or (d < 0 and pv[j])):
                piv = j
                break
            i += 1
        if piv < 0:
            break
        lvl = h[piv] if d > 0 else l[piv]
        if mode == "fordulo":
            ent = fj = -1
            for t in range(i, end + 1):
                j = t - k                      # ez a bar MOST igazolódik swingnek
                if j > piv and ((d > 0 and pv[j]) or (d < 0 and pc[j])):
                    ent, fj = t, j
                    break
            if ent < 0:
                break
            a = atr1[ent]
            if np.isfinite(a) and a > 0:
                if d > 0:
                    sl_abs = c[ent] - (l[fj] - P["buffer_atr"] * a)
                else:
                    sl_abs = (h[fj] + P["buffer_atr"] * a) - c[ent]
                sl_abs = max(sl_abs, P["min_sl_atr"] * a)
                out.append(dict(i=ent, sl_abs=sl_abs, level=lvl, piv=piv, b=-1))
            i = ent + 1
            continue
        b = -1
        for t in range(i, end + 1):
            if (d > 0 and c[t] > lvl) or (d < 0 and c[t] < lvl):
                b = t
                break
        if b < 0:
            break
        ent = -1
        for t in range(b + 1, min(end, b + P["max_wait_lo"]) + 1):
            a = atr1[t]
            if not np.isfinite(a):
                continue
            if d > 0 and l[t] <= lvl + P["retest_tol"] * a and c[t] > lvl:
                ent = t
                break
            if d < 0 and h[t] >= lvl - P["retest_tol"] * a and c[t] < lvl:
                ent = t
                break
        if ent >= 0 and np.isfinite(atr1[ent]) and atr1[ent] > 0:
            a = atr1[ent]
            if d > 0:
                szel = min(l[piv:ent + 1])
                sl_abs = c[ent] - (szel - P["buffer_atr"] * a)
            else:
                szel = max(h[piv:ent + 1])
                sl_abs = (szel + P["buffer_atr"] * a) - c[ent]
            sl_abs = max(sl_abs, P["min_sl_atr"] * a)
            out.append(dict(i=ent, sl_abs=sl_abs, level=lvl, piv=piv, b=b))
            i = ent + 1
        else:
            i = b + 1
    return out


# ── a teljes (régi) szabály: mód + fibo célár ───────────────────────────────
def hi_context(hi: pd.DataFrame, P: dict | None = None, kinds=("D1", "W1")) -> dict:
    """Mint a `csilla_rules.hi_context`, de H1/H4 szintekkel és `leg`-gel."""
    P = {**DEFAULTS, **(P or {})}
    lv = level_table(hi, kinds, P)
    a15 = sw.atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
                 hi["close"].to_numpy(float), 14)
    if not len(lv):
        return dict(lv=lv, evs=[], a15=a15, P=P, kinds=tuple(kinds))
    trend = d1_trend_series(hi, P)
    d1_opp = lv[lv.kind == "D1"] if "D1" in kinds else level_table(hi, ("D1",), P)
    return dict(lv=lv, evs=hi_events(hi, lv, trend, d1_opp, P), a15=a15, P=P,
                kinds=tuple(kinds))


def entries_from(ctx: dict, m1: pd.DataFrame, mode: str = "break",
                 stop_atr: float | None = None) -> pd.DataFrame:
    """A régi belépő-tábla: `tp_abs` (fibo célár) oszloppal és `mode`-dal."""
    P = ctx["P"]
    evs, a15 = ctx["evs"], ctx["a15"]
    if not evs or not len(m1):
        return pd.DataFrame()
    if stop_atr is None:
        stop_atr = P.get("stop_atr")
    h, l, c = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
    atr1 = sw.atr(h, l, c, 14)
    atr1 = np.where(atr1 > 0, atr1, np.nan)
    pc, pv = sw.pivots(h, l, P["k_lo"])
    start = np.searchsorted(m1.index.to_numpy(), [e["t_close"] for e in evs], side="left")
    max_wait_lo = P["max_wait"] * P["hi_tf"]
    PP = {**P, "max_wait_lo": max_wait_lo}
    rows = []
    n = len(c)
    t0 = m1.index[0]
    for e, s in zip(evs, start):
        if s >= n or e["t_close"] < t0:
            continue
        a = a15[e["i"]]
        if not (np.isfinite(a) and a > 0) or not np.isfinite(e["stop_lvl"]):
            continue
        end = min(n - 1, int(s) + max_wait_lo)
        for x in lo_entries(e, int(s), end, h, l, c, atr1, pc, pv, P["k_lo"], mode, PP):
            i = x["i"]
            d = e["dir"]
            sl_abs = (c[i] - (e["stop_lvl"] - P["buffer_atr"] * a)) if d > 0 \
                else ((e["stop_lvl"] + P["buffer_atr"] * a) - c[i])
            sl_abs = max(sl_abs, P["min_sl_atr"] * a)
            if stop_atr:
                sl_abs = float(stop_atr) * a
            cel = e["level"] + d * P["fib_ext"] * e["leg"]
            rows.append(dict(i=i, dir=d, sl_abs=sl_abs, tp_abs=d * (cel - c[i]),
                             atr15=a, kind=e["kind"], label=e["label"],
                             piv=x["piv"], b=x["b"], level=x["level"], ev_i=e["i"]))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def entry_table(m1: pd.DataFrame, P: dict | None = None, kinds=("D1", "W1"),
                mode: str = "break", stop_atr: float | None = None,
                hi: pd.DataFrame | None = None) -> pd.DataFrame:
    P = {**DEFAULTS, **(P or {})}
    if hi is None:
        hi = sw.resample(m1, P["hi_tf"])
    return entries_from(hi_context(hi, P, kinds), m1, mode, stop_atr)

# ── a VÁLTOZATLAN függvények: az élő modulból, átnevezés nélkül ─────────────
# ⚠ Ez a modul a régi (takarítás előtti) `csilla_rules` API-t kínálja, hogy a
# kutató-szkriptek egyetlen import-csere után változatlanul fussanak. Ami nem
# változott, azt NEM másoljuk — ide csak a NEVE kerül, a kód az élő modulban
# marad. (Az első változat ezeket kihagyta, és a `csilla_viz` a
# `d1_trend_series`-en hasalt el — futás közben, nem importáláskor.)
resample = sw.resample
atr = sw.atr
pivots = sw.pivots
