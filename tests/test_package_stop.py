"""Pozícióépítés: a csomag-stop KÖLTSÉG-TUDATOS (nettó null pont).

A bejelentett hiba: GOLD-on a ráépített csomag +2,12 € / −2,16 € = −0,04 €-val zárt.
Ok: a közös stop a NYERS átlagárra került, ami BRUTTÓ nulla — a zárás fizeti a
spreadet, a jutalékot és a swapot, tehát nettó mínusz lett.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import position_build as pb
from core import trade_costs as tc

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. Visszafelé kompatibilitás: cost_buffer=0 → a RÉGI viselkedés ═══════
check("cost_buffer alapertelmezese 0 -> a nyers atlagar",
      pb.package_stop(100.0, "BUY", 105.0, 1.0, 0.1) == (100.0, False))
check("...SELL-en is", pb.package_stop(100.0, "SELL", 95.0, 1.0, 0.1) == (100.0, False))

# ══ 2. A puffer a PROFIT oldalra tol ══════════════════════════════════════
s, c = pb.package_stop(100.0, "BUY", 105.0, 1.0, 0.1, cost_buffer=0.5)
check("BUY: a stop az atlagar FOLE kerul", abs(s - 100.5) < 1e-9 and not c, f"{s}")
s, c = pb.package_stop(100.0, "SELL", 95.0, 1.0, 0.1, cost_buffer=0.5)
check("SELL: a stop az atlagar ALA kerul", abs(s - 99.5) < 1e-9 and not c, f"{s}")

# ══ 3. A LENYEG: a bejelentett GOLD-eset ══════════════════════════════════
# Ket lab, atlagar 4000.0; a zaras koltsege ~0.04 EUR/csomag arban kifejezve.
# A REGI viselkedes: stop 4000.0 -> brutto 0, netto -0.04 -> a bejelentett hiba.
old, _ = pb.package_stop(4000.0, "BUY", 4010.0, 0.5, 0.01)
new, _ = pb.package_stop(4000.0, "BUY", 4010.0, 0.5, 0.01, cost_buffer=0.35)
check("a regi stop PONT az atlagaron volt (brutto 0 = netto minusz)", old == 4000.0)
check("az uj stop a koltseget FEDEZI", new > old and abs(new - 4000.35) < 1e-9,
      f"{old} -> {new}")

# ══ 4. Az INVARIANS: vagtunk-e=False => netto >= 0 ════════════════════════
# Ha a koltseg-fedezett cel NEM erheto el, vagni kell -> a hivo nem jelolhet
# kockazatmentesnek. Kulcs eset: a NYERS atlagar meg elerheto, a cel mar nem.
# Regen ez "nem vagott"-nak szamitott (es kockazatmentesnek jelolodott), pedig
# a zaras netto minusz lett volna.
stop, clamped = pb.package_stop(100.0, "BUY", 100.4, 0.2, 0.0, cost_buffer=0.5)
check("koztes eset (atlagar elerheto, koltseg-fedezett cel nem) -> VAGOTT",
      clamped is True, f"stop={stop}")
check("...es a vagott stop a NYERS atlagar folott/alatt sem hazudik",
      stop <= 100.5 + 1e-9)

# A regi kod ugyanerre az allapotra nem vagott volna:
_, old_clamped = pb.package_stop(100.0, "BUY", 100.4, 0.2, 0.0)
check("a REGI kod ugyanitt NEM vagott (ez volt a hiba magja)", old_clamped is False)

# Teljesen elerhetetlen cel -> szinten vagott
stop, clamped = pb.package_stop(100.0, "BUY", 100.05, 0.2, 0.0, cost_buffer=0.5)
check("elerhetetlen cel -> vagott", clamped is True and stop < 100.0, f"{stop}")

# Boven eleg tavolsag -> nem vagott, a cel pontosan a puffer
stop, clamped = pb.package_stop(100.0, "SELL", 90.0, 0.2, 0.0, cost_buffer=0.5)
check("bo tavolsag SELL -> nem vagott, cel = avg-puffer",
      clamped is False and abs(stop - 99.5) < 1e-9, f"{stop}")

# ══ 5. Monotonitas: nagyobb koltseg => sosem KEVESBE vedett stop ══════════
ok = True
prev = None
for cb in [0.0, 0.1, 0.2, 0.4, 0.8]:
    s, _ = pb.package_stop(100.0, "BUY", 200.0, 0.1, 0.0, cost_buffer=cb)
    if prev is not None and s < prev - 1e-12:
        ok = False
    prev = s
check("nagyobb koltseg -> a BUY-stop sosem kerul lejjebb", ok)

# ══ 6. A backteszt-puffer (config-alapu) ══════════════════════════════════
PC = {"point_size": 0.01, "pv1_point": 1.0, "commission_per_lot": 7.0,
      "swap_long_per_lot": -2.0, "swap_short_per_lot": 0.5, "swap_3x_weekday": 2}
# 1 lot, nincs ejszaka, spread 0 -> csak a jutalek: 7.0 EUR
# artav = 7.0 * 0.01 / (1.0 * 1.0) = 0.07 ; + cushion max(0, point_size)=0.01
b = tc.package_stop_buffer(1.0, "BUY", 0.0, 0.0, PC, 0.0)
check("backteszt-puffer: jutalek atvaltasa helyes", abs(b - (0.07 + 0.01)) < 1e-9, f"{b}")

# A POZITIV swap (short) NEM csokkentheti a puffert a jutalek ala
b_short = tc.package_stop_buffer(1.0, "SELL", 0.0, 5 * 86400, PC, 0.0)
check("pozitiv swap nem csokkenti a puffert", b_short >= 0.07, f"{b_short}")

# A NEGATIV swap noveli
b_long = tc.package_stop_buffer(1.0, "BUY", 0.0, 5 * 86400, PC, 0.0)
check("negativ swap NOVELI a puffert", b_long > b, f"{b} -> {b_long}")

# Koltseg nelkuli config -> csak a spread-cushion (a regi viselkedeshez kozeli)
b0 = tc.package_stop_buffer(1.0, "BUY", 0.0, 0.0, {"point_size": 0.01, "pv1_point": 1.0}, 0.0)
check("nincs beallitott koltseg -> csak a cushion", abs(b0 - 0.01) < 1e-9, f"{b0}")

# Hianyzo kulcsok -> nem robban
check("hianyzo config-kulcsok -> 0-hoz kozeli, nem kivetel",
      tc.package_stop_buffer(1.0, "BUY", 0.0, 0.0, {}, 0.0) == 0.0)
check("nulla lot -> 0", tc.package_stop_buffer(0.0, "BUY", 0.0, 0.0, PC, 0.0) == 0.0)

# ══ 7. A puffer a CSOMAG osszvolumenere szol, nem labankent ═══════════════
# 2 lot ugyanannyi jutalekot fizet lotonkent -> az ARTAVOLSAG ugyanaz marad.
b1 = tc.package_stop_buffer(1.0, "BUY", 0.0, 0.0, PC, 0.0)
b2 = tc.package_stop_buffer(2.0, "BUY", 0.0, 0.0, PC, 0.0)
check("a puffer ARTAVOLSAG-ban volumen-fuggetlen (aranyos koltsegnel)",
      abs(b1 - b2) < 1e-12, f"{b1} vs {b2}")

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
