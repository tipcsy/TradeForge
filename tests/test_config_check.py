"""Config-KOHERENCIA ellenorzo (P2, v2.0.0) — a nemán hatastalan beallitasok.

LELET (2026-08-05). Egy 11 paros configban OT olyan beallitas volt, ami
szintaktikailag rendben van, a program elfogadja, megsem azt csinalja, amit
mutat. Egyik sem okozott hibat, kivetelt vagy naplobejegyzest. Pelda: az UsaInd
`Piac` kapuja `reduce`-ra volt allitva (a felulet igy is mutatta), de mivel a
paron nem volt kivalasztva piac-eloszuro, a kapunak NEM VOLT MIT MERNIE.

A modul NEM javit — csak mer es szol (mint a `core/config_freshness.py`). A
javitas mindig felhasznaloi dontes: masik a helyes valasz a „kapcsold be" es a
„vedd ki" kozott.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import json

from core import config_check as cc

# Teljes koltseg-kulcskeszlet: kulonben MINDEN teszt-par kapna egy missing_costs
# leletet, es elnyomna azt, amit epp merunk.
COSTS = {"commission_per_lot": 0.0, "swap_long_per_lot": -1.0,
         "swap_short_per_lot": 0.5}

# Ugyanezert kell a MERETEZESI kulcskeszlet is (v2.17.0 ota lelet a hianyuk):
# enelkul minden teszt-par kapna egy `missing_sizing`-ot.
SIZING = {"point_size": 0.0001, "pv1_point": 1.0}


def pair(**kw):
    return {**COSTS, **SIZING, "enabled": True, **kw}


def codes(cfg, code=None):
    fs = cc.check(cfg)
    return [f for f in fs if code is None or f["code"] == code]


BASE = {"strategy": {"name": "wpr_sma"},
        "available_strategies": {"wpr_sma": True, "ml_ai": True},
        "trading": {}}


# ══ 1. Piac-kapu osztalyozo nelkul ════════════════════════════════════════

CFG = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                  gates={"market": {"wpr_sma": "reduce"}})})
f = codes(CFG, "market_gate_no_classifier")
check_("A LELET: bekapcsolt Piac-kapu, de nincs piac-eloszuro -> figyelmeztetes",
       len(f) == 1 and f[0]["level"] == cc.WARN, str(len(f)))
check_("a lelet a szimbolumot is hordozza (a felulet ki tudja emelni)",
       f and f[0]["symbol"] == "X")
check_("az uzenet MEGMONDJA a ket kiutat", f and "market_strategy" in f[0]["message"]
       and "'none'" in f[0]["message"])

CFG_OK = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                     market_strategy="regime",
                                     gates={"market": {"wpr_sma": "reduce"}})})
check_("osztalyozoval NINCS lelet", codes(CFG_OK, "market_gate_no_classifier") == [])

CFG_OFF = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                      gates={"market": {"wpr_sma": "none"}})})
check_("kikapcsolt ('none') kapunal NINCS lelet — nincs mit igerni",
       codes(CFG_OFF, "market_gate_no_classifier") == [])

# A kapu alapertelmezese `none`, tehat egy sima par sem adhat leletet.
check_("sima par (nincs gates szekcio) -> nincs Piac-lelet",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma"])}),
             "market_gate_no_classifier") == [])

# Csak a paron ENGEDELYEZETT strategiakra nezunk (a nem futora ertelmetlen).
CFG_NE = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                     gates={"market": {"ml_ai": "block"}})})
check_("nem engedelyezett strategia kapuja nem ad Piac-leletet",
       codes(CFG_NE, "market_gate_no_classifier") == [])

# ══ 2. TF-kapu kikapcsolt figyelovel ══════════════════════════════════════

CFG_TF = dict(BASE, tf_align={"enabled": False, "timeframes": [1, 5], "sma_period": 50},
              pairs={"X": pair(strategies=["wpr_sma"],
                               gates={"tf_align": {"wpr_sma": "block"}})})
check_("bekapcsolt TF-kapu + KIKAPCSOLT figyelo -> figyelmeztetes",
       len(codes(CFG_TF, "tf_gate_disabled_watcher")) == 1)

CFG_TF_OK = dict(BASE, tf_align={"enabled": True, "timeframes": [1, 5], "sma_period": 50},
                 pairs={"X": pair(strategies=["wpr_sma"],
                                  gates={"tf_align": {"wpr_sma": "block"}})})
check_("bekapcsolt figyelovel NINCS lelet",
       codes(CFG_TF_OK, "tf_gate_disabled_watcher") == [])

# ══ 3. Elavult strategia-hivatkozas ═══════════════════════════════════════

CFG_STALE = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                        run_state={"wpr_sma": "live", "ml_ai": "live"})})
f = codes(CFG_STALE, "stale_strategy_key")
check_("a P0 gyokere: 'live' szandek egy nem engedelyezett strategian -> lelet",
       len(f) == 1 and "ml_ai" in f[0]["message"], str(f))
check_("...de csak INFO (nem hiba: ha ujra bekapcsolod, ervenyes lesz)",
       f and f[0]["level"] == cc.INFO)

CFG_STOPPED = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                          run_state={"wpr_sma": "live",
                                                     "ml_ai": "stopped"})})
check_("'stopped' bejegyzes NEM lelet (nem iger semmit)",
       codes(CFG_STOPPED, "stale_strategy_key") == [])

CFG_MODE = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                       strategy_mode={"ml_ai": "signal"})})
check_("mas strategia-terkepek is szamitanak (strategy_mode)",
       len(codes(CFG_MODE, "stale_strategy_key")) == 1)

CFG_UNKNOWN = dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                          run_state={"regi_neve": "live"})})
check_("ISMERETLEN (nem regisztralt) nevre nem szolunk — az mas kerdes",
       codes(CFG_UNKNOWN, "stale_strategy_key") == [])

# ══ 4. Hianyzo koltseg-kulcsok ════════════════════════════════════════════

CFG_COST = dict(BASE, pairs={"X": {"enabled": True, "strategies": ["wpr_sma"]}})
f = codes(CFG_COST, "missing_costs")
check_("hianyzo koltseg-kulcs -> figyelmeztetes (a backteszt 0-val szamolna)",
       len(f) == 1 and f[0]["level"] == cc.WARN)
check_("az uzenet a JAVITO parancsot is megadja",
       f and "refresh_costs.py --write" in f[0]["message"])
check_("teljes koltsegkeszlettel nincs lelet",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma"])}), "missing_costs") == [])
check_("a 0.0 ERVENYES ertek (nem 'hianyzik')",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                         commission_per_lot=0.0)}),
             "missing_costs") == [])

# ══ 5. Holt napi-limit kulcs ══════════════════════════════════════════════

check_("usd>0 mellett a pct HOLT -> info",
       len(codes(dict(BASE, trading={"daily_loss_limit_usd": 70.0,
                                     "daily_loss_limit_pct": 0.015}),
                 "daily_limit_pct_dead")) == 1)
check_("usd=0 eseten a pct EL -> nincs lelet",
       codes(dict(BASE, trading={"daily_loss_limit_usd": 0,
                                 "daily_loss_limit_pct": 0.015}),
             "daily_limit_pct_dead") == [])
check_("csak usd (nincs pct) -> nincs lelet",
       codes(dict(BASE, trading={"daily_loss_limit_usd": 70.0}),
             "daily_limit_pct_dead") == [])

# ══ 6. A regi tf_align.gate lista ARNYEKOLASA ═════════════════════════════
#
# Ma nem all fenn — de ha valaki felvesz egy globalis `gates.tf_align`-t, a
# meglevo per-par listak NEMAN hatastalanna valnak. Ez a jelzes sporolja meg a
# keresest.

CFG_SHADOW = dict(BASE, gates={"tf_align": {"default": "none"}},
                  pairs={"X": pair(strategies=["wpr_sma"],
                                   tf_align={"gate": ["wpr_sma"]})})
check_("globalis gates.tf_align ARNYEKOLJA a regi listat -> figyelmeztetes",
       len(codes(CFG_SHADOW, "legacy_tf_gate_shadowed")) == 1)
check_("globalis gates.tf_align NELKUL a regi lista EL -> nincs lelet",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma"],
                                         tf_align={"gate": ["wpr_sma"]})}),
             "legacy_tf_gate_shadowed") == [])
CFG_SHADOW_OK = dict(BASE, gates={"tf_align": {"default": "none"}},
                     pairs={"X": pair(strategies=["wpr_sma"],
                                      tf_align={"gate": ["wpr_sma"]},
                                      gates={"tf_align": {"wpr_sma": "block"}})})
check_("par-szintu gates.tf_align eseten nincs arnyekolas-lelet (a par nyer)",
       codes(CFG_SHADOW_OK, "legacy_tf_gate_shadowed") == [])

# ══ 7. Tobb KOTO strategia egy paron, hazirend nelkul ═════════════════════

# v2.0.0 ota az ALAP `no_opposite`, tehat ez a lelet csak akkor jon, ha valaki
# KIFEJEZETTEN visszaallitja az `independent`-et.
CFG_MULTI = dict(BASE, trading={"same_symbol_policy": "independent"},
                 pairs={"X": pair(strategies=["wpr_sma", "ml_ai"])})
f = codes(CFG_MULTI, "independent_multi_strategy")
check_("ket VALODI koto strategia + KIFEJEZETT 'independent' -> info",
       len(f) == 1 and f[0]["level"] == cc.INFO, str(f))
check_("az uzenet a ket szigoritast is megnevezi",
       f and "one_per_symbol" in f[0]["message"] and "no_opposite" in f[0]["message"])

check_("az UJ ALAPPAL (no_opposite) mar nincs lelet — a hazirend ved",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma", "ml_ai"])}),
             "independent_multi_strategy") == [])

# EZ A LENYEG: amig az egyik 'csak jelzes', nem all fenn a kockazat -> nem
# zajongunk, meg kifejezett `independent` mellett sem.
CFG_SIGNAL = dict(BASE, trading={"same_symbol_policy": "independent"},
                  pairs={"X": pair(strategies=["wpr_sma", "ml_ai"],
                                   strategy_mode={"ml_ai": "signal"})})
check_("'csak jelzes' modu masodik strategianal NINCS lelet (nem all fenn)",
       codes(CFG_SIGNAL, "independent_multi_strategy") == [])

for pol in ("one_per_symbol", "no_opposite"):
    check_(f"szigoritott hazirenddel ({pol}) nincs lelet",
           codes(dict(BASE, trading={"same_symbol_policy": pol},
                      pairs={"X": pair(strategies=["wpr_sma", "ml_ai"])}),
                 "independent_multi_strategy") == [])
check_("per-par hazirend is szamit (a globalis 'independent' ellenere)",
       codes(dict(BASE, trading={"same_symbol_policy": "independent"},
                  pairs={"X": pair(strategies=["wpr_sma", "ml_ai"],
                                   same_symbol_policy="no_opposite")}),
             "independent_multi_strategy") == [])

# ══ 7b. 'Csak jelzes' mod, amit nem latsz (P3) ════════════════════════════
#
# A `signal` mod CELJA a megfigyeles. Kikapcsolt vizualizacioval + kikapcsolt
# kotes-reteggel viszont vak: pont azt a celt nem szolgalja, amiert bekapcsoltad.

INVIS = dict(BASE, pairs={"X": pair(strategies=["wpr_sma", "ml_ai"],
                                    strategy_mode={"ml_ai": "signal"},
                                    strategy_viz={"ml_ai": False},
                                    strategy_trades={"ml_ai": False},
                                    run_state={"wpr_sma": "live", "ml_ai": "live"})})
f = codes(INVIS, "signal_mode_invisible")
check_("futo 'csak jelzes' + minden rajz KI -> info", len(f) == 1, str(f))
check_("az uzenet megmondja, MIERT baj", f and "'csak jelzés' épp ezért van" in f[0]["message"])

for _on in ("strategy_viz", "strategy_trades"):
    _layers = {"strategy_viz": {"ml_ai": False}, "strategy_trades": {"ml_ai": False}}
    _layers[_on] = {"ml_ai": True}
    _cfg = dict(BASE, pairs={"X": pair(strategies=["wpr_sma", "ml_ai"],
                                       strategy_mode={"ml_ai": "signal"},
                                       run_state={"ml_ai": "live"}, **_layers)})
    check_(f"ha a ket reteg BARMELYIKE latszik ({_on}) -> nincs lelet",
           codes(_cfg, "signal_mode_invisible") == [])

check_("MEGALLITOTT strategianal nincs lelet (ott rendben a kikapcsolt rajz)",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma", "ml_ai"],
                                         strategy_mode={"ml_ai": "signal"},
                                         strategy_viz={"ml_ai": False},
                                         strategy_trades={"ml_ai": False},
                                         run_state={"ml_ai": "stopped"})}),
             "signal_mode_invisible") == [])
check_("VALODI kotes modu strategianal nincs lelet (nem megfigyelesrol szol)",
       codes(dict(BASE, pairs={"X": pair(strategies=["wpr_sma", "ml_ai"],
                                         strategy_viz={"ml_ai": False},
                                         strategy_trades={"ml_ai": False},
                                         run_state={"ml_ai": "live"})}),
             "signal_mode_invisible") == [])

# OSSZEVONAS: tiz par -> EGY sor. Kulonben minden inditasnal tiz azonos uzenet
# menne ki, es a jelzes pont attol valna lathatatlanna.
_many = {f"P{i}": pair(strategies=["wpr_sma", "ml_ai"],
                       strategy_mode={"ml_ai": "signal"},
                       strategy_viz={"ml_ai": False},
                       strategy_trades={"ml_ai": False},
                       run_state={"ml_ai": "live"}) for i in range(10)}
f = codes(dict(BASE, pairs=_many), "signal_mode_invisible")
check_("tiz erintett par -> EGY osszevont lelet (nem tiz)", len(f) == 1, str(len(f)))
check_("az osszevont lelet felsorolja a parokat",
       f and "10 páron" in f[0]["message"] and "P0" in f[0]["message"] and
       "P9" in f[0]["message"])
check_("osszevonasnal nincs egyetlen szimbolumhoz kotve", f and f[0]["symbol"] is None)
check_("EGY erintett parnal viszont ott a szimbolum",
       (lambda g: g and g[0]["symbol"] == "X")(codes(INVIS, "signal_mode_invisible")))

# ══ 8. Robusztussag: a vizsgalat SOSEM buktathatja az indulast ════════════

check_("ures cfg -> nem robban", isinstance(cc.check({}), list))
check_("None cfg -> nem robban", isinstance(cc.check(None), list))
check_("a pairs._comment SZTRING kulcs nem robbant",
       isinstance(cc.check(dict(BASE, pairs={"_comment": "szoveg",
                                             "X": pair(strategies=["wpr_sma"])})), list))
check_("hibas pairs tipus -> nem robban", isinstance(cc.check({"pairs": []}), list))

# Egy elszallo ellenorzes se vigye magaval a tobbit.
_orig = cc._CHECKS


def _boom(cfg, out):
    raise RuntimeError("szandekos")


try:
    cc._CHECKS = (_boom, cc._check_costs)
    _r = cc.check(dict(BASE, pairs={"X": {"enabled": True, "strategies": ["wpr_sma"]}}))
    check_("egy elszallo ellenorzes nem viszi magaval a tobbit",
           len(_r) == 1 and _r[0]["code"] == "missing_costs", str(_r))
finally:
    cc._CHECKS = _orig

# ══ 9. Bekotes: MINDEN belepesi pont lassa ════════════════════════════════

nsrc = (ROOT / "main.py").read_text(encoding="utf-8")
_load = nsrc.split("def load_cfg")[1].split("\ndef ")[0]
check_("main.py: a load_cfg futtatja az ellenorzest (kozos seam)",
       "config_check.log_findings(cfg)" in _load)
check_("main.py: az ellenorzes NEM gatolhatja az indulast",
       "except Exception:" in _load)

# A naplozas tenylegesen kiir (es a szintet is megkulonbozteti)
import logging


class _Cap:
    def __init__(self):
        self.w, self.i = [], []

    def warning(self, msg, *a):
        self.w.append(msg % a if a else msg)

    def info(self, msg, *a):
        self.i.append(msg % a if a else msg)


cap = _Cap()
out = cc.log_findings(dict(BASE, trading={"daily_loss_limit_usd": 70.0,
                                          "daily_loss_limit_pct": 0.015},
                           pairs={"X": {"enabled": True, "strategies": ["wpr_sma"]}}),
                      logger=cap)
check_("log_findings: a WARN szintu figyelmeztetesbe megy",
       any("Euro" not in x and "koltseg" in x for x in cap.w) or
       any("költség" in x for x in cap.w), str(cap.w)[:120])
check_("log_findings: az INFO szintu info-ba megy",
       any("HOLT" in x for x in cap.i), str(cap.i)[:120])
# ⚠ NEM A TELJES SZAMOT ALLITJUK. Korabban `len(out) == 3` allt itt, es azt
# MINDEN uj ellenorzes eltorte (legutobb az `untuned_pair`, 2026-09-05) — pedig
# a teszt targya a log_findings VISSZATERESE, nem az, hany ellenorzes letezik.
# A konkret harom lelet meglete viszont valodi allitas, azt megtartjuk.
_kell = {"missing_costs", "sizing_missing", "daily_limit_dead_pct"}
_van = {f["code"] for f in out}
check_("log_findings: visszaadja a leleteket is",
       len(out) >= 3 and bool(_kell & _van), f"{len(out)} · {sorted(_van)}")
# A „nem zajong" ellenorzes is kod-szinten: az `untuned_pair` egy szintetikus
# configon MINDIG tuzel (nincs hozza mentett keszlet), es az nem zaj, hanem igaz.
_csend = cc.log_findings(dict(BASE, pairs={"X": pair(strategies=["wpr_sma"])}),
                         logger=_Cap())
check_("lelet nelkul NEM zajong",
       [f for f in _csend if f["code"] != "untuned_pair"] == [],
       str([f["code"] for f in _csend]))

# ══ 10. A VALODI config: a modul a 08-05-i leleteket adja vissza ══════════

from strategy.settings import load_config

real = load_config(ROOT / "config.json")
real_codes = {f["code"] for f in cc.check(real)}
check_("az eles configon lefut", isinstance(cc.check(real), list))
# A P2-kor UTAN: az inert Piac-kapu kikerult, a hazirend beallt. Ami maradt, az a
# ket TUDOTT, felhasznaloi dontesre varo tetel (Euro50 koltsegek + a holt pct).
check_("az UsaInd inert Piac-kapuja MEGSZUNT (P2 #1 lezarva)",
       "market_gate_no_classifier" not in real_codes, str(sorted(real_codes)))
check_("a hazirend beallt -> nincs 'independent' lelet (P2 #3 lezarva)",
       "independent_multi_strategy" not in real_codes, str(sorted(real_codes)))
# ⚠ A `stale_strategy_key` NEM hiba, es NEM allitunk a hianyara. A modul
# szandekosan megorzi egy KIKAPCSOLT strategia beallitasait, hogy
# visszakapcsolaskor ervenyes maradjon a korabbi valasztas — tehat amint a user
# kivesz egy strategiat egy parbol (2026-08-08: ml_ai mindenhonnan), ez a lelet
# jogosan megjelenik. Egy ELO configra vonatkozo allitas amugy is torekeny: a
# user barmikor valtoztathat rajta. Amit ALLITANI erdemes: a szint INFO maradjon
# (nem figyelmeztetes), tehat ne riogasson egy szandekos beallitas miatt.
_stale = [f for f in cc.check(real) if f["code"] == "stale_strategy_key"]
check_("az elavult strategia-hivatkozas INFO szintu (nem WARN)",
       all(f["level"] == cc.INFO for f in _stale), f"{len(_stale)} lelet")

from core import symbol_policy as _sp
check_("az eles configban KIFEJEZETTEN ott a hazirend (nem csak alapertelmezes)",
       (real.get("trading") or {}).get("same_symbol_policy") == _sp.NO_OPPOSITE,
       str((real.get("trading") or {}).get("same_symbol_policy")))
_ex = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
check_("a pelda-config is a no_opposite-ot mutatja",
       (_ex.get("trading") or {}).get("same_symbol_policy") == _sp.NO_OPPOSITE)

# ══ A CELAR es a KILEPESI PRESET osszhangja ════════════════════════════════
# ⚠ MERVE (2026-08-23) — a ketto NEM fuggetlen, es ELLENTETES iranyba lejt.
# UsaInd, ugyanaz az ablak:
#     TP        BE+trailing     kockazatcsokkentes NELKUL
#     1,5R          +870              +1870
#     2,7R         +1991              +1587
#     3,0R         +2080              +1557
# Trailinggel a HOSSZU celar a jo (a stop koveti az arat, hagyja futni a
# nyertest); trailing NELKUL a ROVID (a tavoli celarig gyakran nem er el az ar).
#
# ⚠ Ez a szabaly egy VALODI tevedesbol szuletett: eloszor a kockazatcsokkentes
# NELKULI sopresbol javasoltam az UsaInd celaranak 2,7 -> 1,5 atallitasat. A par
# viszont BE+trailinggel fut — a valtoztatas 1121 DOLLARBA kerult volna. Nem
# overfitting volt, hanem KONFIGURACIO-ELTERES.
from core.config_check import (tp_preset_conflict, check_with_state,
                               TP_LONG, TP_SHORT)

check_("hosszu celar VEDELEM NELKUL -> lelet",
      bool(tp_preset_conflict("none", 2.7)), str(tp_preset_conflict("none", 2.7))[:60])
check_("...es kimondja, hogy rovidebb kellene",
      "RÖVIDEBB" in (tp_preset_conflict("none", 2.7) or ""))
check_("rovid celar MOZGO stop mellett -> lelet",
      bool(tp_preset_conflict("off", 1.0)))
check_("...es kimondja, hogy hosszabb kellene",
      "HOSSZABB" in (tp_preset_conflict("off", 1.0) or ""))

# ⚠ Az OSSZHANGBAN levo parositasok NEM adnak leletet — kulonben a figyelmeztetes
# mindenutt ott ulne, es pont ettol valna lathatatlanna.
check_("hosszu celar + trailing -> NINCS lelet", tp_preset_conflict("off", 2.7) is None)
check_("rovid celar + nincs trailing -> NINCS lelet",
      tp_preset_conflict("none", 1.5) is None)
for _p in ("halving", "shield", "fibo", "thirds", "risky"):
    check_(f"a stopot mozgato preset ({_p}) is szamit annak",
          tp_preset_conflict(_p, 1.0) is not None)

# Hibas/hianyzo ertek ne dontson el egy ellenorzest.
for _bad in (None, "abc", 0, -1):
    check_(f"hibas celar ({_bad!r}) -> nincs lelet, nincs kivetel",
          tp_preset_conflict("off", _bad) is None)

# ⚠ A `check()` TISZTA marad: a fajlt olvaso ellenorzes KULON fuggvenyben van.
import inspect as _insp3
from core import config_check as _cc
check_("a check() nem olvas fajlt (a szerzodese tiszta)",
      "params_file" not in _insp3.getsource(_cc.check))
check_("...a fajlt olvaso reteg kulon van", "def check_with_state" in _insp3.getsource(_cc))
# Az olvasok BEADHATOK -> a teszt sem nyul fajlhoz.
_cfg_t = {"pairs": {"X": {"strategies": ["wpr_sma"]}}, "strategy": {"name": "wpr_sma"},
          "available_strategies": {"wpr_sma": True}}
_r = check_with_state(_cfg_t, preset_of=lambda s: "none", tp_of=lambda s, n: 3.0)
check_("beadott allapottal a lelet megjelenik",
      any(x["code"] == "tp_vs_preset" for x in _r), str([x["code"] for x in _r]))
_r2 = check_with_state(_cfg_t, preset_of=lambda s: "off", tp_of=lambda s, n: 3.0)
check_("...osszhangban levo allapottal nem",
      not any(x["code"] == "tp_vs_preset" for x in _r2))
# Egy elszallo olvaso ne vigye el az EGESZ ellenorzest.
def _boom(*_a):
    raise RuntimeError("nincs fajl")
check_("elszallo allapot-olvaso nem buktatja a tobbi ellenorzest",
      isinstance(check_with_state(_cfg_t, preset_of=_boom, tp_of=_boom), list))


# ---------------------------------------------------------------------------
# A MEGCSONKITOTT KERESESI TER (`optimizer_skip`)
# ---------------------------------------------------------------------------
# ⚠ MI TORTENT (2026-09-05). A tiszta lapos ujrahangolasban a Ger40 4 PERC alatt
# "vegzett" az 500 trialbol: a keresese EGYETLEN dimenzion ment, mert a masik 14
# ki volt kapcsolva egy honapokkal korabbi kiserlet ota. A keszlet elkeszult, a
# fajlon semmi nem arulta el. Ot ilyen terv maradt bent (Ger40, UK100, Usa500,
# EURCHF / wpr_sma es UsaInd / trend_pullback).
_cfg_skip = {"pairs": {"Ger40": {"enabled": True, "strategies": ["wpr_sma"],
                                 "optimizer_skip": {"wpr_sma": ["sma_period", "tp_rr_ratio"]}}},
             "strategy": {"name": "wpr_sma"}, "available_strategies": {"wpr_sma": True}}
_fs = [x for x in cc.check(_cfg_skip) if x["code"] == "optimizer_skip"]
check_("a megcsonkitott keresesi ter LELET", len(_fs) == 1, str([x["code"] for x in cc.check(_cfg_skip)]))
if _fs:
    check_("...megnevezi a part es a strategiat",
          "Ger40" in _fs[0]["message"] and "wpr_sma" in _fs[0]["message"])
    check_("...felsorolja a kihagyott kulcsokat (kulonben nem lehet visszakapcsolni)",
          "sma_period" in _fs[0]["message"] and "tp_rr_ratio" in _fs[0]["message"])
    check_("...INFO, nem WARN (a szukites lehet szandekos)", _fs[0]["level"] == "info")

# Terv NELKUL nincs lelet — kulonben minden futasnal zajongana.
_cfg_ok = {"pairs": {"Ger40": {"enabled": True, "strategies": ["wpr_sma"]}},
           "strategy": {"name": "wpr_sma"}, "available_strategies": {"wpr_sma": True}}
check_("terv nelkul nincs lelet",
      not [x for x in cc.check(_cfg_ok) if x["code"] == "optimizer_skip"])

# ⚠ A `pairs` NEM-par kulcsain (pl. `_active`) ne szalljon el: a valodi configban
# vannak ilyenek, es egy AttributeError az EGESZ ellenorzest elvinne.
_cfg_furcsa = {"pairs": {"_active": "wpr_sma",
                         "Ger40": {"enabled": True, "strategies": ["wpr_sma"]}},
               "strategy": {"name": "wpr_sma"}, "available_strategies": {"wpr_sma": True}}
check_("a pairs nem-par kulcsai nem buktatjak az ellenorzest",
      isinstance(cc.check(_cfg_furcsa), list))


# ---------------------------------------------------------------------------
# URES `strategies` LISTA — nemán az ALAPERTELMEZETT fut
# ---------------------------------------------------------------------------
# ⚠ ELESBEN MEGTORTENT (2026-09-05), es majdnem kereskedés lett belole. A 0018
# elore rogzitett kuszobei ELUTASITOTTAK a USDJPY-t es az EURHUF-ot, tehat le
# kellett kerulniuk a wpr_sma-rol. Ki is kerultek a `strategies` listajukbol —
# es pont az ELLENKEZOJE tortent:
#     strategies: []       -> visszaeses az ALAPERTELMEZETT strategiara (wpr_sma)
#     nincs run_state      -> a legacy ag az `enabled`-bol ad LIVE-ot
#     nincs strategy_mode  -> az alapertek VALODI kotes (nem `signal`)
# A ket elutasitott par igy elesben kereskedett volna azzal, amirol leszedtuk.
_cfg_ures = {"pairs": {"USDJPY": {"enabled": True, "strategies": []}},
             "strategy": {"name": "wpr_sma"}, "available_strategies": {"wpr_sma": True}}
_fu = [x for x in cc.check(_cfg_ures) if x["code"] == "empty_strategies_fallback"]
check_("az ures strategies lista engedelyezett paron LELET", len(_fu) == 1,
      str([x["code"] for x in cc.check(_cfg_ures)]))
if _fu:
    check_("...WARN, mert nemán mast futtat, mint amit a config latszik allitani",
          _fu[0]["level"] == "warn", _fu[0]["level"])
    check_("...megmondja, hogy az ures lista NEM kikapcsolas",
          "NEM kikapcsolas" in _fu[0]["message"].replace("á", "a") or
          "NEM kikapcsol" in _fu[0]["message"])
    check_("...es megnevezi a valodi kapcsolot", "enabled" in _fu[0]["message"])

# KIKAPCSOLT paron nincs lelet — ott az ures lista helyes allapot.
_cfg_ki = {"pairs": {"USDJPY": {"enabled": False, "strategies": []}},
           "strategy": {"name": "wpr_sma"}, "available_strategies": {"wpr_sma": True}}
check_("kikapcsolt paron az ures lista NEM lelet",
      not [x for x in cc.check(_cfg_ki) if x["code"] == "empty_strategies_fallback"])

# Kitoltott listaval sincs lelet.
_cfg_van = {"pairs": {"USDJPY": {"enabled": True, "strategies": ["wpr_sma"]}},
            "strategy": {"name": "wpr_sma"}, "available_strategies": {"wpr_sma": True}}
check_("kitoltott listaval nincs lelet",
      not [x for x in cc.check(_cfg_van) if x["code"] == "empty_strategies_fallback"])


# ── Bennragadt csomag-celar (0001) ────────────────────────────────────────
# ⚠ A cel a `data/build_mode.json`-ban el, az epites MODJA ugyanott — de a mod
# „Ki"-re allitasa NEM nullazza a celt, tehat ott maradhat egy szam, ami semmit
# nem csinal. A teszt STUBOLJA a build_state-et: a valodi fajlt sem olvassuk,
# sem irjuk.
from core import build_state as _bs_t, position_build as _pb_t

_bs_orig = _bs_t.get_config
_cfg_bt = {"pairs": {"EURUSD": {"enabled": True}}}
try:
    _bs_t.get_config = lambda s: {**_pb_t.default_config(),
                                  "target_r": 20.0, "mode": _pb_t.MODE_OFF}
    _f = [x for x in cc.check(_cfg_bt) if x["code"] == "build_target_idle"]
    check_("cel + KIKAPCSOLT epites -> lelet", len(_f) == 1)
    check_("...es megnevezi a parat", _f and _f[0].get("symbol") == "EURUSD")

    _bs_t.get_config = lambda s: {**_pb_t.default_config(),
                                  "target_r": 20.0, "mode": _pb_t.MODE_AUTO}
    check_("cel + BEKAPCSOLT epites -> nincs lelet",
           not [x for x in cc.check(_cfg_bt) if x["code"] == "build_target_idle"])

    _bs_t.get_config = lambda s: {**_pb_t.default_config(), "mode": _pb_t.MODE_OFF}
    check_("nincs cel + kikapcsolt epites -> nincs lelet",
           not [x for x in cc.check(_cfg_bt) if x["code"] == "build_target_idle"])

    # ⚠ Kuszo stop CELAR NELKUL: a kuszas a cel fele megtett utat meri, tehat
    # cel nelkul nema es tetlen.
    _bs_t.get_config = lambda s: {**_pb_t.default_config(), "mode": _pb_t.MODE_AUTO,
                                  "target_trail_pct": 0.5}
    _f2 = [x for x in cc.check(_cfg_bt) if x["code"] == "build_trail_without_target"]
    check_("kuszo stop CEL NELKUL -> lelet", len(_f2) == 1)
    _bs_t.get_config = lambda s: {**_pb_t.default_config(), "mode": _pb_t.MODE_AUTO,
                                  "target_r": 20.0, "target_trail_pct": 0.5}
    check_("kuszo stop CELLAL -> nincs lelet",
           not [x for x in cc.check(_cfg_bt) if x["code"] == "build_trail_without_target"])
finally:
    _bs_t.get_config = _bs_orig


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
