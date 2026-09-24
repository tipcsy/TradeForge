"""PIACI NYITÁSOK — hol tart a világ tőzsdéinek napja?

A felhasználó kérése (2026-09-24, „Piaci nyitások kapu"): legyen egy kapu, ami
hat piac nyitva tartását figyeli, és négy dolgot tud megkülönböztetni — zárva,
nyitás előtt, nyitva, nyitás után. Az indok kettős:

  1. amikor minden nagy piac alszik, a KÖLTSÉG megeszi a kereskedést;
  2. a nyitás utáni 5–15 percben akkora a rángatózás, hogy az belépőnek
     alkalmatlan.

⚠ AMIT A PROJEKT SAJÁT MÉRÉSE MOND ERRŐL (mert ez nem magától értetődő):
  * az 1. pontot ALÁTÁMASZTJA: 186 471 kötésen a napszak-hatás majdnem teljesen
    költség, és a 22:00-s óra az EGYETLEN, ahol a BRUTTÓ él is erősen negatív
    (−0,179 R). De a mechanizmus a költség — azt a spread- és a költség-kapu
    KÖZVETLENÜL méri, ez a kapu csak proxy.
  * a 2. pontnak ELLENTMOND egy mérés: a gyertya-alakzat vizsgálatban a
    15:30–16:00 szerver-idejű ablak (= 09:30 New York, a nyitóharang) jött ki a
    LEGJOBB napszaknak. Ugyanaz a jegyzet viszont kimondja, hogy „a piac ×
    napszak cellák NEM stabilak mérőhelyek között".
  ⇒ EZÉRT INDUL MINDEN ÁLLAPOT `none` HATÁSSAL: a kapu MUTAT, nem tilt. Mielőtt
    bármelyik állapot blokkolásra kerül, MEG KELL MÉRNI, mit tesz.

AMIT VISZONT HOZZÁTESZ a meglévő kapukhoz: a spread-kapu REAKTÍV — akkor lát,
amikor a spread már kinyílt. Ez ELŐRE tud: tíz perccel a londoni nyitás előtt
már tudja, hogy jön. Ez más fajta információ, és a pozícióépítésnél is számít.

⚠ AZ IDŐ — A LEGFONTOSABB RÉSZLET, ÉS MÉRVE, NEM TIPPELVE. A gyertyák
időbélyege SZERVER időben van (a projekt ezt a tickeknél már megtanulta). Hogy
melyik zóna a szerveré, azt a Ger40 gyertya-tartományaiból olvastuk ki: a
frankfurti nyitás (09:00 helyi) TÉLEN és NYÁRON is a 09h indexnél adja a
legnagyobb átlagos M1-tartományt — pedig valódi UTC-ben az télen 08:00, nyáron
07:00. Az amerikai púp ugyanígy 15–16h-nál (NYSE 09:30 ET = 15:30 Berlin,
télen-nyáron). Vagyis a szerver órája **Europe/Berlin helyi idő**, és követi az
európai nyári időszámítást. A `data/server_offset.json` mért +2h (CEST) ezzel
egyezik. Innentől a `zoneinfo` mindent elintéz: a szerver-időt berlini helyi
időként olvassuk, abból lesz UTC, abból a piacok helyi ideje.

⚠ ÜNNEPNAPOKAT NEM ISMER. Tőzsdei naptár nélkül karácsonykor is „nyitva"-t
mondana. A hívó ezt a tényleges tick-aktivitással egészítheti ki
(`core.market_state` már ezt csinálja instrumentumra) — ez a modul a NAPTÁRT
mondja meg, nem azt, hogy érkezik-e ár.

TISZTA modul: se MT5, se tkinter, se fájl, se config-olvasás — a hívó adja az
időt és a beállításokat.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

from core.i18n import LabelMap as _LabelMap, t as _t

# ── A szerver órája (MÉRVE, lásd a modul fejlécét) ──────────────────────────
SERVER_ZONE = "Europe/Berlin"

# ── A hat piac: tőzsdei nyitóharang a saját helyi idejükben ─────────────────
# A nyitás-percre azért a tőzsdei nyitás kell (nem a „FX-szesszió"), mert a
# felhasználó kérése a NYITÁSI RÁNGÁS kiszűrése — az a nyitóharanghoz kötődik.
MARKETS = {
    "europa":     {"zone": "Europe/Berlin",    "open": (9, 0),  "close": (17, 30)},
    "london":     {"zone": "Europe/London",    "open": (8, 0),  "close": (16, 30)},
    "amerika":    {"zone": "America/New_York", "open": (9, 30), "close": (16, 0)},
    "azsia":      {"zone": "Asia/Hong_Kong",   "open": (9, 30), "close": (16, 0)},
    "japan":      {"zone": "Asia/Tokyo",       "open": (9, 0),  "close": (15, 0)},
    "ausztralia": {"zone": "Australia/Sydney", "open": (10, 0), "close": (16, 0)},
}
MARKET_KEYS = tuple(MARKETS)
MARKET_LABEL = _LabelMap("sessions.market", MARKET_KEYS)

# ── Az állapotok, ÉLESSÉG szerint csökkenő sorrendben ───────────────────────
# ⚠ A SORREND A PRECEDENCIA. Egy párhoz több piac is tartozhat, és egyszerre
# több állapot is fennállhat (London nyitva + Amerika nyitás előtt). Ilyenkor a
# LEGÉLESEBB nyer — különben a „nyitva" elnyomná a nyitási tüskét, vagyis épp
# azt, amiért a kapu készült.
NYITAS = "nyitas"              # a nyitás ELSŐ perce
NYITAS_UTAN = "nyitas_utan"    # az azt követő `utan_perc`
NYITAS_ELOTT = "nyitas_elott"  # a nyitás előtti `elott_perc`
ZARAS_ELOTT = "zaras_elott"    # a zárás előtti `zaras_elott_perc`
NYITVA = "nyitva"              # nyitva, de egyik különleges ablakban sem
ZARVA = "zarva"                # a figyelt piacok MINDEGYIKE zárva

STATES = (NYITAS, NYITAS_UTAN, NYITAS_ELOTT, ZARAS_ELOTT, NYITVA, ZARVA)
STATE_LABEL = _LabelMap("sessions.state", STATES)

DEFAULTS = {
    "markets": list(MARKET_KEYS),   # melyik piacok számítanak ezen a páron
    "elott_perc": 10,               # a felhasználó 5–15-ös sávjából
    "utan_perc": 10,
    "zaras_elott_perc": 10,
}

GATE = {"key": "sessions", "default_effect": "none", "phase": "signal",
        "kind": "category"}

# ── A SZERKESZTHETŐ MEZŐK (a beállító ablak „Beállítások" szakasza) ─────────
# ⚠ SIMA ADAT, nem `ParamSpec`. A kapu így NEM importálja a keretet: egy
# darabban marad csomagolható (`.tfg`), és nem keletkezik kör-import a kapu-
# felderítés közben. A keret (`core.gate_params._specs_from_module`) fordítja
# le. A feliratok a nyelvi katalógusban élnek: `gp.sessions.<kulcs>.label`.
#
# A `markets` PÁRONKÉNT áll (a felhasználó döntése, 2026-09-24): egy magyar
# részvény-CFD-nek az ázsiai nyitás nem mond semmit, egy JPY-párnak viszont
# igen. Ezért nem találjuk ki szimbólum-névből — megadja.
PARAMS = (
    {"key": "markets", "kind": "multi", "default": list(MARKET_KEYS),
     # ⚠ HÍVHATÓ, nem kész lista: a feliratot a MEGNYITÁS pillanatában oldja
     # fel. Egy import-időben kiszámolt címke befagyna a betöltéskori nyelvbe.
     "choices": lambda: [(m, MARKET_LABEL.get(m, m)) for m in MARKET_KEYS]},
    {"key": "elott_perc", "kind": "int", "default": 10, "lo": 0, "hi": 240},
    {"key": "utan_perc", "kind": "int", "default": 10, "lo": 0, "hi": 240},
    {"key": "zaras_elott_perc", "kind": "int", "default": 10, "lo": 0, "hi": 240},
    {"key": "adverse", "kind": "multi", "default": [],
     "choices": lambda: [(x, STATE_LABEL.get(x, x)) for x in STATES]},
)


def _P(params: dict | None) -> dict:
    p = dict(DEFAULTS)
    for k, v in (params or {}).items():
        if k in DEFAULTS and v is not None:
            p[k] = v
    p["markets"] = [m for m in (p["markets"] or []) if m in MARKETS]
    for k in ("elott_perc", "utan_perc", "zaras_elott_perc"):
        try:
            p[k] = max(0, int(p[k]))
        except (TypeError, ValueError):
            p[k] = DEFAULTS[k]
    return p


def to_utc(server_time) -> _dt.datetime:
    """A SZERVER idejéből valódi UTC.

    A bejövő időbélyeg szerver-időt hordoz — akkor is, ha `tzinfo=UTC` van rajta
    (a gyertya-fájlok így tárolják). Ezért a wall-clock mezőket vesszük, és azokat
    olvassuk BERLINI helyi időként; a DST-t a `zoneinfo` intézi."""
    t = server_time
    naiv = _dt.datetime(t.year, t.month, t.day, t.hour, t.minute,
                        getattr(t, "second", 0))
    return naiv.replace(tzinfo=ZoneInfo(SERVER_ZONE)).astimezone(_dt.timezone.utc)


def market_state(utc_time: _dt.datetime, market: str, params: dict | None = None) -> str:
    """EGY piac állapota. A hétvége zárva (a piac SAJÁT helyi naptára szerint)."""
    spec = MARKETS.get(market)
    if spec is None:
        return ZARVA
    P = _P(params)
    helyi = utc_time.astimezone(ZoneInfo(spec["zone"]))
    if helyi.weekday() >= 5:                      # szombat/vasárnap
        return ZARVA
    perc = helyi.hour * 60 + helyi.minute
    nyit = spec["open"][0] * 60 + spec["open"][1]
    zar = spec["close"][0] * 60 + spec["close"][1]
    if nyit - P["elott_perc"] <= perc < nyit:
        return NYITAS_ELOTT
    if perc == nyit:
        return NYITAS
    if nyit < perc < nyit + P["utan_perc"] + 1:
        return NYITAS_UTAN
    if zar - P["zaras_elott_perc"] <= perc < zar:
        return ZARAS_ELOTT
    if nyit <= perc < zar:
        return NYITVA
    return ZARVA


def state_at(utc_time: _dt.datetime, params: dict | None = None) -> tuple:
    """`(állapot, piac)` — a figyelt piacok közül a LEGÉLESEBB állapot, és hogy
    melyik piac okozza. Ha minden figyelt piac zárva, `(ZARVA, None)`.

    Ez az a pont, ahol a felhasználó „ÉS / VAGY" kérése FELOLDÓDIK: a „bármelyik
    piac nyitás utáni ablakában" = VAGY, a „mindegyik zárva" = ÉS. Mindkettő
    EGYETLEN állapot a piac-halmazon, tehát nem kell szabály-motor hozzá."""
    P = _P(params)
    legjobb, ki = ZARVA, None
    for m in P["markets"]:
        st = market_state(utc_time, m, P)
        if STATES.index(st) < STATES.index(legjobb):
            legjobb, ki = st, m
    return legjobb, ki


def state_of_server(server_time, params: dict | None = None) -> tuple:
    """Ugyanaz, de SZERVER időből (a hívók ezt adják: gyertya-idő vagy óra)."""
    return state_at(to_utc(server_time), params)


# ---------------------------------------------------------------------------
# A kapu-szerződés
# ---------------------------------------------------------------------------
def failed(state: str, adverse) -> bool:
    """Bukott-e a kapu? `adverse` = azok az állapotok, amiket a felhasználó
    kedvezőtlennek jelölt. Sáv (létra) esetén ez nem dönt — akkor a szint
    kategóriája dönti el a hatást, mint a piac-kapunál."""
    return bool(state) and state in set(adverse or ())


def measure(ctx) -> tuple:
    """`(bukott_e, szint)` — a szint maga az ÁLLAPOT (kategória-kapu)."""
    now = getattr(ctx, "now", None)
    if now is None:
        return False, None
    P = params_of(ctx.pair_cfg, ctx.cfg)
    st, _m = state_of_server(now, P)
    return failed(st, adverse_of(ctx.pair_cfg, ctx.cfg)), st


def block_log(ctx) -> str:
    """A blokkolás EMBERI indoklása — melyik piac, melyik állapot, hány perc."""
    now = getattr(ctx, "now", None)
    if now is None:
        return "piaci nyitások: nincs idő a kontextusban"
    P = params_of(ctx.pair_cfg, ctx.cfg)
    st, m = state_of_server(now, P)
    # ⚠ A `LabelMap` SZÓTÁR-ként viselkedik (indexelés/`get`), nincs `.label()`
    # metódusa — a feliratot a hívás pillanatában oldja fel, hogy nyelvváltásnál
    # ne fagyjon be. Egy `.label(...)` hívás itt AttributeError-t dobott, amit a
    # keret elnyelt, és a napló a generikus „a kapu blokkolt" mondatot kapta.
    _piac = MARKET_LABEL.get(m, m) if m else "—"
    return (f"piaci nyitások: {STATE_LABEL.get(st, st)} ({_piac}) → kimarad. "
            f"Ablakok: nyitás előtt {P['elott_perc']}, után {P['utan_perc']}, "
            f"zárás előtt {P['zaras_elott_perc']} perc.")


def evaluate(ctx: dict) -> tuple:
    """A KIJELZÉS állapota + emberi mondat (a keret `evaluate()`-je hívja).

    ⚠ ITT NEM SZÁMOLUNK ÚJRA. Az állapotot a kijelzés-út már kimérte (az utolsó
    zárt M15 gyertya idejéből), és azt a `ctx` hozza. Ha itt a mostani óráról
    kérdeznénk, a „Piacok" oszlop és a sor-jelvény MÁS pillanatot mutatna, mint
    a cella melletti szöveg — pont az a néma szétcsúszás, amit a projekt már
    többször megfizetett.

    A `blocking` állapot itt azt jelenti, hogy a felhasználó KEDVEZŐTLENNEK
    jelölte ezt az állapotot. Alapból nincs ilyen: a kapu mutat, nem tilt."""
    from core.gates import PASS, BLOCKING, UNKNOWN
    st = (ctx or {}).get("sessions_state")
    if not st:
        return UNKNOWN, _t("gate.why.no_bars")
    m = (ctx or {}).get("sessions_market")
    txt = (STATE_LABEL.get(st, st) + " — "
           + (MARKET_LABEL.get(m, m) if m else STATE_LABEL.get(ZARVA, ZARVA)))
    adverse = adverse_of((ctx or {}).get("pair_cfg") or {}, None)
    return (BLOCKING if failed(st, adverse) else PASS), txt


# ---------------------------------------------------------------------------
# Config — a szokásos öröklődéssel (pár → globális → beépített)
# ---------------------------------------------------------------------------
def params_of(pair_cfg: dict | None, cfg: dict | None) -> dict:
    """A kapu beállításai: `pairs.<SYM>.sessions` → `sessions` → `DEFAULTS`."""
    p = dict(DEFAULTS)
    for forras in ((cfg or {}).get("sessions"), (pair_cfg or {}).get("sessions")):
        if isinstance(forras, dict):
            for k in DEFAULTS:
                if forras.get(k) is not None:
                    p[k] = forras[k]
    return _P(p)


def adverse_of(pair_cfg: dict | None, cfg: dict | None) -> set:
    """A KEDVEZŐTLENNEK jelölt állapotok. ⚠ Alapból ÜRES: a kapu csak mutat.
    Lásd a modul fejlécét — a blokkolást mérés nélkül nem kapcsoljuk be."""
    for forras in ((pair_cfg or {}).get("sessions"), (cfg or {}).get("sessions")):
        if isinstance(forras, dict) and forras.get("adverse") is not None:
            return {s for s in (forras.get("adverse") or []) if s in STATES}
    return set()
