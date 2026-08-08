"""
A kuszob ahhoz a modellhez tartozzon, amelyik ki is szolgalja.

A REGI eljaras: a modell a train 80%-an tanult, a kuszob a maradek 20%-on
kalibralodott, majd a mentett csomagba a TELJES train-en UJRATANITOTT modell
kerult. A kuszob igy MAS eloszlasra vonatkozott, mint amire alkalmaztuk — a
vegso modell a sajat tanitoadatan mar kozel tokeletes (merve: AUC 0,87-0,92),
tehat ott a 0,81-es kuszob a TENYLEGES nyeroket valogatta ki; friss adaton
(AUC ~0,50) ugyanaz a kuszob mar csak ermet dob. Innen a 70% -> 26% szakadek.

AZ UJ: a kuszob es az AUC a TELJES train-re vett FOLD-ON KIVULI valoszinusegekbol
jon (`oof_proba`), tisztito savval (a cimke elorenez, tehat a szomszedos sorok
kimenete atfed).

A tesztek SZINTETIKUS adaton futnak: gyorsak, determinisztikusak, es pontosan azt
a kulonbseget merik, ami az eles hibat okozta.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

import numpy as np                                    # noqa: E402
import pandas as pd                                   # noqa: E402
from sklearn.metrics import roc_auc_score             # noqa: E402

from strategy import ml_train as mt                   # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


rng = np.random.default_rng(7)
N, F = 3000, 8

# ---------------------------------------------------------------------------
print("== Tiszta ZAJ: a fold-on kivuli AUC ne igerjen tudast ==")
X_noise = rng.normal(size=(N, F))
y_noise = rng.integers(0, 2, size=N)

p_oof, _eng = mt.oof_proba(X_noise, y_noise, ratio=1.0, n_splits=5, purge=32)
ok = ~np.isnan(p_oof)
auc_oof = roc_auc_score(y_noise[ok], p_oof[ok])

# ...miközben ugyanaz a modell a SAJAT tanitoadatan latvanyosan "tud"
m, _ = mt._make_classifier(1.0)
m.fit(X_noise, y_noise)
auc_in = roc_auc_score(y_noise, m.predict_proba(X_noise)[:, 1])

print(f"     fold-on kivul: {auc_oof:.3f}   |   sajat tanitoadaton: {auc_in:.3f}")
check("zajon a fold-on kivuli AUC ~0,5", 0.44 < auc_oof < 0.56, f"{auc_oof:.3f}")
check("a teljes illesztes ELLENBEN memorizal (ez volt a hiba forrasa)",
      auc_in > 0.75, f"{auc_in:.3f}")
check("a ketto kozott nagy a szakadek", auc_in - auc_oof > 0.2,
      f"{auc_in - auc_oof:.3f}")

# ---------------------------------------------------------------------------
print("== VALODI jel: a fold-on kivuli AUC vegye eszre ==")
X_sig = rng.normal(size=(N, F))
y_sig = (X_sig[:, 0] + 0.35 * rng.normal(size=N) > 0).astype(int)
p_sig, _ = mt.oof_proba(X_sig, y_sig, ratio=1.0, n_splits=5, purge=32)
ok_s = ~np.isnan(p_sig)
auc_sig = roc_auc_score(y_sig[ok_s], p_sig[ok_s])
check("tanulhato adaton magas a fold-on kivuli AUC", auc_sig > 0.85,
      f"{auc_sig:.3f}")
check("minden sor kapott valoszinuseget", ok_s.sum() == N, f"{ok_s.sum()}/{N}")
check("a valoszinusegek 0..1 kozott vannak",
      float(np.nanmin(p_sig)) >= 0.0 and float(np.nanmax(p_sig)) <= 1.0)

# ---------------------------------------------------------------------------
print("== A tisztito sav tenyleg kivag ==")
# Akkora savval, ami a tanito reszt 200 sor ala viszi, nem szabad becslest adni
p_purged, _ = mt.oof_proba(X_sig[:600], y_sig[:600], ratio=1.0,
                           n_splits=2, purge=400)
check("tul nagy tisztito savnal NINCS becsles (nem talal ki adatot)",
      bool(np.isnan(p_purged).all()), f"{int((~np.isnan(p_purged)).sum())} nem-NaN")

check("a fold-szam szamit (2 fold is lefut)",
      bool((~np.isnan(mt.oof_proba(X_sig, y_sig, 1.0, n_splits=2, purge=8)[0])).all()))

# ---------------------------------------------------------------------------
print("== AUC-padlo: nulla jelre ne elesedjen ==")


def _frame(X, y):
    cols = [f"f{i}" for i in range(X.shape[1])]
    df = pd.DataFrame(X, columns=cols)
    df["label_long"] = y
    return df, cols


df_n, cols_n = _frame(X_noise, y_noise)
d, stats = mt._train_direction(df_n, "label_long", cols_n,
                               min_wr=0.4, max_coverage=0.08, min_signals=40,
                               purge=32, n_splits=5, min_auc=0.52)
check("zajon az irany KIKAPCSOL", d is None and not stats.get("enabled"))
check("...es megmondja MIERT (AUC)", "AUC" in (stats.get("reason") or ""),
      (stats.get("reason") or "")[:60])
check("a statisztika kozli a mert AUC-t", stats.get("auc") is not None,
      f"{stats.get('auc')}")

df_s, cols_s = _frame(X_sig, y_sig)
d2, st2 = mt._train_direction(df_s, "label_long", cols_s,
                              min_wr=0.4, max_coverage=0.5, min_signals=40,
                              purge=32, n_splits=5, min_auc=0.52)
check("valodi jelen az irany AKTIV lesz", d2 is not None and st2.get("enabled"),
      f"AUC={st2.get('auc'):.3f} kuszob={st2.get('threshold')}" if d2 else str(st2))
if d2:
    check("a mentett modell a TELJES train-en tanult",
          st2.get("train_rows") == len(df_s), f"{st2.get('train_rows')}")
    check("a kuszob ertelmes tartomanyban van",
          0.44 <= d2["threshold"] <= 0.95, f"{d2['threshold']}")
    check("a csomag scalert is visz", d2.get("scaler") is not None)

# A padlo LEGYEN kikapcsolhato (a kutatashoz), de alapbol vedjen
d3, st3 = mt._train_direction(df_n, "label_long", cols_n,
                              min_wr=0.0, max_coverage=1.0, min_signals=40,
                              purge=32, n_splits=5, min_auc=0.0)
check("min_auc=0 mellett a padlo nem szol bele",
      "AUC" not in (st3.get("reason") or ""), (st3.get("reason") or "(nincs)")[:50])
check("az alapertelmezett padlo 0,52", abs(mt.MIN_MODEL_AUC - 0.52) < 1e-9,
      str(mt.MIN_MODEL_AUC))

# ---------------------------------------------------------------------------
print("== A kuszob VARHATO ERTEKRE kalibral, nem talalati aranyra ==")

check("expected_r: RR 2-nel a nullszaldo 1/3",
      abs(mt.expected_r(1 / 3, 2.0)) < 1e-9, f"{mt.expected_r(1/3, 2.0):.6f}")
check("expected_r: RR 1-nel a nullszaldo 1/2",
      abs(mt.expected_r(0.5, 1.0)) < 1e-9)
check("expected_r: 50% RR 2-nel +0,5R", abs(mt.expected_r(0.5, 2.0) - 0.5) < 1e-9)

# Wilson: kis mintan tavol, nagy mintan kozel az arany
lb_small = mt.wilson_lower(10, 20, 1.96)
lb_big = mt.wilson_lower(500, 1000, 1.96)
print(f"     10/20 -> {lb_small:.3f}   |   500/1000 -> {lb_big:.3f}   (mindketto 50%)")
check("kis mintan az also korlat messze van", lb_small < 0.35, f"{lb_small:.3f}")
check("nagy mintan tapad", lb_big > 0.45, f"{lb_big:.3f}")
check("a korlat SOSEM nagyobb a nyers aranynal", lb_big <= 0.5 and lb_small <= 0.5)
check("nulla mintara 0", mt.wilson_lower(0, 0) == 0.0)
check("szigorubb z -> alacsonyabb korlat",
      mt.wilson_lower(60, 100, 1.96) < mt.wilson_lower(60, 100, 1.28))

# A LENYEG: sok jel kozepes aranyon tobbet er, mint keves jel magas aranyon.
# Ket szigetet epitunk a valoszinusegbe: a legfelso 1% 60%-os, a felso 30% 42%-os.
rng2 = np.random.default_rng(11)
N2 = 4000
p2 = rng2.uniform(0.0, 0.94, size=N2)
y2 = np.zeros(N2, dtype=int)
top = p2 >= 0.90                      # ~1% — nagyon jo arany, keves jel
mid = (p2 >= 0.60) & (p2 < 0.90)      # ~36% — nullszaldo folott, sok jel
y2[top] = (rng2.random(top.sum()) < 0.60).astype(int)
y2[mid] = (rng2.random(mid.sum()) < 0.42).astype(int)
y2[~(top | mid)] = (rng2.random((~(top | mid)).sum()) < 0.20).astype(int)

thr_e, st_e = mt._calibrate_threshold(p2, y2, 0.0, 0.5, 40, rr=2.0, z=1.28)
print(f"     valasztott kuszob={thr_e:.2f}  jelek={st_e['signals']}  "
      f"WR={100*st_e['win_rate']:.1f}%  E[R]alsó={st_e['expected_r_lb']:+.3f}")
check("a szeles, kozepes aranyu savot valasztja (nem a szuk farkat)",
      st_e["signals"] > 400, f"{st_e['signals']} jel")
check("...es a kuszob a sav aljan van", thr_e < 0.85, f"{thr_e:.2f}")
check("pozitiv a konzervativ varhato ertek", st_e["expected_r_lb"] > 0,
      f"{st_e['expected_r_lb']:+.3f}")
check("a stat kozli az RR-t es a z-t", st_e.get("rr") == 2.0 and st_e.get("calib_z") == 1.28)

# Nullszaldo ALATTI arany: barmennyi jellel is el kell utasitani
y_bad = (rng2.random(N2) < 0.30).astype(int)      # 30% < 33,3%
_, st_bad = mt._calibrate_threshold(p2, y_bad, 0.0, 1.0, 40, rr=2.0, z=1.28)
check("nullszaldo alatti aranyt sok jellel sem fogad el",
      not st_bad.get("enabled"), f"kuszob={st_bad.get('threshold')}")
check("...es megmondja, mennyi kellene",
      "nullszaldó" in (st_bad.get("reason") or ""), (st_bad.get("reason") or "")[:60])

# Ugyanaz az arany MAGASABB RR-nel mar elfogadhato (a kriterium RR-tudatos)
_, st_rr = mt._calibrate_threshold(p2, y_bad, 0.0, 1.0, 40, rr=5.0, z=1.28)
check("magasabb RR-nel ugyanaz az arany mar atmegy", bool(st_rr.get("enabled")),
      f"E[R]alsó={st_rr.get('expected_r_lb'):+.3f}")

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
