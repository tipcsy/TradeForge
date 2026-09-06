"""Pozícióépítés (ráépítés) — tiszta logika (nincs MT5/tkinter függés).

Forrás-tananyag: Obsidian `Tananyagok/Pozícióépítés.md`. Elv:
  • Gyertyás építés-jel (a doc kedvenc technikája): akkor építs, ha egy ZÁRT gyertya
    FELJEBB (BUY) / LEJJEBB (SELL) zár, mint az előző ráépítés referenciája.
  • Piramidális méret: minden ráépítés az előző × `size_factor` (csökkenő), min_lot-ig.
  • 1. szabály (kockázatmentesség): a hívó az ÖSSZES azonos-szimbólumú stopot az
    ÁTLAGÁRRA húzza — így a legrosszabb esetben is ~nulla az eredmény. Ezt a live/GUI
    réteg végzi (MT5), ez a modul csak a jelet + a méretet + az átlagárat számolja.

A „suitable" (alkalmas) állapot = a pozíció KOCKÁZATMENTES (a hívó tudja) ÉS a
`build_signal` szól. Az `enabled`-et a mód (off|manual|auto) dönti a hívónál.
"""

from __future__ import annotations

import math

from core.i18n import LabelMap as _LabelMap

MODE_OFF = "off"
MODE_MANUAL = "manual"
MODE_AUTO = "auto"          # későbbi kör (automatikus építés minden jel-gyertyán)
MODES = (MODE_OFF, MODE_MANUAL, MODE_AUTO)

# ── Ráépítés-triggerek (mikor jöjjön a következő adalék) ─────────────────────
TRIGGER_CANDLE     = "candle"      # gyertyás trendkövető (új csúcs/mély-zárás a ref fölött)
TRIGGER_R_FIXED    = "r_fixed"     # fix R-rács: +1R, +2R, +3R… (r_step állandó)
TRIGGER_R_CONVERGE = "r_converge"  # R-felező: a lépés zsugorodik (1R, +0.5R, +0.25R…) → sűrűsödik
TRIGGERS = (TRIGGER_CANDLE, TRIGGER_R_FIXED, TRIGGER_R_CONVERGE)
TRIGGERS = (TRIGGER_CANDLE, TRIGGER_R_FIXED, TRIGGER_R_CONVERGE)
TRIGGER_NAME = _LabelMap("build.trigger", TRIGGERS)

# Biztonsági plafon a ráépítések számára. Nincs FELHASZNÁLÓI korlát (mehet sok R-ig),
# de az R-FELEZŐ a konvergencia-plafon átlépésekor VÉGTELEN adalékot nyitna (minden
# R-szint a plafon alatt van) → ez a hard-cap ezt fogja meg. Nagy, hogy normál
# használatnál gyakorlatilag ne érződjön (a Fix R / gyertyás amúgy is self-limitál).
HARD_MAX_ADDS = 100


def default_config() -> dict:
    """Per-instrumentum építés-beállítás alap (a per-pár állapot felülírja)."""
    return {
        "mode":        MODE_OFF,
        "size_factor": 0.7,     # piramidális: minden add az előző × faktor
        "timeframe":   "M15",   # mely időkeret ZÁRT gyertyáin figyeljük a jelet
        "trigger":     TRIGGER_CANDLE,   # gyertyás | r_fixed | r_converge
        "r_step":      1.0,     # R-alapú triggernél az (első) lépés R-ben
        "r_shrink":    0.5,     # R-felezőnél a lépés szorzója add-onként (0.5 = felező)
        # A CSOMAG közös célára R-ben (0 = nincs cél → a lábak TP nélkül futnak,
        # ez a v3.49.0 előtti viselkedés). A felhasználó kérése: „legyen egy
        # célár, pl. 20 R", és „első körben a TP célár legyen, ne az SL célár".
        "target_r":    0.0,
        # A KÚSZÓ közös stop: a csomag célár felé megtett út hányadát rögzítjük
        # profitban (0 = nincs kúszás → a stop az átlagáron marad, ez a
        # `target_r` bevezetésekori viselkedés). CSAK `target_r > 0` mellett él:
        # cél nélkül nincs mihez mérni a haladást.
        "target_trail_pct": 0.0,
    }


def r_level(initial_entry, r_price, direction: str, n_add: int, cfg: dict):
    """Az `n_add`-adik ráépítés (n_add ≥ 1) ÁRSZINTJE az R-alapú triggereknél. Az R a
    csomag kockázati egysége (az INDULÓ láb |belépő − eredeti SL|-je). None, ha nem
    R-alapú a trigger vagy nincs érvényes R. A szintek az INDULÓ belépőtől mérve:
      • Fix R:     init ± n·r_step·R
      • R-felező:  init ± r_step·(1 − shrink^n)/(1 − shrink)·R  (konvergál → sűrűsödik)."""
    if initial_entry is None or not r_price or r_price <= 0 or n_add < 1:
        return None
    step = float(cfg.get("r_step", 1.0))
    trig = cfg.get("trigger", TRIGGER_CANDLE)
    if trig == TRIGGER_R_FIXED:
        cum = n_add * step
    elif trig == TRIGGER_R_CONVERGE:
        shrink = float(cfg.get("r_shrink", 0.5))
        if abs(1.0 - shrink) < 1e-9:
            cum = n_add * step
        else:
            cum = step * (1.0 - shrink ** n_add) / (1.0 - shrink)
    else:
        return None
    return (initial_entry + cum * r_price) if direction == "BUY" \
        else (initial_entry - cum * r_price)


def build_signal(bars, direction: str, ref_close: float) -> bool:
    """GYERTYÁS építés-jel az UTOLSÓ ZÁRT gyertyán: BUY-nál a záró > referencia (új
    csúcs-zárás), SELL-nél a záró < referencia. `ref_close` = az előző ráépítés (vagy az
    elsőnél a belépő) záróára. A formálódó gyertya az utolsó sor."""
    if bars is None or len(bars) < 2 or ref_close is None:
        return False
    try:
        c = float(bars["close"].iloc[-2])
    except Exception:
        return False
    if math.isnan(c):
        return False
    if direction == "BUY":
        return c > float(ref_close)
    if direction == "SELL":
        return c < float(ref_close)
    return False


def build_fires(bars, direction: str, cfg: dict, *, ref_close=None,
                initial_entry=None, r_price=None, n_add: int = 1) -> bool:
    """EGYSÉGES ráépítés-jel az UTOLSÓ ZÁRT gyertyán, a `cfg['trigger']` szerint:
      • candle    → a `build_signal` (gyertyás trendkövető).
      • r_fixed / r_converge → a záró elérte-e az `n_add`-adik R-szintet.
    Determinisztikus (árszint / gyertyazáró) → backtestelhető Kéziben is."""
    trig = cfg.get("trigger", TRIGGER_CANDLE)
    if trig == TRIGGER_CANDLE:
        return build_signal(bars, direction, ref_close)
    if n_add > HARD_MAX_ADDS:          # biztonsági plafon (fő cél: R-felező konvergencia)
        return False
    if bars is None or len(bars) < 2:
        return False
    try:
        c = float(bars["close"].iloc[-2])
    except Exception:
        return False
    if math.isnan(c):
        return False
    lvl = r_level(initial_entry, r_price, direction, n_add, cfg)
    if lvl is None:
        return False
    return c >= lvl if direction == "BUY" else c <= lvl


def next_lot(last_lot: float, size_factor: float, min_lot: float, lot_step: float) -> float:
    """A következő ráépítés mérete (piramidális, csökkenő). A lot_step-re illesztve,
    min_lot alá nem megy. Ha már a min_lot-on vagyunk → tovább a min_lot-tal (a doc:
    a végén a legkisebbel pakol tovább)."""
    if last_lot <= 0 or min_lot <= 0 or lot_step <= 0:
        return 0.0
    want = last_lot * float(size_factor)
    stepped = math.floor(want / lot_step + 1e-9) * lot_step
    return max(min_lot, round(stepped, 8))


def average_price(positions) -> float:
    """Volumen-súlyozott átlagár (a null pont) az azonos-szimbólum+irány nyitott
    pozíciókból. `positions`: [(price_open, volume), …]. 0.0, ha nincs volumen."""
    tot_v = sum(float(v) for _, v in positions)
    if tot_v <= 0:
        return 0.0
    return sum(float(p) * float(v) for p, v in positions) / tot_v


def package_target(avg: float, direction: str, risk_total: float,
                   target_r: float, lot_total: float,
                   pv1_point: float, point_size: float) -> float:
    """A csomag KÖZÖS célára ÁRBAN — vagy `0.0`, ha nincs cél.

    ⚠ A CÉL A TELJES CSOMAGRA szól (átlagár + ÖSSZ-kockázat), nem az első
    lábra. Ez a felhasználó kimondott döntése: egy 20 R-es cél azt jelenti,
    hogy a csomag EGYÜTT hoz 20-szor annyit, mint amennyit a lábak együtt
    kockáztattak — nem azt, hogy az induló láb hoz 20 R-t.

    A képlet a csomag P&L-jéből jön:

        P&L(pont) = pont · össz_lot · pv1_point          (`risk_from_points`)
        cél:        P&L = target_r · össz_kockázat
        →  pont = (target_r · össz_kockázat) / (össz_lot · pv1_point)
        →  ár   = átlagár ± pont · point_size

    ⚠ A `pv1_point` PONTONKÉNTI, tehát a képlet PONTOT ad, nem árkülönbséget —
    a `point_size`-zal kell árra váltani. Elsőre kihagytam, és a cél a
    `point_size` reciprokának arányában lett hibás (EURUSD-n 10 000×).

    ⚠ AZ ÖSSZ-KOCKÁZAT A BELÉPÉSKORI (`position_meta.risk_of` lábanként), NEM a
    mostani. Miután a közös stop az átlagárra kerül, a pillanatnyi kockázat
    nulla — abból számolva a cél a végtelenbe menne.

    ⚠ HIÁNYZÓ ADATNÁL `0.0`-t ad (nincs cél), NEM kitalált árat: a hívó ilyenkor
    a mai viselkedést folytatja (TP nélküli csomag). Egy rossz helyre tett TP
    rosszabb, mint a hiányzó — az elvinné a csomagot egy véletlen szinten.

    ⚠ MIÉRT A CSOMAGRA ÉS NEM LÁBANKÉNT: lábanként külön TP-vel az induló láb a
    saját célján ÖNÁLLÓAN zárna, otthagyva a többit — pontosan ez volt a
    bejelentett hiba („lezárta a kezdeti pozíciót, és csak a veszteségesek
    maradtak"). Ezért kapja MINDEN láb UGYANEZT az árat.
    """
    try:
        target_r = float(target_r)
        risk_total = float(risk_total)
        lot_total = float(lot_total)
        pv1_point = float(pv1_point)
        point_size = float(point_size)
        avg = float(avg)
    except (TypeError, ValueError):
        return 0.0
    if not (target_r > 0 and risk_total > 0 and lot_total > 0
            and pv1_point > 0 and point_size > 0 and avg > 0):
        return 0.0
    pont = (target_r * risk_total) / (lot_total * pv1_point)
    tav = pont * point_size
    return avg + (tav if direction == "BUY" else -tav)


def package_trail_stop(avg: float, direction: str, price_now: float,
                      target: float, trail_pct: float,
                      current_sl: float = 0.0) -> float:
    """A csomag KÚSZÓ közös stopja — vagy `0.0`, ha nincs mit mozgatni.

    A felhasználó megfogalmazása: *„az SL húzás úgy történjen, ahogy a dinamikus
    csúszó SL működik — azaz úgy szűkíti az SL-t pozitívba, ahogy kezdi elérni a
    célárat."* Tehát a stop nem fix távolságot követ (azt a `trail_distance_atr`
    csinálja), hanem a CÉLÁR FELÉ MEGTETT ÚT arányában kúszik:

        haladás = (mostani ár − átlagár) / (célár − átlagár)     [0…1-re vágva]
        stop    = átlagár ± haladás · trail_pct · (célár − átlagár)

    `trail_pct = 0.5` mellett a cél feléig érve a stop a cél-táv negyedénél áll
    profitban. `trail_pct = 1.0` mellett a stop az árral együtt ér a célba — de
    odáig a TP úgyis elsül, tehát a gyakorlati tartomány 0 < pct ≤ 1.

    ⚠ CSAK ELŐRE. `current_sl` megadásakor a rosszabb (visszafelé mozgó) stopot
    `0.0`-val utasítjuk el. Enélkül egy visszahúzódó ár LAZÍTANÁ a stopot —
    pontosan az ellenkezője annak, amit egy csúszó stop csinál. Ugyanezért nem
    ütközik az ATR-trailinggel sem: mindkettő csak szorít, tehát a szorosabb nyer.

    ⚠ A HALADÁS 1-re VÁGVA. A célt túllépő ár (rés/csúszás) enélkül a célár FÖLÉ
    tenné a stopot, ahol a bróker sem fogadná el.

    ⚠ A stop-táv broker-minimumát NEM ez a függvény ismeri (nincs `symbol_info`
    függése) — azt a hívó vágja, mint a `package_stop`-nál."""
    try:
        avg = float(avg); price_now = float(price_now); target = float(target)
        trail_pct = float(trail_pct); current_sl = float(current_sl or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not (avg > 0 and price_now > 0 and target > 0 and trail_pct > 0):
        return 0.0
    tav = (target - avg) if direction == "BUY" else (avg - target)
    elore = (price_now - avg) if direction == "BUY" else (avg - price_now)
    if tav <= 0 or elore <= 0:
        return 0.0                      # rossz oldalon álló cél / még nincs haladás
    halad = min(1.0, elore / tav)
    zar = halad * trail_pct * tav
    uj = avg + zar if direction == "BUY" else avg - zar
    if current_sl:
        if (uj <= current_sl) if direction == "BUY" else (uj >= current_sl):
            return 0.0                  # nem szorít → nem mozgatunk
    return uj


def package_stop(avg: float, direction: str, price_now: float,
                 min_gap: float, point: float = 0.0,
                 cost_buffer: float = 0.0) -> tuple[float, bool]:
    """A csomag KÖZÖS stopja: a NETTÓ null pont, a bróker MINIMUM stop-távolságára
    vágva. Visszaad: `(stop, vágtunk-e)`.

    A cél a `cost_buffer`-rel a PROFIT oldalra tolt átlagár:

        BUY  → avg + cost_buffer          SELL → avg − cost_buffer

    Miért nem a nyers átlagár: az átlagár a **bruttó** null pont. A zárás fizeti a
    spreadet, a jutalékot és a felhalmozott swapot, ezért a nyers átlagáron zárt
    csomag **nettó MÍNUSZ** — pontosan ez adta a bejelentett GOLD-esetet
    (+2,12 € / −2,16 € = −0,04 €). Az egyedi pozíció breakevenje régóta
    költség-tudatos (`mt5_connector._breakeven_plan`); ez a két hely csúszott szét.
    A `cost_buffer` ugyanaz a mennyiség, csak a csomag EGÉSZÉRE számolva.

    Miért kell a vágás: ráépítéskor a cél tipikusan KÖZEL van a piaci árhoz (épp
    akkor építünk, amikor az ár túlüt a referencián). Ha közelebb, mint a bróker
    `trade_stops_level`-je, a stop-áthelyezést `10016 Invalid stops`-szal utasítja
    el — és eddig ez NÉMÁN történt: a friss láb stop NÉLKÜL maradt, miközben a
    motor kockázatmentesnek jelölte.

    Ilyenkor a legszorosabb ENGEDÉLYEZETT stopot adjuk (egy ponttal a határon
    belül), és `vágtunk-e = True`. **A hívónak ilyenkor NEM szabad
    kockázatmentesnek jelölnie a lábakat.** A `cost_buffer` óta ez erősebb
    állítás: `vágtunk-e = False` mostantól azt jelenti, hogy a csomag **nettó**
    (költség után) sem zár mínuszban — korábban csak bruttó nullát garantált.
    Ezért a köztes eset (a nyers átlagár még elérhető, a költség-fedezett cél már
    nem) SZÁNDÉKOSAN vágottnak számít: ott a zárás nettó mínusz lenne.

    `min_gap`, `point` és `cost_buffer` ÁR-egységben; `min_gap <= 0` (nincs korlát)
    → nincs vágás. `cost_buffer=0.0` (alapérték) → a korábbi viselkedés bitazonos.
    """
    target = avg + (cost_buffer if direction == "BUY" else -cost_buffer)
    if min_gap <= 0 or price_now <= 0:
        return target, False
    if direction == "BUY":
        cap = price_now - min_gap - point      # a stop legfeljebb eddig lehet FÖNT
        if target > cap:
            return cap, True
    else:
        cap = price_now + min_gap + point      # a stop legalább eddig LENT
        if target < cap:
            return cap, True
    return target, False
