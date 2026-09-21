"""KARMESTER F2 — javaslat-postalada: dontes, vegrehajtas, visszavonas.

⚠ ITT ER HOZZA A KARMESTER A RENDSZERHEZ. Minden mas modulja mer, itel vagy
javasol; itt dol el, hogy egy javaslatbol valtozas lesz-e. Ezert minden szabaly,
ami a tervben „invarians" neven szerepel, itt valik kodda:

  • a javaslat NEM parancs: az elfogadas pillanataban ujraszamoljuk;
  • a vegrehajtas a KOZOS parancs-retegen megy (nem negyedik irasi ut);
  • minden akcio rogziti az ELOZO allapotot (visszavonhatosag);
  • es amihez nincs vegrehajtasi ut, arra NEM teszunk ugy, mintha lenne.
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
from conductor import inbox as ib
from conductor import actions as act
from conductor import config as ccfg
from conductor import report as rep
from conductor import proposals as pr
from core import console_cmd as cc
from core import telegram_cmd as tc
from core import trade_mode as tm

TMP = Path(tempfile.mkdtemp(prefix="tf_ibx_"))
cp.DIR = TMP / "conductor"
_CSV = TMP / "trades.csv"
cp.trades_csv = lambda: _CSV
tl.FLUSH_SEC = 0.0
import core.params_store as ps
ps.PARAMS_DIR = TMP / "params"
(ps.PARAMS_DIR / "csilla").mkdir(parents=True, exist_ok=True)

NOW = dt.datetime.now(dt.timezone.utc)
COLS = ["time", "event", "strategy", "symbol", "direction", "lot", "price",
        "sl", "tp", "ticket", "magic", "pnl_usd"]


def _naplo(pnl_fn, n=60):
    with open(_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for i in range(n):
            w.writerow({"time": (NOW - dt.timedelta(days=i % 40)).isoformat(),
                        "event": "close", "strategy": "csilla", "symbol": "GOLD",
                        "ticket": i, "pnl_usd": pnl_fn(i)})


(ps.PARAMS_DIR / "csilla" / "GOLD.json").write_text(json.dumps({
    "params": {"x": 1}, "optimized_at": NOW.isoformat(),
    "test_summary": {"trades": 200, "profit_factor": 1.6, "win_rate": 0.5,
                     "max_drawdown": 0.1}}), encoding="utf-8")


def _cfg():
    return {"optimizer": {"test_start_date": "2026-01-01"},
            "pairs": {"GOLD": {"enabled": True, "strategies": ["csilla"],
                               "run_state": {"csilla": "live"}}}}


def _ctx(cfg=None):
    return cc.Context(cfg=cfg or _cfg(), save_config=lambda: True, positions=list,
                      close_position=lambda t: False, account=dict, dashboard={},
                      instrument_state={}, strategies_of=lambda s: ["csilla"])


ROMLO = lambda i: 10.0 if i % 5 == 0 else -4.0      # PF ~0,62
JO = lambda i: 10.0 if i % 2 == 0 else -4.0         # PF ~2,5


# ══ 1. BEOLVASZTAS: ami mar nyitott ugy, nem szuletik ujra ══════════════
ib.reset_for_test()
_naplo(ROMLO)
ctx = _ctx()
_st = cc._inbox_sync(ctx)
check("a javaslatbol postalada-tetel lesz", _st["new"] == 1, str(_st))
_id = ib.items(ib.PENDING)[0]["id"]
check("...azonositoval", bool(_id) and len(_id) >= 4, _id)
# ⚠ Egy fennallo helyzet minden korben ujra javaslatta valna — a postalada egy
# nap alatt olvashatatlan lenne, es pont az veszne el benne, ami UJ.
check("ugyanaz a javaslat NEM szuletik ujra, amig nyitott",
      cc._inbox_sync(ctx)["new"] == 0 and len(ib.items(ib.PENDING)) == 1)
# A `hold` sosem kerul be.
check("a `hold` nem kerul a postaladaba",
      ib.sync(_cfg(), [pr.Proposal(action=pr.HOLD, symbol="X", strategy="y",
                                   reason="ok")])["new"] == 0)


# ══ 2. ELVETES: meg kell maradnia ═══════════════════════════════════════
# ⚠ Ha az elvetett javaslat masnap ujraszuletne, az elvetes semmit nem jelentene
# — a postalada pedig arra tanitana, hogy hagyd figyelmen kivul.
_r = cc.dispatch(ctx, f"reject {_id}")
check("az elvetes visszajelez", _r.ok and "Elvetve" in chr(10).join(_r.lines))
check("...a tetel kikerul a nyitottak kozul", not ib.items(ib.PENDING))
check("⚠ ...es NEM szuletik ujra", cc._inbox_sync(ctx)["new"] == 0,
      str(len(ib.items(ib.PENDING))))
check("...a turelmi ido a configbol jon",
      ccfg.inbox({})["reject_cooldown_days"] == 14)

# A turelmi ido LEJARTA utan viszont igen.
ib.set_state(_id, ib.REJECTED, _cfg(), hidden_days=-1)     # „tegnap jart le"
check("a turelmi ido lejartaval a javaslat ujraszulethet",
      cc._inbox_sync(ctx)["new"] == 1, str(len(ib.items(ib.PENDING))))
_id = ib.items(ib.PENDING)[0]["id"]

# HALASZTAS: ugyanaz a mechanika, rovidebb idore.
_r = cc.dispatch(ctx, f"defer {_id}")
check("az elhalasztas felreteszi", _r.ok and not ib.items(ib.PENDING))
ib.set_state(_id, ib.DEFERRED, _cfg(), hidden_days=-1)
check("...es a hatarido utan visszajon", cc._inbox_sync(ctx)["new"] == 1)
_id = ib.items(ib.PENDING)[0]["id"]


# ══ 3. ELFOGADAS: vegrehajtas a KOZOS retegen ═══════════════════════════
jr.reset_for_test()
cfg = _cfg()
ctx = _ctx(cfg)
check("a mod elotte `live`", tm.mode_of(cfg, "GOLD", "csilla") == "live")
_r = cc.dispatch(ctx, f"accept {_id}")
check("az elfogadas VEGREHAJT", _r.ok, str(_r.lines))
check("...a mod tenylegesen atallt", tm.mode_of(cfg, "GOLD", "csilla") == "signal")
check("...es felajanlja a visszavonast",
      any("undo" in s for s in _r.lines), str(_r.lines))
_e = ib.get(_id)
check("a tetel `accepted` lett", _e["state"] == ib.ACCEPTED, _e["state"])
# ⚠ MINDEN AKCIO ROGZITI AZ ELOZO ALLAPOTOT — enelkul nincs visszaut.
check("⚠ a VISSZAUT rogzult", (_e.get("undo") or {}).get("mode") == "live",
      str(_e.get("undo")))
check("...es ki dontott", _e.get("decided_by") == "human")
_akciok = jr.read(limit=5, kind=jr.KIND_ACTION)
check("az akcio a kronikaba kerult", bool(_akciok) and _akciok[0]["code"].startswith("set_mode_signal"))
check("...a bizonyitekkal egyutt",
      (_akciok[0].get("data") or {}).get("evidence", {}).get("live_trades") == 60,
      str(_akciok[0].get("data", {}).get("evidence"))[:60])
check("ugyanaz a tetel masodszor nem fogadhato el",
      not cc.dispatch(ctx, f"accept {_id}").ok)


# ══ 4. ⚠ A JAVASLAT NEM PARANCS: UJRAERVENYESITES ══════════════════════
# Egy tegnapi „minositsd vissza" egy azota megjavult cellan kart tenne — es pont
# az ilyen, idokozben elavult dontes a legnehezebben eszrevehetoo hiba: minden
# lepes helyesnek LATSZIK, csak epp egy regi vilagra vonatkozik.
ib.reset_for_test()
jr.reset_for_test()
_naplo(ROMLO)
cfg = _cfg()
ctx = _ctx(cfg)
cc._inbox_sync(ctx)
_id2 = ib.items(ib.PENDING)[0]["id"]
_naplo(JO)                                   # a cella MEGJAVULT
_r = cc.dispatch(ctx, f"accept {_id2}")
check("⚠ az elavult javaslat NEM hajtodik vegre", not _r.ok, str(_r.lines))
check("...es megmondja, miert", "MÁR NEM ÉRVÉNYES" in chr(10).join(_r.lines))
check("...a mod VALTOZATLAN marad", tm.mode_of(cfg, "GOLD", "csilla") == "live")
check("...es a tetel nyitott marad", ib.get(_id2)["state"] == ib.PENDING)
# ⚠ FAIL CLOSED: ha nem tudjuk ELLENORIZNI, nem hajtunk vegre.
_eredeti = act.still_valid
act.still_valid = lambda c, e: (_ for _ in ()).throw(RuntimeError("proba"))
try:
    check("⚠ ha az ellenorzes elszall, NEM hajtunk vegre",
          not act.apply(ctx, ib.get(_id2)).ok)
finally:
    act.still_valid = _eredeti


# ══ 5. MINDEN AKCIONAK VAN VEGREHAJTASI UTJA (v3.82.0 ota) ═════════════
# ⚠ EZ VALTOZOTT. Az optimalizalas korabban CSAK a feluleten indulhatott
# (OptimizerController), ezert a `queue_optimize` javaslat TANACS volt: az
# elfogadas oszinten elutasitott, es megmondta, hol vegezheto el. A fej nelkuli
# sor (conductor/optqueue.py) ota vegrehajthato — a „nincs vegrehajto" ag
# viszont MEGMARAD a kodban, mert a kovetkezo uj akcional ujra kelleni fog.
check("a mod-valtasnak van vegrehajtoja", act.can_execute(pr.SET_MODE_LIVE)
      and act.can_execute(pr.SET_MODE_SIGNAL))
check("az optimalizalasnak MOSTANTOL van", act.can_execute(pr.QUEUE_OPTIMIZE))

# ⚠ ES A HAMIS SIKER TOVABBRA IS TILOS: egy akcio, amihez nincs vegrehajto, nem
# tehet ugy, mintha megtortent volna — megmondja, hol vegezheto el.
_r = act.apply(ctx, {"id": "x", "action": "nincsilyen", "symbol": "GOLD",
                     "strategy": "csilla"})
check("⚠ ismeretlen akciora OSZINTEN elutasit", not _r.ok, str(_r.lines))
check("...es megmondja, HOL vegezheto el",
      "felületen" in chr(10).join(_r.lines), str(_r.lines))
_nincs = [{"id": "x", "action": "nincsilyen", "symbol": "GOLD",
           "strategy": "csilla", "text": "ismeretlen", "needs_human": False}]
check("a listaban TANACSKENT latszik",
      any("tanács" in x for x in rep.inbox_lines(_nincs)),
      chr(10).join(rep.inbox_lines(_nincs)))


# ══ 6. VISSZAVONAS ═════════════════════════════════════════════════════
ib.reset_for_test()
jr.reset_for_test()
_naplo(ROMLO)
cfg = _cfg()
ctx = _ctx(cfg)
cc._inbox_sync(ctx)
_id3 = ib.items(ib.PENDING)[0]["id"]
cc.dispatch(ctx, f"accept {_id3}")
check("elfogadas utan `signal`", tm.mode_of(cfg, "GOLD", "csilla") == "signal")
# ⚠ A VISSZAVONAS IS AKCIO: egy visszaminosites visszavonasa VALODI KOTEST
# kapcsol vissza, ezert ugyanazon a megerosites-mintan megy.
_r = cc.dispatch(ctx, f"undo {_id3}")
check("⚠ a visszavonas MEGERSITEST ker (penzt kapcsol vissza)", bool(_r.confirm),
      (_r.confirm or "")[:50])
check("...es addig NEM csinal semmit", tm.mode_of(cfg, "GOLD", "csilla") == "signal")
_r = cc.dispatch(ctx, f"undo {_id3}", confirmed=True)
check("megerositve visszaall", tm.mode_of(cfg, "GOLD", "csilla") == "live")
check("a visszavonas is a kronikaba kerul",
      any(e["code"].startswith("undo:") for e in jr.read(limit=5, kind=jr.KIND_ACTION)))
# ⚠ A tetel NEM megy vissza PENDING-be: a javaslat akkor szulessen ujra, ha a
# hazirend MA IS javasolja — egy feltamasztott, de mar nem idoszeru ugy hazugsag.
check("⚠ a visszavont tetel NEM kerul vissza a nyitottak koze",
      ib.get(_id3)["state"] != ib.PENDING, ib.get(_id3)["state"])
check("nem vegrehajtott tetel nem vonhato vissza",
      not cc.dispatch(ctx, f"undo {_id3}").ok)


# ══ 7. LEJARAT ═════════════════════════════════════════════════════════
# ⚠ TISZTA LAP: a `reset_for_test` csak a MEMORIAT uriti — az elozo blokk
# elvetett tetele a FAJLBAN marad, es az elvetes (helyesen) eltemeti a
# javaslatot, tehat a `sync` nem szulne ujra. A blokk igy onmagaban all.
ib.reset_for_test()
(cp.DIR / "inbox.json").unlink(missing_ok=True)
_naplo(ROMLO)
cc._inbox_sync(ctx)
_e = ib.items(ib.PENDING)[0]
ib._state[_e["id"]]["expires"] = "2020-01-01T00:00:00+00:00"
_st = ib.sync(_cfg(), [])
check("az elevult tetel kiesik", _st["expired"] == 1 and not ib.items(ib.PENDING),
      str(_st))
check("⚠ a lejarat a MASODIK vedvonal (az elso az ujraervenyesites)",
      ccfg.inbox({})["expire_days"] == 7)


# ══ 8. A PARANCSOK es a TELEGRAM ═══════════════════════════════════════
for _c in ("inbox", "accept", "reject", "defer", "undo"):
    check(f"a `{_c}` parancs be van jegyezve", _c in cc.COMMANDS)
check("mind szerepel a sugoban",
      all(any(n.split()[0] == c for n, _k in cc._HELP)
          for c in ("inbox", "accept", "reject", "defer", "undo")))
# ⚠ A POSTALADA CSAK OLVASHATO Telegramrol. Az `accept` valodi kotest
# kapcsolhat be egy chatuzenetbol — az a `notify.answer_trading` kategoriaja
# (kulon opt-in, gombos megerositessel).
check("a `inbox` ELERHETO Telegramon (csak olvas)", "inbox" in tc.ENGEDETT)
check("⚠ az `accept` NEM", "accept" not in tc.ENGEDETT)
check("...es a `reject`/`defer`/`undo` sem",
      not any(c in tc.ENGEDETT for c in ("reject", "defer", "undo")))
check("ismeretlen azonositora beszedes hiba",
      not cc.dispatch(ctx, "accept nincsilyen").ok)
check("azonosito nelkul hasznalatot ir", not cc.dispatch(ctx, "accept").ok)


# ══ 9. A MOTOR: gyujt, de NEM dont ═════════════════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor beolvasztja a javaslatokat a postaladaba", "_cibx.sync(cfg, _jav" in _lt)
# ⚠ ES ATADJA A STRATEGIA-LISTAT is: enelkul a postalada nem tudna megallapitani,
# hogy egy tetel alol ELTUNT-e a cella (lasd a 10. blokkot).
check("...a motor strategia-listaval egyutt", "_cibx.sync(cfg, _jav" in _lt
      and "strategies_of=lambda s: _ensn_h(cfg, s) or []" in _lt)
# ⚠ A MOTOR NEM DONT: a tetelek `pending` allapotban allnak, amig nem dontesz.
check("⚠ a motor NEM fogad el es NEM hajt vegre",
      "actions.apply" not in _lt and "_cibx.set_state" not in _lt)
check("indulaskor a postalada is takarodik", "_cibx0.prune(" in _lt)



# ══ 10. ARVA TETEL: a cella megszunt a javaslat alatt ═══════════════════
# ⚠ A LELET (a felhasznalotol): „mi van akkor, ha egy strategiat kozben
# kiveszek? Mi lesz az uzenetekkel?" A valasz eddig az volt, hogy ULNEK a
# listan a lejaratukig (alapbol egy hetig), egy cellara hivatkozva, ami mar
# nincs. Elfogadni ezeket eddig sem lehetett (az `actions.still_valid`
# elbukik rajtuk) — de egy lista, amiben tArgytalan tetelek allnak, arra
# tanit, hogy a postaladat nem kell komolyan venni.
ib.reset_for_test()
_naplo(ROMLO)
_st = cc._inbox_sync(_ctx())
check("van mit arvan hagyni", _st["new"] == 1 and len(ib.items(ib.PENDING)) == 1,
      str(_st))

# A strategiat levesszuk a parrol — a motor listaja ures lesz ra.
_ctx_nelkul = cc.Context(cfg=_cfg(), save_config=lambda: True, positions=list,
                         close_position=lambda t: False, account=dict,
                         dashboard={}, instrument_state={},
                         strategies_of=lambda s: [])
_st2 = cc._inbox_sync(_ctx_nelkul)
check("⚠ a tetel AZONNAL targytalan lesz (nem var a lejaratra)",
      _st2.get("obsolete") == 1, str(_st2))
check("...es kikerul a nyitottak kozul", not ib.items(ib.PENDING))
check("...de a nyoma megmarad, a sajat allapotaval",
      len(ib.items(ib.OBSOLETE)) == 1)

# ⚠ A BIZONYTALANSAG NEM MEGSZUNES: ha a strategia-listat nem tudjuk feloldani,
# NEM temetunk. Inkabb maradjon egy folosleges tetel, mint hogy egy atmeneti
# hiba (importhiba, elszallo feloldas) kiuritse a postaladat.
ib.reset_for_test()
cc._inbox_sync(_ctx())
_elott = len(ib.items(ib.PENDING))
ib.sync(_cfg(), [])                       # strategies_of NELKUL
check("⚠ strategia-lista nelkul NEM minositunk targytalanna",
      len(ib.items(ib.PENDING)) == _elott and _elott == 1)

def _robban(_s):
    raise RuntimeError("a feloldas elszallt")
_st3 = ib.sync(_cfg(), [], strategies_of=_robban)
check("...es egy ELSZALLO feloldas sem temet",
      _st3.get("obsolete") == 0 and len(ib.items(ib.PENDING)) == 1, str(_st3))

# Ha maga az INSTRUMENTUM tunik el a configbol, az is megszunes.
_st4 = ib.sync({"pairs": {}}, [], strategies_of=lambda s: ["csilla"])
check("a torolt INSTRUMENTUM tetelei is targytalanok",
      _st4.get("obsolete") == 1 and not ib.items(ib.PENDING), str(_st4))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
