"""ÉLETCIKLUS-LÉTRA — hol tart egy cella, és mi a következő lépése.

⚠ EZ AZ A FELADATKÖR, AMI A MÁTRIXOT KÉZBEN TARTHATÓVÁ TESZI. 10-12 instrumentum
× 4-5 stratégia = több tucat cella, mindegyik saját paraméterkészlettel,
minősítéssel és múlttal. Ezeket egyenként, kapcsolónként fejben tartani nem
lehet — de ÁLLAPOTKÉNT igen: minden cella a létra EGY fokán áll, és a fok
megmondja, mi a következő kérdés vele kapcsolatban.

── A LÉTRA ────────────────────────────────────────────────────────────────

    STOPPED ──► UNTUNED ──► PAPER ──► LIVE
                (nincs      (csak     (valódi
                 mentett     jelzés)   kötés)
                 készlet)
                    ▲           ▲         │
                    └───────────┴─────────┘
                        visszaminősítés

⚠ MIÉRT NINCS KÜLÖN „FELEZETT ÉLŐ" FOK, pedig a terv említi. A méretezés
kockázatcsökkentő presetje (`core/rr_state.py`) **instrumentum-szintű**, nem
cella-szintű: egy páron a `wpr_sma`-t nem lehet felezni úgy, hogy az `ml_ai`
teljes mérettel menjen. Egy kitalált „felezett élő" fok tehát olyan állapotot
ígérne, amit a rendszer nem tud előállítani — a létra ehelyett a BIZONYÍTÉK
mennyiségét viszi külön mezőben (`evidence`), és a jelentés ezt mondja ki.

── ⚠ MIT BIZONYÍT A PAPÍR, ÉS MIT NEM ─────────────────────────────────────
A „csak jelzés" módban a motor mindent kiszámol, de nem köt — a `trades.csv`
`signal` sorai ezért **P&L nélküliek**. A papírkereskedés tehát AKTIVITÁST
bizonyít (a stratégia jelez, a várt ütemben, a kapuk átengedik), NYERESÉGESSÉGET
nem. Aki papírból következtet hozamra, a backtestjét méri újra, csak lassabban.
Ezért a papír → élő lépés feltétele: aktivitás + a MENTETT out-of-sample
minősítés + tiszta egészség — és MINDIG emberi jóváhagyás.

⚠ ÉS NEM A WALK-FORWARD VIZSGAABLAK EGYEDÜL. A mentett minősítés azokból az
ablakokból jön, amiken az optimalizáló ÉPPEN választott (mérve: 2,51× felfújás)
— ezért önmagában sosem elég, csak a másik két feltétellel együtt.

── AZ F1-BEN EZ ÁRNYÉK-MÓD ────────────────────────────────────────────────
A házirend JAVASLATOT ad, és a javaslat a krónikába kerül (`kind="shadow"`).
Semmit nem hajt végre. Így mérhetővé válik, hogy a létra döntései jók
lettek-e — a terv szerint az önállóság (L2+) csak ezután adható meg.
"""

from __future__ import annotations

import logging

from core.i18n import t as _t
from core.overview import SEV_RISK

from conductor import config as _ccfg
from conductor import expectation as _exp
from conductor import telemetry as _tlm
from conductor.proposals import (HOLD, QUEUE_OPTIMIZE, SET_MODE_LIVE,
                                 SET_MODE_SIGNAL, Proposal)

log = logging.getLogger(__name__)

# ── A FOKOK (stabil kódok) ───────────────────────────────────────────────
STOPPED = "stopped"     # nem fut (leállítva vagy nem engedélyezett)
UNTUNED = "untuned"     # fut, de nincs mentett paraméterkészlet
PAPER   = "paper"       # fut, „csak jelzés" módban
LIVE    = "live"        # fut, valódi kötéssel

STAGES = (STOPPED, UNTUNED, PAPER, LIVE)


def stage_of(sn: dict) -> str:
    """Egy cella FOKA a pillanatképből.

    ⚠ A MOTOR KÉPLETE DÖNTI EL, hogy „fut"-e: engedélyezett ÉS szándék=live. A
    szándék önmagában nem elég — a `run_state` bejegyzés akkor is ott marad, ha
    a stratégiát közben kikapcsoltad a páron."""
    if not sn.get("running"):
        return STOPPED
    if (sn.get("expected") or {}).get("source") != "saved":
        return UNTUNED
    return PAPER if sn.get("mode") == "signal" else LIVE


def _ev(sn: dict, extra: dict = None) -> dict:
    """A javaslat BIZONYÍTÉKA: a döntést hozó számok."""
    elo = sn.get("live") or {}
    d = sn.get("divergence") or {}
    ki = {"live_trades": elo.get("trades"), "live_pf": elo.get("profit_factor"),
          "live_per_day": elo.get("trades_per_day"),
          "expected_per_day": (sn.get("expected") or {}).get("trades_per_day"),
          "activity_ratio": d.get("activity_ratio"),
          "window_days": sn.get("window_days")}
    ki.update(extra or {})
    return ki


# ---------------------------------------------------------------------------
# A SZABÁLYOK
# ---------------------------------------------------------------------------

def _untuned(sn, k, health_codes) -> Proposal:
    """Hangolatlanul fut → optimalizálást javaslunk.

    ⚠ NEM ÁLLÍTJUK LE. A stratégia a SAJÁT alapértékeivel fut, ami a projekt
    dokumentált döntése (egy új stratégia ne legyen használhatatlan, amíg le nem
    fut rá egy több órás optimalizálás). De nem is hagyjuk szó nélkül: egy
    hangolt és egy hangolatlan cella ránézésre egyforma."""
    return Proposal(action=QUEUE_OPTIMIZE, symbol=sn["symbol"],
                    strategy=sn["strategy"], reason="untuned",
                    from_stage=UNTUNED, to_stage=UNTUNED,
                    text=_t("conductor.plan.untuned", symbol=sn["symbol"],
                            strategy=sn["strategy"]),
                    evidence=_ev(sn))


def _paper(sn, k, health_codes) -> Proposal:
    """Papír → élő, HA az aktivitás és a minősítés is megvan."""
    w = _tlm.window(sn["symbol"], sn["strategy"],
                    days=max(1, int(k["paper_min_days"]) * 3))
    jelek, napok = int(w["signals"]), int(w["signal_days"])
    kell_j, kell_n = int(k["paper_min_signals"]), int(k["paper_min_days"])
    ev = _ev(sn, {"paper_signals": jelek, "paper_days": napok,
                  "need_signals": kell_j, "need_days": kell_n,
                  "engine_days": w["engine_days"]})

    if jelek < kell_j or napok < kell_n:
        return Proposal(action=HOLD, symbol=sn["symbol"], strategy=sn["strategy"],
                        reason="paper_evidence", from_stage=PAPER, to_stage=PAPER,
                        text=_t("conductor.plan.paper_wait", symbol=sn["symbol"],
                                strategy=sn["strategy"], n=jelek, need=kell_j,
                                days=napok, need_days=kell_n),
                        evidence=ev)

    # ⚠ A KOCKÁZATI LELET MEGÁLLÍTJA A LÉPTETÉST. Pénzt bekapcsolni olyan cellán,
    # amiről ÉPP azt mondja az egészségőr, hogy valami nincs rendben, a
    # leggyorsabb út a kimagyarázhatatlan veszteséghez.
    if health_codes:
        return Proposal(action=HOLD, symbol=sn["symbol"], strategy=sn["strategy"],
                        reason="health_blocks", from_stage=PAPER, to_stage=PAPER,
                        text=_t("conductor.plan.health_blocks", symbol=sn["symbol"],
                                strategy=sn["strategy"],
                                codes=", ".join(sorted(health_codes))),
                        evidence={**ev, "health": sorted(health_codes)})

    return Proposal(action=SET_MODE_LIVE, symbol=sn["symbol"],
                    strategy=sn["strategy"], reason="paper_proven",
                    from_stage=PAPER, to_stage=LIVE,
                    text=_t("conductor.plan.promote", symbol=sn["symbol"],
                            strategy=sn["strategy"], n=jelek, days=napok),
                    evidence=ev)


def _live(sn, k, health_codes) -> Proposal:
    """Élő cella: kell-e visszaminősítés?"""
    elo = sn.get("live") or {}
    d = sn.get("divergence") or {}
    n = int(elo.get("trades") or 0)
    pf = elo.get("profit_factor")
    ev = _ev(sn, {"demote_pf": k["demote_pf"],
                  "demote_min_trades": k["demote_min_trades"]})

    # ⚠ ELSZÁRADÁS: az egészségőr leletét NEM SZÁMOLJUK ÚJRA — egy helyen van a
    # küszöb (`health.dried_up_*`), különben a lelet és a döntés mást mondana.
    if "dried_up" in health_codes:
        return Proposal(action=SET_MODE_SIGNAL, symbol=sn["symbol"],
                        strategy=sn["strategy"], reason="dried_up",
                        from_stage=LIVE, to_stage=PAPER,
                        text=_t("conductor.plan.demote_dried", symbol=sn["symbol"],
                                strategy=sn["strategy"],
                                pct=f"{(d.get('activity_ratio') or 0) * 100:.0f}%"),
                        evidence=ev)

    # ⚠ ROMLÁS — DE CSAK ELÉG BIZONYÍTÉKKAL. Kis mintából visszaminősíteni
    # zajra reagálás: a mérés szerint 15 kötésen egy 1,10-es PF-ű stratégia a
    # minták 4,5%-ában PF>3-at mutat — és ugyanennyire tud lefelé is tévedni.
    if n >= int(k["demote_min_trades"]) and pf is not None \
            and float(pf) < float(k["demote_pf"]):
        return Proposal(action=SET_MODE_SIGNAL, symbol=sn["symbol"],
                        strategy=sn["strategy"], reason="degraded",
                        from_stage=LIVE, to_stage=PAPER,
                        text=_t("conductor.plan.demote_pf", symbol=sn["symbol"],
                                strategy=sn["strategy"], pf=f"{float(pf):.2f}",
                                need=f"{float(k['demote_pf']):.2f}", n=n),
                        evidence=ev)

    # Avult készlet → optimalizálás (a kereskedés megy tovább).
    kor = _kor_nap(sn)
    if kor is not None and kor > int(k["stale_params_days"]):
        return Proposal(action=QUEUE_OPTIMIZE, symbol=sn["symbol"],
                        strategy=sn["strategy"], reason="stale_params",
                        from_stage=LIVE, to_stage=LIVE,
                        text=_t("conductor.plan.stale", symbol=sn["symbol"],
                                strategy=sn["strategy"], days=int(kor)),
                        evidence={**ev, "params_age_days": int(kor)})

    return Proposal(action=HOLD, symbol=sn["symbol"], strategy=sn["strategy"],
                    reason="ok", from_stage=LIVE, to_stage=LIVE,
                    text=_t("conductor.plan.live_ok", symbol=sn["symbol"],
                            strategy=sn["strategy"], n=n,
                            pf=("-" if pf is None else f"{float(pf):.2f}")),
                    evidence=ev)


def _kor_nap(sn: dict):
    """A mentett készlet kora napokban (vagy None)."""
    from core.overview import _age_days
    try:
        return _age_days((sn.get("expected") or {}).get("optimized_at"))
    except Exception:
        return None


_SZABALY = {UNTUNED: _untuned, PAPER: _paper, LIVE: _live}


# ---------------------------------------------------------------------------
# A TELJES LÉTRA
# ---------------------------------------------------------------------------

def proposal_for(sn: dict, cfg: dict, health_findings=None) -> Proposal:
    """EGY cella következő lépése.

    `health_findings`: az egészségőr leletei (a KOCKÁZATI szintűek megállítják a
    pénzt bekapcsoló léptetést, az `dried_up` pedig visszaminősítést vált ki)."""
    k = _ccfg.lifecycle(cfg)
    fok = stage_of(sn)
    if fok == STOPPED:
        return Proposal(action=HOLD, symbol=sn["symbol"], strategy=sn["strategy"],
                        reason="stopped", from_stage=STOPPED, to_stage=STOPPED,
                        text=_t("conductor.plan.stopped", symbol=sn["symbol"],
                                strategy=sn["strategy"]),
                        evidence=_ev(sn))

    kodok = {f.get("code") for f in (health_findings or [])
             if f.get("symbol") == sn["symbol"]
             and f.get("strategy") == sn["strategy"]
             and (f.get("sev") == SEV_RISK or f.get("code") == "dried_up")}
    return _SZABALY[fok](sn, k, kodok)


def proposals(cfg: dict, *, strategies_of=None, health_findings=None,
              day=None, days: int = 90) -> list:
    """MINDEN cella javaslata. A `hold`-ok is benne vannak: az „miért NEM
    lépünk" ugyanolyan válasz, mint a lépés — és az árnyék-mód mérésekor
    pontosan ez a kérdés."""
    from conductor import snapshot as _snap

    ki = []
    for sn in _snap.cells(cfg, strategies_of=strategies_of, day=day, days=days):
        try:
            ki.append(proposal_for(sn, cfg, health_findings))
        except Exception as ex:
            log.warning("conductor.lifecycle: %s/%s — a javaslat elszállt: %s",
                        sn.get("symbol"), sn.get("strategy"), ex)
    return ki


def shadow(cfg: dict, javaslatok: list) -> int:
    """ÁRNYÉK-MÓD: a javaslatok krónikába írása — VÉGREHAJTÁS NÉLKÜL.

    Visszaad: hány sor keletkezett.

    ⚠ A `hold` NEM KERÜL BE. Egy „nincs teendő" sor cellánként naponta annyi
    zajt adna, amiben a valódi javaslatok elvesznének — és épp azok mérése a
    cél. A `hold` a jelentésben látszik, ahol a kérdés az AKTUÁLIS állapot."""
    from conductor import journal as _j

    ism = int(_ccfg.health(cfg)["repeat_days"])
    n = 0
    for p in (javaslatok or []):
        if p.action == HOLD or not p.valid():
            continue
        if not _j.ujdonsag(p.code, p.symbol, p.strategy, ism):
            continue
        if _j.write(_j.KIND_SHADOW, p.code, p.text, sev="info",
                    symbol=p.symbol, strategy=p.strategy,
                    data=p.as_dict()):
            n += 1
    return n
