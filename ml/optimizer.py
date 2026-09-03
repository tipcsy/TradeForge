"""
AI Paraméter Optimalizálás — Random / Grid Search

Működés:
  1. TRAIN adat (history_start → test_start_date): próbálja az összes kombinációt
  2. Legjobb kombináció kiválasztása (max. total_pnl, min. max_drawdown figyelembe véve)
  3. TEST adat (test_start_date → ma): out-of-sample validálás
  4. Eredmények mentése: data/optimized_params.json

Futtatás: python ml/optimizer.py
"""

import csv
import json
import logging
import math
import random
import sys
import time
from copy import deepcopy
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _OPTUNA_AVAILABLE = True
except ImportError:
    _OPTUNA_AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.indicator_engine import compute_indicators
from core.execution_params import load_execution_params
from trading.backtest import load_data, run_pair

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Stratégia-hatókörű path-helperek a KÖZÖS, könnyű modulból (core.params_store) —
# innen re-exportálva, hogy a régi `from ml.optimizer import PARAMS_DIR/params_file`
# importok változatlanul működjenek. A tárolás elrendezését lásd ott.
from core.params_store import (            # noqa: E402  (re-export)
    PARAMS_DIR, set_active_strategy, active_strategy, strategy_dir,
    params_file, trials_file, study_db, done_marker, stop_marker, space_marker,
    migrate_flat_layout,
)


# A trials CSV formátuma: ';' elválasztó + ',' tizedesjel (magyar Excel),
# utf-8-sig BOM. A GUI Excelben nyitja, ill. a paraméter-szerkesztő a `rank`
# oszlop (minőségi rangsor, 1 = legjobb) szerint tölti be az egyes sorokat.
# A sor MÉRÉS-oszlopai. Minden MÁS oszlop a keresett paramétertérhez tartozik,
# tehát az AZONOSSÁG alapja — az `rr_*` dimenziók is (azokat is keressük).
_MERES_OSZLOPOK = frozenset((
    "rank", "score", "trades", "win_rate", "total_pnl", "max_drawdown",
    "profit_factor", "note"))


def _param_kulcs(row: dict) -> tuple:
    """Egy trial-sor paraméter-ujjlenyomata (a mérés-oszlopok nélkül).

    ⚠ A lebegőpontos értékeket KEREKÍTJÜK: a 0,3 és a 0,30000000000000004 ugyanaz
    a készlet, de nyers összehasonlításban két külön sor lenne — és pont ilyen
    „majdnem egyforma" sorok tennék használhatatlanná a listát."""
    ki = []
    for k in sorted(row):
        if k in _MERES_OSZLOPOK:
            continue
        v = row[k]
        ki.append((k, round(v, 6) if isinstance(v, float) else v))
    return tuple(ki)


def _write_trials_csv(rows: list[dict], out_csv: Path) -> int:
    """A kísérlet-lista mentése — paraméterenként EGY sorral.

    ⚠ MIÉRT KELL A DEDUPLIKÁLÁS. Az optuna study adatbázisa perzisztens, a
    TPE-mintavevő pedig szűk, diszkrét térben ÚJRA ÉS ÚJRA ugyanazt a
    kombinációt húzza. Mindegyik külön trial lett, külön sorral, AZONOS
    eredménnyel — a felhasználó szava szerint „ugyanaz az eredmény, csak
    sokszorosítva", ami használhatatlanná tette a listát.
    
    Ez a szűrő a MÁR MEGLÉVŐ, elszennyezett listákat is kitakarítja a következő
    mentéskor: a study-ban benne maradt duplikátumok innen már nem jutnak ki.

    Azonos paramétereknél a MAGASABB score-ú sort tartjuk meg. Determinisztikus
    futásnál a kettő egyezik; ha mégsem, az azt jelenti, hogy az ADAT változott
    két futás között (új gyertyák) — ilyenkor a frissebb, jobb mérés a hasznos."""
    if not rows:
        return 0
    df = pd.DataFrame(rows)

    # ⚠ A RENDEZÉS SZÁM SZERINT, nem betűrend szerint. Ha a `score` oszlop
    # bármiért `object` típusú (pl. egy régebbi verzió pont-tizedessel írta a
    # fájlt, és onnan olvassuk vissza), a `sort_values` LEXIKOGRAFIKUSAN
    # rendezne: a „97.68" nagyobb volna, mint a „739.55", és a lista élére a
    # ROSSZ készlet kerülne. Élesben pontosan ez történt egy takarításkor.
    _szam = pd.to_numeric(df["score"], errors="coerce")
    df = (df.assign(_rendez=_szam)
            .sort_values("_rendez", ascending=False, na_position="last")
            .drop(columns="_rendez")
            .reset_index(drop=True))

    # A rendezés után az ELSŐ előfordulás a legjobb score-ú → azt tartjuk meg.
    _kulcsok = df.apply(lambda r: _param_kulcs(r.to_dict()), axis=1)
    # ⚠ ÜRES ujjlenyomatnál NEM deduplikálunk. Ha a soroknak nincs egyetlen
    # paraméter-oszlopa sem (csak mérések), akkor MINDEGYIK kulcsa `()` volna,
    # és egyetlen sor maradna az egészből — néma adatvesztés.
    if all(len(k) == 0 for k in _kulcsok):
        log.warning("  a kísérlet-sorokban nincs paraméter-oszlop — "
                    "az ismétlődés-szűrés kimarad (%d sor)", len(df))
    else:
        _elott = len(df)
        df = df[~_kulcsok.duplicated()].reset_index(drop=True)
        if _elott != len(df):
            log.info("  a kísérlet-listából %d ismétlődő paraméter-készlet "
                     "kimaradt (%d → %d sor)", _elott - len(df), _elott, len(df))

    # Explicit sorszám (rank): a score-rendezés utáni pozíció → 1 = legjobb.
    df.insert(0, "rank", range(1, len(df) + 1))
    df.to_csv(out_csv, index=False, encoding="utf-8-sig", sep=";", decimal=",")
    return len(df)


# ---------------------------------------------------------------------------
# Paraméter tér generálás
# ---------------------------------------------------------------------------

def _range(spec: dict) -> list:
    """Egész vagy float tartomány generálása a config alapján."""
    lo, hi, step = spec["min"], spec["max"], spec["step"]
    values = []
    v = lo
    while v <= hi + 1e-9:
        values.append(round(v, 6))
        v += step
    return values


def generate_random_params(opt_cfg: dict, base_params: dict, n: int,
                           constraints=None) -> list[dict]:
    """N db véletlen paraméter kombinációt generál.

    constraints: opcionális fn(params)->bool — a stratégia érvényesség-ellenőrzője
    (pl. WPR szint-sorrend). None → nincs szűrés.
    """
    ranges = {
        k: _range(v)
        for k, v in opt_cfg.items()
        if isinstance(v, dict) and "min" in v
    }

    combos = []
    seen = set()
    attempts = 0
    max_attempts = n * 20

    while len(combos) < n and attempts < max_attempts:
        attempts += 1
        p = deepcopy(base_params)
        for key, values in ranges.items():
            p[key] = random.choice(values)

        if constraints is not None and not constraints(p):
            continue

        key_tuple = tuple(sorted(p.items()))
        if key_tuple in seen:
            continue
        seen.add(key_tuple)
        combos.append(p)

    return combos


def generate_grid_params(opt_cfg: dict, base_params: dict,
                         constraints=None) -> list[dict]:
    """Teljes grid — csak kis paramétertérnél használandó!

    constraints: opcionális fn(params)->bool — a stratégia érvényesség-ellenőrzője.
    """
    ranges = {}
    fixed = deepcopy(base_params)

    for k, v in opt_cfg.items():
        if isinstance(v, dict) and "min" in v:
            ranges[k] = _range(v)
        # string értékek (pl. method) kihagyva

    keys = list(ranges.keys())
    combos = []
    for values in product(*[ranges[k] for k in keys]):
        p = deepcopy(fixed)
        for k, v in zip(keys, values):
            p[k] = v

        if constraints is not None and not constraints(p):
            continue

        combos.append(p)

    return combos


# ---------------------------------------------------------------------------
# Értékelési metrika
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# MENNYI KOTES KELL, hogy egy trial eredménye JELENTSEN valamit?
# ---------------------------------------------------------------------------
# ⚠ MÉRVE (2026-08-23), nem ízlésből. A Ger40 998 valódi kötéséből (igazi
# PF = 1,10) bootstrappelve, N kötéses mintákon:
#
#     N kötés     PF 95%    P(PF>2)   P(PF>3)
#         5         5,08      24,5%     14,2%
#        15         2,89      14,8%      4,5%
#        50         1,82       2,9%      0,1%
#
# A régi korlátok (ablakonként 5, összesítve 10) tehát SEMMITŐL nem védtek: egy
# közepes stratégia öt kötésen a minták 14%-ában mutat 3 fölötti PF-et. Élesben
# pontosan ez történt — az EURGBP „PF 5,11 HAT kötésen" alapján lett kiválasztva,
# és a pár azóta gyakorlatilag nem köt. Az optimalizáló így megnyerheti a
# játékot azzal, hogy NEM kereskedik: a zaj jobb pontszámot ad, mint a valódi,
# szerényebb él.
#
# ⚠ AMIT CSERÉBE VÁLLALUNK: egy vékony páron előfordulhat, hogy EGYETLEN
# paraméterkészlet sem éri el a korlátot, és az optimalizálás eredmény nélkül
# tér vissza. Ez nem hiba, hanem a helyes válasz: „ezen az instrumentumon ezzel a
# stratégiával nincs mit hangolni." Korábban ilyenkor egy zajból választott
# készlet került a helyére, „Jó" minősítéssel.
MIN_TRADES_WINDOW = 15      # egy walk-forward VIZSGA-ablakban
MIN_TRADES_TOTAL = 50       # a teljes (train) mintán — a minősítés küszöbével egy szinten


def min_trades_floors(cfg: "dict | None") -> tuple:
    """`(ablakonkénti, összesített)` alsó korlát a configból (`optimizer` blokk).

    A `n_splits` alap 4, tehát az ablakonkénti 15 összesítve ~60 kötést jelent —
    a `core.quality` 50-es küszöbe fölött, vagyis a kiválasztott készlet el TUD
    jutni értékelhető minősítésig."""
    o = ((cfg or {}).get("optimizer") or {})
    try:
        w = int(o.get("min_trades_per_window", MIN_TRADES_WINDOW))
    except (TypeError, ValueError):
        w = MIN_TRADES_WINDOW
    try:
        t = int(o.get("min_trades", MIN_TRADES_TOTAL))
    except (TypeError, ValueError):
        t = MIN_TRADES_TOTAL
    return max(0, w), max(0, t)


def score(summary: dict, min_trades: int = MIN_TRADES_TOTAL) -> float:
    """
    Egyetlen szám ami maximalizálandó.
    Kevés trade esetén bünteti (nem megbízható).
    Drawdown büntető szorzó.
    """
    trades = summary.get("trades", 0)
    if trades < min_trades:
        return -999999.0

    pnl      = summary.get("total_pnl", 0.0)
    max_dd   = summary.get("max_drawdown", 1.0)
    win_rate = summary.get("win_rate", 0.0)
    pf       = summary.get("profit_factor", 1.0)

    if pnl <= 0:
        return pnl  # negatív → egyértelműen rossz

    # Drawdown büntető: 20% felett erősen büntet
    dd_penalty = 1.0 - max(0, max_dd - 0.20) * 3.0
    dd_penalty = max(0.1, dd_penalty)

    return pnl * dd_penalty * math.sqrt(win_rate) * min(pf, 5.0)


# ---------------------------------------------------------------------------
# Walk-forward ablakok generálása
# ---------------------------------------------------------------------------

def _walk_forward_windows(df_m15: pd.DataFrame, n_splits: int = 4,
                           train_months: int = 6, test_months: int = 2) -> list[dict]:
    """
    Gördülő ablakos validáció időablakai.
    Minden ablakban: train_months tanítás + test_months validálás.
    """
    last_ts  = df_m15.index[-1]
    first_ts = df_m15.index[0]
    windows  = []
    test_end = last_ts

    for _ in range(n_splits):
        test_start  = test_end  - pd.DateOffset(months=test_months)
        train_start = test_start - pd.DateOffset(months=train_months)

        if train_start < first_ts:
            break

        # UTC-aware ha szükséges
        def _tz(ts):
            return ts.tz_localize("UTC") if ts.tzinfo is None and df_m15.index.tzinfo is not None else ts

        windows.append({
            "train_start": _tz(train_start),
            "test_start":  _tz(test_start),
            "test_end":    _tz(test_end),
        })
        test_end = test_start

    return list(reversed(windows))  # kronológiai sorrendben


def _score_trades(trades: list, initial_balance: float,
                  min_trades: int = MIN_TRADES_WINDOW) -> float:
    """Zárt trade lista → egyetlen score szám."""
    if len(trades) < min_trades:
        return -999999.0

    pnl_list = [t.pnl_usd for t in trades]
    wins     = [p for p in pnl_list if p > 0]
    losses   = [p for p in pnl_list if p <= 0]

    if not wins:
        return sum(pnl_list)

    balance = initial_balance
    peak    = balance
    max_dd  = 0.0
    for p in pnl_list:
        balance += p
        peak     = max(peak, balance)
        dd       = (peak - balance) / peak if peak > 0 else 0
        max_dd   = max(max_dd, dd)

    total_pnl  = sum(pnl_list)
    win_rate   = len(wins) / len(trades)
    pf         = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 5.0

    if total_pnl <= 0:
        return total_pnl

    dd_penalty = max(0.1, 1.0 - max(0, max_dd - 0.20) * 3.0)
    return total_pnl * dd_penalty * math.sqrt(win_rate) * min(pf, 5.0)


# ---------------------------------------------------------------------------
# Optuna alapú optimalizálás walk-forward validációval
# ---------------------------------------------------------------------------

# ── Kockázatcsökkentés (rr) optimalizálási tere — opt-in: optimizer.optimize_rr ──
# Framework-szintű (bármely stratégiával), ezért a config.json optimizer-blokkban
# felülírható (optimizer.rr_space / optimizer.rr_presets). KRITIKUS invariáns: a
# részleges zárás ≥50% → a halving_fraction alsó határa ≥0.5 (különben stopnál
# nettó mínusz).
_RR_PRESETS = ("none", "off", "risky", "halving", "shield", "fibo", "thirds")
_RR_RUNNERS = ("trailing", "keep", "breakeven")
_RR_SPACE_DEFAULT = {
    "trigger_R":        {"min": 0.5, "max": 2.0, "step": 0.1},
    "halving_fraction": {"min": 0.5, "max": 0.75, "step": 0.05},
    "shield_fraction":  {"min": 0.6, "max": 0.9, "step": 0.05},
    # Preset-specifikus szintek
    "fibo_stop_level":  {"min": 0.0, "max": 0.4, "step": 0.1},
    "thirds_base_R":    {"min": 0.5, "max": 2.0, "step": 0.1},
    # BE + trailing — v1.96.0 óta szintén az rr-hez tartozik
    "breakeven_pct":        {"min": 0.0, "max": 1.0, "step": 0.1},
    "trail_activation_atr": {"min": 0.0, "max": 3.0, "step": 0.1},
    "trail_distance_atr":   {"min": 0.2, "max": 2.5, "step": 0.1},
}


def _suggest_rr(trial, opt_cfg: dict) -> dict:
    """Optuna trial → rr-spec, FELTÉTELES keresési térrel.

    A korábbi változat LAPOS volt: minden dimenziót minden trialen sorsolt, akkor
    is, ha a preset nem használja — a `halving_fraction`-t `off`/`risky` preseten,
    a `shield_fraction`-t `halving`-nál stb. Ezek ELPAZAROLT tengelyek voltak
    (ugyanaz a hibafajta, mint a `max_open_slots` a stratégia-térben): a TPE
    mintavevő rájuk is modellezett, a trials-CSV pedig olyan számot mutatott,
    aminek semmi hatása nem volt az eredményre.

    Most csak abban az ágban `suggest`-elünk, ahol a paraméter TÉNYLEGESEN hat —
    ezt az Optuna natívan támogatja (feltételes keresési tér).

    ⚠ A `be_trail_active` HALMAZT ad; azon iterálni NEM szabad, mert a str-hash
    randomizálás miatt a sorrend processzenként más lenne → az azonos seedű study
    sem lenne reprodukálható. Ezért a rögzített `BE_TRAIL_KEYS` sorrendben megyünk."""
    from core import risk_reduction as _rr
    space = {**_RR_SPACE_DEFAULT, **(opt_cfg.get("rr_space") or {})}
    presets = [p for p in (opt_cfg.get("rr_presets") or _RR_PRESETS)
               if p in _rr.PRESETS]
    runners = list(opt_cfg.get("rr_runners") or _RR_RUNNERS)

    def _f(key):
        s = space[key]
        return trial.suggest_float(f"rr_{key}", float(s["min"]), float(s["max"]),
                                   step=float(s["step"]))

    preset = trial.suggest_categorical("rr_preset", presets or list(_RR_PRESETS))
    spec = {"preset": preset, "cautious": _rr.wants_cautious_size(preset)}

    # Runner + részleges zárás: CSAK a Felező/Pajzs (és a rájuk oldódó auto) ágon.
    partial = preset in (_rr.PRESET_HALVING, _rr.PRESET_SHIELD,
                         _rr.PRESET_SHIELD_FIBO)
    if partial:
        spec["runner_stop"] = trial.suggest_categorical("rr_runner", runners)
        spec["trigger_R"] = _f("trigger_R")
        # CSAK a SAJÁT frakcióját — a másik preseté itt értelmezhetetlen.
        if preset == _rr.PRESET_HALVING:
            spec["halving_fraction"] = _f("halving_fraction")
        else:
            spec["shield_fraction"] = _f("shield_fraction")
    else:
        # A spec akkor is TELJES legyen (a mentés/CSV egységes alakot vár), de ez
        # az érték nem hat — nem is sorsoltuk.
        spec["runner_stop"] = _rr.RUNNER_TRAILING

    if preset == _rr.PRESET_FIBO:
        spec["fibo_stop_level"] = _f("fibo_stop_level")
    if preset == _rr.PRESET_THIRDS:
        spec["thirds_base_R"] = _f("thirds_base_R")

    # BE + trailing: pontosan ott, ahol hat (a preset ÉS a runner dönti el).
    _act = _rr.be_trail_active(preset, spec["runner_stop"])
    for key in _rr.BE_TRAIL_KEYS:          # RÖGZÍTETT sorrend — lásd a docstringet
        if key in _act:
            spec[key] = _f(key)
    return spec


def _rr_for_run(spec: "dict | None"):
    """A run_pair-nek átadható rr.

    ⚠ Korábban a `preset == 'off'` esetet None-ra fordítottuk (hogy bitazonos
    legyen a `rr=None` úttal). v1.96.0 óta ez HIBÁS volna: az `off` preset a
    BE/trailing értékeit is HORDOZZA, és ha None-t adnánk, a `_rr_spec` a PÁR
    mentett értékeit venné a trial által keresett helyett — vagyis a keresés
    eredményét némán eldobnánk.

    A `rr=None` út (optimize_rr kikapcsolva) változatlan: oda spec sem érkezik."""
    return spec or None


def _dep_order(specs: dict) -> list:
    """A range-paraméterek suggeszt-SORRENDJE: a `gt`/`lt`-vel hivatkozott
    paramétereket ELŐBB kell suggesztálni, hogy a dinamikus tartomány (lásd
    `_suggest_params`) az ő értékükből szűkíthető legyen. Kahn-szerű topologikus
    rendezés; körkörös hivatkozásnál a maradékot az eredeti sorrendben fűzi hozzá
    (a constraints-szűrő úgyis elkapja az esetleges érvénytelent)."""
    deps = {}
    for k, s in specs.items():
        deps[k] = {r for r in (s.get("gt"), s.get("lt")) if r in specs}
    order, placed, remaining = [], set(), dict(deps)
    while remaining:
        ready = [k for k, refs in remaining.items() if refs <= placed]
        if not ready:                       # körkörös dep → ne akadjunk el
            order.extend(remaining.keys())
            break
        for k in ready:
            order.append(k); placed.add(k); del remaining[k]
    return order


def _param_split(strategy, opt_cfg: dict) -> tuple[list, list]:
    """A HANGOLT kulcsok kettéosztva: (jel, végrehajtás).

    A besorolás a `strategy/config/<név>.json` `param_meta`-jából jön. Ismeretlen
    kulcs → jel (a drága, biztonságos ág): egy be nem sorolt paraméter inkább
    lassítson, mint hogy a jelölt-lista gyorsítótára tévesen újrahasznosuljon.
    """
    from strategy.settings import load_strategy_config, param_class, EXEC_PARAM
    try:
        scfg = load_strategy_config(strategy.name)
    except Exception:
        scfg = {}
    specs = [k for k, v in opt_cfg.items() if isinstance(v, dict) and "min" in v]
    sig = [k for k in specs if param_class(scfg, k) != EXEC_PARAM]
    exe = [k for k in specs if param_class(scfg, k) == EXEC_PARAM]
    return sig, exe


def ter_ujjlenyomat(opt_cfg: dict, extra: dict = None) -> str:
    """A KERESÉSI TÉR stabil ujjlenyomata.

    Mindent tartalmaz, ami egy trial JELENTÉSÉT megváltoztatja: a paraméter-
    tartományokat (`min`/`max`/`step` + a `gt`/`lt` függések), és a hívó által
    adott extrát (rr-keresés, beágyazott mód). ⚠ A kulcsok RENDEZVE mennek bele,
    különben ugyanaz a tér két különböző ujjlenyomatot adna attól függően,
    milyen sorrendben olvastuk be a configot."""
    import hashlib
    import json as _json
    specs = {}
    for k, v in (opt_cfg or {}).items():
        if isinstance(v, dict) and "min" in v:
            specs[k] = {m: v.get(m) for m in ("min", "max", "step", "gt", "lt")}
    nyers = _json.dumps({"specs": specs, "extra": extra or {}},
                        sort_keys=True, default=str)
    return hashlib.sha1(nyers.encode("utf-8")).hexdigest()[:16]


def _suggest_params(trial, opt_cfg: dict, base_params: dict,
                    keys: "list | None" = None) -> dict:
    """Optuna trial → paraméter dict.

    `keys` (opcionális): csak ezeket a kulcsokat suggeszti (a beágyazott
    kereséshez — a külső hurok a jel-, a belső a végrehajtási dimenziókat).
    None → mind, mint eddig.

    A `gt`/`lt` metaadattal ellátott range-eket DINAMIKUSAN szűkíti a MÁR
    suggeszált paraméterek alapján → érvénytelen kombináció ELŐ SEM ÁLL (nincs
    elpazarolt trial): `gt: X` → szigorúan X fölött (X+step), `lt: Y` → szigorúan
    Y alatt (Y−step). A range-eket a `_dep_order` szerint suggeszti (a hivatkozott
    paraméterek előbb)."""
    params = deepcopy(base_params)
    specs = {k: v for k, v in opt_cfg.items()
             if isinstance(v, dict) and "min" in v}
    if keys is not None:
        specs = {k: v for k, v in specs.items() if k in keys}
    for key in _dep_order(specs):
        spec = specs[key]
        lo, hi, step = spec["min"], spec["max"], spec["step"]
        gt, lt = spec.get("gt"), spec.get("lt")
        if gt is not None and gt in params:
            lo = max(lo, params[gt] + step)          # szigorúan nagyobb
        if lt is not None and lt in params:
            hi = min(hi, params[lt] - step)          # szigorúan kisebb
        if lo > hi:
            # A már suggeszált határok túl közel → nincs érvényes érték; essünk
            # vissza a teljes tartományra (ritka; a constraints-szűrő elkapja).
            lo, hi = spec["min"], spec["max"]
        if isinstance(spec["min"], int) and isinstance(spec["max"], int) and isinstance(step, int):
            step_i = max(1, int(step))
            hi = int(lo) + ((int(hi) - int(lo)) // step_i) * step_i   # rácsra igazít
            params[key] = trial.suggest_int(key, int(lo), int(hi), step=step_i)
        else:
            # A FELSŐ határt is a rácsra igazítjuk — mint az int-ágon. Enélkül az
            # optuna minden trialen `UserWarning`-ot ír („the range is not
            # divisible by step"), és 500 trial × 4 ablak után a napló olvashatatlan.
            # Az ÉRTÉK nem változik: az optuna is pontosan ezt tenné, csak hangosan.
            # A tartomány-hibát INDULÁSKOR jelezzük, EGYSZER (`_warn_step_grid`).
            params[key] = trial.suggest_float(key, float(lo), _grid_max(lo, hi, step),
                                              step=float(step))
    return params


def _grid_max(lo, hi, step) -> float:
    """A `hi` lefelé igazítva a `lo`-tól induló `step`-rácsra (float-biztosan).

    A lebegőpontos maradék miatt kerekítünk: `(3.0-0.5)/0.2` = 12,4999… lenne,
    amiből a `floor` 12-t ad — az helyes; de `(1.0-0.0)/0.1` = 9,999… → 9 lenne,
    ami HIBÁS (10 kell). A 9 tizedesre kerekítés mindkettőt eltalálja."""
    lo, hi, step = float(lo), float(hi), float(step)
    if step <= 0 or hi <= lo:
        return hi
    n = int(round((hi - lo) / step, 9))
    return round(lo + n * step, 10)


def _warn_step_grid(symbol: str, specs: dict) -> None:
    """INDULÁSKOR EGYSZER jelzi, ha egy tartomány nem osztható a lépésközzel.

    Ez nem kódhiba, hanem CONFIG-hiba: a felső határ elérhetetlen. Pl.
    `tp_rr_ratio` [0,5 … 3,0] 0,2-es lépéssel → a rács 0,5; 0,7; …; 2,9, tehát a
    **3,0 sosem áll elő**. A trialonkénti optuna-figyelmeztetés helyett itt egy
    sor van, ami meg is mondja, mit érdemes átírni."""
    for key, spec in sorted(specs.items()):
        lo, hi, step = spec.get("min"), spec.get("max"), spec.get("step")
        if not isinstance(step, (int, float)) or step <= 0:
            continue
        if isinstance(lo, int) and isinstance(hi, int) and isinstance(step, int):
            continue
        eff = _grid_max(lo, hi, step)
        if abs(float(hi) - eff) > 1e-9:
            log.warning("  %s — a(z) `%s` tartománya [%g … %g] NEM osztható a "
                        "%g lépésközzel → a tényleges felső határ %g (a %g nem áll "
                        "elő). Állítsd a min/max/step valamelyikét, ha a %g kell.",
                        symbol, key, lo, hi, step, eff, hi, hi)


def _opt_allowed_hours(symbol: str, strategy, pair_cfg: dict):
    """A KERESKEDÉSI ÓRÁK az optimalizáláshoz — a live-val EGYEZŐ feloldással.

    ⚠ EZ EDDIG HIÁNYZOTT. Az optimalizáló mind a 24 órán hangolt, az él viszont
    csak a `trade_hours` órákban köt — a kapott paraméterek tehát részben olyan
    órákra optimalizáltak, amikben a motor SOHA nem lép be. Ugyanaz a hiba-osztály,
    mint a v1.95.0-ban javított kapu-eltérés, csak az órákra.

    Ma minden párnál mind a 24 óra engedve van, tehát a javítás EGYETLEN mentett
    paramétert sem érint — de az első szűkítéskor némán szétcsúszott volna.

    `None` → nincs korlát (a `run_pair` ilyenkor minden órát enged)."""
    # ⚠ A KONVERZIO IS A VEDELEM ALATT: egy elgepelt `trade_hours` (pl. szoveg)
    # kulonben `ValueError`-t dobna az optimalizalas KOZEPEN, egy orak ota futo
    # munkat elvive. Hibas bemenetnel inkabb NE szurjunk — az a korabbi, ismert
    # viselkedes; a csendes elszallas nem az.
    try:
        from core.params_store import resolve_trade_hours
        th = resolve_trade_hours(symbol, getattr(strategy, "name", None),
                                 (pair_cfg or {}).get("trade_hours"))
        if th is None:
            return None
        hours = {int(h) for h in th}
    except Exception:
        log.warning("%s — ertelmezhetetlen trade_hours, az optimalizalas MINDEN "
                    "oran fut (mint eddig)", symbol)
        return None
    return None if len(hours) >= 24 else hours


def optimize_pair_optuna(
    symbol: str,
    df_m15: pd.DataFrame,
    df_m1: pd.DataFrame,
    opt_cfg: dict,
    base_params: dict,
    pair_cfg: dict,
    trading_cfg: dict,
    initial_balance: float,
    strategy,
    n_trials: int = 500,
    n_splits: int = 4,
    train_months: int = 6,
    test_months: int = 2,
    progress_callback=None,
    cfg: "dict | None" = None,
    exec_gates: bool = False,
    nested: "bool | None" = None,
) -> Optional[dict]:
    """
    Optuna Bayesian optimalizálás walk-forward validációval.
    A legjobb paramétereket az összes walk-forward ablak átlagos score-ja alapján választja.

    `exec_gates`: a trialok az ÉL végrehajtási kapuival (spread + TF-együttállás)
    fussanak-e — lásd `run_optimizer_for_symbol`. A TF-kapu kiértékelőjét
    ablakonként EGYSZER építjük meg (nem trialonként): nem függ a paraméterektől,
    viszont resample-t igényel.
    """
    from trading.backtest import (run_pair, _build_tf_align_evaluator,
                                  build_signal_series)

    # Opt-in: az rr (kockázatcsökkentés) is optimalizált dimenzió? Alapból NEM →
    # a keresési tér és a viselkedés bitazonos a korábbival.
    optimize_rr = bool(opt_cfg.get("optimize_rr", False))

    # ── „Csak EZEKET a paramétereket hangold" ───────────────────────────────
    # A felhasználó a paraméter-ablak Optimalizálás lapján kikapcsolhat
    # dimenziókat (pl. „most csak az SMA-t"). A kihagyott kulcs tartománya
    # kikerül a keresési térből → a `base_params` értékén marad, tehát az
    # optuna nem is sorsolja. Pár+stratégia szintű (`core.opt_plan`).
    #
    # ⚠ ITT kell kivenni, a legelején: ha csak a suggeszt-ágon szűrnénk, a
    # `_warn_step_grid`, a `_param_split` és a kényszer-ellenőrzés még a teljes
    # téren dolgozna — a napló és a felület mást mondana, mint a valóság.
    from core import opt_plan as _oplan
    _skip = _oplan.skip_keys(cfg or {}, symbol, strategy.name)
    if _skip:
        _dropped = [k for k in _skip if k in opt_cfg]
        if _dropped:
            opt_cfg = {k: v for k, v in opt_cfg.items() if k not in _skip}
            log.info("  %s/%s — %d paraméter KIHAGYVA a keresésből (az alapértékén "
                     "marad): %s", symbol, strategy.name, len(_dropped),
                     ", ".join(sorted(_dropped)))

    # ── Beágyazott keresés (opt-in) ─────────────────────────────────────────
    # Alapból KI → a lapos keresés viselkedése BITAZONOS a korábbival. A
    # `nested` argumentum (ha adott) erősebb a confignál — az A/B mérőnek kell.
    if nested is None:
        nested = bool(opt_cfg.get("nested", False))
    n_inner = int(opt_cfg.get("inner_trials", 8) or 8)
    _sig_keys, _exe_keys = _param_split(strategy, opt_cfg)
    if nested and not _exe_keys:
        # Nincs mit söpörni belül → a beágyazás csak felesleges réteg lenne.
        log.warning("  %s/%s — a beágyazott keresés KIMARAD: ennek a stratégiának "
                    "nincs hangolt VÉGREHAJTÁSI paramétere (a param_meta szerint). "
                    "Lapos keresés fut.", symbol, strategy.name)
        nested = False
    if nested:
        log.info("  %s — BEÁGYAZOTT keresés: %d jel-dimenzió kívül, %d "
                 "végrehajtási belül (%d belső trial/külső)",
                 symbol, len(_sig_keys), len(_exe_keys), n_inner)

    # Deklaratív paraméter-kényszerek indításkori ellenőrzése: az elgépelt vagy
    # ismeretlen nevű kifejezéseket LOGBA jelezzük (a check() futásidőben kihagyja).
    _cons = opt_cfg.get("constraints", [])
    if _cons:
        from core import param_constraints
        _known = set(base_params) | {k for k, v in opt_cfg.items()
                                     if isinstance(v, dict) and "min" in v}
        for _expr, _why in param_constraints.validate(_cons, _known):
            log.warning("%s — hibás paraméter-kényszer (kihagyva) %r: %s",
                        symbol, _expr, _why)

    # Rács-ellenőrzés: elérhetetlen felső határ (nem osztható lépésköz) — EGYSZER,
    # itt, ahelyett hogy az optuna trialonként figyelmeztetne (lásd `_warn_step_grid`).
    _warn_step_grid(symbol, {k: v for k, v in opt_cfg.items()
                             if isinstance(v, dict) and "min" in v})

    windows = _walk_forward_windows(df_m15, n_splits, train_months, test_months)
    if not windows:
        log.warning("%s — nincs elég adat walk-forward ablakokhoz.", symbol)
        return None

    log.info("  Walk-forward: %d ablak (%d hó train + %d hó test)", len(windows), train_months, test_months)
    for i, w in enumerate(windows):
        log.info("    Ablak %d: %s → TRAIN → %s → TEST → %s",
                 i + 1,
                 str(w["train_start"])[:10],
                 str(w["test_start"])[:10],
                 str(w["test_end"])[:10])

    # ── Ablakonkénti előkészítés (a trial-cikluson KÍVÜL) ────────────────────
    # Az adat-szeletelés és a TF-kapu kiértékelője paraméter-FÜGGETLEN, tehát
    # ablakonként egyszer elég. Trialonként újraszámolva 500 trial × 4 ablak =
    # 2000 resample lenne — az optimalizálás nagyságrendekkel lassulna, és a
    # kapu-paritás ára indokolatlanul magas volna.
    prepared = []
    for w in windows:
        m15_w = df_m15[df_m15.index >= w["train_start"]]
        m1_w  = df_m1[df_m1.index  >= w["train_start"]]
        tf_eval = (_build_tf_align_evaluator(cfg, symbol, strategy.name, m1_w)
                   if (exec_gates and cfg is not None) else None)
        prepared.append((w, m15_w, m1_w, tf_eval))

    call_count = [0]
    best_score_so_far = [-float("inf")]

    # ── Ismétlődés-szűrő ────────────────────────────────────────────────────
    # ⚠ A TPE-mintavevő szűk, diszkrét térben ÚJRA ÉS ÚJRA ugyanazt a kombinációt
    # húzza, a study adatbázisa pedig perzisztens — folytatáskor a korábbi futás
    # készletei is visszajöhetnek. Kiszámolni MÉGEGYSZER értelmetlen: a backtest
    # determinisztikus, ugyanaz a bemenet ugyanazt adja.
    #
    # A gyorsítótár a KIÉRTÉKELÉST spórolja meg (ez a drága), a CSV-sor
    # elhagyása pedig a listát tartja olvashatóan.
    _mar_ertekelt: dict = {}     # ujjlenyomat -> score
    _duplikatum = [0]

    def _param_oszlopok(params, rr=None) -> dict:
        """A trial-sor PARAMÉTER-oszlopai. ⚠ KÖZÖS építő: az ujjlenyomatot a
        kiértékelés ELŐTT és a sor mentésekor is ez adja, tehát a kettő nem
        csúszhat el. (Két külön másolat előbb-utóbb eltérne, és a szűrő némán
        elkezdene átengedni duplikátumokat.)"""
        ki = {pk: pv for pk, pv in params.items() if not pk.startswith("_")}
        if optimize_rr and rr:
            # A FELTÉTELES tér miatt egy dimenzió hiányozhat a specből (nem is
            # sorsoltuk, mert ezen a preseten nem hat). Ilyenkor ÜRES cella megy
            # a CSV-be — nem 0 és nem alapérték: az azt sugallná, hogy „ezt
            # mértük".
            ki["rr_preset"] = rr.get("preset", "off")
            ki["rr_runner"] = rr.get("runner_stop", "")
            for _k in ("trigger_R", "halving_fraction", "shield_fraction",
                       "fibo_stop_level", "thirds_base_R",
                       "breakeven_pct", "trail_activation_atr",
                       "trail_distance_atr"):
                ki[f"rr_{_k}"] = rr.get(_k, "")
        return ki

    def _ujjlenyomat(params, rr=None) -> tuple:
        """A készlet azonossága — a kiértékelés ELŐTT."""
        return _param_kulcs(_param_oszlopok(params, rr))

    def _record_trial(trial, params, score, summary=None, note="", rr=None):
        """Egy trial sora a CSV-hez — MINDEN trialról (érvénytelen/0-trade is),
        hogy az eredménytáblázat mindig létrejöjjön és lássék, mi történt.
        A sort a TRIAL user_attr-jébe tesszük (a study-val perzisztálódik → a CSV
        a study-ból bármikor újraépíthető, folytatás után is).
        note: elbukás oka (pl. hiányzó config-kulcs), hogy a CSV-ből kiderüljön.
        rr: az adott trial rr-spec-je (ha optimize_rr) → külön oszlopokban."""
        row = {"score": round(score, 2) if score > -999999.0 else score}
        if summary:
            pf = summary["profit_factor"]
            row.update({
                "trades":        summary["trades"],
                "win_rate":      round(summary["win_rate"], 4),
                "total_pnl":     round(summary["total_pnl"], 2),
                "max_drawdown":  round(summary["max_drawdown"], 4),
                "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
            })
        else:
            row["trades"] = 0
        row["note"] = note
        row.update(_param_oszlopok(params, rr))
        sig = _param_kulcs(row)
        trial.set_user_attr("row", row)
        # ⚠ AZ UJJLENYOMAT IS a trialra kerül, nem csak a sor. A study-ból
        # folytatáskor EBBŐL tudjuk, mit számoltunk már ki — a `row`-ból
        # visszafejteni törékeny volna (mérés- és paraméter-oszlopok keverednek).
        trial.set_user_attr("sig", list(sig))
        _mar_ertekelt[sig] = score

    def _progress_tick():
        # ── Haladás MINDEN trialnál, a korai return ELŐTT ──────────────────
        # (Különben a sok érvénytelen trial esetén — pl. BTCUSD — a GUI
        #  stall-timeoutot dob, a CLI nem mutat haladást, és CSV sem készül.)
        call_count[0] += 1
        # Haladás MINDEN trialnál → a GUI stall-órája minden trial után újraindul,
        # így a stall-ablaknak elég EGY trialt lefednie (nem 10-et). A napló
        # viszont csak 10-esével ír, hogy ne árassza el.
        if progress_callback:
            progress_callback(call_count[0], n_trials, best_score_so_far[0])
        if call_count[0] == 1 or call_count[0] % 10 == 0:
            log.info("  %s — %d/%d trial | legjobb score: %.2f",
                     symbol, call_count[0], n_trials, best_score_so_far[0])

    _hours = _opt_allowed_hours(symbol, strategy, pair_cfg)

    def _evaluate(params, rr_run, series_by_window=None):
        """Egy paraméter-készlet pontszáma az ÖSSZES walk-forward ablakon.

        A lapos és a beágyazott keresés UGYANEZT hívja — így a két mód nem
        mérhet mást ugyanarra a paraméter-készletre. `series_by_window`: előre
        megépített jelölt-listák (a beágyazott ág belső hurka adja); None → a
        run_pair maga számol, mint eddig.
        Visszaad: (score, summary|None, hiba-szöveg).
        """
        window_scores = []
        combined_test = []          # az összes ablak TEST-trade-jei (CSV metrikákhoz)
        last_err = ""               # utolsó kivétel szövege (diagnosztika a CSV-be)
        for _wi, (w, m15_w, m1_w, tf_eval) in enumerate(prepared):
            try:
                # Teljes ablak adat (train + test) — az indikátorok warmuphoz kellenek
                result = run_pair(
                    symbol, m15_w, m1_w,
                    params, pair_cfg, trading_cfg,
                    initial_balance,
                    test_start=None,  # teljes ablakot futtatjuk
                    strategy=strategy,
                    rr=rr_run,
                    cfg=cfg, exec_gates=exec_gates, tf_eval=tf_eval,
                    allowed_hours=_hours,
                    signal_series=(series_by_window[_wi] if series_by_window else None),
                )

                # Csak a TEST periódus trade-jeit értékeljük
                test_trades = [
                    t for t in result.closed
                    if t.close_time is not None and t.close_time >= w["test_start"]
                ]
                combined_test.extend(test_trades)
                window_scores.append(
                    _score_trades(test_trades, initial_balance,
                                  min_trades=min_trades_floors(cfg)[0]))

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                window_scores.append(-999999.0)

        valid = [s for s in window_scores if s > -999999.0]
        if not valid:
            return -999999.0, None, (last_err or
                                     "nincs értékelhető trade a TEST ablakokban")

        # Átlag × konzisztencia arány (hány ablak működött)
        avg_score   = float(np.mean(valid))
        consistency = len(valid) / len(window_scores)
        final_score = avg_score * consistency

        pnl_list = [t.pnl_usd for t in combined_test]
        summary = None
        if pnl_list:
            wins   = [p for p in pnl_list if p > 0]
            losses = [p for p in pnl_list if p <= 0]
            bal = peak = initial_balance
            mdd = 0.0
            for p in pnl_list:
                bal += p
                peak = max(peak, bal)
                mdd  = max(mdd, (peak - bal) / peak if peak > 0 else 0)
            pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
            summary = {
                "trades":        len(pnl_list),
                "win_rate":      len(wins) / len(pnl_list),
                "total_pnl":     sum(pnl_list),
                "max_drawdown":  mdd,
                "profit_factor": pf,
            }
        return final_score, summary, ""

    # ── LAPOS keresés (az eddigi) — minden dimenzió EGYÜTT ──────────────────
    def _objective_flat(trial):
        params = _suggest_params(trial, opt_cfg, base_params)
        # rr (kockázatcsökkentés) dimenziók — csak ha opt-in (különben None → OFF).
        rr_spec = _suggest_rr(trial, opt_cfg) if optimize_rr else None

        # ⚠ MÁR KISZÁMOLTUK EZT A KÉSZLETET → nem futtatjuk újra. A backtest
        # determinisztikus; ugyanaz a bemenet ugyanazt adja. A gyorsítótár a
        # DRÁGA részt (kiértékelés) spórolja meg, és mivel nem hívunk
        # `_record_trial`-t, a kísérlet-listába sem kerül ismétlődő sor.
        #
        # A haladás-tick is kimarad: ez az ág ~azonnal lefut, tehát nincs mit
        # jelenteni, és a GUI stall-órája sem eshet ki miatta.
        _sig = _ujjlenyomat(params, rr_spec)
        if _sig in _mar_ertekelt:
            _duplikatum[0] += 1
            return _mar_ertekelt[_sig]

        _progress_tick()
        if not strategy.constraints_ok(params):
            _record_trial(trial, params, -999999.0,
                          note="paraméter-kényszer nem teljesült", rr=rr_spec)
            return -999999.0
        score, summary, err = _evaluate(params, _rr_for_run(rr_spec))
        if summary is None and score <= -999999.0:
            _record_trial(trial, params, score, rr=rr_spec, note=err)
            return score
        _record_trial(trial, params, score, summary, rr=rr_spec)
        if score > best_score_so_far[0]:
            best_score_so_far[0] = score
        return score

    # ── BEÁGYAZOTT keresés — kívül a JEL, belül a VÉGREHAJTÁS ───────────────
    # Miért működik: a jel-paraméterek megváltoztatják a jelölt-listát (drága
    # újraszámolás), a végrehajtásiak nem (lásd `strategy.settings.param_class`).
    # A külső trial tehát ablakonként EGYSZER építi a jelölt-listát, és a belső
    # hurok azon söpri végig a végrehajtási teret — a `run_pair` a munka nagy
    # részét újrahasználja (mérve 1,7–2,0×).
    #
    # ⚠ EZ NEM UGYANAZ A KERESÉS, csak gyorsabban: a költségvetés máshogy oszlik.
    # Azonos időből több KIÉRTÉKELÉS lesz, de KEVESEBB jel-beállításra. Hogy ez
    # nyereség-e, az a tájképtől függ — ezért alapból KI van kapcsolva, és A/B-vel
    # kell igazolni (`tools/nested_ab.py`).
    def _objective_nested(trial):
        sig_params = _suggest_params(trial, opt_cfg, base_params, keys=_sig_keys)

        # ⚠ A KÜLSŐ trial csak a JEL-paramétereket sorsolja — az azonosság alapja
        # tehát ez, nem a teljes készlet. Ugyanaz a jel-készlet ugyanazt a belső
        # söprést adná, ami itt a MUNKA JAVA (ablakonként újraépített jelölt-
        # lista). Ez a szűrő tehát nem sorokat spórol, hanem PERCEKET.
        _sig = _ujjlenyomat(sig_params)
        if _sig in _mar_ertekelt:
            _duplikatum[0] += 1
            return _mar_ertekelt[_sig]

        _progress_tick()
        if not strategy.constraints_ok(sig_params):
            # A kényszerek MIND jel-paraméterekre hivatkoznak (ellenőrizve
            # wpr_sma-n és bollingeren), tehát itt eldönthető — nem pazarolunk rá
            # egy teljes belső hurkot.
            _record_trial(trial, sig_params, -999999.0,
                          note="paraméter-kényszer nem teljesült")
            return -999999.0

        # A jelölt-lista ablakonként EGYSZER. Ha bármelyik ablak elhasal, a
        # trial elbukik — de a hibát megnevezzük (nem néma -999999).
        try:
            series = [build_signal_series(symbol, m15_w, m1_w, sig_params,
                                          pair_cfg, strategy=strategy)
                      for _w, m15_w, m1_w, _tf in prepared]
        except Exception as e:
            _record_trial(trial, sig_params, -999999.0,
                          note=f"jelölt-lista építés: {type(e).__name__}: {e}")
            return -999999.0

        n_sig = sum(len(s.signals) for s in series)
        if n_sig == 0:
            # Nincs egyetlen jelölt sem → a végrehajtási tér söprése értelmetlen
            # (mind a 0 kötést adná). Ez GYAKORI a rossz jel-beállításoknál, és
            # a belső hurok átugrásával sok időt spórolunk.
            _record_trial(trial, sig_params, -999999.0,
                          note="a jel-beállítás egyetlen jelöltet sem ad")
            return -999999.0

        best = {"score": -999999.0, "params": None, "summary": None, "rr": None}

        def _inner(itrial):
            p = _suggest_params(itrial, opt_cfg, sig_params, keys=_exe_keys)
            rr_spec = _suggest_rr(itrial, opt_cfg) if optimize_rr else None
            s, summ, _err = _evaluate(p, _rr_for_run(rr_spec), series)
            if s > best["score"]:
                best.update(score=s, params=p, summary=summ, rr=rr_spec)
            # ⚠ A leállítás-kérést ITT is figyelni kell, nem csak a külső
            # trial-határon: egy külső trial `n_inner` teljes kiértékelés, ami
            # percekig tart. Enélkül a STOP gomb annyit „gondolkodna", és a
            # felhasználó joggal hinné, hogy lefagyott.
            if stop_marker(symbol, strategy.name).exists():
                itrial.study.stop()
            return s

        inner = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=1000 + trial.number))
        inner.optimize(_inner, n_trials=n_inner, show_progress_bar=False)

        # A nyertes TELJES paraméter-készletet a trialhoz kötjük: a végén ebből
        # olvassuk ki a legjobbat (a külső trial maga csak a jel-dimenziókat
        # ismeri, a végrehajtásiakat a belső study „tudja").
        _bp = best["params"] or sig_params
        trial.set_user_attr("nested_params", {k: _bp.get(k) for k in _exe_keys})
        if best["rr"]:
            trial.set_user_attr("nested_rr", best["rr"])
        trial.set_user_attr("nested_signals", n_sig)
        _record_trial(trial, _bp, best["score"], best["summary"], rr=best["rr"],
                      note=("" if best["summary"] else
                            "a végrehajtási söprés egyetlen értékelhető trade-et sem adott"))
        # ⚠ A `_record_trial` a TELJES nyertes készlettel jegyzett fel; a külső
        # trial viszont a JEL-készletén azonosítódik. E nélkül a szűrő sosem
        # találna egyezést a beágyazott módban.
        _mar_ertekelt[_sig] = best["score"]
        if best["score"] > best_score_so_far[0]:
            best_score_so_far[0] = best["score"]
        return best["score"]

    objective = _objective_nested if nested else _objective_flat

    out_csv     = trials_file(symbol, strategy.name)
    storage_url = f"sqlite:///{study_db(symbol, strategy.name).as_posix()}"

    def _dump_csv(study, _trial=None):
        """A trials CSV újraépítése a study-ból (a trialok user_attr sorai).
        Folytatás után a RÉGI trialok is benne vannak (a .db perzisztálja őket)."""
        rows = [t.user_attrs["row"] for t in study.trials if "row" in t.user_attrs]
        try:
            _write_trials_csv(rows, out_csv)
        except Exception as e:
            log.debug("%s — trials CSV mentés hiba: %s", symbol, e)

    def _incremental_cb(study, trial):
        # Inkrementális CSV-mentés minden 10. trial után. A study MINDEN trialt
        # azonnal a .db-be ír → megszakadáskor sem vész el eredmény, a CSV pedig
        # bármikor újraépíthető belőle.
        if (trial.number + 1) % 10 == 0:
            _dump_csv(study)
        # Leállítás-kérés (GUI STOP gomb → stop-marker): trial-határon állunk le.
        # A kezelést (státusz, takarítás) az optimize_symbol közös útja végzi.
        if stop_marker(symbol, strategy.name).exists():
            study.stop()

    # Folytatás-szemantika:
    #   • előző futás BEFEJEZŐDÖTT (marker fájl van) → FRISS optimalizálás
    #     (a régi .db-t töröljük — még a kapcsolat megnyitása ELŐTT, friss
    #     processzben, így nincs Windows-fájlzár),
    #   • előző futás MEGSZAKADT (nincs marker, de van .db) → FOLYTATÁS.
    done_flag = done_marker(symbol, strategy.name)
    if done_flag.exists():
        try:
            study_db(symbol, strategy.name).unlink(missing_ok=True)
            done_flag.unlink(missing_ok=True)
        except Exception as e:
            log.debug("%s — study reset hiba: %s", symbol, e)

    # ── A KERESÉSI TÉR VÁLTOZOTT-E? ──────────────────────────────────────
    # ⚠ Ha igen, a folytatás HAMIS eredményt adna: a régi trialok a régi
    # tartományból származnak, és a „legjobb" közülük is kikerülhet. Ilyenkor
    # ÚJAT kezdünk — de a régi `.db`-t nem dobjuk el, csak félretesszük.
    _fp = ter_ujjlenyomat(opt_cfg, {
        # ⚠ A KOCKÁZATCSÖKKENTÉS-KERESÉS és a BEÁGYAZOTT mód is a TÉR része:
        # bekapcsolva más dimenziók kerülnek a trialba, tehát a régi trialok nem
        # összemérhetők az újakkal.
        "rr": bool(optimize_rr), "rr_presets": sorted(
            opt_cfg.get("rr_presets") or _RR_PRESETS),
        "nested": bool(nested), "exec_gates": bool(exec_gates),
        "strategy": strategy.name,
    })
    _fp_fajl = space_marker(symbol, strategy.name)
    _db = study_db(symbol, strategy.name)
    if _db.exists():
        try:
            _regi = _fp_fajl.read_text(encoding="utf-8").strip() if _fp_fajl.exists() else ""
        except OSError:
            _regi = ""
        if _regi != _fp:
            _uj_nev = _db.with_suffix(
                f".db.regi-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                _db.rename(_uj_nev)
                log.warning(
                    "%s/%s — a KERESÉSI TÉR megváltozott az előző futás óta "
                    "(%s → %s). Új optimalizálás indul; a félbehagyott study "
                    "félretéve: %s.  ⇒ Enélkül a régi tartományból származó "
                    "trialok is versenyeznének, és a „legjobb” közülük is "
                    "kikerülhetne — vagyis a beállított tartomány NEM "
                    "érvényesülne.",
                    symbol, strategy.name, _regi or "ismeretlen", _fp,
                    _uj_nev.name)
            except OSError as e:
                # ⚠ NEM HALLGATUNK: ha nem tudjuk félretenni, inkább mondjuk
                # meg, mint hogy csendben rossz tartománnyal folytassunk.
                log.error("%s — a régi study nem tehető félre (%s); a folytatás "
                          "RÉGI tartományú trialokat is tartalmazhat!", symbol, e)
    try:
        _fp_fajl.parent.mkdir(parents=True, exist_ok=True)
        _fp_fajl.write_text(_fp, encoding="utf-8")
    except OSError as e:
        log.debug("%s — a tér-ujjlenyomat nem menthető: %s", symbol, e)

    # Perzisztens study (SQLite) → megszakadás után FOLYTATHATÓ ugyanarra a párra.
    study = optuna.create_study(
        study_name=symbol,
        storage=storage_url,
        load_if_exists=True,
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    done = len(study.trials)
    call_count[0] = done            # a haladás a TELJES készültséget mutassa
    if done:
        try:
            best_score_so_far[0] = study.best_value
        except Exception as ex:
            # Egyetlen trial sem ért el értékelhető eredményt (pl. mind a
            # kötés-korlát alatt maradt) — ez ÉRVÉNYES állapot, csak tudni kell
            # róla: a haladás-kijelző ilyenkor nem tud „eddigi legjobbat" mutatni.
            log.debug("  %s — még nincs értékelhető trial a study-ban (%s)",
                      symbol, ex)
    # ⚠ A GYORSÍTÓTÁR FELTÖLTÉSE A STUDY-BÓL. Folytatáskor a KORÁBBI futás
    # készleteit is ismernünk kell, különben mindet újraszámolnánk — és pont a
    # folytatás az az eset, ahol a TPE a legszívesebben húzza elő ugyanazokat.
    for _t in study.trials:
        _s = _t.user_attrs.get("sig")
        if _s and _t.value is not None:
            try:
                _mar_ertekelt[tuple((_p[0], _p[1]) for _p in _s)] = _t.value
            except Exception:
                # Régi study, `sig` nélkül vagy más alakban — nem baj, csak
                # annyit veszítünk, hogy azt a készletet újraszámoljuk.
                pass
    if _mar_ertekelt:
        log.info("  %s — %d korábbi paraméter-készlet ismert (nem számoljuk újra)",
                 symbol, len(_mar_ertekelt))

    remaining = max(0, n_trials - done)
    if remaining > 0:
        if done:
            log.info("  %s — FOLYTATÁS: %d kész trial a study-ban, még %d hátra",
                     symbol, done, remaining)
        study.optimize(objective, n_trials=remaining, show_progress_bar=False,
                       callbacks=[_incremental_cb])
    if _duplikatum[0]:
        # ⚠ NEM néma. Ez a szám mondja meg, mennyire merítette ki a keresés a
        # teret: ha a trialok nagy része ismétlődés, a tartományok szűkek (vagy
        # a lépésköz durva), és a további trial-szám emelése már nem hoz újat.
        log.info("  %s — %d trial ISMÉTLŐDŐ készletet húzott (nem futott le "
                 "újra, és nem került a kísérlet-listába)", symbol, _duplikatum[0])
    else:
        log.info("  %s — a study már kész (%d trial). Új futáshoz töröld a .db-t: %s",
                 symbol, done, study_db(symbol, strategy.name).name)

    # Végső, teljes CSV a study-ból (a folytatott trialokkal együtt).
    _dump_csv(study)
    log.info("  %s — %d trial eredménye mentve: %s", symbol, len(study.trials), out_csv.name)

    # Ha elértük a teljes trial-számot → BEFEJEZETT: marker, hogy a KÖVETKEZŐ OPT
    # frissen induljon (ne folytassa a már kész study-t).
    if len(study.trials) >= n_trials:
        try:
            done_flag.touch()
        except Exception as ex:
            # ⚠ A marker HIÁNYA nem kozmetika: a study „befejezetlen" marad, és a
            # program MINDEN indításkor automatikusan újraindítja
            # (`unfinished_studies` → auto-folytatás) — egy már kész, 500 trialos
            # futást. Némán ez egy örökké visszatérő, órákig futó munka.
            log.warning("  %s — a befejezés-marker nem jött létre (%s): a study "
                        "BEFEJEZETLENNEK látszik, és a következő indításkor "
                        "AUTOMATIKUSAN újraindul.", symbol, ex)

    if progress_callback:
        progress_callback(n_trials, n_trials, study.best_value)

    if study.best_value <= -999999.0:
        return None

    if nested:
        # A külső trial csak a JEL-dimenziókat suggesztálta; a végrehajtásiakat a
        # belső study nyerte meg, és a trial user_attr-jébe került. (A study-ban
        # eltárolva → folytatás után is visszaolvasható.)
        best_params = _suggest_params(study.best_trial, opt_cfg, base_params,
                                      keys=_sig_keys)
        best_params.update({k: v for k, v in
                            (study.best_trial.user_attrs.get("nested_params") or {}).items()
                            if v is not None})
        best_rr = study.best_trial.user_attrs.get("nested_rr") if optimize_rr else None
    else:
        best_params = _suggest_params(study.best_trial, opt_cfg, base_params)
        # A nyertes trial rr-je (ugyanabból a trialból visszafejtve) — a train/TEST
        # validáció is EZZEL fut, hogy a mentett minősítés konzisztens legyen.
        best_rr = _suggest_rr(study.best_trial, opt_cfg) if optimize_rr else None
    best_rr_run = _rr_for_run(best_rr)

    # TRAIN summary a teljes train perióduson (utolsó ablak train_start → test_start)
    last_window = windows[-1]
    try:
        from trading.backtest import run_pair as _rp
        m15_tr = df_m15[df_m15.index >= windows[0]["train_start"]]
        m1_tr  = df_m1[df_m1.index  >= windows[0]["train_start"]]
        train_result = _rp(symbol, m15_tr, m1_tr, best_params, pair_cfg, trading_cfg,
                           initial_balance, strategy=strategy, rr=best_rr_run,
                           allowed_hours=_hours)
        train_trades = [
            t for t in train_result.closed
            if t.close_time is not None and t.close_time < last_window["test_start"]
        ]
        pnl_list  = [t.pnl_usd for t in train_trades]
        wins      = [p for p in pnl_list if p > 0]
        losses    = [p for p in pnl_list if p <= 0]
        balance   = initial_balance
        peak      = balance
        max_dd    = 0.0
        for p in pnl_list:
            balance += p
            peak = max(peak, balance)
            dd   = (peak - balance) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        train_summary = {
            "symbol":        symbol,
            "trades":        len(train_trades),
            "win_rate":      len(wins) / len(train_trades) if train_trades else 0,
            "total_pnl":     sum(pnl_list),
            "max_drawdown":  max_dd,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf"),
            "wf_score":      study.best_value,
            "wf_windows":    len(windows),
        }
    except Exception as e:
        log.warning("  %s — train summary hiba: %s", symbol, e)
        train_summary = {"symbol": symbol, "trades": 0, "wf_score": study.best_value}

    return {"params": best_params, "train_summary": train_summary, "rr": best_rr}


# ---------------------------------------------------------------------------
# Egy pár optimalizálása
# ---------------------------------------------------------------------------

def optimize_pair(
    symbol: str,
    df_m15,
    df_m1,
    params_list: list[dict],
    pair_cfg: dict,
    trading_cfg: dict,
    initial_balance: float,
    train_end: str,
    strategy,
    progress_callback=None,   # fn(done: int, total: int, best_pnl: float)
    cfg: "dict | None" = None,
    exec_gates: bool = False,
) -> Optional[dict]:
    """
    Végigpróbálja az összes params kombinációt TRAIN adaton.
    Visszaadja a legjobb params dict-et és a hozzá tartozó train summary-t.

    `exec_gates`: az él végrehajtási kapuival (spread + TF-együttállás) fusson-e —
    lásd `run_optimizer_for_symbol`. A TF-kapu kiértékelője itt is EGYSZER épül
    (nem kombinációnként): nem függ a paraméterektől.
    """
    from trading.backtest import _build_tf_align_evaluator
    _tf_eval = (_build_tf_align_evaluator(cfg, symbol, strategy.name, df_m1)
                if (exec_gates and cfg is not None) else None)
    best_score = -float("inf")
    best_params = None
    best_summary = None
    all_rows: list[dict] = []   # minden kombináció eredménye → CSV export

    for i, params in enumerate(params_list):
        # Leállítás-kérés (GUI STOP gomb → stop-marker): kombináció-határon le.
        if stop_marker(symbol, strategy.name).exists():
            log.info("  %s — leállítás-kérés, a keresés megszakítva (%d/%d).",
                     symbol, i, len(params_list))
            break
        try:
            result = run_pair(
                symbol, df_m15, df_m1,
                params, pair_cfg, trading_cfg,
                initial_balance,
                test_start=None,   # TRAIN: teljes adat a train_end-ig
                strategy=strategy,
                cfg=cfg, exec_gates=exec_gates, tf_eval=_tf_eval,
                allowed_hours=_opt_allowed_hours(symbol, strategy, pair_cfg),
            )
            # TRAIN adatra szűrünk
            train_result_trades = [
                t for t in result.closed
                if t.close_time is not None and str(t.close_time.date()) < train_end
            ]
            if not train_result_trades:
                continue

            # Gyors summary a train szegmensre
            pnl_list = [t.pnl_usd for t in train_result_trades]
            wins = [p for p in pnl_list if p > 0]
            losses = [p for p in pnl_list if p <= 0]

            balance = initial_balance
            peak = balance
            max_dd = 0.0
            for p in pnl_list:
                balance += p
                peak = max(peak, balance)
                dd = (peak - balance) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)

            summary = {
                "symbol": symbol,
                "trades": len(train_result_trades),
                "win_rate": len(wins) / len(train_result_trades),
                "total_pnl": sum(pnl_list),
                "max_drawdown": max_dd,
                "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf"),
            }

            s = score(summary, min_trades=min_trades_floors(cfg)[1])

            # Sor az eredménytáblázathoz: score + metrikák + a próbált paraméterek
            row = {
                "score":         round(s, 2),
                "trades":        summary["trades"],
                "win_rate":      round(summary["win_rate"], 4),
                "total_pnl":     round(summary["total_pnl"], 2),
                "max_drawdown":  round(summary["max_drawdown"], 4),
                "profit_factor": (round(summary["profit_factor"], 3)
                                  if summary["profit_factor"] != float("inf") else "inf"),
            }
            for pk, pv in params.items():
                if not pk.startswith("_"):
                    row[pk] = pv
            all_rows.append(row)

            if s > best_score:
                best_score = s
                best_params = params
                best_summary = summary

        except Exception as e:
            log.debug("%s — kombináció hiba: %s", symbol, e)
            continue

        # Haladás MINDEN kombinációnál (stall-óra újraindítás); log 10-esével.
        best_pnl = best_summary["total_pnl"] if best_summary else 0
        if progress_callback:
            progress_callback(i + 1, len(params_list), best_pnl)
        if (i + 1) % 10 == 0:
            log.info(
                "  %s — %d/%d próbált | legjobb P&L: %.2f$",
                symbol, i + 1, len(params_list), best_pnl,
            )
            # Inkrementális CSV: az eddigi eredmények azonnal lemezre (nem vész el).
            _write_trials_csv(all_rows, trials_file(symbol, strategy.name))

    # Végső callback
    if progress_callback:
        best_pnl = best_summary["total_pnl"] if best_summary else 0
        progress_callback(len(params_list), len(params_list), best_pnl)

    # ── Teljes eredménytáblázat mentése CSV-be (score szerint csökkenő) ──────
    n = _write_trials_csv(all_rows, trials_file(symbol, strategy.name))
    if n:
        log.info("  %s — %d kombináció eredménye mentve: %s",
                 symbol, n, trials_file(symbol, strategy.name).name)

    return {"params": best_params, "train_summary": best_summary} if best_params else None


# ---------------------------------------------------------------------------
# Fő belépési pont
# ---------------------------------------------------------------------------

def _no_result_reason(symbol, df_m15, opt_cfg: dict, strategy) -> str:
    """A „nincs eredmény" OKA — a puszta tény helyett a TEENDŐ.

    Két tipikus ok van, és a kettő teljesen más lépést kíván:
      • kevés adat → nincs egyetlen walk-forward ablak sem (tölts le hosszabb
        előzményt / csökkentsd a wf_* hónapokat),
      • van adat, de MINDEN trial elbukott → az elbukás okát a trials CSV `note`
        oszlopa tartalmazza (kényszer, kivétel, kevés kötés) → azt összegezzük.
    """
    train_m = int(opt_cfg.get("wf_train_months", 6))
    test_m  = int(opt_cfg.get("wf_test_months", 2))
    try:
        span_m = (df_m15.index[-1] - df_m15.index[0]).days / 30.44
    except Exception:
        span_m = 0.0
    if span_m < train_m + test_m:
        return (f"kevés adat: {span_m:.1f} hónap a train_start után, a "
                f"walk-forwardhoz legalább {train_m + test_m} hónap kell "
                f"(train {train_m} + test {test_m}). Tölts le hosszabb "
                f"előzményt (data.history_start_date), vagy csökkentsd a "
                f"wf_train_months/wf_test_months értékét.")

    # A trials CSV `note` oszlopa: mi bukott el a legtöbbször?
    try:
        import collections
        with open(trials_file(symbol, strategy.name), encoding="utf-8-sig",
                  newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        notes = collections.Counter((r.get("note") or "").strip()
                                    for r in rows if (r.get("note") or "").strip())
        if notes:
            top, cnt = notes.most_common(1)[0]
            return (f"mind a(z) {len(rows)} trial érvénytelen — leggyakoribb ok: "
                    f"{top} ({cnt}×). Nézd meg a trials CSV `note` oszlopát.")
    except Exception:
        pass
    return ("egyetlen paraméterkészlet sem hozott értékelhető kötést a TEST "
            "ablakokban (ablakonként min. 5 kötés kell) — lazíts a "
            "paraméter-tartományokon vagy az órakapun.")


def optimize_symbol(symbol, df_m15, df_m1, cfg, initial_balance, progress=None,
                    strategy=None) -> dict:
    """EGYSÉGES optimalizálási belépési pont — a CLI és a GUI-processz is EZT hívja.

    ⚠ EZ A BUROK CSAK A ZÁRAT KEZELI; a munka a `_optimize_symbol_locked`-ban van.
    2026-08-04-én ÉLESBEN megtörtént, hogy egy CLI-futás és egy GUI-ból indított
    futás PÁRHUZAMOSAN dolgozott ugyanazon a (Ger40, wpr_sma) páron: közös optuna
    study (a „500 trial" a kettő EGYÜTTESE lett), közös kimeneti fájl (az egyik
    felülírta volna a másikat), sőt eltérő kódverzió. A GUI saját védelme
    (`_symbol_busy`) csak a SAJÁT sorára lát — egy külső processzről nem tud.

    ITT a helye, mert ez az EGYETLEN pont, amin a CLI és a GUI is átmegy: bármely
    FELÜLETRE tett zárat meg lehetne kerülni a másik felülettel.

    ⚠ ÉS `finally`-VAL. A belső függvénynek öt visszatérési ága van, plusz a
    kivételek; kézzel elengedni mindegyiken előbb-utóbb kimaradna egy — és egy
    ottfelejtett zár a következő indulást tagadná meg."""
    if strategy is None:
        from strategy import get_strategy
        strategy = get_strategy(cfg)

    from core import opt_lock as _lock
    _ok, _held = _lock.acquire(symbol, strategy.name)
    if not _ok:
        msg = _lock.describe(_held, symbol, strategy.name)
        log.error("%s/%s — %s", symbol, strategy.name, msg)
        return {"error": msg}
    try:
        return _optimize_symbol_locked(symbol, df_m15, df_m1, cfg,
                                       initial_balance, progress, strategy)
    finally:
        _lock.release(symbol, strategy.name)


def _optimize_symbol_locked(symbol, df_m15, df_m1, cfg, initial_balance,
                            progress=None, strategy=None) -> dict:
    """A tényleges optimalizálás — a zárat a hívó `optimize_symbol` tartja.

    A method-döntés (optuna | grid | random) EGYETLEN helyen él, így a két felület
    sosem csúszhat szét. Az adat szeletelése train_start-tól, a trials CSV kiírása
    (a compute-függvényekben) és az out-of-sample teszt is itt, egységesen történik.

    strategy: a használandó stratégia (seam). None → a config alapján (get_strategy).
    progress: opcionális fn(done, total, best) haladásjelző.
    Visszaad: {"train_summary","test_summary","params"} vagy {"error": "..."}.
    """
    if strategy is None:
        from strategy import get_strategy
        strategy = get_strategy(cfg)

    # A cfg átképezése a JOB stratégiájának nézetére: a futásidejű cfg az
    # ELSŐDLEGES stratégia szekcióival van merge-elve — másodlagos stratégia
    # optimalizálásakor annak a SAJÁT indicators/sltp/optimizer-tere kell
    # (különben a base_params a másik stratégia kulcsait kapná).
    from strategy.settings import config_for_strategy
    cfg = config_for_strategy(cfg, strategy.name)

    # Stratégia-hatókörű tárolás: az aktív stratégiát beállítjuk (a subprocess is
    # ezt hívja) + egyszeri migráció a régi lapos elrendezésről.
    set_active_strategy(strategy.name)
    migrate_flat_layout(strategy.name)

    opt_cfg     = cfg["optimizer"]
    method      = opt_cfg.get("method", "random")
    max_trials  = opt_cfg.get("max_trials", 500)
    train_start = opt_cfg.get("train_start_date", "2025-01-01")
    test_start  = opt_cfg.get("test_start_date", "2025-10-01")
    trading_cfg = cfg["trading"]
    pair_cfg    = cfg["pairs"][symbol]
    base_params = strategy.base_params(cfg)
    # A BE/trailing/atr_period/spread-kapu MÁR NEM stratégia-paraméter (közös,
    # instrumentum-szintű execution config) — de a stratégia hookjai (pl.
    # wpr_sma.bt_warmup: `params["atr_period"]`) még mindig elvárják, hogy a
    # kulcs jelen legyen minden trial params-jában. A jelenlegi, ténylegesen ható
    # értékkel töltjük fel (nem keresi az optimalizáló — konstansként viszi
    # minden trial-on át).
    base_params = {**base_params, **load_execution_params(symbol, cfg)}

    # ── ÉL-PARITÁS: az optimalizáló ugyanazokat a végrehajtási kapukat járja ──
    # Ez a v1.95.0 előtt NEM így volt, és ez volt a legsúlyosabb csendes hiba a
    # rendszerben: a `run_pair` csak `exec_gates=True` mellett építi a spread- és
    # a TF-együttállás kaput, az optimalizáló viszont MINDHÁROM hívását kapuk
    # NÉLKÜL indította. Az él mindkettőt alkalmazza → MINDEN mentett
    # paraméterkészlet egy olyan világban lett hangolva, ami élesben nem létezik.
    # (Ez okozta azt is, hogy egy trials-sor betöltése után a Backtest-ablak — ami
    # alapból kapuz — MÁS eredményt adott, mint amit az optimalizáló mutatott.)
    #
    # Kapcsolható, hogy a RÉGI futások reprodukálhatók maradjanak; alap: BE.
    exec_gates = bool(opt_cfg.get("exec_gates", True))
    log.info("  Végrehajtási kapuk (spread + TF-együttállás): %s",
             "BE (él-paritás)" if exec_gates else "KI (nyers jelek)")

    # A tanítható ág (lentebb) a TELJES előzményt kapja — a modell-tanítás a saját
    # lookback-jét alkalmazza (optimizer.training.lookback_years), nem a
    # train_start_date-et (több adat = jobb modell).
    df_m15_full = df_m15

    # Adat szeletelése train_start-tól (idempotens, ha a hívó már szeletelt)
    ts_train = pd.Timestamp(train_start)
    if df_m15.index.tzinfo is not None:
        ts_train = ts_train.tz_localize("UTC")
    df_m15 = df_m15[df_m15.index >= ts_train]
    df_m1  = df_m1[df_m1.index  >= ts_train]
    if len(df_m15) < 200 or len(df_m1) < 200:
        return {"error": "túl kevés adat a train_start után"}

    # OOS-kapu: ha a test_start_date az adat végén túl van (pl. jövőbeli dátum a
    # configban), az out-of-sample szelet ÜRES lenne → az optimizer némán 0-trade
    # test_summary-t mentene (nincs Minőség, a param-ablak "0 trade"-et mutat).
    # Ilyenkor az utolsó wf_test_months hónapra esünk vissza, és naplózzuk.
    ts_test = pd.Timestamp(test_start)
    if df_m15.index.tzinfo is not None:
        ts_test = ts_test.tz_localize("UTC")
    data_end = df_m15.index[-1]
    if ts_test >= data_end:
        _fb = data_end - pd.DateOffset(months=int(opt_cfg.get("wf_test_months", 2)))
        log.warning("  %s — test_start_date (%s) az adat vége (%s) UTÁN van → "
                    "OOS fallback: %s", symbol, test_start,
                    data_end.date(), _fb.date())
        test_start = _fb.strftime("%Y-%m-%d")

    # ── Method-dispatch (EGY helyen) ─────────────────────────────────────────
    # (A stop-marker takarítása a KÉRÉSKOR történik — request_optimize / CLI —,
    # itt nem törlünk: az adat-előkészítés alatt kért STOP-nak is élnie kell.)
    if callable(getattr(strategy, "fit", None)):
        # Tanítható stratégia (pl. ml_ai): az „optimalizálás" = MODELL-TANÍTÁS.
        # A fit a teljes előzményből tanít a test_start ELŐTTI adaton, menti a
        # modellt, és {"params","train_summary"}-t ad — az OOS teszt (lentebb)
        # és a mentés a KÖZÖS úton megy, mint a paraméter-keresésnél.
        log.info("  Tanítható stratégia (%s) → modell-tanítás...", strategy.name)
        done_flag = done_marker(symbol, strategy.name)
        done_flag.unlink(missing_ok=True)          # friss futás — friss marker
        try:
            result = strategy.fit(symbol, df_m15_full, cfg, pair_cfg,
                                  test_start=test_start, progress_callback=progress)
        except RuntimeError as ex:                 # tanítás megszakítva (stop marker)
            log.info("  %s — tanítás megszakítva: %s", symbol, ex)
            result = None
        if result is not None and "error" not in result:
            done_flag.touch()                      # 'Utolsó opt:' címke + állapot
    elif method == "optuna" and _OPTUNA_AVAILABLE:
        log.info("  Optuna Bayesian optimalizálás (%d trial, walk-forward)...", max_trials)
        result = optimize_pair_optuna(
            symbol, df_m15, df_m1, opt_cfg, base_params, pair_cfg, trading_cfg,
            initial_balance, strategy,
            n_trials=max_trials,
            n_splits=opt_cfg.get("wf_n_splits", 4),
            train_months=opt_cfg.get("wf_train_months", 6),
            test_months=opt_cfg.get("wf_test_months", 2),
            progress_callback=progress,
            cfg=cfg, exec_gates=exec_gates)
    elif method == "grid":
        params_list = generate_grid_params(opt_cfg, base_params, strategy.constraints_ok)
        log.info("  Grid search: %d kombináció", len(params_list))
        result = optimize_pair(symbol, df_m15, df_m1, params_list, pair_cfg,
                               trading_cfg, initial_balance, test_start, strategy,
                               progress_callback=progress,
                               cfg=cfg, exec_gates=exec_gates)
    else:
        params_list = generate_random_params(opt_cfg, base_params, max_trials,
                                             strategy.constraints_ok)
        log.info("  Random search: %d kombináció", len(params_list))
        result = optimize_pair(symbol, df_m15, df_m1, params_list, pair_cfg,
                               trading_cfg, initial_balance, test_start, strategy,
                               progress_callback=progress,
                               cfg=cfg, exec_gates=exec_gates)

    # ── Leállítás-kérés (GUI STOP): a futás eredményét ELDOBJUK ─────────────
    # A user-cancel nem hiba és nem „megszakadt futás": a meglévő mentett
    # paraméterek érintetlenek maradnak, és az induláskori auto-folytatás sem
    # veszi fel újra (a study lezárva/törölve).
    _stop_p = stop_marker(symbol, strategy.name)
    if _stop_p.exists():
        _stop_p.unlink(missing_ok=True)
        try:
            import gc
            gc.collect()                      # SQLite-kapcsolat elengedése (Windows-zár)
            study_db(symbol, strategy.name).unlink(missing_ok=True)
        except Exception:
            # Ha a .db zárolt, a done-marker akadályozza az auto-folytatást;
            # a KÖVETKEZŐ Opt friss study-val indul (done+db → reset).
            try:
                done_marker(symbol, strategy.name).touch()
            except Exception as ex:
                log.warning("  %s — a done-marker nem jött létre (%s): a zárolt "
                            "study miatt a következő OPT nem tud frissen "
                            "indulni.", symbol, ex)
        log.info("  %s — optimalizálás MEGSZAKÍTVA (user stop), eredmény eldobva.",
                 symbol)
        return {"error": "megszakítva", "stopped": True}

    if result is None:
        return {"error": _no_result_reason(symbol, df_m15, opt_cfg, strategy)}

    # A `fit` ág (pl. ml_ai) a saját params-ját a `base_params`-tól FÜGGETLENÜL
    # építi — ráfésüljük a közös execution configot is, hogy az OOS teszt (lentebb)
    # és a mentett eredmény a TÉNYLEGESEN ható BE/trailing/atr_period/spread-kapu
    # értékkel egyezzen (ne a beépített alapértékkel).
    if "params" in result:
        result["params"] = {**result["params"], **load_execution_params(symbol, cfg)}

    # Out-of-sample (TEST) validálás — szintén itt, egységesen. A nyertes rr-rel
    # (ha volt rr-optimalizálás), hogy a mentett test_summary konzisztens legyen.
    _best_rr = result.get("rr")   # csak az optuna-ág adja; grid/random → None (OFF)
    try:
        test_result  = run_pair(symbol, df_m15, df_m1, result["params"],
                                pair_cfg, trading_cfg, initial_balance,
                                test_start=test_start, strategy=strategy,
                                rr=_rr_for_run(_best_rr),
                                cfg=cfg, exec_gates=exec_gates,
                                allowed_hours=_opt_allowed_hours(symbol, strategy,
                                                                 pair_cfg))
        test_summary = test_result.summary(initial_balance)
    except Exception as e:
        log.warning("  %s — TEST hiba: %s", symbol, e)
        test_summary = {}

    # Fix volatilitás-MÉRCE mentése a paraméterek közé: az optimalizált atr_period-del
    # számolt ATR ÁTLAGA a betöltött adaton — EGY szám, amit a backtest, a viz és az él
    # is használ (ablak-függetlenül) → a három egyezik, és a backtest reprodukálható
    # (több letöltött előzmény nem billenti el az eredményt). Fallback marad az ablak-
    # átlag, ha ez hiányzik (régi params / a stratégia nem ad atr_avg-ot).
    try:
        _m15_ind, _ = strategy.bt_indicators(
            df_m15, df_m1, {**result["params"], "symbol": symbol,
                            "point_size": pair_cfg.get("point_size", 0.0001)})
        if "atr_avg" in _m15_ind.columns and len(_m15_ind):
            _av = float(_m15_ind["atr_avg"].iloc[0])
            if _av > 0:
                result["params"]["atr_avg_ref"] = _av
    except Exception:
        pass

    return {
        "train_summary": result["train_summary"],
        "test_summary":  test_summary,
        "params":        result["params"],
        "rr":            _best_rr,
        # MELYIK VILÁGBAN lett hangolva. A mentett fájlból így kiderül, hogy a
        # készlet kapu-tudatos-e — enélkül egy régi (v1.95.0 előtti) és egy új
        # eredmény ránézésre megkülönböztethetetlen, pedig MÁST jelent.
        "exec_gates":    exec_gates,
    }


def apply_optimized_rr(symbol: str, rr: dict):
    """A nyertes rr-t a per-pár állapotba írja (data/risk_mode.json) → a live/GUI
    ezt veszi át (mint az optimalizált paramétereket). Naplózza az alkalmazást."""
    if not rr:
        return
    try:
        from core import rr_state
        rr_state.set_from_optimizer(symbol, rr)
        log.info("  %s — rr alkalmazva a live-ra: preset=%s runner=%s "
                 "trigger_R=%s halving=%s shield=%s", symbol, rr.get("preset"),
                 rr.get("runner_stop"), rr.get("trigger_R"),
                 rr.get("halving_fraction"), rr.get("shield_fraction"))
    except Exception as e:
        log.warning("  %s — rr_state alkalmazás hiba: %s", symbol, e)


def resolve_cli_strategies(cfg: dict, symbol: str,
                           requested: Optional[list[str]] = None) -> list[str]:
    """MELY stratégiákat optimalizálja a CLI ezen a páron.

    `requested`: a `--strategy` kapcsoló nevei (a hívó már ellenőrizte, hogy
    léteznek). None → a pár SAJÁT engedélyezett stratégiái
    (`pairs.<sym>.strategies`), tehát ugyanaz a halmaz, amit a motor futtat.

    MIÉRT NEM az elsődleges stratégia (a v1.97.0-ig ez volt). A CLI mindig a
    `strategy.name`-et optimalizálta, függetlenül attól, mi van a páron
    engedélyezve — így az `ml_ai`-t egyáltalán nem lehetett CLI-ből tanítani, és
    aki az `ml_ai` „tanítsd újra" üzenetét követte, NÉMÁN a `wpr_sma`-t hangolta
    újra. A GUI OPT gombja már per stratégia dolgozott; ez a függvény hozza a
    CLI-t ugyanarra a szintre.

    A pár listáját az ELÉRHETŐKRE szűrjük: egy `available_strategies`-ben
    kikapcsolt stratégiát a felület sem kínál, tehát a CLI se hangolja némán."""
    from strategy import enabled_strategy_names, available_strategy_names
    if requested:
        return list(requested)
    avail = set(available_strategy_names(cfg))
    names = [n for n in (enabled_strategy_names(cfg, symbol) or []) if n in avail]
    return names


def run_optimizer(cfg: dict, symbols: Optional[list[str]] = None,
                  strategies: Optional[list[str]] = None):
    """CLI-optimalizálás — pár × STRATÉGIA.

    `symbols`:    mely párok (None → az összes `enabled`).
    `strategies`: mely stratégiák (None → páronként a sajátjai, lásd
                  `resolve_cli_strategies`). A hívó (`main.py`) ellenőrzi a neveket.

    Egy szimbólumon TÖBB stratégia egymás után fut; mindegyik a SAJÁT
    paraméter-terével és saját kimeneti fájljával (`data/optimized_params/
    <stratégia>/<SYMBOL>.json`), tehát nem írják felül egymást."""
    from strategy import get_strategy_by_name
    opt_cfg     = cfg["optimizer"]
    method      = opt_cfg.get("method", "random")
    max_trials  = opt_cfg.get("max_trials", 500)
    initial_balance = cfg.get("ml", {}).get("starting_balance_eur", 1000.0)

    # Egyszeri migráció a RÉGI lapos elrendezésről — ez az ELSŐDLEGES stratégiáé
    # (a lapos fájlok még egy-stratégiás korból valók), függetlenül attól, mit
    # optimalizálunk most.
    from strategy.settings import strategy_name as _stratname
    _primary = _stratname(cfg)
    set_active_strategy(_primary)
    migrate_flat_layout(_primary)

    # Párok kiválasztása
    all_pairs = {s: p for s, p in cfg["pairs"].items() if isinstance(p, dict) and p.get("enabled", False)}
    if symbols:
        _known = {s for s, p in cfg["pairs"].items() if isinstance(p, dict)}
        # Elgépelt vagy LETILTOTT párnév: a kettő más teendőt jelent, ezért külön
        # mondjuk. Enélkül a futás csak annyit közölne, hogy „nincs mit
        # optimalizálni" — és úgy tűnne, a parancs lefutott.
        for s in symbols:
            if s not in _known:
                log.warning("Ismeretlen instrumentum: %r (a config.json pairs "
                            "szekciójában nincs ilyen)", s)
            elif s not in all_pairs:
                log.warning("%s — le van tiltva (pairs.%s.enabled = false), kihagyva",
                            s, s)
        all_pairs = {s: p for s, p in all_pairs.items() if s in symbols}

    # A MUNKATÉTELEK: (pár, stratégia). Előre kiszámoljuk, hogy a napló első
    # sorában látszódjon, MI FOG FUTNI — egy hosszú futásnál ez az egyetlen
    # pillanat, amikor még olcsó észrevenni, ha nem azt kértük, amit akartunk.
    jobs: list = []
    for symbol in all_pairs:
        for sname in resolve_cli_strategies(cfg, symbol, strategies):
            jobs.append((symbol, sname))
    if not jobs:
        if not all_pairs:
            log.warning("Nincs mit optimalizálni: egyetlen kiválasztott pár sem "
                        "aktív (pairs.<sym>.enabled).")
        else:
            log.warning("Nincs mit optimalizálni: a kiválasztott párokon egyetlen "
                        "elérhető stratégia sincs engedélyezve "
                        "(pairs.<sym>.strategies / available_strategies).")
        return

    _by_strat: dict = {}
    for _s, _n in jobs:
        _by_strat.setdefault(_n, []).append(_s)
    log.info("Optimalizálás indul | módszer: %s | max_trials: %d | tételek: %d",
             method, max_trials, len(jobs))
    for _n, _syms in _by_strat.items():
        _existing = [f.stem for f in strategy_dir(_n).glob("*.json")]
        log.info("  %-10s → %s%s", _n, ", ".join(_syms),
                 f"   (már megvan: {', '.join(_existing)})" if _existing else "")

    _loaded: dict = {}          # symbol → (df_m15, df_m1); páronként EGYSZER olvas

    for symbol, sname in jobs:
        strategy = get_strategy_by_name(sname)
        # Ha már van mentett eredmény és nem kényszerített újrafuttatás → kihagyás.
        # A `symbols` (kifejezett pár-lista) a felülírás jelzése — ahogy eddig.
        if params_file(symbol, sname).exists() and not symbols:
            log.info("─" * 60)
            log.info("✓  %s/%s — már optimalizálva, kihagyva. (Felülíráshoz: "
                     "python main.py optimize %s --strategy %s)",
                     symbol, sname, symbol, sname)
            continue

        log.info("─" * 60)
        log.info("▶  %s / %s optimalizálása...", symbol, sname)
        t0 = time.time()
        # Elavult (GUI-s) leállítás-marker törlése — a CLI-futást ne szakítsa meg.
        stop_marker(symbol, sname).unlink(missing_ok=True)

        if symbol not in _loaded:
            _loaded[symbol] = load_data(symbol)
        df_m15, df_m1 = _loaded[symbol]
        if df_m15 is None:
            log.warning("%s — nincs adat, kihagyva.", symbol)
            continue

        # ── KÖZÖS dispatch (ugyanaz, mint a GUI-ban) ──────────────────────
        # A `strategy` ÁTADÁSA a lényeg: enélkül az `optimize_symbol` a config
        # elsődleges stratégiájára esne vissza, és minden tétel ugyanazt hangolná.
        result = optimize_symbol(symbol, df_m15, df_m1, cfg, initial_balance,
                                 strategy=strategy)
        if "error" in result:
            log.warning("%s/%s — %s", symbol, sname, result["error"])
            continue

        train_summary = result["train_summary"]
        test_summary  = result.get("test_summary", {})
        elapsed = time.time() - t0
        log.info(
            "  TRAIN | Kötések: %d | Win: %.0f%% | P&L: %.2f$ | MaxDD: %.1f%%",
            train_summary.get("trades", 0),
            train_summary.get("win_rate", 0) * 100,
            train_summary.get("total_pnl", 0),
            train_summary.get("max_drawdown", 0) * 100,
        )
        if test_summary:
            log.info(
                "  TEST  | Kötések: %d | Win: %.0f%% | P&L: %.2f$ | MaxDD: %.1f%%",
                test_summary.get("trades", 0),
                test_summary.get("win_rate", 0) * 100,
                test_summary.get("total_pnl", 0),
                test_summary.get("max_drawdown", 0) * 100,
            )
        log.info("  ⏱  %.1f mp", elapsed)

        entry = {
            "symbol":        symbol,
            "optimized_at":  datetime.utcnow().isoformat(),
            # Kapu-tudatos-e a készlet (v1.95.0+). Hiányzó kulcs = RÉGI eredmény,
            # ami kapuk NÉLKÜL lett hangolva — élesben más világ.
            "exec_gates":    result.get("exec_gates", True),
            "train_summary": train_summary,
            "test_summary":  test_summary,
            "params":        result["params"],
        }
        _rr = result.get("rr")
        if _rr:
            entry["rr"] = _rr
        # A célfájl EXPLICIT stratégiával: az `optimize_symbol` menet közben
        # átállítja a modul-szintű aktív stratégiát, tehát az implicit alak
        # (`params_file(symbol)`) itt a MÚLTBELI állapotra hagyatkozna.
        out = params_file(symbol, sname)
        tmp = out.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2, ensure_ascii=False, default=str)
        tmp.replace(out)
        log.info("  Mentve: %s", out)
        if _rr:
            apply_optimized_rr(symbol, _rr)

    log.info("=" * 60)
    log.info("Optimalizálás kész.")

    # Összesített kimutatás — STRATÉGIÁNKÉNT (a fájlok is stratégia-almappákban
    # élnek, tehát egy közös tábla összemosná a két világot).
    for sname in _by_strat:
        files = sorted(strategy_dir(sname).glob("*.json"))
        if not files:
            continue
        log.info("")
        log.info("%s  —  %s", sname, strategy_dir(sname))
        log.info("%-10s  %6s  %6s  %8s  %8s", "Szimbólum", "Kötés", "Win%", "P&L$", "MaxDD%")
        log.info("-" * 50)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            ts = data.get("test_summary", {})
            log.info(
                "%-10s  %6d  %5.0f%%  %8.2f  %7.1f%%",
                data.get("symbol", f.stem),
                ts.get("trades", 0),
                ts.get("win_rate", 0) * 100,
                ts.get("total_pnl", 0),
                ts.get("max_drawdown", 0) * 100,
            )


# ---------------------------------------------------------------------------
# Külön PROCESSZBEN futtatható feladat (GIL-mentes — a GUI sosem fagy tőle)
# ---------------------------------------------------------------------------

def optimize_job(symbol, df_m15, df_m1, cfg, initial_balance, progress_q=None,
                 strategy_name=None) -> dict:
    """Az `optimize_symbol` PROCESSZBEN futtatható burka (a GUI ezt küldi a pool-nak).

    Minden bemenet picklezhető (DataFrame-ek + a teljes cfg dict), nincs MT5 vagy
    tkinter függés. A haladást a progress_q-ra teszi (symbol, done, total) hármasként.
    A method-döntést (optuna|grid|random) az optimize_symbol intézi → a GUI és a CLI
    UGYANAZT az utat járja. Visszaad: {"train_summary","test_summary","params"} | {"error"}.

    `strategy_name`: MELYIK stratégiát optimalizáljuk (picklázható név, a subprocess
    a `get_strategy_by_name`-mel oldja fel). None → a config alapértelmezett stratégiája
    (visszafelé kompatibilis)."""
    def _progress(done, total, best):
        if progress_q is not None:
            try:
                progress_q.put((symbol, done, total))
            except Exception:
                pass

    try:
        strategy = None
        if strategy_name:
            from strategy import get_strategy_by_name
            strategy = get_strategy_by_name(strategy_name)
        return optimize_symbol(symbol, df_m15, df_m1, cfg, initial_balance,
                               progress=_progress, strategy=strategy)
    except Exception as e:
        import traceback
        return {"error": f"{e}", "traceback": traceback.format_exc()}


if __name__ == "__main__":
    cfg_path = ROOT / "config.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    # Opcionálisan: csak megadott szimbólumok optimalizálása
    # python ml/optimizer.py EURUSD GBPJPY
    symbols = sys.argv[1:] if len(sys.argv) > 1 else None
    run_optimizer(cfg, symbols)
