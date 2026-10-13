"""
Per-pár kockázatcsökkentő ÁLLAPOT — perzisztens JSON-ban (`data/risk_mode.json`).

Instrumentumonként: PRESET (off|risky|halving/Felező|shield/Pajzs) + haladó
felülbírálások: `cautious` (óvatos/felezett belépő-méret, None=preset szerint) és
`runner` (a maradék stopja: keep|breakeven|trailing, None=default=trailing).

Fájlformátum (visszafelé kompatibilis): érték lehet sima string (csak preset) VAGY
dict {"preset","cautious","runner"}. Régi string → {"preset": string}.

A régi `risky_mode` (R gomb, kívülről is írható) MEGMARAD: `effective_preset`
egyesíti — ha itt 'off' de a risky_mode be van kapcsolva → 'risky'.

⚠ STRATÉGIÁNKÉNTI FELÜLÍRÁS (2026-10-13, Tibi: „az egyes stratégiáknak lehet
külön kiszállójuk"). A pár bejegyzése a pár ALAPJA; alatta egy opcionális
`strategies` blokk stratégiánként CSAK AZ ELTÉRÉST tartja:

    "Ger40": {"preset": "off", "breakeven_r": 1.0,
              "strategies": {"csilla": {"preset": "shield", "runner": "exit"}}}

Minden lekérdező kap egy opcionális `strategy` paramétert: ha a stratégiának van
felülírása, az a kulcs nyer, különben a pár alapja érvényes (ugyanaz az öröklés,
mint a kapuknál). `strategy=None` → PONTOSAN a régi, páronkénti viselkedés — a
meglévő fájlok és hívók változtatás nélkül működnek. Egy páron futó két stratégia
eddig OSZTOZOTT a kiszálláson; az egyikre hangolt kilépés a másikat rontotta.
"""

import json
import logging
import threading
from pathlib import Path

from core import risky_mode
from core.risk_reduction import (
    PRESET_NONE, PRESET_OFF, PRESET_RISKY, PRESET_HALVING, PRESET_SHIELD,
    PRESET_FIBO, PRESET_THIRDS, PRESET_SHIELD_FIBO, PRESETS,
    RUNNER_KEEP, RUNNER_BREAKEVEN, RUNNER_TRAILING, RUNNER_EXIT,
    BE_TRAIL_KEYS, be_trail_active, default_config, wants_cautious_size,
    parse_hhmm,
)
from core import exit_signal
from core.i18n import LabelMap as _LabelMap

log = logging.getLogger(__name__)

PATH = Path(__file__).resolve().parents[1] / "data" / "risk_mode.json"

CYCLE = (PRESET_NONE, PRESET_OFF, PRESET_RISKY, PRESET_HALVING, PRESET_SHIELD,
         PRESET_FIBO, PRESET_THIRDS, PRESET_SHIELD_FIBO)
# ⚠ LabelMap, nem sima szótár: a felület ezekből építi a legördülőt ÉS ebből
# fejti vissza a választást. Egy betöltéskor kiszámolt tábla befagyna a
# nyelvvel, és a két oldal elcsúszna — lásd `core.i18n.LabelMap`.
LABEL = _LabelMap("rr.short", CYCLE)
# ⚠ Az `off` NEVE volt hazug, nem a viselkedése: mindig BE-t és trailinget
# futtatott. A KULCS marad (a mentett állapot és a viselkedés érintetlen), csak a
# felirat mond végre igazat. A „semmi" ezentúl a külön `none`.
NAME = _LabelMap("rr.name", CYCLE)
RUNNERS = (RUNNER_TRAILING, RUNNER_KEEP, RUNNER_BREAKEVEN, RUNNER_EXIT)
RUNNER_NAME = _LabelMap("rr.runner", RUNNERS)

# A per-pár kiszállási-modul beállítás mezői (a core.exit_signal.default_config
# kulcsai az `enabled` NÉLKÜL — az `enabled`-et a runner==exit vezérli).
_EXIT_KEYS = ("indicator", "timeframe", "st_period", "st_multiplier",
              "wpr_period", "wpr_ma_period", "osc", "div_period", "div_pivot")

_lock = threading.Lock()
_state: dict[str, dict] = {}

# Numerikus kalibrációs override-ok (az optimalizáló írhatja): ha jelen vannak, a
# spec_for felülírja velük a default_config() megfelelő kulcsait. Hiányukban a
# default_config érvényes (visszafelé kompatibilis: a régi fájlokban nincsenek).
_CALIB_KEYS = ("trigger_R", "halving_fraction", "shield_fraction",
               "fibo_level", "fibo_stop_level", "thirds_base_R", "cost_cut_bars",
               "big_move_atr_mult",
               # v1.96.0: a BE + trailing IDE költözött a közös végrehajtási
               # configból — ezek is a kimenet-menedzsment paraméterei.
               *BE_TRAIL_KEYS,
               # ⚠ A `breakeven_r` SZÁNDÉKOSAN nincs a `BE_TRAIL_KEYS`-ben, csak
               # itt. Az a sorozat rögzített szerződés (az optimalizáló
               # rr-keresési tere és három teszt EGYENLŐSÉGET vár rá, pl.
               # `MIGRATED_KEYS == set(BE_TRAIL_KEYS)`) — bővítve némán elbukna
               # olyasmi, aminek semmi köze ehhez. Per-pár menthetőnek viszont
               # kell lennie, ezért a kalibrációs kulcsok közt a helye.
               "breakeven_r")


_OVERRIDE_KEYS = ("preset", "cautious", "cost_cut", "eod_close", "max_hold_min",
                  "runner", "exit") + _CALIB_KEYS


def _norm_override(v) -> dict:
    """Egy stratégia-felülírás normalizálása: CSAK a megadott kulcsok maradnak
    (a hiányzó = örökölt a pártól). Ugyanazok a szabályok, mint a pár alapjánál."""
    if not isinstance(v, dict):
        return {}
    teljes = _norm({**v, "preset": v.get("preset", PRESET_OFF)})
    out = {k: teljes[k] for k in _OVERRIDE_KEYS if k in teljes and k in v}
    if "cautious" in v and v["cautious"] is None:
        out["cautious"] = None
    return out


def _norm(v) -> dict:
    """Érték normalizálása dict-re (régi string → {preset})."""
    if isinstance(v, str):
        return {"preset": v if v in PRESETS else PRESET_OFF}
    if isinstance(v, dict):
        d = {"preset": v.get("preset", PRESET_OFF)}
        if d["preset"] not in PRESETS:
            d["preset"] = PRESET_OFF
        if v.get("cautious") is not None:
            d["cautious"] = bool(v["cautious"])
        if v.get("cost_cut") is not None:
            d["cost_cut"] = bool(v["cost_cut"])
        # Idő-kilépés (2026-10-02): napvégi zárás "HH:MM" (kanonikus fal-óra) +
        # max. tartás percben. Az érvénytelen időt NEM tároljuk (= kikapcsolva).
        if isinstance(v.get("eod_close"), str) and (
                v["eod_close"] == "" or parse_hhmm(v["eod_close"]) is not None):
            d["eod_close"] = v["eod_close"]
        if isinstance(v.get("max_hold_min"), (int, float)) and v["max_hold_min"] >= 0:
            d["max_hold_min"] = float(v["max_hold_min"])
        if v.get("runner") in RUNNERS:
            d["runner"] = v["runner"]
        for k in _CALIB_KEYS:
            if isinstance(v.get(k), (int, float)):
                d[k] = float(v[k])
        # Per-pár kiszállási-modul beállítás (csak az ismert kulcsok, ha van).
        ex = v.get("exit")
        if isinstance(ex, dict):
            d["exit"] = {k: ex[k] for k in _EXIT_KEYS if k in ex}
        st = v.get("strategies")
        if isinstance(st, dict):
            ov = {str(n): _norm_override(o) for n, o in st.items()}
            ov = {n: o for n, o in ov.items() if o}
            if ov:
                d["strategies"] = ov
        return d
    return {"preset": PRESET_OFF}


def load() -> dict:
    with _lock:
        try:
            if PATH.exists():
                with open(PATH, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _state.clear()
                    _state.update({str(k): _norm(v) for k, v in data.items()})
        except Exception as ex:
            # ⚠ EZ A MODUL LEGVESZÉLYESEBB NÉMA HIBÁJA. A fájl nem csak a
            # presetet hordozza, hanem a per-pár KALIBRÁCIÓT is (`_CALIB_KEYS`:
            # breakeven_pct, breakeven_r, trailing, trigger_R, frakciók). Ha
            # sérült vagy zárolt, MINDEN pár a modul alapértékére esik vissza —
            # `breakeven_r = 0`, azaz pontosan az a célár-arányos BE, aminek a
            # kikapcsolása egy egész napi hibakeresésbe került (lásd
            # `test_breakeven_r.py`). Kívülről ez semmiben nem különbözik a
            # „még nincs beállítás" állapottól, ezért ERROR (a felület a
            # `applog` hibaszámlálójából szól), nem warning.
            log.error("%s: a kockázatcsökkentő állapot NEM OLVASHATÓ (%s) — "
                      "minden pár az ALAPÉRTELMEZETT presetre és kalibrációra "
                      "esik vissza (BE/trailing is). A mentett beállítások NEM "
                      "érvényesülnek.", PATH.name, ex)
        return dict(_state)


def ensure_loaded() -> None:
    """Betöltés, ha még nem történt meg. Azoknak a hívóknak kell (pl.
    `backtest._rr_spec`), amelyek nem tudják, futott-e már a `load()` — és amelyek
    SZOROS ciklusban hívódnak (az optimalizáló 2000× hív `run_pair`-t), tehát a
    feltétel nélküli fájlolvasás pazarlás volna."""
    if not _state:
        load()


def _entry(symbol: str, strategy: str = None) -> dict:
    """A pár bejegyzése — `strategy` megadásával a stratégia felülírásával
    ÖSSZEFÉSÜLVE (a felülírt kulcs nyer; az `exit` blokk kulcsonként)."""
    alap = _state.get(symbol, {"preset": PRESET_OFF})
    if not strategy:
        return alap
    ov = (alap.get("strategies") or {}).get(strategy)
    if not ov:
        return alap
    out = {k: v for k, v in alap.items() if k != "strategies"}
    for k, v in ov.items():
        if k == "exit" and isinstance(v, dict):
            out["exit"] = {**(alap.get("exit") or {}), **v}
        else:
            out[k] = v
    return out


def override_of(symbol: str, strategy: str) -> dict:
    """A stratégia SAJÁT felülírása (üres = mindent örököl a pártól)."""
    with _lock:
        return dict(((_state.get(symbol) or {}).get("strategies") or {})
                    .get(strategy) or {})


def overridden_strategies(symbol: str) -> list:
    """Mely stratégiáknak van saját felülírása ezen a páron."""
    with _lock:
        return sorted(((_state.get(symbol) or {}).get("strategies") or {}).keys())


def clear_override(symbol: str, strategy: str, keys=None) -> None:
    """A stratégia felülírásának törlése („vissza örököltre") — `keys` nélkül
    az egész, különben csak a megadott kulcsok."""
    with _lock:
        d = dict(_state.get(symbol) or {"preset": PRESET_OFF})
        st = dict(d.get("strategies") or {})
        if strategy not in st:
            return
        if keys is None:
            st.pop(strategy, None)
        else:
            o = {k: v for k, v in st[strategy].items() if k not in set(keys)}
            if o:
                st[strategy] = o
            else:
                st.pop(strategy, None)
        if st:
            d["strategies"] = st
        else:
            d.pop("strategies", None)
        _state[symbol] = _norm(d)
        _save_locked()


def get_preset(symbol: str, strategy: str = None) -> str:
    with _lock:
        return _entry(symbol, strategy).get("preset", PRESET_OFF)


def get_runner(symbol: str, strategy: str = None) -> str:
    with _lock:
        return _entry(symbol, strategy).get("runner", default_config()["runner_stop"])


def get_cautious(symbol: str, strategy: str = None):
    """None = a preset szerint (Risky→igen); True/False = kézi felülbírálás."""
    with _lock:
        return _entry(symbol, strategy).get("cautious", None)


def get_calibration(symbol: str, strategy: str = None) -> dict:
    """A per-pár numerikus kalibrációs override-ok (trigger_R/frakciók), ha vannak.
    Üres dict, ha nincs (→ a default_config érvényes)."""
    with _lock:
        e = _entry(symbol, strategy)
        return {k: float(e[k]) for k in _CALIB_KEYS if isinstance(e.get(k), (int, float))}


def _set(symbol: str, strategy: str = None, **kw):
    """Írás a pár ALAPJÁBA, vagy — `strategy` megadásával — a stratégia
    FELÜLÍRÁSÁBA (csak a megadott kulcsok; a többi továbbra is örökölt)."""
    with _lock:
        d = dict(_state.get(symbol) or {"preset": PRESET_OFF})
        if strategy:
            st = dict(d.get("strategies") or {})
            st[strategy] = {**(st.get(strategy) or {}), **kw}
            d["strategies"] = st
        else:
            d.update(kw)
        _state[symbol] = _norm(d)
        _save_locked()


def _sync_risky(symbol: str, preset: str) -> None:
    """A RÉGI `risky_mode` (az „R" gomb és egy KÜLSŐ program által is írt fájl)
    szinkronban tartása a presettel.

    ⚠ MIÉRT ITT, ÉS NEM A HÍVÓKNÁL. Ez az egy sor HÁROM helyen élt egymás
    mellett — a sor „R" gombjánál, a Pozíciók-fül kiszállás-menüjében és az
    instrumentum-ablak preset-választójában —, mindháromnál ugyanazzal a
    kommenttel („mint a másik"), kettőnél néma `except: pass` mögött. Aki
    NEGYEDIKKÉNT hívná a settert (a motor, egy eszköz, egy teszt vagy a tervezett
    karmester), annál a szinkron CSENDBEN elmaradna: a `risky_mode.json` a régi
    értéket őrizné, és az azt olvasó élő/backtest ág MÁS kockázattal futna, mint
    amit a felület mutat. A setternek egy gazdája van, tehát a mellékhatás is ide
    tartozik.

    ⚠ A ZÁRON KÍVÜL hívjuk: a `risky_mode` saját zárat használ, és két zár
    egymásba ágyazása a jövőben holtpontot adhatna."""
    try:
        risky_mode.set_risky(symbol, preset == PRESET_RISKY)
    except Exception as ex:
        # A szinkron elmaradása nem dönthet el egy preset-váltást — de nem is
        # néma: a két állapot ilyenkor eltér, és ezt látni kell a naplóban.
        log.warning("rr_state: a risky_mode szinkronja nem sikerült (%s): %s",
                    symbol, ex)


def set_preset(symbol: str, preset: str, strategy: str = None):
    p = preset if preset in PRESETS else PRESET_OFF
    _set(symbol, strategy, preset=p)
    if not strategy:
        # A régi `risky_mode` PÁRONKÉNTI — csak a pár alapja szinkronizál vele.
        _sync_risky(symbol, p)


def set_runner(symbol: str, runner: str, strategy: str = None):
    _set(symbol, strategy, runner=runner if runner in RUNNERS else RUNNER_TRAILING)


def get_exit_config(symbol: str, strategy: str = None) -> dict:
    """A per-pár KISZÁLLÁSI-MODUL beállítása (core.exit_signal cfg formátumban).
    A default_config-ra ráolvasztjuk a per-pár override-ot, és az `enabled`-et a
    runner-mód dönti: csak akkor él, ha a runner == 'exit' (Kiszállási jel)."""
    cfg = exit_signal.default_config()
    with _lock:
        ov = _entry(symbol, strategy).get("exit")
        runner = _entry(symbol, strategy).get("runner", default_config()["runner_stop"])
    if isinstance(ov, dict):
        cfg.update({k: ov[k] for k in _EXIT_KEYS if k in ov})
    cfg["enabled"] = (runner == RUNNER_EXIT)
    return cfg


def set_exit_config(symbol: str, strategy: str = None, **params):
    """A per-pár kiszállási-modul mezőinek frissítése (indicator/paraméterek).
    Csak az ismert kulcsokat tartja meg; a meglévő override-ot kiegészíti."""
    upd = {k: params[k] for k in _EXIT_KEYS if k in params}
    if not upd:
        return
    with _lock:
        d = dict(_state.get(symbol) or {"preset": PRESET_OFF})
        if strategy:
            st = dict(d.get("strategies") or {})
            o = dict(st.get(strategy) or {})
            o["exit"] = {**(o.get("exit") or {}), **upd}
            st[strategy] = o
            d["strategies"] = st
        else:
            ex = dict(d.get("exit") or {})
            ex.update(upd)
            d["exit"] = ex
        _state[symbol] = _norm(d)
        _save_locked()


def set_cautious(symbol: str, value, strategy: str = None):
    _set(symbol, strategy, cautious=(None if value is None else bool(value)))


def get_cost_cut(symbol: str, strategy: str = None) -> bool:
    """Cost-cut (idő-stop) be van-e kapcsolva a párra. Default: ki."""
    with _lock:
        return bool(_entry(symbol, strategy).get("cost_cut", False))


def set_cost_cut(symbol: str, value: bool, strategy: str = None):
    _set(symbol, strategy, cost_cut=bool(value))


def get_cost_cut_bars(symbol: str, strategy: str = None) -> int:
    """Hány fő-timeframe gyertya után vágjuk le a veszteséges pozíciót."""
    with _lock:
        v = _entry(symbol, strategy).get("cost_cut_bars")
    return int(v) if isinstance(v, (int, float)) else int(default_config()["cost_cut_bars"])


def set_cost_cut_bars(symbol: str, bars: int, strategy: str = None):
    if bars > 0:
        _set(symbol, strategy, cost_cut_bars=float(int(bars)))


def get_time_exit(symbol: str, strategy: str = None) -> dict:
    """Az idő-kilépés per-pár beállítása: `{"eod_close": "HH:MM"|"",
    "max_hold_min": perc}` (hiányzó → a default_config: kikapcsolva)."""
    dc = default_config()
    with _lock:
        e = _entry(symbol, strategy)
        return {"eod_close": e.get("eod_close", dc["eod_close"]),
                "max_hold_min": float(e.get("max_hold_min", dc["max_hold_min"]))}


def set_time_exit(symbol: str, eod_close: str = "", max_hold_min: float = 0,
                  strategy: str = None):
    """⚠ Az érvénytelen időpont (pl. "25:00") hibát dob, nem némán kikapcsol."""
    if eod_close and parse_hhmm(eod_close) is None:
        raise ValueError(f"érvénytelen napvégi időpont: {eod_close!r} (HH:MM kell)")
    _set(symbol, strategy, eod_close=str(eod_close or ""),
         max_hold_min=float(max(0, max_hold_min)))


def set_from_optimizer(symbol: str, rr: dict, strategy: str = None):
    """Az optimalizáló nyertes rr-jét a per-pár állapotba írja: preset + runner +
    cautious + numerikus kalibráció (trigger_R/frakciók). A live/GUI ezt veszi át."""
    if not rr:
        return
    kw = {"preset": rr.get("preset", PRESET_OFF),
          "runner": rr.get("runner_stop", RUNNER_TRAILING),
          "cautious": rr.get("cautious")}
    for k in _CALIB_KEYS:
        if isinstance(rr.get(k), (int, float)):
            kw[k] = float(rr[k])
    _set(symbol, strategy, **kw)


def cycle_preset(symbol: str) -> str:
    with _lock:
        d = dict(_entry(symbol))
        cur = d.get("preset", PRESET_OFF)
        nxt = CYCLE[(CYCLE.index(cur) + 1) % len(CYCLE)] if cur in CYCLE else PRESET_RISKY
        d["preset"] = nxt
        _state[symbol] = _norm(d)
        _save_locked()
    # ⚠ A ZÁRON KÍVÜL — és MINDEN preset-váltásnál, nem csak a settereknél.
    _sync_risky(symbol, nxt)
    return nxt


def effective_preset(symbol: str, strategy: str = None) -> str:
    """A ténylegesen érvényes preset: a per-pár (vagy a stratégia felülírta)
    választás, DE ha 'off' és a régi risky_mode (R gomb / külső fájl) be van
    kapcsolva → 'risky'."""
    p = get_preset(symbol, strategy)
    if p == PRESET_OFF and risky_mode.is_risky(symbol):
        return PRESET_RISKY
    return p


def spec_for(symbol: str, strategy: str = None) -> dict:
    """Teljes run_pair kockázatcsökkentő spec az adott párra (preset + runner +
    cautious felülbírálás). A run_pair a `cautious` kulcsot a méretezéshez nézi.

    `strategy` → a stratégia felülírása az örökölt pár-alapra ráfésülve (a motor
    és a backtest a pozíció/futás SAJÁT stratégiájával hívja)."""
    preset = effective_preset(symbol, strategy)
    spec = {**default_config(), "preset": preset,
            "runner_stop": get_runner(symbol, strategy)}
    # Numerikus kalibráció-override (ha az optimalizáló beírta) — különben a default.
    spec.update(get_calibration(symbol, strategy))
    c = get_cautious(symbol, strategy)
    spec["cautious"] = wants_cautious_size(preset) if c is None else bool(c)
    # Cost-cut (idő-stop): per-pár kapcsoló — bármely presettel kombinálható.
    spec["cost_cut"] = get_cost_cut(symbol, strategy)
    # Idő-kilépés (napvégi zárás / max. tartás) — szintén per pár.
    spec.update(get_time_exit(symbol, strategy))
    # A kiszállási-modul beállítása (enabled = runner==exit) — a motor/backtest ezt
    # adja tovább az exit_signal.exit_triggered-nek a runner zárásához.
    spec["exit"] = get_exit_config(symbol, strategy)
    return spec


def all_states() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _state.items()}


def _save_locked():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2, ensure_ascii=False)
        tmp.replace(PATH)
    except Exception as ex:
        # ⚠ A memóriában megvan, a lemezen nincs: a felületen beállított preset
        # (vagy a hangolás kiírta kalibráció) MŰKÖDIK — egészen a következő
        # indításig, amikor nyomtalanul eltűnik.
        log.error("%s: a kockázatcsökkentő állapot MENTÉSE nem sikerült (%s). "
                  "A beállítás csak a memóriában él — újraindítás után elveszik.",
                  PATH.name, ex)
