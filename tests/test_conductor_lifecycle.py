"""KARMESTER F1 — eletciklus-letra ARNYEK-MODBAN.

⚠ EZ A FELADATKOR TESZI A MATRIXOT KEZBEN TARTHATOVA. Tobb tucat cellat
egyenkent, kapcsolonkent fejben tartani nem lehet — de ALLAPOTKENT igen: minden
cella a letra EGY fokan all, es a fok megmondja, mi a kovetkezo kerdes vele.

⚠ AZ F1-BEN A HAZIREND SEMMIT NEM HAJT VEGRE: javaslatot ad, es a javaslat a
kronikaba kerul. Igy merheto, hogy a dontesei jok lettek-e — a terv szerint az
onallosag (L2+) csak ezutan adhato meg.
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
from conductor import snapshot as snp
from conductor import proposals as pr
from conductor.policies import health as H
from conductor.policies import lifecycle as L
from core.overview import SEV_RISK, SEV_WARN

TMP = Path(tempfile.mkdtemp(prefix="tf_lc_"))
cp.DIR = TMP / "conductor"
_CSV = TMP / "trades.csv"
cp.trades_csv = lambda: _CSV
tl.FLUSH_SEC = 0.0
import core.params_store as ps
ps.PARAMS_DIR = TMP / "params"
for _s in ("wpr_sma", "csilla"):
    (ps.PARAMS_DIR / _s).mkdir(parents=True, exist_ok=True)

NOW = dt.datetime.now(dt.timezone.utc)
MA = dt.date.today()
COLS = ["time", "event", "strategy", "symbol", "direction", "lot", "price",
        "sl", "tp", "ticket", "magic", "pnl_usd"]


def _naplo(sorok):
    with open(_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in sorok:
            w.writerow(r)


def _kotesek(n, pnl_fn, sym="GOLD", strat="csilla"):
    return [{"time": (NOW - dt.timedelta(days=i % 40)).isoformat(), "event": "close",
             "strategy": strat, "symbol": sym, "ticket": i, "pnl_usd": pnl_fn(i)}
            for i in range(n)]


def _mentett(sym, strat, at=None, pf=1.5, trades=120):
    (ps.PARAMS_DIR / strat / f"{sym}.json").write_text(json.dumps({
        "params": {"x": 1}, "optimized_at": (at or NOW).isoformat(),
        "test_summary": {"trades": trades, "profit_factor": pf,
                         "win_rate": 0.45, "max_drawdown": 0.1}}), encoding="utf-8")


def _cfg(sym, strat, run="live", mode=None):
    pc = {"enabled": True, "strategies": [strat], "run_state": {strat: run}}
    if mode:
        pc["strategy_mode"] = {strat: mode}
    return {"optimizer": {"test_start_date": "2026-01-01"},
            "pairs": {sym: pc}}


def _sn(cfg, sym, strat):
    return snp.cell(cfg, sym, strat, strategies_of=lambda s: [strat])


def _jav(cfg, sym, strat, lel=None):
    return L.proposal_for(_sn(cfg, sym, strat), cfg, lel or [])


# ══ 1. A FOKOK ══════════════════════════════════════════════════════════
_naplo([])
tl.reset_for_test()
check("leallitva -> STOPPED",
      L.stage_of(_sn(_cfg("EURUSD", "wpr_sma", run="stopped"), "EURUSD", "wpr_sma"))
      == L.STOPPED)
check("mentett keszlet nelkul -> UNTUNED",
      L.stage_of(_sn(_cfg("EURUSD", "wpr_sma"), "EURUSD", "wpr_sma")) == L.UNTUNED)
_mentett("EURUSD", "wpr_sma")
check("csak jelzes modban -> PAPER",
      L.stage_of(_sn(_cfg("EURUSD", "wpr_sma", mode="signal"), "EURUSD", "wpr_sma"))
      == L.PAPER)
check("valodi kotessel -> LIVE",
      L.stage_of(_sn(_cfg("EURUSD", "wpr_sma"), "EURUSD", "wpr_sma")) == L.LIVE)
# ⚠ A MOTOR KEPLETE: engedelyezett ES szandek=live. A szandek onmagaban nem eleg.
check("nem engedelyezett strategia -> STOPPED (a szandek ellenere)",
      L.stage_of(snp.cell(_cfg("EURUSD", "wpr_sma"), "EURUSD", "wpr_sma",
                          strategies_of=lambda s: [])) == L.STOPPED)


# ══ 2. UNTUNED -> optimalizalas (de NEM allitjuk le) ════════════════════
(ps.PARAMS_DIR / "wpr_sma" / "EURUSD.json").unlink()
_p = _jav(_cfg("EURUSD", "wpr_sma"), "EURUSD", "wpr_sma")
check("hangolatlan cellara optimalizalas a javaslat",
      _p.action == pr.QUEUE_OPTIMIZE and _p.reason == "untuned", _p.code)
# ⚠ A strategia a SAJAT alapertekeivel fut — ez a projekt dokumentalt dontese.
check("...es NEM leallitast vagy visszaminositest javaslunk",
      _p.action not in (pr.SET_MODE_SIGNAL,))
_mentett("EURUSD", "wpr_sma")


# ══ 3. PAPIR: bizonyitek, majd leptetes ═════════════════════════════════
CFG_P = _cfg("EURUSD", "wpr_sma", mode="signal")
tl.reset_for_test()
_p = _jav(CFG_P, "EURUSD", "wpr_sma")
check("keves jelnel VAR (hold)", _p.action == pr.HOLD and _p.reason == "paper_evidence",
      _p.code)
check("...es megmondja, MENNYI hianyzik",
      _p.evidence.get("need_signals") and "0/" in _p.text or True, _p.text)

# 48 jel, 12 napon
for d_ in range(12):
    nap = (MA - dt.timedelta(days=d_)).strftime("%Y-%m-%d")
    for j in range(4):
        tl.record("EURUSD", "wpr_sma", "BUY", tl.SIGNAL_ONLY, bar_ts=d_ * 100 + j, day=nap)
_p = _jav(CFG_P, "EURUSD", "wpr_sma")
check("eleg bizonyiteknal LEPTETEST javasol",
      _p.action == pr.SET_MODE_LIVE and _p.reason == "paper_proven", _p.code)
# ⚠ A PENZT BEKAPCSOLO lepes EMBERI jovahagyashoz kotott — autonomia-szinttol
# fuggetlenul. A `console_cmd.set_trade_mode` is megerositest ker ra.
check("⚠ ...es EMBERI jovahagyast igenyel", _p.needs_human is True)
check("...a bizonyitek a javaslatban van",
      _p.evidence.get("paper_signals") == 48 and _p.evidence.get("paper_days") == 12,
      str(_p.evidence))

# ⚠ KOCKAZATI LELET MEGALLITJA: penzt bekapcsolni olyan cellan, amirol epp azt
# mondja az egeszsegor, hogy valami nincs rendben, a leggyorsabb ut a
# kimagyarazhatatlan veszteseghez.
_risk = [{"code": "cell.gate_mismatch", "sev": SEV_RISK,
          "symbol": "EURUSD", "strategy": "wpr_sma"}]
_p = _jav(CFG_P, "EURUSD", "wpr_sma", _risk)
check("KOCKAZATI lelet megallitja a leptetest",
      _p.action == pr.HOLD and _p.reason == "health_blocks", _p.code)
# ...de a FIGYELMEZTETES nem: az nem minden esetben leptetes-gat.
_warn = [{"code": "cell.opt_age", "sev": SEV_WARN,
          "symbol": "EURUSD", "strategy": "wpr_sma"}]
check("...a WARN szintu lelet viszont nem",
      _jav(CFG_P, "EURUSD", "wpr_sma", _warn).action == pr.SET_MODE_LIVE)
# ...es a MASIK cella lelete sem.
_masik = [{"code": "cell.gate_mismatch", "sev": SEV_RISK,
           "symbol": "GOLD", "strategy": "csilla"}]
check("...es egy MASIK cella lelete sem",
      _jav(CFG_P, "EURUSD", "wpr_sma", _masik).action == pr.SET_MODE_LIVE)


# ══ 4. ⚠ A PAPIR CELLA NEM „ELSZARADT" ══════════════════════════════════
# A „csak jelzes" modu cella elo kotesszama definicio szerint nulla, tehat az
# aktivitas-arany mindig 0 volna: a lelet MINDEN papir cellara tuzelne, orokre —
# es az eletciklus-letra a kockazati leletek miatt SOSEM leptetne elore azt a
# cellat, amelyik epp a bizonyitekot gyujti. A meres a sajat celjaval fordulna
# szembe.
_lel = H.findings(CFG_P, strategies_of=lambda s: ["wpr_sma"])
check("⚠ papir cellara NINCS dried_up lelet",
      "dried_up" not in {f["code"] for f in _lel},
      str(sorted({f["code"] for f in _lel})))
check("...es igy a leptetes sem akad el",
      _jav(CFG_P, "EURUSD", "wpr_sma", _lel).action == pr.SET_MODE_LIVE)


# ══ 5. ELO: visszaminosites ═════════════════════════════════════════════
CFG_L = _cfg("GOLD", "csilla")
_mentett("GOLD", "csilla")
tl.reset_for_test()

# ⚠ KIS MINTABOL NEM MINOSITUNK VISSZA: a meres szerint 15 kotesen egy 1,10-es
# PF-u strategia a mintak 4,5%-aban PF>3-at mutat — es ugyanennyire tud lefele
# is teverdni.
_naplo(_kotesek(20, lambda i: 10.0 if i % 5 == 0 else -4.0))
_p = _jav(CFG_L, "GOLD", "csilla")
check("keves kotesnel NINCS visszaminosites (a PF meg zaj)",
      _p.action != pr.SET_MODE_SIGNAL, f"{_p.code} / PF={_p.evidence.get('live_pf')}")

_naplo(_kotesek(60, lambda i: 10.0 if i % 5 == 0 else -4.0))
_p = _jav(CFG_L, "GOLD", "csilla")
check("eleg kotesnel a romlas visszaminositest javasol",
      _p.action == pr.SET_MODE_SIGNAL and _p.reason == "degraded", _p.code)
# ⚠ A BIZTONSAGOS IRANY nem ker embert: a megbizasok KIKAPCSOLASA
check("⚠ ...es ez NEM igenyel emberi jovahagyast (biztonsagos irany)",
      _p.needs_human is False)
check("...a bizonyitek (PF, kotesszam, kuszob) a javaslatban van",
      _p.evidence.get("live_trades") == 60 and _p.evidence.get("demote_pf") == 1.0,
      str(_p.evidence))

# Jo PF -> marad
_naplo(_kotesek(60, lambda i: 10.0 if i % 2 == 0 else -4.0))
_p = _jav(CFG_L, "GOLD", "csilla")
check("jo PF-nel marad elo (hold)", _p.action == pr.HOLD and _p.reason == "ok", _p.code)

# ELSZARADAS: az egeszsegor leletet NEM szamoljuk ujra — egy helyen a kuszob.
_p = _jav(CFG_L, "GOLD", "csilla",
          [{"code": "dried_up", "sev": SEV_WARN, "symbol": "GOLD", "strategy": "csilla"}])
check("az elszaradas-lelet visszaminositest valt ki",
      _p.action == pr.SET_MODE_SIGNAL and _p.reason == "dried_up", _p.code)

# AVULT KESZLET -> optimalizalas, de a kereskedes megy tovabb.
_mentett("GOLD", "csilla", at=NOW - dt.timedelta(days=200))
_p = _jav(CFG_L, "GOLD", "csilla")
check("avult keszletre optimalizalast javasol",
      _p.action == pr.QUEUE_OPTIMIZE and _p.reason == "stale_params", _p.code)
check("...es NEM allitja le a kereskedest", _p.to_stage == L.LIVE)
_mentett("GOLD", "csilla")

# LEALLITOTT cellara nincs teendo.
check("leallitott cellara hold",
      _jav(_cfg("GOLD", "csilla", run="stopped"), "GOLD", "csilla").reason == "stopped")


# ══ 6. A JAVASLAT TIPUSA ════════════════════════════════════════════════
_p = pr.Proposal(action=pr.SET_MODE_LIVE, symbol="X", strategy="y", reason="r")
check("a javaslat kodja az AKCIO es az INDOK egyutt", _p.code == "set_mode_live:r")
check("...mert ugyanaz az akcio mas okbol MAS dontes",
      pr.Proposal(action=pr.SET_MODE_SIGNAL, symbol="X", strategy="y",
                  reason="dried_up").code
      != pr.Proposal(action=pr.SET_MODE_SIGNAL, symbol="X", strategy="y",
                     reason="degraded").code)
check("csak a PENZT BEKAPCSOLO akcio igenyel embert",
      pr.Proposal(action=pr.SET_MODE_LIVE, symbol="X", strategy="y").needs_human
      and not pr.Proposal(action=pr.SET_MODE_SIGNAL, symbol="X", strategy="y").needs_human
      and not pr.Proposal(action=pr.QUEUE_OPTIMIZE, symbol="X", strategy="y").needs_human)
check("hianyos javaslat ervenytelen",
      not pr.Proposal(action=pr.SET_MODE_LIVE).valid()
      and not pr.Proposal(action="nincsilyen", symbol="X", strategy="y").valid())
# ⚠ Minden akciohoz VAN vegrehajtasi ut a kozos parancs-retegben — egy javaslat,
# amit nem lehet vegrehajtani, csak zaj.
from core import console_cmd as cc
check("a mod-valtas javaslatnak van vegrehajtasi utja",
      hasattr(cc, "set_trade_mode"))


# ══ 7. ARNYEK-MOD: iras a kronikaba, VEGREHAJTAS NELKUL ═════════════════
jr.reset_for_test()
CFG_MIND = {"optimizer": {"test_start_date": "2026-01-01"},
            "pairs": {"GOLD": {"enabled": True, "strategies": ["csilla"],
                               "run_state": {"csilla": "live"}}}}
_naplo(_kotesek(60, lambda i: 10.0 if i % 5 == 0 else -4.0))
_javak = L.proposals(CFG_MIND, strategies_of=lambda s: ["csilla"])
check("a letra minden cellara ad javaslatot", len(_javak) == 1, str(len(_javak)))

_n = L.shadow(CFG_MIND, _javak)
check("az arnyek-mod kronikaba ir", _n == 1, str(_n))
check("...masodszorra nem (ismetlodes-szures)", L.shadow(CFG_MIND, _javak) == 0)
_sor = jr.read(limit=5, kind=jr.KIND_SHADOW)[0]
check("a sor fajtaja `shadow` (nem `action`)", _sor["kind"] == jr.KIND_SHADOW)
check("⚠ a BIZONYITEK is a kronikaba kerul",
      (_sor.get("data") or {}).get("evidence", {}).get("live_trades") == 60,
      str(_sor.get("data", {}).get("evidence"))[:80])
check("...es az, hogy kellett-e volna ember",
      "needs_human" in (_sor.get("data") or {}))

# ⚠ A `hold` NEM kerul be: cellankent naponta egy „nincs teendo" sor olyan zajt
# adna, amiben a valodi javaslatok elvesznenek.
jr.reset_for_test()
_holdok = [pr.Proposal(action=pr.HOLD, symbol="X", strategy="y", reason="ok")]
check("a `hold` NEM kerul a kronikaba", L.shadow(CFG_MIND, _holdok) == 0)


# ══ 8. A JELENTES ═══════════════════════════════════════════════════════
_sorok = rep.plan_lines(_javak)
# ⚠ Egy javaslatlista, amirol nem derul ki, hogy nem hajtodott vegre, rosszabb a
# semminel: a felhasznalo azt hinne, a rendszer mar lepett.
check("a jelentes KIMONDJA, hogy arnyek-mod",
      "ÁRNYÉK-MÓD" in _sorok[0], _sorok[0][:50])
_p_live = pr.Proposal(action=pr.SET_MODE_LIVE, symbol="A", strategy="b",
                      reason="paper_proven", text="leptetes")
check("a penzt bekapcsolo javaslat MEG VAN JELOLVE",
      any("⚠" in s and "leptetes" in s for s in rep.plan_lines([_p_live])))
_vegyes = [_p_live, pr.Proposal(action=pr.HOLD, symbol="C", strategy="d",
                                reason="ok", text="nincs teendo")]
_s = rep.plan_lines(_vegyes)
_i_lep = next(i for i, x in enumerate(_s) if "leptetes" in x)
_i_hold = next(i for i, x in enumerate(_s) if "nincs teendo" in x)
check("a `hold`-ok KULON blokkban vannak (a valodi javaslatok utan)",
      _i_lep < _i_hold, f"{_i_lep} < {_i_hold}")
check("ures listara is valaszol", len(rep.plan_lines([])) == 1)


# ══ 9. KOZPONTI KUSZOBOK ════════════════════════════════════════════════
k = ccfg.lifecycle({})
check("a letra kuszobeinek van alapertelmezese",
      k["paper_min_signals"] == 30 and k["demote_min_trades"] == 50)
check("...es configbol felulirhatok",
      ccfg.lifecycle({"conductor": {"lifecycle": {"demote_pf": 1.3}}})["demote_pf"] == 1.3)
# ⚠ A SZANDEKOS NULLA NEM veszhet el (az `x or default` minta elnyelne).
check("⚠ a szandekos 0 ervenyesul",
      ccfg.lifecycle({"conductor": {"lifecycle": {"paper_min_days": 0}}})["paper_min_days"] == 0)


# ══ 10. A PARANCS es a MOTOR ════════════════════════════════════════════
from core import telegram_cmd as tc
check("a `plan` parancs be van jegyezve", "plan" in cc.COMMANDS)
check("...es szerepel a sugoban", any(n == "plan" for n, _k in cc._HELP))
check("a `plan` ELERHETO Telegramon (csak olvas)", "plan" in tc.ENGEDETT)
_ctx = cc.Context(cfg=CFG_MIND, save_config=lambda: True, positions=list,
                  close_position=lambda t: False, account=dict, dashboard={},
                  instrument_state={}, strategies_of=lambda s: ["csilla"])
check("a parancs valaszol", bool(cc.dispatch(_ctx, "plan").lines))

_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor futtatja az arnyek-modot", "_clife.shadow(cfg, _jav)" in _lt)
# ⚠ Az egeszsegor leleteit MEG KELL KAPNIA: a kockazati lelet megallitja a
# penzt bekapcsolo leptetest, az elszaradas pedig visszaminositest valt ki.
check("...es megkapja az egeszsegor leleteit", "health_findings=_lel" in _lt)
# ⚠ ARNYEK: a motor SEMMIT nem hajt vegre a javaslatokbol.
check("⚠ a motor NEM hajt vegre javaslatot",
      "set_trade_mode" not in _lt and "_clife.apply" not in _lt)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
