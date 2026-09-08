"""A MÉRETEZÉS bemeneteinek őrei — és két lelet, ami MÉRVE nem lelet.

⚠ A LELET (2026-09-08, független code review). A `point_size` több tucat
osztásban szerepel (lot, SL-táv, P&L, R-szintek, spread-pont), és a védelme
hiányos volt:

    sl_points = atr_value / params.get("point_size", 0.0001) * ...

Az alapérték CSAK hiányzó kulcsnál lép be. Ha a kulcs JELEN VAN `0`-val — üres
mező a configban, félig feltöltött új instrumentum —, a `.get` a 0-t adja, és
`ZeroDivisionError` jön, olyan üzenettel, amiből sem a pár, sem a javítás nem
derül ki. (A 2026-08-08-i eset ugyanennek a másik fele volt: ott a KeyError ölte
meg a teljes LiveTrader szálat.)

A `0` nem alapértelmezhető: a `point_size` a pár TÉNYADATA. Rossz értékkel a lot,
az SL, a P&L és az R MIND hibás — csendben, mert egyik szám sem nézne ki
lehetetlennek. Ezért a válasz: BESZÉDES kivétel, ami megnevezi a párat és a
javító parancsot.

⚠ EGY SEAM, NEM HÚSZ ŐR. A backtestben ~20 osztás megy a `point_size`-zal;
mindegyikhez külön őrt tenni zaj lenne, és egy kimaradó őr csendben rossz számot
adna. A motor BEMENETÉN (`_prepare_params`) ellenőrzünk egyszer.

⚠ ÉS AMI MÉRVE NEM HIBA. A review két további pontot jelzett; mindkettőt
MEGMÉRTEM, és egyik sem áll:

  * `fits_budget` `_EPS = 1e-9` „túl nagy tűrés" — a valódi halmozódási hiba
    legrosszabb esetben 6,7e-16 (100 súly összege), az `_EPS` ennek 1,5 MILLIÓ-
    szorosa, és amit átenged, az 2,45 NANO-euró egy 981 eurós számlán. Egy
    1e-8-as súly már elutasításra kerül. A tűrés helyesen van méretezve.
  * a lot-kerekítés „lebegőpontos pontatlansága" — a `floor(round(v/step, 9))`
    alak PONT ez ellen véd: 1596 pontos többszörösön 0 hiba, míg a naiv
    `floor(v/step)` alak több százon elvéreznék (0,05-ös lépésnél tömegesen).
    Ez a teszt ezt is rögzíti, nehogy egy jövőbeli „egyszerűsítés" visszavigye.
"""
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog

applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. A közös point_size-őr ══════════════════════════════════════════════
from core.risk_manager import require_point_size, calc_sl_tp_points, fits_budget, _EPS

for rossz, cimke in (({}, "hiányzik"), ({"point_size": 0}, "0"),
                     ({"point_size": 0.0}, "0.0"), ({"point_size": None}, "None"),
                     ({"point_size": ""}, "üres string"),
                     ({"point_size": "x"}, "nem szám"),
                     ({"point_size": -0.01}, "negatív")):
    try:
        require_point_size(rossz, "teszt")
        check(f"point_size {cimke} → hiba", False, "ÁTMENT")
    except ValueError as ex:
        check(f"point_size {cimke} → beszédes ValueError", True)
        if cimke == "0":
            check("...és MEGMONDJA a javító parancsot",
                  "refresh_point_values.py" in str(ex), str(ex)[:60])
            check("...és megnevezi a helyet (ctx)", "teszt" in str(ex))
    except ZeroDivisionError:
        check(f"point_size {cimke} → NEM nyers ZeroDivisionError", False)

check("érvényes érték átmegy", require_point_size({"point_size": 0.01}) == 0.01)

# A hívó: ZeroDivisionError HELYETT beszédes hiba
try:
    calc_sl_tp_points(1.0, {"point_size": 0, "sl_atr_mult": 2.0, "tp_rr_ratio": 2.0})
    check("⚠ calc_sl_tp_points point_size=0-val megáll", False, "ÁTMENT")
except ZeroDivisionError:
    check("⚠ calc_sl_tp_points: NEM nyers ZeroDivisionError", False)
except ValueError:
    check("⚠ calc_sl_tp_points point_size=0-val BESZÉDESEN áll meg", True)

check("...és érvényes bemeneten VÁLTOZATLAN",
      calc_sl_tp_points(1.0, {"point_size": 0.01, "sl_atr_mult": 2.0,
                              "tp_rr_ratio": 2.0}) == (200.0, 400.0))


# ══ 2. A MOTOR bemenete: egy seam, a pár nevével ══════════════════════════
from trading.backtest import _prepare_params, _rr_spec

try:
    _prepare_params("TESZTPAR", {}, {"point_size": 0, "pv1_point": 1.0})
    check("⚠ a backteszt bemenete elutasítja a 0 point_size-t", False, "ÁTMENT")
except ValueError as ex:
    check("⚠ a backteszt bemenete elutasítja a 0 point_size-t", True)
    check("...és MEGNEVEZI a párat (különben melyik a 16-ból?)",
          "TESZTPAR" in str(ex), str(ex)[:70])

_ok = _prepare_params("X", {"a": 1}, {"point_size": 0.01})
check("...érvényes párnál változatlanul dolgozik",
      _ok["point_size"] == 0.01 and _ok["symbol"] == "X" and _ok["a"] == 1)


# ══ 3. Az rr-spec típusa ott bukjon, ahol keletkezik ══════════════════════
for rossz in ([{"preset": "off"}], "off", 3.14):
    try:
        _rr_spec(rossz, False, "X")
        check(f"rr={type(rossz).__name__} → hiba", False, "ÁTMENT")
    except TypeError as ex:
        check(f"⚠ rr={type(rossz).__name__} → TypeError a HATÁRON", True)
        if isinstance(rossz, list):
            check("...és megmondja, mit várt", "szótár" in str(ex), str(ex)[:60])
    except AttributeError:
        # Pontosan ezt kerüljük: a hiba a motor mélyén, a hívó megnevezése nélkül.
        check(f"⚠ rr={type(rossz).__name__} → NEM kései AttributeError", False)

check("a None továbbra is érvényes ('használd a pár éles specjét')",
      isinstance(_rr_spec(None, False, "NINCSILYEN"), dict))
check("a szótár változatlanul átmegy",
      _rr_spec({"preset": "off", "x": 1}, False, "X")["x"] == 1)


# ══ 4. A tick-letöltő mértékegysége ══════════════════════════════════════
# A tickek int64 PONTBAN tárolódnak — 0-s `point` több óra letöltés közepén
# szállna el. (Az MT5-import miatt csak a forrást nézzük, ha a modul nem jön be.)
try:
    from tools.download_ticks import to_frame
    _van_modul = True
except Exception:
    _van_modul = False

if _van_modul:
    try:
        to_frame(None, 0.0)
        check("⚠ a tick→pont váltás elutasítja a 0 pontot", False, "ÁTMENT")
    except ValueError:
        check("⚠ a tick→pont váltás elutasítja a 0 pontot (ELŐRE, nem menet közben)",
              True)
    except Exception as ex:
        check("⚠ a tick→pont váltás elutasítja a 0 pontot", False, type(ex).__name__)
else:
    _src = (ROOT / "tools" / "download_ticks.py").read_text(encoding="utf-8")
    check("⚠ a tick→pont váltás elutasítja a 0 pontot (forrás)",
          "if not point or point <= 0:" in _src)


# ══ 5. MÉRT CÁFOLAT: az _EPS helyesen van méretezve ══════════════════════
# A valódi halmozódási hiba: N egyenlő súly összege vs. a pontos 1.0.
_worst = 0.0
for n in (2, 3, 4, 5, 8, 10, 16, 32, 100):
    w, s = 1.0 / n, 0.0
    for _ in range(n):
        s += w
    _worst = max(_worst, abs(s - 1.0))
check("⚠ az _EPS NAGYSÁGRENDEKKEL a valódi halmozódási hiba fölött van",
      _EPS > _worst * 1000, f"_EPS={_EPS:g} vs legrosszabb hiba={_worst:.2e}")
check("⚠ ...de egy ÉRDEMI túllépést már elutasít (1e-8 súly telt kereten)",
      not fits_budget(4.0, 1e-8, 4.0))
check("...a nulla-közeli maradék viszont átfér (ez a CÉLJA)",
      fits_budget(4.0, 1e-9, 4.0))
check("a négy 0,25-ös súly EGYÜTT belefér (ez volt az eredeti indok)",
      fits_budget(0.75, 0.25, 1.0))


# ══ 6. MÉRT CÁFOLAT: a lot-kerekítés PONT a pontatlanság ellen véd ═══════
def _kerekit(volume, step):
    """Az `mt5_connector.close_partial` alakja."""
    return round(math.floor(round(volume / step, 9)) * step, 8)


def _naiv(volume, step):
    return round(math.floor(volume / step) * step, 8)


_hibak = _naiv_hibak = _esetek = 0
for step in (0.01, 0.1, 0.001, 0.05):
    for k in range(1, 400):
        v = round(k * step, 10)
        _esetek += 1
        if abs(_kerekit(v, step) - v) > 1e-9:
            _hibak += 1
        if abs(_naiv(v, step) - v) > 1e-9:
            _naiv_hibak += 1

check("⚠ a JELENLEGI lot-kerekítés pontos többszörösön hibátlan",
      _hibak == 0, f"{_hibak}/{_esetek}")
check("⚠ ...a NAIV alak viszont elvérezne (ezért van ott a round(...,9))",
      _naiv_hibak > 100, f"{_naiv_hibak}/{_esetek} hiba a naiv alaknál")

random.seed(7)
_fel = sum(1 for _ in range(20000)
           if _kerekit((v := random.uniform(0.001, 50.0)),
                       (st := random.choice((0.01, 0.1, 0.001)))) > v + 1e-12)
check("a kerekítés SOSEM megy felfelé (20 000 véletlen érték)", _fel == 0, str(_fel))

# És a forrás tényleg ezt az alakot használja (nehogy egy „egyszerűsítés" elvigye).
_mc = (ROOT / "core" / "mt5_connector.py").read_text(encoding="utf-8")
check("⚠ a védett alak a forrásban is ez",
      "math.floor(round(volume / step, 9)) * step" in _mc)

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)
