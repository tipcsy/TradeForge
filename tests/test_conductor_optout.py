"""KIZÁRÁS AZ OPTIMALIZÁLÁSBÓL — „van olyan, amit nem fogok optimalizálni".

⚠ MIÉRT KÜLÖN FOGALOM. Az ELVETÉS egy KONKRÉT javaslatról mond nemet, és a
türelmi idő után visszatér. A KIZÁRÁS tartós döntés a celláról: a javaslat létre
sem jön, a sorba be sem kerülhet. A kettő összekeverése azt jelentené, hogy
kéthetente újra el kell vetned ugyanazt — és egy postaláda, amit át lehet
lapozni, a MELLETTE álló fontos javaslatot is elveszíti.

⚠ A FELOLDÁS KÉT SZINTŰ, és a sorrend SZÁMÍT: a cella bejegyzése felülírja a
stratégia alapértelmezését. A „nincs bejegyzés" és a „kifejezetten `false`" NEM
ugyanaz — az elsőt az alap dönti el, a második felülírja. Ezt a különbséget egy
`bool()` vagy egy `x or alap` elmosná: pont ez a projekt visszatérő néma hibája.
"""
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


from conductor import optout as oo
from conductor import paths as cp
from conductor import optqueue as oq
from conductor import report as rep
from core import console_cmd as cc

TMP = Path(tempfile.mkdtemp(prefix="tf_noopt_"))
cp.DIR = TMP / "conductor"


def _cfg():
    return {"pairs": {"GOLD": {"enabled": True, "strategies": ["csilla", "ml_ai"],
                               "run_state": {"csilla": "stopped",
                                             "ml_ai": "stopped"}},
                      "GER40": {"enabled": True, "strategies": ["csilla", "ml_ai"],
                                "run_state": {"csilla": "stopped",
                                              "ml_ai": "stopped"}}}}


_SOF = lambda s: ["csilla", "ml_ai"]


def _ctx(cfg):
    return cc.Context(cfg=cfg, save_config=lambda: True, positions=list,
                      close_position=lambda t: False, account=dict, dashboard={},
                      instrument_state={}, strategies_of=_SOF)


# ══ 1. A FELOLDAS SORRENDJE ════════════════════════════════════════════
c = _cfg()
check("alapbol semmi nincs kizarva", not oo.no_optimize(c, "GOLD", "ml_ai"))
check("...es a forras URES (nem talalt)", oo.forras(c, "GOLD", "ml_ai") == "")

oo.set_strategia(c, "ml_ai", True)
check("strategia-szint: MINDEN paron hat",
      oo.no_optimize(c, "GOLD", "ml_ai") and oo.no_optimize(c, "GER40", "ml_ai"))
check("...de csak arra a strategiara", not oo.no_optimize(c, "GOLD", "csilla"))
check("...es a forras megmondja, honnan jon",
      oo.forras(c, "GOLD", "ml_ai") == oo.FORRAS_STRATEGIA)

# ⚠ EZ A LENYEG: a cella-szintu `false` VISSZAKAPCSOL.
oo.set_cella(c, "GOLD", "ml_ai", False)
check("⚠ a cella-szintu `false` FELULIRJA a strategia `true`-jat",
      not oo.no_optimize(c, "GOLD", "ml_ai"))
check("...a tobbi par valtozatlanul kizarva", oo.no_optimize(c, "GER40", "ml_ai"))
check("...es a forras a CELLA", oo.forras(c, "GOLD", "ml_ai") == oo.FORRAS_CELLA)

oo.set_cella(c, "GOLD", "ml_ai", None)
check("a cella bejegyzes torlesevel visszaall az alap",
      oo.no_optimize(c, "GOLD", "ml_ai")
      and oo.forras(c, "GOLD", "ml_ai") == oo.FORRAS_STRATEGIA)

# ══ 2. ⚠ A `False` NEM „NINCS BEJEGYZES" ═══════════════════════════════
# A projekt visszatero nema hibaja: `x or alapertelmezes` — a False hamis, tehat
# az alapra esne vissza, vagyis a KIKAPCSOLAS kapcsolna BE valamit.
c2 = _cfg()
oo.set_cella(c2, "GOLD", "csilla", False)
check("⚠ a kifejezett `false` NEM tunik el (a forras: cella)",
      oo.cella_ertek(c2, "GOLD", "csilla") is False
      and oo.forras(c2, "GOLD", "csilla") == oo.FORRAS_CELLA)
check("...a nem letezo bejegyzes viszont `None`",
      oo.cella_ertek(c2, "GOLD", "ml_ai") is None)
# Es a configban tenyleg ott a false, nem takaritottuk ki „ures"-kent.
check("...a config is ezt tarolja",
      c2["pairs"]["GOLD"]["no_optimize"] == {"csilla": False},
      str(c2["pairs"]["GOLD"].get("no_optimize")))

# Kezzel atirt JSON: a szoveges „true" meg elmegy, a szemet NEM allit be semmit.
c3 = _cfg()
c3["pairs"]["GOLD"]["no_optimize"] = {"csilla": "true", "ml_ai": "hupp"}
check("a szoveges `true` ertelmezodik", oo.no_optimize(c3, "GOLD", "csilla"))
check("⚠ az ertelmezhetetlen ertek NEM zar ki (nem talalgatunk)",
      not oo.no_optimize(c3, "GOLD", "ml_ai"))

# ⚠ AZ URES TABLA KITAKARODIK: egy `"no_optimize": {}` blokk azt sugallna, hogy
# van itt beallitas — pedig nincs.
c4 = _cfg()
oo.set_cella(c4, "GOLD", "csilla", True)
oo.set_cella(c4, "GOLD", "csilla", None)
check("az ures tabla kikerul a configbol",
      "no_optimize" not in c4["pairs"]["GOLD"], str(c4["pairs"]["GOLD"]))

# ══ 3. A VALTOZAS JELZESE (a hivo csak akkor mentsen) ══════════════════
c5 = _cfg()
check("az elso allitas VALTOZAS", oo.set_cella(c5, "GOLD", "csilla", True) is True)
check("...ugyanaz masodszor NEM",
      oo.set_cella(c5, "GOLD", "csilla", True) is False)
check("nem letezo parra nem irunk",
      oo.set_cella(c5, "NINCSILYEN", "csilla", True) is False)

# ══ 4. A HAZIREND: kizart cellara NINCS optimalizalas-javaslat ═════════
from conductor.policies import lifecycle as lc
from conductor import proposals as pr

_sn = {"symbol": "GOLD", "strategy": "ml_ai", "enabled": True, "intent": "live",
       "mode": "signal", "running": True,
       "today": {}, "live": {"trades": 0, "profit_factor": None},
       "expected": {}, "divergence": {}, "window_days": 90}
c6 = _cfg()
c6["pairs"]["GOLD"]["run_state"]["ml_ai"] = "live"
_p = lc.proposal_for(_sn, c6)
check("hangolatlan cellara optimalizalas a javaslat",
      _p.action == pr.QUEUE_OPTIMIZE, f"{_p.action}:{_p.reason}")
oo.set_cella(c6, "GOLD", "ml_ai", True)
_p2 = lc.proposal_for(_sn, c6)
check("⚠ kizart cellara viszont NINCS javaslat", _p2.action == pr.HOLD,
      f"{_p2.action}:{_p2.reason}")
check("...az OKA pedig a kizaras", _p2.reason == "no_optimize")
# ⚠ ES NEM NEMAN: a cella attol meg hangolatlan, csak TE dontottel ugy.
check("⚠ a szoveg KIMONDJA, hogy a te dontesed miatt hallgat",
      "kizártad" in _p2.text or "excluded" in _p2.text, _p2.text[:90])
check("...a bizonyitek megmarad", isinstance(_p2.evidence, dict))

# ══ 5. AZ OPT-SOR: be sem kerul, es nem is indul ═══════════════════════
oq.reset_for_test()
(cp.DIR / "opt_queue.json").unlink(missing_ok=True)
c7 = _cfg()
oo.set_cella(c7, "GOLD", "ml_ai", True)
check("⚠ a kizart cella BE SEM KERUL a sorba",
      oq.enqueue(c7, "GOLD", "ml_ai", source="teszt") is None and not oq.items())
check("...a nem kizart viszont igen",
      bool(oq.enqueue(c7, "GOLD", "csilla", source="teszt")))

# Ha mar a sorban allt, amikor kizartad: BLOKKOLT lesz, nem eldobott.
# ⚠ A kizaras AKADALY, nem veg: a pipa levetelevel barmikor indithatova valik.
oo.set_cella(c7, "GOLD", "csilla", True)
check("⚠ a mar sorban allo tetel BLOKKOLT lesz",
      oq.blocked_reason(c7, "GOLD", "csilla", _SOF) == "no_optimize")
_st = oq.drain(c7, strategies_of=_SOF)
_e = oq.items()[0]
check("...es a hajtas sem inditja el",
      _e["state"] == oq.BLOCKED and _e["reason"] == "no_optimize"
      and _st["started"] == 0, f"{_e['state']}/{_e.get('reason')}")
check("⚠ ...de NEM dobjuk el (a megszunt cellaval ellentetben)",
      _e["state"] != oq.DROPPED)
_sorok = chr(10).join(rep.optq_lines(oq.items()))
check("a jelentes megmondja, MIERT all",
      "kizárt" in _sorok or "exclude" in _sorok, _sorok[:130])
oo.set_cella(c7, "GOLD", "csilla", False)
check("...a pipa levetele utan ujra indithato",
      oq.blocked_reason(c7, "GOLD", "csilla", _SOF) == "")

# ══ 6. A KOZOS PARANCS-RETEG ═══════════════════════════════════════════
# ⚠ EGY IRASI UT: a felulet pipaja, a konzol es a Telegram ugyanitt ir.
c8 = _cfg()
ctx = _ctx(c8)
check("ures listara beszedes valasz",
      "Nincs kizárva" in chr(10).join(cc.dispatch(ctx, "noopt").lines))
_r = cc.dispatch(ctx, "noopt GOLD ml_ai on")
check("a cella kizarhato parancsbol", _r.ok and oo.no_optimize(c8, "GOLD", "ml_ai"))
check("...a lista mutatja, HONNAN jon",
      "ezen a cellán" in chr(10).join(cc.dispatch(ctx, "noopt").lines))
_r = cc.dispatch(ctx, "noopt ml_ai on")
check("a strategia-szint is allithato", _r.ok and oo.strategia_ertek(c8, "ml_ai") is True)
_r = cc.dispatch(ctx, "noopt GOLD ml_ai auto")
check("az `auto` torli a cella bejegyzest",
      _r.ok and oo.cella_ertek(c8, "GOLD", "ml_ai") is None)
check("⚠ ...es KIMONDJA, mi lett belole", "mostantól" in chr(10).join(_r.lines),
      chr(10).join(_r.lines))
check("kis/nagybetutol fuggetlen par-feloldas",
      cc.dispatch(ctx, "noopt gold csilla on").ok)
check("nem engedelyezett strategiara NEM irunk",
      not cc.dispatch(ctx, "noopt GOLD nincsilyen on").ok)
check("ismeretlen parra sem", not cc.dispatch(ctx, "noopt XX csilla on").ok)
check("ertelmetlen kapcsolora hasznalatot ir",
      not cc.dispatch(ctx, "noopt GOLD csilla hupp").ok)
check("...a valtozatlan allitas nem hazudik valtozast",
      "nincs változás" in chr(10).join(
          cc.dispatch(ctx, "noopt GOLD csilla on").lines).lower())
check("a `noopt` be van jegyezve a parancstablaba", "noopt" in cc.COMMANDS)
# ⚠ A TELEGRAMON NINCS. A kizaras TARTOS config-dontes; a `mode` ugyanezert
# maradt ki. Egy chatuzenetbol nem szabad olyat allitani, aminek a kovetkezmenye
# honapokig fennall, es sehol nem latszik a telefonon.
from core import telegram_cmd as tgc
check("⚠ a `noopt` NINCS a Telegram engedelyezo listajan",
      "noopt" not in tgc.ENGEDETT, str(tgc.ENGEDETT))
check("...es szerepel a sugoban",
      any("noopt" in n for n, _k in cc._HELP))

# ⚠ A MENTES A HIVOE: ha a config nem menthato, azt KIMONDJUK — kulonben
# ujrainditas utan a kizaras visszaallna, es nem ertened, miert.
_c9 = _cfg()
_ctx9 = cc.Context(cfg=_c9, save_config=lambda: False, positions=list,
                   close_position=lambda t: False, account=dict, dashboard={},
                   instrument_state={}, strategies_of=_SOF)
_r = cc.dispatch(_ctx9, "noopt GOLD csilla on")
check("⚠ a sikertelen mentest kimondjuk",
      not _r.ok and any("ment" in s.lower() or "sav" in s.lower() for s in _r.lines),
      chr(10).join(_r.lines))

# ══ 7. A FELULET UGYANEZT AZ UTAT JARJA ════════════════════════════════
_tab = (ROOT / "dashboard" / "conductor_tab.py").read_text(encoding="utf-8")
check("a ful a KOZOS retegen at ir", "_cc.set_no_optimize(" in _tab)
check("⚠ ...es NEM kozvetlenul az optout-ba", "_oo.set_cella(" not in _tab
      and "set_strategia(" not in _tab)
check("a ful a HATALYOS erteket mutatja", "_oo.no_optimize(" in _tab)
check("...es jelzi, ha OROKOLT", "FORRAS_STRATEGIA" in _tab)
check("a jelmagyarazat elmondja a ket szintet",
      "cond.tab.noopt.legend" in _tab)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
