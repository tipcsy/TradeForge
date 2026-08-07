"""Az ML kuszob-kalibracio MAXIMUM-TORZITAS elleni vedelme.

A `_calibrate_threshold` 51 kuszob-jeloltet probal vegig, es a LEGJOBB talalati
aranyut valasztja. Nehany mintabol a legjobbat kivalasztva a magas win-rate nem
kepesseg, hanem a kereses mellekterméke — a regi korlat (`n < 6`) ezt szabadon
engedte.

VALODI ESET (2026-08-06-i tanitas, Ger40): a long irany BEKAPCSOLVA lett
12 kalibracios jel alapjan, "75% talalattal". Ugyanez a modell eles OOS-on
0 kotest adott. A vedelem ezt a mintat celozza.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

import numpy as np

from strategy.ml_train import _calibrate_threshold, MIN_CALIB_SIGNALS

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


check("az alapertelmezett minimum ERDEMI (nem a regi 6)",
      MIN_CALIB_SIGNALS >= 30, str(MIN_CALIB_SIGNALS))

# ══ A GER40-MINTA: a magas savban CSAK 12 minta, veletlenul 9 nyero ═══════
rng = np.random.default_rng(3)
proba = np.concatenate([rng.uniform(0.0, 0.60, 4988), rng.uniform(0.86, 0.94, 12)])
y = np.concatenate([rng.integers(0, 2, 4988), np.array([1] * 9 + [0] * 3)])

t_old, s_old = _calibrate_threshold(proba, y, 0.4, 0.08, min_signals=6)
check("a REGI korlat a 12 mintas savra ELESIT (ez volt a hiba)",
      s_old["signals"] < 30 and s_old["win_rate"] > 0.7 and s_old["enabled"],
      f"jel={s_old['signals']}, wr={s_old['win_rate']:.2f}, kuszob={t_old:.2f}")

t_new, s_new = _calibrate_threshold(proba, y, 0.4, 0.08)
check("az UJ korlat NEM elesit ilyen keves jelre",
      s_new["signals"] >= MIN_CALIB_SIGNALS or not s_new["enabled"],
      f"jel={s_new['signals']}, wr={s_new['win_rate']:.2f}, kuszob={t_new:.2f}")
check("...hanem erdemi mintaju kuszobot valaszt (vagy kikapcsol)",
      (not s_new["enabled"]) or s_new["signals"] >= MIN_CALIB_SIGNALS,
      f"jel={s_new['signals']}")
check("a kuszob emiatt ALACSONYABB lett (szelesebb, megalapozottabb sav)",
      t_new < t_old, f"{t_new:.2f} < {t_old:.2f}")

# ══ Ha SEMMI nem eri el a minimumot -> az irany KIKAPCSOL, indoklassal ════
tiny = np.concatenate([rng.uniform(0.0, 0.30, 900), rng.uniform(0.90, 0.95, 8)])
ytiny = np.concatenate([np.zeros(900, dtype=int), np.ones(8, dtype=int)])
t_t, s_t = _calibrate_threshold(tiny, ytiny, 0.4, 0.02)
check("keves jelnel az irany KIKAPCSOL (1.01 = de facto tiltva)",
      not s_t["enabled"] and t_t > 1.0, f"kuszob={t_t}, be={s_t['enabled']}")
check("...es megmondja, MIERT (a naplo/`meta` olvashato legyen)",
      "jellel" in (s_t.get("reason") or ""), str(s_t.get("reason"))[:60])

# ══ VALODI jelet viszont NEM fojt el ══════════════════════════════════════
# A magas valoszinuseg tenylegesen jobb kimenetet jelent, BOSEGES mintan.
p2 = rng.uniform(0, 1, 5000)
y2 = (rng.uniform(0, 1, 5000) < p2 * 0.9).astype(int)
t2, s2 = _calibrate_threshold(p2, y2, 0.4, 0.08)
check("valodi, boseges jelre TOVABBRA is elesit",
      s2["enabled"] and s2["signals"] >= MIN_CALIB_SIGNALS,
      f"jel={s2['signals']}, wr={s2['win_rate']:.2f}")

# ══ A minimum CONFIGBOL hangolhato ════════════════════════════════════════
_t3, s3 = _calibrate_threshold(p2, y2, 0.4, 0.08, min_signals=1000)
check("a minimum atadhato (configbol hangolhato)",
      (not s3["enabled"]) or s3["signals"] >= 1000,
      f"jel={s3['signals']}, be={s3['enabled']}")
check("a statisztika KIIRJA a hasznalt minimumot (visszakovetheto legyen)",
      s2.get("min_signals") == MIN_CALIB_SIGNALS, str(s2.get("min_signals")))

# ══ A CIMKE a SPREADET is megfizeti (kulonben elerhetetlen celt tuz ki) ═══
# A gyertyak BID arak. Egy SHORT-ot bid-en nyitsz es ASK-on zarsz -> az SL egy
# spreaddel KOZELEBB, a TP egy spreaddel TAVOLABB. Ugyanez a LONG-nal is igaz.
# Meres (2026-08-07): EURCHF-en az SL 47 pont, a spread 15 — a stop HARMADA.
import pandas as pd
from strategy.ml_train import label_outcomes

n = 60
idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
close = np.full(n, 1000.0)
high = close.copy()
low = close.copy()
# ATR=100 -> SL=150, TP=300. Spread=40.
# A 6. gyertyan az ar 1130-ig megy FEL: a nyers (spread nelkuli) SHORT-stop
# (1150) MEG all, a spreades (1150-40=1110) viszont MAR kiutott.
high[6] = 1130.0
# Utana lemegy 660-ig: a TP mindket esetben teljesulne (700 ill. 660).
low[10] = 660.0
f = pd.DataFrame({"close": close, "high": high, "low": low, "atr14": 100.0},
                 index=idx)
P = {"sl_atr_mult": 1.5, "tp_rr_ratio": 2.0}
a = label_outcomes(f, P, 1.0, 32, 0.0)      # spread NELKUL
b = label_outcomes(f, P, 1.0, 32, 40.0)     # spreaddel

check("spread NELKUL a short cimke NYERO (a 1130-as kiles nem uti ki)",
      int(a["label_short"].iloc[0]) == 1)
check("spreaddel viszont VESZTO (a stop kozelebb van -> elobb utott ki)",
      int(b["label_short"].iloc[0]) == 0)
check("a LONG oldalt is bunteti (nem csak a shortot)",
      label_outcomes(f, P, 1.0, 32, 40.0)["label_long"].sum()
      <= label_outcomes(f, P, 1.0, 32, 0.0)["label_long"].sum())
check("nulla spread -> a regi viselkedes valtozatlan",
      (label_outcomes(f, P, 1.0, 32).values
       == label_outcomes(f, P, 1.0, 32, 0.0).values).all())

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
