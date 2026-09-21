"""VÉGREHAJTÁS — az EGYETLEN út a javaslattól a valódi változásig.

⚠ EZ AZ A PONT, AHOL A KARMESTER HOZZÁÉR A RENDSZERHEZ. Minden más modulja
mér, ítél vagy javasol; itt dől el, hogy egy javaslatból változás lesz-e. Ezért
minden szabály, ami a tervben „invariáns" néven szerepel, itt válik kóddá.

── ⚠ A JAVASLAT NEM PARANCS: ÚJRAÉRVÉNYESÍTÉS ─────────────────────────────
Az elfogadás pillanatában ÚJRASZÁMOLJUK a javaslatot, és csak akkor hajtjuk
végre, ha a házirend MA IS ugyanazt mondja. Egy tegnapi „minősítsd vissza" egy
azóta megjavult cellán kárt tenne — és pont az ilyen, időközben elavult döntés
a legnehezebben észrevehető hiba: minden lépés helyesnek LÁTSZIK, csak épp egy
régi világra vonatkozik. A lejárat (`inbox.expire_days`) csak a második védvonal.

── ⚠ A KÖZÖS PARANCS-RÉTEGEN MEGY ─────────────────────────────────────────
A végrehajtás a `core.console_cmd` függvényeit hívja — ugyanazokat, amiket a
felület, a konzol és a Telegram. A karmester NEM lehet negyedik írási út:
különben a benne lévő, élesben megtanult szabályok (engedélyezettség,
optimalizálás alatti tiltás, kivezetés-figyelmeztetés, mentés-hiba jelzése) rá
nem vonatkoznának — és ugyanaz a hiba megint megtörténhetne, most már
automatikusan, éjjel.

── ⚠ MINDEN AKCIÓ RÖGZÍTI AZ ELŐZŐ ÁLLAPOTOT ──────────────────────────────
A terv invariánsa: ami megtörtént, visszavonható. A visszaút a postaláda
tételébe kerül (`undo`), és a krónikába is — így egy reggeli „mi történt éjjel?"
után egy paranccsal visszaállítható az előző állapot.

── A VÉGREHAJTÁSI UTAK ────────────────────────────────────────────────────
    set_mode_live / set_mode_signal → `core.console_cmd.set_trade_mode`
    queue_optimize                  → `conductor.optqueue` (fej nélküli sor)

⚠ AMIHEZ NINCS ÚT, ARRA NEM TESZÜNK ÚGY, MINTHA LENNE. Ha egy akcióhoz nincs
végrehajtó, az elfogadás MEGMONDJA, hol végezhető el — egy hamis siker rosszabb,
mint a hiányzó funkció. (A `queue_optimize` v3.82.0 előtt pont ilyen volt: az
optimalizálás csak a grafikus felületről indult.)
"""

from __future__ import annotations

import logging

from core.i18n import t as _t

from conductor import inbox as _inbox
from conductor import journal as _j
from conductor.proposals import (QUEUE_OPTIMIZE, SET_MODE_LIVE, SET_MODE_SIGNAL)

log = logging.getLogger(__name__)

# Akció → a KÖZÖS parancs-réteg kötés-módja.
_MODE_OF = {SET_MODE_LIVE: "live", SET_MODE_SIGNAL: "signal"}

# Amihez van fej nélküli végrehajtási út.
EXECUTABLE = tuple(_MODE_OF) + (QUEUE_OPTIMIZE,)


def can_execute(action: str) -> bool:
    return action in EXECUTABLE


# ---------------------------------------------------------------------------
# ÚJRAÉRVÉNYESÍTÉS
# ---------------------------------------------------------------------------

def still_valid(ctx, entry: dict) -> tuple:
    """Igaz-e MA IS a javaslat? → `(igen, mai_kód)`.

    ⚠ Hiba esetén `(False, "")`: ha nem tudjuk ellenőrizni, NEM hajtjuk végre.
    A kétely a nem-cselekvés felé billen — ez a terv „fail closed" szabálya."""
    try:
        from conductor import snapshot as _snap
        from conductor.policies import health as _h, lifecycle as _lc

        _sof = lambda s: ctx.strategies_of(s) or []
        lel = _h.findings(ctx.cfg, strategies_of=_sof)
        sn = _snap.cell(ctx.cfg, entry["symbol"], entry["strategy"],
                        strategies_of=_sof)
        mai = _lc.proposal_for(sn, ctx.cfg, lel)
        return (mai.code == entry.get("code"), mai.code)
    except Exception as ex:
        log.warning("conductor.actions: az újraérvényesítés elszállt (%s/%s): %s",
                    entry.get("symbol"), entry.get("strategy"), ex)
        return (False, "")


# ---------------------------------------------------------------------------
# VÉGREHAJTÁS
# ---------------------------------------------------------------------------

def apply(ctx, entry: dict, *, confirmed: bool = False, by: str = "human"):
    """Egy postaláda-tétel végrehajtása. Visszaad: `console_cmd.Result`.

    A `Result.confirm` NEM üres → a hívónak rá kell kérdeznie, és
    `confirmed=True`-val megismételnie (a projekt megerősítés-mintája)."""
    from core import console_cmd as _cc
    from core import trade_mode as _tm

    action = entry.get("action")
    if not can_execute(action):
        # ⚠ NEM hazudunk sikert. Megmondjuk, hol lehet elvégezni.
        return _cc.Result([_t("conductor.act.no_executor",
                              action=action or "-")], ok=False)

    # ⚠ A HÍVÁST IS BEBURKOLJUK, nem csak a belsejét. A `still_valid` maga
    # kezeli a saját hibáit — de ha MAGA a függvény száll el (átalakítás,
    # importhiba), a kivétel a parancsig szaladna, és a konzol/Telegram szálán
    # jelenne meg nyers hibaként. A PÉNZ ÚTJÁN a kétely mindig a nem-cselekvés
    # felé billen: amit nem tudunk ellenőrizni, azt nem hajtjuk végre.
    try:
        igaz, mai = still_valid(ctx, entry)
    except Exception as ex:
        log.warning("conductor.actions: az érvényesség nem ellenőrizhető "
                    "(%s/%s): %s", entry.get("symbol"), entry.get("strategy"), ex)
        igaz, mai = False, ""
    if not igaz:
        return _cc.Result([_t("conductor.act.stale", text=entry.get("text") or "",
                              now=mai or "-")], ok=False)

    sym, strat = entry["symbol"], entry["strategy"]
    if action == QUEUE_OPTIMIZE:
        return _optimalizalast_sorba(ctx, entry, by=by)

    elozo = _tm.mode_of(ctx.cfg, sym, strat)
    res = _cc.set_trade_mode(ctx, sym, [strat], _MODE_OF[action],
                             confirmed=confirmed)
    if res.confirm:
        return res
    if not res.ok:
        _inbox.set_state(entry["id"], _inbox.FAILED, ctx.cfg, by=by)
        return res

    # ⚠ A VISSZAÚT rögzítése — a tételbe ÉS a krónikába.
    undo = {"kind": "trade_mode", "symbol": sym, "strategy": strat,
            "mode": elozo}
    _inbox.set_state(entry["id"], _inbox.ACCEPTED, ctx.cfg, by=by, undo=undo)
    _j.write(_j.KIND_ACTION, entry.get("code") or action,
             entry.get("text") or "", sev="info", symbol=sym, strategy=strat,
             data={"by": by, "undo": undo, "inbox_id": entry["id"],
                   "evidence": entry.get("evidence") or {}})
    res.lines = list(res.lines) + [_t("conductor.act.undo_hint", id=entry["id"])]
    return res


def _optimalizalast_sorba(ctx, entry: dict, *, by: str = "human"):
    """`queue_optimize` — a fej nélküli sorba tesszük.

    ⚠ A SOR NEM INDÍT AZONNAL. Ha a cella ÉPP KERESKEDIK, a kérés `blocked`
    állapotban várakozik, az okával együtt — a futás végén ugyanis a stratégia
    paraméterfájlja íródna felül az alól a cella alól, amelyik vele kereskedik.
    Ezt KIMONDJUK, nem csendben halasztjuk: különben azt hinnéd, elindult."""
    from core import console_cmd as _cc
    from conductor import optqueue as _q

    sym, strat = entry["symbol"], entry["strategy"]
    _sof = lambda s: ctx.strategies_of(s) or []
    azon = _q.enqueue(ctx.cfg, sym, strat, source=f"inbox:{entry.get('id')}")
    if azon is None:
        return _cc.Result([_t("conductor.act.already_queued", symbol=sym,
                              strategy=strat)], ok=False)

    ok = _q.blocked_reason(ctx.cfg, sym, strat, _sof)
    sorok = [_t("conductor.act.queued", symbol=sym, strategy=strat, id=azon)]
    if ok:
        sorok.append(_t(f"conductor.optq.blocked.{ok}", symbol=sym,
                        strategy=strat))
    undo = {"kind": "optqueue", "queue_id": azon}
    _inbox.set_state(entry["id"], _inbox.ACCEPTED, ctx.cfg, by=by, undo=undo)
    _j.write(_j.KIND_ACTION, entry.get("code") or QUEUE_OPTIMIZE,
             entry.get("text") or "", sev="info", symbol=sym, strategy=strat,
             data={"by": by, "undo": undo, "inbox_id": entry["id"],
                   "evidence": entry.get("evidence") or {}})
    sorok.append(_t("conductor.act.undo_hint", id=entry["id"]))
    return _cc.Result(sorok)


def undo(ctx, entry: dict, *, confirmed: bool = False, by: str = "human"):
    """Egy VÉGREHAJTOTT tétel visszavonása. Visszaad: `console_cmd.Result`.

    ⚠ A VISSZAVONÁS IS AKCIÓ. Egy visszaminősítés visszavonása VALÓDI KÖTÉST
    kapcsol vissza — ezért ugyanazon a megerősítés-mintán megy, mint minden
    pénzt bekapcsoló lépés, és ugyanúgy a krónikába kerül."""
    from core import console_cmd as _cc

    u = entry.get("undo") or {}
    if entry.get("state") != _inbox.ACCEPTED:
        return _cc.Result([_t("conductor.act.no_undo", id=entry.get("id") or "-")],
                          ok=False)

    if u.get("kind") == "optqueue":
        # ⚠ CSAK A VÁRAKOZÓT vesszük ki. Egy MÁR FUTÓ optimalizálást nem
        # szakítunk félbe innen: azt a saját stop-markere állítja le
        # (`params_store.stop_marker`), és a félbeszakított futás állapotát a
        # sor learatása rendezi.
        from conductor import optqueue as _q
        if not _q.cancel(u.get("queue_id")):
            return _cc.Result([_t("conductor.act.undo_running")], ok=False)
        _j.write(_j.KIND_ACTION, f"undo:{entry.get('code')}",
                 _t("conductor.act.undone", text=entry.get("text") or ""),
                 sev="info", symbol=entry.get("symbol"),
                 strategy=entry.get("strategy"),
                 data={"by": by, "inbox_id": entry.get("id")})
        _inbox.set_state(entry["id"], _inbox.REJECTED, ctx.cfg, by=by)
        return _cc.Result([_t("conductor.act.undone",
                              text=entry.get("text") or "")])

    if u.get("kind") != "trade_mode":
        return _cc.Result([_t("conductor.act.no_undo", id=entry.get("id") or "-")],
                          ok=False)

    res = _cc.set_trade_mode(ctx, u["symbol"], [u["strategy"]], u["mode"],
                             confirmed=confirmed)
    if res.confirm or not res.ok:
        return res
    _j.write(_j.KIND_ACTION, f"undo:{entry.get('code')}",
             _t("conductor.act.undone", text=entry.get("text") or ""),
             sev="info", symbol=u["symbol"], strategy=u["strategy"],
             data={"by": by, "inbox_id": entry.get("id")})
    # ⚠ A tétel NEM megy vissza PENDING-be: a javaslat akkor születik újra, ha a
    # házirend ma is javasolja. Egy feltámasztott, de már nem időszerű ügy
    # hazugság volna — ugyanaz a szabály, mint a halasztás lejártánál.
    _inbox.set_state(entry["id"], _inbox.REJECTED, ctx.cfg, by=by)
    return res
