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

    {"sma": {"tf": 15, "period": 200},
     "panels": [{"kind": "wpr", "tf": 15, "period": 21,
                 "levels": [-20, -50, -50, -80]},
                {"kind": "wpr", "tf": 1, "period": 21,
                 "levels": [-20, -50, -50, -80]}]}

Üres spec → csak gyertyák + szintek (minden stratégiára működik).

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
SHOW = {15: 70, 1: 90}

_UP, _DOWN = "#2a9d4b", "#d33a2c"
_ENTRY, _SL, _TP = "#1f6fd1", "#d33a2c", "#2a9d4b"


def bars_needed(spec: dict | None, tf: int) -> int:
    """Hány gyertyát kérjen a hívó ezen az idősíkon: a látható rész + a
    leghosszabb indikátor bemelegítése (különben a vonal eleje hiányozna)."""
    spec = spec or {}
    warm = 0
    sma = spec.get("sma") or {}
    if int(sma.get("tf", 15)) == tf:
        warm = max(warm, int(sma.get("period", 0) or 0))
    for p in spec.get("panels") or ():
        if int(p.get("tf", 0)) == tf:
            warm = max(warm, int(p.get("period", 0) or 0))
    return SHOW.get(tf, 80) + warm + 2


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
    if kind == "wpr":
        from core.indicator_engine import wpr
        v = wpr(df["high"], df["low"], df["close"], per)
        ax.set_ylim(-102, 2)
        name = f"WPR({per})"
    else:
        return
    v = v.iloc[-SHOW.get(int(panel.get("tf", 1)), 80):]
    ax.plot(np.arange(len(v)), v.to_numpy(float), color="#333333", linewidth=1.0)
    levels = list(panel.get("levels") or ())
    # A szintek jelentése a wpr_sma sorrendjében: felső extrém, SELL trigger,
    # BUY trigger, alsó extrém — az extrémek szürkék, a triggerek színesek.
    stilus = ["#888888", _SL, _UP, "#888888"]
    for i, lv in enumerate(levels):
        ax.axhline(float(lv), color=stilus[i] if i < len(stilus) else "#888888",
                   linewidth=0.8, linestyle=":" if i in (0, 3) else "--")
    ax.set_ylabel(name, fontsize=7)
    ax.tick_params(labelsize=7)


def render_png(symbol: str, direction: str, entry, sl, tp,
               bars: dict, spec: dict | None = None, digits: int = 5,
               title: str = "", tfs=(15, 1), only: "str | None" = None) -> bytes:
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
    tfs = [tf for tf in (15, 1) if tf in tuple(tfs)
           and bars.get(tf) is not None and len(bars[tf])]
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
    gs = fig.add_gridspec(len(rows), 1, height_ratios=ratios, hspace=0.12)
    is_buy = str(direction).upper() == "BUY"
    for r, (fajta, tf, panel) in enumerate(rows):
        ax = fig.add_subplot(gs[r, 0])
        df = bars[tf]
        show = SHOW.get(tf, 80)
        if fajta == "price":
            d = df.iloc[-show:]
            _candles(ax, d)
            sma = spec.get("sma") or {}
            if sma and int(sma.get("tf", 15)) == tf and sma.get("period"):
                s = df["close"].rolling(int(sma["period"])).mean().iloc[-show:]
                ax.plot(np.arange(len(s)), s.to_numpy(float), color="#e69f00",
                        linewidth=1.2, label=f"SMA({int(sma['period'])})")
                ax.legend(loc="upper left", fontsize=7, frameon=False)
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
            ax.set_title(f"M{tf}", loc="left", fontsize=8, pad=2)
            ax.tick_params(labelsize=7)
            _time_ticks(ax, d.index)
            # Ha alatta az idősík oszcillátora jön, az időtengely ott látszik —
            # kétszer kiírva összecsúszna a következő panel címével.
            if panels_by_tf[tf]:
                ax.set_xticklabels([])
        elif only is not None:
            _osc_panel(ax, df, panel)
            ax.set_title(f"M{tf}", loc="left", fontsize=8, pad=2)
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
                out.append((f"WPR M{tf}", float(v)))
    return out


def values_text(values: list) -> str:
    """`WPR M15: -44 · WPR M1: -80` (üres lista → üres szöveg)."""
    return " · ".join(f"{n}: {v:.0f}" for n, v in (values or ()))


def fetch_bars(symbol: str, spec: dict | None, fetch) -> dict:
    """`{tf: DataFrame}` a két idősíkra. `fetch(tf, n)` → DataFrame | None
    (élesben `mt5_connector.tf_bars`). Hiba → az adott idősík kimarad."""
    out = {}
    for tf in (15, 1):
        try:
            df = fetch(tf, bars_needed(spec, tf))
        except Exception:
            df = None
        if df is not None and len(df):
            out[tf] = df
    return out
