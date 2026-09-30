"""VEZÉRLŐ CSATORNA egy bróker-motorhoz — fájl-alapú parancs-postaláda.

⚠ 0029 „Több bróker egyszerre", 4b lépés (2026-09-28). A 4a-ban a felület csak
OLVASTA a többi bróker motorját (`core/engine_status`). Most VEZÉRELNI is tudja:
Play/Stop, mód-váltás, pozíció-zárás, a motor leállítása.

A CSATORNA: a felület egy parancsfájlt tesz a bróker számla-mappájába
(`data/accounts/<id>/engine_inbox/<azon>.json`), a motor másodpercenként
felveszi, a KÖZÖS parancs-rétegen (`core.console_cmd.dispatch`) végrehajtja, és
válaszfájlt ír (`engine_outbox/<azon>.json`). Ugyanaz a döntés, mint a 4a-nál:
nincs port, tűzfal, újrakapcsolódás; atomikus írás (temp → replace).

⚠ A SZABÁLYOK A PARANCS-RÉTEGBEN MARADNAK. A megerősítés kétlépcsős, pontosan
úgy, mint a konzolon és a Telegramon: a felület `confirmed=False`-szal küld,
a motor a megerősítő kérdést adja vissza (`confirm`), a felület rákérdez, és
csak igen esetén küldi újra `confirmed=True`-val. A felület tehát nem tud olyat,
amit a konzol ne tudna — és nem is kerülheti meg azt, amire a konzol rákérdez.

⚠ ELAVULT PARANCS NEM FUT LE. Ha a motor egy parancsot `MAX_AGE_SEC`-nél
később vesz fel (mert közben állt vagy újraindult), ELDOBJA, és ezt válaszban
meg is mondja. Egy órákkal korábban beküldött „close all" nem sülhet el
váratlanul egy újraindítás után.

⚠ CSAK ENGEDÉLYEZETT PARANCSOK (`ALLOWED`) futnak távolról — a felületnek
ennyi kell; a többi (hangolás, karmester, kép) a motor konzolján marad.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from core import engine_status as ES
from core.i18n import t as _t

INBOX, OUTBOX = "engine_inbox", "engine_outbox"
ALLOWED = frozenset({"play", "stop", "close", "mode", "quit", "pos", "pairs"})
MAX_AGE_SEC = 60.0
# ⚠ ÁRVA VÁLASZOK (demó-próba, 2026-09-29): ha a motor később válaszol, mint
# ameddig a felület vár (pl. induláskor, amikor a felület már kérdez, a motor
# még kapcsolódik), a válasz a kimenő postaládában marad. A motor ezeket
# `ORPHAN_SEC` után törli — különben a mappa lassan telne.
ORPHAN_SEC = 120.0
# ⚠ 2026-09-30, MÉRVE élesben: minden kérés ~900-1000 ms volt a MÉRETTŐL
# FÜGGETLENÜL (419 B és 35 KB ugyanannyi) — a késés a postaláda-figyelés volt,
# nem az adat. Páronként 3-5 kérés × 27 pár = percekig „számolgatta a kapukat".
# Egy üres mappa listázása 50 ms-onként elhanyagolható terhelés.
POLL_SEC = 0.05


def _dir(nev: str, profile=None) -> Path:
    from core import broker_paths
    return broker_paths.account(broker_paths.DATA / nev, profile)


def _olvas(p: Path):
    for _ in range(6):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
        except Exception:
            return None
    return None


# ── FELÜLET OLDAL ───────────────────────────────────────────────────────────

def send(profile, line: str = "", confirmed: bool = False, *, now=None,
         inbox: Path | None = None, op: str | None = None,
         args: dict | None = None) -> str:
    """Parancs a bróker motorjának. Visszaad: a parancs azonosítója.

    Két alak: `line` — egy konzol-parancssor (a közös parancs-rétegen fut);
    `op` + `args` — STRUKTURÁLT művelet (4b/3 S3b), amelynek nincs konzol-
    parancsa (kézi kötés, BE, trailing, örökbefogadás…); a motor csak a neki
    megadott művelet-listából (`ops`) hajt végre."""
    azon = uuid.uuid4().hex
    cmd = {"id": azon, "line": str(line or ""), "confirmed": bool(confirmed),
           "ts": time.time() if now is None else now}
    if op:
        cmd.update(op=str(op), args=dict(args or {}))
    ES.write(cmd, (inbox or _dir(INBOX, profile)) / f"{azon}.json")
    return azon


def result(profile, azon: str, *, outbox: Path | None = None) -> dict | None:
    """A válasz (és a fájl törlése), vagy None, ha még nincs."""
    p = (outbox or _dir(OUTBOX, profile)) / f"{azon}.json"
    r = _olvas(p)
    if r is not None:
        try:
            p.unlink()
        except Exception:
            pass
    return r


def request(profile, line: str = "", confirmed: bool = False, timeout: float = 10.0,
            *, inbox=None, outbox=None, op=None, args=None) -> dict | None:
    """Küldés + várakozás a válaszra (HÁTTÉRSZÁLBÓL hívandó — blokkol).
    None: a motor `timeout` alatt nem válaszolt (nem fut / lefagyott)."""
    azon = send(profile, line, confirmed, inbox=inbox, op=op, args=args)
    vege = time.time() + timeout
    while time.time() < vege:
        r = result(profile, azon, outbox=outbox)
        if r is not None:
            return r
        time.sleep(0.02)             # a válaszra várás is sűrű (volt 0,2 mp)
    # ⚠ A válasz nélkül maradt parancsot VISSZAVONJUK — különben a motor egy
    # későbbi induláskor (a MAX_AGE-en belül) még végrehajthatná.
    try:
        ((inbox or _dir(INBOX, profile)) / f"{azon}.json").unlink()
    except Exception:
        pass
    return None


# ── MOTOR OLDAL ─────────────────────────────────────────────────────────────

def _parancs_nev(line: str) -> str:
    from core import console_cmd as C
    parts = str(line or "").strip().split()
    if not parts:
        return ""
    nev = parts[0].lower().lstrip("/")
    return C.ALIASES.get(nev, nev)


def _arvak_torlese(ob: Path, now: float) -> int:
    """A senki által át nem vett, `ORPHAN_SEC`-nél régebbi válaszok törlése."""
    n = 0
    if not ob.exists():
        return 0
    for f in ob.glob("*.json"):
        try:
            if now - f.stat().st_mtime > ORPHAN_SEC:
                f.unlink()
                n += 1
        except Exception:
            pass
    return n


def process_once(ctx, profile, *, now=None, inbox=None, outbox=None,
                 ops: dict | None = None) -> list:
    """A postaláda EGY feldolgozása. Visszaad: a feldolgozott válaszok listája
    (a teszthez). Egy hibás parancs nem állítja meg a többit."""
    from core import console_cmd as C
    now = time.time() if now is None else now
    ib = inbox or _dir(INBOX, profile)
    ob = outbox or _dir(OUTBOX, profile)
    _arvak_torlese(ob, now)
    if not ib.exists():
        return []
    kesz = []
    for f in sorted(ib.glob("*.json"), key=lambda x: x.stat().st_mtime):
        cmd = _olvas(f)
        try:
            f.unlink()
        except Exception:
            pass
        if not isinstance(cmd, dict) or not cmd.get("id"):
            continue
        valasz = {"id": cmd["id"], "ts": now, "ok": False, "lines": [],
                  "confirm": "", "quit": False}
        nev = _parancs_nev(cmd.get("line", ""))
        muvelet = cmd.get("op")
        if now - float(cmd.get("ts") or 0) > MAX_AGE_SEC:
            valasz["lines"] = [_t("channel.stale")]
            valasz["reason"] = "stale"
        elif muvelet:
            fn = (ops or {}).get(muvelet)
            if fn is None:
                valasz["lines"] = [_t("channel.not_allowed", name=muvelet)]
                valasz["reason"] = "not_allowed"
            else:
                try:
                    eredmeny = fn(**(cmd.get("args") or {}))
                    valasz.update(ok=eredmeny is not False and eredmeny is not None,
                                  result=eredmeny)
                except Exception as ex:             # a motort nem viheti el
                    valasz["lines"] = [_t("channel.error", error=ex)]
                    valasz["reason"] = "error"
        elif nev not in ALLOWED:
            valasz["lines"] = [_t("channel.not_allowed", name=nev)]
            valasz["reason"] = "not_allowed"
        else:
            try:
                r = C.dispatch(ctx, cmd["line"], confirmed=bool(cmd.get("confirmed")))
                valasz.update(ok=bool(r.ok), lines=list(r.lines or []),
                              confirm=r.confirm or "", quit=bool(r.quit))
            except Exception as ex:                 # a motort nem viheti el
                valasz["lines"] = [_t("channel.error", error=ex)]
                valasz["reason"] = "error"
        try:
            ES.write(valasz, ob / f"{cmd['id']}.json")
        except Exception:
            pass
        kesz.append(valasz)
    return kesz


class Processor:
    """Háttérszál a motorban: `POLL_SEC`-enként feldolgozza a postaládát.
    `on_quit()` a távoli leállításkor hívódik (a motor rendes kilépése)."""

    def __init__(self, ctx, profile, on_quit=lambda: None, period=POLL_SEC,
                 inbox=None, outbox=None, ops: dict | None = None):
        self.ctx, self.profile, self.on_quit = ctx, profile, on_quit
        self.period = period
        self._dirs = {"inbox": inbox, "outbox": outbox}
        self.ops = dict(ops or {})
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._fut, daemon=True,
                                   name="EngineChannel")

    def _fut(self):
        while not self._stop.is_set():
            try:
                kesz = process_once(self.ctx, self.profile, ops=self.ops, **self._dirs)
            except Exception:
                kesz = []
            if any(v.get("quit") for v in kesz):
                self._stop.set()
                self.on_quit()
                return
            self._stop.wait(self.period)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._stop.set()
