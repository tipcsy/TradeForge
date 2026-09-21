"""A BUROK — meddig mehet el a karmester MAGÁTÓL.

⚠ A FOK ÉS A BUROK NEM UGYANAZ. Az autonómia-fok (`conductor/autonomy.py`) azt
mondja meg, kell-e EMBERI PIPA. A burok azt, MEDDIG mehet el a gép, ha nem kell.
A terv szerint a burok L4-en is a helyén marad — „különben nem autonómia, hanem
felügyelet nélküli szabadesés". Egy elszálló visszacsatolási hurkot nem a fok
állít meg, hanem a kvóta.

⚠ MIÉRT KÜLÖN MODUL, ÉS NEM AZ `actions.py`-BAN. Az `actions.apply` a
VÉGREHAJTÁS: ugyanazt csinálja, akár te nyomtad meg, akár a gép. A burok viszont
CSAK a gépre vonatkozik — te a saját kvótádat nem lépheted túl, mert nincs
kvótád. Ha a kettő egy helyen élne, előbb-utóbb a kézi elfogadás is beleütközne
egy „napi keret elfogyott" üzenetbe, ami értelmetlen.

── AZ AKCIÓK OSZTÁLYAI ────────────────────────────────────────────────────
  L2 (SEGÍTETT)     `set_mode_signal` — kockázatCSÖKKENTŐ ÉS visszafordítható:
                    a cella „csak jelzés"-re áll, a pénz kikapcsol, és a
                    visszaút egyetlen parancs.
  L3 (KORLÁTOZOTT)  `queue_optimize` — nem mozgat pénzt, de a paraméterkészlet
                    felülírása NEM VONHATÓ VISSZA (nincs mentés a régiről).
                    Ezért nem fér bele az L2 „visszafordítható" ígéretébe.
  SOHA              `set_mode_live` — a PÉNZT BEKAPCSOLÓ lépés emberi
                    jóváhagyáshoz kötött, autonómia-szinttől FÜGGETLENÜL
                    (`Proposal.needs_human`). L4 sem oldja fel.

── A KAPUK, EBBEN A SORRENDBEN ────────────────────────────────────────────
  1. `needs_human`   — a pénzt bekapcsoló lépés sosem gépi
  2. `not_machine`   — ismeretlen akció: nincs gépi osztálya
  3. `level`         — a CELLA foka nem éri el az akció szintjét
  4. `config_warn`   — a `config_check` WARN írás-tiltó (a terv invariánsa)
  5. `position_open` — nyitott pozíció a páron
  6. `cooldown`      — ezen a cellán túl frissen lépett a gép
  7. `daily_quota`   — a napi keret elfogyott

⚠ A SORREND SZÁNDÉKOS: az OKA a leginkább „végleges" elutasítástól halad a
leginkább átmeneti felé. Amit visszaadunk, az az ELSŐ ok — és az kerül a
naplóba is. Ha a kvóta lenne elöl, egy soha-nem-gépi akciónál is azt látnád,
hogy „elfogyott a keret", és holnap újra várnád.

⚠ TISZTA MODUL: a config, a krónika és a hívótól kapott pozíció-lekérdezés.
Se MT5, se felület.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from conductor import autonomy as _au
from conductor import config as _ccfg
from conductor import journal as _j
from conductor.proposals import (MONEY_ON, QUEUE_OPTIMIZE, SET_MODE_LIVE,
                                 SET_MODE_SIGNAL)

log = logging.getLogger(__name__)

# ── OKOK (stabil kódok — a felirat ezekből fordul) ──────────────────────
OK_NEEDS_HUMAN   = "needs_human"
OK_NOT_MACHINE   = "not_machine"
OK_LEVEL         = "level"
OK_CONFIG_WARN   = "config_warn"
OK_POSITION_OPEN = "position_open"
OK_COOLDOWN      = "cooldown"
OK_DAILY_QUOTA   = "daily_quota"
OK_IRREVERSIBLE  = "irreversible"

# ── MELYIK AKCIÓ MILYEN FOKTÓL GÉPI ─────────────────────────────────────
MIN_SZINT = {
    SET_MODE_SIGNAL: _au.ASSISTED,     # L2 — kockázatcsökkentő ÉS visszafordítható
    QUEUE_OPTIMIZE:  _au.LIMITED,      # L3 — a paraméter-felülírás nem visszavonható
    # `set_mode_live` SZÁNDÉKOSAN NINCS ITT: a `needs_human` kapu előbb fog.
}

# Ma egyik gépi akció sem visszavonhatatlan a „pozíciózárás" értelmében; a
# kapcsoló (`allow_irreversible`) azért van, hogy amikor lesz ilyen akció, ne
# kelljen új fogalmat bevezetni hozzá.
IRREVERZIBILIS = frozenset()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def machine_actions(cfg: dict, *, hours: float = None, symbol: str = None,
                    strategy: str = None) -> list:
    """A GÉPI lépések a krónikából, legújabb elöl.

    ⚠ A KRÓNIKA AZ EGYETLEN IGAZSÁGFORRÁS. A kvótát és a türelmi időt abból
    számoljuk, ami TÉNYLEG megtörtént — nem egy külön számlálóból, ami a motor
    újraindulásakor lenullázódna, és a kvóta némán újraindulna vele."""
    k = _ccfg.journal(cfg)
    ora = float(hours) if hours else 24.0 * 8
    hatar = _now() - timedelta(hours=ora)
    # ⚠ A NAP-SZŰRŐ csak durva előszűrés (a krónika naponta tagolt); a pontos
    # határt az időbélyegen húzzuk meg.
    nap = (hatar - timedelta(days=1)).strftime("%Y-%m-%d")
    ki = []
    for sor in _j.read(limit=2000, kind=_j.KIND_ACTION, symbol=symbol,
                       since_day=nap,
                       max_scan_lines=int(k["max_scan_lines"])):
        if ((sor.get("data") or {}).get("by") or "") != "conductor":
            continue
        if strategy and sor.get("strategy") != strategy:
            continue
        t = _ts(sor.get("ts"))
        if t is None or t < hatar:
            continue
        ki.append(sor)
    return ki


def _mai_gepi(cfg: dict) -> int:
    """Hány gépi változtatás volt MA (UTC nap)."""
    ma = _now().strftime("%Y-%m-%d")
    return sum(1 for s in machine_actions(cfg, hours=48)
               if str(s.get("day") or "") == ma)


def _config_warn(cfg: dict) -> bool:
    """Van-e WARN szintű config-lelet? ⚠ A terv invariánsa: WARN mellett a
    karmester NEM ír. Hiba esetén IGAZAT adunk — a kétely a nem-cselekvés felé
    billen."""
    try:
        from core import config_check as _cc
        return any(f.get("level") == _cc.WARN for f in (_cc.check(cfg) or []))
    except Exception:
        log.warning("conductor.governor: a config-ellenőrzés nem fut le — "
                    "BIZTONSÁGBÓL írás-tiltónak vesszük", exc_info=True)
        return True


def min_level(action: str) -> "int | None":
    """Melyik foktól gépi ez az akció? `None` = sosem."""
    if action in MONEY_ON:
        return None
    return MIN_SZINT.get(action)


def allowed(cfg: dict, entry: dict, *, positions=None) -> tuple:
    """Végrehajthatja-e a GÉP ezt a postaláda-tételt? → `(igen, ok_kód)`.

    `positions() -> list`: a nyitott pozíciók (a hívó adja be; a modul nem
    nyúl a brókerhez). Hiányában a pozíció-szabály NEM ad felmentést: ha nem
    tudjuk, van-e pozíció, nem lépünk.

    ⚠ HIBA ESETÉN NEM. Ez a „fail closed" szabály: amit nem tudunk
    ellenőrizni, azt nem hajtjuk végre magunktól."""
    try:
        return _allowed(cfg, entry, positions)
    except Exception as ex:                                  # pragma: no cover
        log.warning("conductor.governor: a burok-ellenőrzés elszállt "
                    "(%s/%s): %s", entry.get("symbol"), entry.get("strategy"), ex)
        return (False, OK_NOT_MACHINE)


def _allowed(cfg: dict, entry: dict, positions) -> tuple:
    akcio = entry.get("action") or ""
    sym = entry.get("symbol") or ""
    strat = entry.get("strategy") or ""
    k = _ccfg.autonomy(cfg)

    # 1. ⚠ A PÉNZT BEKAPCSOLÓ LÉPÉS SOSEM GÉPI — a fokra rá sem nézünk.
    if akcio in MONEY_ON or entry.get("needs_human"):
        return (False, OK_NEEDS_HUMAN)

    # 2. Ismeretlen akció: nincs gépi osztálya.
    also = MIN_SZINT.get(akcio)
    if also is None:
        return (False, OK_NOT_MACHINE)

    # 3. A CELLA foka.
    if _au.level(cfg, sym, strat) < also:
        return (False, OK_LEVEL)

    # 4. ⚠ Vissza nem vonható akció külön kapcsolón — L4 SEM oldja fel magától.
    if akcio in IRREVERZIBILIS and not k["allow_irreversible"]:
        return (False, OK_IRREVERSIBLE)

    # 5. ⚠ `config_check` WARN → ÍRÁS-TILTÓ. Ha a config maga gyanús, a
    #    karmester nem épít rá döntést.
    if _config_warn(cfg):
        return (False, OK_CONFIG_WARN)

    # 6. NYITOTT POZÍCIÓ. ⚠ Ha nem tudjuk megkérdezni, nem lépünk.
    if k["no_change_while_position_open"]:
        try:
            nyitott = any(str(p.get("symbol")) == sym
                          for p in (positions() if positions else []))
        except Exception:
            log.warning("conductor.governor: a pozíciók nem kérdezhetők le — "
                        "nem lépünk", exc_info=True)
            return (False, OK_POSITION_OPEN)
        if positions is None or nyitott:
            return (False, OK_POSITION_OPEN)

    # 7. TÜRELMI IDŐ a cellán.
    ora = float(k["cooldown_hours_per_cell"])
    if ora > 0 and machine_actions(cfg, hours=ora, symbol=sym, strategy=strat):
        return (False, OK_COOLDOWN)

    # 8. NAPI KERET. ⚠ A `0` (és a negatív) KORLÁTLAN — ezt a terv mondja ki
    #    (L4-en 0 = korlátlan). Veszélyes érték, ezért a `karmester` kiírása
    #    NÉVVEL mondja ki, hogy nincs plafon: némán nem maradhat.
    kvota = int(k["max_changes_per_day"])
    if kvota > 0 and _mai_gepi(cfg) >= kvota:
        return (False, OK_DAILY_QUOTA)

    return (True, "")


def quota_state(cfg: dict) -> dict:
    """`{used, limit, unlimited}` — a napi keret állása (a kijelzéshez)."""
    kvota = int(_ccfg.autonomy(cfg)["max_changes_per_day"])
    return {"used": _mai_gepi(cfg), "limit": kvota, "unlimited": kvota <= 0}
