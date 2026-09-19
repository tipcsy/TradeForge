"""EGÉSZSÉGŐR — a NÉMA bajok vadászata.

⚠ MIT KERES. Nem hibát: a hiba hangos, elszáll, naplóz. Azokat az állapotokat
keresi, amikben a program úgy néz ki, mintha rendben volna, közben nem — ez a
projekt visszatérő, legdrágább hibaosztálya (némán hatástalan kapu, elévült
pillanatkép-érték, más világban optimalizált paraméterkészlet, elszáradt pár).

── ⚠ NEM ÍR ÚJRA SEMMIT ───────────────────────────────────────────────────
A néma bajok HÁROM detektora már létezik, és mind tiszta függvény:

    core/config_check.py      — önellentmondó config (kapu, aminek nincs mit mérnie)
    core/config_freshness.py  — elévült pillanatkép-érték (pv1_point, swap)
    core/overview.py          — a cella mentett állapotának bajai

Ez a modul ÖSSZEFOGJA őket, és hozzáteszi azt, amit CSAK a karmester tud: a
MÉRÉSBŐL jövő leleteket (elszáradás, kapu-fal, néma sorozat). Egy „karmester
saját config-ellenőrzés" az első config-változásnál elcsúszna az igazitól, és
két forrás mondana mást ugyanarról — a projekt visszatérő hibaosztálya.

── ⚠ A MÉRÉS HIÁNYA IS LELET ──────────────────────────────────────────────
Ha egy forrás elszáll, NEM nyeljük le: `source_error` lelet keletkezik. Egy
csendben kimaradó ellenőrzés ugyanazt jelenti, mint a csendben átengedő kapu —
a felület „minden rendben"-t mutatna, miközben senki nem nézett oda.

⚠ EGY KIVÉTEL, AMIT NEM TUDUNK ORVOSOLNI: a `config_freshness` MT5-kapcsolat
nélkül ÜRES listát ad (a saját szerződése szerint), és az üres lista
megkülönböztethetetlen a „minden friss"-től. Ezt a modul nem tudja eldönteni —
a jelentés ezért sosem állítja, hogy „a frissesség rendben", csak azt, hogy
nincs LELET.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from core.i18n import t as _t
from core.overview import SEV_INFO, SEV_RISK, SEV_WARN

from conductor import config as _ccfg
from conductor import expectation as _exp
from conductor import snapshot as _snap
from conductor import telemetry as _tlm

log = logging.getLogger(__name__)

# Súlyosság-sorrend a rendezéshez. ⚠ A KÓD a kulcs, nem a felirat.
RANK = {SEV_RISK: 0, SEV_WARN: 1, SEV_INFO: 2}

SOURCE_ERROR = "source_error"


def _lelet(sev, code, text, symbol=None, strategy=None, source="") -> dict:
    return {"sev": sev, "code": code, "text": text, "symbol": symbol,
            "strategy": strategy, "source": source}


# ---------------------------------------------------------------------------
# A MEGLÉVŐ detektorok becsatornázása
# ---------------------------------------------------------------------------

def _from_config_check(cfg: dict) -> list:
    from core import config_check as _cc
    ki = []
    for f in (_cc.check_with_state(cfg) or []):
        sev = SEV_WARN if f.get("level") == _cc.WARN else SEV_INFO
        ki.append(_lelet(sev, f"config.{f.get('code')}", f.get("message") or "",
                         symbol=f.get("symbol"), source="config_check"))
    return ki


def _from_freshness(cfg: dict) -> list:
    from core import config_freshness as _cf
    ki = []
    for sor in (_cf.check(cfg) or []):
        # `[(szimbólum, mező, config, élő)]`
        try:
            sym, mezo, regi, uj = sor[0], sor[1], sor[2], sor[3]
        except Exception:
            continue
        ki.append(_lelet(SEV_WARN, f"freshness.{mezo}",
                         _t("conductor.health.freshness", symbol=sym, field=mezo,
                            cfg=f"{regi}", live=f"{uj}"),
                         symbol=sym, source="config_freshness"))
    return ki


def _from_overview(cfg: dict, sn: dict) -> list:
    from core import overview as _ov
    sym, strat = sn.get("symbol"), sn.get("strategy")
    data = _exp.saved(sym, strat)
    ki = []
    for w in (_ov.warnings(cfg, sym, strat, data,
                           state=sn.get("intent") or "", mode=sn.get("mode") or "")
              or []):
        ki.append(_lelet(w.get("sev") or SEV_INFO,
                         f"cell.{w.get('code') or 'unknown'}",
                         w.get("text") or "", symbol=sym, strategy=strat,
                         source="overview"))
    return ki


# ---------------------------------------------------------------------------
# AMIT CSAK A KARMESTER TUD — a mérésből
# ---------------------------------------------------------------------------

def _dried_up(sn: dict, k: dict) -> list:
    """ELSZÁRADÁS: fut, nem blokkolja semmi, nem is veszít — csak nem köt.

    ⚠ EZ A LEGGYAKORIBB NÉMA BAJ, és a mai felületen SEHOL nem látszik: egy
    elszáradt cella pontosan úgy néz ki, mint amelyik épp nem talál belépőt."""
    if not sn.get("running"):
        return []
    # ⚠ PAPÍR MÓDBAN NINCS KÖTÉS — SZÁNDÉKOSAN. A „csak jelzés" módú cella
    # élő kötésszáma definíció szerint nulla, tehát az aktivitás-arány mindig 0
    # volna: a lelet MINDEN papír cellára tüzelne, örökre. Ez nemcsak zaj lenne,
    # hanem KÁROS is: az életciklus-létra a kockázati leletek miatt sosem
    # léptetné élőre azt a cellát, amelyik épp a bizonyítékot gyűjti — vagyis a
    # mérés a saját céljával fordulna szembe. A papír aktivitását a létra a
    # JELEKBŐL méri (`lifecycle._paper`), nem innen.
    if sn.get("mode") == "signal":
        return []
    v = sn.get("expected") or {}
    d = sn.get("divergence") or {}
    ar = d.get("activity_ratio")
    if v.get("source") != "saved" or ar is None:
        return []
    # ⚠ FRISS CELLÁRA NEM: egy most indított pár néhány nap alatt jogosan nem
    # hozza a havi átlagot — az „elszáradt" ott hamis riasztás volna.
    if int(sn.get("window_days") or 0) < int(k["dried_up_min_days"]):
        return []
    if ar > float(k["dried_up_ratio"]):
        return []
    return [_lelet(SEV_WARN, "dried_up",
                   _t("conductor.health.dried_up",
                      symbol=sn["symbol"], strategy=sn["strategy"],
                      live=f"{(sn.get('live') or {}).get('trades_per_day') or 0:.2f}",
                      expected=f"{v.get('trades_per_day') or 0:.2f}",
                      pct=f"{ar * 100:.0f}%"),
                   symbol=sn["symbol"], strategy=sn["strategy"], source="measured")]


def _gate_wall(sn: dict, k: dict) -> list:
    """KAPU-FAL: egy kapu a mai jelek szinte mindegyikét blokkolta, és egy kötés
    sem lett. Nem hiba — de ha napokig így áll, a cella gyakorlatilag ki van
    kapcsolva, miközben a felületen „fut"."""
    t = sn.get("today") or {}
    jelek = int(t.get("signals") or 0)
    if jelek < int(k["gate_wall_min_signals"]):
        return []
    if int(t.get("entries") or 0) > 0:
        return []
    ki = []
    for kapu, db in (t.get("gates_blocked") or {}).items():
        arany = db / jelek if jelek else 0.0
        if arany >= float(k["gate_wall_ratio"]):
            ki.append(_lelet(SEV_WARN, f"gate_wall.{kapu}",
                             _t("conductor.health.gate_wall",
                                symbol=sn["symbol"], strategy=sn["strategy"],
                                gate=kapu, n=db, total=jelek,
                                pct=f"{arany * 100:.0f}%"),
                             symbol=sn["symbol"], strategy=sn["strategy"],
                             source="measured"))
    return ki


def _silent_days(sn: dict, k: dict, day=None) -> list:
    """NÉMA SOROZAT: a cella X olyan napon nem adott jelet, amikor a motor FUTOTT.

    ⚠ MIÉRT A „MOTOR FUTOTT" A FELTÉTEL, ÉS NEM A NAPTÁR. Hétvégén, ünnepnapon
    és leállás alatt MINDEN cella néma — ezekből a napokból sorozatot számolni
    hamis riasztások sorozata volna. Egy nap akkor számít, ha a telemetria napi
    fájljában VOLT jel (bármelyik cellánál): akkor a motor dolgozott, a piac
    nyitva volt, és ennek a cellának mégsem volt mondanivalója."""
    if not sn.get("running"):
        return []
    kell = int(k["silent_days"])
    if kell <= 0:
        return []
    cella = f"{sn['symbol']}|{sn['strategy']}"
    mai = _tlm.day_key(day)
    try:
        y, m, d = (int(x) for x in mai.split("-"))
        nap = date(y, m, d)
    except Exception:
        return []
    sorozat = 0
    # Legfeljebb 3× annyi naptári napot nézünk, mint amennyi FUTÓ nap kell:
    # ennyibe a hétvégék és egy-két leállás is belefér.
    for i in range(kell * 3):
        kulcs = (nap - timedelta(days=i)).strftime("%Y-%m-%d")
        napi = _tlm.load(kulcs)
        if not napi:
            continue                       # a motor nem futott ezen a napon
        if int((napi.get(cella) or {}).get("signals") or 0) > 0:
            break                          # volt jel → nincs sorozat
        sorozat += 1
        if sorozat >= kell:
            return [_lelet(SEV_WARN, "silent_days",
                           _t("conductor.health.silent_days",
                              symbol=sn["symbol"], strategy=sn["strategy"],
                              days=sorozat),
                           symbol=sn["symbol"], strategy=sn["strategy"],
                           source="measured")]
    return []


# ---------------------------------------------------------------------------
# A TELJES ÁTVIZSGÁLÁS
# ---------------------------------------------------------------------------

def findings(cfg: dict, *, strategies_of=None, day=None,
             days: int = _snap.DEFAULT_WINDOW_DAYS) -> list:
    """MINDEN lelet, súlyosság szerint rendezve.

    `strategies_of(symbol) -> list`: a páron engedélyezett stratégiák (a motor
    listája). Nélküle a cella-szintű ellenőrzések kimaradnak — és ezt LELETKÉNT
    mondjuk ki, nem csendben."""
    k = _ccfg.health(cfg)
    ki: list = []

    for nev, fn in (("config_check", lambda: _from_config_check(cfg)),
                    ("config_freshness", lambda: _from_freshness(cfg))):
        try:
            ki += fn()
        except Exception as ex:
            log.warning("conductor.health: a(z) %s forrás elszállt: %s", nev, ex)
            ki.append(_lelet(SEV_WARN, f"{SOURCE_ERROR}.{nev}",
                             _t("conductor.health.source_error", source=nev,
                                error=str(ex)), source=nev))

    if strategies_of is None:
        ki.append(_lelet(SEV_INFO, f"{SOURCE_ERROR}.cells",
                         _t("conductor.health.no_strategy_list"), source="cells"))
        return sorted(ki, key=lambda f: (RANK.get(f["sev"], 9), f["code"]))

    try:
        cellak = _snap.cells(cfg, strategies_of=strategies_of, day=day, days=days)
    except Exception as ex:
        log.warning("conductor.health: a pillanatkép elszállt: %s", ex)
        cellak = []
        ki.append(_lelet(SEV_WARN, f"{SOURCE_ERROR}.snapshot",
                         _t("conductor.health.source_error", source="snapshot",
                            error=str(ex)), source="snapshot"))

    for sn in cellak:
        for nev, fn in (("overview", lambda: _from_overview(cfg, sn)),
                        ("dried_up", lambda: _dried_up(sn, k)),
                        ("gate_wall", lambda: _gate_wall(sn, k)),
                        ("silent_days", lambda: _silent_days(sn, k, day))):
            try:
                ki += fn()
            except Exception as ex:
                log.warning("conductor.health: %s/%s — a(z) %s elszállt: %s",
                            sn.get("symbol"), sn.get("strategy"), nev, ex)
                ki.append(_lelet(SEV_WARN, f"{SOURCE_ERROR}.{nev}",
                                 _t("conductor.health.source_error", source=nev,
                                    error=str(ex)),
                                 symbol=sn.get("symbol"),
                                 strategy=sn.get("strategy"), source=nev))

    return sorted(ki, key=lambda f: (RANK.get(f["sev"], 9), f["code"],
                                     f.get("symbol") or "", f.get("strategy") or ""))


def journal_new(cfg: dict, leletek: list) -> int:
    """Az ÚJ leletek krónikába írása. Visszaad: hány sor keletkezett.

    ⚠ NAPONTA EGYSZER ugyanaz a lelet (`journal.ujdonsag`): egy fennálló baj
    minden körben igaz, és ha minden körben sort írna, a valódi események
    elvesznének a krónikában."""
    from conductor import journal as _j

    k = _ccfg.health(cfg)
    ism = int(k["repeat_days"])
    n = 0
    for f in (leletek or []):
        if not _j.ujdonsag(f["code"], f.get("symbol"), f.get("strategy"), ism):
            continue
        if _j.write(_j.KIND_HEALTH, f["code"], f.get("text") or "",
                    sev=f.get("sev") or SEV_INFO, symbol=f.get("symbol"),
                    strategy=f.get("strategy"),
                    data={"source": f.get("source") or ""}):
            n += 1
    return n
