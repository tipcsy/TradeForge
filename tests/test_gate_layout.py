"""Mely kapuk latszanak, milyen sorrendben — es mit jelent a KIKAPCSOLT.

A user kerese (Obsidian, 2026-08-07): a Beallitas ablakban legyen ket lista
(Kikapcsolt / Bekapcsolt), sorrenddel; es „kikapcsolva egyetlen instrumentumra
sem lesz hatassal".

EZ A LEGFONTOSABB ALLITAS ITT: a kikapcsolas KET dolgot jelent EGYUTT —
  1. az oszlop nem latszik, ES
  2. a kapu EGYETLEN instrumentumon sem szol bele a kereskedesbe.
Ha csak elrejtenenk az oszlopot, a kapu LATHATATLANUL blokkolhatna tovabb.

...es a per-par beallitasok kozben NEM vesznek el: felfuggesztjuk oket.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import gate_layout as gl
from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. Alapertelmezes: a MAI viselkedes ═══════════════════════════════════
check("hianyzo config -> MINDEN kapu, a REGISTRY sorrendjeben",
      gl.enabled_gates({}) == list(g.KEYS), str(gl.enabled_gates({})))
check("...es semmi nincs kikapcsolva", gl.disabled_gates({}) == [])

# ══ 2. A LISTA dont — kor es sorrend ══════════════════════════════════════
cfg = {"dashboard": {"gate_order": ["cost", "spread"]}}
check("csak a listaban szereplok engedelyezettek",
      gl.enabled_gates(cfg) == ["cost", "spread"], str(gl.enabled_gates(cfg)))
check("a tobbi KIKAPCSOLT",
      set(gl.disabled_gates(cfg)) == {g.TF_ALIGN, g.MARKET, g.MOMENTUM},
      str(gl.disabled_gates(cfg)))
check("a SORREND a listat koveti (nem a REGISTRY-t)",
      gl.enabled_gates(cfg)[0] == "cost")
check("ures lista -> egyetlen kapu sem",
      gl.enabled_gates({"dashboard": {"gate_order": []}}) == [])

# Az OSZLOP-kulcs elter a KAPU-kulcstol egy helyen (`tf_align` -> `align`)
check("a tf_align oszlopa `align`", gl.column_key(g.TF_ALIGN) == "align")
check("...es visszafele is", gl.gate_key("align") == g.TF_ALIGN)
check("a lista OSZLOP-kulcsokkal is lekerheto",
      gl.enabled_columns({"dashboard": {"gate_order": ["tf_align", "spread"]}})
      == ["align", "spread"])
check("az oszlop-kulcs a configban is elfogadott (`align`)",
      gl.enabled_gates({"dashboard": {"gate_order": ["align"]}}) == [g.TF_ALIGN])

# Robusztussag: elgepeles ne tuntessen el kaput NEMAN
check("ismeretlen kulcs egyszeruen kimarad",
      gl.enabled_gates({"dashboard": {"gate_order": ["spread", "nincs_ilyen"]}})
      == ["spread"])
check("ismetlodes nem duplaz",
      gl.enabled_gates({"dashboard": {"gate_order": ["spread", "spread"]}})
      == ["spread"])

# ══ 3. A KIKAPCSOLAS HATASTALANIT — ez a lenyeg ═══════════════════════════
# Egy par, ahol a spread-kapu KIFEJEZETTEN blokkolora van allitva.
live = {"dashboard": {"gate_order": list(g.KEYS)},
        "pairs": {"GOLD": {"gates": {g.SPREAD: {"wpr_sma": g.EFFECT_BLOCK}}}}}
check("bekapcsolva a per-par beallitas ervenyes",
      g.effect_for(live, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)

off = {"dashboard": {"gate_order": [k for k in g.KEYS if k != g.SPREAD]},
       "pairs": live["pairs"]}
check("KIKAPCSOLVA a kapu SEHOL nem szol bele",
      g.effect_for(off, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_NONE)
check("...a motor igy meg sem meri",
      not g.active(g.effects_for(off, "GOLD", "wpr_sma"), g.SPREAD))
_eff, _src = g.effect_with_source(off, "GOLD", "wpr_sma", g.SPREAD)
check("...es a felulet MEGMONDJA, miert (nem hazudik sima 'Ki'-t)",
      _src == g.SRC_MASTER_OFF, _src)
check("...az indoklas emberi", "KIKAPCSOLVA" in g.SOURCE_LABEL[g.SRC_MASTER_OFF])

# FELFUGGESZT, NEM TOROL: a per-par beallitas a configban marad
check("a per-par beallitas NEM veszett el",
      off["pairs"]["GOLD"]["gates"][g.SPREAD]["wpr_sma"] == g.EFFECT_BLOCK)
back = {"dashboard": {"gate_order": list(g.KEYS)}, "pairs": off["pairs"]}
check("...visszakapcsolva ujra el",
      g.effect_for(back, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)

# A tobbi kapura NINCS hatassal
check("a kikapcsolas csak AZT az egy kaput erinti",
      g.effect_for(off, "GOLD", "wpr_sma", g.TF_ALIGN)
      == g.effect_for(live, "GOLD", "wpr_sma", g.TF_ALIGN))

# ══ 4. Iras a configba ════════════════════════════════════════════════════
c = {}
gl.apply_order(c, ["cost", "align", "spread"])
check("a TELJES listat kiirja (a fajlbol deruljon ki a sorrend)",
      c["dashboard"]["gate_order"] == ["cost", g.TF_ALIGN, "spread"],
      str(c["dashboard"]["gate_order"]))
gl.apply_order(c, ["spread", "hulyeseg", "spread"])
check("iraskor is szurunk (ismeretlen/ismetlodo kulcs)",
      c["dashboard"]["gate_order"] == ["spread"])
check("a kiirt lista visszaolvasva ugyanaz",
      gl.enabled_gates(c) == ["spread"])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
