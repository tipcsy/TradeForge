"""MI FOG TÖRTÉNNI, ha megnyomod az OPT gombot?

A felhasználói dokumentáció (`Paraméterek vs OPT vs Backtest`) legsúlyosabb
panasza nem a sebesség volt, hanem hogy az optimalizálás **átláthatatlan**:

    „Nem látom az időintervallumot · nem látom a lehetséges paramétereket ·
     nem tudom csak egyes paramétereket optimalizálni · nem látom, melyik kapu
     működött · nem tudom, milyen időintervallumban történt az optimalizálás,
     és milyenben a tesztelés."

Ez a modul MINDET megválaszolja — FUTTATÁS NÉLKÜL. Nem becslés és nem másolat:
ugyanazokat a függvényeket hívja, amiket maga az optimalizáló
(`_walk_forward_windows`, `core.gates.effects_for`, `param_class`), tehát amit
itt látsz, az az, ami történni fog.

⚠ Miért nem másoltam a logikát ide: egy külön „kijelző-számítás" az első
config-változásnál elcsúszna az igazitól, és a felület MAGABIZTOSAN hazudna. Egy
hibás szám rosszabb, mint a hiányzó szám — a felhasználó ez alapján dönt arról,
hogy órákra elindít-e egy futást.

A modul KÖNNYŰ: nincs optuna/MT5 függése, hogy a dashboard az optimalizáló
importja nélkül is használhassa.
"""
from __future__ import annotations

from core.i18n import t as _t

import logging

log = logging.getLogger(__name__)

# A kihagyott (nem hangolt) paraméterek helye a configban:
#   pairs.<SYMBOL>.optimizer_skip.<strategy> = ["kulcs", ...]
# Pár+stratégia szintű, mert a „most csak az SMA-t hangolom" jellemzően EGY
# instrumentumra szól. A `config_check` házirendje szerint csak az ELTÉRÉS
# kerül a fájlba: üres lista → a kulcs kikerül.
_SKIP_SECTION = "optimizer_skip"


# ---------------------------------------------------------------------------
# Melyik paramétereket hangoljuk?
# ---------------------------------------------------------------------------

def skip_keys(cfg: dict, symbol: str, strategy: str) -> set:
    """A KIHAGYOTT (nem hangolt) paraméter-kulcsok erre a (pár, stratégia) párra."""
    sec = ((cfg or {}).get("pairs", {}).get(symbol) or {}).get(_SKIP_SECTION) or {}
    val = sec.get(strategy)
    return set(val) if isinstance(val, (list, tuple, set)) else set()


def set_skip_keys(cfg: dict, symbol: str, strategy: str, keys) -> dict:
    """A kihagyott kulcsok beállítása (a `cfg`-t HELYBEN módosítja, és vissza is adja).

    Üres halmaznál a bejegyzés KIKERÜL a configból — a házirend szerint a config
    csak az alapértelmezéstől való ELTÉRÉST rögzíti (különben egy üres lista
    „beállításnak" látszana, és a későbbi alapérték-változás némán hatástalan
    maradna rá).
    """
    cfg = cfg if cfg is not None else {}
    pairs = cfg.setdefault("pairs", {})
    pc = pairs.setdefault(symbol, {})
    sec = pc.get(_SKIP_SECTION) or {}
    keys = sorted(set(keys or ()))
    if keys:
        sec[strategy] = keys
        pc[_SKIP_SECTION] = sec
    else:
        sec.pop(strategy, None)
        if sec:
            pc[_SKIP_SECTION] = sec
        else:
            pc.pop(_SKIP_SECTION, None)
    return cfg


def tuned_specs(opt_cfg: dict) -> dict:
    """A hangolható kulcsok tartomány-specifikációi (`{kulcs: {min,max,step,…}}`)."""
    return {k: v for k, v in (opt_cfg or {}).items()
            if isinstance(v, dict) and "min" in v}


def grid_values(spec: dict) -> list:
    """A tartomány DISZKRÉT értékei — a söprés ezeket járja végig.

    ⚠ Az EGÉSZ/TÖRT jelleget a `min` típusa dönti el, ugyanúgy, ahogy az
    optimalizáló (`suggest_int` vs `suggest_float`). Ha egy egész paraméter
    (sma_period) tört értékeket kapna, az indikátor-motor vagy elszállna, vagy
    némán csonkolna — és a söprés görbéjén két szomszédos pont ugyanaz lenne.
    """
    try:
        lo, hi, step = spec["min"], spec["max"], spec["step"]
        as_int = isinstance(lo, int) and isinstance(step, int) and not isinstance(lo, bool)
        lo, hi, step = float(lo), float(hi), float(step)
        if step <= 0 or hi < lo:
            return []
        n = int(round((hi - lo) / step, 9)) + 1
        out = []
        for i in range(n):
            v = lo + i * step
            out.append(int(round(v)) if as_int else round(v, 10))
        return out
    except Exception:
        return []


def grid_size(spec: dict) -> int:
    """Hány DISZKRÉT érték áll elő ebből a tartományból? (A rács, nem a folytonos tér.)

    A `grid_values` hosszával AZONOS — egy helyen definiált, hogy a felületen
    kiírt darabszám és a ténylegesen lefutó söprés ne térhessen el.
    """
    return len(grid_values(spec))


def param_rows(cfg: dict, symbol: str, strategy_name: str, opt_cfg: dict,
               current: dict | None = None) -> list:
    """Soronként MINDEN hangolható paraméter — a felület ebből épít táblát.

    Mezők: `key`, `min`, `max`, `step`, `values` (rács-méret), `cls`
    (`signal`/`execution`), `skipped`, `current` (a most betöltött érték),
    `category` (a meglévő csoportosítás a param_meta-ból).
    """
    from strategy.settings import load_strategy_config, param_class
    try:
        scfg = load_strategy_config(strategy_name)
    except Exception:
        scfg = {}
    meta = ((scfg.get("param_meta") or {}).get("params") or {})
    skipped = skip_keys(cfg, symbol, strategy_name)
    rows = []
    for key, spec in sorted(tuned_specs(opt_cfg).items()):
        rows.append({
            "key": key,
            "min": spec.get("min"), "max": spec.get("max"), "step": spec.get("step"),
            "values": grid_size(spec),
            "cls": param_class(scfg, key),
            "skipped": key in skipped,
            "current": (current or {}).get(key),
            "category": (meta.get(key) or {}).get("category", ""),
        })
    return rows


def search_space(rows: list) -> int:
    """A HANGOLT dimenziók rácsának szorzata — „hány kombináció közül választ".

    ⚠ Ez nem a trialok száma: az optuna nem járja be a teret, hanem mintavételez.
    A szám azért hasznos, mert megmutatja az ARÁNYT: 500 trial egy 10^9-es
    térben más állítás, mint egy 200-asban.
    """
    total = 1
    for r in rows:
        if r["skipped"] or r["values"] <= 0:
            continue
        total *= r["values"]
        if total > 10 ** 18:
            return 10 ** 18            # jelzés-érték: „gyakorlatilag végtelen"
    return total


# ---------------------------------------------------------------------------
# MI LESZ EBBŐL: egyetlen futás, végigpróbálás, rács vagy optimalizálás?
#
# ⚠ A FELÜLETEN NEM SZEREPEL a „söprés" szó. A felhasználó szó szerint: „A
# söprés szót mellőzzük, egyszerűen nem értem, hogy ebben a kontextusban mit
# jelent." Igaza volt: szakmai jövevényszó (parameter sweep), ami semmit nem
# mond arról, MI történik. A „végigpróbálás" magától érthető. A KÓDBAN a
# `KIND_SWEEP`/`sweep` név megmarad — az a modul neve, nem felirat.
# ---------------------------------------------------------------------------
# A felhasználói doksi felismerése:
#
#   „OPT = paraméter beállít; teljes futtatás; kiértékelés — és ez 500-szor.
#    Backtest ugyanez, csak a kiértékelés manuálisan történik."
#
# Ha ez igaz — és igaz —, akkor nem két funkció van, hanem EGY, aminek a
# futásszáma különbözik. És a futásszámot nem kell külön beállítani: kiderül
# abból, hány paraméternek adtunk tartományt. Ez a levezetés teszi értelmessé a
# „csak az SMA-t 100→200-ig backtesteljük" kérést is: az az 1 hangolt paraméter
# esete, nem külön funkció.

KIND_SINGLE = "single"      # 0 hangolt → egyetlen futás (a mai backtest)
KIND_SWEEP = "sweep"        # 1 hangolt → görbe
KIND_GRID = "grid"          # 2 hangolt → hőtérkép
KIND_OPTIMIZE = "optimize"  # 3+        → optuna mintavétel


def run_plan(rows: list, trials: int = 500) -> dict:
    """A HANGOLT sorokból: mi fog történni, és hány futásból.

    `rows`: `param_rows` kimenete (a `skipped` mező a pillanatnyi állapot).
    Visszaad: `kind`, `runs` (hány kiértékelés), `tuned` (kulcsok), `text`.

    ⚠ A `runs` a rács/söprés ágon PONTOS (végigpróbáljuk), az optimalizálás
    ágon a mintaszám — ott a tér ennél nagyságrendekkel nagyobb. A kettőt nem
    szabad ugyanúgy nevezni: az egyik kimerítő, a másik mintavétel.
    """
    tuned = [r for r in rows if not r.get("skipped") and r.get("values", 0) > 0]
    keys = [r["key"] for r in tuned]
    if not tuned:
        return {"kind": KIND_SINGLE, "runs": 1, "tuned": [], "exhaustive": True,
                "text": _t("plan.single")}
    if len(tuned) == 1:
        n = tuned[0]["values"]
        return {"kind": KIND_SWEEP, "runs": n, "tuned": keys, "exhaustive": True,
                "text": _t("plan.sweep", runs=n, key=keys[0])}
    if len(tuned) == 2:
        a, b = tuned[0]["values"], tuned[1]["values"]
        return {"kind": KIND_GRID, "runs": a * b, "tuned": keys, "exhaustive": True,
                "text": _t("plan.grid", a=a, b=b, runs=a * b)}
    return {"kind": KIND_OPTIMIZE, "runs": int(trials), "tuned": keys,
            "exhaustive": False,
            "text": _t("plan.optimize", n=len(tuned), trials=int(trials))}


def estimate_minutes(runs: int, sec_per_run: float, windows: int = 1) -> float:
    """Durva időbecslés percben. `sec_per_run`: egy ablak egy kiértékelése.

    ⚠ Szándékosan DURVA: a valódi idő paraméterfüggő (több kötés = lassabb), és
    a korai elbukó trialok gyorsak. A becslés arra jó, hogy „3 perc" és „6 óra"
    között dönts — nem arra, hogy percre tervezz.
    """
    return max(0.0, runs * max(1, windows) * max(0.0, sec_per_run) / 60.0)


# ---------------------------------------------------------------------------
# Mikor tanul és mikor vizsgázik?
# ---------------------------------------------------------------------------

def windows(df_m15, n_splits: int, train_months: int, test_months: int) -> list:
    """A walk-forward ablakok — UGYANAZ a függvény, amit az optimalizáló hív."""
    try:
        from ml.optimizer import _walk_forward_windows
        return _walk_forward_windows(df_m15, n_splits, train_months, test_months)
    except Exception as ex:                       # optuna nélküli környezet
        log.debug("walk-forward ablakok nem számolhatók: %s", ex)
        return []


def window_rows(df_m15, n_splits: int, train_months: int, test_months: int) -> list:
    """Ablakonként `{i, train_start, test_start, test_end}` — a felület táblájához."""
    return [{"i": i + 1,
             "train_start": w["train_start"], "test_start": w["test_start"],
             "test_end": w["test_end"]}
            for i, w in enumerate(windows(df_m15, n_splits, train_months, test_months))]


# ---------------------------------------------------------------------------
# Az egész terv egy hívásban
# ---------------------------------------------------------------------------

def build(cfg: dict, symbol: str, strategy, opt_cfg: dict, df_m15=None,
          current: dict | None = None) -> dict:
    """Az OPT gomb TELJES elő-képe. Futtatás nélkül, a valódi forrásokból."""
    from core import gates as _gt

    # ⚠ A kulcsok NEM ugyanonnan jönnek: a walk-forward beosztás a STRATÉGIA
    # optimizer-szekciójából (`opt_cfg`, ahogy az `optimize_symbol` is olvassa),
    # az `exec_gates` viszont MOTOR-kulcs (a fő config.json-ban marad — lásd
    # `OPTIMIZER_ENGINE_KEYS`). Ha ezt elvétenénk, a panel más számot mutatna,
    # mint amivel a futás indul.
    opt_cfg = opt_cfg or {}
    n_splits = int(opt_cfg.get("wf_n_splits", 4) or 4)
    train_m = int(opt_cfg.get("wf_train_months", 6) or 6)
    test_m = int(opt_cfg.get("wf_test_months", 2) or 2)
    exec_gates = bool((cfg or {}).get("optimizer", {}).get("exec_gates", True))

    rows = param_rows(cfg, symbol, strategy.name, opt_cfg, current)
    wins = window_rows(df_m15, n_splits, train_m, test_m) if df_m15 is not None else []

    # ⚠ A kapuk: az optimalizáló CSAK akkor modellezi őket, ha az `exec_gates`
    # be van kapcsolva. Ha ki van, akkor a kapu-beállítás LÁTSZÓLAG él, de az
    # optimalizálás nem tud róla — és a mentett paraméterek olyan világból
    # jönnek, ami élesben nem létezik. Ezt ki KELL írni.
    effects = (_gt.effects_for(cfg or {}, symbol, strategy.name)
               if exec_gates else {k: _gt.EFFECT_NONE for k in _gt.KEYS})

    data_from = data_to = None
    if df_m15 is not None and len(df_m15):
        data_from, data_to = df_m15.index.min(), df_m15.index.max()

    return {
        "symbol": symbol, "strategy": strategy.name,
        "params": rows,
        "tuned": [r["key"] for r in rows if not r["skipped"]],
        "skipped": [r["key"] for r in rows if r["skipped"]],
        "signal_tuned": [r["key"] for r in rows
                         if not r["skipped"] and r["cls"] == "signal"],
        "exec_tuned": [r["key"] for r in rows
                       if not r["skipped"] and r["cls"] == "execution"],
        "space": search_space(rows),
        "windows": wins,
        "wf": {"splits": n_splits, "train_months": train_m, "test_months": test_m},
        "exec_gates": exec_gates,
        "gate_effects": effects,
        "data_from": data_from, "data_to": data_to,
        "nested": bool(opt_cfg.get("nested", False)),
        "inner_trials": int(opt_cfg.get("inner_trials", 8) or 8),
    }
