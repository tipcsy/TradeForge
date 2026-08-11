"""A söprés eredményének RAJZA: görbe (1 paraméter) vagy hőtérkép (2 paraméter).

A felhasználói dokumentáció dilemmája:

    „A kiértékelő grafikon két paraméter összehasonlítására kiváló, de 10-re már
     nem lenne alkalmas. Ha mondjuk futtatnánk egy SMA 100-200 tól-ig-et step
     10-zel… Itt lehet, hogy megint közös gondolkodás fog eredményre vezetni."

A válasz a dimenziószám: 1 paraméternél GÖRBE (a paraméter → eredmény függvény),
2-nél HŐTÉRKÉP (a rács minden pontja egy szín). Háromnál több már nem rajzolható
értelmesen — ott az optimalizálás mintavétele és az eredménytábla a helyes eszköz.

⚠ AMIT A GÖRBE ALAKJA MEGMUTAT, ÉS EGY SZÁM NEM: hogy a legjobb pont egy SZÉLES
FENNSÍK közepén van-e, vagy egy magányos tüskén. A tüske szinte biztosan
túlillesztés — a szomszédos paraméter-érték már mást ad, tehát a „legjobb" érték
a zajt találta el, nem a piacot. Ez az egyetlen ok, amiért ezt a nézetet érdemes
megépíteni: a puszta „legjobb érték" szám ezt eltakarja.

A rajz tk.Canvas-on készül (nincs külső függőség), a színek a témából jönnek.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PAD_L, PAD_R, PAD_T, PAD_B = 62, 16, 18, 34


def _nice(v: float) -> str:
    if v == int(v):
        return f"{int(v)}"
    return f"{v:g}".replace(".", ",")


def _lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def heat_color(v: float, lo: float, hi: float, neg_hex: str, zero_hex: str,
               pos_hex: str) -> str:
    """Érték → szín. A NULLA a fordulópont, nem a tartomány közepe.

    ⚠ Ez nem esztétika: a P&L-nél a 0 az egyetlen jelentéssel bíró határ. Ha a
    színskála a min…max közepére tenné a semlegest, egy csupa veszteséges rács
    fele ZÖLDNEK látszana — a felhasználó pedig „jó tartományt" keresne ott, ahol
    csak a kevésbé rossz van.
    """
    if v is None:
        return zero_hex
    if v >= 0:
        t = 0.0 if hi <= 0 else v / hi
        return _hex([_lerp(a, b, t) for a, b in zip(_to_rgb(zero_hex),
                                                    _to_rgb(pos_hex))])
    t = 0.0 if lo >= 0 else v / lo
    return _hex([_lerp(a, b, t) for a, b in zip(_to_rgb(zero_hex),
                                                _to_rgb(neg_hex))])


def draw(canvas, axes: list, rows: list, metric: str, theme, font,
         on_pick=None) -> None:
    """A söprés kirajzolása. `axes`: `[(kulcs, [értékek]), …]` (1 vagy 2 elem)."""
    canvas.delete("all")
    if not axes or not rows:
        return
    if len(axes) == 1:
        _draw_curve(canvas, axes[0], rows, metric, theme, font, on_pick)
    else:
        _draw_heat(canvas, axes[0], axes[1], rows, metric, theme, font, on_pick)


def _values(rows, key_x, metric, xs):
    by = {}
    for r in rows:
        if r.get("note"):
            continue
        by[r.get(key_x)] = r.get(metric)
    return [by.get(x) for x in xs]


def _draw_curve(canvas, axis, rows, metric, th, font, on_pick):
    key, xs = axis
    ys = _values(rows, key, metric, xs)
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if not pts:
        return
    w = max(int(canvas.winfo_width()), 320)
    h = max(int(canvas.winfo_height()), 200)
    x0, x1 = PAD_L, w - PAD_R
    y0, y1 = PAD_T, h - PAD_B
    vals = [p[1] for p in pts]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1.0
    # A NULLA mindig benne van a skálában: enélkül egy csupa veszteséges görbe
    # felfelé tartónak látszana, és nem derülne ki, hogy végig a 0 alatt jár.
    lo, hi = min(lo, 0.0), max(hi, 0.0)

    def px(x):
        i = xs.index(x)
        return x0 + (x1 - x0) * (i / max(1, len(xs) - 1))

    def py(v):
        return y1 - (y1 - y0) * ((v - lo) / (hi - lo))

    # rács + tengelyfeliratok
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = lo + (hi - lo) * frac
        y = py(v)
        canvas.create_line(x0, y, x1, y, fill=th.BG_HEADER)
        canvas.create_text(x0 - 6, y, text=_nice(round(v, 2)), anchor="e",
                           fill=th.FG_GRAY_DIM, font=font)
    if lo < 0 < hi:                       # a nulla-vonal kiemelve
        canvas.create_line(x0, py(0), x1, py(0), fill=th.FG_GRAY)

    # a görbe
    coords = []
    for x, v in pts:
        coords += [px(x), py(v)]
    if len(coords) >= 4:
        canvas.create_line(*coords, fill=th.FG_BLUE, width=2, smooth=False)
    for x, v in pts:
        canvas.create_oval(px(x) - 3, py(v) - 3, px(x) + 3, py(v) + 3,
                           fill=(th.FG_GREEN if v > 0 else
                                 th.FG_RED if v < 0 else th.FG_GRAY),
                           outline="")
    # a legjobb pont
    bx, bv = max(pts, key=lambda p: p[1])
    canvas.create_oval(px(bx) - 6, py(bv) - 6, px(bx) + 6, py(bv) + 6,
                       outline=th.FG_YELLOW, width=2)
    canvas.create_text(px(bx), py(bv) - 12, text=f"{key}={_nice(bx)}",
                       fill=th.FG_YELLOW, font=font)

    # x-feliratok (ritkítva, hogy ne folyjanak össze)
    step = max(1, len(xs) // 10)
    for i, x in enumerate(xs):
        if i % step:
            continue
        canvas.create_text(px(x), y1 + 12, text=_nice(x), fill=th.FG_GRAY_DIM,
                           font=font)
    canvas.create_text((x0 + x1) / 2, h - 8, text=key, fill=th.FG_GRAY, font=font)

    if on_pick:
        def _click(ev):
            near = min(xs, key=lambda x: abs(px(x) - ev.x))
            on_pick({key: near})
        canvas.bind("<Button-1>", _click)


def _draw_heat(canvas, ax, ay, rows, metric, th, font, on_pick):
    kx, xs = ax
    ky, ys = ay
    grid = {}
    for r in rows:
        if r.get("note"):
            continue
        grid[(r.get(kx), r.get(ky))] = r.get(metric)
    vals = [v for v in grid.values() if v is not None]
    if not vals:
        return
    lo, hi = min(vals), max(vals)

    w = max(int(canvas.winfo_width()), 320)
    h = max(int(canvas.winfo_height()), 200)
    x0, x1 = PAD_L, w - PAD_R
    y0, y1 = PAD_T, h - PAD_B
    cw = (x1 - x0) / max(1, len(xs))
    ch = (y1 - y0) / max(1, len(ys))
    best_cell, best_v = None, None

    for i, xv in enumerate(xs):
        for j, yv in enumerate(ys):
            v = grid.get((xv, yv))
            cx, cy = x0 + i * cw, y1 - (j + 1) * ch
            canvas.create_rectangle(
                cx, cy, cx + cw, cy + ch, width=0,
                fill=(th.BG_HEADER if v is None else
                      heat_color(v, lo, hi, th.FG_RED, th.BG, th.FG_GREEN)))
            if v is not None and (best_v is None or v > best_v):
                best_v, best_cell = v, (cx, cy)
    if best_cell:
        canvas.create_rectangle(best_cell[0], best_cell[1],
                                best_cell[0] + cw, best_cell[1] + ch,
                                outline=th.FG_YELLOW, width=2)

    step_x = max(1, len(xs) // 8)
    for i, xv in enumerate(xs):
        if i % step_x:
            continue
        canvas.create_text(x0 + i * cw + cw / 2, y1 + 12, text=_nice(xv),
                           fill=th.FG_GRAY_DIM, font=font)
    step_y = max(1, len(ys) // 8)
    for j, yv in enumerate(ys):
        if j % step_y:
            continue
        canvas.create_text(x0 - 6, y1 - j * ch - ch / 2, text=_nice(yv),
                           anchor="e", fill=th.FG_GRAY_DIM, font=font)
    canvas.create_text((x0 + x1) / 2, h - 8, text=kx, fill=th.FG_GRAY, font=font)
    canvas.create_text(12, (y0 + y1) / 2, text=ky, fill=th.FG_GRAY, font=font,
                       angle=90)

    if on_pick:
        def _click(ev):
            i = int((ev.x - x0) // cw) if cw else 0
            j = int((y1 - ev.y) // ch) if ch else 0
            if 0 <= i < len(xs) and 0 <= j < len(ys):
                on_pick({kx: xs[i], ky: ys[j]})
        canvas.bind("<Button-1>", _click)
