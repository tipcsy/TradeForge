"""#10 — a TF-egyuttallas kapu LOOK-AHEAD-je a backtestben es a viz-replayben."""
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import tf_align as tfa

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ A HIBA MAGVA ═══════════════════════════════════════════════════════════
# M15 gyertyak, SMA=3. Az utolso (formalodo) gyertya 2700-kor nyit es VEGUL
# 20-on zar — de a dontes pillanataban (t=3000) az ar meg 5.
TOPEN  = np.array([0, 900, 1800, 2700], dtype=np.int64)
CLOSES = np.array([10.0, 10.0, 10.0, 20.0])
N = 3

gate = tfa.build_historical_gate({15: (TOPEN, CLOSES)}, N)

check("a formalodo gyertya VEGLEGES close-a (20) NEM szol bele: BUY blokkolva, "
      "amikor az akkori ar 5 volt",
      gate(3000, 5.0, "BUY") is False)
check("...es a SELL viszont atmegy (az akkori ar szerint lefele all)",
      gate(3000, 5.0, "SELL") is True)
check("ha az akkori ar tenyleg 20, a BUY atmegy",
      gate(3000, 20.0, "BUY") is True)

# A regi (hibas) logika ellenprobaja: a vegleges close-bol szamolva
sma_regi = CLOSES[-3:].mean()                      # (10+10+20)/3 = 13.33
check("a REGI logika szerint ugyanez BUY-t engedett volna (look-ahead)",
      (CLOSES[-1] - sma_regi) > 0, f"d={CLOSES[-1]-sma_regi:.2f}")

# ══ ELO PARITAS: a historikus kapu == az elo keplet ════════════════════════
# Az el: closes = az utolso n gyertya, az UTOLSO a formalodo, close = pillanatnyi ar.
random.seed(7)
mismatch = 0
for _ in range(400):
    n = random.choice([3, 5, 10])
    m = n + random.randint(1, 20)
    closed = [round(random.uniform(90, 110), 3) for _ in range(m)]
    price = round(random.uniform(90, 110), 3)
    final_close = round(random.uniform(90, 110), 3)      # a formalodo bar VEGSO zaroara
    topen = np.arange(m + 1, dtype=np.int64) * 900

    # historikus kapu: a lezart gyertyak + a formalodo (vegleges close-szal)
    g = tfa.build_historical_gate(
        {15: (topen, np.array(closed + [final_close], dtype=float))}, n)
    t_inside = int(topen[-1]) + 300                      # a formalodo baron BELUL

    # elo keplet: az utolso n close, az utolso a PILLANATNYI ar
    live_dir, _ = tfa.alignment({15: closed[-(n - 1):] + [price]}, [15], n)

    for sig in ("BUY", "SELL"):
        if g(t_inside, price, sig) != tfa.gate_ok(live_dir, sig):
            mismatch += 1

check("400 veletlen eseten a historikus kapu BITRE az elo kepletet adja "
      "(a vegleges close-tol fuggetlenul)", mismatch == 0, f"{mismatch} elteres")

# ══ Adathiany: az el BLOKKOL, tehat a backtest is ══════════════════════════
kevesg = tfa.build_historical_gate({15: (np.array([0, 900], dtype=np.int64),
                                         np.array([10.0, 11.0]))}, 5)
check("keves gyertya -> BLOKK (nem fail-open, mint korabban)",
      kevesg(1000, 12.0, "BUY") is False)
check("ures bemenet -> BLOKK", tfa.build_historical_gate({}, 3)(1, 1.0, "BUY") is False)

g2 = tfa.build_historical_gate({15: (TOPEN, CLOSES)}, N)
check("a sorozat ELOTTI idore is BLOKK (nincs mogotte n-1 lezart gyertya)",
      g2(100, 10.0, "BUY") is False)

# ══ Tobb idosik: MINDNEK egyeznie kell ═════════════════════════════════════
up1   = (np.arange(10, dtype=np.int64) * 60,  np.linspace(100, 90, 10))   # M1 lefele
up15  = (np.arange(10, dtype=np.int64) * 900, np.linspace(90, 100, 10))   # M15 folfele
g3 = tfa.build_historical_gate({1: up1, 15: up15}, 3)
t = 8100
check("ket idosik ellentetes -> egyik iranyba sem enged",
      g3(t, 95.0, "BUY") is False and g3(t, 95.0, "SELL") is False)

both = tfa.build_historical_gate(
    {1: (np.arange(10, dtype=np.int64) * 60,  np.linspace(90, 100, 10)),
     15: (np.arange(10, dtype=np.int64) * 900, np.linspace(90, 100, 10))}, 3)
check("mindket idosik folfele + magas ar -> BUY atmegy",
      both(8100, 200.0, "BUY") is True)
check("...de a SELL nem", both(8100, 200.0, "SELL") is False)

# ══ Az SMA a LEZART gyertyakbol jon (a formalodo sajat close-a nem szamit) ═
a = tfa.build_historical_gate({15: (TOPEN, np.array([10.0, 10.0, 10.0, 999.0]))}, N)
b = tfa.build_historical_gate({15: (TOPEN, np.array([10.0, 10.0, 10.0, -999.0]))}, N)
check("a formalodo bar vegleges close-a (999 vs -999) SEMMIT nem valtoztat",
      a(3000, 12.0, "BUY") == b(3000, 12.0, "BUY") is True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
