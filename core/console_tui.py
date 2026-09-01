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


def par_tabla(ctx: cc.Context, max_sor: "int | None" = None, sorok=None):
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

    _sorok = cc.pair_rows(ctx) if sorok is None else list(sorok)
    # ⚠ AMI NEM FÉR KI, AZ NE TOLJA SZÉT A KÉPET. Egy a képernyőnél magasabb
    # élő terület nem frissíthető helyben — a rich ilyenkor törli és újrarajzol,
    # ami LÁTHATÓAN ugrál. Inkább levágjuk, és MEGMONDJUK, mennyi maradt ki.
    _kimaradt = 0
    if max_sor is not None and len(_sorok) > max_sor:
        _kimaradt = len(_sorok) - max_sor + 1
        _sorok = _sorok[:max_sor - 1]
    for r in _sorok:
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
    if _kimaradt:
        t.add_row(Text(_t("console.tui.more", n=_kimaradt), style="dim"),
                  "", "", "")
    return t


def pozicio_tabla(ctx: cc.Context, max_sor: "int | None" = None, sorok=None):
    from rich.table import Table
    from rich.text import Text

    _mind = cc.position_rows(ctx) if sorok is None else list(sorok)
    poz = _mind
    _kimaradt = 0
    if max_sor is not None and len(poz) > max_sor:
        _kimaradt = len(poz) - max_sor + 1
        poz = poz[:max_sor - 1]
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
              title=_t("console.tui.positions", n=len(_mind)),
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
    if _kimaradt:
        t.add_row(Text(_t("console.tui.more", n=_kimaradt), style="dim"),
                  *[""] * 7)
    return t


# A kép ÁLLANDÓ része sorokban: fejléc (2) + a pár-tábla kerete és fejléce (4)
# + pozíció-cím (1) + a pozíció-tábla kerete és fejléce (4) + tipp-sor (1) +
# egy sor tartalék. Ebből jön ki, hány ADATSOR fér ki.
#
# ⚠ A fejléc körül KORÁBBAN keret volt, a két tábla között üres sor: együtt
# három sor, ami 24 soros terminálon három instrumentummal kevesebbet
# jelentett. Egy teli képernyőn a tartalom többet ér a díszítésnél.
KERET_SOR = 13


def _sor_keret(magassag: int, n_par: int, n_poz: int) -> tuple:
    """Hány pár- és hány pozíció-sor fér ki `magassag` sorba? `(pár, pozíció)`.

    ⚠ A POZÍCIÓ AZ ELSŐBB: abból általában kevés van, és az a fontosabb — valódi
    pénz van benne. A pár-listát vágjuk, mert ott a lényeg úgyis a néhány aktív
    sor, és a `pairs` paranccsal bármikor kilistázható az egész."""
    hely = max(4, int(magassag) - KERET_SOR)
    poz = min(n_poz, max(2, hely // 2))
    par = max(3, hely - poz)
    return par, poz


def kep(ctx: cc.Context, magassag: "int | None" = None):
    """A TELJES képernyő egyetlen renderelhető objektumként.

    `magassag`: a terminál sorainak száma. ⚠ NEM DÍSZ. Ha a kép MAGASABB a
    képernyőnél, a rich nem tudja helyben frissíteni az élő területet, hanem
    törli és újrarajzolja az egészet — ezt látja a felhasználó „ugrálásként"
    (15 instrumentumnál jelentkezett). A magasság ismeretében levágjuk, ami nem
    fér ki, és MEGMONDJUK, mennyi maradt le.

    ⚠ Szándékosan TISZTA FÜGGVÉNY (csak a `ctx`-ből dolgozik): így a teszt egy
    sztringbe rajzolja, és ellenőrizni tudja, MI látszik — a `Live`-hurok nélkül."""
    from rich.console import Group
    from rich.text import Text

    # ⚠ EGYSZER kérdezzük le, és úgy adjuk tovább. A sor-keret számításához és
    # a rajzoláshoz is kell a lista; külön lekérdezve a POZÍCIÓK kétszer jönnének
    # le az MT5-ből minden képnél (és az `open_positions_detailed` pozíciónként
    # egy `symbol_info`-t is kér). A kijelzés-út terhelése ebben a projektben már
    # okozott GIL-fogást — ne termeljünk feleslegeset.
    _parok = cc.pair_rows(ctx)
    _pozok = cc.position_rows(ctx)
    _par = _poz = None
    if magassag:
        _par, _poz = _sor_keret(magassag, len(_parok), len(_pozok))
    return Group(
        fejlec(ctx),
        par_tabla(ctx, _par, _parok),
        pozicio_tabla(ctx, _poz, _pozok),
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
        # ⚠ `screen=True` — KÜLÖN képernyő-puffer (mint a `less` vagy a `top`).
        # Enélkül a rich a görgethető kimenetbe rajzol, és egy a terminálnál
        # MAGASABB kép frissítésekor törölni + újrarajzolni kényszerül: pontosan
        # ez az „ugrálás", amit 15 instrumentumnál látni lehetett. Kilépéskor a
        # képernyő visszaáll, tehát a parancsok kimenete a megszokott,
        # görgethető területre megy.
        #
        # ⚠ `auto_refresh=False` — MI mondjuk meg, mikor rajzoljon. A 4/mp-es
        # automatikus frissítés VÁLTOZATLAN tartalmat is újrarajzolt, tehát
        # nyolcszor annyit dolgozott, mint amennyi látszott belőle.
        with Live(kep(ctx, con.size.height), console=con, screen=True,
                  auto_refresh=False, transient=False) as live:
            _ch = None
            _utolso = 0.0
            while not (megall and megall()):
                if time.monotonic() - _utolso >= FRISSITES_MP:
                    live.update(kep(ctx, con.size.height), refresh=True)
                    _utolso = time.monotonic()
                if msvcrt is not None and msvcrt.kbhit():
                    # ⚠ Az első leütött karaktert MI olvassuk ki, különben a
                    # `input()` elé kerülne, és a felhasználó azt hinné, hogy
                    # elveszett. Ezért a promptba visszaírjuk.
                    _ch = msvcrt.getwch()
                    break
                # ⚠ SŰRŰN figyelünk billentyűre, RITKÁN rajzolunk. Korábban a
                # kettő egy ütemen ment (2 mp), tehát a leütésre akár két
                # másodpercet is várni kellett — az elakadásnak látszott.
                time.sleep(0.05)
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
