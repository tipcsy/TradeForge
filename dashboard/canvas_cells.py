"""
Egy sor cellái ADATKÉNT — rajzolás nélkül, tkinter nélkül.

MIÉRT KÜLÖN. A vászon-tábla kétféleképpen nyúl egy cellához: FELÉPÍTÉSKOR rajzol,
FRISSÍTÉSKOR viszont csak akkor ír, ha a tartalom ténylegesen változott
(`itemconfigure` a tárolt elem-azonosítón — pontosan az a trükk, amivel a mai
widget-tábla `_set`-je elkerüli a villogást). Ha a „mit kell kiírni" logika a
rajzolásba lenne szőve, a két útnak külön-külön kellene ugyanazt kiszámolnia, és
szét tudnának csúszni.

Ezért ez a modul EGY dolgot csinál: a sor-dictből előállítja, hogy oszloponként
mi a SZÖVEG, a SZÍN és az IGAZÍTÁS. A formázók (`_money_r`, `_run_text`,
`_stage_color`, …) a MEGLÉVŐ `live_row`-ból jönnek — nem másoljuk őket, tehát a
két renderelő garantáltan ugyanazt írja ki.

A cella-fajták (`kind`) a rajzolónak szólnak:
    "text"   egyszerű szöveg
    "dots"   pöttyök sora (idősík-irányok / stádiumok), esetleg KERETTEL
    "ctrl"   két kattintható vezérlő egy cellában (Play/Stop + OPT)
"""

from __future__ import annotations
from core.i18n import t as _t

from dashboard import live_row as _lr
from dashboard.theme import (FG_WHITE, FG_GREEN, FG_RED, FG_GRAY, FG_GRAY_DIM)


class Cell:
    """Egy megrajzolandó cella. `key` az oszlop kulcsa (`"wpr_sma|opt"` alakban is)."""

    __slots__ = ("key", "kind", "text", "fg", "anchor", "font", "on_click",
                 "dots", "frame", "parts", "tip")

    def __init__(self, key, kind="text", text="", fg=FG_WHITE, anchor="w",
                 font="mono", on_click=None, dots=None, frame="", parts=None,
                 tip=""):
        self.key = key
        self.kind = kind
        self.text = text
        self.fg = fg
        self.anchor = anchor
        self.font = font
        self.on_click = on_click
        self.dots = list(dots or [])      # [(szín, ), …] — a pöttyök színei
        self.frame = frame                 # "" | "blocked" | "reduced"
        self.parts = list(parts or [])     # ctrl: [(alkulcs, szöveg, szín, cb, aktív)]
        # Buborék: a cella MAGA mondja meg, miért olyan, amilyen. Üres → nincs
        # buborék (a legtöbb cella magától értetődő, és egy mindenhol felugró
        # súgó ugyanolyan zaj, mint egy mindig látszó „nincs hiba" felirat).
        self.tip = tip

    def visual(self) -> tuple:
        """A cella LÁTHATÓ állapota — a frissítés ezt hasonlítja össze.
        Ha nem változott, egyetlen `itemconfigure` sem fut."""
        return (self.text, self.fg, tuple(self.dots), self.frame,
                tuple((p[0], p[1], p[2]) for p in self.parts))


def _pane_of(key: str) -> str:
    """Melyik rögzített sávba tartozik az oszlop: bal | közép | jobb.
    (A tábla fix–görgethető–fix elrendezésű, mint a mai widget-változat.)"""
    if key in ("symbol", "bid", "ask", "change"):
        return "left"
    if key in ("total_pos", "total_daily", "close"):
        return "right"
    return "mid"


PANE_OF = _pane_of


def cells_for(d: dict, collapsed: dict, on_close=None) -> dict:
    """`{oszlop_kulcs: Cell}` egy sorra. A `d` a `row_source.row_data` kimenete."""
    pnl = _lr.pnl_mode(collapsed)
    dg = d.get("digits", 2)
    g = d.get("gates") or {}
    out = {}

    # ── bal: instrumentum ────────────────────────────────────────────────
    # ⚠ ZÁRT PIAC: az ár HALVÁNY. Egy zárt piacú pár eddig pontosan úgy nézett
    # ki, mint egy nyitott, amelyik épp nem talál belépőt — a leggyakoribb néma
    # kérdés (*miért nem csinál semmit?*) megválaszolatlan maradt. A szürke ár
    # magától elmondja, hogy amit látsz, az már nem él; a részleteket (mióta,
    # melyik volt az utolsó árajánlat) a buborék adja. SZÖVEGET nem teszünk a
    # sorba: a szín elég jelzés, a felirat csak zaj volna 10-30 soron át.
    _ses = d.get("session") or {}
    _closed = _ses.get("state") in ("closed", "unknown")
    _tip = _ses.get("tip") or None
    _price_fg = FG_GRAY_DIM if _closed else FG_WHITE

    out["symbol"] = Cell("symbol", text=d.get("symbol", "—"), font="mono_bold",
                         on_click=d.get("on_symbol"), tip=_tip)
    out["bid"] = Cell("bid", text=_lr._fmt_price(d.get("bid"), dg), anchor="e",
                      fg=_price_fg, tip=_tip)
    out["ask"] = Cell("ask", text=_lr._fmt_price(d.get("ask"), dg), anchor="e",
                      fg=_price_fg, tip=_tip)
    ch = d.get("change_pct")
    out["change"] = Cell("change", anchor="e", tip=_tip,
                         text=("—" if ch is None else f"{ch:+.2f}%"),
                         fg=(FG_GRAY_DIM if _closed else
                             (FG_GRAY if ch is None
                              else (FG_GREEN if ch >= 0 else FG_RED))))

    # ── közép: kapuk ─────────────────────────────────────────────────────
    if not (collapsed or {}).get("gates"):
        sp = g.get("spread") or {}
        out["spread"] = Cell("spread", text=sp.get("text", "—"), anchor="center",
                             fg=(FG_RED if sp.get("blocking") else FG_GREEN),
                             on_click=g.get("on_spread"))
        al = g.get("align") or {}
        out["align"] = Cell("align", kind="dots", on_click=al.get("on_click"),
                            dots=[_sign_color(s) for s in (al.get("signs") or [])])
        if _lr.show_market(collapsed):
            mk = g.get("market") or {}
            out["market"] = Cell("market", text=mk.get("text", "—"), fg=FG_GRAY,
                                 font="small", on_click=mk.get("on_click"))
        if _lr.show_momentum(collapsed):
            mo = g.get("momentum") or {}
            out["momentum"] = Cell("momentum", text=mo.get("text", "—"),
                                   anchor="center", on_click=mo.get("on_click"),
                                   fg=(FG_RED if mo.get("blocking") else FG_WHITE))
        if _lr.show_cost(collapsed):
            co = g.get("cost") or {}
            out["cost"] = Cell("cost", text=co.get("text", "—"), anchor="center",
                               on_click=co.get("on_click"),
                               fg=(FG_RED if co.get("blocking") else FG_GREEN))
        # ⚠ A VOLATILITÁS oszlopa eddig KIMARADT innen: a fejléce megjelent (a
        # `gate_order` engedi), de cella SOSEM készült hozzá — az oszlop minden
        # soron ÜRES volt. Közben a `K.Össz.` számolta a volatilitás blokkoló
        # állapotát, tehát a sor „⛔1"-et mutatott LÁTHATÓ ok nélkül. Pontosan az
        # a hibaosztály, ami miatt ez az oszlop egyáltalán megszületett: a
        # BTCUSD hetekig némán nem kereskedett 0,51× aránnyal.
        vo = g.get("volatility") or {}
        out["volatility"] = Cell("volatility", text=vo.get("text", "—"),
                                 anchor="center", on_click=vo.get("on_click"),
                                 fg=(FG_RED if vo.get("blocking") else FG_GREEN))
    badge = g.get("badge", "✓")
    out["badge"] = Cell("badge", text=badge, anchor="center",
                        fg=(FG_RED if badge != "✓" else FG_GREEN))

    # ── közép: stratégiánként ────────────────────────────────────────────
    for st in (d.get("strategies") or []):
        n = st.get("name", "")
        coll = _lr.is_collapsed(collapsed, n)
        # ⚠ A pöttyök ELŐTT egy betű: „V" = VALÓDI kötést nyit, „J" = csak
        # jelez. Enélkül a két állapot ránézésre azonos — ugyanaz a pötty-sor,
        # ugyanaz a zöld Play —, pedig az egyik pénzt mozgat, a másik nem. A
        # betűt a `_lr._mode_mark` adja (ott a szín is).
        _mk, _mk_fg = _lr._mode_mark(st)
        out[f"{n}|stages"] = Cell(
            f"{n}|stages", kind="dots", on_click=st.get("on_stages"),
            frame=(st.get("frame") or ""), text=_mk, fg=_mk_fg,
            dots=[_lr._stage_color(s) for s in (st.get("stages") or [])])
        if not coll:
            pos, day = st.get("position") or {}, st.get("daily") or {}
            out[f"{n}|position"] = Cell(
                f"{n}|position", anchor="e",
                text=_lr._money_r(pos.get("money"), pos.get("r"), pnl))
            out[f"{n}|daily"] = Cell(
                f"{n}|daily", anchor="e",
                text=_lr._money_r(day.get("money"), day.get("r"), pnl),
                fg=_lr._pnl_color(day.get("money")))
            q = st.get("quality") or "—"
            # A SZÖVEG a lefordított felirat, a SZÍN a kódból jön.
            out[f"{n}|quality"] = Cell(
                f"{n}|quality", text=q, anchor="center", font="small",
                fg=_lr._quality_color(st.get("quality_code") or q))
        # ⚠ A VEZERLES mostantol CSAK Play/Stop. Az OPT lekerult: az
        # optimalizalas a parameter-ablak Futtatas lapjarol indul, ahol LATOD,
        # mi fog tortenni (idoszakok, kapuk, hangolt dimenziok, keresesi ter).
        # Egy sorbeli gomb ezt mind atugrotta — orakra inditott valamit, amirol
        # a felulet semmit nem mondott.
        run_txt, run_fg = _lr._run_text(st)
        # ⚠ A HALVÁNY VEZÉRLŐ MOSTANTÓL MAGÁTÓL MEGMONDJA, MIÉRT AZ.
        # Eddig a `–` csak KATTINTÁSRA árulta el az okot (az állapotsorban) — egy
        # gondolatjelnek látszó jel viszont a szemnek „nincs itt semmi", nem „ez
        # ki van kapcsolva". Így a stratégiát nem lehetett elindítani, és az sem
        # derült ki, mi az akadály: a sor közben jelzést ÉS minősítést is
        # mutatott, tehát késznek látszott.
        _tip = ""
        if not st.get("enabled", True):
            _tip = _t("strategy.disabled_tip", name=n)
        out[f"{n}|ctrl"] = Cell(f"{n}|ctrl", kind="ctrl", tip=_tip, parts=[
            ("run", run_txt, run_fg, st.get("on_toggle"),
             bool(st.get("enabled", True))),
        ])
        if not coll:
            out[f"{n}|opt"] = Cell(f"{n}|opt", text=st.get("opt") or "—",
                                   anchor="center", font="small", fg=FG_GRAY)

    # ── jobb: összesítő ──────────────────────────────────────────────────
    t = d.get("total") or {}
    tp, td = t.get("position") or {}, t.get("daily") or {}
    out["total_pos"] = Cell("total_pos", anchor="e", font="mono_bold",
                            text=_lr._money_r(tp.get("money"), tp.get("r"), pnl))
    out["total_daily"] = Cell("total_daily", anchor="e", font="mono_bold",
                              text=_lr._money_r(td.get("money"), td.get("r"), pnl),
                              fg=_lr._pnl_color(td.get("money")))
    out["close"] = Cell("close", text="✕", anchor="center", font="small",
                        fg=FG_GRAY_DIM, on_click=on_close)
    return out


def _sign_color(s):
    """Az idősík-irány pöttyének színe — ugyanaz a szabály, mint a widget-sorban."""
    return FG_GREEN if s > 0 else FG_RED if s < 0 else FG_GRAY_DIM
