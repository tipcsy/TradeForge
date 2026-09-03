"""A KOLTSEG/KOCKAZAT kapu — core/cost_gate.py.

Nem a spread NAGYSAGAT meri, hanem azt, mennyire rontja el az uzletet:

    tenyleges_RR = (TP + spread) / (SL - spread)

MIERT KELL, HA MAR VAN SPREAD-KAPU. A `spread_gate` relativ PADLOJA
(`min_spread_mult x normal_spread`) konstrukcio szerint mindig nagyobb a par
normal spreadjenel — tehat egy par a sajat szokasos spreadjen SOHA nem akad fenn
rajta. Meres (2026-08-07): EURCHF-en az ATR-tag 6,2 pont (regen blokkolna), a
padlo 23,1 — a 15-os spread atmegy, holott az a tervezett stop HARMADA.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from gates import cost_gate as cg
from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ A MERES — valos parok szamaival ═══════════════════════════════════════
# (SL, TP, spread) pontban, a 2026-08-07-i meresbol.
CASES = {
    "UsaTec": (7062, 14124, 191),
    "GOLD":   (1475, 2950, 48),
    "EURUSD": (83, 166, 10),
    "EURJPY": (129, 258, 22),
    "EURCHF": (47, 94, 15),
    "EURGBP": (43, 86, 14),
}
print(f"{'par':8s} {'tervezett':>10s} {'tenyleges':>10s} {'torzitas':>9s} {'bukik?':>7s}")
for sym, (sl, tp, sp) in CASES.items():
    eff = cg.effective_rr(sl, tp, sp)
    d = cg.distortion(sl, tp, sp)
    print(f"{sym:8s} {tp/sl:9.1f}:1 {eff:9.1f}:1 {d*100:+8.0f}% "
          f"{('IGEN' if cg.failed(sl, tp, sp) else 'nem'):>7s}")

check("a torzitas NULLA, ha nincs spread", abs(cg.distortion(100, 200, 0)) < 1e-9)
check("a spread MINDKET oldalon ront (a stop kozelebb, a cel tavolabb)",
      cg.effective_rr(100, 200, 10) > 2.0, f"{cg.effective_rr(100, 200, 10):.2f}")
check("a keplet: (TP+s)/(SL-s)",
      abs(cg.effective_rr(100, 200, 10) - (210 / 90)) < 1e-9)

# A merteknek MONOTONNAK kell lennie a spreadben — kulonben nem hasznalhato
# kuszobolesre.
ds = [cg.distortion(100, 200, s) for s in (0, 5, 10, 20, 40)]
check("a torzitas monoton no a spreaddel", all(a < b for a, b in zip(ds, ds[1:])),
      str([round(x, 3) for x in ds]))

# ══ A HATARESETEK ═════════════════════════════════════════════════════════
check("ha a spread FELEMESZTI a stopot -> vegtelen (remenytelen belepo)",
      cg.effective_rr(10, 20, 10) == float("inf"))
check("...es a kapu bukik", cg.failed(10, 20, 10))
check("adathiany (nincs terv) -> NEM szurunk (fail-open)",
      not cg.failed(None, None, 15) and not cg.failed(0, 0, 15))
check("nulla spread -> sosem bukik", not cg.failed(47, 94, 0))

# ══ A KUSZOB: mit zar ki es mit enged at ══════════════════════════════════
blocked = {s for s, (sl, tp, sp) in CASES.items() if cg.failed(sl, tp, sp)}
check("az alap kuszob (0.25) a DRAGA parokat zarja ki",
      blocked == {"EURCHF", "EURGBP", "EURJPY"}, str(sorted(blocked)))
check("...az olcsokat viszont atengedi",
      not (blocked & {"UsaTec", "GOLD", "EURUSD"}))
check("szigorubb kuszob tobbet zar",
      cg.failed(83, 166, 10, 0.10) and not cg.failed(83, 166, 10, 0.25))

# ══ A KAPU-REGISZTER ══════════════════════════════════════════════════════
check("a kapu regisztralva van", g.COST in g.KEYS)
check("alapbol NEM szol bele (a frissites nem kereskedik maskepp)",
      g.effect_for({}, "EURCHF", "wpr_sma", g.COST) == g.EFFECT_NONE)
check("a kuszob configbol hangolhato (par > globalis > alap)",
      g.cost_max_distortion({"gates": {g.COST: {"max_rr_distortion": 0.1}}}) == 0.1)
check("...es alapertelmezve a modul erteke",
      g.cost_max_distortion({}) == cg.DEFAULT_MAX_DISTORTION)

# ══ A KIJELZES ════════════════════════════════════════════════════════════
check("a cella a tenyleges RR-t es a torzitast mutatja",
      cg.cell_text(47, 94, 15).startswith("3.4:1") and "+70%" in cg.cell_text(47, 94, 15),
      cg.cell_text(47, 94, 15))
check("adathianynal em-dash", cg.cell_text(None, None, 10) == "—")

# ══ A `gates.evaluate` uton is mukodik ════════════════════════════════════
ctx = {"plan_sl_points": 47, "plan_tp_points": 94, "spread_points": 15,
       "cost_max_distortion": 0.25}
st = {s["key"]: s for s in g.evaluate(ctx, {g.COST: g.EFFECT_BLOCK})}
check("bekapcsolva BLOKKOLO allapotot ad", st[g.COST]["state"] == g.BLOCKING,
      st[g.COST]["detail"])
st2 = {s["key"]: s for s in g.evaluate(ctx, {g.COST: g.EFFECT_NONE})}
check("kikapcsolva OFF (nem villog olyasmi, ami nem szol bele)",
      st2[g.COST]["state"] == g.OFF)
ctx_ok = {**ctx, "spread_points": 1}
st3 = {s["key"]: s for s in g.evaluate(ctx_ok, {g.COST: g.EFFECT_BLOCK})}
check("olcso spreadnel ATENGED", st3[g.COST]["state"] == g.PASS,
      st3[g.COST]["detail"])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
