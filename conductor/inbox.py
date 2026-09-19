"""JAVASLAT-POSTALÁDA — a karmester javaslatai, amíg döntesz róluk.

⚠ MIÉRT KELL TÁROLNI ŐKET, HA ÚGYIS ÚJRASZÁMOLHATÓK. Az árnyék-módban a
javaslat elég volt listaként: minden lekérdezés újraszámolta. Amint viszont
DÖNTENI lehet róluk, a javaslatnak AZONOSÍTÓJA kell:

  • az „Elfogad" egy KONKRÉT javaslatra vonatkozik (egy szöveges „igen" két
    egyidejű javaslatnál kétértelmű volna — ez a `core/signal_offer.py` tanulsága);
  • az ELVETÉSNEK MEG KELL MARADNIA. Ha az elvetett javaslat másnap
    újraszületne, az elvetés semmit nem jelentene — a postaláda pedig arra
    tanítana, hogy hagyd figyelmen kívül. Ezért az elvetés `reject_cooldown_days`
    ideig eltemeti ugyanazt a `(kód, instrumentum, stratégia)` hármast;
  • az ELHALASZTÁS („most nem") egy dátumig félreteszi;
  • és a VÉGREHAJTOTT javaslathoz tartozik egy VISSZAÚT (az előző állapot),
    amit valahol tárolni kell.

⚠ A JAVASLAT NEM PARANCS. Az elfogadás pillanatában a végrehajtó ÚJRA
megnézi, igaz-e még (`conductor/actions.py`) — egy tegnapi „minősítsd vissza"
egy azóta megjavult cellán kárt tenne. A lejárat (`expire_days`) csak a második
védvonal: az elévült javaslat magától kiesik.

Tárolás: `data/conductor/inbox.json` (a teljes állapot egy fájlban — kevés,
kis rekord; a krónika viszi a TÖRTÉNETET, ez csak a NYITOTT ügyeket).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import date, datetime, timedelta, timezone

from conductor import paths as _paths

log = logging.getLogger(__name__)

# ── ÁLLAPOTOK (stabil kódok) ─────────────────────────────────────────────
PENDING  = "pending"     # vár a döntésedre
ACCEPTED = "accepted"    # elfogadva ÉS végrehajtva
REJECTED = "rejected"    # elvetve (a türelmi idő alatt nem születik újra)
DEFERRED = "deferred"    # elhalasztva egy dátumig
EXPIRED  = "expired"     # magától elévült
FAILED   = "failed"      # elfogadtad, de a végrehajtás nem sikerült

STATES = (PENDING, ACCEPTED, REJECTED, DEFERRED, EXPIRED, FAILED)
# Amiből még lehet PENDING (a türelmi idő / halasztás lejártával).
_ELTEMETETT = (REJECTED, DEFERRED)

_lock = threading.RLock()
_state: dict = {}
_betoltve = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _fp(e: dict) -> str:
    """A javaslat AZONOSSÁGA: akció+indok+cella. Ugyanaz a hármas nem születhet
    újra, amíg nyitott ügy vagy eltemetve van."""
    return f"{e.get('code')}|{e.get('symbol')}|{e.get('strategy')}"


def _load() -> None:
    global _betoltve
    with _lock:
        if _betoltve:
            return
        _betoltve = True
        ut = _paths.DIR / "inbox.json"
        if not ut.exists():
            return
        try:
            with open(ut, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("items"), dict):
                _state.update(d["items"])
        except Exception as ex:
            # ⚠ NEM néma: egy olvashatatlan postaláda ÜRESNEK látszana, és a
            # rendszer újraszülné a már elvetett javaslatokat.
            log.warning("conductor.inbox: a postaláda nem olvasható: %s", ex)


def _save_locked() -> bool:
    if not _paths.ensure():
        return False
    ut = _paths.DIR / "inbox.json"
    tmp = ut.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "items": _state}, f,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, ut)
        return True
    except Exception as ex:
        log.warning("conductor.inbox: a postaláda nem írható: %s", ex)
        return False


# ---------------------------------------------------------------------------
# ÖSSZEFÉSÜLÉS a friss javaslatokkal
# ---------------------------------------------------------------------------

def sync(cfg: dict, javaslatok: list) -> dict:
    """A friss javaslatok beolvasztása. Visszaad: `{"new": n, "expired": n}`.

    ⚠ AMI MÁR NYITOTT ÜGY, NEM SZÜLETIK ÚJRA. Egy fennálló helyzet (pl.
    „elszáradt a GOLD/csilla") minden körben újra javaslattá válna — a postaláda
    egy nap alatt olvashatatlan lenne, és pont az veszne el benne, ami új."""
    from conductor import config as _ccfg
    from conductor.proposals import HOLD

    k = _ccfg.inbox(cfg)
    _load()
    most = _now()
    uj = lejart = 0
    with _lock:
        # 1. Lejárat és a temetés feloldása — MINDIG, a friss javaslatoktól
        #    függetlenül (különben egy elhalasztott ügy sosem jönne vissza).
        for e in _state.values():
            if e.get("state") == PENDING:
                le = _ts(e.get("expires"))
                if le and most > le:
                    e["state"] = EXPIRED
                    lejart += 1
            elif e.get("state") in _ELTEMETETT:
                ig = _ts(e.get("hidden_until"))
                if ig and most > ig:
                    # ⚠ NEM tesszük vissza PENDING-be: a javaslat akkor
                    # születik újra, ha a HÁZIREND ma is javasolja. Egy
                    # feltámasztott, de már nem időszerű ügy hazugság volna.
                    e["state"] = EXPIRED

        nyitott = {_fp(e) for e in _state.values()
                   if e.get("state") in (PENDING,) + _ELTEMETETT}
        for p in (javaslatok or []):
            if p.action == HOLD or not p.valid():
                continue
            e = {"code": p.code, "symbol": p.symbol, "strategy": p.strategy}
            if _fp(e) in nyitott:
                continue
            azon = secrets.token_hex(3)
            while azon in _state:
                azon = secrets.token_hex(3)
            _state[azon] = {
                "id": azon, "created": _iso(most),
                "day": most.strftime("%Y-%m-%d"), "state": PENDING,
                "expires": _iso(most + timedelta(days=int(k["expire_days"]))),
                "code": p.code, "action": p.action, "reason": p.reason,
                "symbol": p.symbol, "strategy": p.strategy, "text": p.text,
                "evidence": dict(p.evidence or {}),
                "needs_human": bool(p.needs_human),
                "from_stage": p.from_stage, "to_stage": p.to_stage,
                "undo": None, "decided_at": None, "decided_by": None,
            }
            nyitott.add(_fp(e))
            uj += 1
        if uj or lejart:
            _save_locked()
    return {"new": uj, "expired": lejart}


# ---------------------------------------------------------------------------
# LEKÉRDEZÉS
# ---------------------------------------------------------------------------

def items(state=PENDING) -> list:
    """A postaláda tételei, legújabb elöl. `state=None` → mind."""
    _load()
    with _lock:
        ki = [dict(e) for e in _state.values()
              if state is None or e.get("state") == state]
    ki.sort(key=lambda e: str(e.get("created") or ""), reverse=True)
    return ki


def get(azon: str) -> "dict | None":
    _load()
    with _lock:
        e = _state.get(str(azon or "").strip().lower())
        return dict(e) if e else None


def set_state(azon: str, allapot: str, cfg: dict = None, *, by: str = "",
              undo=None, hidden_days: "int | None" = None) -> bool:
    """Egy tétel állapotának átírása. Visszaad: sikerült-e."""
    from conductor import config as _ccfg

    if allapot not in STATES:
        return False
    _load()
    with _lock:
        e = _state.get(str(azon or "").strip().lower())
        if not e:
            return False
        e["state"] = allapot
        e["decided_at"] = _iso(_now())
        e["decided_by"] = by or e.get("decided_by") or ""
        if undo is not None:
            e["undo"] = undo
        if allapot in _ELTEMETETT:
            k = _ccfg.inbox(cfg or {})
            napok = (int(k["reject_cooldown_days"]) if allapot == REJECTED
                     else int(k["defer_days"]))
            if hidden_days is not None:
                napok = int(hidden_days)
            e["hidden_until"] = _iso(_now() + timedelta(days=napok))
        return _save_locked()


def prune(keep_days: int = 30) -> int:
    """A LEZÁRT (nem nyitott) tételek takarítása. Visszaad: hány maradt.

    ⚠ A TÖRTÉNET A KRÓNIKÁBAN VAN, nem itt: ez a fájl a NYITOTT ügyeké. Egy
    végtelenül növő postaláda-fájl a betöltést lassítaná, a döntések nyomát
    viszont nem őrizné jobban."""
    _load()
    if keep_days is None or int(keep_days) <= 0:
        return len(_state)
    kuszob = (date.today() - timedelta(days=int(keep_days))).strftime("%Y-%m-%d")
    with _lock:
        for azon in [a for a, e in _state.items()
                     if e.get("state") not in (PENDING,) + _ELTEMETETT
                     and str(e.get("day") or "") < kuszob]:
            _state.pop(azon, None)
        _save_locked()
        return len(_state)


def reset_for_test() -> None:
    global _betoltve
    with _lock:
        _state.clear()
        _betoltve = False
