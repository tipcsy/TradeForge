"""
A volatilitas-szuro MERCEJE — egy definicio a backtestnek, a viznek es az elnek.

MIERT: 2026-08-08-an a BTCUSD hetekig NEMAN nem kereskedett. A mentett merce
272,75 volt, a friss ATR-median 140,19 (a BTC volatilitasa a felere esett), az
atr_min_pct=0,9 padlo pedig igy a gyertyak 94%-at kizarta: a 30 nap alatt
keletkezett 26 M1-jelbol MIND a 26 elbukott, tehat a charton egyetlen jelolo sem
jelent meg. A tobbi paron ez nem latszott (Ger40 1,00x, GOLD 0,97x).

Ket dolgot rogzit ez a teszt:

1. AZ ALAP NEM VALTOZOTT. `atr_baseline_bars = 0` -> pontosan a regi viselkedes
   (fix `atr_avg_ref`, tartalek az ablak-atlag). Enelkul a valtoztatas MINDEN par
   koteseit elmozditotta volna.
2. A gordulo merce OK-OKOZATI: az i. bar merceje csak a MULTBOL szamol. Egy
   look-ahead itt eszrevetlen maradna, es a backtestet felfele torzitana.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

import numpy as np                                  # noqa: E402
import pandas as pd                                 # noqa: E402

from core import vol_baseline as vb                 # noqa: E402
from strategy import get_strategy_by_name           # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


idx = pd.date_range("2026-01-01", periods=400, freq="15min", tz="UTC")
# Rezsimvaltas: az elso fele elenk (10), a masodik csendes (4)
atr = pd.Series(np.r_[np.full(200, 10.0), np.full(200, 4.0)], index=idx)

# ---------------------------------------------------------------------------
print("== Alapertelmezes: a regi viselkedes ==")
s0 = vb.series(atr, {})
check("merce nelkul az egesz ablak atlaga", abs(s0.iloc[0] - 7.0) < 1e-9,
      f"{s0.iloc[0]:.3f}")
check("...es MINDEN baron ugyanaz (konstans)", float(s0.std()) == 0.0)
check("baseline_bars alap = 0", vb.baseline_bars({}) == 0)
check("hibas erteknel is 0", vb.baseline_bars({"atr_baseline_bars": "abc"}) == 0)
check("negativ ertek -> 0", vb.baseline_bars({"atr_baseline_bars": -5}) == 0)

# A precedencia: alapban a MENTETT ref nyer
check("alapban az atr_avg_ref nyer a sor felett",
      vb.effective({"atr_avg_ref": 272.75}, 140.0) == 272.75)
check("ref nelkul a sor erteke", vb.effective({}, 140.0) == 140.0)
check("gordulonel a SOR nyer (a ref nem szol bele)",
      vb.effective({"atr_avg_ref": 272.75, "atr_baseline_bars": 96}, 140.0) == 140.0,
      "kulonben a beallitas neman hatastalan lenne")

# ---------------------------------------------------------------------------
print("== Gordulo merce: koveti a rezsimvaltast ==")
p = {"atr_baseline_bars": 100}
s1 = vb.series(atr, p)
check("a csendes szakasz vegen a merce is lecsokken",
      abs(s1.iloc[-1] - 4.0) < 1e-9, f"{s1.iloc[-1]:.3f}")
check("az elenk szakaszban meg magas", abs(s1.iloc[150] - 10.0) < 1e-9,
      f"{s1.iloc[150]:.3f}")
check("nincs NaN (a warmup visszatoltodik)", not s1.isna().any())

# ⚠ OK-OKOZATI: a jovo megvaltoztatasa NEM valtoztathatja a korabbi mercet
atr2 = atr.copy()
atr2.iloc[300:] = 999.0
s2 = vb.series(atr2, p)
check("a JOVO modositasa nem hat a korabbi barokra (nincs look-ahead)",
      bool(np.allclose(s1.iloc[:250].to_numpy(), s2.iloc[:250].to_numpy())),
      "a 300. bar utani valtozas a 250. bar mercejet nem erinti")

# A tombos valtozat (viz replay) egyezzen a sorozatossal
arr = atr.to_numpy()
for i in (150, 250, 399):
    check(f"value_at({i}) == series[{i}]",
          abs(vb.value_at(arr, i, p, 0.0) - float(s1.iloc[i])) < 1e-6,
          f"{vb.value_at(arr, i, p, 0.0):.4f} vs {float(s1.iloc[i]):.4f}")
check("value_at alapban a tartalekot adja", vb.value_at(arr, 100, {}, 7.5) == 7.5)

# ---------------------------------------------------------------------------
print("== Allapot: MEGMONDJA, miert nem lepne be ==")
prm = {"atr_min_pct": 0.9, "atr_max_pct": 3.2}
lo, hi = vb.band(prm, 272.75)
check("a sav a mercebol szamol", abs(lo - 245.475) < 1e-6 and abs(hi - 872.8) < 1e-6,
      f"{lo:.1f}..{hi:.1f}")

st_quiet = vb.status(140.19, prm, 272.75)          # a VALODI BTCUSD eset
check("a BTCUSD-eset: savon KIVUL", not st_quiet["ok"])
check("...es 'tul csendes'-kent", "csendes" in st_quiet["why"], st_quiet["why"][:50])
check("...az aranyt is kiirja", abs(st_quiet["ratio"] - 0.514) < 0.01,
      f"{st_quiet['ratio']:.3f}")

check("savon belul OK", vb.status(300.0, prm, 272.75)["ok"])
st_wild = vb.status(3000.0, prm, 272.75)
check("tul kaotikus is elkulonul", (not st_wild["ok"]) and "kaotikus" in st_wild["why"])
check("merce nelkul nem szur", vb.status(1.0, prm, 0.0)["ok"])
check("a kikapcsolt padlo nem szur",
      vb.status(1.0, {"atr_min_pct": 0, "atr_max_pct": 0}, 272.75)["ok"])

# ---------------------------------------------------------------------------
print("== A KAPU hasznalja (v3.27.0: mar nem a bt_entry) ==")
# ⚠ v3.27.0 elott ez a szures a strategia `bt_entry`-jeben volt. Most a
# VOLATILITAS-KAPU dont (`vol_baseline.failed`), a kuszobok viszont tovabbra is
# a strategia optimalizalt parameterei. A `bt_entry` ezert mar NEM szur —
# csak meretez —, es ezt itt ki is mondjuk, hogy a valtas ne legyen nema.
strat = get_strategy_by_name("wpr_sma")
row_quiet = {"atr": 140.19, "atr_avg": 140.19}
p_fix = {"atr_avg_ref": 272.75, "atr_min_pct": 0.9, "atr_max_pct": 3.2,
         "sl_atr_mult": 1.5, "tp_rr_ratio": 2.0, "sl_method": "atr"}
check("fix mercevel a BTCUSD-eset BUKIK a kapun",
      vb.failed(row_quiet["atr"], p_fix, row_quiet["atr_avg"]))
check("gordulo mercevel ATMEGY",
      not vb.failed(row_quiet["atr"],
                    {**p_fix, "atr_baseline_bars": 96 * 90}, row_quiet["atr_avg"]),
      "a sor atr_avg-ja a merce, tehat az arany 1,00")
check("a bt_entry mar NEM szur (csak meretez)",
      strat.bt_entry(row_quiet, p_fix, 0.01) is not None)

# A bt_indicators oszlopa a KOZOS modulbol jojjon
df_hi = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0},
                     index=idx)
try:
    ind, _ = strat.bt_indicators(df_hi, df_hi, {"sma_period": 5, "wpr_m15_period": 5,
                                                "wpr_m1_period": 5, "atr_period": 5,
                                                "atr_baseline_bars": 100})
    got = "atr_avg" in ind.columns and float(ind["atr_avg"].std()) >= 0.0
    check("a bt_indicators ad atr_avg oszlopot", got)
except Exception as e:
    check("a bt_indicators ad atr_avg oszlopot", False, str(e)[:60])

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
