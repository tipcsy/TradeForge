"""KÖZÖS PARANCS-RÉTEG a felület nélküli futáshoz (konzol · TUI · Telegram).

⚠ MIÉRT EGY HELYEN. A konzolos mód, a TUI és (a következő körben) a Telegram
UGYANAZT a hat-hét műveletet kínálja: párok listája, pozíciók, zárás,
Play/Stop, állapot. Ha mindhárom felület a sajátját írná meg, **három forrás
romlana el külön** — ez a projekt visszatérő hibaosztálya (viz ↔ backtest
paritás, a két stratégia-lista, a warmup-mélység). Itt a szabályok EGYSZER
vannak leírva, a felületek pedig csak megjelenítenek.

⚠ ÉS A SZABÁLYOK NEM TRIVIÁLISAK. A Play/Stop mögött két olyan tanulság áll,
ami élesben került pénzbe:

  • **Csak ENGEDÉLYEZETT stratégia indítható.** A motor a `_enabled & _intent`
    szorzatot futtatja; egy nem engedélyezett stratégiánál a `run_state`
    `live`-ban ragadna a configban, a felület futónak mutatná, a motor pedig
    sosem futtatná. Némán.
  • **A „maradt-e még élő stratégia?" kérdést a MOTOR listájából kell
    megválaszolni**, nem a megjelenített listából. 2026-08-23-án az
    `available_strategies` blokkban a bollinger `false` volt (nem jelent meg
    oszlopként), a párokon viszont ENGEDÉLYEZVE volt és FUTOTT — a Stop a
    megjelenítési listát nézve arra jutott, hogy nem maradt élő stratégia, a
    szimbólumot STOPPED-re tette, és a motor a bollingert is leállította.
    Három páron, egyetlen kattintásból.

⚠ MEGERŐSÍTÉS-MINTA. A veszélyes parancsok (`close`, kivezetéssel járó `stop`)
NEM hajtódnak végre azonnal: a `Result.confirm` mezőben visszaadják, hogy MIT
csinálnának, és a hívó dönti el, hogyan kérdez rá. A konzol beír egy `i/n`-t, a
Telegram gombot tesz az üzenet alá — **a szabály viszont ugyanaz marad**, nem
a felületben lakik.

Ez a modul MT5-mentes és tkinter-mentes: mindent, ami a brókerhez nyúl, a hívó
ad át a `Context`-ben. Így hálózat és terminál nélkül tesztelhető.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core import run_state as _rs
from core.i18n import t as _t


# ---------------------------------------------------------------------------
# Eredmény és környezet
# ---------------------------------------------------------------------------

@dataclass
class Result:
    """Egy parancs kimenete. `lines`: amit ki kell írni (már fordítva).

    `confirm`: ha NEM üres, a parancs NEM hajtódott végre — a hívónak rá kell
    kérdeznie, és a parancsot `confirmed=True`-val újra kell adnia.
    `quit`: a felület fejezze be a munkát."""
    lines: list = field(default_factory=list)
    ok: bool = True
    confirm: str = ""
    quit: bool = False


@dataclass
class Context:
    """Amit a parancsoknak a külvilágból meg kell kapniuk.

    ⚠ MINDEN külső hatás hívható függvényként jön be — így a teszt egy
    szótárral és néhány lambdával lejátssza az egészet, MT5 nélkül."""
    cfg: dict
    save_config: Callable[[], bool]
    positions: Callable[[], list]
    close_position: Callable[[int], bool]
    account: Callable[[], dict]
    dashboard: dict
    instrument_state: dict
    strategies_of: Callable[[str], list]
    engine_alive: Callable[[], bool] = lambda: True
    last_cycle_ts: Callable[[], float] = lambda: 0.0
    mt5_ok: Callable[[], bool] = lambda: True
    licence_status: Callable[[], dict] = dict
    cycle_sec: float = 10.0


# ---------------------------------------------------------------------------
# Segédek
# ---------------------------------------------------------------------------

def _pairs(ctx: Context) -> dict:
    return {s: p for s, p in (ctx.cfg.get("pairs") or {}).items()
            if isinstance(p, dict)}


def _primary(ctx: Context) -> Optional[str]:
    try:
        from strategy import default_strategy_name
        return default_strategy_name(ctx.cfg)
    except Exception:
        return None


def _live_strats(ctx: Context, symbol: str) -> list:
    """A páron ÉPP FUTÓ stratégiák — `engedélyezett ÉS szándék=live`.

    ⚠ Ez a motor képlete (`_enabled & _intent`). A felület sosem mutathat
    mást, mint ami valóban fut."""
    prim = _primary(ctx)
    return [n for n in ctx.strategies_of(symbol)
            if _rs.get_state(ctx.cfg, symbol, n, prim) == _rs.LIVE]


def _has_position(ctx: Context, symbol: str) -> bool:
    ds = ctx.dashboard.get(symbol)
    if ds is not None and getattr(ds, "position_pnl", None) is not None:
        return True
    # ⚠ Tartalék: a dashboard-állapot a MOTORÉ, és fej nélküli indulás után
    # néhány körig üres lehet. A brókernél lévő pozíció viszont akkor is ott van.
    try:
        return any(str(p.get("symbol")) == symbol for p in ctx.positions())
    except Exception:
        return False


def _fmt_pos(p: dict) -> str:
    return _t("console.pos.row",
              ticket=p.get("ticket"), symbol=p.get("symbol"),
              dir=str(p.get("type", "")).upper(), volume=p.get("volume"),
              price=p.get("price_open"), pnl=f"{float(p.get('profit') or 0):+.2f}",
              sl=p.get("sl") or "-", tp=p.get("tp") or "-")


# ---------------------------------------------------------------------------
# Parancsok
# ---------------------------------------------------------------------------

def cmd_help(ctx: Context, args: list, confirmed: bool = False) -> Result:
    sorok = [_t("console.help.head")]
    for nev, kulcs in _HELP:
        sorok.append(f"  {nev:<22} {_t(kulcs)}")
    return Result(sorok)


def cmd_pairs(ctx: Context, args: list, confirmed: bool = False) -> Result:
    prim = _primary(ctx)
    sorok = [_t("console.pairs.head")]
    for sym in sorted(_pairs(ctx)):
        allapot = ctx.instrument_state.get(sym, "-")
        strats = ctx.strategies_of(sym) or []
        # ⚠ Stratégiánként MEGMUTATJUK a szándékot ÉS azt, hogy engedélyezett-e:
        # a kettő szorzata dönti el, mi fut valójában.
        cimkek = []
        for n in strats:
            el = _rs.get_state(ctx.cfg, sym, n, prim) == _rs.LIVE
            cimkek.append(f"{n}{'*' if el else ''}")
        ds = ctx.dashboard.get(sym)
        pnl = getattr(ds, "position_pnl", None) if ds is not None else None
        sorok.append(_t("console.pairs.row", symbol=sym, state=allapot,
                        strategies=", ".join(cimkek) or "-",
                        pnl=("-" if pnl is None else f"{float(pnl):+.2f}")))
    sorok.append(_t("console.pairs.legend"))
    return Result(sorok)


def cmd_pos(ctx: Context, args: list, confirmed: bool = False) -> Result:
    poz = ctx.positions() or []
    if not poz:
        return Result([_t("console.pos.none")])
    sorok = [_t("console.pos.head", n=len(poz))]
    sorok += [_fmt_pos(p) for p in poz]
    try:
        ossz = sum(float(p.get("profit") or 0) for p in poz)
        sorok.append(_t("console.pos.total", pnl=f"{ossz:+.2f}"))
    except (TypeError, ValueError):
        pass
    return Result(sorok)


def cmd_close(ctx: Context, args: list, confirmed: bool = False) -> Result:
    if not args:
        return Result([_t("console.close.usage")], ok=False)
    poz = ctx.positions() or []
    if str(args[0]).lower() == "all":
        cel = list(poz)
        leiras = _t("console.close.confirm_all", n=len(cel))
    else:
        try:
            ticket = int(args[0])
        except ValueError:
            return Result([_t("console.close.usage")], ok=False)
        cel = [p for p in poz if int(p.get("ticket") or 0) == ticket]
        if not cel:
            return Result([_t("console.close.unknown", ticket=ticket)], ok=False)
        leiras = _t("console.close.confirm_one", ticket=ticket,
                    symbol=cel[0].get("symbol"))
    if not cel:
        return Result([_t("console.pos.none")])
    if not confirmed:
        return Result(confirm=leiras)
    # ⚠ A ZÁRÁS NEM ÁLLÍTJA LE A STRATÉGIÁT. A motor a következő jelre újra
    # nyithat — ha ezt nem mondjuk meg, a felhasználó azt hiszi, „kiszállt".
    sorok, hiba = [], 0
    for p in cel:
        t = int(p.get("ticket") or 0)
        if ctx.close_position(t):
            sorok.append(_t("console.close.done", ticket=t))
        else:
            hiba += 1
            sorok.append(_t("console.close.failed", ticket=t))
    sorok.append(_t("console.close.note"))
    return Result(sorok, ok=(hiba == 0))


def cmd_play(ctx: Context, args: list, confirmed: bool = False) -> Result:
    if not args:
        return Result([_t("console.play.usage")], ok=False)
    sym = _resolve_symbol(ctx, args[0])
    if sym is None:
        return Result([_t("console.unknown_pair", symbol=args[0])], ok=False)
    engedett = ctx.strategies_of(sym) or []
    kert = [args[1]] if len(args) > 1 else list(engedett)
    if not kert:
        return Result([_t("console.play.no_strategy", symbol=sym)], ok=False)

    sorok, indult = [], []
    for n in kert:
        # ⚠ A NEM ENGEDÉLYEZETT stratégia NEM indítható — különben a szándék
        # `live`-ban ragadna, miközben a motor sosem futtatná.
        if n not in engedett:
            sorok.append(_t("console.play.not_enabled", symbol=sym, name=n))
            continue
        _rs.set_state(ctx.cfg, sym, n, _rs.LIVE)
        indult.append(n)
    if not indult:
        return Result(sorok, ok=False)
    mentve = ctx.save_config()
    if ctx.instrument_state.get(sym) != "LIVE":
        ctx.instrument_state[sym] = "LIVE"
    sorok.append(_t("console.play.started", symbol=sym, names=", ".join(indult)))
    if not mentve:
        # ⚠ A stratégia MOST elindul (a motor ugyanabból a dictből olvas), de a
        # SZÁNDÉK nem perzisztált — újraindítás után nem folytatódna.
        sorok.append(_t("console.not_saved"))
    return Result(sorok, ok=mentve)


def cmd_stop(ctx: Context, args: list, confirmed: bool = False) -> Result:
    if not args:
        return Result([_t("console.stop.usage")], ok=False)
    sym = _resolve_symbol(ctx, args[0])
    if sym is None:
        return Result([_t("console.unknown_pair", symbol=args[0])], ok=False)
    engedett = ctx.strategies_of(sym) or []
    kert = [args[1]] if len(args) > 1 else list(engedett)
    if not kert:
        # ⚠ Ne jelentsünk sikeres leállítást, ha nem volt mit leállítani —
        # a „leállítva — -" sor azt sugallná, hogy történt valami.
        return Result([_t("console.play.no_strategy", symbol=sym)], ok=False)

    # Mi maradna élőben, ha ezeket leállítjuk?
    marad = [n for n in _live_strats(ctx, sym) if n not in kert]
    nyitott = _has_position(ctx, sym)
    # ⚠ KIVEZETÉS: ha ez volt az utolsó élő stratégia ÉS van nyitott pozíció, a
    # pár nem STOPPED lesz, hanem CLOSING — a motor tovább kezeli a pozíciót
    # (BE, trailing, kiszállás), de új belépőt nem nyit. A felhasználónak ezt
    # tudnia kell, mielőtt igent mond.
    if not marad and nyitott and not confirmed:
        return Result(confirm=_t("console.stop.confirm_closing", symbol=sym))

    for n in kert:
        _rs.set_state(ctx.cfg, sym, n, _rs.STOPPED)
    mentve = ctx.save_config()
    sorok = [_t("console.stop.stopped", symbol=sym, names=", ".join(kert) or "-")]
    if marad:
        sorok.append(_t("console.stop.still_live", names=", ".join(marad)))
    elif nyitott:
        ctx.instrument_state[sym] = "CLOSING"
        sorok.append(_t("console.stop.closing", symbol=sym))
    else:
        ctx.instrument_state[sym] = "STOPPED"
        sorok.append(_t("console.stop.pair_stopped", symbol=sym))
    if not mentve:
        sorok.append(_t("console.not_saved"))
    return Result(sorok, ok=mentve)


def cmd_balance(ctx: Context, args: list, confirmed: bool = False) -> Result:
    a = ctx.account() or {}
    if not a:
        return Result([_t("console.balance.unavailable")], ok=False)
    _nap = a.get("daily_pnl")
    return Result([_t("console.balance.row",
                      balance=f"{float(a.get('balance') or 0):.2f}",
                      currency=a.get("currency") or "",
                      daily=("?" if _nap is None else f"{float(_nap):+.2f}"))])


def cmd_state(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """A motor ÉLETJELE — az öt sor, amiből a „minden rendben" áll.

    ⚠ Egy zöld pipa, ami nem néz semmit, rosszabb a semminél: azt sugallná,
    hogy ellenőriztük. Ezért minden sor MÉRT értéket mutat."""
    sorok = [_t("console.state.head")]
    el = bool(ctx.engine_alive())
    sorok.append(_t("console.state.thread",
                    value=_t("console.yes") if el else _t("console.no")))
    ts = float(ctx.last_cycle_ts() or 0)
    if ts <= 0:
        sorok.append(_t("console.state.cycle_none"))
    else:
        kor = max(0.0, time.time() - ts)
        # ⚠ A küszöb a ciklusidő HÁROMSZOROSA: egy-egy elnyúló kör (mély
        # adatablak, lassú bróker) még nem baj, a tartós elmaradás igen.
        sorok.append(_t("console.state.cycle", sec=f"{kor:.0f}",
                        flag=("" if kor <= 3 * ctx.cycle_sec
                              else " " + _t("console.state.late"))))
    sorok.append(_t("console.state.mt5",
                    value=_t("console.yes") if ctx.mt5_ok() else _t("console.no")))
    lic = ctx.licence_status() or {}
    if lic:
        sorok.append(_t("console.state.licence",
                        state=lic.get("allapot", "?"),
                        days=lic.get("lejar_nap", "?")))
    elo = [s for s in sorted(_pairs(ctx)) if _live_strats(ctx, s)]
    sorok.append(_t("console.state.pairs", n=len(elo),
                    names=", ".join(elo) or "-"))
    return Result(sorok)


def cmd_quit(ctx: Context, args: list, confirmed: bool = False) -> Result:
    return Result([_t("console.quit")], quit=True)


def _resolve_symbol(ctx: Context, name: str) -> Optional[str]:
    """Kis/nagybetűtől független pár-feloldás — a `ger40` is találjon."""
    parok = _pairs(ctx)
    if name in parok:
        return name
    kicsi = str(name).lower()
    for s in parok:
        if s.lower() == kicsi:
            return s
    return None


# ---------------------------------------------------------------------------
# Elosztó
# ---------------------------------------------------------------------------

# ⚠ A parancsnevek ANGOLUL (a felhasználó döntése): telefonon és SSH-n is
# gépelhetők, és a Telegram parancs-listájába változtatás nélkül átvihetők.
# A VÁLASZOK viszont a katalógusból jönnek, tehát a beállított nyelven szólnak.
COMMANDS: dict = {
    "help":    cmd_help,
    "pairs":   cmd_pairs,
    "pos":     cmd_pos,
    "close":   cmd_close,
    "play":    cmd_play,
    "stop":    cmd_stop,
    "balance": cmd_balance,
    "state":   cmd_state,
    "quit":    cmd_quit,
}

ALIASES: dict = {"?": "help", "h": "help", "list": "pairs", "p": "pos",
                 "positions": "pos", "exit": "quit", "q": "quit"}

_HELP = (
    ("help", "console.help.help"),
    ("pairs", "console.help.pairs"),
    ("pos", "console.help.pos"),
    ("close <ticket>|all", "console.help.close"),
    ("play <pár> [stratégia]", "console.help.play"),
    ("stop <pár> [stratégia]", "console.help.stop"),
    ("balance", "console.help.balance"),
    ("state", "console.help.state"),
    ("quit", "console.help.quit"),
)


def dispatch(ctx: Context, line: str, confirmed: bool = False) -> Result:
    """Egy beírt sor végrehajtása. Ismeretlen parancsnál SEGÍT, nem hallgat."""
    parts = str(line or "").strip().split()
    if not parts:
        return Result([])
    nev = parts[0].lower().lstrip("/")          # a Telegram `/pos` alakja is jó
    nev = ALIASES.get(nev, nev)
    fn = COMMANDS.get(nev)
    if fn is None:
        return Result([_t("console.unknown_command", name=parts[0])], ok=False)
    return fn(ctx, parts[1:], confirmed)


def live_context(cfg: dict, config_path) -> Context:
    """A VALÓDI környezet — a motor és az MT5 bekötve.

    ⚠ Itt és csak itt van MT5-függés; a parancsok maguk nem ismerik."""
    from core import licence, mt5_connector
    from strategy import enabled_strategy_names
    from strategy.settings import save_main_config
    from trading import live_trader as lt

    def _mentes() -> bool:
        try:
            save_main_config(cfg, config_path)
            return True
        except Exception:
            return False

    def _szamla() -> dict:
        try:
            b = mt5_connector.account_balance()
            if not b:
                return {}
            return {"balance": b, "currency": mt5_connector.account_currency(),
                    "daily_pnl": mt5_connector.daily_pnl_cached()}
        except Exception:
            return {}

    return Context(
        cfg=cfg,
        save_config=_mentes,
        # ⚠ A KÖZÖS forrás: ugyanaz a lista, amit a Pozíciók fül mutat — így a
        # konzol és a felület nem tud eltérő képet adni ugyanarról a számláról.
        positions=mt5_connector.open_positions_detailed,
        close_position=lambda t: bool(mt5_connector.close_position(t)),
        account=_szamla,
        dashboard=lt.dashboard,
        instrument_state=lt.instrument_state,
        strategies_of=lambda s: enabled_strategy_names(cfg, s) or [],
        engine_alive=lt.engine_alive,
        last_cycle_ts=lambda: lt.last_cycle_ts,
        mt5_ok=lambda: bool(mt5_connector.is_connected()),
        licence_status=licence.status,
    )
