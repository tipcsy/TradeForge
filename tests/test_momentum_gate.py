"""A LENDULET kapu — core/momentum.py + a gates-beli mod/hatas + backtest-paritas.

A fordulatszammero: elojeles, normalt szam. Elojel = irany, nagysag = mennyire
porog. Ket meresi alap valaszthato (egy idosik 3 SMA-val / harom idosik).

A LEGFONTOSABB, AMIT ORIZ: a backtest sorozata NEM LAT A JOVOBE. A `series_at`
a gyertya ZARASI idejere indexel, tehat egy `t` pillanatbeli dontes csak az addig
LEZART gyertyakat hasznalja. Ha nyitasi idore indexelnenk, a dontes a sajat,
meg formalodo gyertyajanak vegleges zaroarat latna — pontosan az a hiba, amit a
`tf_align` kapunal is javitani kellett (`test_tf_align_lookahead.py`).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

import numpy as np
import pandas as pd

from core import gates as g
from core import momentum as m

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. A MERES ═════════════════════════════════════════════════════════════
# Egyenletesen EMELKEDO ar: a gyors atlag a lassu FOLOTT -> pozitiv fordulat.
up = list(np.arange(0, 300, 1.0))
down = list(np.arange(300, 0, -1.0))
flat = [100.0] * 300

check("emelkedo piacon a fordulat POZITIV", m.rpm_sma(up) > 0, f"{m.rpm_sma(up):.2f}")
check("eso piacon NEGATIV", m.rpm_sma(down) < 0, f"{m.rpm_sma(down):.2f}")
check("...es az irany ebbol jon",
      m.direction(m.rpm_sma(up)) == "BUY" and m.direction(m.rpm_sma(down)) == "SELL")

# Teljesen ALLO piac: nincs elmozdulas -> a merce 0, nem tudunk merni (nan).
check("teljesen allo piacon nincs ertelmes meres (nan, nem 0)",
      math.isnan(m.rpm_sma(flat)))
check("...es a nan NEM szur (fail-open)", not m.is_idle(float("nan")))

# NORMALAS: ugyanaz az alakzat mas ARSZINTEN ugyanazt a fordulatot adja. Ez a
# lenyeg — enelkul a kuszob GOLD-on es EURUSD-n mast jelentene.
scaled = [x * 1000 + 50000 for x in up]
check("a mutato AR-SZINT-fuggetlen (GOLD es EURUSD ugyanazt a szamot adja)",
      abs(m.rpm_sma(up) - m.rpm_sma(scaled)) < 1e-9,
      f"{m.rpm_sma(up):.6f} vs {m.rpm_sma(scaled):.6f}")

# Alapjarat: zajos, iranytalan piac -> kicsi |fordulat|
rng = np.random.default_rng(5)
# Valoban IRANYTALAN: oszcillal egy szint korul (a bolyongas trendelne, es akkor
# az allitas nem azt merne, amit mond).
noise = list(100 + np.sin(np.arange(600) / 7.0) * 0.5 + rng.normal(0, 0.05, 600))
check("zajos, iranytalan piacon a fordulat kicsi (alapjarat)",
      abs(m.rpm_sma(noise)) < abs(m.rpm_sma(up)),
      f"{m.rpm_sma(noise):.2f} vs {m.rpm_sma(up):.2f}")

# Keves gyertya -> nan (nem veletlenszeru dontes)
check("keves gyertyanal nan", math.isnan(m.rpm_sma(up[:20])))

# `tf` alap: tobb idosik atlaga
tf_closes = {1: up, 5: up, 15: down}
check("a `tf` alap az idosikok atlagat adja",
      not math.isnan(m.rpm_tf(tf_closes, [1, 5, 15], {"basis": "tf"})))
check("a hianyzo idosikot KIHAGYJA (nem nullazza)",
      abs(m.rpm_tf({1: up}, [1, 5, 15], {"basis": "tf"})
          - m.rpm_tf({1: up}, [1], {"basis": "tf"})) < 1e-12)

# Melyik idosikok kellenek
check("az `sma` alap EGY idosikot ker", m.needed_timeframes({"basis": "sma"}) == [15])
check("a `tf` alap HARMAT (M1/M5/M15 az alap)",
      m.needed_timeframes({"basis": "tf"}) == [1, 5, 15])


# ══ 2. A KAPU BUKASA — mod szerint ═════════════════════════════════════════
P = {"idle_threshold": 0.35}
check("idle mod: alapjaraton bukik", m.failed(0.10, "BUY", "idle", P))
check("idle mod: porgo piacon nem bukik", not m.failed(2.0, "BUY", "idle", P))
check("dir mod: SZEMBEN meno fordulatnal bukik", m.failed(2.0, "SELL", "dir", P))
check("dir mod: egyezo iranynal nem bukik", not m.failed(2.0, "BUY", "dir", P))
check("dir mod: alapjarat NEM erdekli", not m.failed(0.10, "BUY", "dir", P))
check("both mod: mindket okbol bukhat",
      m.failed(0.10, "BUY", "both", P) and m.failed(2.0, "SELL", "both", P))
check("adathianynal (nan) SOHA nem bukik (fail-open)",
      not m.failed(float("nan"), "BUY", "both", P))


# ══ 3. CONFIG: hatas + mod, orokléssel ═════════════════════════════════════
check("uj kapu alapbol NEM szol bele (a frissites nem kereskedik maskepp)",
      g.effect_for({}, "GOLD", "wpr_sma", g.MOMENTUM) == g.EFFECT_NONE)
check("...es igy a motor mérni sem kezdi",
      not g.active(g.effects_for({}, "GOLD", "wpr_sma"), g.MOMENTUM))

cfg = {"pairs": {"GOLD": {"gates": {g.MOMENTUM: {
    "wpr_sma": {"effect": g.EFFECT_BLOCK, "mode": g.MOM_DIR},
    "idle_threshold": 0.5, "basis": "tf"}}}}}
check("a szotaras bejegyzesbol a HATAS kiolvashato",
      g.effect_for(cfg, "GOLD", "wpr_sma", g.MOMENTUM) == g.EFFECT_BLOCK)
check("...es a MOD is", g.mode_for(cfg, "GOLD", "wpr_sma") == g.MOM_DIR)
check("a merési parameterek UGYANEBBOL a szotarbol jonnek",
      g.momentum_config(cfg["pairs"]["GOLD"], cfg)["idle_threshold"] == 0.5)
check("...a strategia-nevek es a meresi kulcsok nem utkoznek",
      g.momentum_config(cfg["pairs"]["GOLD"], cfg)["basis"] == "tf")
check("a mod alapja az `idle`, ha nincs megadva",
      g.mode_for({}, "GOLD", "ml_ai") == g.MOM_IDLE)

# A REGI, egyszeru (string) alak valtozatlanul ervenyes — a meglevo configok
# nem tornek el attol, hogy a Lendulet szotarat is ertjuk.
old = {"pairs": {"GOLD": {"gates": {g.SPREAD: {"wpr_sma": g.EFFECT_REDUCE}}}}}
check("a REGI string-alak valtozatlanul mukodik",
      g.effect_for(old, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_REDUCE)


# ══ 4. BACKTEST-SOROZAT — a look-ahead ellen ═══════════════════════════════
# M1 adat: 3 napnyi, egy ELES fordulattal a kozepen. A fordulat UTANI ertek nem
# szivaroghat vissza a fordulat ELOTTI dontesekbe.
N = 3 * 1440
idx1 = pd.date_range("2026-01-05", periods=N, freq="1min", tz="UTC")
half = N // 2
prices = np.concatenate([np.full(half, 100.0) + np.arange(half) * 0.001,
                         np.full(N - half, 100.0 + half * 0.001)
                         - np.arange(N - half) * 0.02])
df_m1 = pd.DataFrame({"open": prices, "high": prices + 0.01,
                      "low": prices - 0.01, "close": prices}, index=idx1)
m15_idx = idx1[::15]

ser = m.series_at(df_m1, m15_idx, {"basis": "sma", "timeframe": 15})
check("a backtest-sorozat a dontesi idopontokra all", len(ser) == len(m15_idx))

# A LENYEG: minden `t`-re a sorozat erteke KISZAMOLHATO a t-ig lezart gyertyakbol.
# Ellenprobat futtatunk: a t UTANI adatot ELDOBVA ugyanazt kell kapnunk.
mismatch, tested = 0, 0
# A warmup (SMA100 az M15-on) ~1785 M1-gyertya, ezert csak azon TULI pontokat
# vetjuk ossze — elotte mindket oldal NaN, az nem bizonyitana semmit.
for t in m15_idx[::7]:
    truncated = df_m1[df_m1.index < t]        # SZIGORUAN t elott lezart M1-ek
    if len(truncated) < 2000:
        continue
    a = ser.get(t, float("nan"))
    b = m.series_at(truncated, [t], {"basis": "sma", "timeframe": 15}).iloc[0]
    tested += 1
    if not (math.isnan(a) and math.isnan(b)) and abs((a or 0) - (b or 0)) > 1e-9:
        mismatch += 1
check(f"NINCS LOOK-AHEAD: a t-utani adat eldobasa nem valtoztat ({tested} pont)",
      mismatch == 0 and tested >= 20, f"elteres={mismatch}, ellenorzott={tested}")

# Ellenproba: a hibas (nyitasi idore indexelt) valtozat ELBUKNA ezen. A fordulat
# koruli pontokon a ket ertek elter, ha a dontes belelat a sajat gyertyajaba.
turn = m15_idx[len(m15_idx) // 2]
before = ser[ser.index < turn].dropna()
after = ser[ser.index > turn].dropna()
check("a sorozat a fordulat elott POZITIV, utana NEGATIV lesz",
      before.iloc[-1] > 0 and after.iloc[-1] < 0,
      f"{before.iloc[-1]:.2f} -> {after.iloc[-1]:.2f}")

# A `tf` alap is mukodik M1-bol resample-elve (a backtestben nincs nativ M5)
ser_tf = m.series_at(df_m1, m15_idx, {"basis": "tf", "timeframes": [1, 5, 15],
                                      "tf_sma": 50})
check("a `tf` alap M1-bol resample-elve is ad sorozatot",
      ser_tf.notna().sum() > 0, f"ervenyes={int(ser_tf.notna().sum())}")

# A kezdeti (warmup) szakasz NaN — ott a kapu nem szur
check("a warmup szakasz NaN (ott a kapu nem szur)", math.isnan(ser.iloc[0]))


# ══ 5. A cella szovege ═════════════════════════════════════════════════════
check("a cella nyilat es nagysagot mutat", m.cell_text(1.234) == "↑1.23",
      m.cell_text(1.234))
check("...lefele is", m.cell_text(-0.5) == "↓0.50", m.cell_text(-0.5))
check("...adathianynal em-dash", m.cell_text(float("nan")) == "—")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
