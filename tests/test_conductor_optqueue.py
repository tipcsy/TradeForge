"""KARMESTER F2 — fej nelkuli optimalizalas-sor.

⚠ A LELET. Az optimalizalas inditasa eddig CSAK a grafikus feluleten letezett
(OptimizerController): a konzolos es a fej nelkuli (VM, SSH) futas egyaltalan
nem tudott optimalizalast kerni, es a karmester `queue_optimize` javaslata
ezert csak TANACS lehetett.

⚠ ES KET KORLAT, AMIT A SOR NEM HAGHAT AT:
  1. KERESKEDO CELLAT NEM OPTIMALIZAL — a futas vegen a parameterfajlja irodna
     felul az alol a cella alol, amelyik epp vele kereskedik;
  2. a CPU-nehez munka ALPROCESSZBEN megy, nem a motor szalan.
"""
import datetime as dt
import sys
import tempfile
import time
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
from conductor import optqueue as oq
from conductor import config as ccfg
from conductor import report as rep
from core import opt_activity as oa

TMP = Path(tempfile.mkdtemp(prefix="tf_oq_"))
cp.DIR = TMP / "conductor"

# ⚠ A TESZT NEM INDIT VALODI OPTIMALIZALAST: a parancsot egy azonnal kilepo
# processzre csereljuk. Igy a SPAWN es a LEARATAS utja valodi (igazi
# alprocessz), de nem kell hozza MT5 es orak.
_RC = {"kod": 0}
oq._parancs = lambda sym, strat: [sys.executable, "-c", f"raise SystemExit({_RC['kod']})"]


def _cfg(run="live", parallel=1):
    return {"pairs": {"GOLD": {"enabled": True, "strategies": ["csilla"],
                               "run_state": {"csilla": run}}},
            "conductor": {"optqueue": {"max_parallel": parallel}}}


_SOF = lambda s: ["csilla"]


def _tiszta():
    """⚠ TELJES ujrakezdes: a `reset_for_test` csak a MEMORIAT uriti, a fajl
    megmarad es a kovetkezo betoltes visszaolvassa (ez helyes — a sor
    perzisztens). A teszt blokkjai kozott viszont tiszta lap kell."""
    oq.reset_for_test()
    (cp.DIR / "opt_queue.json").unlink(missing_ok=True)


def _var_befejezesre(mp=10.0):
    """A learatas addig hivodik, amig a futo tetel be nem fejezodik."""
    hatar = time.time() + mp
    while time.time() < hatar:
        st = oq.drain(_cfg(run="stopped"), strategies_of=_SOF)
        if not [e for e in oq.items() if e["state"] == oq.RUNNING]:
            return st
        time.sleep(0.05)
    return {}


# ══ 1. KERES ES ISMETLODES ══════════════════════════════════════════════
oq.reset_for_test()
_id = oq.enqueue(_cfg(), "GOLD", "csilla", source="teszt")
check("a keres sorba kerul", bool(_id) and len(oq.items()) == 1)
check("...ugyanaz a cella masodszor NEM", oq.enqueue(_cfg(), "GOLD", "csilla") is None)
check("...a tetel viszi a keres forrasat", oq.items()[0]["source"] == "teszt")


# ══ 2. ⚠ A KERESKEDO CELLAT NEM OPTIMALIZALJUK ═════════════════════════
# A futas vegen a parameterfajlja irodna felul alatta. A keplet a MOTORE
# (run_state.live_strategies): engedelyezett ES szandek=live.
check("⚠ a futo cella BLOKKOLT",
      oq.blocked_reason(_cfg(run="live"), "GOLD", "csilla", _SOF) == "cell_live")
check("...a leallitott viszont indithato",
      oq.blocked_reason(_cfg(run="stopped"), "GOLD", "csilla", _SOF) == "")
# ⚠ A „csak jelzes" modu cella is FUT (run_state=live): ott a papir-bizonyitek
# gyulik, amit egy parameter-csere ertelmetlenne tenne.
_cfg_sig = _cfg(run="live")
_cfg_sig["pairs"]["GOLD"]["strategy_mode"] = {"csilla": "signal"}
check("⚠ a papir (csak jelzes) modu cella is blokkolt",
      oq.blocked_reason(_cfg_sig, "GOLD", "csilla", _SOF) == "cell_live")
# A NEM engedelyezett strategia nem „fut" — ott nincs mit felteni.
check("a nem engedelyezett strategia nem blokkol",
      oq.blocked_reason(_cfg(run="live"), "GOLD", "csilla", lambda s: []) == "")
# Ha mar fut rajta optimalizalas (barhonnan), nem inditunk masodikat.
oa.set_state("GOLD", "csilla", oa.RUNNING)
try:
    check("a mar futo optimalizalas blokkol",
          oq.blocked_reason(_cfg(run="stopped"), "GOLD", "csilla", _SOF)
          == "already_busy")
finally:
    oa.set_state("GOLD", "csilla", None)


# ══ 3. HAJTAS: a blokkolt VAR, az OKAVAL ═══════════════════════════════
_st = oq.drain(_cfg(run="live"), strategies_of=_SOF)
check("futo cellanal semmi nem indul", _st["started"] == 0 and _st["blocked"] == 1,
      str(_st))
_e = oq.items()[0]
check("...a tetel `blocked`, es OTT AZ OK",
      _e["state"] == oq.BLOCKED and _e["reason"] == "cell_live", str(_e["reason"]))
# ⚠ A blokkolt keres NEM vesz el es nem fut le csendben — a jelentes kimondja.
_sorok = chr(10).join(rep.optq_lines(oq.items()))
check("...a jelentes megmondja, mit kell tenni",
      "Stop" in _sorok and "blokkolva" in _sorok, _sorok[:110])


# ══ 4. HAJTAS: indulas, majd learatas ══════════════════════════════════
_st = oq.drain(_cfg(run="stopped"), strategies_of=_SOF)
check("leallitott cellanal ELINDUL", _st["started"] == 1, str(_st))
_e = oq.items()[0]
check("...a tetel `running`, pid-del", _e["state"] == oq.RUNNING and _e["pid"])
# ⚠ A FELULET IS LASSA: a motor es a dashboard EGY processzben fut, tehat a
# modul-szintu opt_activity azonnal megjelenik az OPT oszlopban — kulonben a
# felhasznalo nem ertene, miert nem inditható kezzel ugyanaz a cella.
check("⚠ a felulet is latja (opt_activity)", oa.busy("GOLD", "csilla"))

_st = _var_befejezesre()
_e = oq.items()[0]
check("a befejezodott tetel learatodik", _e["state"] == oq.DONE, str(_e["state"]))
check("...a kilepesi kod rogzul", _e["rc"] == 0)
check("...es az opt_activity felszabadul", not oa.busy("GOLD", "csilla"))

# HIBAS kilepes -> `failed`, az okkal.
_RC["kod"] = 3
_tiszta()
oq.enqueue(_cfg(), "GOLD", "csilla")
oq.drain(_cfg(run="stopped"), strategies_of=_SOF)
_var_befejezesre()
_e = oq.items()[0]
check("a hibas futas `failed`", _e["state"] == oq.FAILED and _e["rc"] == 3,
      f"{_e['state']}/{_e['rc']}")
check("...az okkal egyutt", _e["reason"] == "exit_code")
_RC["kod"] = 0


# ══ 5. PARHUZAMOSSAG ═══════════════════════════════════════════════════
# ⚠ ALAPBOL EGY: az optimalizalas az ELO MOTOR MELLETT fut, hat parhuzamos
# futas elvenne a gepet a kereskedes elol.
check("alapbol EGY parhuzamos futas", ccfg.optqueue({})["max_parallel"] == 1)
_tiszta()
for _s in ("A", "B", "C"):
    oq.enqueue(_cfg(), _s, "csilla")
_cfg3 = {"pairs": {}, "conductor": {"optqueue": {"max_parallel": 2}}}
_st = oq.drain(_cfg3, strategies_of=lambda s: [])
check("a keret betartva (2)", _st["started"] == 2, str(_st))
check("...a harmadik sorban marad",
      sum(1 for e in oq.items() if e["state"] == oq.QUEUED) == 1)
while [e for e in oq.items() if e["state"] == oq.RUNNING]:
    oq.drain(_cfg3, strategies_of=lambda s: [])
    time.sleep(0.05)


# ══ 6. ⚠ A MOTOR UJRAINDULASA: elveszett allapot ═══════════════════════
# Egy orokke „fut" sor rosszabb, mint egy bevallott hiany.
_tiszta()
_id = oq.enqueue(_cfg(), "GOLD", "csilla")
oq._state[_id].update({"state": oq.RUNNING, "pid": 999999,
                       "started_at": "2020-01-01T00:00:00+00:00"})
oq._popen.clear()                       # mintha a motor ujraindult volna
oq.drain(_cfg(run="stopped"), strategies_of=_SOF)
_e = oq.items()[0]
check("⚠ a turelmi ido utan ELVESZETTNEK nyilvanitjuk",
      _e["state"] == oq.FAILED and _e["reason"] == "lost_after_restart",
      f"{_e['state']}/{_e['reason']}")
# ...de FRISS tetelt nem bantunk (hatha tenyleg fut).
_tiszta()
_id = oq.enqueue(_cfg(), "GOLD", "csilla")
oq._state[_id].update({"state": oq.RUNNING, "pid": 999999,
                       "started_at": dt.datetime.now(dt.timezone.utc).isoformat()})
oq._popen.clear()
oq.drain(_cfg(run="stopped"), strategies_of=_SOF)
check("...a FRISS tetelt viszont nem", oq.items()[0]["state"] == oq.RUNNING)


# ══ 7. TORLES ══════════════════════════════════════════════════════════
_tiszta()
_id = oq.enqueue(_cfg(), "GOLD", "csilla")
check("a varakozo tetel torolheto", oq.cancel(_id) and not oq.items())
_id = oq.enqueue(_cfg(), "GOLD", "csilla")
oq._state[_id]["state"] = oq.RUNNING
check("⚠ a FUTO tetel innen nem torolheto", not oq.cancel(_id))


# ══ 8. A JAVASLAT MOSTANTOL VEGREHAJTHATO ══════════════════════════════
from conductor import actions as act
from conductor import inbox as ib
from conductor import journal as jr
from conductor import proposals as pnew
from core import console_cmd as cc

check("⚠ a `queue_optimize` mostantol VEGREHAJTHATO",
      act.can_execute(pnew.QUEUE_OPTIMIZE))

_tiszta()
ib.reset_for_test()
jr.reset_for_test()
(cp.DIR / "inbox.json").unlink(missing_ok=True)
cfg = _cfg(run="live")
ctx = cc.Context(cfg=cfg, save_config=lambda: True, positions=list,
                 close_position=lambda t: False, account=dict, dashboard={},
                 instrument_state={}, strategies_of=_SOF)
ib.sync(cfg, [pnew.Proposal(action=pnew.QUEUE_OPTIMIZE, symbol="GOLD",
                            strategy="csilla", reason="stale_params",
                            text="avult keszlet")])
_e = ib.items(ib.PENDING)[0]
# ⚠ Az ujraervenyesites a hazirendet kerdezi; itt azt megkeruljuk, mert a
# TESZT TARGYA a vegrehajtas utja, nem a hazirend (azt a lifecycle-teszt orzi).
act.still_valid = lambda c, e: (True, e.get("code"))
_r = act.apply(ctx, _e)
check("az elfogadas SORBA ALLIT", _r.ok and len(oq.items()) == 1, str(_r.lines))
check("...es KIMONDJA, hogy nem indul, amig a cella fut",
      any("NEM INDUL" in x for x in _r.lines), str(_r.lines))
check("...a postalada-tetel `accepted`", ib.get(_e["id"])["state"] == ib.ACCEPTED)
check("...a visszaut a SOR azonositoja",
      (ib.get(_e["id"]).get("undo") or {}).get("kind") == "optqueue")
check("...es az akcio a kronikaba kerult",
      bool(jr.read(limit=3, kind=jr.KIND_ACTION)))

# Visszavonas: a VARAKOZO tetel kivehetó.
_r = act.undo(ctx, ib.get(_e["id"]))
check("a visszavonas kiveszi a sorbol", _r.ok and not oq.items(), str(_r.lines))
# ...de a FUTOT nem.
_tiszta()
ib.reset_for_test()
(cp.DIR / "inbox.json").unlink(missing_ok=True)
ib.sync(cfg, [pnew.Proposal(action=pnew.QUEUE_OPTIMIZE, symbol="GOLD",
                            strategy="csilla", reason="stale_params", text="x")])
_e = ib.items(ib.PENDING)[0]
act.apply(ctx, _e)
_qid = (ib.get(_e["id"]).get("undo") or {}).get("queue_id")
oq._state[_qid]["state"] = oq.RUNNING
_r = act.undo(ctx, ib.get(_e["id"]))
check("⚠ a FUTO optimalizalas innen nem szakithato felbe", not _r.ok, str(_r.lines))


# ══ 9. A PARANCS es a MOTOR ════════════════════════════════════════════
from core import telegram_cmd as tc
check("az `optq` parancs be van jegyezve", "optq" in cc.COMMANDS)
check("...es szerepel a sugoban", any(n.startswith("optq") for n, _k in cc._HELP))
check("az `optq` ELERHETO Telegramon (csak olvas)", "optq" in tc.ENGEDETT)
check("a parancs listaz", bool(cc.dispatch(ctx, "optq").lines))
# ⚠ A SOR HAJTASA A MOTORE: egy alprocessz inditasa egy LEKERDEZES
# mellekhatasakent meglepetes volna.
_src = (ROOT / "core" / "console_cmd.py").read_text(encoding="utf-8")
_cmd = _src.split("def cmd_optq(")[1].split(chr(10) + "def ")[0]
check("⚠ a lekerdezes NEM inditja a sort", "drain(" not in _cmd, "")

_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor hajtja a sort", "_coptq.drain(" in _lt)
check("...es indulaskor takaritja", "_coptq0.prune(" in _lt)
# ⚠ A MOTOR NEM OPTIMALIZAL SAJAT MAGA: a CPU-nehez munka alprocesszben megy.
_oq = (ROOT / "conductor" / "optqueue.py").read_text(encoding="utf-8")
check("⚠ a sor ALPROCESSZT indit, nem szalat",
      "subprocess.Popen" in _oq and "threading.Thread" not in _oq)
check("...a MEGLEVO CLI belepesi ponton",
      '"optimize", symbol' in _oq and '"--strategy", strategy' in _oq)
check("...es nem importal optimalizalot",
      "run_optimizer" not in _oq and "optimize_job" not in _oq)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
