"""Az M1 belépő triggere IRÁNYONKÉNT külön — ahogy az M15-ön már régóta.

⚠ A KÉRÉS (a felhasználótól, 2026-08-18): „A wpr_sma-nak vezessünk be egy új
paramétert: wpr_m1_sell_trigger. A wpr_m1_trigger-t pedig nevezzük át
wpr_m1_buy_trigger-nek. Működésileg ugyanúgy működjön, mint ahogy az M15
működik."

⚠ MIÉRT NEM MINDEGY. Az M15 „jó zóna" triggere már két külön szám
(`wpr_m15_buy_trigger` / `wpr_m15_sell_trigger`), az M1 belépőé viszont EGY volt
mindkét irányra. A két irány nem szimmetrikus: az egyik irányban egy korábbi
visszaütés is jó belépő, a másikban mélyebb megerősítés kell — egy közös szám ezt
a két igényt egyetlen kompromisszumba préselte, és az optimalizáló sem tudta
szétválasztani őket.

⚠ ÉS AMI NEM VÁLTOZHAT: a régi mentett készletek viselkedése. A régi EGY trigger
MINDKÉT irányt szolgálta, tehát a migráció UGYANAZT az értéket teszi mindkét új
kulcsba — bitre azonos viselkedés. Egy még nem migrált készlet (mentés, másik
gép) pedig a régi kulcsra esik vissza, NEM a modul -50-ére: különben egy -70-re
hangolt pár némán -50-nel kereskedne tovább.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


CFG = json.loads((ROOT / "strategy" / "config" / "wpr_sma.json").read_text(encoding="utf-8"))
OLD = "wpr_m1_trigger"

# ── 1. A KONFIG: az M1 pontosan azt a szerkezetet kapja, mint az M15 ──────
_ind = CFG["indicators"]
check("van wpr_m1_buy_trigger alapérték", "wpr_m1_buy_trigger" in _ind)
check("van wpr_m1_sell_trigger alapérték", "wpr_m1_sell_trigger" in _ind)
check("a régi közös kulcs KIKERÜLT az alapértékekből", OLD not in _ind)
# ⚠ Az alapérték UGYANAZ a kettő: a szétválasztás önmagában nem változtathat a
# kiindulási viselkedésen.
check("az alapértékek megegyeznek a régi közös értékkel (-50)",
      _ind["wpr_m1_buy_trigger"] == _ind["wpr_m1_sell_trigger"] == -50,
      f"buy={_ind['wpr_m1_buy_trigger']} sell={_ind['wpr_m1_sell_trigger']}")

_opt = CFG["optimizer"]
for _k in ("wpr_m1_buy_trigger", "wpr_m1_sell_trigger"):
    check(f"{_k}: optimalizálható tartomány", _k in _opt)
    # ⚠ A gt/lt metaadat szűkíti a suggeszt-tartományt — enélkül az optuna
    # érvénytelen kombókat sorsolna, és elpazarolt trialokat futtatna.
    check(f"{_k}: a szint-sorrend metaadata megvan",
          _opt[_k].get("gt") == "wpr_m1_buy_extreme"
          and _opt[_k].get("lt") == "wpr_m1_sell_extreme", str(_opt[_k]))
check("a régi közös kulcs KIKERÜLT a tartományokból", OLD not in _opt)

_meta = CFG["param_meta"]["params"]
for _k in ("wpr_m1_buy_trigger", "wpr_m1_sell_trigger"):
    check(f"{_k}: van leírása a paraméter-ablakhoz", _k in _meta)
    check(f"{_k}: az M1 kategóriába", _meta[_k]["category"].endswith("M1"),
          _meta[_k]["category"])
    # A trigger a JELET változtatja: újraszámolás kell (nem végrehajtási param).
    check(f"{_k}: jel-újraszámolást igényel", _meta[_k]["recompute"] == "signal")
check("a régi közös kulcs KIKERÜLT a leírásokból", OLD not in _meta)

# ⚠ A KÉNYSZEREK: pontosan az M15 mintája, csak m1-re. Mindkét trigger a két
# extrém KÖZÖTT kell legyen — különben a felfegyverzés sosem tud tüzelni.
_c = CFG["optimizer"]["constraints"]
_want = ["wpr_m1_buy_extreme < wpr_m1_buy_trigger",
         "wpr_m1_buy_trigger < wpr_m1_sell_extreme",
         "wpr_m1_buy_extreme < wpr_m1_sell_trigger",
         "wpr_m1_sell_trigger < wpr_m1_sell_extreme"]
check("mind a 4 M1 kényszer megvan", all(w in _c for w in _want),
      str([w for w in _want if w not in _c]))
check("...és az M15-tel AZONOS alakúak",
      [w.replace("_m1_", "_m15_") for w in _want]
      == [w for w in _c if "_m15_" in w], str(_c))
check("a régi kényszerek eltűntek", not any(OLD in w for w in _c))

# A stratégia constraints_ok ellenőrzése ténylegesen szűr az új kulcsokra.
from strategy import get_strategy_by_name
_st = get_strategy_by_name("wpr_sma")
_base = dict(_ind)
_ok = {**_base, "wpr_m1_buy_trigger": -60, "wpr_m1_sell_trigger": -40}
_bad = {**_base, "wpr_m1_buy_trigger": -99, "wpr_m1_sell_trigger": -40}  # az extrém ALATT
check("constraints_ok: érvényes kombó átmegy", _st.constraints_ok(_ok))
check("constraints_ok: az extrémen kívüli BUY trigger ELBUKIK",
      not _st.constraints_ok(_bad))


# ── 2. A VISELKEDÉS: a két trigger TÉNYLEG külön hat ─────────────────────
from core.signal_detector import PairState, check_m1_entry

P = {"wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
     "wpr_m1_sell_trigger": -40, "wpr_m1_buy_trigger": -60}


def _sell_run(params, cross_to):
    """Nyitott SELL ablak: felfegyverzés a felső extrémen, majd LEFELÉ átütés."""
    st = PairState("X", direction="SELL", m15_window_open=True)
    check_m1_entry(st, -15.0, -10.0, params)          # felfegyverez (>= -20)
    return check_m1_entry(st, -30.0, cross_to, params)


def _buy_run(params, cross_to):
    """Nyitott BUY ablak: felfegyverzés az alsó extrémen, majd FELFELÉ átütés."""
    st = PairState("X", direction="BUY", m15_window_open=True)
    check_m1_entry(st, -85.0, -90.0, params)          # felfegyverez (<= -80)
    return check_m1_entry(st, -70.0, cross_to, params)


# A SELL a SAJÁT triggerén tüzel (-40), a BUY-én (-60) nem.
check("SELL: a saját triggerét átütve tüzel", _sell_run(P, -45.0) == "SELL",
      _sell_run(P, -45.0))
check("SELL: a saját triggere ELŐTT még nem tüzel", _sell_run(P, -35.0) == "NONE",
      _sell_run(P, -35.0))
# ⚠ EZ A LÉNYEG: ha a kód még a közös (-50) triggert használná, a -45-ös eset
# NEM tüzelne — a szétválasztás mérhetően más döntést hoz.
check("BUY: a saját triggerét átütve tüzel", _buy_run(P, -55.0) == "BUY",
      _buy_run(P, -55.0))
check("BUY: a saját triggere ELŐTT még nem tüzel", _buy_run(P, -65.0) == "NONE",
      _buy_run(P, -65.0))

_common = {**P, "wpr_m1_sell_trigger": -50, "wpr_m1_buy_trigger": -50}
check("a szétválasztás tényleg számít (közös -50-nel más a döntés)",
      _sell_run(_common, -45.0) == "NONE" and _sell_run(P, -45.0) == "SELL")


# ── 3. VISSZAFELÉ KOMPATIBILITÁS: a régi kulcs TARTALÉK ──────────────────
# ⚠ Egy még nem migrált készlet (mentés, másik gép) a RÉGI értékkel fusson
# tovább — némán a modul -50-ére esni a legrosszabb kimenet: egy -70-re hangolt
# pár észrevétlenül más stratégiát futtatna.
_legacy = {"wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
           "wpr_m1_trigger": -70}
_migrated = {"wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80,
             "wpr_m1_sell_trigger": -70, "wpr_m1_buy_trigger": -70}
for _cross, _dirn in ((-75.0, "SELL"), (-65.0, "BUY")):
    _run = _sell_run if _dirn == "SELL" else _buy_run
    check(f"{_dirn}: a régi kulcs UGYANAZT adja, mint a migrált készlet",
          _run(_legacy, _cross) == _run(_migrated, _cross),
          f"legacy={_run(_legacy, _cross)} migrált={_run(_migrated, _cross)}")
# ...és a régi kulcs a MODUL alapértéke helyett hat.
check("a régi kulcs FELÜLÍRJA a -50-es alapértelmezést",
      _sell_run(_legacy, -55.0) == "NONE"
      and _sell_run({"wpr_m1_sell_extreme": -20, "wpr_m1_buy_extreme": -80},
                    -55.0) == "SELL")


# ── 4. A MENTETT KÉSZLETEK MIGRÁLVA ─────────────────────────────────────
from core.params_store import strategy_dir
# ⚠ A `<SYM>_hours.json` NEM paraméter-készlet (kereskedési órák) — a nyers
# glob azt is behozta, és a mérés 11/19-et mutatott ott, ahol 11/11 a helyes.
_files = sorted(p for p in strategy_dir("wpr_sma").glob("*.json")
                if not p.stem.endswith("_hours"))
_stale, _split = [], []
for _f in _files:
    _blk = (json.loads(_f.read_text(encoding="utf-8")).get("params") or {})
    if OLD in _blk:
        _stale.append(_f.name)
    if "wpr_m1_buy_trigger" in _blk:
        _split.append((_f.name, _blk["wpr_m1_buy_trigger"], _blk["wpr_m1_sell_trigger"]))
check("van mit mérni (vannak mentett készletek)", bool(_files), f"{len(_files)} fájl")
check("egyetlen ÉLES készletben sem maradt a régi kulcs", not _stale, str(_stale))
check("mindegyik megkapta a két új kulcsot", len(_split) == len(_files),
      f"{len(_split)}/{len(_files)}")
# ⚠ A MIGRÁCIÓ értéktartó volt (a régi EGY trigger mindkét irányt szolgálta →
# ugyanaz az érték mindkét új kulcsba), de EGYENLŐSÉGET tiltó invariánst NEM
# írhatunk ide: az első kézi hangolás vagy újraoptimalizálás után a kettő
# jogosan eltér — épp ez a feature értelme. (Az első mérésnél az UsaTec már
# −55/−45 volt, mert kézzel átállították.)
_diff = [(n, b, s) for n, b, s in _split if b != s]
check("a szétválasztott értékek érvényes tartományban vannak",
      all(-100 < v < 0 for _n, b, s in _split for v in (b, s)), str(_split)[:120])
print(f"      (irányonként ELTÉRŐ trigger: {len(_diff)} pár — {_diff})")


# ── 5. A CHARTON: 4 szint, az M15-tel AZONOS sorrendben ─────────────────
# ⚠ A sorrend SZERZŐDÉS az MQL-lel: [felső extrém, SELL trigger, BUY trigger,
# alsó extrém]. A TradeForgeWPR a 4-es esetet MÁR ismeri (SELL trigger piros,
# BUY trigger zöld) — ezért NEM kell újrafordítani.
_src = (ROOT / "strategy" / "wpr_sma.py").read_text(encoding="utf-8")
_i = _src.find("m1_levels  = (")      # ⚠ a fallback-sor is `p.get("wpr_m1…`
_blk = _src[_i:_src.find(")", _src.find("wpr_m1_buy_extreme", _i)) + 1]
check("a viz M1 szintjei: 4 elem", _blk.count('p.get("wpr_m1') == 4,
      str(_blk.count('p.get("wpr_m1')))
check("...az M15-tel azonos sorrendben (sell_extr, sell_trig, buy_trig, buy_extr)",
      _blk.find("wpr_m1_sell_extreme") < _blk.find("wpr_m1_sell_trigger")
      < _blk.find("wpr_m1_buy_trigger") < _blk.find("wpr_m1_buy_extreme"))
_mql = (ROOT / "mt5" / "TradeForgeWPR.mq5").read_text(encoding="utf-8")
check("az MQL már ismeri a 4-szintes esetet (nincs újrafordítás)",
      "cnt == 4" in _mql and "clrRed : clrGreen" in _mql)


# ── 6. A per-pár „mit ne optimalizálj" listák is migrálva ───────────────
# ⚠ Ha a felhasználó KIVETTE a keresésből a közös triggert, a szándéka MINDKÉT
# új kulcsra vonatkozik — különben a következő optimalizálás némán elkezdené
# hangolni azt, amit ő kizárt.
_cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
_bad2 = []
for _sym, _pc in (_cfg.get("pairs") or {}).items():
    if not isinstance(_pc, dict):
        continue
    for _sn, _lst in ((_pc.get("optimizer_skip") or {}).items()):
        if OLD in (_lst or []):
            _bad2.append(f"{_sym}/{_sn}")
check("egyetlen skip-listában sem maradt a régi kulcs", not _bad2, str(_bad2))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
