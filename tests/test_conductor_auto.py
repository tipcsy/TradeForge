"""GEPI VEGREHAJTAS ES A BUROK (F3/b) — meddig mehet el a karmester magatol.

⚠ A FOK ES A BUROK NEM UGYANAZ. A fok azt mondja meg, kell-e EMBERI PIPA; a
burok azt, MEDDIG mehet el a gep, ha nem kell. A terv szerint a burok L4-en is a
helyen marad — „kulonben nem autonomia, hanem felugyelet nelkuli szabadeses".
Egy elszallo visszacsatolasi hurkot nem a fok allit meg, hanem a kvota.

⚠ AMIT EZ A TESZT ORIZ, AZ NEM A „MUKODIK-E", HANEM A „MIKOR NEM":
  1. a penzt bekapcsolo lepes SOSEM gepi — semmilyen fokon;
  2. a megerosites-kerdesre a gep NEM valaszol helyetted;
  3. amit a burok megallit, az a postaladaban MARAD (nem vetjuk el a nevedben);
  4. a tetlenseg OKA ugyanolyan valasz, mint a lepes.
"""
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

TMP = Path(tempfile.mkdtemp(prefix="tf_auto_"))
cp.DIR = TMP / "conductor"
cp.DIR.mkdir(parents=True, exist_ok=True)

from conductor import autonomy as au
from conductor import auto as ca
from conductor import governor as gov
from conductor import inbox as ib
from conductor import journal as jr
from conductor import optqueue as oq
from conductor import proposals as pr
from conductor import report as rep
from core import console_cmd as cc
from core import trade_mode as tm


def _cfg(level=au.ASSISTED, **burok):
    c = {"optimizer": {"test_start_date": "2026-01-01"},
         "pairs": {"GOLD": {"enabled": True, "strategies": ["csilla", "ml_ai"],
                            "run_state": {"csilla": "live", "ml_ai": "live"},
                            "strategy_mode": {"csilla": "live"}}},
         "conductor": {"autonomy": {"default": level}}}
    c["conductor"]["autonomy"].update(burok)
    return c


_MENTVE = []


def _ctx(cfg, poz=()):
    return cc.Context(cfg=cfg, save_config=lambda: (_MENTVE.append(1) or True),
                      positions=lambda: list(poz),
                      close_position=lambda t: False, account=dict, dashboard={},
                      instrument_state={}, strategies_of=lambda s: ["csilla", "ml_ai"])


def _tiszta():
    ib.reset_for_test()
    jr.reset_for_test()
    oq.reset_for_test()
    # ⚠ A FAJLT IS: a `reset_for_test` csak a MEMORIAT uriti, a kronikat es a
    # postaladat a kovetkezo olvasas visszahozna a lemezrol — es akkor a
    # turelmi ido egy korabbi blokk lepesetol indulna el.
    for f in ("inbox.json", "opt_queue.json"):
        (cp.DIR / f).unlink(missing_ok=True)
    cp.journal_file().unlink(missing_ok=True)
    cp.off_switch().unlink(missing_ok=True)


def _javaslat(cfg, action=pr.SET_MODE_SIGNAL, sym="GOLD", strat="csilla"):
    """Egy PENDING tetel a postaladaba, hazirend nelkul."""
    p = pr.Proposal(action=action, symbol=sym, strategy=strat, reason="degraded",
                    from_stage="live", to_stage="paper", text="teszt-javaslat",
                    evidence={"live_trades": 60})
    ib.sync(cfg, [p], strategies_of=lambda s: ["csilla", "ml_ai"])
    return ib.items(ib.PENDING)[0]


# ⚠ A `config_check` a VALODI configot nezne; a tesztben lecsereljuk.
import core.config_check as _cchk
_cchk_eredeti = _cchk.check
_cchk.check = lambda cfg=None, *a, **k: []


# ══ 1. AZ AKCIOK OSZTALYAI ═════════════════════════════════════════════
check("⚠ a penzt bekapcsolo lepes SOSEM gepi",
      gov.min_level(pr.SET_MODE_LIVE) is None)
check("a kockazatCSOKKENTO lepes L2-tol",
      gov.min_level(pr.SET_MODE_SIGNAL) == au.ASSISTED)
# ⚠ Az optimalizalas nem mozgat penzt, DE a parameterkeszlet felulirasa nem
# vonhato vissza (nincs mentes a regirol) — ezert nem fer az L2 igeretebe.
check("az optimalizalas csak L3-tol", gov.min_level(pr.QUEUE_OPTIMIZE) == au.LIMITED)
check("ismeretlen akciora nincs gepi osztaly", gov.min_level("hupp") is None)


# ══ 2. A KAPUK ═════════════════════════════════════════════════════════
_tiszta()
c = _cfg()
t = _javaslat(c)
_szabad, _ok = gov.allowed(c, t, positions=list)
check("L2-n a visszaminositest a gep megteheti", _szabad, _ok)

# ⚠ A PENZ: barmilyen fokon NEM.
_tiszta()
c = _cfg(level=au.FULL)
t = _javaslat(c, action=pr.SET_MODE_LIVE)
_szabad, _ok = gov.allowed(c, t, positions=list)
check("⚠ L4-en SEM kapcsol be penzt magatol",
      not _szabad and _ok == gov.OK_NEEDS_HUMAN, _ok)

# A FOK: L1-en meg nincs gepi mandatum.
_tiszta()
c = _cfg(level=au.ADVISOR)
t = _javaslat(c)
_szabad, _ok = gov.allowed(c, t, positions=list)
check("L1-en a gep nem lep", not _szabad and _ok == gov.OK_LEVEL, _ok)
# ...de EGY CELLA felemelheto.
au.set_override(c, "GOLD", "csilla", au.ASSISTED)
_szabad, _ok = gov.allowed(c, t, positions=list)
check("⚠ ...de a cella-szintu felulbiralas felemeli", _szabad, _ok)

# AZ OPTIMALIZALAS L2-n MEG NEM.
_tiszta()
c = _cfg(level=au.ASSISTED)
t = _javaslat(c, action=pr.QUEUE_OPTIMIZE)
_szabad, _ok = gov.allowed(c, t, positions=list)
check("L2-n az optimalizalas meg NEM gepi",
      not _szabad and _ok == gov.OK_LEVEL, _ok)
au.set_default(c, au.LIMITED)
_szabad, _ok = gov.allowed(c, t, positions=list)
check("...L3-on viszont igen", _szabad, _ok)

# NYITOTT POZICIO.
_tiszta()
c = _cfg()
t = _javaslat(c)
_szabad, _ok = gov.allowed(c, t, positions=lambda: [{"symbol": "GOLD"}])
check("nyitott pozicio mellett nem valtoztat",
      not _szabad and _ok == gov.OK_POSITION_OPEN, _ok)
_szabad, _ok = gov.allowed(c, t, positions=lambda: [{"symbol": "GER40"}])
check("...MAS paron levo pozicio viszont nem akadaly", _szabad, _ok)
# ⚠ HA NEM TUDJUK MEGKERDEZNI, NEM LEPUNK („fail closed").
_szabad, _ok = gov.allowed(c, t, positions=None)
check("⚠ pozicio-lekerdezes nelkul NEM lepunk",
      not _szabad and _ok == gov.OK_POSITION_OPEN, _ok)
def _robban():
    raise RuntimeError("nincs kapcsolat")
_szabad, _ok = gov.allowed(c, t, positions=_robban)
check("⚠ ...es egy ELSZALLO lekerdezes sem ad felmentest",
      not _szabad and _ok == gov.OK_POSITION_OPEN, _ok)
# A szabaly kikapcsolhato.
c2 = _cfg(no_change_while_position_open=False)
t2 = _javaslat(c2)
_szabad, _ok = gov.allowed(c2, t2, positions=lambda: [{"symbol": "GOLD"}])
check("...a szabaly configbol kikapcsolhato", _szabad, _ok)

# CONFIG WARN → IRAS-TILTO (a terv invarianasa).
_tiszta()
c = _cfg()
t = _javaslat(c)
_cchk.check = lambda cfg=None, *a, **k: [{"level": _cchk.WARN, "code": "x"}]
_szabad, _ok = gov.allowed(c, t, positions=list)
check("⚠ `config_check` WARN mellett a karmester NEM ir",
      not _szabad and _ok == gov.OK_CONFIG_WARN, _ok)
# ⚠ ES HA MAGA AZ ELLENORZES SZALL EL: biztonsagbol iras-tiltonak vesszuk.
def _cc_robban(cfg=None, *a, **k):
    raise RuntimeError("elszallt")
_cchk.check = _cc_robban
_szabad, _ok = gov.allowed(c, t, positions=list)
check("⚠ ...es ha az ellenorzes elszall, szinten nem",
      not _szabad and _ok == gov.OK_CONFIG_WARN, _ok)
_cchk.check = lambda cfg=None, *a, **k: []


# ══ 3. TURELMI IDO ES NAPI KERET — a krónikábol ════════════════════════
_tiszta()
c = _cfg()
t = _javaslat(c)
jr.write(jr.KIND_ACTION, "set_mode_signal:degraded", "korabbi gepi lepes",
         symbol="GOLD", strategy="csilla", data={"by": "conductor"})
_szabad, _ok = gov.allowed(c, t, positions=list)
check("a turelmi ido megallitja az ujabb lepest",
      not _szabad and _ok == gov.OK_COOLDOWN, _ok)
# ⚠ A KEZI lepes NEM szamit: a turelmi ido a GEPRE vonatkozik.
_tiszta()
c = _cfg()
t = _javaslat(c)
jr.write(jr.KIND_ACTION, "set_mode_signal:degraded", "amit TE csinaltal",
         symbol="GOLD", strategy="csilla", data={"by": "human"})
_szabad, _ok = gov.allowed(c, t, positions=list)
check("⚠ a KEZI lepes nem inditja el a turelmi idot", _szabad, _ok)
# MAS cellan nem akadaly.
_tiszta()
c = _cfg()
t = _javaslat(c, strat="ml_ai")
jr.write(jr.KIND_ACTION, "set_mode_signal:degraded", "masik cella",
         symbol="GOLD", strategy="csilla", data={"by": "conductor"})
_szabad, _ok = gov.allowed(c, t, positions=list)
check("...es MAS cellan sem", _szabad, _ok)

# NAPI KERET.
_tiszta()
c = _cfg(max_changes_per_day=2, cooldown_hours_per_cell=0)
t = _javaslat(c)
for i in range(2):
    jr.write(jr.KIND_ACTION, f"x{i}", "gepi", symbol="GER40", strategy="csilla",
             data={"by": "conductor"})
_szabad, _ok = gov.allowed(c, t, positions=list)
check("a napi keret elfogyasa megallit",
      not _szabad and _ok == gov.OK_DAILY_QUOTA, _ok)
_q = gov.quota_state(c)
check("...es a keret allasa lekerdezheto",
      _q["used"] == 2 and _q["limit"] == 2 and not _q["unlimited"], str(_q))
# ⚠ A `0` a tervben KORLATLAN (L4-en) — ez forditva van, mint ahol a 0
# „kikapcsolva" (pl. `noopt`), ezert nemán nem maradhat: a kiiras kimondja.
c0 = _cfg(max_changes_per_day=0, cooldown_hours_per_cell=0)
check("a `0` keret KORLATLAN (a terv szerint)",
      gov.quota_state(c0)["unlimited"])
_sorok = chr(10).join(rep.autonomy_lines(c0))
check("⚠ ...es a kiiras NEVVEL mondja ki, hogy nincs plafon",
      "KORLÁTLAN" in _sorok, _sorok[-160:])


# ══ 4. A VEGREHAJTAS: egy ut, ket hivo ═════════════════════════════════
# ⚠ AZ UJRAERVENYESITES ELOSZOR. Az `actions.apply` a vegrehajtas pillanataban
# UJRA megkerdezi a hazirendet: igaz-e meg a javaslat. A kezzel osszerakott
# teszt-tetel ezen megbukna (a hazirend mas javaslatot adna erre a cellara) —
# es ez HELYES viselkedes, ezert eloszor EZT allitjuk, csak utana cserelunk.
import conductor.actions as _act
_tiszta()
c = _cfg()
ctx = _ctx(c)
t = _javaslat(c)
_st = ca.run(ctx)
check("⚠ az ELAVULT javaslatot a gep NEM hajtja vegre",
      _st["done"] == 0 and _st["failed"] == 1, str(_st))
check("...es a mod valtozatlan marad",
      tm.mode_of(c, "GOLD", "csilla") == tm.MODE_LIVE)

# Innentol a hazirend-ujraszamolast lecsereljuk: a VEGREHAJTAST merjuk, nem az
# eletciklus-letrat (annak sajat tesztje van).
_eredeti_valid = _act.still_valid
_act.still_valid = lambda ctx_, e: (True, e.get("code"))

_tiszta()
c = _cfg()
ctx = _ctx(c)
t = _javaslat(c)
check("indulaskor `live` a mod", tm.mode_of(c, "GOLD", "csilla") == tm.MODE_LIVE)
_st = ca.run(ctx)
check("a gep vegrehajtotta", _st["done"] == 1, str(_st))
check("...es a mod tenyleg atallt",
      tm.mode_of(c, "GOLD", "csilla") == tm.MODE_SIGNAL)
check("...a tetel ELFOGADVA, visszauttal",
      ib.get(t["id"])["state"] == ib.ACCEPTED and ib.get(t["id"])["undo"])
# ⚠ A KRONIKABAN BENNE VAN, HOGY A GEP TETTE.
_sorok = jr.read(limit=10, kind=jr.KIND_ACTION)
check("⚠ a kronika megjeloli, hogy GEPI volt",
      _sorok and (_sorok[0].get("data") or {}).get("by") == "conductor",
      str((_sorok[0].get("data") or {}).get("by") if _sorok else None))
# ⚠ ES VISSZAVONHATO — ugyanazzal a paranccsal, mint a kezi dontes.
# ⚠ DE A VISSZAVONAS IS AKCIO: egy visszaminosites visszavonasa VALODI KOTEST
# kapcsol vissza, tehat ugyanazon a megerosites-mintan megy, mint minden penzt
# bekapcsolo lepes. Ez NEM kenyelmetlenseg, hanem a lenyeg: a gep lefokozhat
# magatol, de visszakapcsolni csak te tudsz — es csak tudatosan.
_r = cc.dispatch(ctx, f"undo {t['id']}")
check("⚠ a visszavonas MEGERSITEST ker (penzt kapcsolna vissza)",
      bool(_r.confirm), _r.confirm[:80])
check("...es addig NEM allit vissza semmit",
      tm.mode_of(c, "GOLD", "csilla") == tm.MODE_SIGNAL)
_r = cc.dispatch(ctx, f"undo {t['id']}", confirmed=True)
check("megerositve a gepi lepes visszavonhato", _r.ok,
      chr(10).join(_r.lines)[:80])
check("...es a mod visszaallt",
      tm.mode_of(c, "GOLD", "csilla") == tm.MODE_LIVE)

# ⚠ AMIT A BUROK MEGALLIT, AZ A POSTALADABAN MARAD.
_tiszta()
c = _cfg(level=au.ADVISOR)
ctx = _ctx(c)
t = _javaslat(c)
_st = ca.run(ctx)
check("a burok altal megallitott tetel NEM hajtodik vegre", _st["done"] == 0)
check("⚠ ...es NEM is vetjuk el a nevedben",
      ib.get(t["id"])["state"] == ib.PENDING, ib.get(t["id"])["state"])
check("...az OKA viszont megvan", _st["reasons"].get(gov.OK_LEVEL) == 1,
      str(_st["reasons"]))

# ⚠ A MEGEROSITES-KERDESRE A GEP NEM VALASZOL HELYETTED.
_tiszta()
c = _cfg()
ctx = _ctx(c)
t = _javaslat(c)
_eredeti_apply = _act.apply
_act.apply = lambda ctx_, e, confirmed=False, by="human": cc.Result(
    confirm="tenyleg?") if not confirmed else cc.Result(["megtortent"])
try:
    _st = ca.run(ctx)
    check("⚠ a gep NEM valaszol a megerosites-kerdesre",
          _st["done"] == 0 and _st["reasons"].get("needs_confirm") == 1,
          str(_st))
    check("...es a tetel nyitva marad", ib.get(t["id"])["state"] == ib.PENDING)
finally:
    _act.apply = _eredeti_apply

# ⚠ KIKAPCSOLVA (L-1) SEMMI NEM TORTENIK.
_tiszta()
c = _cfg()
ctx = _ctx(c)
t = _javaslat(c)
au.set_off_file(True)
try:
    _st = ca.run(ctx)
    check("⚠ kikapcsolva a gep nem lep", _st["done"] == 0, str(_st))
    check("...es a mod valtozatlan",
          tm.mode_of(c, "GOLD", "csilla") == tm.MODE_LIVE)
finally:
    au.set_off_file(False)


# ══ 5. AMIT TETT, AZT LATNOD KELL ══════════════════════════════════════
_act.still_valid = lambda ctx_, e: (True, e.get("code"))
_tiszta()
c = _cfg()
ctx = _ctx(c)
t = _javaslat(c)
ca.run(ctx)
_sorok = rep.auto_lines(c)
check("a jelentes kiirja, mit tett a gep magatol",
      _sorok and any("teszt-javaslat" in s for s in _sorok), str(_sorok[:2]))
check("⚠ ...es a VISSZAVONAS azonositojaval egyutt",
      any(t["id"] in s for s in _sorok))
_napi = chr(10).join(rep.daily_lines(c, strategies_of=lambda s: ["csilla"])).lower()
check("...a napi szakaszba is bekerul",
      "magától" in _napi or "on its own" in _napi, _napi[-160:])
# Ha nem tett semmit, NINCS szakasz (nem „0 db").
_tiszta()
check("⚠ ha nem tett semmit, nincs szakasz", rep.auto_lines(_cfg()) == [])

_act.still_valid = _eredeti_valid

# ⚠ A POSTALADA MEGMONDJA, MIERT ALL MEG OTT A TETEL.
_tiszta()
c = _cfg(level=au.ASSISTED)
ctx = _ctx(c)
_javaslat(c)
jr.write(jr.KIND_ACTION, "korabbi", "gepi", symbol="GOLD", strategy="csilla",
         data={"by": "conductor"})
_r = cc.dispatch(ctx, "inbox")
check("⚠ a postalada kimondja, miert nem tette meg a gep",
      "türelmi idő" in chr(10).join(_r.lines), chr(10).join(_r.lines)[:200])


# ══ 6. A MOTOR TENYLEG HIVJA ═══════════════════════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor hivja a gepi vegrehajtast", "_cauto.run(" in _lt)
check("⚠ ...de CSAK az `AUTO` kapun at", "_cau.enged(cfg, _cau.AUTO)" in _lt)
check("...a postalada beolvasztasa UTAN",
      _lt.index("_cibx.sync(cfg, _jav") < _lt.index("_cauto.run("))
check("...es a sor hajtasa ELOTT",
      _lt.index("_cauto.run(") < _lt.index("_coptq.drain("))
# ⚠ EGY IRASI UT: a gep ugyanazt az `actions.apply`-t hivja, mint az „Elfogad".
_auto_src = (ROOT / "conductor" / "auto.py").read_text(encoding="utf-8")
check("⚠ a gep a KOZOS vegrehajton megy", "_act.apply(" in _auto_src)
check("...a `by=conductor` megjelolessel", 'by="conductor"' in _auto_src)
check("⚠ ...es NEM ir kozvetlenul allapotot",
      "set_trade_mode" not in _auto_src and "_tm." not in _auto_src)

_cchk.check = _cchk_eredeti
print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
