"""
Korreláció-/devizakitettség-védelem.

Minden pozíciót devizákra bont (EURUSD BUY = +EUR / −USD). Két instrumentum
akkor "korrelált", ha LEGALÁBB egy devizában AZONOS irányú kitettséget halmoz
(pl. EURUSD BUY és GBPUSD BUY is short-USD). Így nem kell korrelációs listát
karbantartani, és az indok jól megmagyarázható ("halmozott short-USD").

A K-mód GLOBÁLIS, 4 állapotú, és perzisztens (data/correlation_mode.json), hogy
a felület gombja a mérvadó, látható igazság legyen — nem egy elfeledett config-flag.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PATH = Path(__file__).resolve().parents[1] / "data" / "correlation_mode.json"

# Állapotok (a K gomb körbe lépteti)
# ⚠ AZONOSÍTÓ, NEM FELIRAT (0011). Korábban a magyar szó VOLT az érték
# (`INACTIVE = "Inaktív"`), és ez az érték **lemezre is kerül**
# (`data/correlation_mode.json`). Két baja volt:
#
#   • lefordíthatatlan — a felirat megváltoztatása a MENTETT ÁLLAPOTOT
#     érvénytelenítette volna (a `load()` csak a `MODES`-ban lévőt fogadja el,
#     tehát a régi mentés némán visszaesett volna az alapértelmezésre);
#   • kódolás-érzékeny — az „Inaktív" ékezete egy más kódolású gépen máshogy
#     jön vissza, és ugyanaz a néma visszaesés történik.
#
# Ugyanaz a szétválasztás, mint a paraméter-kategóriáknál: az ÉRTÉK azonosító,
# a felirat az i18n-ből jön (`corr_mode.*`).
INACTIVE = "inactive"
ALERT    = "alert"          # csak jelöl/villog, nem avatkozik be
STRONGER = "stronger"       # korrelált újat blokkol (az erősebb nyit elsőként)
HALF     = "half"           # korrelált pozíció fele mérettel
MODES = [INACTIVE, ALERT, STRONGER, HALF]

# A RÉGI (magyar felirat) mentések beolvasása. ⚠ Enélkül egy meglévő
# `correlation_mode.json` NÉMÁN elveszne, és a mód visszaugrana `alert`-re.
_LEGACY_MODE = {"Inaktív": INACTIVE, "Jelző": ALERT,
                "Csak erősebb": STRONGER, "Fél méret": HALF}


def mode_label(mode: str) -> str:
    """A mód FELIRATA a felülethez (az i18n-ből; ismeretlennél maga az azonosító)."""
    from core.i18n import t as _t
    kulcs = f"corr_mode.{mode}"
    felirat = _t(kulcs)
    return felirat if felirat and felirat != kulcs else str(mode)

_lock = threading.Lock()
_mode = ALERT   # alap: csak jelez, semmit nem tilt csendben


def load() -> str:
    global _mode
    with _lock:
        try:
            if PATH.exists():
                with open(PATH, encoding="utf-8") as f:
                    m = json.load(f).get("mode")
                m = _LEGACY_MODE.get(m, m)     # régi, magyar feliratú mentés
                if m in MODES:
                    _mode = m
        except Exception as ex:
            log.error("%s: a korrelációs mód NEM OLVASHATÓ (%s) — az "
                      "alapértelmezett mód marad érvényben.", PATH.name, ex)
        return _mode


def get_mode() -> str:
    with _lock:
        return _mode


def set_mode(mode: str):
    global _mode
    mode = _LEGACY_MODE.get(mode, mode)
    if mode not in MODES:
        return
    with _lock:
        _mode = mode
        _save_locked()


def cycle() -> str:
    """A következő állapotra lép (gombnyomásra) és menti."""
    global _mode
    with _lock:
        _mode = MODES[(MODES.index(_mode) + 1) % len(MODES)]
        _save_locked()
        return _mode


def _save_locked():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"mode": _mode}, f, indent=2, ensure_ascii=False)
        tmp.replace(PATH)
    except Exception as ex:
        log.error("%s: a korrelációs mód MENTÉSE nem sikerült (%s). A beállítás "
                  "csak a memóriában él — újraindítás után elveszik.",
                  PATH.name, ex)


# ---------------------------------------------------------------------------
# Devizakitettség
# ---------------------------------------------------------------------------

def pair_currencies(symbol: str) -> Optional[tuple]:
    """(base, quote) ha a szimbólum 6 betűs devizapár (pl. EURUSD, XAUUSD),
    egyébként None (index/egyéb — ezekre nem alkalmazunk deviza-halmozást)."""
    s = symbol.upper()
    if len(s) == 6 and s.isalpha():
        return s[:3], s[3:]
    return None


def exposure(symbol: str, direction: str) -> dict:
    """{deviza: +1/−1} kitettség. BUY: +base/−quote, SELL: −base/+quote."""
    cc = pair_currencies(symbol)
    if not cc:
        return {}
    base, quote = cc
    if direction == "BUY":
        return {base: +1, quote: -1}
    if direction == "SELL":
        return {base: -1, quote: +1}
    return {}


def shared_exposure(symbol: str, direction: str, others: list) -> list:
    """A jelölttel AZONOS irányú deviza-kitettséget halmozó instrumentumok.

    others: [(symbol, direction), ...] (a saját szimbólumot ne tartalmazza).
    Visszaad: a halmozó szimbólumok listája (üres = nincs ütközés).
    """
    cand = exposure(symbol, direction)
    if not cand:
        return []
    out = []
    for osym, odir in others:
        if osym == symbol:
            continue
        oexp = exposure(osym, odir)
        for ccy, sign in cand.items():
            if ccy in oexp and (oexp[ccy] > 0) == (sign > 0):
                out.append(osym)
                break
    return out
