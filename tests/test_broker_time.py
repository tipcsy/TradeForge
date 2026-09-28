"""BRÓKER-IDŐ → KANONIKUS IDŐ, és a szerver-zóna felismerése.

⚠ MIT ŐRZÜNK (0029 „Több bróker egyszerre", 2026-09-28):
  1. A kanonikus zóna (Europe/Berlin = a mai ActivTrades szerver) ÜRES
     átváltás — ugyanazt az OBJEKTUMOT adja vissza. Ha ez eltörne, a mai
     egy-brókeres működés minden órája megváltozhatna.
  2. Egy NY-zárásos szerver (America/New_York+7) gyertyája a kanonikus órára
     helyesen kerül — télen, nyáron, ÉS az évi ~4 eltérő héten, amikor az USA
     már/még nyári időben van, Európa nem. Ez a hét az, amin egy naiv
     „+1 óra" eltolás NÉMÁN hibázna.
  3. A felismerő eszköz a VALÓDI VILÁGÓRA horgonyain (08:30/09:30/10:00 NY)
     dolgozik, NEM a heti nyitáson — az ActivTrades a saját éjfelén nyit, és a
     heti nyitás így a Berlint hamisan „NY+6"-nak mérte (2026-09-28).
"""
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from core import applog                                                  # noqa: E402
applog.harden_console()

import numpy as np                                                       # noqa: E402
import pandas as pd                                                      # noqa: E402

from core import broker_time as BT                                       # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------
print("== A zona leirasa ==")
check("None -> kanonikus", BT.parse(None).is_canonical)
check("ures -> kanonikus", BT.parse("").is_canonical)
check("'Europe/Berlin' -> kanonikus", BT.parse("Europe/Berlin").is_canonical)
nyz = BT.parse("America/New_York+7")
check("'America/New_York+7' -> zona + 7 ora",
      (nyz.zone, nyz.shift_h) == ("America/New_York", 7), str(nyz))
check("'UTC-3' negativ eltolas", BT.parse("UTC-3").shift_h == -3)
try:
    BT.parse("Europe/Berlni")
    check("elgepelt zona -> ValueError (NEM csendes visszaeses)", False)
except ValueError:
    check("elgepelt zona -> ValueError (NEM csendes visszaeses)", True)
check("config nelkul kanonikus", BT.of_config({}).is_canonical)
check("config broker.server_zone", str(BT.of_config(
    {"broker": {"server_zone": "America/New_York+7"}})) == "America/New_York+7")

# ---------------------------------------------------------------------------
print("\n== A kanonikus zona URES atvaltas (a mai viselkedes bitre) ==")
idx = pd.date_range("2026-03-10", periods=5, freq="1min", tz="UTC")
check("index: ugyanaz az objektum", BT.index_to_canonical(idx, BT.CANONICAL) is idx)
df = pd.DataFrame({"close": range(5)}, index=idx)
check("tabla: ugyanaz az objektum", BT.frame_to_canonical(df, BT.CANONICAL) is df)
t = dt.datetime(2026, 3, 10, 9, 0)
check("idopont: ugyanaz", BT.to_canonical(t, BT.CANONICAL) is t)

# ---------------------------------------------------------------------------
print("\n== NY+7 szerver -> kanonikus (hetfo 00:00 szerver = NY vasarnap 17:00) ==")
# Tel:  NY EST (UTC-5), Berlin CET (UTC+1)   -> 22:00 UTC = 23:00 Berlin
# Nyar: NY EDT (UTC-4), Berlin CEST (UTC+2)  -> 21:00 UTC = 23:00 Berlin
# ELTERO HET (2026-03-16): NY mar EDT (03-08 ota), Berlin meg CET (03-29-ig)
#                          -> 21:00 UTC = 22:00 Berlin  <- a naiv +1 ora itt hibazna
esetek = (("tel", dt.datetime(2026, 1, 12, 0, 0), dt.datetime(2026, 1, 11, 23, 0)),
          ("nyar", dt.datetime(2026, 6, 15, 0, 0), dt.datetime(2026, 6, 14, 23, 0)),
          ("ELTERO het (marc.)", dt.datetime(2026, 3, 16, 0, 0), dt.datetime(2026, 3, 15, 22, 0)),
          ("ELTERO het (nov.)", dt.datetime(2025, 11, 2, 18, 0) + dt.timedelta(hours=6),
           dt.datetime(2025, 11, 2, 23, 0)))
for cim, szerver, vart in esetek:
    kap = BT.to_canonical(szerver, nyz)
    check(f"{cim}: {szerver:%m-%d %H:%M} -> {vart:%m-%d %H:%M}", kap == vart, f"{kap}")
    vx = BT.index_to_canonical(pd.DatetimeIndex([szerver]).tz_localize("UTC"), nyz)
    check(f"{cim}: vektoros == egyedi (a UTC-cimke megmarad)",
          vx[0] == pd.Timestamp(vart, tz="UTC"), str(vx[0]))

u = dt.datetime(2026, 3, 16, 13, 30, tzinfo=dt.timezone.utc)
check("oda-vissza: utc -> fal -> utc", BT.wall_to_utc(BT.utc_to_wall(u, nyz), nyz) == u)

df2 = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.DatetimeIndex(
    [dt.datetime(2026, 1, 12, 0, 0), dt.datetime(2026, 1, 12, 0, 1)]).tz_localize("UTC"))
out = BT.frame_to_canonical(df2, nyz)
check("tabla atvaltas: az adat valtozatlan, csak az index", list(out.close) == [1.0, 2.0]
      and out.index[0] == pd.Timestamp("2026-01-11 23:00", tz="UTC"))

# ---------------------------------------------------------------------------
print("\n== A felismero: mesterseges piac, ismert zonaval ==")
import detect_server_zone as D                                           # noqa: E402


def piac(sz: BT.ServerZone, napok=500, seed=1) -> pd.DataFrame:
    """Hetkoznapi M1, NY 01:00-12:30. Alapzaj + TARTOS lepcsok a valodi
    nyitasoknal (London 08:00 London-ido x1,6; NYSE 09:30 NY-ido x2,5) +
    pontszeru hir-tuskek NY 08:30-kor (a napok 1/3-an, x9) — ez utobbi a
    csapda, ami a perc-alapu mercet megtevesztette. Fal-ora `sz` szerint."""
    rng = np.random.default_rng(seed)
    napok_ = pd.bdate_range("2023-01-02", periods=napok)
    perc = np.arange(60, 12 * 60 + 30)
    ny = (pd.DatetimeIndex(np.repeat(napok_.values, len(perc)))
          + pd.to_timedelta(np.tile(perc, len(napok_)), unit="min"))
    ny = ny.tz_localize("America/New_York", nonexistent="shift_forward",
                        ambiguous=np.zeros(len(ny), bool))
    utc = ny.tz_convert("UTC")
    lon = utc.tz_convert("Europe/London")
    lp = np.asarray(lon.hour * 60 + lon.minute)
    npp = np.asarray(ny.hour * 60 + ny.minute)
    v = rng.gamma(2.0, 1.0, len(ny))
    v *= np.where(lp >= 8 * 60, 1.6, 1.0)
    v *= np.where(npp >= 9 * 60 + 30, 2.5, 1.0)
    hirnap = np.repeat(rng.random(len(napok_)) < 1 / 3, len(perc))
    v *= np.where((npp == 8 * 60 + 30) & hirnap, 9.0, 1.0)
    fal = (utc.tz_convert(sz.zone).tz_localize(None)
           + pd.Timedelta(hours=sz.shift_h)).tz_localize("UTC")
    return pd.DataFrame({"high": v, "low": np.zeros_like(v)}, index=fal)


for igazi in (BT.ServerZone("America/New_York", 7), BT.ServerZone("Europe/Berlin", 0)):
    T = D.felismer(piac(igazi))
    b = T.iloc[0]
    check(f"igazi {igazi}: a felismero ezt adja", b.zona == str(igazi),
          f"{b.zona} {b.lepcso:.2f} / 2. {T.iloc[1].zona} {T.iloc[1].lepcso:.2f}")
    # az ellen-szabalyu (EU vs USA nyari ido, NYARON azonos eltolasu) jelolt
    # csak az ELTERO heteken kulonbozik — ott kell lemaradnia
    ellen = "Europe/Athens" if igazi.zone == "America/New_York" else "America/New_York+6"
    r_ellen = T[T.zona == ellen].iloc[0]
    check(f"igazi {igazi}: az ellen-szabaly ({ellen}) az eltero heteken lemarad",
          b.elteres_heteken - r_ellen.elteres_heteken >= 0.10,
          f"{b.elteres_heteken:.2f} vs {r_ellen.elteres_heteken:.2f}")

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
