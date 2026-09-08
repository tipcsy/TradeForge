"""
Kockázatcsökkentő technikák — presetek + LOT-LÉTRA feloldás (stratégia-független).

A megbeszélt 3 tengely (lásd Obsidian: Kockázatcsökkentés.md):
  1. Belépő méret            : normál | felezett (óvatos)      → wants_cautious_size
  2a. Részleges zárás 1R-nél : Ki | 50% (Felező) | 75% (Pajzs) → target_fraction
  2b. (maradék) stop         : marad TÁVOL | BE | Trailing      → runner_stop

Ez a modul TISZTA logika (nincs MT5/backtest/tkinter függés): adott preset + a
pozíció aktuális lotja → mit tegyünk (mennyit zárjunk le, mi a runner stopja),
a **lot-létrával degradálva**. A motor (backtest + live) ezt hívja 1R elérésekor.

KRITIKUS invariáns: a részleges zárás mindig **≥ 50%**, különben — ha az ár
visszafordul és kistoppol — a lezárt fél nyeresége NEM fedezi a maradék
veszteségét, azaz nettó MÍNUSZ lenne (pont a lényeg veszne el). Ha a pozíció
túl kicsi ahhoz, hogy ≥50%-ot lezárva a runner ≥ min_lot maradjon → nincs
részleges zárás, a hívó BE-húzásra (Risky) esik vissza.
"""

from __future__ import annotations

from core.i18n import t as _t

import logging
import math
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Presetek (2a tengely fő értékei + a Risky mint kombináció) ──────────────
#
# ⚠ A `PRESET_OFF` NEVE FÉLREVEZETŐ VOLT, ezért a CÍMKÉJE megváltozott (v1.96.0):
# ez a preset SOSEM jelentett „semmit" — mindig futtatta a költség-tudatos
# breakevent és a trailinget (`_manage_position` → `_update_stops`). A KULCS
# szándékosan `off` MARADT: az átnevezés így nem változtat semmit sem a mentett
# `data/risk_mode.json`-ban, sem a viselkedésben.
#
# Aki tényleg semmit nem akar (a stop marad, ahol a belépéskor volt — pl. a nyers
# stratégia-él méréséhez), az a ÚJ `PRESET_NONE`-t válassza.
PRESET_NONE    = "none"      # TÉNYLEG semmi: a stop marad a helyén
PRESET_OFF     = "off"       # BE + trailing (a „legkisebb" kockázatcsökkentés)
PRESET_RISKY   = "risky"     # óvatos méret + BE-húzás (NINCS részleges zárás)
PRESET_HALVING = "halving"   # Felező: 50% zár 1R-nél
PRESET_SHIELD  = "shield"    # Pajzs: 75% zár 1R-nél
PRESET_FIBO    = "fibo"      # Fibo: stop-húzás a belépő→TP táv 61,8%-ánál (nincs zárás)
PRESET_THIRDS  = "thirds"    # Harmados (1/3–2/3): R-alapú stop-létra (nincs zárás)
# Pajzs↔Fibo auto (tananyag 3. pont): alaphelyzetben PAJZS; NAGY mozgásnál
# (ATR >> átlag a belépéskor) FIBO — hagyjuk futni, később húzunk stopot.
PRESET_SHIELD_FIBO = "shield_fibo"
PRESETS = (PRESET_NONE, PRESET_OFF, PRESET_RISKY, PRESET_HALVING, PRESET_SHIELD,
           PRESET_FIBO, PRESET_THIRDS, PRESET_SHIELD_FIBO)

# ── runner-stop (2b tengely) ────────────────────────────────────────────────
RUNNER_KEEP      = "keep"        # marad a TÁVOLI (eredeti) stop — a videó Pajzsa
RUNNER_BREAKEVEN = "breakeven"   # a maradék stopja a nyitóra (óvatosabb)
RUNNER_TRAILING  = "trailing"    # a maradék trailinggel fut
RUNNER_EXIT      = "exit"        # a maradékot KISZÁLLÁSI JELRE zárjuk (core.exit_signal)

_EPS = 1e-9


# ── A BE + trailing paraméterei — ITT laknak, nem a stratégiánál ────────────
#
# MIÉRT ITT (v1.96.0): ezek a kimenet-menedzsment paraméterei, tehát a
# kockázatcsökkentésé. Korábban a közös végrehajtási configban voltak
# (`core/execution_params.py`), és a Stratégia Paraméterek ablak „Végrehajtás"
# kategóriájában jelentek meg — MINDEN stratégiánál, MINDEN preseten. Csakhogy a
# preset dönti el, hogy egyáltalán HATNAK-e:
#
#   preset                              | breakeven_pct | trail_activation | trail_distance
#   ------------------------------------|---------------|------------------|----------------
#   none                                |       —       |        —         |       —
#   off  (= BE + trailing)              |       ✔       |        ✔         |       ✔
#   risky                               |  — (azonnali) |   — (azonnali)   |   ✔ (×0,5)
#   halving/shield + runner=trailing    |       —       |        ✔         |       ✔
#   halving/shield + runner=keep/BE     |       —       |        —         |       —
#   fibo / thirds                       |       —       |        —         |       —
#
# Fibo vagy Harmados preseten tehát a három érték HALOTT volt: szerkeszthetőnek
# látszott, és semmit nem csinált. Ugyanaz a hibafajta, mint a `max_open_slots`
# a stratégia-paraméterek közt.
BE_TRAIL_KEYS = ("breakeven_pct", "trail_activation_atr", "trail_distance_atr")

# ── A RÉSZLEGES ZÁRÁS paraméterei (Felező / Pajzs) ──────────────────────────
# ⚠ Ezek eddig CSAK a fájlból voltak állíthatók, a felületről nem — pedig a
# `trigger_R` dönti el, MIKOR zár a Pajzs. Ha a TP ugyanoda esik (tp_rr_ratio ==
# trigger_R), a részleges zárás SOHA nem hat: a célár előbb ér oda, és a teljes
# pozíciót zárja. Élesben pontosan ez történt (tp_rr_ratio = 1,0, trigger_R =
# 1,0): a Pajzs be volt kapcsolva, és semmit nem csinált.
PARTIAL_KEYS = ("trigger_R", "halving_fraction", "shield_fraction")


def partial_active(preset: str) -> set:
    """MELY részleges-zárás kulcsok hatnak ezen a preseten?

    Ugyanaz az elv, mint a `be_trail_active`-nál: a felület ez alapján dönti el,
    mit MUTAT, így egy hatástalan mező nem kelti azt a látszatot, hogy állítható.
    A Felező a `halving_fraction`-t használja, a Pajzs a `shield_fraction`-t —
    mindkettő a `trigger_R`-nél lép életbe."""
    if preset == PRESET_HALVING:
        return {"trigger_R", "halving_fraction"}
    if preset in (PRESET_SHIELD, PRESET_SHIELD_FIBO):
        return {"trigger_R", "shield_fraction"}
    return set()


def be_trail_active(preset: str, runner_stop: str = RUNNER_TRAILING) -> set:
    """MELY BE/trailing kulcsok hatnak ezen a preset+runner kombináción?

    A felület ez alapján dönti el, mit MUTAT (a nem ható paraméter ne zavarjon
    bele a listába), az optimalizáló pedig ez alapján, mit KERESSEN (a hatástalan
    dimenzió elpazarolt trial). Egy igazságforrás mindkettőnek."""
    if preset == PRESET_OFF:
        return set(BE_TRAIL_KEYS)
    if preset == PRESET_RISKY:
        # A risky azonnal BE-zik és azonnal trailel — csak a TÁVOLSÁG számít.
        return {"trail_distance_atr"}
    if preset in (PRESET_HALVING, PRESET_SHIELD, PRESET_SHIELD_FIBO):
        if runner_stop == RUNNER_TRAILING:
            return {"trail_activation_atr", "trail_distance_atr"}
        return set()
    return set()          # none / fibo / thirds → egyik sem


def default_config() -> dict:
    """A kalibrációs paraméterek alapértékei (a per-pár állapot felülírja)."""
    return {
        # ── BE + trailing (lásd BE_TRAIL_KEYS / be_trail_active) ──
        "breakeven_pct":        0.5,        # a TP hány %-ánál megy az SL a belépőre (0 = ki)
        # ⚠ KÖLTSÉG-TUDATOS BREAKEVEN. A stop PONTOSAN a nyitóárra állítva a
        # kötés árban nullán zár, de a jutalék+swap után MÍNUSZBAN — vagyis a
        # "kockázatmentes" pozíció valójában kis veszteséget garantál. Ez a
        # puffer (a spread hányszorosa, PONTBAN a hívó adja) a stopot annyival
        # a nyitó FÖLÉ (BUY) / ALÁ (SELL) teszi, hogy tényleg 0 vagy kicsit
        # pozitív legyen. 0.0 = a régi viselkedés, bitazonosan.
        "be_buffer_points":     0.0,
        # ⚠ A BE KÜSZÖBE R-BEN — ha > 0, FELÜLÍRJA a `breakeven_pct`-et.
        #
        # MIÉRT KELL (mérve 2026-09-08). A `breakeven_pct` a CÉLÁR százaléka:
        # `be_trigger = open + (tp − open) × breakeven_pct`. Amíg a célár 2–3 R
        # volt, ez rendben működött. A célár-tartomány felnyitása után viszont az
        # optimalizáló 16/16 páron HOSSZÚ célárat választott (9,5–15,0 R), és a
        # 0,5-ös szorzóval a BE 7,25 R-re került — amit gyakorlatilag egy kötés
        # sem ér el. A trailing pedig a `risk_free`-hez van kötve, tehát AZ IS
        # meghalt. Vagyis a hosszú célár NÉMÁN kikapcsolta a kimenet-kezelést.
        # Mérve, 14 pár, OOS: BE ~7 R → −0,3198 R/kötés; BE 1 R → −0,2234.
        # A csatolás ára +0,166 R/kötés.
        #
        # `0.0` (alap) = a régi viselkedés BITAZONOSAN — a `breakeven_pct` dönt.
        "breakeven_r":          0.0,
        "trail_activation_atr": 0.5,        # ennyi ATR profit UTÁN indul a trailing
        "trail_distance_atr":   0.4,        # ennyi ATR-rel követ
        "trigger_R":        1.0,            # hány R-nél lép életbe a részleges zárás
        "halving_fraction": 0.5,            # Felező: a pozíció mekkora részét zárja
        "shield_fraction":  0.75,           # Pajzs: a nagyobb rész
        # A runner alapból TRAILINGgel fut (backteszt: alacsonyabb DD, azonos hozam,
        # mint a 'keep' távoli stop). A tiszta videó-Pajzs a 'keep' — haladó opció.
        "runner_stop":      RUNNER_TRAILING,
        # Fibo preset: a belépő→TP távra húzott Fibonacci. A trigger a fibo_level
        # pontján (tananyag: 61,8%); a stop a fibo_stop_level szintre áll
        # (0.0 = breakeven; variánsok: 0.236 / 0.382 — bezárt rész-profit).
        "fibo_level":       0.618,
        "fibo_stop_level":  0.0,
        # Harmados (1/3–2/3, „Birger") preset: az alap-táv R-ben. A tananyag
        # 1,5R-rel számol (távoli, ~3R célárnál); nálunk a TP tipikusan 1,5R-nél
        # ül (tp_rr_ratio), ezért az alap 1,0R — így a lépcső a TP ELŐTT elsül.
        # 1. lépcső: az ár megteszi az alap-távot → stop az alap 1/3-ára (profitban).
        # 2. lépcső: az ár a célárnál → stop a 2/3-ra (hard TP-nél ritkán él —
        # akkor számít, ha a TP-t kézzel kivetted/kitoltad).
        "thirds_base_R":    1.0,
        # Pajzs↔Fibo auto: e szorzó FÖLÖTT számít „nagy mozgásnak" a piac
        # (belépéskori ATR > big_move_atr_mult × ATR-átlag) → Fibo; alatta Pajzs.
        # 2.0-val a nagy mozgás RITKA volt (az atr_max_pct vol-szűrő is vágja a
        # kaotikus belépőket) → 1.5, hogy a Fibo-ág érdemben szerephez jusson.
        "big_move_atr_mult": 1.5,
        # Cost-cut (tananyag 2.6): IDŐ-STOP, bármely presettel kombinálható.
        # Ha a nyitás után cost_cut_bars fő-timeframe gyertyával a pozíció még
        # VESZTESÉGES → piaci áron zárjuk (a kanóc/zaj korai levágása töredék-R
        # veszteséggel, a teljes SL kivárása helyett). False = kikapcsolva.
        "cost_cut":         False,
        "cost_cut_bars":    12,
    }


# ⚠ A `breakeven_trigger` SZOROS CIKLUSBAN fut (a backteszt minden gyertyán,
# minden nyitott kötésre), ezért a diagnosztika futásonként EGYSZER szólal meg
# okonként. A függvény egyébként tiszta marad: a naplózás nem változtat
# viselkedést, csak láthatóvá teszi a `None`-t — enélkül a „nincs breakeven"
# ugyanúgy néma volna, mint a hiba, amit javít.
_warned: set = set()


def _warn_once(key: str, msg: str, *args) -> None:
    if key in _warned:
        return
    _warned.add(key)
    log.warning(msg, *args)


def breakeven_trigger(open_price: float, tp: float, sl_dist: float, is_buy: bool,
                      be_pct: float, be_r: float, risky: bool = False):
    """A BREAKEVEN-küszöb ÁRA, vagy `None`, ha nincs breakeven.

    EGY forrás mindhárom hívónak: `trading.backtest._update_stops`,
    `live_trader._apply_be_and_trailing` és a `live_trader.process_pair`
    off/risky ága. A háromból kettő IKERPÁRKÉNT volt jelölve („HA ITT
    VÁLTOZTATSZ, azt is módosítsd") — pontosan az a szerkezet, amiből néma
    él↔backteszt eltérés lesz. Ez a függvény tiszta: se MT5, se Trade, csak
    számok, tehát egy sorban tesztelhető, és MINDHÁROM út ugyanazt kapja.

    `sl_dist`: az EREDETI stop-távolság ÁRBAN (1 R). A backtestben
    `trade.sl_points × point_size`, élőben `|nyitóár − original_sl|`.

    A SORREND (szándékosan): `risky` → `be_r` → `be_pct`.
      * `risky`   — azonnali BE a nyitóáron (a live óvatos módja),
      * `be_r>0`  — a küszöb R-BEN (a célártól FÜGGETLEN),
      * különben  — a régi, célár-arányos `be_pct` (bitazonos viselkedés).

    ⚠ A `none` presetet NEM itt kapuzzuk: a hívó adjon `be_pct=0, be_r=0`-t.
    Így a preset-logika ott marad, ahol eddig volt, és ez a függvény nem tud a
    presetekről — egy dolgot csinál, azt egy helyen.

    ⚠ NINCS NÉMA MÓDVÁLTÁS (2026-09-08, független code review). Két ág korábban
    csendben MÁS SZEMANTIKÁRA váltott:

      1. `be_r > 0`, de a stop-távolság ismeretlen (0) → visszaesett a
         `be_pct`-re. Aki R-ben kérte a küszöböt, célár-arányosat kapott —
         épp az a csatolás, aminek a felszámolására a `be_r` készült.
      2. `tp` hiányzik vagy 0 → a `be_pct` képlet ÉRTELMETLEN, de nem szólt:
         BUY-nál `open + (0 − open) × 0.5 = open/2`, azaz a küszöb a belépő
         FELE — ami alatta van az árnak, tehát **azonnal elsül**. Nem
         elmaradó BE: HAMIS, azonnali BE. És ez nem elméleti: a ráépített
         lábakat a motor `tp=0.0`-val nyitja (a csomag egyben fut).

    Mindkettő most `None` (nincs breakeven) + EGYSZERI naplóbejegyzés. A `None`
    a biztonságos válasz: a stop marad, ahol van — a pozíció nem lesz
    kockázatmentes, de hamis küszöbtől sem sül el.
    """
    if risky:
        return open_price
    try:
        be_r = float(be_r or 0.0)
    except (TypeError, ValueError):
        be_r = 0.0
    if be_r > 0:
        try:
            _d = float(sl_dist or 0.0)
        except (TypeError, ValueError):
            _d = 0.0
        if _d > 0:
            d = be_r * _d
            return open_price + d if is_buy else open_price - d
        # ⚠ NEM esünk vissza a be_pct-re (lásd a docstringet): az R-ben kért
        # küszöböt nem tudjuk kiszámolni, tehát nincs breakeven.
        _warn_once("be_r_no_sl_dist",
                   "breakeven_r be van állítva (%.2f R), de a stop-távolság "
                   "ISMERETLEN → NINCS breakeven. A pozíció nem lesz "
                   "kockázatmentes; a régi, célár-arányos küszöbre NEM esünk "
                   "vissza (az más szemantika volna).", be_r)
        return None
    try:
        be_pct = float(be_pct or 0.0)
    except (TypeError, ValueError):
        be_pct = 0.0
    if be_pct <= 0:
        return None
    # ⚠ Célár nélkül a `be_pct` képlet nem hibázik, hanem HAZUDIK: `tp=0`-nál a
    # küszöb a belépő fele (BUY), ami már az induláskor teljesül.
    if not tp:
        _warn_once("be_pct_no_tp",
                   "breakeven_pct van beállítva (%.2f), de a pozíciónak NINCS "
                   "célára → NINCS breakeven. (Célár-arányos küszöb célár "
                   "nélkül azonnal elsülne.) Használj `breakeven_r`-t.", be_pct)
        return None
    return (open_price + (tp - open_price) * be_pct if is_buy
            else open_price - (open_price - tp) * be_pct)


def trailing_new_sl(is_buy: bool, price_open: float, price_current: float,
                    current_sl: float, *, entry_atr: float,
                    trail_distance_atr: float, trail_activation_atr: float,
                    point: float, digits: int, override_points=None,
                    risky: bool = False, stops_level: float = 0.0,
                    be_floor=None):
    """Az ÚJ trailing stop ÁRA + a követési távolság, vagy `None`, ha nincs húzás.

    Visszatérés: `(new_sl, eff_price)` — a hívó dolga a broker-hívás és a napló.

    EGY forrás a KÉT ÉLŐ ÁGNAK — ugyanaz a szerep, mint a `breakeven_trigger`-é.
    A kódban „IKERPÁR"-ként voltak megjelölve („HA ITT VÁLTOZTATSZ, azt is
    módosítsd"), és ez a szerkezet meg is termelte a maga hibáját:

    ⚠ A `_apply_be_and_trailing` (a no-trade órák ága) az `_atr`-t CSAK az
    ATR-es ágban vette fel, az `act_price` viszont mindig hivatkozott rá.
    KÉZI követés-felülírás (`trail_points`, a Pozíciók fülről) + nem-risky
    pozíció → **`NameError`** — amit a hívó `except`-je `log.debug`-ba nyelt,
    tehát a szünetben nem csak a trailing, hanem az adott körben a többi
    pozíció BE-je is elmaradt volna, némán. A fő ág ugyanezt helyesen csinálta.

    A SZEMANTIKA a FŐ ÁGÉ (az fut minden kereskedhető órában):
      * `override_points` (kézi, PONTBAN) → pontos táv, a risky NEM felezi;
      * különben `entry_atr × trail_distance_atr`, risky felezi;
      * `entry_atr` ismeretlen ÉS nincs override → nincs trailing (`None`);
      * az AKTIVÁLÁS `entry_atr × trail_activation_atr` (risky: azonnal). Kézi
        felülírásnál ismeretlen ATR-rel ez 0 — azaz azonnal aktív: a felhasználó
        kifejezetten megadta a követést, nincs mihez késleltetni.

    A bróker MINIMUM stop-távolsága (`stops_level`, PONTBAN) alá nem megyünk +1
    ponttal: enélkül a modify csendben elutasításra kerül, és a trailing sosem
    kötne le profitot.

    `be_floor`: ha a BE már megtörtént, a stop SOSEM lehet a belépőnél rosszabb
    (elavult pillanatkép mellett is) — a 2026-07-28-i eset invariánsa.
    """
    try:
        entry_atr = float(entry_atr or 0.0)
    except (TypeError, ValueError):
        entry_atr = 0.0

    if override_points is not None:
        dist_price = float(override_points) * point
    elif entry_atr > 0:
        dist_price = (float(trail_distance_atr) * entry_atr
                      * (0.5 if risky else 1.0))
    else:
        return None                      # ismeretlen ATR, nincs kézi táv

    eff_price = max(dist_price, float(stops_level) * point + point)
    act_price = 0.0 if risky else float(trail_activation_atr) * entry_atr

    if is_buy:
        if price_current < price_open + act_price:
            return None
        new_sl = round(price_current - eff_price, digits)
        if new_sl <= current_sl:
            return None
        if be_floor is not None and new_sl < be_floor:
            return None
    else:
        if price_current > price_open - act_price:
            return None
        new_sl = round(price_current + eff_price, digits)
        if new_sl >= current_sl:
            return None
        if be_floor is not None and new_sl > be_floor:
            return None
    return new_sl, eff_price


def wants_cautious_size(preset: str) -> bool:
    """Óvatos (felezett) belépő-méret kell-e a preset alapján? (1. tengely.)
    A Risky felezi a méretet; a többi preset alap: normál. A GUI 'Óvatos méret'
    pipája ezt bármelyik presetnél felülbírálhatja — az a hívó (motor) dolga."""
    return preset == PRESET_RISKY


def target_fraction(preset: str, cfg: dict) -> float:
    """A preset által KÉRT részleges-zárás arány (a lot-létra ELŐTT). 0 = nincs."""
    if preset == PRESET_HALVING:
        return float(cfg.get("halving_fraction", 0.5))
    if preset == PRESET_SHIELD:
        return float(cfg.get("shield_fraction", 0.75))
    return 0.0   # off / risky → nincs részleges zárás


def fibo_levels(open_price: float, tp_price: float, cfg: dict) -> tuple[float, float]:
    """Fibo preset: (trigger_ár, új_stop_ár) a belépő→TP távra húzott Fibonacci
    szerint (tananyag 2.2: NEM a hullámra, hanem a beszálló→célár távra).

    A táv ELŐJELES (BUY: +, SELL: −) → mindkét irányra helyes képlet:
      trigger  = open + táv × fibo_level      (alap 0.618)
      új stop  = open + táv × fibo_stop_level (0.0 = breakeven; 0.236/0.382 =
                 rész-profit bezárva, nem túl közel az árhoz → a zaj nem ver ki)
    (0.0, 0.0), ha nincs érvényes TP (a Fibo TP-távra épül — enélkül nem értelmezhető)."""
    if not tp_price or not open_price:
        return (0.0, 0.0)
    dist = tp_price - open_price
    if dist == 0.0:
        return (0.0, 0.0)
    lvl  = float(cfg.get("fibo_level", 0.618))
    slvl = float(cfg.get("fibo_stop_level", 0.0))
    return (open_price + dist * lvl, open_price + dist * slvl)


def big_move(atr_now: float, atr_avg: float, cfg: dict) -> bool:
    """Pajzs↔Fibo auto: „nagy mozgás"-e a piac a belépéskor? (ATR a szokásos
    átlag big_move_atr_mult-szorosa fölött.) Érvénytelen inputnál False (→ Pajzs,
    a konzervatív alaphelyzet)."""
    if not atr_now or not atr_avg or atr_avg <= 0:
        return False
    return atr_now > float(cfg.get("big_move_atr_mult", 2.0)) * atr_avg


def thirds_levels(open_price: float, risk_dist: float, is_buy: bool,
                  cfg: dict) -> tuple[float, float, float]:
    """Harmados (1/3–2/3, „Birger"): (trigger_ár, stop1_ár, stop2_ár) R-alapon.

    alap-táv = thirds_base_R × R (a kezdeti kockázat-távolság `risk_dist`).
      trigger : az ár megtette az alap-távot   → stop1 = alap-táv 1/3-a (profitban)
      célárnál: stop2 = alap-táv 2/3-a (a hívó a saját TP-érintésén ellenőrzi)
    (0,0,0), ha nincs érvényes kockázat-táv."""
    if risk_dist <= 0.0:
        return (0.0, 0.0, 0.0)
    base = float(cfg.get("thirds_base_R", 1.0)) * risk_dist
    sgn  = 1.0 if is_buy else -1.0
    return (open_price + sgn * base,
            open_price + sgn * base / 3.0,
            open_price + sgn * base * 2.0 / 3.0)


def closable_lot(cur_lot: float, fraction: float, min_lot: float,
                 lot_step: float) -> float:
    """A LOT-LÉTRA magja: a kért `fraction`-ből mennyit zárjunk le ténylegesen úgy,
    hogy (a) a lezárt rész **≥ 50%** (breakeven-biztos), (b) a runner ≥ min_lot,
    (c) minden lot_step-re illeszkedjen. 0.0 = nem osztható (pl. 1× min_lot)."""
    if fraction <= 0.0 or min_lot <= 0.0 or lot_step <= 0.0 or cur_lot <= 0.0:
        return 0.0
    # Legalább 2× min_lot kell, különben a runner min_lot alá menne.
    if cur_lot < 2.0 * min_lot - _EPS:
        return 0.0

    # Alsó korlát: legalább 50% (különben stopnál nettó mínusz) — step-re felfelé.
    lower = math.ceil(0.5 * cur_lot / lot_step - _EPS) * lot_step
    # Felső korlát: a runner ≥ min_lot maradjon.
    upper = cur_lot - min_lot
    # A preset céljához legközelebbi step-mennyiség.
    want = round(cur_lot * fraction / lot_step) * lot_step

    closed = min(max(want, lower), upper)
    # step-illesztés (lefelé, hogy sose lépjük túl az upper-t)
    closed = math.floor(closed / lot_step + _EPS) * lot_step
    if closed < min_lot - _EPS or closed < lower - _EPS:
        return 0.0
    return round(closed, 8)


def can_reduce_lot(cur_lot: float, min_lot: float, lot_step: float) -> bool:
    """Megfelezhető-e egyáltalán ez a lot? (A részleges záráshoz ≥ 2× min_lot kell.)
    A Felező/Pajzs (és a Pajzs↔Fibo, ami Pajzsra eshet) ezt igényli — a GUI ez
    alapján tiltja a presetet a nem-felezhető (pl. min-loton nyíló) instrumentumnál."""
    return closable_lot(cur_lot, 0.5, min_lot, lot_step) > 0.0


# A részleges zárást (megfelezést) IGÉNYLŐ presetek — ezeket kell tiltani, ha a
# pozíció lotja nem felezhető (a Fibo/Harmados/Risky csak stopot mozgat, nem zár részt).
PARTIAL_CLOSE_PRESETS = (PRESET_HALVING, PRESET_SHIELD, PRESET_SHIELD_FIBO)


def preset_blockers(cur_lot, min_lot: float, lot_step: float,
                    netting: bool = False) -> dict:
    """`{preset: MIÉRT nem választható}` — csak a TILTOTTAK szerepelnek benne.

    EGY igazságforrás a felületnek: a Pozíciók-fül menüje ÉS az instrumentum-ablak
    preset-választója is ezt hívja, tehát nem tudnak szétcsúszni (korábban a
    szabály csak a menüben élt, kézzel bemásolva).

    `cur_lot=None` → nincs (még) nyitott pozíció: a lot-alapú tiltás ilyenkor NEM
    érvényes, mert a jövőbeli belépő mérete még nem ismert. A netting-korlát
    viszont akkor is áll: az a SZÁMLA tulajdonsága, nem a pozícióé.

    Tiszta függvény (se MT5, se config) — a hívó méri be a számlát és a lotot."""
    if netting:
        # NETTING/EXCHANGE számla: egy szimbólumon egy nettó pozíció lehet, így a
        # kockázatmentes runner mellé nyíló új belépő ÖSSZEVONÓDNA vele — a
        # részleges záráson alapuló technikák nem működnének helyesen.
        return {p: _t("rr.blocked.netting") for p in PARTIAL_CLOSE_PRESETS}
    if cur_lot is not None and not can_reduce_lot(cur_lot, min_lot, lot_step):
        return {p: _t("rr.blocked.lot") for p in PARTIAL_CLOSE_PRESETS}
    return {}


@dataclass
class Plan:
    """Amit a technika 1R-nél tesz — a motor ezt hajtja végre."""
    close_lot: float     # ennyi lotot zárjon le (0 = nincs részleges zárás)
    runner_stop: str     # a maradékra: keep|breakeven|trailing
    effective: str       # a TÉNYLEGESEN alkalmazott technika (UI/log)


def plan_at_trigger(preset: str, cfg: dict, cur_lot: float, min_lot: float,
                    lot_step: float, allow_partial: bool = True) -> Plan:
    """1R elérésekor: mit tegyünk a pozícióval, a lot-létrával DEGRADÁLVA.

    - off              → nincs teendő.
    - risky            → nincs részleges zárás, a runner (teljes) stopja BE-re.
    - halving/shield   → részleges zárás (ha a lot engedi), a runner stopja a
                         cfg['runner_stop'] szerint. Ha a lot túl kicsi az osztáshoz,
                         DEGRADÁL risky-re (BE-húzás, nincs zárás).
    A `effective` a UI/log számára a ténylegesen alkalmazott technikát adja."""
    if preset == PRESET_OFF:
        return Plan(0.0, RUNNER_KEEP, PRESET_OFF)
    if preset == PRESET_RISKY:
        return Plan(0.0, RUNNER_BREAKEVEN, PRESET_RISKY)
    if preset == PRESET_FIBO:
        # A Fibo nem 1R-alapú és nem zár részlegesen — a motor a fibo_levels()
        # szerinti stop-húzással kezeli (ez az ág csak védelem, ha mégis idehívnák).
        return Plan(0.0, RUNNER_KEEP, PRESET_FIBO)
    if preset == PRESET_THIRDS:
        # A Harmados sem zár részlegesen — a motor a thirds_levels() szerinti
        # stop-létrával kezeli (ez az ág csak védelem).
        return Plan(0.0, RUNNER_KEEP, PRESET_THIRDS)
    if preset == PRESET_SHIELD_FIBO:
        # A Pajzs↔Fibo autót a motor belépéskor HATÁSOS presetre oldja fel
        # (shield vagy fibo) — ide már nem juthat el; védelemként Pajzsként kezeljük.
        preset = PRESET_SHIELD

    if not allow_partial:
        # NETTING/EXCHANGE számla: egy szimbólumon csak EGY nettó pozíció lehet, a
        # részleges zárásra épülő technika nem működne helyesen → Risky/BE degradálás
        # (ugyanaz a fallback, mint a nem osztható lotnál).
        return Plan(0.0, RUNNER_BREAKEVEN, PRESET_RISKY)

    frac = target_fraction(preset, cfg)
    closed = closable_lot(cur_lot, frac, min_lot, lot_step)
    if closed <= 0.0:
        # nem osztható (kis pozíció) → Risky/BE fallback
        return Plan(0.0, RUNNER_BREAKEVEN, PRESET_RISKY)

    runner = cfg.get("runner_stop", RUNNER_KEEP)
    # Tényleges technika: ha a Pajzs (75%) nem fért ki és inkább felező-szintű lett,
    # jelöljük halving-nak (a UI így pontosan mutatja, mi valósult meg).
    achieved = closed / cur_lot
    eff = preset
    if preset == PRESET_SHIELD and achieved < 0.66:
        eff = PRESET_HALVING
    return Plan(round(closed, 8), runner, eff)
