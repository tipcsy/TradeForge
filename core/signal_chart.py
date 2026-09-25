"""
JELZÉS-KÉP a Telegram-értesítéshez — M15 + M1 gyertyák, a belépő szintjeivel.

A felhasználó kérése (2026-09-25): „amikor érkezik egy jelzés, küldjön egy
képet is az aktuális beszállóról, M1 és M15" — és a WPR jelzését is, külön
panelen. A kép minden idősíkra:

    ┌ M15 ár + (ha a stratégia kéri) SMA ─────────────┐
    │ M15 oszcillátor (pl. WPR) a stratégia szintjeivel │
    ├ M1 ár ───────────────────────────────────────────┤
    │ M1 oszcillátor                                    │
    └──────────────────────────────────────────────────┘

A belépő (kék), az SL (piros) és a TP (zöld) vízszintes vonal mindkét
ár-panelen, a jelölő a legutolsó (a jelzést adó) gyertyán.

⚠ MIT RAJZOLJUNK — A STRATÉGIA MONDJA MEG (`Strategy.chart_spec`). Ez a modul
a KERET része: nem tudja, mi az a WPR vagy melyik SMA számít. A spec egy sima
szótár, pl.

    {"tfs": [15, 1],                                   # a kép idősíkjai
     "sma": {"tf": 15, "period": 200},                 # (régi alak, = overlay)
     "overlays": [{"kind": "ema", "tf": 60, "period": 200},
                  {"kind": "bb", "tf": 60, "period": 20, "std": 2.0},
                  {"kind": "keltner", "tf": 60, "period": 20,
                   "atr_period": 10, "mult": 1.5, "atr": "ema"}],
     "panels": [{"kind": "wpr", "tf": 15, "period": 21,
                 "levels": [-20, -50, -50, -80]},
                {"kind": "stoch", "tf": 5, "period": 14, "d": 3,
                 "levels": [80, 20]}]}

Üres spec → M15 + M1 gyertyák + szintek (minden stratégiára működik).

⚠ A KÉPLETEK A STRATÉGIÁÉI: a Keltner ATR-je a trend_pullbacknél egyszerű
mozgóátlag, a bollingernél EMA (`"atr": "sma"|"ema"`), a Bollinger szórása
`ddof=0`. Egy „szabványos" képlet a képen más sávot rajzolna, mint amiből a
jelzés született — és a felhasználó a képről ítél.

⚠ SZÁLBIZTOS RAJZ: `matplotlib.figure.Figure` + Agg vászon, NEM `pyplot`. A
pyplot globális állapotot tart (az „aktuális ábra"), és az értesítés-szál meg
egy jóváhagyó-szál egyszerre rajzolhat.

⚠ A TÁVOLI CÉLÁR nem nyomhatja össze a gyertyákat: ha a TP messze a látható
tartományon kívül esik (pl. `tp_rr_ratio` 15 = „nincs célár"), a vonal helyett
egy nyíl + ár jelzi a panel szélén.

TISZTA modul: a hívó adja a gyertyákat (DataFrame), itt csak rajzolunk.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

# Mennyi gyertya látsszon idősíkonként.
SHOW = {1: 90, 5: 80, 15: 70, 30: 70, 60: 60, 240: 60}
DEFAULT_TFS = (15, 1)


def spec_tfs(spec: dict | None) -> tuple:
    """A kép idősíkjai (felülről lefelé) — a spec `tfs`-e, különben M15 + M1."""
    t = (spec or {}).get("tfs")
    try:
        out = tuple(int(x) for x in (t or ()))
    except (TypeError, ValueError):
        out = ()
    return out or DEFAULT_TFS


def _overlays(spec: dict | None) -> list:
    """Az ár-panelre rajzolandó vonalak — a régi `sma` kulccsal együtt."""
    spec = spec or {}
    out = list(spec.get("overlays") or ())
    sma = spec.get("sma") or {}
    if sma and sma.get("period"):
        out.insert(0, {"kind": "sma", "tf": int(sma.get("tf", 15)),
                       "period": int(sma["period"])})
    return out

_UP, _DOWN = "#2a9d4b", "#d33a2c"
_ENTRY, _SL, _TP = "#1f6fd1", "#d33a2c", "#2a9d4b"


def bars_needed(spec: dict | None, tf: int) -> int:
    """Hány gyertyát kérjen a hívó ezen az idősíkon: a látható rész + a
    leghosszabb indikátor bemelegítése (különben a vonal eleje hiányozna)."""
    spec = spec or {}
    warm = 0
    for o in _overlays(spec):
        if int(o.get("tf", 0)) == tf:
            warm = max(warm, int(o.get("period", 0) or 0),
                       int(o.get("atr_period", 0) or 0))
    for p in spec.get("panels") or ():
        if int(p.get("tf", 0)) == tf:
            warm = max(warm, int(p.get("period", 0) or 0)
                       + int(p.get("d", 0) or 0))
    # Az EMA-knak több bemelegítés kell (exponenciális emlékezet): ×2.
    return SHOW.get(tf, 80) + 2 * warm + 2


def _atr_series(df: pd.DataFrame, n: int, mode: str) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([(df["high"] - df["low"]).abs(), (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    if mode == "ema":
        return tr.ewm(span=int(n), adjust=False).mean()
    return tr.rolling(int(n)).mean()


def _draw_overlay(ax, df: pd.DataFrame, o: dict, show: int) -> None:
    """Egy ár-panel vonal (SMA/EMA/Bollinger/Keltner) — a stratégia képletével."""
    kind = str(o.get("kind") or "")
    per = int(o.get("period") or 20)
    c = df["close"]
    x = np.arange(min(len(df), show))

    def _v(s):
        return s.iloc[-show:].to_numpy(float)

    if kind == "sma":
        ax.plot(x, _v(c.rolling(per).mean()), color="#e69f00", linewidth=1.2,
                label=f"SMA({per})")
    elif kind == "ema":
        ax.plot(x, _v(c.ewm(span=per, adjust=False).mean()),
                color=o.get("color", "#8e44ad"), linewidth=1.1,
                label=f"EMA({per})")
    elif kind == "bb":
        k = float(o.get("std", 2.0))
        mb = c.rolling(per).mean()
        sd = c.rolling(per).std(ddof=0)
        ax.plot(x, _v(mb + k * sd), color="#1f77b4", linewidth=0.9,
                label=f"BB({per}, {k:g})")
        ax.plot(x, _v(mb - k * sd), color="#1f77b4", linewidth=0.9)
        ax.plot(x, _v(mb), color="#1f77b4", linewidth=0.6, linestyle=":")
    elif kind == "keltner":
        m = float(o.get("mult", 2.0))
        mid = c.ewm(span=per, adjust=False).mean()
        a = _atr_series(df, int(o.get("atr_period") or per),
                        str(o.get("atr", "sma")))
        ax.plot(x, _v(mid + m * a), color="#16a085", linewidth=0.9,
                linestyle="--", label=f"Keltner({per}, {m:g})")
        ax.plot(x, _v(mid - m * a), color="#16a085", linewidth=0.9,
                linestyle="--")


def _candles(ax, df: pd.DataFrame) -> None:
    x = np.arange(len(df))
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    col = np.where(c >= o, _UP, _DOWN)
    ax.vlines(x, l, h, colors=col, linewidth=0.8)
    body_lo = np.minimum(o, c)
    body_h = np.maximum(np.abs(c - o), (h.max() - l.min()) * 0.0015)
    ax.bar(x, body_h, bottom=body_lo, width=0.62, color=col, linewidth=0)


def _time_ticks(ax, idx, n: int = 6) -> None:
    if not len(idx):
        return
    pos = np.linspace(0, len(idx) - 1, min(n, len(idx))).astype(int)
    ax.set_xticks(pos)
    ax.set_xticklabels([pd.Timestamp(idx[i]).strftime("%H:%M") for i in pos],
                       fontsize=7)


def _levels(ax, direction: str, entry: float, sl: float, tp: float,
            lo: float, hi: float, fmt) -> tuple:
    """A három vízszintes szint + a látható tartomány. `(ymin, ymax)`.

    Az SL MINDIG látsszon (az a kockázat); a TP csak akkor, ha a gyertya-
    tartomány ~2,5-szörösén belül van — különben nyíl a szélen."""
    rng = max(hi - lo, abs(entry - sl), 1e-12)
    ymin = min(lo, entry, sl)
    ymax = max(hi, entry, sl)
    tp_in = tp is not None and abs(tp - entry) <= 2.5 * rng
    if tp_in:
        ymin, ymax = min(ymin, tp), max(ymax, tp)
    pad = (ymax - ymin) * 0.06
    ymin, ymax = ymin - pad, ymax + pad
    for y, c, lab in ((entry, _ENTRY, "Entry"), (sl, _SL, "SL")) + (
            ((tp, _TP, "TP"),) if tp_in else ()):
        ax.axhline(y, color=c, linewidth=1.0, linestyle="--", alpha=0.9)
        ax.text(1.002, y, f"{lab} {fmt(y)}", transform=ax.get_yaxis_transform(),
                color=c, fontsize=7, va="center", ha="left")
    if tp is not None and not tp_in:
        up = tp > entry
        ax.annotate(f"TP {fmt(tp)} {'↑' if up else '↓'}",
                    xy=(0.99, 0.97 if up else 0.03), xycoords="axes fraction",
                    ha="right", va="top" if up else "bottom", fontsize=7,
                    color=_TP)
    return ymin, ymax


def _osc_panel(ax, df: pd.DataFrame, panel: dict) -> None:
    kind = str(panel.get("kind") or "")
    per = int(panel.get("period") or 14)
    v2 = None
    if kind == "wpr":
        from core.indicator_engine import wpr
        v = wpr(df["high"], df["low"], df["close"], per)
        ax.set_ylim(-102, 2)
        name = f"WPR({per})"
    elif kind == "stoch":
        v, v2 = _stoch(df, per, int(panel.get("d") or 3))
        ax.set_ylim(-2, 102)
        name = f"Stoch({per},{int(panel.get('d') or 3)})"
    else:
        return
    _n = SHOW.get(int(panel.get("tf", 1)), 80)
    v = v.iloc[-_n:]
    ax.plot(np.arange(len(v)), v.to_numpy(float), color="#333333", linewidth=1.0)
    if v2 is not None:
        v2 = v2.iloc[-_n:]
        ax.plot(np.arange(len(v2)), v2.to_numpy(float), color="#d35400",
                linewidth=0.9)
    levels = list(panel.get("levels") or ())
    if kind == "stoch":
        for lv in levels:
            ax.axhline(float(lv), color="#888888", linewidth=0.8, linestyle=":")
        ax.set_ylabel(name, fontsize=7)
        ax.tick_params(labelsize=7)
        return
    # A szintek jelentése a wpr_sma sorrendjében: felső extrém, SELL trigger,
    # BUY trigger, alsó extrém — az extrémek szürkék, a triggerek színesek.
    stilus = ["#888888", _SL, _UP, "#888888"]
    for i, lv in enumerate(levels):
        ax.axhline(float(lv), color=stilus[i] if i < len(stilus) else "#888888",
                   linewidth=0.8, linestyle=":" if i in (0, 3) else "--")
    ax.set_ylabel(name, fontsize=7)
    ax.tick_params(labelsize=7)


def _stoch(df: pd.DataFrame, n: int, d: int) -> tuple:
    """%K és %D — a trend_pullback képletével (a legalacsonyabb low / legmagasabb
    high `n` gyertyán, %D = %K egyszerű átlaga `d`-re)."""
    hh = df["high"].rolling(n, min_periods=n).max()
    ll = df["low"].rolling(n, min_periods=n).min()
    rng = (hh - ll).where(lambda r: r > 0)
    k = 100.0 * (df["close"] - ll) / rng
    return k, k.rolling(d, min_periods=d).mean()


def render_png(symbol: str, direction: str, entry, sl, tp,
               bars: dict, spec: dict | None = None, digits: int = 5,
               title: str = "", tfs=None, only: "str | None" = None) -> bytes:
    """A kép PNG-bájtjai. `bars`: `{15: DataFrame, 1: DataFrame}` (OHLC).

    `entry=None` → NINCS belépő (a `/photo` parancs pillanatképe): csak a
    gyertyák és az indikátorok, szintek és jelölő nélkül. `tfs`: melyik
    idősík(ok) kerüljenek a képre. `only="wpr"` → CSAK az ilyen fajtájú
    oszcillátor-panelek (ár nélkül) — `/photo UsaTec M15 wpr`; ha nincs
    ilyen panel, `ValueError`.

    Hiányzó idősík kimarad; ha egyik sincs, `ValueError` (a hívó ilyenkor a
    szöveges üzenetet küldi)."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    spec = spec or {}
    _kert = tuple(tfs) if tfs else spec_tfs(spec)
    tfs = [tf for tf in _kert if bars.get(tf) is not None and len(bars[tf])]
    if not tfs:
        raise ValueError("nincs gyertya a képhez")
    panels_by_tf = {tf: [p for p in (spec.get("panels") or ())
                         if int(p.get("tf", 0)) == tf] for tf in tfs}
    ratios, rows = [], []
    for tf in tfs:
        if only is None:
            rows.append(("price", tf, None))
            ratios.append(3)
        for p in panels_by_tf[tf]:
            if only is not None and str(p.get("kind")) != only:
                continue
            rows.append(("osc", tf, p))
            ratios.append(1 if only is None else 2)
    if not rows:
        raise ValueError(f"nincs {only} panel")

    def fmt(v):
        return f"{float(v):.{max(0, int(digits))}f}"

    _n_ar = sum(1 for r in rows if r[0] == "price")
    fig = Figure(figsize=(9, 2.2 * _n_ar + (0.9 if only is None else 1.8)
                          * (len(rows) - _n_ar) + 0.6), dpi=110)
    FigureCanvasAgg(fig)
    gs = fig.add_gridspec(len(rows), 1, height_ratios=ratios, hspace=0.3)
    is_buy = str(direction).upper() == "BUY"
    for r, (fajta, tf, panel) in enumerate(rows):
        ax = fig.add_subplot(gs[r, 0])
        df = bars[tf]
        show = SHOW.get(tf, 80)
        if fajta == "price":
            d = df.iloc[-show:]
            _candles(ax, d)
            _ov = [o for o in _overlays(spec) if int(o.get("tf", 0)) == tf]
            for o in _ov:
                _draw_overlay(ax, df, o, show)
            if _ov:
                ax.legend(loc="upper left", fontsize=7, frameon=True,
                          framealpha=0.75, edgecolor="none")
            if entry is not None:
                y0, y1 = _levels(ax, direction, float(entry), float(sl),
                                 None if tp is None else float(tp),
                                 float(d["low"].min()), float(d["high"].max()),
                                 fmt)
                ax.set_ylim(y0, y1)
                ax.plot([len(d) - 1], [float(entry)],
                        marker="^" if is_buy else "v", color=_ENTRY,
                        markersize=9)
            else:
                # Pillanatkép: a legutolsó záróár mint jobb oldali felirat.
                _c = float(d["close"].iloc[-1])
                ax.text(1.002, _c, fmt(_c), transform=ax.get_yaxis_transform(),
                        color="#333333", fontsize=7, va="center", ha="left")
            ax.set_title(tf_label(tf), loc="left", fontsize=8, pad=2)
            ax.tick_params(labelsize=7)
            _time_ticks(ax, d.index)
            # Ha alatta az idősík oszcillátora jön, az időtengely ott látszik —
            # kétszer kiírva összecsúszna a következő panel címével.
            if panels_by_tf[tf]:
                ax.set_xticklabels([])
        elif only is not None:
            _osc_panel(ax, df, panel)
            ax.set_title(tf_label(tf), loc="left", fontsize=8, pad=2)
            _time_ticks(ax, df.index[-show:])
        else:
            _osc_panel(ax, df, panel)
            ax.plot([min(len(df), show) - 1], [0], alpha=0)   # közös x-skála
            _time_ticks(ax, df.index[-show:])
        ax.set_xlim(-1, show + 1)
        ax.grid(alpha=0.15)
    fig.suptitle(title or f"{symbol} {direction}", fontsize=10, x=0.02, ha="left")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    return buf.getvalue()


def panel_values(bars: dict, spec: dict | None) -> list:
    """`[("WPR M15", -44.0), ("WPR M1", -80.0)]` — az oszcillátorok ÉRTÉKE a
    legutolsó LEZÁRT gyertyán (ugyanaz a gyertya, amin a rajz véget ér).

    A képaláírásba kerül: a felhasználó kérése, hogy a szám a kép mellett
    SZÖVEGKÉNT is ott legyen (a panelről leolvasni pontatlan)."""
    out = []
    for p in (spec or {}).get("panels") or ():
        tf = int(p.get("tf", 0))
        df = (bars or {}).get(tf)
        if df is None or not len(df):
            continue
        if str(p.get("kind")) == "wpr":
            from core.indicator_engine import wpr
            v = wpr(df["high"], df["low"], df["close"],
                    int(p.get("period") or 14)).iloc[-1]
            if v == v:
                out.append((f"WPR {tf_label(tf)}", float(v)))
        elif str(p.get("kind")) == "stoch":
            k, dd = _stoch(df, int(p.get("period") or 14), int(p.get("d") or 3))
            if k.iloc[-1] == k.iloc[-1]:
                out.append((f"Stoch {tf_label(tf)}", float(k.iloc[-1])))
    return out


def tf_label(tf: int) -> str:
    """`1` → „M1", `60` → „H1", `240` → „H4"."""
    tf = int(tf)
    return f"H{tf // 60}" if tf >= 60 and tf % 60 == 0 else f"M{tf}"


def values_text(values: list) -> str:
    """`WPR M15: -44 · WPR M1: -80` (üres lista → üres szöveg)."""
    return " · ".join(f"{n}: {v:.0f}" for n, v in (values or ()))


def fetch_bars(symbol: str, spec: dict | None, fetch, tfs=None) -> dict:
    """`{tf: DataFrame}` a kép idősíkjaira (`tfs`, különben a spec-éi).
    `fetch(tf, n)` → DataFrame | None (élesben `mt5_connector.tf_bars`). Hiba →
    az adott idősík kimarad."""
    out = {}
    for tf in (tuple(tfs) if tfs else spec_tfs(spec)):
        try:
            df = fetch(tf, bars_needed(spec, tf))
        except Exception:
            df = None
        if df is not None and len(df):
            out[tf] = df
    return out
