"""Belepo-kapuk per (instrumentum x strategia) — a dashboard-atstrukturalas adatretege.

A visszajelzes ket kulcspontja, amit ez a teszt oriz:

  1. A betukod (S/E/P) ELHAGYVA: 10 kapunal az E/E2/E3 olvashatatlan lenne.
     A sor csak ALLAPOTOT mutat, a NEVEK a kapu-panelen elnek.
  2. A kapuk per STRATEGIA dolnek el — a config mar igy gondolkodik
     (`tf_align.gate` szo szerint strategia-neveket sorol), csak a felulet nem.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import gates as g

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def ctx(**kw):
    base = {"spread_points": 100, "max_spread_points": 200,
            "tf_align_gated": True, "tf_align_signs": [1, 1, 1],
            "tf_align_labels": ["M1", "M5", "M15"], "tf_align_dir": "BUY",
            "market_name": "regime_adx", "market_label": "trendelo"}
    base.update(kw)
    return base


def st(states, key):
    return next(s["state"] for s in states if s["key"] == key)


# ══ 1. Alaphelyzet: minden atenged ═══════════════════════════════════════
ok = g.evaluate(ctx())
check("harom regisztralt kapu", len(ok) == 3, str([s["key"] for s in ok]))
check("a sorrend STABIL (a csik szegmensei helyben maradnak)",
      [s["key"] for s in ok] == [x["key"] for x in g.REGISTRY])
check("minden atenged -> nincs blokkolo", g.is_blocked(ok) is False)

# ══ 2. Spread ════════════════════════════════════════════════════════════
check("spread a hataron belul -> ATENGED", st(g.evaluate(ctx()), g.SPREAD) == g.PASS)
check("spread a hatar FOLOTT -> BLOKKOL",
      st(g.evaluate(ctx(spread_points=250)), g.SPREAD) == g.BLOCKING)
check("nincs hatar -> KIKAPCSOLVA",
      st(g.evaluate(ctx(max_spread_points=0)), g.SPREAD) == g.OFF)
check("nincs arjegyzes -> ISMERETLEN (nem hazudunk 'atenged'-et)",
      st(g.evaluate(ctx(spread_points=None)), g.SPREAD) == g.UNKNOWN)
# A reszletek (a felhasznalo 4. pontja) a panelen, nem a sorban:
_d = next(s["detail"] for s in g.evaluate(ctx(spread_points=1721, max_spread_points=1111))
          if s["key"] == g.SPREAD)
check("a spread reszletei a panelre kerulnek", "1721" in _d and "1111" in _d, _d)

# ══ 3. TF-egyuttallas — PER STRATEGIA ════════════════════════════════════
check("a strategia NINCS a gate listaban -> KIKAPCSOLVA",
      st(g.evaluate(ctx(tf_align_gated=False)), g.TF_ALIGN) == g.OFF)
check("egyuttallas van -> ATENGED",
      st(g.evaluate(ctx(tf_align_dir="BUY")), g.TF_ALIGN) == g.PASS)
check("NINCS egyuttallas -> BLOKKOL (mindket irany elbukna)",
      st(g.evaluate(ctx(tf_align_dir=None, tf_align_signs=[1, -1, 1])), g.TF_ALIGN)
      == g.BLOCKING)
check("meg nincs adat -> ISMERETLEN",
      st(g.evaluate(ctx(tf_align_signs=[])), g.TF_ALIGN) == g.UNKNOWN)
_d2 = next(s["detail"] for s in g.evaluate(ctx()) if s["key"] == g.TF_ALIGN)
check("az idosik-iranyok a panelen olvashatoak", "M1" in _d2 and "M15" in _d2, _d2)

# ══ 4. Piac — MA nem blokkol ═════════════════════════════════════════════
check("nincs piac-eloszuro -> KIKAPCSOLVA",
      st(g.evaluate(ctx(market_name=None)), g.MARKET) == g.OFF)
check("a piac hatasa PRESET, nem BLOCK", g.effect_of(g.MARKET) == g.EFFECT_PRESET)
# A LENYEG: egy nem-blokkolo kapu nem szamit blokkolasnak, akkor sem, ha
# valamiert BLOCKING allapotba kerulne.
fake = [{"key": g.MARKET, "label": "x", "effect": g.EFFECT_PRESET,
         "state": g.BLOCKING, "detail": ""}]
check("nem-blokkolo hatasu kapu NEM szamit blokkolasnak", g.is_blocked(fake) is False)

# ══ 5. A CSIK: betu NELKUL ═══════════════════════════════════════════════
s_all_ok = g.strip(g.evaluate(ctx()))
check("a csik hossza = a kapuk szama", len(s_all_ok) == 3, s_all_ok)
check("a csikban NINCS betu (a bejelentes lenyege)",
      not any(c.isalpha() for c in s_all_ok), s_all_ok)
s_block = g.strip(g.evaluate(ctx(spread_points=250)))
check("a blokkolo szegmens MASKENT nez ki", s_block != s_all_ok, f"{s_all_ok} -> {s_block}")
s_off = g.strip(g.evaluate(ctx(max_spread_points=0)))
check("a kikapcsolt szegmens is megkulonboztetheto",
      s_off not in (s_all_ok, s_block), s_off)

# Skalazodas: 10 kapunal is egy karakter/kapu, betuk nelkul
many = [{"key": f"k{i}", "label": f"kapu{i}", "effect": g.EFFECT_BLOCK,
         "state": g.PASS, "detail": ""} for i in range(10)]
check("10 kapu -> 10 szegmens, tovabbra sincs betu",
      len(g.strip(many)) == 10 and not any(c.isalpha() for c in g.strip(many)))

# ══ 6. A badge: SZAMMAL mondja meg a lenyeget ════════════════════════════
check("minden tiszta -> pipa", g.badge(g.evaluate(ctx(market_name=None))) == "✓")
b2 = g.badge(g.evaluate(ctx(spread_points=250, tf_align_dir=None,
                            tf_align_signs=[1, -1, 1])))
check("ket blokkolo -> a SZAM ketto", b2.endswith("2"), b2)
check("a badge-ben sincs betu", not any(c.isalpha() for c in b2), b2)

# ══ 7. Instrumentum-aggregatum (a szulo-sor ●○ jelolese) ═════════════════
per = {"wpr_sma": g.evaluate(ctx()),
       "ml_ai":   g.evaluate(ctx(spread_points=250))}
check("2 strategiabol 1 kesz", g.ready_count(per) == (1, 2), str(g.ready_count(per)))
check("ures -> (0, 0)", g.ready_count({}) == (0, 0))
check("None -> nem robban", g.ready_count(None) == (0, 0))

# ══ 8. Robusztussag ══════════════════════════════════════════════════════
check("ures ctx -> nem robban, minden ertelmezett",
      all(s["state"] in (g.PASS, g.BLOCKING, g.OFF, g.UNKNOWN)
          for s in g.evaluate({})))
check("None ctx -> nem robban", len(g.evaluate(None)) == 3)
check("ures allapotlista -> ures csik", g.strip([]) == "" and g.strip(None) == "")
check("minden kapunak van EMBERI neve",
      all(g.label_of(x["key"]) and g.label_of(x["key"]) != x["key"] for x in g.REGISTRY))

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
