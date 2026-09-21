"""NAPI VESZTESÉG-LIMIT — az érték ÉS a mód egy helyen.

⚠ MIÉRT KÜLÖN MODUL. A limit értékét eddig egy függvény adta
(`trading.backtest.daily_limit_usd`), a MÓDJA viszont sehol nem volt kimondva:
implicit módon az `usd > 0` jelentette a „fix összeg" módot. Ez működött, amíg
csak a motor olvasta — de amint a felületen is ÁLLÍTANI kell, a hívónak tudnia
kell, MELYIK dimenziót állítja. Egy ▼ gomb, ami hol dollárt, hol százalékot
léptet, anélkül hogy bárhol le volna írva, melyiket mikor, pontosan az a néma
viselkedés, ami ebben a projektben visszatérő hibaosztály.

── A KÉT MÓD ──────────────────────────────────────────────────────────────
  FIX   `trading.daily_loss_limit_usd > 0`  → a limit ez az összeg, a számlától
        függetlenül. A `_pct` ilyenkor HOLT kulcs (a `config_check` szól is érte).
  PCT   `trading.daily_loss_limit_usd == 0` → a limit `_pct × egyenleg`, tehát
        EGYÜTT MOZOG a számlával.

⚠ MIÉRT SZÁMÍT A KÜLÖNBSÉG. A kockázati modell többi része százalékos
(`account_risk_pct`): egy kötés az egyenleg adott hányadát kockáztatja. Ha a napi
plafon fix összeg, akkor a „hány vesztes kötés fér bele egy napba" arány NÉMÁN
vándorol, ahogy a számla nő vagy csökken. 962 € egyenlegnél egy 90 $-os plafon a
számla ~9%-a (≈23 kötés) — vagyis nem véd; 22 500 $-nál ugyanaz a 90 $ már EGY
kötés kockázata alatt van — vagyis az első veszteség lezárja a napot. Ugyanaz a
szám, két ellentétes hiba.

⚠ A MÓDVÁLTÁS NEM UGORHAT. Váltáskor az ÉRTÉKET visszük át (a mostani effektív
limitet), nem az alapértelmezést: aki átkapcsol, ne kapjon mellé egy észrevétlen
limit-változást is. Utána már a választott dimenzió szerint mozog.

⚠ TISZTA MODUL: csak a `trading` config-szótárral dolgozik. A mentés a hívóé.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MODE_FIX = "fix"       # rögzített összeg
MODE_PCT = "pct"       # az egyenleg százaléka

KULCS_USD = "daily_loss_limit_usd"
KULCS_PCT = "daily_loss_limit_pct"

# A `_pct` alapértéke, ha a config nem mond semmit (a régi viselkedés).
ALAP_PCT = 0.015

# A felületi léptetés határai — a limit se ne legyen nevetségesen kicsi, se
# akkora, hogy ne legyen limit.
MIN_USD, LEPES_USD = 10.0, 10.0
MIN_PCT, MAX_PCT, LEPES_PCT = 0.001, 0.20, 0.001


def _szam(nyers, alap: float = 0.0) -> float:
    try:
        return float(nyers)
    except (TypeError, ValueError):
        return alap


def mode(trading_cfg: dict) -> str:
    """`fix` vagy `pct` — MELYIK dimenzió az érvényes."""
    return MODE_FIX if _szam((trading_cfg or {}).get(KULCS_USD)) > 0 else MODE_PCT


def pct_of(trading_cfg: dict) -> float:
    """A beállított százalék (akkor is, ha épp `fix` módban vagyunk)."""
    v = _szam((trading_cfg or {}).get(KULCS_PCT), ALAP_PCT)
    return v if v > 0 else ALAP_PCT


def value(trading_cfg: dict, balance: float) -> float:
    """A limit ÉRTÉKE a számla pénznemében — EGY igazságforrás.

    ⚠ Ez a függvény a motoré, a backteszté ÉS a felületé. Ha bármelyik a sajátját
    számolná, a fejléc mást mutatna, mint amit a motor betart."""
    usd = _szam((trading_cfg or {}).get(KULCS_USD))
    if usd > 0:
        return usd
    return _szam(balance) * pct_of(trading_cfg)


def set_fix(trading_cfg: dict, usd: float) -> float:
    """Átállás FIX módra a megadott összeggel. Visszaad: a beállított érték."""
    v = max(MIN_USD, round(_szam(usd) / LEPES_USD) * LEPES_USD)
    trading_cfg[KULCS_USD] = float(v)
    return v


def set_pct(trading_cfg: dict, pct: float) -> float:
    """Átállás SZÁZALÉK módra. Visszaad: a beállított százalék.

    ⚠ Az `usd` kulcsot 0-ra állítjuk, nem töröljük: a 0 KIMONDJA, hogy nincs fix
    összeg. Egy hiányzó kulcs ugyanezt jelentené, de a fájlból nem derülne ki,
    hogy ez döntés volt-e vagy felejtés."""
    v = min(MAX_PCT, max(MIN_PCT, round(_szam(pct, ALAP_PCT), 4)))
    trading_cfg[KULCS_PCT] = float(v)
    trading_cfg[KULCS_USD] = 0.0
    return v


def step(trading_cfg: dict, balance: float, irany: int) -> float:
    """Egy lépés ▼/▲ az ÉPPEN ÉRVÉNYES dimenzióban. Visszaad: az új limit-érték.

    ⚠ A GOMB MINDIG AZT LÉPTETI, AMI LÁTSZIK. Fix módban dollárt, százalék
    módban százalékot — a felirat pedig kiírja, melyiket."""
    if mode(trading_cfg) == MODE_FIX:
        set_fix(trading_cfg, value(trading_cfg, balance) + irany * LEPES_USD)
    else:
        set_pct(trading_cfg, pct_of(trading_cfg) + irany * LEPES_PCT)
    return value(trading_cfg, balance)


def toggle(trading_cfg: dict, balance: float) -> str:
    """Módváltás — az ÉRTÉK megtartásával. Visszaad: az új mód.

    ⚠ NEM UGRIK A LIMIT. `pct → fix`: a mostani effektív összeg lesz a fix
    érték. `fix → pct`: a mostani összeg az egyenleg hányadaként megy át. Aki
    átkapcsol, ne kapjon mellé egy észrevétlen szigorítást vagy lazítást."""
    most = value(trading_cfg, balance)
    if mode(trading_cfg) == MODE_FIX:
        egyenleg = _szam(balance)
        if egyenleg <= 0:
            # ⚠ EGYENLEG NÉLKÜL NEM SZÁMOLUNK ARÁNYT. Nulla egyenlegnél a
            # „hány százalék" kérdésnek nincs értelme; maradunk fixen, és szólunk.
            log.warning("core.daily_limit: nincs ismert egyenleg — a százalékos "
                        "módra váltás kimaradt")
            return MODE_FIX
        set_pct(trading_cfg, most / egyenleg)
        return MODE_PCT
    set_fix(trading_cfg, most)
    return MODE_FIX
