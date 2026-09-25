"""
KIMENT-E A JELZÉS? — a Telegram-kézbesítés DÖNTÉSÉNEK naplója.

A felhasználó látta (2026-09-25): a Jelzések fül „Kiküldött jelzések" címmel
mutatott három jelzést, a Telegramra viszont egyik sem érkezett meg. Az ok a
csendes óra volt (22:00–07:00, helyi idő) — ez SZÁNDÉKOS, de a fül ebből
semmit nem mutatott, tehát a felhasználó hibát keresett.

Ez a modul rögzíti, MI LETT a jelzés értesítésével, abban a pillanatban,
amikor eldőlt (`core.notify.trade_event`):

    sent    — kiment (sorba került, vagy a jóváhagyó ajánlat ment ki)
    quiet   — csendes óra: a jelzés szándékosan elveszett
    muted   — a pár/stratégia értesítése ki van kapcsolva
    off     — az értesítés nincs beállítva (nincs token / címzett)
    dropped — a küldő sor tele volt, eldobva

⚠ KÜLÖN FÁJL, NEM ÚJ OSZLOP a `trades.csv`-ben. Egy új oszlop a meglévő
naplót egyszer TELJESEN ÁTÍRNÁ (a `log_trade` sémamigrációja) — az a kötések
auditnyoma, és egy félbeszakadt átírás mindent vinne. Ez a fájl csak
HOZZÁFŰZ, és a kulcsa ugyanaz az időbélyeg, amit a `trades.csv` sora kap.

⚠ Csak a DÖNTÉST rögzíti, a hálózati kézbesítést nem: a „sent" azt jelenti,
hogy a program elküldte. Ha a Telegram utána elutasítja, az a naplóban látszik
(`telegram: a küldés nem sikerült`).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "signal_delivery.csv"

SENT, QUIET, MUTED, OFF, DROPPED = "sent", "quiet", "muted", "off", "dropped"
STATUSES = (SENT, QUIET, MUTED, OFF, DROPPED)
_FEJ = ["time", "symbol", "strategy", "status"]


def key(time_iso, symbol, strategy) -> tuple:
    return (str(time_iso or ""), str(symbol or ""), str(strategy or ""))


def record(time_iso, symbol, strategy, status: str) -> None:
    """Egy döntés hozzáfűzése. ⚠ SOSEM DOB: a napló-írás hibája nem viheti el
    a jelzés naplózását (a hívó a `log_trade` útján van)."""
    if status not in STATUSES:
        return
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        uj = not PATH.exists()
        with open(PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if uj:
                w.writerow(_FEJ)
            w.writerow([str(time_iso or ""), str(symbol or ""),
                        str(strategy or ""), status])
    except Exception:
        log.debug("signal_delivery: a rögzítés kimaradt", exc_info=True)


def load() -> dict:
    """`{(idő, pár, stratégia): állapot}` — a fül ebből olvas. Hiba → üres."""
    out = {}
    if not PATH.exists():
        return out
    try:
        with open(PATH, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[key(r.get("time"), r.get("symbol"), r.get("strategy"))] = \
                    r.get("status") or ""
    except Exception:
        log.debug("signal_delivery: az olvasás kimaradt", exc_info=True)
    return out
