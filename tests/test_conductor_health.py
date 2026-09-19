"""KARMESTER F1 — egeszsegor es kronika.

⚠ MIT KERES AZ EGESZSEGOR. Nem hibat: a hiba hangos, elszall, naploz. Azokat az
allapotokat keresi, amikben a program ugy nez ki, mintha rendben volna, kozben
nem — ez a projekt visszatero, legdragabb hibaosztalya.

⚠ ES MIERT KELL A KRONIKA MAR MOST. A terv szerint az onallosag (L3/L4) csak
akkor adhato meg, ha a dontesek utolag SZAMONKERHETOK. Egy onalloan dolgozo
reteg, aminek nincs nyoma, nem hibazik kevesebbet — csak kideritetlenul.

⚠ A TESZT SOHA NEM NYUL A VALODI `data/`-hoz.
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
from conductor import journal as jr
from conductor import config as ccfg
from conductor import report as rep
from conductor.policies import health as H
from core.overview import SEV_INFO, SEV_RISK, SEV_WARN

TMP = Path(tempfile.mkdtemp(prefix="tf_f1_"))
cp.DIR = TMP / "conductor"
_CSV = TMP / "trades.csv"
cp.trades_csv = lambda: _CSV
tl.FLUSH_SEC = 0.0
import core.params_store as ps
ps.PARAMS_DIR = TMP / "params"
(ps.PARAMS_DIR / "wpr_sma").mkdir(parents=True, exist_ok=True)

NOW = dt.datetime.now(dt.timezone.utc)
COLS = ["time", "event", "strategy", "symbol", "direction", "lot", "price",
        "sl", "tp", "ticket", "magic", "pnl_usd"]


def _naplo(sorok):
    with open(_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in sorok:
            w.writerow(r)


def _cfg(run="live", mode=None):
    pc = {"enabled": True, "strategies": ["wpr_sma"], "run_state": {"wpr_sma": run}}
    if mode:
        pc["strategy_mode"] = {"wpr_sma": mode}
    return {"optimizer": {"test_start_date": "2026-01-01"},
            "pairs": {"EURUSD": pc}}


def _mentett(trades=120, at="2026-03-02T00:00:00+00:00"):
    (ps.PARAMS_DIR / "wpr_sma" / "EURUSD.json").write_text(json.dumps({
        "params": {"x": 1}, "optimized_at": at,
        "test_summary": {"trades": trades, "profit_factor": 1.5,
                         "win_rate": 0.45, "max_drawdown": 0.1}}), encoding="utf-8")


def _kodok(cfg, **kw):
    return {f["code"] for f in H.findings(cfg, strategies_of=lambda s: ["wpr_sma"], **kw)}


# ══ 1. KOZPONTI KUSZOBOK ════════════════════════════════════════════════
k = ccfg.health({})
check("a kuszoboknek van alapertelmezese", k["dried_up_ratio"] == 0.25 and k["silent_days"] == 5)
k2 = ccfg.health({"conductor": {"health": {"dried_up_ratio": 0.9}}})
check("...es configbol felulirhatok", k2["dried_up_ratio"] == 0.9)
check("...de ISMERETLEN kulcs nem szivarog be",
      "nincsilyen" not in ccfg.health({"conductor": {"health": {"nincsilyen": 1}}}))
# ⚠ A `_comment*` kulcsok DOKUMENTACIOK a configban (a projekt konvencioja),
# nem beallitasok.
check("...es a _comment kulcs sem",
      "_comment_x" not in ccfg.health({"conductor": {"health": {"_comment_x": "..."}}}))


# ══ 2. ELSZARADAS ═══════════════════════════════════════════════════════
# ⚠ EZ A LEGGYAKORIBB NEMA BAJ: fut, nem blokkolja semmi, nem is veszit —
# egyszeruen nem kot. A mai feluleten SEHOL nem latszik.
_mentett(trades=120)                       # 2 kotes/nap igeret (60 napos ablak)
_naplo([{"time": (NOW - dt.timedelta(days=5)).isoformat(), "event": "close",
         "strategy": "wpr_sma", "symbol": "EURUSD", "ticket": 1, "pnl_usd": 4.0}])
tl.reset_for_test()
check("az elszaradt cella LELET", "dried_up" in _kodok(_cfg()))

# ...de a LEALLITOTT cellara nem: nem baj, ha egy megallitott par nem kot.
check("leallitott cellara NINCS elszaradas-lelet",
      "dried_up" not in _kodok(_cfg(run="stopped")))

# ⚠ FRISS CELLARA SEM: egy most inditott par nehany nap alatt jogosan nem hozza
# a havi atlagot — ott az „elszaradt" hamis riasztas volna.
check("rovid ablakon NINCS elszaradas-lelet (friss cella)",
      "dried_up" not in _kodok(_cfg(), days=7))

# Mentett meres nelkul nincs mihez merni.
(ps.PARAMS_DIR / "wpr_sma" / "EURUSD.json").unlink()
check("mentett meres nelkul NINCS elszaradas-lelet", "dried_up" not in _kodok(_cfg()))
_mentett(trades=120)


# ══ 3. KAPU-FAL ═════════════════════════════════════════════════════════
tl.reset_for_test()
for i in range(5):
    tl.record("EURUSD", "wpr_sma", "BUY", tl.GATE, gates_blocked=["spread"], bar_ts=i)
_k = _kodok(_cfg())
check("a mindent blokkolo kapu LELET", "gate_wall.spread" in _k, str(sorted(_k)))

# ⚠ HA VOLT KOTES, NINCS FAL: a kapu szurt, de a cella dolgozott.
tl.record("EURUSD", "wpr_sma", "BUY", tl.ENTERED, bar_ts=99)
check("kotes mellett NINCS kapu-fal lelet", "gate_wall.spread" not in _kodok(_cfg()))

# ⚠ KEVES JELBOL ZAJ: 2 jel nem „fal".
tl.reset_for_test()
for i in range(2):
    tl.record("EURUSD", "wpr_sma", "BUY", tl.GATE, gates_blocked=["spread"], bar_ts=500 + i)
check("keves jelbol NINCS kapu-fal lelet", "gate_wall.spread" not in _kodok(_cfg()))


# ══ 4. NEMA SOROZAT — a MOTOR FUTOTT napjaibol ══════════════════════════
# ⚠ MIERT NEM A NAPTARBOL. Hetvegen, unnepnapon es leallas alatt MINDEN cella
# nema — ezekbol sorozatot szamolni hamis riasztasok sorozata volna. Egy nap
# akkor szamit, ha a napi fajlban VOLT jel (barmelyik cellanal).
tl.reset_for_test()
_ma = dt.date.today()
for i in range(6):
    _nap = (_ma - dt.timedelta(days=i)).strftime("%Y-%m-%d")
    # MASIK cella jelet ad -> a motor futott azon a napon
    tl.record("GOLD", "csilla", "BUY", tl.ENTERED, bar_ts=i, day=_nap)
check("6 futo, nema nap -> LELET", "silent_days" in _kodok(_cfg()))

# Ha a kozelmultban volt jel, nincs sorozat.
tl.record("EURUSD", "wpr_sma", "BUY", tl.GATE, bar_ts=777,
          day=(_ma - dt.timedelta(days=1)).strftime("%Y-%m-%d"))
check("a kozelmultbeli jel megszakitja a sorozatot",
      "silent_days" not in _kodok(_cfg()))

# ⚠ A motor NEM futott napok nem szamitanak: ures napi fajlokbol nincs sorozat.
tl.reset_for_test()
import shutil
shutil.rmtree(cp.telemetry_dir(), ignore_errors=True)
check("a motor nelkuli napokbol NINCS sorozat", "silent_days" not in _kodok(_cfg()))


# ══ 5. A MEGLEVO DETEKTOROK BECSATORNAZASA (nem irjuk ujra oket) ════════
_k = _kodok(_cfg())
check("a config-leletek atjonnek (config_check)",
      any(c.startswith("config.") for c in _k), str(sorted(_k)))
check("a cella-leletek atjonnek (overview)",
      any(c.startswith("cell.") for c in _k), str(sorted(_k)))
# ⚠ A KODOK STABILAK: az `overview` leletei v3.77.0 ota `code`-ot is visznek —
# enelkul az ismetlodes-szures a FORDITOTT mondatra epulne, es nyelvvaltas utan
# ugyanaz a lelet ujra bekerulne a kronikaba.
from core import overview as _ov
_w = _ov.warnings(_cfg(), "EURUSD", "wpr_sma", {}, state="live")
check("minden overview-lelet visz stabil kodot",
      all(x.get("code") for x in _w), str(_w))
check("...es a kod ASCII azonosito", all(str(x["code"]).isascii() for x in _w))


# ══ 6. A MERES HIANYA IS LELET ══════════════════════════════════════════
# ⚠ Egy csendben kimarado ellenorzes ugyanazt jelenti, mint a csendben atengedo
# kapu: a felulet „minden rendben"-t mutatna, mikozben senki nem nezett oda.
check("bekotetlen strategia-lista -> LELET (nem csendes kihagyas)",
      any(c.startswith("source_error") for c in
          {f["code"] for f in H.findings(_cfg())}))

_eredeti = H._from_config_check
H._from_config_check = lambda cfg: (_ for _ in ()).throw(RuntimeError("proba"))
try:
    _k = _kodok(_cfg())
    check("elszallo forras -> source_error lelet",
          "source_error.config_check" in _k, str(sorted(_k)))
    check("...es a TOBBI ellenorzes lefut",
          any(c.startswith("cell.") or c == "dried_up" for c in _k))
finally:
    H._from_config_check = _eredeti


# ══ 7. RENDEZES ES JELENTES ═════════════════════════════════════════════
_lel = H.findings(_cfg(), strategies_of=lambda s: ["wpr_sma"])
_rangok = [H.RANK.get(f["sev"], 9) for f in _lel]
check("a leletek sulyossag szerint jonnek", _rangok == sorted(_rangok), str(_rangok))

_sorok = rep.health_lines(_lel)
check("a jelentes kiirja a darabszamot", str(len(_lel)) in _sorok[0])
# ⚠ A cella-szintu leletek szovege nem nevezi meg a cellat (a feluleten a sor
# mellett all) — egy listaban viszont hasznalhatatlan lenne.
check("a cella-szintu lelet megkapja a cimzettjet",
      any("EURUSD/wpr_sma:" in s for s in _sorok), chr(10).join(_sorok[:4]))

# ⚠ A „NINCS LELET" NEM „MINDEN RENDBEN": a frissesseg-ellenorzes MT5 nelkul a
# sajat szerzodese szerint URES listat ad.
_ures = rep.health_lines([])
check("ures leletnel is KIMONDJA a korlatot",
      len(_ures) == 1 and "nem ugyanaz" in _ures[0], _ures[0])


# ══ 8. KRONIKA ══════════════════════════════════════════════════════════
jr.reset_for_test()
_n1 = H.journal_new(_cfg(), _lel)
check("az uj leletek bekerulnek a kronikaba", _n1 == len(_lel), f"{_n1}/{len(_lel)}")
# ⚠ EGY FENNALLO LELET MINDEN KORBEN IGAZ. Ha minden korben sort irna, a
# kronika percenkent nőne, es a VALODI esemenyek elvesznenek benne.
check("...masodszorra egy sem (ismetlodes-szures)", H.journal_new(_cfg(), _lel) == 0)
check("repeat_days=0 -> nincs szures",
      H.journal_new({**_cfg(), "conductor": {"health": {"repeat_days": 0}}},
                    _lel) == len(_lel))

_sorok = jr.read(limit=500)
check("a kronika visszaolvashato", len(_sorok) >= len(_lel))
check("...legujabb elol", _sorok[0]["ts"] >= _sorok[-1]["ts"])
_egy = _sorok[0]
check("minden sor visz STABIL kodot ES a mondatot",
      _egy.get("code") and "text" in _egy and _egy.get("kind") == jr.KIND_HEALTH)
check("...es a napot (a miota-all-fenn kerdeshez ez kell)", _egy.get("day"))
check("szurheto fajtara", len(jr.read(limit=500, kind="nincsilyen")) == 0)
check("szurheto instrumentumra",
      all(r.get("symbol") == "EURUSD" for r in jr.read(limit=500, symbol="EURUSD")))

# ⚠ EGY SERULT SOR NE VIGYE EL A TOBBIT: a kronika az a fajl, amibol utolag
# rekonstrualnank, mi tortent.
with open(cp.journal_file(), "a", encoding="utf-8") as f:
    f.write("{ ez nem json\n")
check("a serult sor nem viszi el a kronikat", len(jr.read(limit=500)) >= len(_lel))

# Takaritas: a regi sorok kiesnek, az atiras atomikus.
with open(cp.journal_file(), "a", encoding="utf-8") as f:
    f.write(json.dumps({"ts": "2020-01-01T00:00:00+00:00", "day": "2020-01-01",
                        "kind": "health", "code": "regi"}) + "\n")
_maradt = jr.prune(keep_days=30)
check("a regi sor kitakarodik", all(r.get("code") != "regi" for r in jr.read(limit=500)))
check("...es a mai sorok megmaradnak", _maradt >= len(_lel))
check("...temp fajl nem marad utana",
      not list(cp.DIR.glob("*.tmp")), str(list(cp.DIR.glob("*.tmp"))))


# ══ 9. A PARANCS a KOZOS retegben ═══════════════════════════════════════
from core import console_cmd as cc
from core import telegram_cmd as tc
check("a `health` parancs be van jegyezve", "health" in cc.COMMANDS)
check("...es szerepel a sugoban", any(n == "health" for n, _k in cc._HELP))
check("a `health` ELERHETO Telegramon (csak olvas)", "health" in tc.ENGEDETT)
_ctx = cc.Context(cfg=_cfg(), save_config=lambda: True, positions=list,
                  close_position=lambda t: False, account=dict, dashboard={},
                  instrument_state={}, strategies_of=lambda s: ["wpr_sma"])
_r = cc.dispatch(_ctx, "health")
check("a parancs valaszol", bool(_r.lines), str(_r.lines[:1]))


# ══ 10. A MOTOR BEKOTESE — forras-szintu orzes ══════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor ORANKENT vizsgal (nem koronkent)",
      "time.time() - _last_health >= 3600" in _lt)
check("...es a lelet a KRONIKABA megy", "_chealth.journal_new(cfg, _lel)" in _lt)
# ⚠ A MERES SOHA NEM ALLITHATJA MEG A KERESKEDEST.
check("...vedve van", "karmester-egészségőr: a kör kimaradt" in _lt)
check("indulaskor a kronika is takarodik", "_cjrn.prune(" in _lt)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
