"""KRÓNIKA — mit LÁTOTT és (később) mit TETT a karmester.

Append-only JSONL: `data/conductor/decisions.jsonl`.

⚠ MIÉRT KELL, MÉG MIELŐTT BÁRMIT TENNE. A terv szerint a karmester önállósága
(L3/L4) csak akkor adható meg, ha a döntései utólag SZÁMONKÉRHETŐK. Egy
önállóan dolgozó réteg, aminek nincs nyoma, nem hibázik kevesebbet — csak
kideríthetetlenül hibázik. Ezért a krónika az ELSŐ írásra képes darab, és már az
egészségőr leletei is ide kerülnek.

⚠ A KÓD AZ AZONOSÍTÓ, A SZÖVEG CSAK EMLÉKEZTETŐ. Minden sor visz egy stabil
`code`-ot ÉS a beírás pillanatában érvényes fordított mondatot. A mondat azért
kerül bele, hogy a fájl fél év múlva is olvasható legyen — de rendezni,
szűrni, összehasonlítani SOSEM szabad vele (nyelvváltás után más lenne).

⚠ ISMÉTLŐDÉS-SZŰRÉS. Egy fennálló lelet (pl. „elszáradt a GOLD/csilla") minden
körben igaz. Ha minden körben sort írna, a krónika percenként nőne, és a VALÓDI
események elvesznének benne. Ezért az `ujdonsag()` naponta egyszer engedi át
ugyanazt a `(kód, instrumentum, stratégia)` hármast.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone

from conductor import paths as _paths

log = logging.getLogger(__name__)

KIND_HEALTH = "health"      # az egészségőr lelete (F1)
KIND_SHADOW = "shadow"      # árnyék-mód: mit TENNE (F1/F2)
KIND_ACTION = "action"      # amit ténylegesen TETT (F2-től)

_lock = threading.RLock()
_seen: set = set()          # (nap, ujjlenyomat) — a mai sorok
_seen_betoltve = False


def _ma() -> str:
    from conductor import telemetry as _tlm
    return _tlm.day_key()


def _fp(code: str, symbol=None, strategy=None) -> str:
    return f"{code}|{symbol or ''}|{strategy or ''}"


def _betolt(max_lines: int = 20000) -> None:
    """A MAI sorok ujjlenyomatainak beolvasása (ismétlődés-szűréshez).

    ⚠ CSAK A MAI NAP kell, de a fájl elejéről nem tudjuk, hol kezdődik — ezért a
    VÉGÉRŐL olvasunk legfeljebb `max_lines` sort. A napi takarítás mellett ez
    bőven elég, és egy nagyra nőtt fájl sem lassítja be az indulást."""
    global _seen_betoltve
    with _lock:
        if _seen_betoltve:
            return
        _seen_betoltve = True
        ut = _paths.journal_file()
        if not ut.exists():
            return
        try:
            with open(ut, encoding="utf-8") as f:
                sorok = f.readlines()[-int(max_lines):]
        except Exception as ex:
            log.warning("conductor.journal: a krónika nem olvasható: %s", ex)
            return
        ma = _ma()
        for sor in sorok:
            try:
                d = json.loads(sor)
            except Exception:
                continue
            if d.get("day") == ma:
                _seen.add((ma, _fp(d.get("code"), d.get("symbol"),
                                   d.get("strategy"))))


def ujdonsag(code: str, symbol=None, strategy=None, repeat_days: int = 1) -> bool:
    """Új-e MA ez a `(kód, instrumentum, stratégia)` hármas?

    `repeat_days <= 0` → mindig új (nincs szűrés)."""
    if repeat_days is not None and int(repeat_days) <= 0:
        return True
    _betolt()
    with _lock:
        return (_ma(), _fp(code, symbol, strategy)) not in _seen


def write(kind: str, code: str, text: str = "", *, sev: str = "info",
          symbol=None, strategy=None, data=None) -> bool:
    """Egy sor a krónikába. Visszaad: sikerült-e.

    ⚠ SOHA NEM DOB: a krónika hiánya nem állíthatja meg sem a mérést, sem a
    kereskedést — de naplózza, mert egy néma krónika pont az a nyom, amit
    keresnénk."""
    ma = _ma()
    sor = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "day": ma, "kind": kind, "sev": sev, "code": code,
           "symbol": symbol, "strategy": strategy, "text": text}
    if data:
        sor["data"] = data
    if not _paths.ensure():
        return False
    try:
        with open(_paths.journal_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(sor, ensure_ascii=False) + "\n")
    except Exception as ex:
        log.warning("conductor.journal: a bejegyzés nem írható: %s", ex)
        return False
    _betolt()
    with _lock:
        _seen.add((ma, _fp(code, symbol, strategy)))
    return True


def read(limit: int = 200, kind=None, symbol=None, since_day=None,
         max_scan_lines: int = 20000) -> list:
    """A krónika sorai, LEGÚJABB ELÖL. Szűrhető fajtára/instrumentumra/napra."""
    ut = _paths.journal_file()
    if not ut.exists():
        return []
    try:
        with open(ut, encoding="utf-8") as f:
            nyers = f.readlines()[-int(max_scan_lines):]
    except Exception as ex:
        log.warning("conductor.journal: a krónika nem olvasható: %s", ex)
        return []
    ki = []
    for sor in reversed(nyers):
        try:
            d = json.loads(sor)
        except Exception:
            continue                      # egy sérült sor ne vigye el a többit
        if kind and d.get("kind") != kind:
            continue
        if symbol and d.get("symbol") != symbol:
            continue
        if since_day and str(d.get("day") or "") < str(since_day):
            continue
        ki.append(d)
        if len(ki) >= int(limit):
            break
    return ki


def prune(keep_days: int = 365) -> int:
    """A régi sorok eldobása. Visszaad: hány sort tartott meg.

    ⚠ ÁTÍRÁSSAL, ATOMIKUSAN (temp → replace): egy félbeszakadt takarítás nem
    hagyhat csonka krónikát — épp az a fájl, amiből utólag rekonstruálnánk,
    mi történt."""
    ut = _paths.journal_file()
    if keep_days is None or int(keep_days) <= 0 or not ut.exists():
        return 0
    kuszob = (date.today() - timedelta(days=int(keep_days))).strftime("%Y-%m-%d")
    try:
        with open(ut, encoding="utf-8") as f:
            sorok = f.readlines()
        tart = []
        for sor in sorok:
            try:
                if str(json.loads(sor).get("day") or "") >= kuszob:
                    tart.append(sor)
            except Exception:
                continue
        if len(tart) == len(sorok):
            return len(tart)
        tmp = ut.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(tart)
        os.replace(tmp, ut)
        return len(tart)
    except Exception as ex:
        log.warning("conductor.journal: a takarítás nem sikerült: %s", ex)
        return 0


def reset_for_test() -> None:
    global _seen_betoltve
    with _lock:
        _seen.clear()
        _seen_betoltve = False
