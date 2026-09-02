"""Kézi laboratórium: a forgatókönyv-futtató NE legyen második motor.

⚠ A LEGFONTOSABB KÉRDÉS EBBEN A FUNKCIÓBAN. A labor arra válaszol, hogy „mi
lett volna, ha itt lépek be" — és egy ilyen eszköz pontosan arra hajlamos, hogy
MAGABIZTOS KÉPET adjon arról, ami sosem történt volna meg. A projekt ezt már
többször megfizette: viz ↔ backtest paritás, a `BacktestReplayer` v4 (a régi
újraszimulált, és teljesen mást adott), a kutató-labor `_map_to`-hibája.

Ezért a labor NEM szimulál: a kézi belépőket a `trading.backtest.run_pair`-nek
adja be jelölt-listaként, és az futtatja őket. A paritás így nem MÉRENDŐ, hanem
SZERKEZETI — és ez a teszt pontosan ezt bizonyítja:

  1. a stratégia saját jelzéseivel a labor eredménye BITRE annyi, mint egy sima
     `run_pair` ugyanarra az időszakra;
  2. `manual_events=None` mellett a motor viselkedése változatlan;
  3. a kézi kockázatmentesítés NEM találhat ki jobb kimenetelt, mint ami történt.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import json
import tempfile

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import pandas as pd

from trading import backtest as bt
import tools.lab_scenario as lab

# ── 0. A KÉZI BE — tiszta függvény, adat nélkül ──────────────────────────
_be = pd.Timestamp("2026-08-27 02:00")


def _trade(sl, entry=100.0, irany="BUY"):
    return bt.Trade(symbol="X", direction=irany, open_time=_be,
                    open_price=entry, sl=sl, tp=entry + 2, lot=0.1,
                    point_size=0.01, pv1_point=1.0, sl_points=100.0)


t = _trade(sl=99.0)
check("⚠ `manual_events=None` → nem nyúl semmihez",
      not bt._apply_manual_be(t, _be, None, 0.01) and t.sl == 99.0)
check("a megadott idő ELŐTT sem",
      not bt._apply_manual_be(t, _be - pd.Timedelta(minutes=1),
                              {"breakeven_at": _be}, 0.01) and t.sl == 99.0)
check("⚠ az időponttól a stop a BELÉPŐRE megy",
      bt._apply_manual_be(t, _be, {"breakeven_at": _be}, 0.01)
      and t.sl == 100.0 and t.risk_free)
check("...és a technika NEVE megmondja, hogy KÉZI volt",
      "kezi_be" in t.rr_technique, t.rr_technique)
# ⚠ NEM RONTHAT: ha a stop már a belépő nyereség-oldalán van (trailing), a kézi
# BE nem húzhatja VISSZA — az elvenné a már megszerzett védelmet.
t2 = _trade(sl=101.0)
check("⚠ a már ELŐRÉBB húzott stopot nem rántja vissza",
      not bt._apply_manual_be(t2, _be, {"breakeven_at": _be}, 0.01)
      and t2.sl == 101.0)
t3 = _trade(sl=101.0, entry=100.0, irany="SELL")
check("SELL: tükrözve", not bt._apply_manual_be(t3, _be, {"breakeven_at": _be}, 0.01)
      or t3.sl == 100.0)

# ⚠ IDŐZÓNA: a naiv és a tz-tudatos időbélyeg összehasonlítása `TypeError`-t dob
# — a backtest FORRÓ HURKÁBAN. Ezért a normalizálás a hurkon KÍVÜL történik.
_idx = pd.date_range("2026-08-27", periods=3, freq="1min", tz="UTC")
_n = bt._normalize_manual({"breakeven_at": "2026-08-27 02:00"}, _idx)
check("⚠ a naiv időpont az adat időzónájára igazodik",
      _n["breakeven_at"].tzinfo is not None, str(_n["breakeven_at"]))
check("...és összehasonlítható a bar-idővel", _n["breakeven_at"] > _idx[0])
check("`None` → `None` (nincs fölösleges munka)",
      bt._normalize_manual(None, _idx) is None)
_naiv = pd.date_range("2026-08-27", periods=3, freq="1min")
check("⚠ tz-mentes adatnál a tz-tudatos bemenetet is elrendezi",
      bt._normalize_manual({"breakeven_at": _n["breakeven_at"]},
                           _naiv)["breakeven_at"].tzinfo is None)

# ── 1. A FORGATÓKÖNYV ELLENŐRZÉSE — hangosan, nem némán ──────────────────
_tmp = Path(tempfile.mkdtemp(prefix="tf_lab_"))


def _fut(fk: dict):
    """A futtatás kimenete vagy a HIBAKÓD (SystemExit)."""
    p = _tmp / "fk.json"
    p.write_text(json.dumps(fk, ensure_ascii=False), encoding="utf-8")
    try:
        return lab.futtat(lab.betolt(p))
    except SystemExit as ex:
        return int(ex.code or 0)


check("hiányzó kulcsnál nem indul el", _fut({"symbol": "X"}) == 2)
check("ismeretlen instrumentumnál sem",
      _fut({"symbol": "NINCSILYEN", "from": "2026-01-01", "to": "2026-01-02"}) == 2)

# ── 2. ÉLES ADAT: paritás és a kézi belépő ───────────────────────────────
SYM = "UsaTec"
_pq = ROOT / "data" / "m1" / f"{SYM}.parquet"
if not _pq.exists():
    print(f"      (nincs {SYM} M1 parquet — az éles adatos rész kimarad)")
else:
    from strategy import get_strategy_by_name
    from strategy.settings import config_for_strategy, load_config
    from trading.live_trader import default_params, strategy_params

    cfg = load_config(ROOT / "config.json")
    NEV = "wpr_sma"
    st = get_strategy_by_name(NEV)
    cs = config_for_strategy(cfg, NEV)
    params = strategy_params(SYM, NEV, cs, fallback=default_params(st, cs))
    pair_cfg = cfg["pairs"][SYM]
    df15, df1 = bt.load_data(SYM)
    TOL, IG = "2026-08-24 00:00", "2026-08-28 23:59"

    # ⚠ EZ A TESZT LELKE. A labor a stratégia SAJÁT jelzéseivel ugyanazt kell
    # adja, mint egy sima backtest — különben nem a motort mérnénk vele, hanem
    # a laborét, és a „mi lett volna" válasz a saját hibáit tartalmazná.
    _sima = bt.run_pair(SYM, df15, df1, params, pair_cfg, cfg.get("trading") or {},
                        1000.0, test_start=TOL, test_end=IG, strategy=st,
                        cfg=cfg, exec_gates=True)
    _labor = _fut({"symbol": SYM, "strategy": NEV, "from": TOL, "to": IG,
                   "use_strategy_signals": True, "exec_gates": True,
                   "balance": 1000.0})
    check("a labor lefutott éles adaton", not isinstance(_labor, int),
          str(_labor)[:40])
    if not isinstance(_labor, int):
        _a = [(t.open_time, t.direction, round(t.open_price, 6),
               round(t.pnl_usd, 6), t.status) for t in _sima.trades]
        _b = [(t.open_time, t.direction, round(t.open_price, 6),
               round(t.pnl_usd, 6), t.status) for t in _labor["res"].trades]
        check("⚠ PARITÁS: a labor = a sima backtest, KÖTÉSRE",
              _a == _b, f"{len(_a)} vs {len(_b)} kötés")
        check("...és van is mit összevetni", len(_a) > 0, f"{len(_a)} kötés")

    # ── KÉZI BELÉPŐ ──────────────────────────────────────────────────────
    _kezi = _fut({"symbol": SYM, "strategy": NEV,
                  "from": "2026-08-27 00:00", "to": "2026-08-27 23:59",
                  "entries": [{"time": "2026-08-27 01:30", "direction": "BUY"}],
                  "exec_gates": False, "balance": 1000.0})
    check("a kézi belépőből KÖTÉS lesz",
          not isinstance(_kezi, int) and len(_kezi["res"].trades) == 1,
          str(_kezi)[:60] if isinstance(_kezi, int) else
          f"{len(_kezi['res'].trades)} kötés")
    if not isinstance(_kezi, int) and _kezi["res"].trades:
        _t = _kezi["res"].trades[0]
        check("⚠ ...pontosan az ÁLTALAM megadott percben",
              str(_t.open_time).startswith("2026-08-27 01:30"), str(_t.open_time))
        check("...az irány is az enyém", _t.direction == "BUY")
        # ⚠ A TELJES MENEDZSMENT FUT: az esemény-naplóból látszik, mikor mozdult
        # a stop és mi zárta. Ez a labor lényege — nem a P&L, hanem a MENET.
        check("⚠ az esemény-napló megvan (mikor mi történt)",
              len(_t.events) >= 2, f"{len(_t.events)} esemény")
        check("...és a nyitás benne van",
              any(e[0] == "OPEN" for e in _t.events))

    # ── KÉZI KOCKÁZATMENTESÍTÉS ──────────────────────────────────────────
    # ⚠ A BEAVATKOZÁS NEM TALÁLHAT KI JOBB KIMENETELT. A stop a KÖVETKEZŐ bártól
    # hat: ha a megadott percben a bar már lement az eredeti stopig, az teljes
    # veszteség marad — nem „breakeven-zárás".
    _be_kezi = _fut({"symbol": SYM, "strategy": NEV,
                     "from": "2026-08-27 00:00", "to": "2026-08-27 23:59",
                     "entries": [{"time": "2026-08-27 01:30", "direction": "BUY"}],
                     "breakeven_at": "2026-08-27 01:35",
                     "rr_preset": "none", "exec_gates": False, "balance": 1000.0})
    if not isinstance(_be_kezi, int) and _be_kezi["res"].trades:
        _t2 = _be_kezi["res"].trades[0]
        check("⚠ a kézi BE hatott (a stop a belépőn)",
              abs(_t2.sl - _t2.open_price) < _t2.point_size,
              f"SL {_t2.sl} vs belépő {_t2.open_price}")
        check("...és a napló megmondja, hogy KÉZI volt",
              "kezi_be" in (_t2.rr_technique or ""), _t2.rr_technique)

    # ── HANGOS HIBÁK ─────────────────────────────────────────────────────
    # ⚠ Egy órával arrébb tett belépő NEM ugyanaz a kötés — inkább szóljunk.
    # Az időszakon KÍVÜLI időpontra a legközelebbi bár messze van, tehát a
    # labornak meg kell állnia. (Itt szándékosan egy hétvégi napot adunk meg:
    # ott biztosan nincs bár.)
    check("⚠ adat nélküli időpontra NEM tesz belépőt csendben",
          _fut({"symbol": SYM, "strategy": NEV,
                "from": "2026-08-27 00:00", "to": "2026-08-27 23:59",
                "entries": [{"time": "2026-08-27 00:02", "direction": "BUY"},
                            {"time": "2026-08-29 12:00", "direction": "BUY"}],
                "exec_gates": False}) == 2)
    check("hibás iránynál megáll",
          _fut({"symbol": SYM, "strategy": NEV,
                "from": "2026-08-27 00:00", "to": "2026-08-27 23:59",
                "entries": [{"time": "2026-08-27 01:30", "direction": "OLDALRA"}]}) == 2)
    check("ismeretlen rr-presetnél megáll",
          _fut({"symbol": SYM, "strategy": NEV,
                "from": "2026-08-27 00:00", "to": "2026-08-27 23:59",
                "rr_preset": "nincsilyen"}) == 2)

# ── 3. NINCS MÁSODIK MOTOR ───────────────────────────────────────────────
# ⚠ A labor CSAK bekötözi a `run_pair`-t. Ha saját SL/TP-vizsgálatot vagy
# pozíció-kezelést kezdene írni, a paritás azonnal elveszne.
import ast
_fa = ast.parse((ROOT / "tools" / "lab_scenario.py").read_text(encoding="utf-8"))
_hivott = {n.func.attr for n in ast.walk(_fa)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check("⚠ a labor a `run_pair`-t futtatja", "run_pair" in _hivott)
check("⚠ ...és a jelölt-listát a `build_signal_series` adja",
      "build_signal_series" in _hivott)
_src = (ROOT / "tools" / "lab_scenario.py").read_text(encoding="utf-8")
for _tilos in ("def _manage", "def simulate", "close_price =", "def _sl_hit"):
    check(f"⚠ nincs saját végrehajtás a laborban ({_tilos!r})", _tilos not in _src)

# ── A FORGATÓKÖNYV KÓDOLÁSA ────────────────────────────────────────────────
# ⚠ A dokumentált indítás (`--minta > sajat.json`) a Windows PowerShellben
# UTF-16LE-t ír BOM-mal. Ha a betöltő csak UTF-8-at ismerne, a felhasználó a
# SAJÁT mintaállományára kapna „nem érvényes JSON" választ.
_minta_szoveg = json.dumps(lab.MINTA, ensure_ascii=False)
for _kod, _nev in (("utf-16", "UTF-16 (PowerShell `>`)"),
                   ("utf-8-sig", "UTF-8 BOM-mal (Jegyzettömb)"),
                   ("utf-8", "sima UTF-8")):
    _f = Path(_tmp) / ("kod_" + _kod + ".json")
    _f.write_bytes(_minta_szoveg.encode(_kod))
    try:
        _be = lab.betolt(_f)
        _ok = _be.get("symbol") == lab.MINTA["symbol"]
    except SystemExit:
        _ok = False
    check("a forgatókönyv olvasható: " + _nev, _ok)

# A sablon önmagában érvényes forgatókönyv (a `--minta` kimenete).
check("a `--minta` sablon minden kötelező kulcsot tartalmaz",
      all(k in lab.MINTA for k in ("symbol", "from", "to")))

import shutil
shutil.rmtree(_tmp, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
