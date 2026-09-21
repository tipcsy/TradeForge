"""KARMESTER F0 — elo gordulo teljesitmeny, vart aktivitas, pillanatkep, jelentes.

A telemetria (`test_conductor_telemetry.py`) megmondja, MI akadalyozta a belepot.
Ez a harom darab azt teszi hozza, hogy MIHEZ KEPEST keves — enelkul a
leggyakoribb nema baj (a cella ELSZARADT: nem blokkolja semmi, nem is veszit,
egyszeruen nem kot) eszrevetlen marad.

⚠ A TESZT SOHA NEM NYUL A VALODI `data/`-hoz es a valodi `trades.csv`-hez.
"""
import csv
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.WARNING)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from conductor import paths as cp
from conductor import telemetry as tl
from conductor import metrics as met
from conductor import expectation as exp
from conductor import snapshot as snap
from conductor import report as rep

TMP = Path(tempfile.mkdtemp(prefix="tf_f0_"))
cp.DIR = TMP / "conductor"
_CSV = TMP / "trades.csv"
cp.trades_csv = lambda: _CSV          # a modulok ezen a modulon at kerdezik
tl.FLUSH_SEC = 0.0
NOW = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
COLS = ["time", "event", "strategy", "symbol", "direction", "lot", "price",
        "sl", "tp", "ticket", "magic", "pnl_usd"]


def _naplo(sorok):
    with open(_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in sorok:
            w.writerow(r)


def _zaras(napja, pnl, sym="EURUSD", strat="wpr_sma", event="close"):
    return {"time": (NOW - dt.timedelta(days=napja)).isoformat(), "event": event,
            "strategy": strat, "symbol": sym, "ticket": 1000 + napja,
            "pnl_usd": pnl}


# ══ 1. ELO GORDULO TELJESITMENY ══════════════════════════════════════════
_naplo([_zaras(1, 20.0), _zaras(2, -10.0), _zaras(3, 30.0), _zaras(4, -10.0),
        _zaras(200, 999.0)])                    # az ablakon KIVUL
m = met.cell("EURUSD", "wpr_sma", days=90, now=NOW)
check("csak az ABLAKON BELULI kotesek szamitanak", m["trades"] == 4, str(m["trades"]))
check("a PF a brutto nyereseg / brutto veszteseg",
      m["profit_factor"] == 2.5, str(m["profit_factor"]))
check("a nettó es a talalati arany egyezik",
      m["net"] == 30.0 and m["win_rate"] == 0.5, f"{m['net']} / {m['win_rate']}")
check("az expectancy a nettó / kotesszam", m["expectancy"] == 7.5, str(m["expectancy"]))

# ⚠ A VEGTELEN PF NEM PF. Veszteseg nelkul a hanyados ERTELMEZHETETLEN — egy
# „PF = ∞" a rangsorban minden mast megverne, pedig epp azt jelenti, hogy nincs
# eleg adat.
_naplo([_zaras(1, 5.0), _zaras(2, 7.0)])
check("veszteseg nelkul a PF None (nem vegtelen)",
      met.cell("EURUSD", "wpr_sma", days=90, now=NOW)["profit_factor"] is None)

# ⚠ A NULLA P&L-es kotes SEM nyero, SEM veszto — de KOTES.
_naplo([_zaras(1, 10.0), _zaras(2, 0.0), _zaras(3, -10.0)])
_m0 = met.cell("EURUSD", "wpr_sma", days=90, now=NOW)
check("a nulla eredmenyu kotes szamit kotesnek",
      _m0["trades"] == 3 and _m0["wins"] == 1 and _m0["losses"] == 1,
      f"{_m0['trades']}/{_m0['wins']}/{_m0['losses']}")
# ⚠ A modul 4 tizedesre kerekit (a szam kijelzesre es rangsorolasra megy, nem
# konyvelesre) — a teszt turese ehhez igazodik, nem forditva.
check("...es a win_rate nevezoje a TELJES darabszam",
      abs(_m0["win_rate"] - 1 / 3) < 1e-4, str(_m0["win_rate"]))

# ⚠ P&L nelkuli sor: zaj. Beszamitva a kotesszamot (es a bizonyitek-szorzot!)
# novelne, a PF-et viszont nem.
_naplo([_zaras(1, 10.0), {**_zaras(2, ""), "pnl_usd": ""},
        {**_zaras(3, "nan"), "pnl_usd": "nan"}])
check("a P&L nelkuli zaras-sor kimarad",
      met.cell("EURUSD", "wpr_sma", days=90, now=NOW)["trades"] == 1)

# A NEM zaras esemenyek (open/signal) sosem kotesek.
_naplo([_zaras(1, 10.0), _zaras(2, 0.0, event="open"), _zaras(3, 0.0, event="signal")])
check("az `open`/`signal` sor NEM kotes",
      met.cell("EURUSD", "wpr_sma", days=90, now=NOW)["trades"] == 1)

# Cellankent kulon: a masik strategia/par nem keveredik bele.
_naplo([_zaras(1, 10.0), _zaras(2, -5.0, strat="ml_ai"), _zaras(3, 7.0, sym="GOLD")])
_all = met.all_cells(days=90, now=NOW)
check("a cellak nem keverednek",
      set(_all) == {"EURUSD|wpr_sma", "EURUSD|ml_ai", "GOLD|wpr_sma"}, str(set(_all)))
check("...es egyetlen naplo-olvasasbol keszul",
      _all["EURUSD|wpr_sma"]["trades"] == 1 and _all["GOLD|wpr_sma"]["trades"] == 1)

# ⚠ BIZONYITEK-SZORZO: mert a PF kis mintan hazudik (core/quality.py merese:
# 15 kotesen egy 1,10-es strategia 4,5%-ban PF>3-at mutat).
check("a bizonyitek-szorzo 0-rol no", met.confidence(0) == 0.0)
check("...a mert kuszobon (50) 0,5", abs(met.confidence(50) - 0.5) < 1e-9)
check("...es SOSEM eri el az 1-et", met.confidence(100000) < 1.0)
check("...monoton", met.confidence(10) < met.confidence(30) < met.confidence(80))

# ⚠ A kotes/nap a KERT ablakbol szamol, nem az elso es utolso kotes kozotti
# idobol: utobbi egy elszaradt cellanal hazudna (ha 90 napbol csak az elso
# kettoben kotott, a „ket nap alatt 6 kotes" 3/nap-ot adna a valos 0,07 helyett).
_naplo([_zaras(88, 1.0), _zaras(89, 1.0)])
_m = met.cell("EURUSD", "wpr_sma", days=90, now=NOW)
check("a kotes/nap a TELJES ablakra vetit",
      abs(met.trades_per_day(_m, 90) - 2 / 90) < 1e-4,
      str(met.trades_per_day(_m, 90)))

# Hianyzo naplo: ures, de nem dob.
_CSV.unlink()
check("hianyzo naplo -> ures, nem dob", met.cell("X", "y", days=90, now=NOW)["trades"] == 0)


# ══ 2. VART AKTIVITAS ════════════════════════════════════════════════════
_PAR = TMP / "params"
(_PAR / "wpr_sma").mkdir(parents=True, exist_ok=True)
import core.params_store as ps
ps.PARAMS_DIR = _PAR

CFG = {"optimizer": {"test_start_date": "2026-01-01"},
       "pairs": {"EURUSD": {"strategies": ["wpr_sma"],
                            "run_state": {"wpr_sma": "live"}}}}

check("mentett eredmeny nelkul nincs varakozas",
      exp.expected("EURUSD", "wpr_sma", CFG, now=NOW)["source"] == "")

(_PAR / "wpr_sma" / "EURUSD.json").write_text(json.dumps({
    "params": {"x": 1},
    "optimized_at": "2026-03-02T00:00:00+00:00",     # 60 nap a test_start utan
    "test_summary": {"trades": 120, "profit_factor": 1.5, "win_rate": 0.45},
}), encoding="utf-8")
e = exp.expected("EURUSD", "wpr_sma", CFG, now=NOW)
check("a varakozas a mentett OOS meresbol jon", e["source"] == "saved")
check("az ablak a test_start_date -> optimized_at", e["window_days"] == 60,
      str(e["window_days"]))
check("a vart kotes/nap ebbol szamolodik", e["trades_per_day"] == 2.0,
      str(e["trades_per_day"]))

# ⚠ Hianyzo `optimized_at` -> a MAI napig szamolunk: az ablak HOSSZABB, a
# varakozas ALACSONYABB. Ez a biztonsagos irany — inkabb ne kialtsunk
# elszaradast ott, ahol csak a metaadat hianyzik.
(_PAR / "wpr_sma" / "EURUSD.json").write_text(json.dumps({
    "test_summary": {"trades": 120}}), encoding="utf-8")
_e2 = exp.expected("EURUSD", "wpr_sma", CFG, now=NOW)
check("hianyzo optimized_at -> hosszabb ablak, ALACSONYABB varakozas",
      _e2["window_days"] > 60 and _e2["trades_per_day"] < 2.0,
      f"{_e2['window_days']} nap / {_e2['trades_per_day']}")


# ══ 3. ELTERES — ARANYOKON, SOSEM PENZBEN ════════════════════════════════
# ⚠ A backtest P&L-je NEM vetheto ossze az elo P&L-lel abszolut ertekben: a
# meretezes az AKKORI egyenleghez igazodott. Ezert az eltereshez PENZ-mezo nem
# tartozhat — ha valaki felvenne egyet, ebbol rossz dontesek szuletnenek.
d = exp.divergence({"trades_per_day": 1.0, "profit_factor": 1.2, "trades": 60},
                   {"trades_per_day": 2.0, "profit_factor": 1.5})
check("az aktivitas-arany elo/vart", d["activity_ratio"] == 0.5, str(d))
check("a PF-elteres elo - vart", abs(d["pf_delta"] + 0.3) < 1e-9, str(d["pf_delta"]))
check("⚠ az elteresben NINCS penz-mezo",
      not any(k in d for k in ("net", "pnl", "profit", "total_pnl")), str(sorted(d)))
check("eleg kotesnel az elteres ertelmezheto", d["enough"] is True)
check("⚠ keves kotesnel NEM",
      exp.divergence({"trades": 3, "trades_per_day": 1.0},
                     {"trades_per_day": 2.0})["enough"] is False)
check("nincs mentett varakozas -> nincs arany",
      exp.divergence({"trades_per_day": 1.0}, {})["activity_ratio"] is None)
check("nulla vart aktivitas -> nincs arany (nem osztunk nullaval)",
      exp.divergence({"trades_per_day": 1.0},
                     {"trades_per_day": 0.0})["activity_ratio"] is None)


# ══ 4. PILLANATKEP: a MOTOR keplete ══════════════════════════════════════
_naplo([_zaras(1, 10.0)])
tl.reset_for_test()
_ma = tl.day_key()
tl.record("EURUSD", "wpr_sma", "BUY", tl.GATE, gates_blocked=["spread"], bar_ts=1)
tl.record("EURUSD", "wpr_sma", "BUY", tl.ENTERED, bar_ts=2)

sn = snap.cell(CFG, "EURUSD", "wpr_sma", strategies_of=lambda s: ["wpr_sma"])
check("a pillanatkep egyben adja a mai merest", sn["today"]["signals"] == 2)
check("...az elo teljesitmenyt", sn["live"]["trades"] == 1)
check("...es a varakozast", sn["expected"]["source"] == "saved")
check("a `running` a MOTOR keplete (engedelyezett ES szandek=live)",
      sn["running"] is True)
check("nem engedelyezett strategia -> nem fut",
      snap.cell(CFG, "EURUSD", "wpr_sma",
                strategies_of=lambda s: [])["running"] is False)
# ⚠ Ha a listat nem tudjuk, az NEM „nem": a None es a False kulonbozo valasz.
check("⚠ bekotetlen strategia-lista -> None (nem tudjuk), nem False",
      snap.cell(CFG, "EURUSD", "wpr_sma")["running"] is None)


# ══ 5. A JELENTES ════════════════════════════════════════════════════════
_sorok = rep.why_lines(sn)
_sz = chr(10).join(_sorok)
check("a jelentes fejlece a cellat nevezi meg", "EURUSD/wpr_sma" in _sorok[0])
check("kiirja a jel -> kotes aranyt", "2 jel" in _sz and "1 kötés" in _sz, _sz[:60])
check("nevesiti a KAPUT (a 'kapu blokkolt' onmagaban nem cselekvokepes)",
      "spread" in _sz, _sz)
check("⚠ figyelmeztet a kis mintara", "zaj is lehet" in _sz)

# ⚠ „Nem volt jel" ≠ „nincs adat". A ketto osszemosasa pontosan az a nema
# allapot, ami miatt ez a meres elkeszult.
# ⚠ EGY MASIK CELLAN vizsgaljuk: a `reset_for_test` csak a MEMORIAT uriti, a mar
# kiirt napi fajl viszont megmarad — es ez helyes (lemez + memoria egyutt az
# igazsag, kulonben a jelentes egy percet kesne).
_cfg_uj = {"optimizer": CFG["optimizer"],
           "pairs": {"GBPJPY": {"strategies": ["wpr_sma"],
                                "run_state": {"wpr_sma": "live"}}}}
_sn2 = snap.cell(_cfg_uj, "GBPJPY", "wpr_sma", strategies_of=lambda s: ["wpr_sma"])
check("jel nelkul KIMONDJA, hogy nem volt jel",
      any("nem volt jel" in l for l in rep.why_lines(_sn2)),
      chr(10).join(rep.why_lines(_sn2)))

# Az ALLAPOT az elso kerdes: leallitott cellanal a kapuk magyarazata felrevezetne.
_cfg_stop = {"optimizer": CFG["optimizer"],
             "pairs": {"EURUSD": {"strategies": ["wpr_sma"],
                                  "run_state": {"wpr_sma": "stopped"}}}}
check("leallitott cellanal ezt mondja elsonek",
      any("LE VAN ÁLLÍTVA" in l for l in rep.why_lines(
          snap.cell(_cfg_stop, "EURUSD", "wpr_sma", strategies_of=lambda s: ["wpr_sma"]))))
_cfg_sig = {"optimizer": CFG["optimizer"],
            "pairs": {"EURUSD": {"strategies": ["wpr_sma"],
                                 "run_state": {"wpr_sma": "live"},
                                 "strategy_mode": {"wpr_sma": "signal"}}}}
check("csak-jelzes modnal is kimondja",
      any("jelzés" in l and "SZÁNDÉKOSAN" in l for l in rep.why_lines(
          snap.cell(_cfg_sig, "EURUSD", "wpr_sma", strategies_of=lambda s: ["wpr_sma"]))))
check("nem engedelyezett cellanal is",
      any("NINCS engedélyezve" in l for l in rep.why_lines(
          snap.cell(CFG, "EURUSD", "wpr_sma", strategies_of=lambda s: []))))


# ══ 6. A PARANCS a KOZOS retegben ═══════════════════════════════════════
from core import console_cmd as cc
from core import telegram_cmd as tc
check("a `why` parancs be van jegyezve", "why" in cc.COMMANDS)
check("...es szerepel a sugoban", any(n.startswith("why ") for n, _k in cc._HELP))
# ⚠ OLVASO parancs: nem allit semmit, nem mozgat penzt — mehet a Telegramra.
check("a `why` ELERHETO Telegramon (csak olvas)", "why" in tc.ENGEDETT)
check("⚠ ...a `mode` viszont tovabbra sem", "mode" not in tc.ENGEDETT)

_ctx = cc.Context(cfg=CFG, save_config=lambda: True, positions=list,
                  close_position=lambda t: False, account=dict, dashboard={},
                  instrument_state={}, strategies_of=lambda s: ["wpr_sma"])
_r = cc.dispatch(_ctx, "why EURUSD")
check("a parancs valaszol", _r.ok and _r.lines and "EURUSD" in _r.lines[0], str(_r.lines[:1]))
check("ismeretlen par -> beszedes hiba", not cc.dispatch(_ctx, "why NINCSILYEN").ok)
check("par nelkul -> hasznalat", not cc.dispatch(_ctx, "why").ok)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
