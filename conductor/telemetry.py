"""BELÉPŐ-TELEMETRIA — a „miért nem kötött ma az EURUSD?" válasza.

⚠ A LELET. A rendszer ma meg tudja mondani, MI történt (kötések, P&L, napló), de
nem tudja megmondani, MI NEM. Egy `(instrumentum × stratégia)` cella, ami nem
köt, pontosan úgy néz ki, mint amelyik épp nem talál belépőt — pedig a kettő
között minden különbség ott van: lehet, hogy a spread-kapu zárt egész nap, lehet,
hogy elfogytak a slotok, lehet, hogy a napi limit áll fenn, és lehet, hogy tényleg
nem volt jel. 10-12 instrumentumon és 4-5 stratégián ez naponta visszatérő,
megválaszolhatatlan kérdés — és a karmester ENÉLKÜL vakon döntene.

── MIT MÉRÜNK ─────────────────────────────────────────────────────────────
Minden JELET, és azt, hogy mi lett belőle. A motor a belépő-ágon (`process_pair`)
már kiszámolja a választ — eddig csak a naplóba írta, ahonnan másnap eltűnt.

⚠ A KÓD AZ AZONOSÍTÓ, A SZÖVEG CSAK A KIJELZÉS. A kimenetek stabil angol kódok
(`no_slot`, `daily_limit`, …), nem fordított mondatok. Ugyanez a szabály fogta
meg a `core/quality.py` minősítéseit: ott a magyar szó volt a rangsor kulcsa is,
és angolra fordítva a tábla NÉMÁN rossz sorrendet mutatott. Egy naplófájl ennél
rosszabb: a tegnapi fájlt már nem lehet visszafordítani.

── AMIT NEM MÉRÜNK (és miért) ─────────────────────────────────────────────
Nem mintavételezzük ciklusonként a kapuk ÁLLAPOTÁT („mennyi ideig volt zárva a
spread-kapu"). Az percenként írna minden párra, és a kérdésre („miért nem lett
kötés") nem is válaszol: egy egész nap zárt kapu is lehet ártalmatlan, ha aznap
egyetlen jel sem volt. A JEL-hez kötött hozzárendelés pontosan azt méri, ami
számít — és nagyságrendekkel olcsóbb.

── ISMÉTLŐDÉS-VÉDELEM ─────────────────────────────────────────────────────
⚠ EGY JEL EGYSZER SZÁMÍT. A motor percenként fut, a döntést hozó gyertya viszont
lehet H1 — ugyanaz a szetup 60 cikluson át „jel" marad. Ez élesben MÁR
elsült egyszer: a „csak jelzés" riasztásból egyetlen szetupra 60 üzenet ment ki
(GOLD BUY, 18:00–18:04, percenként egy), amíg az alert-ID a JEL-gyertyára nem
került. Ha a telemetria ezt nem kezelné, egy H1-es stratégia 60×-os súllyal
látszana egy M1-eshez képest — és a karmester ebből vonna le következtetést.
Ezért minden rekord viszi a JEL-GYERTYA idejét (`bar_ts`), és cellánként csak az
ELSŐ döntés számít arra a gyertyára.

── KÖLTSÉG ────────────────────────────────────────────────────────────────
A `record()` egy zár alatti szótár-frissítés — a motor körében elhanyagolható.
A lemezre írás IDŐZÍTETT (alap: 60 mp) és atomikus; a hívónak nem kell tudnia
róla. Nap-váltáskor az előző nap MINDIG kiíródik, mielőtt az új elkezdődne.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from core.i18n import LabelMap as _LabelMap
from conductor import paths as _paths

log = logging.getLogger(__name__)

# ── A KIMENETEK (stabil kódok) ───────────────────────────────────────────
# A sorrend a KIJELZÉSÉ is: előbb ami sikerült, aztán ami megakadályozta.
ENTERED      = "entered"        # valódi megbízás ment ki
SIGNAL_ONLY  = "signal_only"    # „csak jelzés" mód — szándékosan nem köt
CLOSING      = "closing"        # kivezetés alatt a pár
ALREADY_OPEN = "already_open"   # már van nyitott pozíció ezen a cellán
POLICY       = "policy"         # azonos-szimbólum házirend (pl. ellenirány)
DAILY_LIMIT  = "daily_limit"    # a napi veszteség-limit fennáll
NO_ATR       = "no_atr"         # nincs ATR (nincs elég adat a méretezéshez)
NO_SLOT      = "no_slot"        # elfogytak a kockázati slotok
GATE         = "gate"           # belépő-kapu blokkolt (a kapuk külön is)
CORRELATION  = "correlation"    # deviza-kitettség / korreláció-védelem
NO_PLAN      = "no_plan"        # a stratégia nem adott érvényes SL/TP méretet
EXEC_FAILED  = "exec_failed"    # a megbízás kiment, de a bróker elutasította

OUTCOMES = (ENTERED, SIGNAL_ONLY, CLOSING, ALREADY_OPEN, POLICY, DAILY_LIMIT,
            NO_ATR, NO_SLOT, GATE, CORRELATION, NO_PLAN, EXEC_FAILED)

# ⚠ LabelMap, nem sima szótár: a betöltéskor kiszámolt tábla BEFAGYNA a
# nyelvvel, és nyelvváltás után más feliratot adna, mint a felület többi része.
LABELS = _LabelMap("conductor.outcome", OUTCOMES)

# Ami NEM kötés — a jelentés ezekre bontja a „miért nem".
BLOCKERS = tuple(o for o in OUTCOMES if o not in (ENTERED,))

FLUSH_SEC = 60.0            # ennyinél ritkábban nem írunk lemezre
_FILE_VERSION = 1

_lock = threading.RLock()
_state: dict = {}           # nap -> {"SYM|strat": rekord}
_seen: dict = {}            # "SYM|strat" -> (nap, bar_ts, irány)  — dedup
_dirty: set = set()         # mely NAPOK változtak a legutóbbi kiírás óta
_last_flush = 0.0
_day_provider = None        # a hívó adhat KERESKEDÉSI napot (lásd set_day_provider)
# ⚠ AZ AUTONÓMIA-FOK KAPUJA. L-1-en („kikapcsolt") a karmester nem figyel —
# ideértve a mérést is. A kaput NEM itt oldjuk fel: a modul nem ismeri a
# configot (tiszta mérő réteg), a hívó állítja körönként EGYSZER. Így a
# `record()` forró útján nincs se config-olvasás, se fájlkérdezés.
_engedve = True


# ---------------------------------------------------------------------------
# A NAP
# ---------------------------------------------------------------------------

def set_enabled(be: bool) -> None:
    """A mérés ki/be — a hívó (motor) állítja az autonómia-fokból, körönként.

    ⚠ NEM ÜRÍTI, AMI MÁR MEGVAN. A kikapcsolás a JÖVŐRE szól: a már mért nap
    a lemezen marad. A visszamenőleges törlés adatvesztés volna, és a
    kikapcsolás nem arról szól, hogy eltüntessük a múltat."""
    global _engedve
    _engedve = bool(be)


def enabled() -> bool:
    return _engedve


def set_day_provider(fn) -> None:
    """A „mai nap" forrása — a motor a BRÓKER napját adja be
    (`mt5_connector.server_today`).

    ⚠ MIÉRT NEM DÖNTJÜK EL ITT. A projektben KÉT „ma" él, mindkettő
    szándékosan: a „Lezárt" fül a bróker napját használja (`server_today`), a
    napi összesítő a HELYI napot (`today_trade_rows`) — mert a felhasználó abban
    gondolkodik. A telemetria a PIAC napjához tartozik (a napi limit, a
    szesszió-ablakok és a kapuk is ahhoz), ezért a motor a brókerét adja be. De
    ez a modul MT5-mentes marad: aki nem köt be semmit, UTC-t kap."""
    global _day_provider
    _day_provider = fn


def day_key(day=None) -> str:
    """`ÉÉÉÉ-HH-NN`. `day`: `date`/`datetime`/szöveg, vagy `None` → a mai."""
    if day is None:
        if _day_provider is not None:
            try:
                day = _day_provider()
            except Exception:
                day = None
        if day is None:
            day = datetime.now(timezone.utc).date()
    if isinstance(day, str):
        return day[:10]
    return day.strftime("%Y-%m-%d")


def _cell(symbol: str, strategy: str) -> str:
    return f"{symbol}|{strategy}"


def _uj_rekord() -> dict:
    return {"signals": 0, "entries": 0, "outcomes": {},
            "gates_blocked": {}, "gates_reduced": {}, "last": None}


# ---------------------------------------------------------------------------
# RÖGZÍTÉS
# ---------------------------------------------------------------------------

def record(symbol: str, strategy: str, direction: str, outcome: str,
           gates_blocked=(), gates_reduced=(), bar_ts=None, day=None) -> bool:
    """Egy JEL kimenetele. Visszaad: beszámítottuk-e (`False` = ismétlődés).

    ⚠ SOHA NEM DOB. A mérés nem állíthatja meg a kereskedést — minden hiba a
    naplóba megy, és a motor megy tovább."""
    if not _engedve:
        return False
    try:
        return _record(symbol, strategy, direction, outcome,
                       gates_blocked, gates_reduced, bar_ts, day)
    except Exception as ex:                                  # pragma: no cover
        log.warning("conductor.telemetry: a rögzítés nem sikerült (%s/%s): %s",
                    symbol, strategy, ex)
        return False


def _record(symbol, strategy, direction, outcome,
            gates_blocked, gates_reduced, bar_ts, day) -> bool:
    if outcome not in OUTCOMES:
        # ⚠ NEM dobunk, de nem is nyelünk le: egy elgépelt kód némán egy új
        # oszlopot nyitna a jelentésben, és senki nem venné észre.
        log.warning("conductor.telemetry: ismeretlen kimenet: %r", outcome)
        return False

    nap = day_key(day)
    cella = _cell(symbol, strategy)
    with _lock:
        # ── ISMÉTLŐDÉS: egy JEL-GYERTYÁRA cellánként EGY döntés ───────────
        if bar_ts is not None:
            kulcs = (nap, int(bar_ts), str(direction or ""))
            if _seen.get(cella) == kulcs:
                return False
            _seen[cella] = kulcs

        napi = _state.setdefault(nap, {})
        r = napi.setdefault(cella, _uj_rekord())
        r["signals"] += 1
        if outcome == ENTERED:
            r["entries"] += 1
        r["outcomes"][outcome] = r["outcomes"].get(outcome, 0) + 1
        for k in (gates_blocked or ()):
            r["gates_blocked"][k] = r["gates_blocked"].get(k, 0) + 1
        for k in (gates_reduced or ()):
            r["gates_reduced"][k] = r["gates_reduced"].get(k, 0) + 1
        r["last"] = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "direction": str(direction or ""), "outcome": outcome,
                     "gates": list(gates_blocked or ())}
        _dirty.add(nap)
    _maybe_flush()
    return True


# ---------------------------------------------------------------------------
# LEMEZ
# ---------------------------------------------------------------------------

def _maybe_flush() -> None:
    global _last_flush
    most = time.time()
    if most - _last_flush < FLUSH_SEC:
        return
    flush()


def tick() -> None:
    """A motor kör-szívverése: ha eljött az ideje, kiírja a lemezre.

    ⚠ MIÉRT KELL A `record()` MELLÉ. A `record` maga is időzítve ír, de csak
    AKKOR fut, ha volt jel. Egy csendes napon a legutóbbi mérés órákig a
    memóriában maradna — és egy váratlan leállásnál elveszne. A kör úgyis
    percenként fut, tehát a szívverés ingyen van."""
    _maybe_flush()


def flush() -> bool:
    """A megváltozott NAPOK kiírása. Visszaad: minden sikerült-e.

    ⚠ ATOMIKUS (temp → replace): egy félbeszakadt írás nem hagyhat maga után
    olvashatatlan fájlt, amit aztán a jelentés „nincs adat"-ként mutatna."""
    global _last_flush
    with _lock:
        napok = sorted(_dirty)
        masolat = {n: json.loads(json.dumps(_state.get(n) or {})) for n in napok}
        _dirty.clear()
        _last_flush = time.time()
    if not napok:
        return True
    if not _paths.ensure(_paths.telemetry_dir()):
        # ⚠ A MÉRÉS NEM VESZHET EL EGY MAPPA-HIBA MIATT. A napokat a ciklus
        # elején kivettük a `_dirty`-ből; ha most nem tudunk írni, VISSZA kell
        # tenni őket — különben az addig gyűlt telemetria csendben eltűnik, és
        # a jelentés „nem volt jel"-t mutatna ott, ahol csak a lemez hiányzott.
        with _lock:
            _dirty.update(napok)
        return False
    ok = True
    for nap in napok:
        ut = _paths.telemetry_file(nap)
        tmp = ut.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": _FILE_VERSION, "day": nap,
                           "cells": masolat[nap]}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, ut)
        except Exception as ex:
            ok = False
            log.warning("conductor.telemetry: a(z) %s nem írható: %s", ut.name, ex)
            with _lock:
                _dirty.add(nap)          # ne vesszen el: a következő körben újra
    return ok


def load(day=None) -> dict:
    """Egy nap telemetriája LEMEZRŐL + a még ki nem írt memóriabeli rész.

    ⚠ A KETTŐ EGYÜTT AZ IGAZSÁG. Csak a fájlt olvasni azt jelentené, hogy a
    jelentés legfeljebb egy percet késik — a felhasználó pedig épp az imént
    kimaradt belépőt keresi benne."""
    nap = day_key(day)
    ki = {}
    try:
        ut = _paths.telemetry_file(nap)
        if ut.exists():
            with open(ut, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("cells"), dict):
                ki = d["cells"]
    except Exception as ex:
        # ⚠ NEM néma: egy sérült fájl üres jelentést adna, ami
        # megkülönböztethetetlen a „ma nem volt jel"-től.
        log.warning("conductor.telemetry: a(z) %s nem olvasható: %s", nap, ex)
    with _lock:
        mem = _state.get(nap) or {}
        for cella, r in mem.items():
            ki[cella] = json.loads(json.dumps(r))
    return ki


def cell(symbol: str, strategy: str, day=None) -> dict:
    """EGY `(instrumentum × stratégia)` cella napi telemetriája."""
    return load(day).get(_cell(symbol, strategy)) or _uj_rekord()


def why_not(symbol: str, strategy: str, day=None) -> list:
    """„Miért nem kötött?" — `[(kód, darab)]`, a leggyakoribb elöl.

    A KÖTÉSEK nincsenek benne: a kérdés az, ami MEGAKADÁLYOZTA. Üres lista =
    nem volt akadály (vagy nem is volt jel — azt a `signals` mondja meg)."""
    r = cell(symbol, strategy, day)
    ki = [(k, v) for k, v in (r.get("outcomes") or {}).items()
          if k in BLOCKERS and v]
    ki.sort(key=lambda x: (-x[1], x[0]))
    return ki


def window(symbol: str, strategy: str, days: int = 30, day=None) -> dict:
    """Egy cella telemetriája TÖBB napra összegezve.

    Visszaad: `{signals, entries, engine_days, signal_days, outcomes,
    gates_blocked}`.

    ⚠ AZ `engine_days` A LÉNYEG, NEM A NAPTÁRI NAP. Hétvégén, ünnepnapon és
    leállás alatt MINDEN cella néma — ha a nevezőbe naptári napok kerülnének, egy
    tökéletesen dolgozó cella is „ritkán jelzőnek" látszana. Egy nap akkor
    számít, ha aznap BÁRMELYIK cellának volt jele: akkor a motor futott és a
    piac nyitva volt."""
    from datetime import date as _date, timedelta as _td

    mai = day_key(day)
    try:
        y, m, d = (int(x) for x in mai.split("-"))
        kezd = _date(y, m, d)
    except Exception:
        return {"signals": 0, "entries": 0, "engine_days": 0, "signal_days": 0,
                "outcomes": {}, "gates_blocked": {}}

    cella = _cell(symbol, strategy)
    ki = {"signals": 0, "entries": 0, "engine_days": 0, "signal_days": 0,
          "outcomes": {}, "gates_blocked": {}}
    for i in range(max(1, int(days))):
        napi = load((kezd - _td(days=i)).strftime("%Y-%m-%d"))
        if not napi:
            continue                       # a motor nem futott ezen a napon
        ki["engine_days"] += 1
        r = napi.get(cella)
        if not r:
            continue
        n = int(r.get("signals") or 0)
        ki["signals"] += n
        ki["entries"] += int(r.get("entries") or 0)
        if n:
            ki["signal_days"] += 1
        for kulcs, forras in (("outcomes", "outcomes"),
                              ("gates_blocked", "gates_blocked")):
            for k, v in (r.get(forras) or {}).items():
                ki[kulcs][k] = ki[kulcs].get(k, 0) + int(v or 0)
    return ki


def prune(keep_days: int = 90) -> int:
    """A régi napi fájlok törlése. Visszaad: hány fájlt törölt.

    ⚠ MIÉRT KELL. Napi egy kis JSON évi ~250 fájl — önmagában nem probléma, de
    a `data/` mappa takarítatlanul nő, és a projektben már van rá minta
    (`position_record_keep_days`, `signal_journal_keep_days`), hogy minden
    nyilvántartásnak van megtartási ideje."""
    d = _paths.telemetry_dir()
    if keep_days <= 0 or not d.exists():
        return 0
    hatar = day_key()
    n = 0
    try:
        from datetime import date as _date, timedelta as _td
        y, m, dd = (int(x) for x in hatar.split("-"))
        kuszob = (_date(y, m, dd) - _td(days=int(keep_days))).strftime("%Y-%m-%d")
        for f in d.glob("*.json"):
            if f.stem < kuszob:
                f.unlink()
                n += 1
    except Exception as ex:
        log.warning("conductor.telemetry: a takarítás nem sikerült: %s", ex)
    return n


def reset_for_test() -> None:
    """A memóriabeli állapot ürítése — CSAK teszthez."""
    global _last_flush
    with _lock:
        _state.clear()
        _seen.clear()
        _dirty.clear()
        _last_flush = 0.0
