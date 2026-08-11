"""Söprés: EGY vagy KÉT paraméter végigpróbálása, kimerítően.

A felhasználói dokumentáció kérése:

    „Ha a paramétereink között van tól-ig, akkor miért ne csinálhatnánk meg azt,
     hogy pl. csak az SMA-t 100→200-ig backtesteljük bizonyos időszakra. Ez is
     optimalizálás, és ez is backtest része."

⚠ MIÉRT NEM ELÉG EGY `for` CIKLUS A run_pair KÖRÜL — a rács szerkezete
kihasználható. Egy `sma_period × tp_rr_ratio` rács (26 × 13 = 338 futás) esetén
a 13 TP-érték UGYANAZT a belépő-listát használja: a `tp_rr_ratio` végrehajtási
paraméter, nem változtatja a jelzést. Ha a futásokat a JEL-paraméterek szerint
csoportosítjuk, elég 26-szor felépíteni a jelölt-listát 338 helyett.

Ez ugyanaz a gondolat, ami a beágyazott OPTIMALIZÁLÁSNÁL megbukott — de ott az
optuna véletlenszerűen mintavételez, tehát két egymás utáni trial szinte sosem
osztozik a jel-paramétereken. Egy KIMERÍTŐ rácsnál a csoportosítás ingyen van,
és mindig nyer. (Mérve: a végrehajtási futás 1,7–2,0× gyorsabb.)

A modul KÖNNYŰ a felület felé: nincs Tk-függése.
"""
from __future__ import annotations

import itertools
import logging

log = logging.getLogger(__name__)


def combos(rows: list, opt_cfg: dict) -> tuple:
    """A söprés rács-pontjai. Visszaad: `(tengelyek, kombinációk)`.

    `tengelyek`: `[(kulcs, [értékek]), …]` — a megjelenítés ebből tudja, mit
    tegyen az X és az Y tengelyre. `kombinációk`: `[{kulcs: érték}, …]`.
    """
    from core import opt_plan as _op
    specs = _op.tuned_specs(opt_cfg)
    axes = []
    for r in rows:
        if r.get("skipped") or r["key"] not in specs:
            continue
        vals = _op.grid_values(specs[r["key"]])
        if vals:
            axes.append((r["key"], vals))
    if not axes:
        return [], [{}]
    keys = [a[0] for a in axes]
    return axes, [dict(zip(keys, vs))
                  for vs in itertools.product(*[a[1] for a in axes])]


def group_by_signal(combos_list: list, strategy_name: str) -> list:
    """A kombinációk csoportosítása a JEL-paraméterek szerint.

    Visszaad: `[(jel_rész, [kombináció, …]), …]` — csoportonként EGY jelölt-lista
    elég. A csoportok sorrendje a bemenetét követi (determinisztikus).
    """
    from strategy.settings import load_strategy_config, param_class, SIGNAL_PARAM
    try:
        scfg = load_strategy_config(strategy_name)
    except Exception:
        scfg = {}
    groups, order = {}, []
    for c in combos_list:
        key = tuple(sorted((k, v) for k, v in c.items()
                           if param_class(scfg, k) == SIGNAL_PARAM))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)
    return [(dict(k), groups[k]) for k in order]


def metrics_of(result, initial_balance: float) -> dict:
    """A söprés egy pontjának mérőszámai — ugyanazok, amiket az eredménytábla mutat."""
    try:
        s = result.summary(initial_balance) or {}
    except Exception:
        s = {}
    return {
        "trades": int(s.get("trades", 0) or 0),
        "win_rate": float(s.get("win_rate", 0.0) or 0.0),
        "total_pnl": float(s.get("total_pnl", 0.0) or 0.0),
        "max_drawdown": float(s.get("max_drawdown", 0.0) or 0.0),
        "profit_factor": float(s.get("profit_factor", 0.0) or 0.0),
    }


def run(symbol, df_m15, df_m1, base_params, pair_cfg, trading_cfg,
        initial_balance, strategy, combos_list, *, test_start=None,
        test_end=None, allowed_hours=None, rr=None, build=None, cfg=None,
        exec_gates=False, progress=None, stop_flag=None) -> list:
    """A söprés lefuttatása. Visszaad: `[{**kombináció, **metrikák}, …]`.

    `progress(kész, összes, utolsó_eredmény)` — best-effort.
    `stop_flag`: `threading.Event`; megszakításkor a RÉSZEREDMÉNYT adja vissza.
    """
    from trading.backtest import run_pair, signal_series_cached

    out = []
    total = len(combos_list)
    done = 0
    cache = None
    for sig_part, group in group_by_signal(combos_list, strategy.name):
        if stop_flag is not None and stop_flag.is_set():
            break
        # A csoport minden tagja ugyanazt a jelölt-listát használja: a csoport
        # ELSŐ paraméterkészletével építjük (a jel-rész mindegyikben azonos).
        series = None
        try:
            first = {**base_params, **group[0]}
            cache, _reused = signal_series_cached(
                cache, symbol, df_m15, df_m1, first, pair_cfg,
                strategy=strategy, test_start=test_start, test_end=test_end,
                allowed_hours=allowed_hours)
            series = cache
        except Exception as ex:
            # ⚠ Nem néma: ha a gyorsítótár nem építhető, a söprés FUT tovább
            # (csak lassabban) — a hibás eredmény sokkal rosszabb volna, mint a
            # lassú. A `run_pair` series nélkül ugyanazt számolja ki.
            log.warning("%s — a jelölt-lista nem építhető (%s: %s); a söprés "
                        "gyorsítótár nélkül fut tovább", symbol,
                        type(ex).__name__, ex)
            series = None

        for c in group:
            if stop_flag is not None and stop_flag.is_set():
                break
            params = {**base_params, **c}
            row = dict(c)
            try:
                res = run_pair(symbol, df_m15, df_m1, params, pair_cfg,
                               trading_cfg, initial_balance,
                               test_start=test_start, test_end=test_end,
                               strategy=strategy, allowed_hours=allowed_hours,
                               rr=rr, build=build, cfg=cfg,
                               exec_gates=exec_gates, signal_series=series)
                row.update(metrics_of(res, initial_balance))
                row["note"] = ""
            except Exception as ex:
                # Egy elhasalt pont nem viheti el az egész söprést — a rács
                # többi pontja értékes marad. Az OK viszont látszódjon.
                row.update({"trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
                            "max_drawdown": 0.0, "profit_factor": 0.0,
                            "note": f"{type(ex).__name__}: {ex}"})
            out.append(row)
            done += 1
            if progress is not None:
                try:
                    progress(done, total, row)
                except Exception:
                    pass
    return out


def best(rows: list, metric: str = "total_pnl") -> dict | None:
    """A legjobb pont egy mérőszám szerint (az elhasalt pontok kiesnek)."""
    live = [r for r in rows if not r.get("note")]
    if not live:
        return None
    rev = metric != "max_drawdown"        # a visszaesésnél a KISEBB a jobb
    return sorted(live, key=lambda r: r.get(metric, 0.0), reverse=rev)[0]
