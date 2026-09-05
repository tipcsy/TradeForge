"""A KUTATO LABOR — az elso tesztek a `kutatas` csoportban.

⚠ MIERT KELL (0012). A teszt-csoportositas ota ez LATSZIK:

    python tests/run_all.py --csoportok
       kutatas           0   <- nincs ra teszt

A `tools/research/` 30 modulja adja a strategia-leleteket (holdout-kereses,
indikator-szures, kimenet-kezeles, VR-rezsim…), es a dontesek jelentos resze
ezekre epul. Egyetlen teszt sem fedte oket.

⚠ NEM ELMELETI KOCKAZAT — ket hiba mar megtortent:

  1. A `lab.simulate` NEM MODELLEZI A SWAPOT. A `trend_pullback`
     kiertekelesenel derult ki: minden long-only lelet FELFELE torzult. (A
     motorban a swap -0,079 R, ami epp felemeszti a long sodrodas-elet.)
  2. A `_map_to` MASZK-vetito (`dtype=bool`). Egy float sorozat (ATR) ott
     1,0-ra kerekedett, es a stop 25 helyett 1,5 ar-egyseg lett. Azt a
     NULL-TESZT fogta meg, nem unit-teszt.

Ez a fajl a jegyzet harom pontjat fedi: (1) simulate — spread/swap/
one_at_a_time/R, (2) vetitok — look-ahead es tipus, (3) null-teszt or.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

from tools.research import lab                        # noqa: E402
from strategies.trend_pullback import _map_to         # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


PS = 0.01          # point_size


def _df(zar, spread_pts=0.0, kezdet="2026-01-05 08:00"):
    """M1 keret adott zaroarakkal. A high/low tagabb, hogy a SL/TP elerheto legyen."""
    idx = pd.date_range(kezdet, periods=len(zar), freq="1min", tz="UTC")
    c = np.asarray(zar, float)
    d = pd.DataFrame({"high": c + 5 * PS, "low": c - 5 * PS, "close": c}, index=idx)
    if spread_pts:
        d["avg_spread"] = spread_pts * PS
        d["close_spread"] = spread_pts * PS
    return d


# ── 1. R-SZAMITAS: a TP-be futo kotes pontosan a cel-R-t adja ───────────
# Sima emelkedo ar; SL 10 pont, TP 20 pont -> a TP-t eri el -> r = +2.
ar = 100.0 + np.arange(60) * (1.0 * PS)
tr = lab.simulate(_df(ar), np.array([0]), np.array([1]),
                  np.array([10.0]), np.array([20.0]), PS, max_hold=50)
check("a TP-be futo BUY pontosan +2 R (SL 10 / TP 20 pont)",
      len(tr) == 1 and abs(tr["r"][0] - 2.0) < 1e-9,
      f"n={len(tr)} r={tr['r'][0] if len(tr) else '—'}")
check("...es a statusz TP (1)", len(tr) and tr["status"][0] == 1)

# Eso ar -> a BUY a stopba fut -> r = -1.
tr = lab.simulate(_df(100.0 - np.arange(60) * (1.0 * PS)), np.array([0]),
                  np.array([1]), np.array([10.0]), np.array([20.0]), PS, max_hold=50)
check("a stopba futo BUY pontosan -1 R",
      len(tr) == 1 and abs(tr["r"][0] + 1.0) < 1e-9, str(tr["r"][:1]))
check("...es a statusz SL (0)", len(tr) and tr["status"][0] == 0)


# ── 2. SPREAD: a BUY a BELEPESKOR fizet, a SELL a KILEPESKOR ────────────
# ⚠ Ez a modell lelke: az ar-sorozat KOZEP/BID, a BUY ASK-on nyit.
_nospread = lab.simulate(_df(ar), np.array([0]), np.array([1]),
                         np.array([10.0]), np.array([20.0]), PS, max_hold=50)
_spread = lab.simulate(_df(ar, spread_pts=4.0), np.array([0]), np.array([1]),
                       np.array([10.0]), np.array([20.0]), PS, max_hold=50)
check("a BUY belepoje spreaddel ROSSZABB (magasabb)",
      _spread["entry"][0] > _nospread["entry"][0],
      f"{_nospread['entry'][0]:.4f} -> {_spread['entry'][0]:.4f}")
check("...pontosan a spreaddel",
      abs((_spread["entry"][0] - _nospread["entry"][0]) - 4.0 * PS) < 1e-9)

# SELL: az ar-sorozat a BID, a kilepes ASK-on tortenik -> a spread OTT jelenik meg.
#
# ⚠ EZT ELSORE ROSSZUL MERTEM: egy stopba futo SELL-t neztem, ahol a kilepesi
# ar DEFINICIO SZERINT az `sl`, tehat az R pontosan -1 spreaddel is, spread
# nelkul is. A spread-koltseg a SELL-en az IDO-ALAPU kilepesen latszik
# (`xprice = c[j] + sp[j]`), ezert lapos aron, TP nelkul, rovid tartassal
# merunk.
_lapos = np.full(60, 100.0)
_s0 = lab.simulate(_df(_lapos), np.array([0]), np.array([-1]),
                   np.array([50.0]), np.array([0.0]), PS, max_hold=10)
_s1 = lab.simulate(_df(_lapos, spread_pts=4.0), np.array([0]), np.array([-1]),
                   np.array([50.0]), np.array([0.0]), PS, max_hold=10)
check("a SELL idoben zar (nem stop/TP)", _s0["status"][0] == 2 and _s1["status"][0] == 2)
check("a SELL belepoje NEM valtozik a spreadtol (bid-en nyit)",
      abs(_s1["entry"][0] - _s0["entry"][0]) < 1e-9)
check("...de a KILEPESE ask-on van, tehat rosszabb",
      _s1["exit"][0] > _s0["exit"][0],
      f"{_s0['exit'][0]:.4f} -> {_s1['exit'][0]:.4f}")
check("...es az eredmenye pontosan a spreaddel romlik",
      abs((_s0["r"][0] - _s1["r"][0]) - 4.0 / 50.0) < 1e-9,
      f"{_s0['r'][0]:+.4f} -> {_s1['r'][0]:+.4f}")


# ── 3. ⚠ A SWAP NINCS MODELLEZVE — kimondva, hogy ne higgyuk maskepp ────
# Ket AZONOS kotes, csak az egyik NAPOKIG all nyitva. Ha lenne swap, a hosszan
# tartott dragabb lenne. A `lab.simulate` szerint UGYANANNYI.
_lassu = 100.0 + np.arange(3000) * (0.002 * PS)     # ~2 nap, alig mozdul
_a = lab.simulate(_df(_lassu), np.array([0]), np.array([1]),
                  np.array([50.0]), np.array([0.0]), PS, max_hold=100)
_b = lab.simulate(_df(_lassu), np.array([0]), np.array([1]),
                  np.array([50.0]), np.array([0.0]), PS, max_hold=2500)
check("a 25x hosszabban tartott kotes NEM fizet tobbet (nincs swap a laborban)",
      len(_a) and len(_b) and _b["i_close"][0] - _b["i_open"][0]
      > 20 * (_a["i_close"][0] - _a["i_open"][0]),
      "⚠ ISMERT HIANY: a long-only leletek ezert FELFELE torzulnak")
check("...a tartas tenyleg hosszabb volt (a teszt mer valamit)",
      _b["i_close"][0] > _a["i_close"][0],
      f"{_a['i_close'][0]} vs {_b['i_close'][0]}")
# Forras-szintu or: ha valaki BEVEZETI a swapot, ez a teszt szoljon, hogy a
# fenti allitasokat (es a raepulo leleteket) at kell nezni.
_src = (ROOT / "tools" / "research" / "lab.py").read_text(encoding="utf-8")
check("a labor forrasa tovabbra sem emlit swapot (ha igen: nezd at a leleteket)",
      "swap" not in _src.lower())


# ── 4. one_at_a_time: atfedo belepok ───────────────────────────────────
_idx = np.array([0, 1, 2, 3])
_kw = dict(sl_pts=np.full(4, 50.0), tp_pts=np.zeros(4), point_size=PS, max_hold=40)
_egy = lab.simulate(_df(_lassu[:200]), _idx, np.ones(4, int), one_at_a_time=True, **_kw)
_tobb = lab.simulate(_df(_lassu[:200]), _idx, np.ones(4, int), one_at_a_time=False, **_kw)
check("one_at_a_time=True elnyeli az atfedo belepoket", len(_egy) == 1, str(len(_egy)))
check("one_at_a_time=False mindet megnyitja", len(_tobb) == 4, str(len(_tobb)))
check("...es a 4 kulon kotes ugyanarrol a barrol indul",
      len(_tobb) == 4 and len(set(_tobb["i_open"])) == 4)


# ── 5. VETITOK: LOOK-AHEAD ─────────────────────────────────────────────
# ⚠ EZ A LEGDRAGABB HIBAFAJTA: nem omlik ossze, csak felfujja az eredmenyt.
_m1 = pd.date_range("2026-01-05 08:00", periods=120, freq="1min", tz="UTC")
_m5 = pd.date_range("2026-01-05 08:00", periods=24, freq="5min", tz="UTC")
_maszk = np.zeros(24, dtype=bool)
_maszk[12] = True                       # a 12. M5 gyertya (08:60 = 09:00 nyitas)
_v = _map_to(_m1, _m5, 5, _maszk)
_elso = int(np.argmax(_v)) if _v.any() else -1
check("a TF-jel csak a gyertya ZARASA UTAN valik ervenyesse",
      _elso >= 0 and _m1[_elso] >= _m5[12] + pd.Timedelta(minutes=5),
      f"jel {_m1[_elso]} vs zaras {_m5[12] + pd.Timedelta(minutes=5)}")

# A dontő or: a JOVOT megvaltoztatva a MULT nem valtozhat.
_maszk2 = _maszk.copy()
_maszk2[20] = True                       # kesobbi gyertya
_v2 = _map_to(_m1, _m5, 5, _maszk2)
_hatar = int(np.searchsorted(_m1, _m5[20]))
check("egy KESOBBI TF-gyertya megvaltoztatasa a korabbi sorokat nem erinti",
      np.array_equal(_v[:_hatar], _v2[:_hatar]))

check("a vetites elotti sorok False-ok (nincs meg lezart gyertya)",
      not _v[:1].any())

# ── 6. VETITOK: A TIPUS-CSAPDA — kimondva ──────────────────────────────
# ⚠ EZ OKOZTA a 25 -> 1,5 ar-egyseges stopot. A `_map_to` MASZK-vetito:
# `dtype=bool`, tehat egy float sorozat NAGYSAGA elvesz. A fuggveny igy helyes
# (a docstringje ezt mondja) — a hiba a HASZNALAT volt. A teszt azert allitja,
# hogy a csapda LATHATO legyen, es senki ne tanulja meg megegyszer draga aron.
_atr_ertekek = np.full(24, 25.0)         # „ATR = 25 ar-egyseg"
_ki = _map_to(_m1, _m5, 5, _atr_ertekek)
check("a `_map_to` MASZK-vetito: bool tombot ad", _ki.dtype == bool, str(_ki.dtype))
check("⚠ egy float sorozat NAGYSAGA elvesz (25.0 -> True)",
      _ki.any() and float(_ki[_ki][0]) == 1.0,
      "ezert lett a stop 25 helyett 1,5 — float-ra KULON vetito kell")


# ── 7. NULL-TESZT OR: veletlen belepok ne termeljenek elt ──────────────
# ⚠ EZ fogta meg a `_map_to`-hibat is. Ha a szimulator veletlen belepokre
# POZITIV varhato erteket ad, akkor a hiba a SZIMULATORBAN van, nem a jelben.
rng = np.random.default_rng(7)
_zaj = 100.0 + np.cumsum(rng.normal(0, 2.0 * PS, 6000))
_d = _df(_zaj, spread_pts=0.0)
_be = np.arange(0, 5800, 25)
_r_ek = []
for _mag in range(6):
    _rg = np.random.default_rng(100 + _mag)
    _oldal = _rg.choice([-1, 1], size=len(_be))
    _t = lab.simulate(_d, _be, _oldal, np.full(len(_be), 30.0),
                      np.full(len(_be), 30.0), PS, max_hold=200,
                      one_at_a_time=False)
    if len(_t):
        _r_ek.append(float(np.mean(_t["r"])))
_atl = float(np.mean(_r_ek))
check("veletlen iranyu belepok atlagos R-je ~0 (spread nelkul)",
      abs(_atl) < 0.10, f"atlag {_atl:+.4f} hat magbol")
check("...es egyetlen mag sem ad extrem elt",
      all(abs(x) < 0.25 for x in _r_ek),
      " ".join(f"{x:+.3f}" for x in _r_ek))

# Spreaddel viszont a veletlen belepo NEM lehet nyereseges — ez a koltseg.
_d_sp = _df(_zaj, spread_pts=6.0)
_rg = np.random.default_rng(100)
_t_sp = lab.simulate(_d_sp, _be, _rg.choice([-1, 1], size=len(_be)),
                     np.full(len(_be), 30.0), np.full(len(_be), 30.0), PS,
                     max_hold=200, one_at_a_time=False)
check("spreaddel a veletlen belepo varhato erteke ROMLIK",
      float(np.mean(_t_sp["r"])) < _r_ek[0],
      f"{_r_ek[0]:+.4f} -> {float(np.mean(_t_sp['r'])):+.4f}")



# ── 8. A FLOAT-VETITO — a `_map_to` csapdajara adott valasz ─────────────
# A `trend_pullback_check._vetit_float` ugyanaz a vetites, csak MEGTARTJA a
# nagysagot. Ha ez lett volna hasznalva, a 25 -> 1,5 stop-hiba elo sem all.
from tools.research.trend_pullback_check import _vetit_float   # noqa: E402

_f = _vetit_float(_m1, _m5, 5, _atr_ertekek)
check("a float-vetito MEGTARTJA a nagysagot (25.0 marad 25.0)",
      _f.dtype != bool and float(np.nanmax(_f)) == 25.0,
      f"dtype={_f.dtype} max={np.nanmax(_f)}")

# ⚠ …de a look-ahead tilalom RA IS all: kulonben a helyes ertek rossz idoben jonne.
_val = np.arange(24, dtype=float)
_f1 = _vetit_float(_m1, _m5, 5, _val)
_val2 = _val.copy()
_val2[20] = 999.0
_f2 = _vetit_float(_m1, _m5, 5, _val2)
_h = int(np.searchsorted(_m1, _m5[20]))
check("a float-vetito sem hasznal jovobeli TF-gyertyat",
      np.array_equal(np.nan_to_num(_f1[:_h], nan=-1.0),
                     np.nan_to_num(_f2[:_h], nan=-1.0)))


# ── 9. IMPORT-OR a TELJES `tools/research/` csomagra ────────────────────
# ⚠ 30 modul, amit eddig SEMMI nem fedett. Ez a legolcsobb valodi fedes: egy
# elgepelt nev, egy atnevezett API vagy egy korkoros import AZONNAL kiderul —
# ma ezek csak akkor derultek ki, amikor valaki epp futtatni akarta a kutatast.
import importlib          # noqa: E402
import contextlib         # noqa: E402
import io as _io          # noqa: E402
import time as _time      # noqa: E402

_modulok = sorted(p.stem for p in (ROOT / "tools" / "research").glob("*.py")
                  if p.stem != "__init__")
check("a kutato-csomag megvan (30 korul)", len(_modulok) >= 25, f"{len(_modulok)} modul")

_rossz, _lassu_m = [], []
for _m in _modulok:
    _t0 = _time.time()
    try:
        with contextlib.redirect_stdout(_io.StringIO()),              contextlib.redirect_stderr(_io.StringIO()):
            importlib.import_module(f"tools.research.{_m}")
    except BaseException as _e:               # noqa: BLE001 — a HIBA a lelet
        _rossz.append(f"{_m}: {type(_e).__name__}")
    else:
        if _time.time() - _t0 > 5.0:
            _lassu_m.append(_m)
check("MINDEN kutato-modul importalhato", not _rossz, "; ".join(_rossz))

# ⚠ ES EGYIK SEM VEGEZHET MUNKAT IMPORTKOR. A `trend_pullback_check` igy allt:
# a puszta import 18,8 mp-et futott (MT5-adattal), ezert a modul se
# ujrahasznalhato, se tesztelheto nem volt. Most `main()` + `__main__` vedi.
check("egyik modul sem vegez erdemi munkat importkor",
      not _lassu_m, f"lassu: {_lassu_m}")
for _m in ("trend_pullback_check", "search", "holdout"):
    _p = ROOT / "tools" / "research" / f"{_m}.py"
    if _p.exists():
        check(f"{_m}: van `__main__` ved (a szkript-torzs nem fut importkor)",
              '__name__ == "__main__"' in _p.read_text(encoding="utf-8"))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
