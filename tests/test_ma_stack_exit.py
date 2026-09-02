"""MOZGÓÁTLAG-SZALAG kiszállási indikátor (`core.exit_signal.ma_stack`).

⚠ MIÉRT KISZÁLLÁS, ÉS MIÉRT NEM BELÉPŐ. A 2026-09-02-i mérés szerint a négy SMA
(8/21/100/250) távolságából és lejtéséből BELÉPŐ nem lesz: a bruttó él
+0,02…+0,10 R, a költség −0,05…−0,23 R. A LEJTÉS-EGYETÉRTÉS viszont monoton
összefügg a jövőbeli hozammal (Ger40: 0 egyetértésnél −0,191, 3-nál +0,024 ATR).

Egy kiszállási szabály **ingyen van**: nem generál új kötést, tehát nem fizet új
spreadet. (A/B-vel mérve a hozadéka kicsi — +0,0027 R/kötés —, de a mechanizmus
bekötve marad, mert a kimenet-kezelés az egyetlen hely, ahol a projektben eddig
mérhető javulás született.)

Ez a teszt azt őrzi, hogy a modul azt csinálja, amit állít — és hogy a
backtest-kiértékelő ugyanazt mondja, mint az élő út. Két külön implementáció
(élő: gyertyánként; backtest: egyszer az egész M15-re) külön romlik el.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from core import exit_signal as ex

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def _keret(v):
    return pd.DataFrame({"close": v, "high": v + 1, "low": v - 1})


N = 600
FEL = _keret(np.linspace(100, 130, N))
LE = _keret(np.linspace(130, 100, N))

# ── 1. Az alapeset: a szalag a pozíció ELLEN lejt → zárunk ────────────────
check("emelkedő szalag, BUY → NEM zár", ex.ma_stack_exit(FEL, "BUY") is False)
check("emelkedő szalag, SELL → ZÁR", ex.ma_stack_exit(FEL, "SELL") is True)
check("eső szalag, BUY → ZÁR", ex.ma_stack_exit(LE, "BUY") is True)
check("eső szalag, SELL → NEM zár", ex.ma_stack_exit(LE, "SELL") is False)

# ── 2. Adathiánynál NEM zárunk ────────────────────────────────────────────
# ⚠ FAIL-OPEN, ahogy a többi kapu: hiányzó mérésből nem hozunk kereskedési
# döntést. Egy „biztos, ami biztos" zárás itt VESZTESÉGET realizálna azért,
# mert még nincs elég gyertya.
check("kevés gyertyánál nem zár", ex.ma_stack_exit(FEL.head(50), "BUY") is False)
check("üres kerettel nem dob", ex.ma_stack_exit(_keret(np.array([])), "BUY") is False)
check("ismeretlen iránynál nem zár", ex.ma_stack_exit(FEL, "OLDALRA") is False)

# ── 3. A KÜSZÖB tényleg számít ────────────────────────────────────────────
# Vegyes szalag: emelkedő, majd az elején megtörik → a gyorsak lefordulnak,
# a lassúak még emelkednek.
_v = np.concatenate([np.linspace(100, 130, N - 80), np.linspace(130, 122, 80)])
VEGYES = _keret(_v)
_szigoru = ex.ma_stack_exit(VEGYES, "BUY", min_agree=3)   # 3 alatt zár
_laza = ex.ma_stack_exit(VEGYES, "BUY", min_agree=1)      # csak 0-nál zár
check("a szigorúbb küszöb hamarabb zár", _szigoru is True and _laza is False,
      f"szigoru={_szigoru} laza={_laza}")

# ── 4. A diszpécser ───────────────────────────────────────────────────────
check("kikapcsolva sosem zár",
      ex.exit_triggered(LE, "BUY", {"enabled": False}) is False)
_cfg = {**ex.default_config(), "enabled": True,
        "indicator": ex.INDICATOR_MA_STACK}
check("a diszpécser eléri az indikátort",
      ex.exit_triggered(LE, "BUY", _cfg) is True)
check("...és az ellenkező irányra nem szól",
      ex.exit_triggered(LE, "SELL", _cfg) is False)
check("az `ma_stack` szerepel az INDICATORS listában",
      ex.INDICATOR_MA_STACK in ex.INDICATORS)
for _k in ("ma_periods", "ma_slope_bars", "ma_min_agree"):
    check(f"a default_config tartalmazza: {_k}", _k in ex.default_config())

# ── 5. AZ ÉLŐ ÉS A BACKTEST ÚT UGYANAZT MONDJA ────────────────────────────
# ⚠ EZ A LÉNYEG. Az élő út gyertyánként hívja a függvényt, a backtest EGYSZER
# számol az egész M15-re és egy `fn(i, direction)`-t ad. Két implementáció —
# a projekt ebből már megfizetett néhányat (viz ↔ backtest paritás,
# BacktestReplayer v4). Itt kimondjuk, hogy egyeznek.
from trading.backtest import _build_exit_evaluator

_rng = np.random.default_rng(11)
_ar = 100 + np.cumsum(_rng.normal(0, 0.4, 900))
M15 = pd.DataFrame({"open": _ar, "high": _ar + 0.5, "low": _ar - 0.5,
                    "close": _ar},
                   index=pd.date_range("2026-01-01", periods=900, freq="15min",
                                       tz="UTC"))
_ertekelo = _build_exit_evaluator(M15, {"exit": _cfg})
check("a backtest kiértékelő felépül", _ertekelo is not None)

if _ertekelo is not None:
    _elteres = []
    for i in range(400, 900, 7):
        for _d in ("BUY", "SELL"):
            _bt = bool(_ertekelo(i, _d))
            # Az élő út az utolsó ZÁRT gyertyáig lát: a `[:i+1]` szelet utolsó
            # sora a formálódó, amit a függvény maga hagy el.
            _elo = bool(ex.ma_stack_exit(M15.iloc[:i + 2], _d,
                                         tuple(_cfg["ma_periods"]),
                                         int(_cfg["ma_slope_bars"]),
                                         int(_cfg["ma_min_agree"])))
            if _bt != _elo:
                _elteres.append((i, _d, _bt, _elo))
    check("az ÉLŐ és a BACKTEST út bitre egyezik", not _elteres,
          f"{len(_elteres)} eltérés, első: {_elteres[:2]}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
