"""A „SZEP CHART" MEROSZAMOK ORE — kulonos tekintettel a LOOK-AHEAD-re.

⚠ MIERT EZ A LEGFONTOSABB ALLITAS ITT. Egy swing-csucshoz a JOBB oldali n
gyertya is kell (a [i-n, i+n] ablak maximuma), az viszont a dontes pillanataban
meg nem letezik. Ha a maszk nincs eltolva, a meroszam a JOVOT olvassa, es akkor
minden backteszt gyonyoruen mukodik — a projekt tobbszor futott mar bele ebbe
(viz↔backtest paritas, a kutato-labor `_map_to`-ja).

Az itteni ellenorzes ERO: a jovobeli gyertyak MEGVALTOZTATASA nem valtoztathatja
meg a mult meroszamait. Ha valaki kiveszi az eltolast, EZ a teszt bukik el.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402
from core import chart_quality as CQ  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def _adat(n=600, mag=7):
    rng = np.random.default_rng(mag)
    ar = 100 + np.cumsum(rng.normal(0, 0.5, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": ar, "high": ar + 0.3, "low": ar - 0.3,
                         "close": ar}, index=idx)


df = _adat()

# ── 1. LOOK-AHEAD: a jovo megvaltoztatasa nem hat a multra ──────────────
VAG = 400
csonk = df.iloc[:VAG].copy()

masolat = df.copy()                       # a VAG utani reszt SZETVERJUK
masolat.iloc[VAG:, :] = masolat.iloc[VAG:, :] * 3.0

for nev, fn in (("swing-maszk (csucs)", lambda d: CQ.swing_mask(d)[0].astype(float)),
                ("swing-maszk (volgy)", lambda d: CQ.swing_mask(d)[1].astype(float)),
                ("trendline_r2(100)", lambda d: CQ.trendline_r2(d, 100)),
                ("r2_multi(min)", lambda d: CQ.r2_multi(d))):
    a = fn(df).iloc[:VAG - CQ.SWING_N]
    b = fn(masolat).iloc[:VAG - CQ.SWING_N]
    egyezik = bool(np.allclose(a.fillna(-1).to_numpy(), b.fillna(-1).to_numpy()))
    check(f"{nev}: a JOVO atirasa nem valtoztatja a multat", egyezik)

# A csonkitott adaton szamolt ertek is ugyanaz (nem csak a felulirt jovonel)
a = CQ.trendline_r2(df, 100).iloc[:VAG - CQ.SWING_N]
b = CQ.trendline_r2(csonk, 100).iloc[:VAG - CQ.SWING_N]
check("a csonkitott elozmenyen ugyanaz jon ki",
      bool(np.allclose(a.fillna(-1).to_numpy(), b.fillna(-1).to_numpy())))

# ── 2. A swing-maszk TENYLEG eltolt ────────────────────────────────────
cs, _ = CQ.swing_mask(df)
h = df["high"].to_numpy()
n = CQ.SWING_N
hol = np.flatnonzero(cs.to_numpy())
jo = all(h[i - n] == h[max(0, i - 2 * n):i + 1].max() for i in hol if i >= 2 * n)
check("minden jelolt swing a t-n baron van, es ott az ablak maxa", jo,
      f"{len(hol)} swing")
check("az elso n bar nem lehet swing (nincs meg mit igazolni)",
      not cs.iloc[:n].any())

# ── 3. AZ R² ERTELMES ───────────────────────────────────────────────────
# ⚠ A TOKELETES EGYENES DEGENERALT ESET: szigoruan monoton sorozatnak nincs
# lokalis szelsoerteke, tehat NINCS swing-pont -> nincs mire vonalat illeszteni.
# A `NaN` itt nem „csunya", hanem „nincs iteletem". Ezt ALLITJUK, nem rejtjuk.
lin = np.arange(600, dtype=float) * 0.1 + 100
idx = pd.date_range("2025-01-01", periods=600, freq="15min", tz="UTC")
egyenes = pd.DataFrame({"open": lin, "high": lin + 0.2, "low": lin - 0.2,
                        "close": lin}, index=idx)
check("tokeletesen monoton szakaszon NINCS swing -> NaN (dokumentalt eset)",
      bool(CQ.trendline_r2(egyenes, 100).isna().all()))

# ZAJOS trend (van visszahuzodas) -> magas R2; feher zaj -> alacsony
rng = np.random.default_rng(11)
tr = lin + rng.normal(0, 0.6, 600)
trend = pd.DataFrame({"open": tr, "high": tr + 0.2, "low": tr - 0.2,
                      "close": tr}, index=idx)
r_tr = CQ.trendline_r2(trend, 100).dropna()
r_zaj = CQ.trendline_r2(_adat(600, 3), 100).dropna()
check("zajos TRENDEN magas az R2", bool(r_tr.median() > 0.85),
      f"median={r_tr.median():.3f}")
check("feher zajon erdemben alacsonyabb", bool(r_zaj.median() < r_tr.median() - 0.2),
      f"zaj={r_zaj.median():.3f} vs trend={r_tr.median():.3f}")
check("az R2 a [0,1] savban marad",
      bool(r_zaj.min() >= 0.0 and r_zaj.max() <= 1.0))

# ── 4. A MULTI-SCALE OSSZEVONAS ────────────────────────────────────────
mn = CQ.r2_multi(df, mod="min").dropna()
mx = CQ.r2_multi(df, mod="max").dropna()
mean = CQ.r2_multi(df, mod="mean").dropna()
k = mn.index.intersection(mx.index).intersection(mean.index)
check("min <= mean <= max minden baron",
      bool((mn[k] <= mean[k] + 1e-9).all() and (mean[k] <= mx[k] + 1e-9).all()))
check("az alapertelmezes a MIN (a konzervativ irany)",
      bool(np.allclose(CQ.r2_multi(df).fillna(-1), mn.reindex(df.index).fillna(-1))))

# ── 5. A KEVES PONT NEM AD ITELETET ────────────────────────────────────
# 2 pontra az R2 mindig 1 lenne — ezert MIN_SWING a kapu.
check("legalabb 3 swing-pont kell (2-re az R2 mindig 1,0 lenne)",
      CQ.MIN_SWING >= 3, f"MIN_SWING={CQ.MIN_SWING}")
rovid = CQ.trendline_r2(df.iloc[:20], 100)
check("keves adatnal NaN, nem hamis biztonsag", bool(rovid.isna().all()))

# ── 6. A KUSZOBOK A TANANYAGBOL ────────────────────────────────────────
check("a tananyag kuszobei valtozatlanul szerepelnek",
      CQ.R2_SZEP == 0.80 and CQ.R2_CHOPPY == 0.50)
_src = (ROOT / "core" / "chart_quality.py").read_text(encoding="utf-8")
check("a modul kimondja, hogy CSAK MER (nem kapu, nem szur)",
      "CSAK MÉR" in _src and "Nem kapu" in _src)
check("a look-ahead veszelye dokumentalva van", "look-ahead" in _src.lower())

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
