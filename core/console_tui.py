"""ÉLŐ TÁBLÁZAT a konzolon (`rich`) — a `console_cmd` MÁSODIK megjelenítője.

⚠ MIÉRT NEM EGY MÁSODIK PROGRAM. A parancsok (`play`, `stop`, `close`) és a
lekérdezések (`pair_rows`, `position_rows`, `state_rows`) a `core.console_cmd`-ben
laknak. Ez a modul CSAK rajzol: ha a TUI a saját lekérdezését írná meg, két
helyen kellene karbantartani ugyanazt a szabályt (mikor „fut" egy stratégia,
mikor „halad" a motor) — és a kettő elcsúszna. Ugyanaz a hibaosztály, amiért a
viz-sáv és a warmup-mélység lelete született.

⚠ A `rich` NEM KÖTELEZŐ FÜGGŐSÉG A FUTÁSHOZ. Ha hiányzik, a program a
parancssoros módban megy tovább, és MEGMONDJA, mit kell telepíteni — egy
importhiba miatt ne álljon meg a kereskedés.

── A MŰKÖDÉS ───────────────────────────────────────────────────────────────
Alaphelyzetben a táblázat frissül magától. Billentyűleütésre a kép MEGÁLL, és
egy `tf>` sor jön: ott ugyanazok a parancsok mennek, mint a parancssoros
módban. A parancs lefutása után a kép visszatér.

⚠ MIÉRT ÁLL MEG A KÉP a beíráshoz: egy magától újrarajzolódó képernyőn a
begépelt sor másodpercenként eltűnne a frissítés alatt. A megállítás olcsóbb,
mint egy saját sorszerkesztő megírása — és a `close`/`stop` megerősítő kérdése
is olvasható marad.
"""

from __future__ import annotations

import time

from core import console_cmd as cc
from core.i18n import t as _t

# A frissítés üteme. ⚠ A motor köre 10 mp; ennél sűrűbben nincs mit mutatni,
# ritkábban viszont „beragadtnak" látszana a kép. A rajzolás költsége egy
# 10-20 soros táblánál elhanyagolható, de gyenge gépen se pörgessük fölöslegesen.
FRISSITES_MP = 2.0


def elerheto() -> bool:
    """Telepítve van-e a `rich`? (A hívó ebből dönt, nem egy elkapott hibából.)"""
    try:
        import rich                                # noqa: F401
        return True
    except ImportError:
        return False


def _szin_allapot(allapot: str) -> str:
    return {"LIVE": "green", "CLOSING": "yellow",
            "OPTIMIZING": "cyan", "QUEUED": "cyan"}.get(str(allapot), "dim")


def _pnl_szoveg(ertek):
    """P&L érték színezve. `None` → nincs pozíció (nem nulla!)."""
    from rich.text import Text
    if ertek is None:
        return Text("-", style="dim")
    v = float(ertek)
    return Text(f"{v:+.2f}", style="green" if v > 0 else
                ("red" if v < 0 else "dim"))


def fejlec(ctx: cc.Context):
    """Számla + életjel egy sorban. A `state_rows`-ból, nem külön lekérdezésből."""
    from rich.table import Table
    from rich.text import Text
    from version import APP_TITLE

    # ⚠ KÉT SOR, nem két oszlop: egy szűk (80 oszlopos, SSH-s) terminálon a
    # jobbra igazított állapot-sor betördelődött a számla-sor alá, és a kép
    # összekuszálódott. Két sorban minden szélességen olvasható marad.
    t = Table.grid(expand=True)
    t.add_column(justify="left")

    a = ctx.account() or {}
    bal = Text(APP_TITLE + "   ", style="bold")
    if a:
        bal.append(_t("console.tui.balance", balance=f"{float(a.get('balance') or 0):.2f}",
                      currency=a.get("currency") or ""))
        _nap = a.get("daily_pnl")
        if _nap is not None:
            bal.append("  ")
            bal.append(_pnl_szoveg(_nap))
    else:
        bal.append(_t("console.balance.unavailable"), style="red")

    jobb = Text()
    for cimke, ertek, rendben in cc.state_rows(ctx):
        if jobb.plain:
            jobb.append(" · ", style="dim")
        jobb.append(f"{cimke}: ", style="dim")
        jobb.append(str(ertek), style="green" if rendben else "bold red")
    t.add_row(bal)
    t.add_row(jobb)
    return t


def par_tabla(ctx: cc.Context):
    from rich.table import Table
    from rich.text import Text

    # ⚠ A SZÉLESSÉG kötött az első három oszlopon, és csak a stratégia-oszlop
    # nyúlik: `expand=True` mellett a rich egyenlően osztaná szét a helyet, és
    # egy háromkarakteres P&L ugyanakkora hasábot kapna, mint a nevek.
    t = Table(expand=True, pad_edge=False, header_style="bold")
    t.add_column(_t("console.tui.col.symbol"), no_wrap=True, width=13)
    t.add_column(_t("console.tui.col.state"), no_wrap=True, width=9)
    t.add_column(_t("console.tui.col.pnl"), justify="right", no_wrap=True, width=10)
    t.add_column(_t("console.tui.col.strategies"), ratio=1)

    for r in cc.pair_rows(ctx):
        # ⚠ A FUTÓ stratégia kiemelve, a többi halványan. A megkülönböztetés
        # ugyanaz, mint a szöveges nézet `*`-a: engedélyezett ÉS szándék=live.
        strat = Text()
        for nev, fut in r["strategies"]:
            if strat.plain:
                strat.append(", ", style="dim")
            strat.append(nev, style="bold green" if fut else "dim")
        if not strat.plain:
            strat = Text("-", style="dim")
        t.add_row(r["symbol"],
                  Text(str(r["state"]), style=_szin_allapot(r["state"])),
                  _pnl_szoveg(r["pnl"]), strat)
    return t


def pozicio_tabla(ctx: cc.Context):
    from rich.table import Table
    from rich.text import Text

    poz = cc.position_rows(ctx)
    if not poz:
        # ⚠ NEM üres táblát rajzolunk: egy fejlécekkel teli, sor nélküli tábla
        # úgy néz ki, mintha a lekérdezés nem sikerült volna. És a „nincs
        # pozíció" mondat egy 10 karakteres oszlopba nem is férne be — az
        # első nekifutásnál pontosan ez történt: „Nincs nyi…".
        from rich.console import Group
        return Group(
            Text(_t("console.tui.positions", n=0), style="bold"),
            Text("  " + _t("console.pos.none"), style="dim"),
        )
    t = Table(expand=True, pad_edge=False, header_style="bold",
              title=_t("console.tui.positions", n=len(poz)),
              title_justify="left", title_style="bold")
    for cim, jobbra, sz in ((_t("console.tui.col.ticket"), False, 10),
                            (_t("console.tui.col.symbol"), False, 13),
                            (_t("console.tui.col.dir"), False, 6),
                            (_t("console.tui.col.volume"), True, 7),
                            (_t("console.tui.col.open"), True, 12),
                            (_t("console.tui.col.sl"), True, 12),
                            (_t("console.tui.col.tp"), True, 12),
                            (_t("console.tui.col.pnl"), True, 10)):
        t.add_column(cim, justify="right" if jobbra else "left",
                     no_wrap=True, width=sz)
    for p in poz:
        _d = str(p.get("type", "")).upper()
        t.add_row(str(p.get("ticket")), str(p.get("symbol")),
                  Text(_d, style="green" if _d == "BUY" else "red"),
                  f"{float(p.get('volume') or 0):g}",
                  f"{float(p.get('price_open') or 0):g}",
                  f"{float(p.get('sl') or 0):g}" if p.get("sl") else "-",
                  f"{float(p.get('tp') or 0):g}" if p.get("tp") else "-",
                  _pnl_szoveg(p.get("profit")))
    return t


def kep(ctx: cc.Context):
    """A TELJES képernyő egyetlen renderelhető objektumként.

    ⚠ Szándékosan TISZTA FÜGGVÉNY (csak a `ctx`-ből dolgozik): így a teszt egy
    sztringbe rajzolja, és ellenőrizni tudja, MI látszik — a `Live`-hurok nélkül."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    return Group(
        Panel(fejlec(ctx), padding=(0, 1)),
        par_tabla(ctx),
        Text(),
        pozicio_tabla(ctx),
        Text(_t("console.tui.hint"), style="dim"),
    )


def fut(ctx: cc.Context, megall=None) -> None:
    """A TUI hurok. `megall()` → True esetén kilép (a hívó leállítás-kérése).

    ⚠ EZ A RÉSZ SZÁNDÉKOSAN VÉKONY, és nincs egységtesztje: egy valódi
    terminál viselkedését (billentyű, sorszerkesztés) teszttel nem lehet
    hűen utánozni. Minden, ami eldönthető — MI látszik —, a `kep()`-ben van."""
    from rich.console import Console
    from rich.live import Live

    con = Console()
    try:
        import msvcrt                              # Windows: billentyű-figyelés
    except ImportError:                            # pragma: no cover
        msvcrt = None

    while not (megall and megall()):
        with Live(kep(ctx), console=con, refresh_per_second=4,
                  screen=False, transient=False) as live:
            while not (megall and megall()):
                time.sleep(FRISSITES_MP)
                live.update(kep(ctx))
                if msvcrt is not None and msvcrt.kbhit():
                    # ⚠ Az első leütött karaktert MI olvassuk ki, különben a
                    # `input()` elé kerülne, és a felhasználó azt hinné, hogy
                    # elveszett. Ezért a promptba visszaírjuk.
                    _ch = msvcrt.getwch()
                    break
                _ch = None
            else:
                return
        if _ch in ("\r", "\n"):
            _ch = ""
        elif _ch in ("q", "Q"):
            # ⚠ A `q` NEM léptet ki azonnal: ugyanazon az úton megy, mint a
            # parancssoros `quit`, hogy a motor körhatáron álljon meg.
            _ch = "quit"
        sor = con.input(_t("console.prompt") + (_ch or ""))
        sor = (_ch or "") + sor
        res = cc.dispatch(ctx, sor)
        if res.confirm:
            valasz = con.input(_t("console.confirm", text=res.confirm))
            if valasz.strip().lower() != _t("console.confirm_yes"):
                con.print(_t("console.cancelled"), style="yellow")
                continue
            res = cc.dispatch(ctx, sor, confirmed=True)
        for ln in res.lines:
            con.print(ln, style=None if res.ok else "yellow", highlight=False)
        if res.quit:
            return
        if res.lines:
            # ⚠ A válasz maradjon a képernyőn, amíg el nem olvastad: a
            # visszatérő élő tábla különben azonnal fölé rajzolna.
            con.input(_t("console.tui.press_enter"))
