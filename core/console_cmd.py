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

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core import opt_activity as _oa
from core import run_state as _rs
from core import trade_mode as _tm
from core.i18n import t as _t

log = logging.getLogger(__name__)


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
    cycle_work: Callable[[], tuple] = lambda: (0.0, 0.0)
    # A MAI kereskedési sorok (`trades.csv`): `[{event, symbol, strategy,
    # direction, pnl_usd, …}]`. ⚠ Ugyanabból a naplóból, amiből a Telegram-
    # üzenetek is mennek — így a napi összesítő és az egyedi értesítések nem
    # tudnak eltérő képet adni ugyanarról a napról.
    today_rows: Callable[[], list] = list
    cycle_sec: float = 10.0
    # A mentett paraméterkészlet megléte: `"tuned"` | `"default"` | `""` (nem tudjuk).
    # ⚠ FÜGGVÉNYKÉNT, mert a `live_trader.params_source` MT5-öt importáló modulban
    # lakik — a parancs-réteg viszont MT5-mentes marad. Aki nem köti be, annál a
    # hangolatlan indulás jelzése egyszerűen elmarad (nem hazudik, csak hallgat).
    params_source: Callable[[str, str], str] = lambda s, n: ""


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


# ---------------------------------------------------------------------------
# STRUKTURÁLT SOROK — a szöveges parancs ÉS a TUI ugyanezekből dolgozik
# ---------------------------------------------------------------------------
# ⚠ MIÉRT NEM A SZÖVEGET PARSZOLJA A TUI. A parancsok fordított, tördelt sorokat
# adnak vissza; egy táblázatnak viszont MEZŐK kellenek. Ha a TUI a saját
# lekérdezését írná meg, két helyen kellene karbantartani ugyanazt a szabályt
# (mikor „fut" egy stratégia, mi a pár állapota) — és a kettő elcsúszna. Ezért a
# lekérdezés itt van egyszer, és a megjelenítés (szöveg vagy táblázat) külön.

def pair_rows(ctx: Context) -> list:
    """Instrumentumonként: `{symbol, state, pnl, strategies: [(név, fut-e)]}`."""
    prim = _primary(ctx)
    out = []
    for sym in sorted(_pairs(ctx)):
        ds = ctx.dashboard.get(sym)
        out.append({
            "symbol": sym,
            "state": ctx.instrument_state.get(sym, "-"),
            "pnl": (getattr(ds, "position_pnl", None) if ds is not None else None),
            "strategies": [
                (n, _rs.get_state(ctx.cfg, sym, n, prim) == _rs.LIVE)
                for n in (ctx.strategies_of(sym) or [])
            ],
        })
    return out


def position_rows(ctx: Context) -> list:
    try:
        return list(ctx.positions() or [])
    except Exception:
        # ⚠ A brókeri lekérdezés elbukhat (kapcsolat) — ilyenkor ÜRES lista megy
        # tovább, de a `state` sor megmondja, hogy nincs MT5-kapcsolat. Egy
        # kivétel itt az egész kijelzést elvinné.
        return []


def state_rows(ctx: Context) -> list:
    """`[(címke, érték, rendben-e)]` — a motor életjele mezőnként.

    ⚠ Egy zöld pipa, ami nem néz semmit, rosszabb a semminél. Minden sor MÉRT
    értéket ad vissza, és a harmadik elem mondja meg, hogy az érték rendben
    van-e — a megjelenítés ebből színez."""
    out = []
    el = bool(ctx.engine_alive())
    out.append((_t("console.state.thread"),
                _t("console.yes") if el else _t("console.no"), el))
    ts = float(ctx.last_cycle_ts() or 0)
    if ts <= 0:
        out.append((_t("console.state.cycle"), "-", False))
    else:
        kor = max(0.0, time.time() - ts)
        out.append((_t("console.state.cycle"), f"{kor:.0f} mp",
                    kor <= 3 * ctx.cycle_sec))
    # ⚠ A KÖR KORA ÉS A KÖR MUNKAIDEJE KÉT KÜLÖNBÖZŐ DOLOG. A kor a 10 mp-es
    # várakozás miatt 0 és 10 között hullámzik — abból NEM derül ki, mennyit
    # dolgozott a motor. Épp ez a szám kell, amikor a felület költségét mérjük
    # (a kijelzés-út egyszer már GIL-fogást okozott: 7,64 → 0,31 mp/kör).
    _atl, _max = ctx.cycle_work()
    if _atl > 0:
        out.append((_t("console.state.work"),
                    _t("console.state.work_val", avg=f"{_atl:.2f}",
                       max=f"{_max:.2f}"),
                    _atl < ctx.cycle_sec))
    _mt5 = bool(ctx.mt5_ok())
    out.append((_t("console.state.mt5"),
                _t("console.yes") if _mt5 else _t("console.no"), _mt5))
    lic = ctx.licence_status() or {}
    if lic:
        out.append((_t("console.state.licence"),
                    f"{lic.get('allapot', '?')} ({lic.get('lejar_nap', '?')})",
                    str(lic.get("allapot")) == "ok"))
    return out


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
    sorok = [_t("console.pairs.head")]
    for r in pair_rows(ctx):
        # ⚠ Stratégiánként MEGJELÖLJÜK, ami FUT (engedélyezett ÉS szándék=live):
        # a kettő szorzata dönti el, mi fut valójában.
        cimkek = [f"{n}{'*' if fut else ''}" for n, fut in r["strategies"]]
        sorok.append(_t("console.pairs.row", symbol=r["symbol"],
                        state=r["state"],
                        strategies=", ".join(cimkek) or "-",
                        pnl=("-" if r["pnl"] is None
                             else f"{float(r['pnl']):+.2f}")))
    sorok.append(_t("console.pairs.legend"))
    return Result(sorok)


def cmd_pos(ctx: Context, args: list, confirmed: bool = False) -> Result:
    poz = position_rows(ctx)
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


# ---------------------------------------------------------------------------
# INDÍTÁS / LEÁLLÍTÁS — a szabályok EGY helyen, felülettől függetlenül
# ---------------------------------------------------------------------------
# ⚠ MIÉRT VAN A PARANCS MÖGÖTT KÜLÖN FÜGGVÉNY. A `cmd_play`/`cmd_stop` SZÖVEGET
# bont (`play EURUSD wpr_sma`); a grafikus felület viszont már tudja, melyik
# cellára kattintottak — neki nincs mit parszolnia. Amíg csak parancs volt, a
# GUI a saját másolatát írta meg, és a két oldal EL IS CSÚSZOTT:
#
#   • az OPTIMALIZÁLÁS alatti indítást a felület tiltotta, a konzol/TUI/Telegram
#     engedte — pedig a futás végén a stratégia paraméterfájlja íródik felül;
#   • a hangolatlan (alapértelmezett paraméteres) indulást a felület kiírta, a
#     parancs-réteg nem — ugyanaz a néma állapot, amit a projekt máshol
#     következetesen kigyomlál;
#   • a KIVEZETÉS-figyelmeztetésre a parancs rákérdezett, a felület nem.
#
# A szabály ezért itt lakik, a parancs pedig már csak argumentumot bont.


def start_strategies(ctx: Context, symbol: str, names: list) -> Result:
    """A megadott stratégiák indítása ezen a páron (a szándék `live`).

    Két dolgot utasít el — MINDKETTŐT INDOKKAL, mert a néma `return` a hívónak
    sikernek látszik:

      • ami NINCS engedélyezve a páron: a motor a `_enabled & _intent` szorzatot
        futtatja, tehát a szándék `live`-ban ragadna, miközben sosem futna;
      • amin ÉPP OPTIMALIZÁLÁS fut: a futás végén a paraméterfájlja íródna felül
        az alól a stratégia alól, amelyik közben kereskedik.

    ⚠ MENTETT KÉSZLET NÉLKÜL IS INDULHAT — a stratégia SAJÁT alapértékeivel
    (`live_trader.default_params`). Egy tiltás egy ÚJ stratégiát minden páron
    használhatatlanná tenne, amíg le nem fut rá egy több órás optimalizálás.
    De nem is némán: kiírjuk, hogy hangolatlanul indul."""
    engedett = ctx.strategies_of(symbol) or []
    kert = [n for n in (names or []) if n]
    if not kert:
        return Result([_t("console.play.no_strategy", symbol=symbol)], ok=False)

    sorok, indult = [], []
    for n in kert:
        if n not in engedett:
            sorok.append(_t("console.play.not_enabled", symbol=symbol, name=n))
            continue
        if _oa.busy(symbol, n):
            sorok.append(_t("console.play.opt_running", symbol=symbol, name=n))
            continue
        # ⚠ A KAPUK AZ ÁLLAPOT-ÍRÁS ELŐTT vannak — különben a `run_state` egy
        # olyan stratégiára ragadna `live`-ban, amit a motor nem futtat.
        _rs.set_state(ctx.cfg, symbol, n, _rs.LIVE)
        indult.append(n)
        try:
            if ctx.params_source(symbol, n) == "default":
                sorok.append(_t("console.play.default_params", symbol=symbol, name=n))
        except Exception:
            # A jelzés hiánya nem ok arra, hogy az indítás elbukjon.
            pass
    if not indult:
        return Result(sorok, ok=False)

    mentve = ctx.save_config()
    if ctx.instrument_state.get(symbol) != "LIVE":
        ctx.instrument_state[symbol] = "LIVE"
    sorok.append(_t("console.play.started", symbol=symbol, names=", ".join(indult)))
    if not mentve:
        # ⚠ A stratégia MOST elindul (a motor ugyanabból a dictből olvas), de a
        # SZÁNDÉK nem perzisztált — újraindítás után nem folytatódna.
        sorok.append(_t("console.not_saved"))
    return Result(sorok, ok=mentve)


def stop_strategies(ctx: Context, symbol: str, names: list,
                    confirmed: bool = False) -> Result:
    """A megadott stratégiák leállítása ezen a páron (a szándék `stopped`).

    ⚠ A „MARADT-E MÉG ÉLŐ STRATÉGIA?" KÉRDÉST A MOTOR LISTÁJÁBÓL kell
    megválaszolni (`ctx.strategies_of` → `pairs.<sym>.strategies`), nem a
    megjelenített listából. 2026-08-23-án az `available_strategies` blokkban a
    bollinger `false` volt (nem kapott oszlopot), a párokon viszont ENGEDÉLYEZVE
    volt és FUTOTT: a megjelenítési listát nézve a Stop arra jutott, hogy nem
    maradt élő stratégia, a szimbólumot STOPPED-re tette, és a motor a bollingert
    is leállította — három páron, egyetlen kattintásból.

    ⚠ KIVEZETÉS: ha ez volt az utolsó élő stratégia ÉS van nyitott pozíció, a pár
    nem STOPPED lesz, hanem CLOSING — a motor tovább kezeli a pozíciót (BE,
    trailing, kiszállás), de új belépőt nem nyit. Ezt a hívónak MEG KELL
    KÉRDEZNIE: `Result.confirm` jön vissza, és a parancsot `confirmed=True`-val
    kell megismételni."""
    kert = [n for n in (names or []) if n]
    if not kert:
        # ⚠ Ne jelentsünk sikeres leállítást, ha nem volt mit leállítani —
        # a „leállítva — -" sor azt sugallná, hogy történt valami.
        return Result([_t("console.play.no_strategy", symbol=symbol)], ok=False)

    marad = [n for n in _live_strats(ctx, symbol) if n not in kert]
    nyitott = _has_position(ctx, symbol)
    if not marad and nyitott and not confirmed:
        return Result(confirm=_t("console.stop.confirm_closing", symbol=symbol))

    for n in kert:
        _rs.set_state(ctx.cfg, symbol, n, _rs.STOPPED)
    mentve = ctx.save_config()
    sorok = [_t("console.stop.stopped", symbol=symbol, names=", ".join(kert) or "-")]
    if marad:
        sorok.append(_t("console.stop.still_live", names=", ".join(marad)))
    elif nyitott:
        ctx.instrument_state[symbol] = "CLOSING"
        sorok.append(_t("console.stop.closing", symbol=symbol))
    else:
        ctx.instrument_state[symbol] = "STOPPED"
        sorok.append(_t("console.stop.pair_stopped", symbol=symbol))
    if not mentve:
        # ⚠ A leállítás MOST érvényes, de a szándék nem perzisztált —
        # újraindítás után a stratégia visszaindulna.
        sorok.append(_t("console.not_saved"))
    return Result(sorok, ok=mentve)


def cmd_play(ctx: Context, args: list, confirmed: bool = False) -> Result:
    if not args:
        return Result([_t("console.play.usage")], ok=False)
    sym = _resolve_symbol(ctx, args[0])
    if sym is None:
        return Result([_t("console.unknown_pair", symbol=args[0])], ok=False)
    # Stratégia nélkül: a pár ÖSSZES engedélyezett stratégiája.
    names = [args[1]] if len(args) > 1 else list(ctx.strategies_of(sym) or [])
    return start_strategies(ctx, sym, names)


def cmd_stop(ctx: Context, args: list, confirmed: bool = False) -> Result:
    if not args:
        return Result([_t("console.stop.usage")], ok=False)
    sym = _resolve_symbol(ctx, args[0])
    if sym is None:
        return Result([_t("console.unknown_pair", symbol=args[0])], ok=False)
    names = [args[1]] if len(args) > 1 else list(ctx.strategies_of(sym) or [])
    return stop_strategies(ctx, sym, names, confirmed=confirmed)


# ---------------------------------------------------------------------------
# KÖTÉS-MÓD (valódi kötés ↔ csak jelzés)
# ---------------------------------------------------------------------------
# ⚠ EZ A LEGDRÁGÁBB KAPCSOLÓ A RENDSZERBEN. A `signal` → `live` váltás után a
# motor a KÖVETKEZŐ jelnél VALÓDI MEGBÍZÁST küld a számlára. Eddig egyetlen
# helyen lehetett átállítani (a beállítás-ablak legördülője), tehát nem volt két
# forrás — de épp ezért nem is volt SEMMILYEN közös szabály mögötte:
#
#   • egyetlen instrumentum mentésénél a felület MEG SEM KÉRDEZTE, hogy most
#     kapcsoltál be valódi kötést (a „minden instrumentumra" ág kérdezett csak);
#   • a nem engedélyezett stratégián beállított mód némán hatástalan;
#   • a nyitott pozíció sorsáról (a motor tovább kezeli) sehol nem esett szó.
#
# A karmesternek EZ lesz a legfontosabb akciója (`signal` ↔ `live` léptetés az
# életciklus-létrán), ezért a szabály ide került — egy helyre, ahol a felület, a
# konzol és a karmester is ugyanazon megy át.
#
# ⚠ A TELEGRAM SZÁNDÉKOSAN NEM KAPJA MEG. A `telegram_cmd.ENGEDETT` engedélyező
# lista — a `close` és a `quit` sincs benne. Egy chatüzenetből bekapcsolható
# valódi kötés ugyanabba a kategóriába tartozik.


def _tarolt_mod(cfg: dict, symbol: str, name: str):
    """A configban TÉNYLEGESEN tárolt nyers érték (vagy `None`, ha nincs).

    A `trade_mode.mode_of` értelmez (mindent `live`-nak olvas, amit nem ismer);
    ide az kell, ami ODA VAN ÍRVA — ebből derül ki az érvénytelen maradék."""
    pc = (cfg.get("pairs") or {}).get(symbol)
    per = pc.get("strategy_mode") if isinstance(pc, dict) else None
    return per.get(name) if isinstance(per, dict) else None


def mode_changes(ctx: Context, symbol: str, names: list, mode: str) -> list:
    """Mely stratégiák módja VÁLTOZNA meg ténylegesen → `[(név, régi_mód)]`.

    TISZTA: nem ír semmit. A hívó ebből építi a megerősítő kérdést — és ebből
    tudja, hogy van-e egyáltalán mit kérdezni (a már `live` módú stratégiára
    rákérdezni zaj)."""
    out = []
    for n in (names or []):
        if not n:
            continue
        regi = _tm.mode_of(ctx.cfg, symbol, n)
        if regi != mode:
            out.append((n, regi))
    return out


def set_trade_mode(ctx: Context, symbol: str, names: list, mode: str,
                   confirmed: bool = False, save: bool = True) -> Result:
    """A kötés-mód beállítása `(pár × stratégia)` szinten.

    `mode`: ``"live"`` (valódi megbízás) vagy ``"signal"`` (csak jelzés).

    ⚠ A `live` IRÁNY MEGERŐSÍTÉST KÉR — de csak akkor, ha tényleg VÁLTOZIK
    valami. Ugyanaz a minta, mint a kivezetéssel járó `stop`-nál: `Result.confirm`
    jön vissza, a hívó megkérdezi, és `confirmed=True`-val megismétli. A `signal`
    irány nem kérdez: az a biztonságos oldal.

    ⚠ `save=False`: a hívó VÁLLALJA a perzisztálást. A beállítás-ablak több sort
    alkalmaz egyszerre, akár tíz instrumentumra, és a végén ment EGYSZER — ott egy
    beágyazott mentés nemcsak fölösleges írás lenne, hanem egy félbeszakadt
    tömeges alkalmazást is lemezre vinne. Ilyenkor az `ok` csak az ÍRÁSRA
    vonatkozik, a `console.not_saved` sor pedig elmarad."""
    if mode not in _tm.MODES:
        return Result([_t("console.mode.unknown", mode=mode)], ok=False)

    kert = [n for n in (names or []) if n]
    if not kert:
        return Result([_t("console.play.no_strategy", symbol=symbol)], ok=False)

    valtozo = mode_changes(ctx, symbol, kert, mode)

    # ⚠ ÉRVÉNYTELEN MARADÉK-ÉRTÉK. A `mode_of` MINDEN ismeretlen értéket `live`-nak
    # olvas (biztonságos alapértelmezés), tehát egy elgépelt `"Signal"` a configban
    # NEM okoz hibát — csak épp ott áll egy sor, ami valódi eltérést sugall,
    # miközben a motor figyelmen kívül hagyja. Pontosan az a néma állapot, amit a
    # `set_mode` takarítása (a `live` TÖRLI a kulcsot) megelőz — csak oda kell
    # engedni, akkor is, ha a mód „nem változik".
    szemet = [n for n in kert if _tarolt_mod(ctx.cfg, symbol, n)
              not in (None, _tm.MODE_SIGNAL)]
    if not valtozo and not szemet:
        return Result([_t("console.mode.nochange", symbol=symbol,
                          names=", ".join(kert), mode=_tm.LABELS.get(mode, mode))])

    # ⚠ CSAK A VÁLTOZÓKRA kérdezünk rá, és csak a PÉNZT BEKAPCSOLÓ irányban.
    # ⚠ CSAK VALÓDI VÁLTÁSRA kérdezünk: ha `valtozo` üres (pl. csak takarítás
    # miatt jutottunk idáig), nincs mit megerősíteni — egy üres kérdés zaj.
    if mode == _tm.MODE_LIVE and valtozo and not confirmed:
        return Result(confirm=_t("console.mode.confirm_live", symbol=symbol,
                                 names=", ".join(n for n, _ in valtozo)))

    engedett = ctx.strategies_of(symbol) or []
    sorok = []
    # ⚠ AZ ÍRÁS MINDEN KÉRT STRATÉGIÁRA MEGY, nem csak a változókra. A
    # `trade_mode.set_mode` idempotens ÉS takarít is (`live`-nál TÖRLI a kulcsot,
    # hogy a `strategy_mode` jelenléte mindig valódi eltérést jelentsen). Ha csak
    # a „változókra" hívnánk, egy érvénytelen maradék-érték (amit a `mode_of`
    # amúgy is `live`-nak olvas) bennragadna a fájlban — pont az a néma
    # állapot, amit a takarítás megelőz. A `valtozo` csak a KÉRDÉSHEZ és a
    # JELENTÉSHEZ kell.
    for n in kert:
        _tm.set_mode(ctx.cfg, symbol, n, mode)
    for n, _regi in valtozo:
        # ⚠ NEM TILTÁS, CSAK JELZÉS: a nem engedélyezett stratégián a beállítás
        # eltárolódik és később érvényes lesz — de MOST nem csinál semmit. A néma
        # hatástalanság rosszabb, mint a hiányzó beállítás (lásd config_check).
        if n not in engedett:
            sorok.append(_t("console.mode.not_enabled", symbol=symbol, name=n))
    if valtozo:
        sorok.append(_t("console.mode.set", symbol=symbol,
                        names=", ".join(n for n, _ in valtozo),
                        mode=_tm.LABELS.get(mode, mode)))
    else:
        # Csak takarítás történt — a mód nem változott, de a config igen.
        sorok.append(_t("console.mode.cleaned", symbol=symbol,
                        names=", ".join(szemet)))
    # ⚠ A MÓD CSAK AZ ÚJ BELÉPŐKRE VONATKOZIK. A „csak jelzés" ellenőrzése a
    # motorban a BELÉPŐ útján ül (`live_trader`): egy már nyitott pozíciót a
    # motor tovább kezel (breakeven, trailing, kiszállási jel). Aki `signal`-ra
    # vált, könnyen hiszi, hogy ezzel „kikapcsolta" a párt — nem.
    if _has_position(ctx, symbol):
        sorok.append(_t("console.mode.open_position", symbol=symbol))

    if not save:
        return Result(sorok)
    mentve = ctx.save_config()
    if not mentve:
        sorok.append(_t("console.not_saved"))
    return Result(sorok, ok=mentve)


def cmd_mode(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`mode <pár> [stratégia] <live|signal>`"""
    if len(args) < 2:
        return Result([_t("console.mode.usage")], ok=False)
    sym = _resolve_symbol(ctx, args[0])
    if sym is None:
        return Result([_t("console.unknown_pair", symbol=args[0])], ok=False)
    mode = str(args[-1]).lower()
    # Stratégia nélkül: a pár ÖSSZES engedélyezett stratégiája — mint a play/stop.
    names = [args[1]] if len(args) > 2 else list(ctx.strategies_of(sym) or [])
    return set_trade_mode(ctx, sym, names, mode, confirmed=confirmed)


def cmd_why(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`why <pár> [stratégia]` — miért nem kötött ma?

    ⚠ EZ A KÉRDÉS EDDIG MEGVÁLASZOLHATATLAN VOLT. Egy nem kötő cella pontosan
    úgy néz ki, mint amelyik épp nem talál belépőt. A választ a karmester
    belépő-telemetriája adja (`conductor/telemetry.py`) — a motor a mérést
    menet közben végzi, itt csak olvassuk.

    ⚠ A PARANCS-RÉTEGBEN VAN, tehát a konzol, a TUI és a Telegram UGYANAZT a
    választ kapja, mint a felület. Egy jelentés, ami felületenként mást mond,
    rosszabb a hiányzónál."""
    if not args:
        return Result([_t("console.why.usage")], ok=False)
    sym = _resolve_symbol(ctx, args[0])
    if sym is None:
        return Result([_t("console.unknown_pair", symbol=args[0])], ok=False)
    names = [args[1]] if len(args) > 1 else list(ctx.strategies_of(sym) or [])
    if not names:
        return Result([_t("console.play.no_strategy", symbol=sym)], ok=False)

    from conductor import report as _crep, snapshot as _csnap
    sorok = []
    for n in names:
        snap = _csnap.cell(ctx.cfg, sym, n,
                           strategies_of=lambda s: ctx.strategies_of(s) or [])
        sorok += _crep.why_lines(snap)
    return Result(sorok)


def cmd_health(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`health` — a NÉMA bajok: mi néz ki rendben, közben nem?

    ⚠ A LELETEK NEM ITT SZÜLETNEK. A karmester egészségőre
    (`conductor/policies/health.py`) fogja össze a meglévő detektorokat
    (`config_check`, `config_freshness`, `overview`) és a mérésből jövő
    leleteket — itt csak megjelenítjük. Egy külön „konzolos ellenőrzés" az első
    config-változásnál mást mondana, mint a felület."""
    from conductor.policies import health as _h
    from conductor import report as _crep

    leletek = _h.findings(ctx.cfg,
                          strategies_of=lambda s: ctx.strategies_of(s) or [])
    # A fennálló leletek a KRÓNIKÁBA is bekerülnek (naponta egyszer) — így a
    # „mióta áll fenn?" kérdés utólag megválaszolható.
    try:
        _h.journal_new(ctx.cfg, leletek)
    except Exception:
        pass
    return Result(_crep.health_lines(leletek), ok=not leletek)


def cmd_plan(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`plan` — az életciklus-létra javaslatai (ÁRNYÉK-MÓD: nem hajt végre semmit).

    ⚠ A JAVASLAT NEM AKCIÓ. A karmester az F1 fázisban csak LEÍRJA, mit tenne; a
    végrehajtás emberi (a `mode` paranccsal vagy a felületen). A javaslatok a
    krónikába is bekerülnek, hogy utólag mérhető legyen, jók lettek volna-e — a
    terv szerint az önállóság csak ezután adható meg."""
    from conductor.policies import health as _h, lifecycle as _lc
    from conductor import report as _crep

    _sof = lambda s: ctx.strategies_of(s) or []
    leletek = _h.findings(ctx.cfg, strategies_of=_sof)
    javaslatok = _lc.proposals(ctx.cfg, strategies_of=_sof,
                               health_findings=leletek)
    try:
        _lc.shadow(ctx.cfg, javaslatok)
    except Exception:
        # ⚠ A krónika hiánya nem viheti el a választ — de a javaslat attól még
        # érvényes, és a felhasználó LÁTJA.
        pass
    return Result(_crep.plan_lines(javaslatok))


def cmd_report(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`report` — a MAI nap + a karmester jelentése. EZ megy este Telegramra.

    ⚠ EGY ESTI ÜZENET, NEM KETTŐ. A napi összefoglaló már ma is megy
    (`notify.daily_summary_time`), és a `cmd_today` adja a tartalmát. Egy MÁSODIK
    esti üzenet versenyezne az elsővel a figyelmedért, és a kettő előbb-utóbb
    mást mondana ugyanarról a napról — ez a projekt visszatérő hibaosztálya. A
    karmester ezért SZAKASZOKAT ad a meglévő üzenethez.

    ⚠ KÉT „MA" TALÁLKOZIK ITT, és ez szándékos. A `cmd_today` a HELYI napot
    használja (a felhasználó abban gondolkodik, amikor azt kérdezi, „mi volt
    ma"), a karmester mérése viszont a BRÓKER napjához tartozik (a napi limit és
    a szesszió-ablakok is ahhoz igazodnak). A karmester szakasza ezért KIÍRJA,
    melyik napról beszél — így a kettő nem tud némán elcsúszni."""
    from conductor import report as _crep

    sorok = list(cmd_today(ctx, []).lines)
    try:
        sorok += _crep.daily_lines(
            ctx.cfg, strategies_of=lambda s: ctx.strategies_of(s) or [])
    except Exception:
        # ⚠ A karmester szakasza SOHA nem viheti el a napi összefoglalót: a
        # kötések és az eredmény akkor is kimennek, ha a mérés elakadt.
        log.debug("karmester: a napi szakasz kimaradt", exc_info=True)
    return Result(sorok)


# ---------------------------------------------------------------------------
# JAVASLAT-POSTALÁDA (a karmester F2 fázisa)
# ---------------------------------------------------------------------------
# ⚠ MIÉRT ITT, ÉS NEM A KARMESTERBEN. A döntés VÉGREHAJTÁSA ugyanazon az úton
# megy, mint a kézi `play`/`stop`/`mode` — a karmester nem lehet negyedik írási
# út. Itt tehát csak a PARANCS-alak van; a szabályok a `conductor/`-ban.


def _inbox_sync(ctx: Context):
    """A friss javaslatok beolvasztása a postaládába. Visszaad: a statisztika."""
    from conductor import inbox as _ib
    from conductor.policies import health as _h, lifecycle as _lc

    _sof = lambda s: ctx.strategies_of(s) or []
    lel = _h.findings(ctx.cfg, strategies_of=_sof)
    jav = _lc.proposals(ctx.cfg, strategies_of=_sof, health_findings=lel)
    return _ib.sync(ctx.cfg, jav, strategies_of=_sof)


def _inbox_tetel(ctx: Context, args: list, parancs: str):
    """`(tétel, hibás_Result)` — a közös azonosító-feloldás a négy döntéshez."""
    from conductor import inbox as _ib

    if not args:
        return None, Result([_t("conductor.inbox.usage", cmd=parancs)], ok=False)
    e = _ib.get(args[0])
    if not e:
        return None, Result([_t("conductor.inbox.unknown", id=args[0])], ok=False)
    return e, None


def cmd_inbox(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`inbox` — a karmester nyitott javaslatai, azonosítóval."""
    from conductor import inbox as _ib
    from conductor import report as _crep

    stat = {}
    try:
        stat = _inbox_sync(ctx)
    except Exception:
        # ⚠ A friss javaslatok hiánya nem viheti el a MÁR MEGLÉVŐ postaládát:
        # a nyitott ügyekről akkor is dönteni kell, ha a házirend most elakadt.
        log.debug("karmester: a postaláda frissítése kimaradt", exc_info=True)
    return Result(_crep.inbox_lines(_ib.items(_ib.PENDING), stat=stat))


def cmd_accept(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`accept <id>` — javaslat elfogadása ÉS végrehajtása.

    ⚠ AZ ELFOGADÁS NEM VAKON HAJT VÉGRE: a `conductor.actions` újraszámolja a
    javaslatot, és csak akkor lép, ha a házirend MA IS ugyanazt mondja."""
    from conductor import actions as _act
    from conductor import inbox as _ib

    e, hiba = _inbox_tetel(ctx, args, "accept")
    if hiba:
        return hiba
    if e.get("state") != _ib.PENDING:
        return Result([_t("conductor.inbox.not_pending", id=e["id"],
                          state=e.get("state"))], ok=False)
    return _act.apply(ctx, e, confirmed=confirmed, by="human")


def cmd_reject(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`reject <id>` — elvetés. A javaslat egy ideig NEM születik újra."""
    from conductor import config as _ccfg
    from conductor import inbox as _ib

    e, hiba = _inbox_tetel(ctx, args, "reject")
    if hiba:
        return hiba
    _ib.set_state(e["id"], _ib.REJECTED, ctx.cfg, by="human")
    return Result([_t("conductor.inbox.rejected", text=e.get("text") or e["id"],
                      days=int(_ccfg.inbox(ctx.cfg)["reject_cooldown_days"]))])


def cmd_defer(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`defer <id>` — „most nem": a javaslat néhány napra félrekerül."""
    from conductor import config as _ccfg
    from conductor import inbox as _ib

    e, hiba = _inbox_tetel(ctx, args, "defer")
    if hiba:
        return hiba
    _ib.set_state(e["id"], _ib.DEFERRED, ctx.cfg, by="human")
    return Result([_t("conductor.inbox.deferred", text=e.get("text") or e["id"],
                      days=int(_ccfg.inbox(ctx.cfg)["defer_days"]))])


def cmd_undo(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`undo <id>` — egy VÉGREHAJTOTT javaslat visszavonása.

    ⚠ A VISSZAVONÁS IS AKCIÓ: egy visszaminősítés visszavonása VALÓDI KÖTÉST
    kapcsol vissza, ezért ugyanazon a megerősítés-mintán megy."""
    from conductor import actions as _act

    e, hiba = _inbox_tetel(ctx, args, "undo")
    if hiba:
        return hiba
    return _act.undo(ctx, e, confirmed=confirmed, by="human")


def cmd_optq(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """`optq [cancel <id>]` — a fej nélküli optimalizálás-sor.

    ⚠ A SOR HAJTÁSA A MOTORÉ (óránként), nem ezé a parancsé: egy alprocessz
    indítása egy lekérdezés mellékhatásaként meglepetés volna. Itt csak
    megnézzük, mi van benne — és kivehetünk belőle egy várakozó tételt."""
    from conductor import optqueue as _q
    from conductor import report as _crep

    if args and str(args[0]).lower() == "cancel":
        if len(args) < 2:
            return Result([_t("conductor.inbox.usage", cmd="optq cancel")],
                          ok=False)
        if _q.cancel(args[1]):
            return Result([_t("conductor.optq.cancelled", id=args[1])])
        return Result([_t("conductor.optq.cancel_failed", id=args[1])], ok=False)
    return Result(_crep.optq_lines(_q.items()))


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
    """A motor ÉLETJELE — ugyanabból a `state_rows`-ból, amit a TUI is rajzol."""
    sorok = [_t("console.state.head")]
    for cimke, ertek, rendben in state_rows(ctx):
        jel = "" if rendben else "  " + _t("console.state.late")
        sorok.append(f"  {cimke:<18} {ertek}{jel}")
    elo = [s for s in sorted(_pairs(ctx)) if _live_strats(ctx, s)]
    sorok.append(_t("console.state.pairs", n=len(elo),
                    names=", ".join(elo) or "-"))
    return Result(sorok)


def cmd_today(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """A MAI nap: kötések, eredmény, a legjobb/legrosszabb — és hány jelzés volt.

    ⚠ A KIMARADT JELZÉS IS INFORMÁCIÓ. A chart-lelet (2026-08-31) épp arról
    szólt, hogy a jelzések többsége sosem lesz kötés; ha a napi kép csak a
    kötéseket mutatná, ugyanaz a félreolvasás jönne vissza szövegben.

    ⚠ ÉS EZ A NAPI ÖSSZEFOGLALÓ TARTALMA IS. A Telegram esti üzenete ugyanezt
    a függvényt hívja: ha külön épülne, a 23:00-kor kapott üzenet és a `/today`
    MÁST mondhatna ugyanarról a napról."""
    sorok = ctx.today_rows() or []
    _nyit = [r for r in sorok if str(r.get("event")) == "open"]
    _zar = [r for r in sorok if str(r.get("event")) == "close"]
    _jel = [r for r in sorok if str(r.get("event")) == "signal"]
    if not sorok:
        return Result([_t("console.today.none")])

    def _pnl(r):
        try:
            return float(r.get("pnl_usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    _ossz = sum(_pnl(r) for r in _zar)
    ki = [_t("console.today.head", opened=len(_nyit), closed=len(_zar),
             pnl=f"{_ossz:+.2f}", signals=len(_jel))]
    for r in _zar:
        ki.append(_t("console.today.row", symbol=r.get("symbol"),
                     strategy=r.get("strategy"), pnl=f"{_pnl(r):+.2f}"))
    # ⚠ A LEGJOBB ÉS A LEGROSSZABB KÜLÖN SOR. Egy napi nettó szám elrejti, hogy
    # egyetlen nagy vesztes vitte-e el a napot, vagy sok apró — pedig a kettő
    # egészen mást jelent.
    if len(_zar) >= 2:
        _j = max(_zar, key=_pnl)
        _r = min(_zar, key=_pnl)
        ki.append(_t("console.today.best", symbol=_j.get("symbol"),
                     pnl=f"{_pnl(_j):+.2f}", worst_symbol=_r.get("symbol"),
                     worst_pnl=f"{_pnl(_r):+.2f}"))
    # Ami MÉG NYITVA van: a nap eredménye nem teljes kép, amíg fut valami.
    _nyitva = len(position_rows(ctx))
    if _nyitva:
        ki.append(_t("console.today.open", n=_nyitva))
    return Result(ki)


def cmd_heart(ctx: Context, args: list, confirmed: bool = False) -> Result:
    """ÉLETJEL: egy soros ítélet, alatta a mért sorok.

    ⚠ A „minden rendben" csak akkor mondható ki, ha MINDEN sor rendben van —
    egy zöld pipa, ami nem néz semmit, rosszabb a semminél."""
    sorok = state_rows(ctx)
    rendben = all(ok for _c, _e, ok in sorok)
    ki = [_t("console.heart.ok" if rendben else "console.heart.bad")]
    for cimke, ertek, ok in sorok:
        ki.append(f"  {cimke:<18} {ertek}" + ("" if ok else "  "
                                              + _t("console.state.late")))
    return Result(ki, ok=rendben)


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
    "mode":    cmd_mode,
    "why":     cmd_why,
    "health":  cmd_health,
    "plan":    cmd_plan,
    "report":  cmd_report,
    "inbox":   cmd_inbox,
    "accept":  cmd_accept,
    "reject":  cmd_reject,
    "defer":   cmd_defer,
    "undo":    cmd_undo,
    "optq":    cmd_optq,
    "balance": cmd_balance,
    "today":   cmd_today,
    "state":   cmd_state,
    "heart":   cmd_heart,
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
    ("mode <pár> [strat] live|signal", "console.help.mode"),
    ("why <pár> [stratégia]", "console.help.why"),
    ("health", "console.help.health"),
    ("plan", "console.help.plan"),
    ("report", "console.help.report"),
    ("inbox", "console.help.inbox"),
    ("accept <id>", "console.help.accept"),
    ("reject <id>", "console.help.reject"),
    ("defer <id>", "console.help.defer"),
    ("undo <id>", "console.help.undo"),
    ("optq [cancel <id>]", "console.help.optq"),
    ("balance", "console.help.balance"),
    ("today", "console.help.today"),
    ("state", "console.help.state"),
    ("heart", "console.help.heart"),
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
        cycle_work=lt.cycle_work_stats,
        today_rows=lt.today_trade_rows,
        mt5_ok=lambda: bool(mt5_connector.is_connected()),
        licence_status=licence.status,
    )
