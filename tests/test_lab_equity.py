"""A LABOR SZAMLAGORBEJE (0009, 4. lepcso) — realizalt vs equity.

⚠ MIERT KELL KET GORBE, es miert epp ez a kulonbsegük a lenyeg:

  • REALIZALT — csak a LEZART kotesek; ez a „mi van a zsebemben".
  • EQUITY    — a realizalt PLUSZ a nyitott poziciok lebego eredmenye; ez az,
                amit a broker mutat, es amin a DRAWDOWN latszik.

Egy strategia lehet realizaltban szep es equityben remes (mely visszaesesek,
amiket „kiul") — ezt CSAK a ketto egyutt mutatja meg.

⚠ MIERT VAN EZ KULON, TESZTELHETO FUGGVENYBEN. A szamitas metoduskent csak elo
Qt-ablakkal futna, tehat tesztelni sem lehetne — pedig epp ez az, ami CSENDBEN
tud hibazni: egy bar-index elcsuszas nem latszik a charton, csak rossz gorbet
rajzol. Ezert `szamla_gorbe()` modul-szintu.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


try:
    from tools.lab_qt import szamla_gorbe
except Exception as _e:            # a Qt hianya ne buktassa az EGESZ csomagot
    print(f"  (kihagyva: a lab_qt nem importalhato — {type(_e).__name__}: {_e})")
    print("\n0/0 teszt PASS")
    sys.exit(0)


class Kotes:
    """A `Trade` minimalis masa — csak amit a gorbe olvas."""

    def __init__(self, nyit, zar, irany, be_ar, pnl, sl_points=10.0,
                 point_size=1.0, risk_usd=100.0):
        self.open_time = nyit
        self.close_time = zar
        self.direction = irany
        self.open_price = be_ar
        self.pnl_usd = pnl
        self.sl_points = sl_points
        self.point_size = point_size
        self.risk_usd = risk_usd


IDX = pd.date_range("2026-01-05 08:00", periods=10, freq="15min", tz="UTC")
# Az ar 100-rol indul es baronkent +1-et lep -> a lebego eredmeny konnyen
# fejben ellenorizheto: 1 arpont = 10 pont a 10 pontos stopbol = 0,1 R = 10 $.
CHART = pd.DataFrame({"close": 100.0 + np.arange(10, dtype=float)}, index=IDX)


# ── 1. KOTES NELKUL: mindket gorbe a kezdo egyenleg ─────────────────────
real, eq, kezdo = szamla_gorbe(CHART, [], 1000.0)
check("kötés nélkül a realizált végig a kezdő egyenleg",
      np.all(real == 1000.0), str(real[:3]))
check("...és az equity is", np.all(eq == 1000.0))
check("a kezdő egyenleg visszajön", kezdo == 1000.0)


# ── 2. EGY LEZART KOTES: a realizalt a ZARASKOR lep ─────────────────────
# nyit a 2. baron (102), zar az 5. baron (105) -> +3 arpont = +0,3 R = +30 $
t = Kotes(IDX[2], IDX[5], "BUY", 102.0, pnl=30.0)
real, eq, _ = szamla_gorbe(CHART, [t], 1000.0)
check("a realizált a zárás ELŐTT nem mozdul",
      np.all(real[:5] == 1000.0), str(real[:6]))
check("a zárás bar-jától viszont igen", real[5] == 1030.0 and real[-1] == 1030.0,
      f"{real[5]} … {real[-1]}")

# ⚠ EZ A LENYEG: a zaras bar-jan a lebego MAR NEM szamit — kulonben ott
# ketszer szerepelne ugyanaz az eredmeny.
check("a záró báron az equity = realizált (nincs kettős számolás)",
      eq[5] == real[5], f"eq={eq[5]} real={real[5]}")
check("a nyitás ELŐTT az equity is a kezdő", np.all(eq[:2] == 1000.0))

# A nyitas es a zaras KOZOTT az equity a lebegot mutatja:
# a 3. baron az ar 103 -> +1 arpont = +0,1 R = +10 $
check("a tartás alatt az equity a LEBEGŐ eredményt mutatja",
      abs(eq[3] - 1010.0) < 1e-9, f"{eq[3]:.2f} (1010 kell)")
check("...és a realizált közben mozdulatlan", real[3] == 1000.0)


# ── 3. NYITVA MARADT KOTES: a realizalt vegig lapos ─────────────────────
t2 = Kotes(IDX[1], None, "BUY", 101.0, pnl=0.0)
real2, eq2, _ = szamla_gorbe(CHART, [t2], 1000.0)
check("a nyitva maradt kötés a realizáltat NEM mozdítja",
      np.all(real2 == 1000.0))
check("...de az equityben végig ott van (az utolsó báron +80 $)",
      abs(eq2[-1] - 1080.0) < 1e-9, f"{eq2[-1]:.2f}")


# ── 4. SELL: az irany megfordul ─────────────────────────────────────────
t3 = Kotes(IDX[1], None, "SELL", 101.0, pnl=0.0)
_, eq3, _ = szamla_gorbe(CHART, [t3], 1000.0)
check("emelkedő áron a SELL equitye CSÖKKEN",
      eq3[-1] < 1000.0 and abs(eq3[-1] - 920.0) < 1e-9, f"{eq3[-1]:.2f}")


# ── 5. TOBB KOTES OSSZEADODIK ───────────────────────────────────────────
real4, eq4, _ = szamla_gorbe(CHART, [t, t2], 1000.0)
check("két kötés realizáltja összeadódik", real4[-1] == 1030.0)
check("...és az equity is (realizált + a nyitott lebegője)",
      abs(eq4[-1] - 1110.0) < 1e-9, f"{eq4[-1]:.2f}")


# ── 6. HATARESETEK: ne szalljon el, es ne hazudjon ──────────────────────
# Hianyzo kockazat -> a lebego NEM szamolhato; a realizalt viszont igen.
t5 = Kotes(IDX[1], IDX[4], "BUY", 101.0, pnl=25.0, risk_usd=0.0)
real5, eq5, _ = szamla_gorbe(CHART, [t5], 1000.0)
check("hiányzó kockázatnál a realizált akkor is helyes", real5[-1] == 1025.0)
check("...és a lebegő NEM lesz kitalált szám (equity = realizált)",
      np.all(eq5 == real5))

# A charton KIVUL nyilo kotes nem eshet szet.
t6 = Kotes(IDX[-1] + pd.Timedelta(hours=5), None, "BUY", 120.0, pnl=0.0)
real6, eq6, _ = szamla_gorbe(CHART, [t6], 1000.0)
check("a chart UTÁN nyíló kötést kihagyja (nem száll el)",
      np.all(real6 == 1000.0) and np.all(eq6 == 1000.0))

# Ugyanabban a barban nyilo ES zarodo kotes: csak realizalt, lebego nincs.
t7 = Kotes(IDX[3], IDX[3], "BUY", 103.0, pnl=12.0)
real7, eq7, _ = szamla_gorbe(CHART, [t7], 1000.0)
check("egy báron belül nyíló+záródó kötés csak a realizáltba megy",
      real7[-1] == 1012.0 and np.all(eq7 == real7), f"{real7[-1]}")


# ── 6b. A ZARAS KET BAR KOZOTT — a valos adat esete ─────────────────────
# ⚠ EZT A HIBAT A VIZUALIS ELLENORZES HOZTA KI, nem ez a teszt. Az elso
# valtozat `searchsorted(..., "right") - 1`-et hasznalt, ami ELCSUSZOTT egy
# barral, ha a zaras ket bar-idopont KOZE esett. Ger40 M15-on egy 21:00-kor
# nyilt es 21:06-kor zart kotes igy a NYITO baron mar realizaltnak latszott,
# mikozben a „Nyitott" tabla ugyanabban a pillanatban NYITOTTKENT mutatta.
# A tabla szabalya (`close_time > kurzor`) az elsodleges — a gorbe ahhoz igazodik.
# ⚠ A belepo ar SZANDEKOSAN nem a bar zaroara (101,0 vs 102,0): kulonben a
# lebego pont nulla lenne, es a lenti allitas nem merne semmit. (Elsore epp
# 102,0-t irtam, es a teszt jogosan bukott.)
_koz = Kotes(IDX[2], IDX[2] + pd.Timedelta(minutes=6), "BUY", 101.0, pnl=20.0)
_r8, _e8, _ = szamla_gorbe(CHART, [_koz], 1000.0)
check("két bár KÖZÖTT záró kötés a NYITÓ báron még NYITOTT (lebeg)",
      _r8[2] == 1000.0, f"realizált[2]={_r8[2]} (1000 kell)")
check("...és a KÖVETKEZŐ bártól realizált",
      _r8[3] == 1020.0 and _r8[-1] == 1020.0, f"{_r8[3]} … {_r8[-1]}")
check("...a nyitó báron az equity a LEBEGŐT mutatja (nem a realizáltat)",
      abs(_e8[2] - 1010.0) < 1e-9, f"eq={_e8[2]} (1010 kell), real={_r8[2]}")

# A tabla es a gorbe UGYANAZT mondja: „nyitott-e a kurzornal?"
_kurzor_ido = IDX[2]
_tabla_szerint_nyitva = (_koz.close_time is None or _koz.close_time > _kurzor_ido)
_gorbe_szerint_nyitva = _r8[2] == 1000.0      # meg nem realizalodott
check("a TÁBLA és a GÖRBE egyetért abban, hogy nyitott-e",
      _tabla_szerint_nyitva == _gorbe_szerint_nyitva,
      f"tábla={_tabla_szerint_nyitva} görbe={_gorbe_szerint_nyitva}")


# ── 7. A GORBE HOSSZA = a chart hossza (az X-tengely kozos) ────────────
check("a görbék hossza a charttal egyezik",
      len(real) == len(CHART) and len(eq) == len(CHART))

# ── 8. A DRAWDOWN a kurzorig szamolhato az equitybol ───────────────────
# (a felulet ezt mutatja az idopillanat-nezetben)
_eq = np.array([1000.0, 1010.0, 990.0, 1005.0])
_dd = float(np.min(_eq - np.maximum.accumulate(_eq)))
check("a max drawdown a csúcshoz mérve NEGATÍV szám", abs(_dd + 20.0) < 1e-9,
      f"{_dd:.2f} (-20 kell)")


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
