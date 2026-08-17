"""A riasztas a JELET azonositsa, ne a kezbesito gyertyat.

⚠ A LELET (2026-08-17, elesben). A GOLD-on a bollinger PERCENKENT riasztott,
ugyanarra a szetupra:

    18:00  GOLD BUY JELZES (bollinger_squeeze_breakout) belepo 4427.8
    18:01  GOLD BUY JELZES (bollinger_squeeze_breakout) belepo 4426.9
    18:02  GOLD BUY JELZES (bollinger_squeeze_breakout) belepo 4426
    18:03  GOLD BUY JELZES (bollinger_squeeze_breakout) belepo 4425.3
    18:04  GOLD BUY JELZES (bollinger_squeeze_breakout) belepo 4425.3

Ok: az MQL5 alert-ID alapjan dedupal, az ID viszont MINDIG a VEGREHAJTASI (M1)
gyertya idejebol keszult. Ez a `wpr_sma`-ra HELYES — ott az M1 allapotgep hozza
a dontest, tehat minden M1 gyertya UJ jel lehet. A `bollinger` viszont H1-en
dont (`signal_tf_min=60`), az M1 „pusztan kezbesiti": egyetlen jelbol igy 60
riasztas lett.

A megoldas seam-mel: a strategia megmondja, milyen hosszu a DONTESI gyertyaja
(`signal_bar_seconds`), a hivo pedig arra kerekit. A `wpr_sma` 0-t ad -> a
viselkedese bitre valtozatlan.
"""
import datetime as dt
import inspect
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


from strategy import get_strategy_by_name
from strategy.settings import load_strategy_config


def _sec(name):
    st = get_strategy_by_name(name)
    return st.signal_bar_seconds(st.base_params(load_strategy_config(name)))


# ── 1. A SEAM ─────────────────────────────────────────────────────────────
# ⚠ A `wpr_sma` DONTESE az M1-en szuletik — ott minden gyertya uj jel lehet,
# tehat NEM szabad kerekiteni. A 0 pontosan ezt jelenti.
check("a wpr_sma a vegrehajtasi gyertyan dont (0 = nincs kerekites)",
      _sec("wpr_sma") == 0, str(_sec("wpr_sma")))
check("a bollinger H1-en dont", _sec("bollinger_squeeze_breakout") == 3600,
      str(_sec("bollinger_squeeze_breakout")))
check("az ml_ai a sajat jel-idosikjan", _sec("ml_ai") == 900, str(_sec("ml_ai")))

# A parameter FELULIRHATJA (per instrumentum hangolhato jel-idosik).
_bb = get_strategy_by_name("bollinger_squeeze_breakout")
check("a params felulirja a modul-alapot",
      _bb.signal_bar_seconds({"signal_tf_min": 15}) == 900,
      str(_bb.signal_bar_seconds({"signal_tf_min": 15})))
# Hibas/hianyzo ertek ne dontson el egy riasztast: essen vissza a modulra.
check("hianyzo ertek -> a modul alapja", _bb.signal_bar_seconds({}) == 3600)

# Az alapertelmezes MINDEN strategiara 0 (a base-ben) — egy uj strategia tehat
# a REGI viselkedest kapja, nem egy meglepetest.
from strategy.base import Strategy
check("a base alapertelmezese 0 (visszafele kompatibilis)",
      inspect.getsource(Strategy.signal_bar_seconds).rstrip().endswith("return 0"))


# ── 2. A HATAS: 60 M1 gyertya -> HANY azonosito ──────────────────────────
def _ids(sec, n=60):
    base = int(dt.datetime(2026, 8, 17, 18, 0, tzinfo=dt.timezone.utc).timestamp())
    return {((base + i * 60) // sec) * sec if sec else (base + i * 60)
            for i in range(n)}


check("bollinger: 60 perc M1 -> EGYETLEN riasztas",
      len(_ids(3600)) == 1, f"{len(_ids(3600))} azonosito")
check("...kerekites nelkul 60 lett volna", len(_ids(0)) == 60)
check("ml_ai: 60 perc -> 4 (negyedorankent)", len(_ids(900)) == 4,
      f"{len(_ids(900))}")
# ⚠ ES A KOVETKEZO jel-gyertya UJ azonositot kap — nem nyeljuk el a valodi uj
# jelet.
_a = _ids(3600, 60)
_b = {((int(dt.datetime(2026, 8, 17, 19, 0, tzinfo=dt.timezone.utc).timestamp())) // 3600) * 3600}
check("a KOVETKEZO jel-gyertya viszont UJ azonosito", not (_a & _b), f"{_a} vs {_b}")


# ── 3. A BEKOTES az elo uton ─────────────────────────────────────────────
_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
_i = _src.find("_aid = f\"{symbol}|{strategy.name}|{signal}|{_bt}\"")
check("az alert-id kepzese megvan", _i > 0)
_blk = _src[max(0, _i - 1200):_i]
check("...a JEL-gyertyara kerekit", "signal_bar_seconds" in _blk)
check("...es csak ha van jel-idosik (0 -> valtozatlan)",
      "if _sig_sec > 0:" in _blk)
# ⚠ Egy hibas strategia-hook ne dontson el egy riasztast.
check("...a hook hibaja nem viszi el a riasztast",
      "except Exception" in _blk and "_sig_sec = 0" in _blk)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
