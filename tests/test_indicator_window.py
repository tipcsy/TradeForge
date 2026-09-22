"""INDIKÁTOR-ABLAK — a vágás NEM változtathatja meg az eredményt.

⚠ MIÉRT (2026-09-22). Mindkét backtest-út a TELJES betöltött kereten számolt
indikátort (Ger40: 101 741 M15 bar = 5 év), majd levágta a 97 %-át egy 2-3
hónapos teszthez. Fázis-profilozva ez a portfólió futásidejének **68 %-a**
(`bt_indicators`), miközben a végrehajtási ciklus 0,5 %. A javítás: a keretet
a `[test_start − warmup, test_end]` ablakra vágjuk a SZÁMÍTÁS ELŐTT.

⚠ ÉS EZ PONTOSAN A PROJEKT HIBAOSZTÁLYA. Egy vágás akkor ártalmatlan, ha az
indikátorok OK-OKOZATIAK (csak a múltat nézik, véges ablakkal). Ha bármelyik
a TELJES sorozatból számol (pl. egy `mean()` az egész kereten), a vágás
NÉMÁN más számot ad — és egy ilyen oszlop egyébként is look-ahead volna.

Ez a teszt tehát nem a sebességet méri, hanem azt, hogy a gyorsítás NEM
változtat: ugyanaz az időszak TELJES és VÁGOTT kereten BITRE ugyanazokat a
kötéseket adja — minden stratégiára külön (mindegyik `bt_indicators`-a máshogy
függhet az előzménytől).

⚠ AMIT MÉR, ÉS AMIT NEM. A `run_pair` a mérőhely: ha a vágott keret más
kötéseket ad, az vagy egy teljes-sorozat statisztika, vagy egy warmup, ami
nem fedi le a saját bemenetét (pl. `atr_baseline_bars` gördülő mércénél).
Mindkettő VALÓDI hiba — a teszt ilyenkor helyesen bukik.

ÉLES ADAT KELL (`requires_live_data.txt`).

Futtatás:  python tests/test_indicator_window.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import applog
applog.harden_console()

import logging
logging.getLogger().setLevel(logging.ERROR)

import pandas as pd

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy.settings import load_config, default_params
from strategy import get_strategy_by_name
from trading import backtest as bt
from core import risky_mode, rr_state
from core.params_store import params_file, set_active_strategy
from core.execution_params import load_execution_params

TOL = os.environ.get("ABLAK_TOL", "2026-06-01")
IG = os.environ.get("ABLAK_IG", "2026-09-01")
CELLAK = [tuple(x.split("/")) for x in
          os.environ.get("ABLAK_CELLAK", "Ger40/wpr_sma,GOLD/wpr_sma,"
                                         "UsaTec/wpr_sma,Ger40/csilla,"
                                         # ⚠ NINCS `atr_avg_ref`-jük → a volatilitás-kapu a SZÁMOLT
                                         # `atr_avg`-ot használja (teljes-sorozat átlag), tehát a
                                         # vágás ITT változtathat a legkönnyebben. A vakfolt 2026-09-22-n
                                         # derült ki: az első lista csak `atr_avg_ref`-es cellákat vitt.
                                         "USDJPY/wpr_sma,EURHUF/wpr_sma").split(",")]

cfg = load_config(ROOT / "config.json")
risky_mode.load()
rr_state.load()
MEZOK = ("direction", "open_time", "open_price", "sl", "tp", "lot", "sl_points",
         "close_time", "close_price", "pnl_usd", "status", "risk_free")


def _kotesek(sym, st, prm, df15, df1, vagas: bool):
    """`vagas=False` → a motor keret-szűkítése KIKAPCSOLVA (a régi viselkedés).

    ⚠ EZ A TESZT LELKE. Ha mindkét kart a motoron engednénk át, az ÚJ kód
    MINDKETTŐT ugyanarra az ablakra vágná — a „bitre egyezik" állítás önmagát
    hasonlítaná össze (a projekt harmadik vákuum-teszt esete ma:
    `vacuous-parity-tests`). Ezért az egyik kart a szűkítő KIIKTATÁSÁVAL
    futtatjuk: így tényleg a TELJES keret áll szemben a vágottal."""
    _ment = bt._szukit_keret
    if not vagas:
        bt._szukit_keret = lambda a, b, *r, **k: (a, b)
    try:
        r = bt.run_pair(sym, df15, df1, prm, cfg["pairs"][sym], cfg["trading"], 1000.0,
                        test_start=TOL, test_end=IG, strategy=st,
                        risky=risky_mode.is_risky(sym), rr=rr_state.spec_for(sym),
                        cfg=cfg, exec_gates=True)
    finally:
        bt._szukit_keret = _ment
    return [[str(getattr(t, m)) for m in MEZOK] for t in r.closed]


_mert = False
for sym, sn in CELLAK:
    if sym not in (cfg.get("pairs") or {}):
        continue
    if not (ROOT / "data" / "m1" / f"{sym}.parquet").exists():
        continue
    set_active_strategy(sn)
    st = get_strategy_by_name(sn)
    pf = params_file(sym, sn)
    base = (json.loads(pf.read_text(encoding="utf-8")).get("params") or {}) if pf.exists() \
        else (default_params(st, cfg) or {})
    if not base:
        continue
    prm = {**base, **load_execution_params(sym, cfg)}
    df15, df1 = bt.load_data(sym)
    if df15 is None:
        continue
    _mert = True

    wu15 = st.bt_warmup(prm, st.timeframes()[0].label)
    # 1. A MOTOR vágása vs. a TELJES keret — ugyanaz a bemenet, a szűkítő ki/be.
    teljes = _kotesek(sym, st, prm, df15, df1, vagas=False)
    vagott = _kotesek(sym, st, prm, df15, df1, vagas=True)
    check(f"{sym}/{sn}: a motor keret-szűkítése BITRE ugyanazt adja",
          teljes == vagott,
          f"teljes {len(teljes)} kötés ({len(df15)} bar) vs vágott {len(vagott)} "
          f"(warmup {wu15})")
    check(f"{sym}/{sn}: ...és volt mit összevetni", len(teljes) > 0,
          f"{len(teljes)} kötés")
    # 2. ...és a szűkítő TÉNYLEG kisebb keretet ad (nem néma no-op).
    _v15, _v1 = bt._szukit_keret(df15, df1, prm, st, TOL, IG)
    check(f"{sym}/{sn}: a szűkítő tényleg vág", len(_v15) < len(df15),
          f"{len(df15)} → {len(_v15)} M15 bar")

if not _mert:
    print("SKIP  nincs éles adat/config — a teszt nem mérhető")

jo = sum(results)
print(f"\n{jo}/{len(results)} teszt PASS")
sys.exit(0 if jo == len(results) else 1)
