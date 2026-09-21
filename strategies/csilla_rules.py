"""SWING-SZINTEK ÉS SZERKEZET-TÖRÉS — a „Csilla beszállója" szabály KÖZÖS magja.

Egyetlen hely, ahonnan a kutató-labor (`tools/research/csilla_levels.py`) ÉS a
stratégia-modul (`strategies/csilla.py`) ugyanazt a szabályt hívja.

⚠ MIÉRT A `strategies/`-BEN, ÉS NEM A `core/`-BAN. A `.tfs` csomagoló a
stratégia SAJÁT segédmoduljait viszi magával (amiket `strategies.<x>`-ből
importál, mint az `ml_ai` → `ml_features`), a `core/`-t nem. Egy `core/`-ra
épülő stratégia máshol telepítve importhibával esne szét. Ez a modul tehát a
csilla segédmodulja — a labor is innen importál (a tools/ nem a keret). Ez nem
kényelem, hanem a paritás feltétele: a projekt háromszor tanulta meg, hogy egy
másodszor leírt szabály némán elcsúszik az elsőtől (lásd
`duplication-produced-its-own-bug`, `vacuous-parity-tests`).

⚠ Szándékosan NEM importál se `lab`-ot, se MetaTrader5-öt — csak numpy/pandas.

A SZABÁLY (a mérés előtt rögzítve, 2026-09-14; a vault „Csilla beszállója —
mérés" jegyzet 5. szakasza):

    1. SZINTEK: igazolt D1 fraktál-swing (k_d1 → ennyi nappal később ismert)
       és igazolt W1 fraktál-swing (k_w1). Csúcs = ellenállás, völgy = támasz.
       Egy szint az igazolásától él, amíg egy M15 gyertya át nem zár rajta
       (= esemény), vagy le nem jár (ttl_d1 / ttl_w1 nap). Minden szint egyszer.
    2. ESEMÉNY (M15): zárás egy élő ellenállás FÖLÖTT (+1) / támasz ALATT (−1).
       Címke: a D1-trend a törés előtt → folytatás / fordulat / nincs.
    3. BELÉPŐ (M1): a M15 gyertya zárása utáni `max_wait` M15-gyertyányi M1
       baron belül igazolt M1-swing az irány oldalán (a „zászló"), majd zárás
       azon túl. Egy eseményhez több belépő is tartozhat.
    4. STOP: `stop_atr` × ATR(M15) a törés gyertyáján (a mért, fix változat).

Az M1 az egyetlen bemenet: a M15 / D1 / W1 keretek belőle képződnek
(`resample`), így a labor és a stratégia ugyanazt a gyertyát látja.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULTS = dict(hi_tf=15, k_hi=3, k_lo=3, k_d1=2, k_w1=1, ttl_d1=90, ttl_w1=365,
                # H4 / H1 szintek — a jegyzet ezeket is említi; a MÉRT változat
                # csak D1+W1 (a `level_kinds` alapja). k = fraktál félablak,
                # ttl = élettartam NAPBAN.
                k_h4=3, ttl_h4=30, k_h1=3, ttl_h1=10,
                max_wait=8, buffer_atr=0.2, min_sl_atr=1.0, retest_tol=0.1,
                fib_ext=1.382, stop_atr=1.5)
KINDS = ("H1", "H4", "D1", "W1")          # a `level_kinds` megengedett elemei


def parse_kinds(spec) -> tuple:
    """`"D1+W1"` / `"D1"` / `("D1","W1")` → rendezett tuple a KINDS-ból.
    Ismeretlen elem kimarad; üres → a mért alap (D1+W1)."""
    if isinstance(spec, str):
        parts = [x.strip().upper() for x in spec.replace(",", "+").split("+")]
    else:
        parts = [str(x).strip().upper() for x in (spec or ())]
    out = tuple(k for k in KINDS if k in parts)
    return out or ("D1", "W1")


# ── segédek ──────────────────────────────────────────────────────────────────
def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """M1 → nagyobb TF (zárt gyertyák, a bar címkéje a NYITÓ ideje)."""
    agg = dict(open=("open", "first"), high=("high", "max"),
               low=("low", "min"), close=("close", "last"))
    o = df.resample(f"{minutes}min", label="left", closed="left").agg(**agg)
    return o.dropna(subset=["close"])


def resample_week(df: pd.DataFrame) -> pd.DataFrame:
    o = df.resample("W", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"))
    return o.dropna(subset=["close"])


def atr(h, l, c, n):
    """ATR — a true range EGYSZERŰ mozgóátlaga (mint `lab.atr`)."""
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def pivots(h: np.ndarray, l: np.ndarray, k: int):
    """`(csucs, volgy)` bool tömbök a PIVOT baron. Szigorú: a csúcs magasabb a
    bal és a jobb k bar MINDEGYIKÉNÉL. A pivot csak k barral később ismerhető
    fel — a hívó tolja el."""
    hs, ls = pd.Series(h), pd.Series(l)
    bal_h = hs.rolling(k).max().shift(1).to_numpy()
    jobb_h = hs.rolling(k).max().shift(-k).to_numpy()
    bal_l = ls.rolling(k).min().shift(1).to_numpy()
    jobb_l = ls.rolling(k).min().shift(-k).to_numpy()
    csucs = (h > bal_h) & (h > jobb_h)
    volgy = (l < bal_l) & (l < jobb_l)
    return np.nan_to_num(csucs, nan=False), np.nan_to_num(volgy, nan=False)


# ── a jelentős szintek ───────────────────────────────────────────────────────
def _levels_of(d, k, bar_len, ttl, kind):
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    pc, pv = pivots(h, l, k)
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
    """[{kind, side(+1 ellenállás/−1 támasz), price, t_conf, t_exp, j}]
    A bemenet BÁRMELY OHLC-keret (M1 vagy M15): a D1/W1 belőle képződik, és a
    napi/heti OHLC ugyanaz, akár M1-ből, akár M15-ből jön."""
    P = {**DEFAULTS, **(P or {})}
    rows = []
    if "H1" in kinds:
        rows += _levels_of(resample(m1, 60), P["k_h1"], pd.Timedelta(hours=1),
                           pd.Timedelta(days=P["ttl_h1"]), "H1")
    if "H4" in kinds:
        rows += _levels_of(resample(m1, 240), P["k_h4"], pd.Timedelta(hours=4),
                           pd.Timedelta(days=P["ttl_h4"]), "H4")
    if "D1" in kinds:
        rows += _levels_of(resample(m1, 1440), P["k_d1"], pd.Timedelta(days=1),
                           pd.Timedelta(days=P["ttl_d1"]), "D1")
    if "W1" in kinds:
        rows += _levels_of(resample_week(m1), P["k_w1"], pd.Timedelta(days=7),
                           pd.Timedelta(days=P["ttl_w1"]), "W1")
    if not rows:
        return pd.DataFrame(columns=["kind", "side", "price", "t_conf", "t_exp", "j"])
    return pd.DataFrame(rows).sort_values("t_conf").reset_index(drop=True)


def d1_trend_series(m1: pd.DataFrame, P: dict | None = None) -> pd.Series:
    """A D1-trend (+1/−1/0) a nap ZÁRÁSÁTÓL érvényes, k_d1-gyel igazolt
    swingekből — a címkéhez. A bemenet M1 vagy M15 keret (lásd `level_table`)."""
    P = {**DEFAULTS, **(P or {})}
    d1 = resample(m1, 1440)
    h = d1["high"].to_numpy(float)
    l = d1["low"].to_numpy(float)
    k = P["k_d1"]
    pc, pv = pivots(h, l, k)
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


# ── az M15 események ─────────────────────────────────────────────────────────
def hi_events(hi: pd.DataFrame, lv: pd.DataFrame, trend: pd.Series,
              d1_opp: pd.DataFrame, P: dict | None = None) -> list[dict]:
    """M15 zárás egy élő szinten túl. Minden szint egyszer. A `leg` a tört
    szint és a D1 ellenoldali utolsó igazolt swingje közti táv; `stop_lvl` a
    törés előtti utolsó igazolt ellenoldali M15-swing (a szerkezeti stophoz)."""
    P = {**DEFAULTS, **(P or {})}
    c = hi.index
    close = hi["close"].to_numpy(float)
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    k = P["k_hi"]
    pc, pv = pivots(h, l, k)
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


# ── az M1 belépők egy eseményhez ─────────────────────────────────────────────
def lo_entries(ev: dict, start: int, end: int, h, l, c, atr1, pc, pv, k,
               mode: str, P: dict) -> list[dict]:
    """[{i, sl_abs, level, piv, b}] — a visszahúzódás-belépők az [start, end]
    ablakban. `pc`/`pv` az M1 pivotjai (a pivot baron), `k` a félablak (az
    igazolás késése). `sl_abs`: az M1-alapú (első mérés) stop — a hívó
    felülírhatja.

    `mode`:
      `break`   — az M1 gyertya a zászló csúcsán TÚL zár (a törés gyertyáján);
      `retest`  — a törés után az első visszaérés a tört szintre;
      `fordulo` — a zászló csúcsa utáni első IGAZOLT ellenoldali M1-swing (long:
                  völgy) — a visszahúzódás fordulója; belépő az igazolás
                  gyertyáján (a pivot + k), stop a forduló-swing mögött.
                  (2026-09-22: a felhasználó kérte a `break` mellé, mindkettő
                  mérve; `b` = −1, mert nincs törés.)"""
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
        if mode == "break":
            ent = b
        else:                       # retest
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


# ── A TELJES SZABÁLY: magas-keret kontextus + M1 belépők ────────────────────
def hi_context(hi: pd.DataFrame, P: dict | None = None, kinds=("D1", "W1")) -> dict:
    """A M15 keret KONTEXTUSA: szintek, D1-trend, események, ATR15. Csak akkor
    változik, ha új M15 gyertya zár — a stratégia ezért gyorsítótárazhatja."""
    P = {**DEFAULTS, **(P or {})}
    lv = level_table(hi, kinds, P)
    a15 = atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
              hi["close"].to_numpy(float), 14)
    if not len(lv):
        return dict(lv=lv, evs=[], a15=a15, P=P)
    trend = d1_trend_series(hi, P)
    d1_opp = lv[lv.kind == "D1"] if "D1" in kinds else level_table(hi, ("D1",), P)
    evs = hi_events(hi, lv, trend, d1_opp, P)
    return dict(lv=lv, evs=evs, a15=a15, P=P, kinds=tuple(kinds))


def entries_from(ctx: dict, m1: pd.DataFrame, mode: str = "break",
                 stop_atr: float | None = None) -> pd.DataFrame:
    """A belépők táblája az M1 sorokra egy `hi_context`-ből: `i` (M1 sorindex),
    `dir`, `sl_abs` (ÁRBAN), `tp_abs` (fibo, árban), `atr15` (a törés
    gyertyáján), `kind`, `label`, `piv`, `b`, `level`, `ev_i` (M15 esemény)."""
    P = ctx["P"]
    evs, a15 = ctx["evs"], ctx["a15"]
    if not evs or not len(m1):
        return pd.DataFrame()
    if stop_atr is None:
        stop_atr = P.get("stop_atr")
    h, l, c = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
    atr1 = atr(h, l, c, 14)
    atr1 = np.where(atr1 > 0, atr1, np.nan)
    pc, pv = pivots(h, l, P["k_lo"])
    start = np.searchsorted(m1.index.to_numpy(), [e["t_close"] for e in evs], side="left")
    max_wait_lo = P["max_wait"] * P["hi_tf"]
    PP = {**P, "max_wait_lo": max_wait_lo}
    rows = []
    n = len(c)
    t0 = m1.index[0]
    for e, s in zip(evs, start):
        if s >= n:
            continue
        # ⚠ Az M1 keret ELEJE előtt zárt esemény kimarad: a `searchsorted` 0-t
        # adna rá, és egy rég lezárult ablak a keret első 120 gyertyájára
        # csúszna (a motor lo-kerete a warmupnál kezdődik, a laboré nem).
        if e["t_close"] < t0:
            continue
        a = a15[e["i"]]
        if not (np.isfinite(a) and a > 0) or not np.isfinite(e["stop_lvl"]):
            continue
        end = min(n - 1, int(s) + max_wait_lo)
        for x in lo_entries(e, int(s), end, h, l, c, atr1, pc, pv, P["k_lo"], mode, PP):
            i = x["i"]
            d = e["dir"]
            sl_abs = (c[i] - (e["stop_lvl"] - P["buffer_atr"] * a)) if d > 0                 else ((e["stop_lvl"] + P["buffer_atr"] * a) - c[i])
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
    """A teljes szabály egy M1 keretre. `hi` = None → a M15 az M1-ből képződik
    (labor); megadva (a motor MT5-ös M15 kerete) azt használja a kontextushoz.

    `stop_atr` = None → a szerkezeti M15-swing stop (2. kérdés); szám →
    fix `stop_atr` × ATR15 (a mért, forward-tesztelt változat)."""
    P = {**DEFAULTS, **(P or {})}
    if hi is None:
        hi = resample(m1, P["hi_tf"])
    return entries_from(hi_context(hi, P, kinds), m1, mode, stop_atr)


def signal_column(m1: pd.DataFrame, P: dict | None = None,
                  stop_atr: float | None = None, hi: pd.DataFrame | None = None,
                  ctx: dict | None = None):
    """A stratégia-motornak: `(sig, sl_abs, atr15)` tömbök az M1 sorokra —
    `sig` = +1/−1 a belépő baron (0 máshol), `sl_abs` a stop ÁRBAN, `atr15`
    a törés gyertyájának ATR-je. Ugyanaz az `entry_table`, oszloppá téve.
    Ha egy bar két eseményből is belépő volna, az ELSŐ esemény számít."""
    n = len(m1)
    sig = np.zeros(n, dtype=np.int8)
    sl = np.full(n, np.nan)
    a15 = np.full(n, np.nan)
    if ctx is not None:
        et = entries_from(ctx, m1, "break", stop_atr)
    else:
        et = entry_table(m1, P, stop_atr=stop_atr, hi=hi)
    if len(et):
        et = et.drop_duplicates("i", keep="first")
        ii = et.i.to_numpy(int)
        sig[ii] = et.dir.to_numpy(int)
        sl[ii] = et.sl_abs.to_numpy(float)
        a15[ii] = et.atr15.to_numpy(float)
    return sig, sl, a15
