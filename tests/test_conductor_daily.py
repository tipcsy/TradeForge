"""KARMESTER F1 — napi riport (az esti Telegram-uzenet karmester-szakaszai).

⚠ EGY ESTI UZENET, NEM KETTO. A napi osszefoglalo mar ma is megy
(`notify.daily_summary_time`), es a `cmd_today` adja a tartalmat. Egy MASODIK
esti uzenet versenyezne az elsovel a figyelemert, es a ketto elobb-utobb mast
mondana ugyanarrol a naprol — ez a projekt visszatero hibaosztalya.

⚠ ES A RIPORT A KRONIKABOL OLVAS, nem futtatja ujra az egeszsegort: ha 23:00-kor
ujraszamolna, a MOSTANI allapotot mutatna, ami elterhet attol, ami napkozben a
kronikaba kerult — es utolag nem lehetne eldonteni, melyik az igaz.
"""
import csv
import datetime as dt
import shutil
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
from conductor import journal as jr
from conductor import report as rep
from core import console_cmd as cc
from core import telegram_cmd as tc
from core.overview import SEV_WARN

TMP = Path(tempfile.mkdtemp(prefix="tf_rep_"))
cp.DIR = TMP / "conductor"
_CSV = TMP / "trades.csv"
cp.trades_csv = lambda: _CSV
tl.FLUSH_SEC = 0.0
COLS = ["time", "event", "strategy", "symbol", "direction", "lot", "price",
        "sl", "tp", "ticket", "magic", "pnl_usd"]
with open(_CSV, "w", newline="", encoding="utf-8") as f:
    csv.DictWriter(f, fieldnames=COLS).writeheader()

CFG = {"pairs": {"BTCUSD": {"enabled": True, "strategies": ["wpr_sma"],
                            "run_state": {"wpr_sma": "live"}},
                 "EURUSD": {"enabled": True, "strategies": ["wpr_sma"],
                            "run_state": {"wpr_sma": "live"}}}}
_SOF = lambda s: ["wpr_sma"]


def _sorok():
    return rep.daily_lines(CFG, strategies_of=_SOF)


def _szoveg():
    return chr(10).join(_sorok())


# ══ 1. ⚠ A TELJESEN NEMA NAP: nem allitunk olyat, amit nem merunk ═══════
# Egy ures napi fajl KET dolgot jelenthet: zart piac (hetvege/unnep), vagy allo
# motor. A telemetria csak JELRE ir, tehat a kettot nem tudja megkulonboztetni —
# es egy magabiztos „a motor nem futott" pont az a fajta hazug allitas, amit a
# projekt mindenhol kigyomlal.
tl.reset_for_test()
shutil.rmtree(cp.telemetry_dir(), ignore_errors=True)
_sz = _szoveg()
check("nema napon KIMONDJA, hogy nem tudja megkulonboztetni",
      "nem tudja megkülönböztetni" in _sz, _sz[:90])
check("...es NEM allitja, hogy a motor allt",
      "a motor ma nem futott." not in _sz)
# ⚠ „Nincs adat" ≠ „nem tortent semmi".
check("...de azt sem allitja, hogy minden rendben",
      "rendben" not in _sz.split("Leletek")[0])


# ══ 2. HETVEGE: csak a kripto el ════════════════════════════════════════
# A mai (2026-09-19, szombat) helyzet: a devizaparok alszanak, a BTCUSD megy.
# A puszta „3 jel" ilyenkor felrevezeto — ugy nezne ki, mintha az EGESZ rendszer
# csendes volna, pedig csak a piac zart.
tl.record("BTCUSD", "wpr_sma", "BUY", tl.ENTERED, bar_ts=1)
tl.record("BTCUSD", "wpr_sma", "SELL", tl.GATE, gates_blocked=["spread"], bar_ts=2)
tl.record("BTCUSD", "wpr_sma", "BUY", tl.NO_SLOT, bar_ts=3)
_sz = _szoveg()
check("a jel -> kotes arany latszik", "3 jel" in _sz and "1 kötés" in _sz, _sz[:80])
check("⚠ ...es hogy MELY instrumentum volt ebren",
      "BTCUSD" in _sz and "ébren" in _sz, _sz)
check("a fo akadalyok nevesitve vannak",
      "belépő-kapu" in _sz and "slot" in _sz)
# A nap cimkezve: ket „ma" talalkozik az uzenetben (helyi vs broker nap).
check("a karmester szakasza KIIRJA, melyik naprol beszel",
      tl.day_key() in _sz, tl.day_key())


# ══ 3. A JELZETT, DE NEM KOTOTT cellak kulon ════════════════════════════
tl.reset_for_test()
shutil.rmtree(cp.telemetry_dir(), ignore_errors=True)
tl.record("EURUSD", "wpr_sma", "BUY", tl.GATE, gates_blocked=["spread"], bar_ts=10)
tl.record("BTCUSD", "wpr_sma", "BUY", tl.ENTERED, bar_ts=11)
_sz = _szoveg()
check("a jelzett-de-nem-kotott cella nevesitve van",
      "EURUSD/wpr_sma" in _sz and "nem kötött" in _sz, _sz)
check("...a koto cella viszont NEM kerul abba a sorba",
      "BTCUSD/wpr_sma" not in _sz.split("nem kötött")[1].split(chr(10))[0])


# ══ 4. LELETEK es ARNYEK a KRONIKABOL ═══════════════════════════════════
jr.reset_for_test()
check("kronika nelkul kimondja, hogy ma nem kerult uj lelet",
      "nem került új lelet" in _szoveg())

jr.write(jr.KIND_HEALTH, "dried_up", "GOLD/csilla: ELSZÁRADT — ...",
         sev=SEV_WARN, symbol="GOLD", strategy="csilla")
jr.write(jr.KIND_SHADOW, "set_mode_signal:degraded",
         "GOLD/csilla: ÉLŐ → papír javasolt", sev="info", symbol="GOLD",
         strategy="csilla", data={"needs_human": False})
jr.write(jr.KIND_SHADOW, "set_mode_live:paper_proven",
         "EURUSD/wpr_sma: papír → ÉLŐ javasolt", sev="info", symbol="EURUSD",
         strategy="wpr_sma", data={"needs_human": True})
_sz = _szoveg()
check("a mai leletek megjelennek", "ELSZÁRADT" in _sz)
check("az arnyek-javaslatok megjelennek", "papír javasolt" in _sz)
# ⚠ ES KIMONDJUK, HOGY NEM HAJTODTAK VEGRE: egy javaslatlista, amirol ez nem
# derul ki, azt sugallja, hogy a rendszer mar lepett.
check("⚠ kimondja, hogy a javaslatok NEM hajtodtak vegre",
      "NEM hajtódtak végre" in _sz, _sz)
# A penzt bekapcsolo javaslat megjelolve.
check("a penzt bekapcsolo javaslat meg van jelolve",
      any("⚠" in s and "papír → ÉLŐ" in s for s in _sorok()))

# ⚠ A TEGNAPI sorok NEM kerulnek a MAI riportba.
jr.write(jr.KIND_HEALTH, "regi", "tegnapi lelet", sev=SEV_WARN)
import json as _json
_ut = cp.journal_file()
_nyers = _ut.read_text(encoding="utf-8").splitlines()
_nyers[-1] = _json.dumps({**_json.loads(_nyers[-1]), "day": "2020-01-01"},
                         ensure_ascii=False)
_ut.write_text(chr(10).join(_nyers) + chr(10), encoding="utf-8")
check("a regi kronika-sor NEM kerul a mai riportba", "tegnapi lelet" not in _szoveg())

# Sok lelet -> levagas, de a darabszam latszik.
for i in range(12):
    jr.write(jr.KIND_HEALTH, f"proba_{i}", f"lelet-{i}", sev=SEV_WARN)
_sz = _szoveg()
check("sok leletnel levagja a listat, de kimondja, hany maradt",
      "és még" in _sz, [s for s in _sorok() if "még" in s])


# ══ 5. A RIPORT = MAI NAP + KARMESTER ═══════════════════════════════════
_ctx = cc.Context(cfg=CFG, save_config=lambda: True, positions=list,
                  close_position=lambda t: False, account=dict, dashboard={},
                  instrument_state={}, strategies_of=_SOF,
                  today_rows=lambda: [{"event": "close", "symbol": "BTCUSD",
                                       "strategy": "wpr_sma", "pnl_usd": 12.0}])
_r = cc.cmd_report(_ctx, [])
_sz = chr(10).join(_r.lines)
check("a riport tartalmazza a mai napot (cmd_today)", "12.00" in _sz, _sz[:80])
check("...ES a karmester szakaszait", "KARMESTER" in _sz)

# ⚠ A karmester szakasza SOHA nem viheti el a napi osszefoglalot: a kotesek es
# az eredmeny akkor is kimennek, ha a meres elakadt.
_eredeti = rep.daily_lines
rep.daily_lines = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("proba"))
try:
    _r2 = cc.cmd_report(_ctx, [])
    check("⚠ elszallo karmester-szakasz mellett is kimegy a napi osszefoglalo",
          "12.00" in chr(10).join(_r2.lines), str(_r2.lines[:2]))
finally:
    rep.daily_lines = _eredeti


# ══ 6. AZ ESTI UZENET es a PARANCS ══════════════════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("az esti uzenet a RIPORTOT kuldi (nem csak a `today`-t)",
      "_cc.cmd_report(_ctx, []).lines" in _lt)
check("a `report` parancs be van jegyezve", "report" in cc.COMMANDS)
check("...es szerepel a sugoban", any(n == "report" for n, _k in cc._HELP))
check("a `report` ELERHETO Telegramon (csak olvas)", "report" in tc.ENGEDETT)
# ⚠ A `mode` tovabbra sem: az penzt kapcsolna be egy chatuzenetbol.
check("⚠ a `mode` tovabbra sem", "mode" not in tc.ENGEDETT)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
