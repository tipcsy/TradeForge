"""
A VOLATILITAS-KAPU szamai az INSTRUMENTUMEI (v3.103.0).

MIERT: a wpr_sma „Piac-szuro" kategoriaja (atr_min_pct / atr_max_pct /
atr_baseline_bars + atr_avg_ref) PONTOSAN a Volatilitas-kapu kuszobe volt, csak
a strategia parameter-ablakaban lakott, es az optimalizalo hangolta. Az
atr_avg_ref raadasul az instrumentum M15 ATR-atlaga — a strategiahoz semmi koze.
Most a `data/execution_params/<SYM>.json`-ban vannak.

Amit ez a teszt rogzit:

1. A TAROLO OSSZEFESUL. A spread-kapu mentese (csak a sajat 3 kulcsat adja at)
   NEM torolheti a volatilitas-kapu szamait — kulonben a par nemán szuretlenul
   kereskedne.
2. A BETOLTES visszaadja a vol-kulcsokat, a hianyzot NEM potolja (hiany = a kapu
   nem szur — a hangolatlan parok mai viselkedese).
3. A `calibrate` BITRE ugyanazt a szamot adja, amit v3.102.0-ig az optimalizalo
   a wpr_sma `bt_indicators`-an at szamolt.
4. A strategia-configokban NINCS tobbe vol-kulcs (se param_meta, se optimizer-
   tartomany) — kulonben az optimalizalo ujra hangolna, es a keszletbe mentene.
5. A kapu ablaka szerkeszti a szamokat; az „osszes instrumentumra" mentes NEM
   masolja a par sajat merceje (atr_avg_ref) — ar-egysegben van.
6. Az optimalizalo mentese kiveszi a vol-kulcsokat a keszletbol.

⚠ A valodi `data/execution_params`-t es a configot a teszt NEM irja: az
`EXECUTION_DIR` egy temp mappara mutat.
"""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.applog as _applog
_applog.harden_console()

import numpy as np                                  # noqa: E402
import pandas as pd                                 # noqa: E402

from core import execution_params as ep             # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


_tmp = pathlib.Path(tempfile.mkdtemp(prefix="volgate_"))
ep.EXECUTION_DIR = _tmp
_REAL = ROOT / "data" / "execution_params"
check("a teszt NEM a valodi mappaba ir", ep.execution_params_file("X").parent == _tmp)

# ---------------------------------------------------------------------------
print("== 1. Tarolo: osszefesul, nem felulir ==")
ep.save_execution_params("AAA", {"atr_min_pct": 0.8, "atr_max_pct": 2.2,
                                 "atr_avg_ref": 30.5})
ep.save_execution_params("AAA", {"atr_period": 19, "max_spread_atr_ratio": 0.25,
                                 "min_spread_mult": 1.5})
own = json.loads(ep.execution_params_file("AAA").read_text(encoding="utf-8"))["params"]
check("a spread mentese utan a vol-kuszob MEGMARADT",
      own.get("atr_min_pct") == 0.8 and own.get("atr_avg_ref") == 30.5, own)
check("es a spread is kikerult", own.get("atr_period") == 19, own)
ep.save_execution_params("AAA", {"atr_avg_ref": None})
own = json.loads(ep.execution_params_file("AAA").read_text(encoding="utf-8"))["params"]
check("None = torles", "atr_avg_ref" not in own and own.get("atr_min_pct") == 0.8, own)
ep.save_execution_params("AAA", {"valami_mas": 1, "breakeven_pct": 0.5})
own = json.loads(ep.execution_params_file("AAA").read_text(encoding="utf-8"))["params"]
check("ismeretlen / atkoltoztetett kulcs NEM kerul ki",
      "valami_mas" not in own and "breakeven_pct" not in own, own)
ep.execution_params_file("BAD").write_text("{ez nem json", encoding="utf-8")
try:
    ep.save_execution_params("BAD", {"atr_min_pct": 1.0})
    check("serult fajl fole NEM ir (a benne levo ertek elveszne)", False)
except RuntimeError:
    check("serult fajl fole NEM ir (a benne levo ertek elveszne)", True)

# ---------------------------------------------------------------------------
print("== 2. Betoltes ==")
got = ep.load_execution_params("AAA", {})
check("a vol-kulcsok a betoltott szotarban vannak",
      got.get("atr_min_pct") == 0.8 and got.get("atr_max_pct") == 2.2, got)
got = ep.load_execution_params("NINCS", {})
check("hianyzo vol-kulcs NINCS potolva (hiany = nem szur)",
      not any(k in got for k in ep.VOL_KEYS), got)
got = ep.load_execution_params("NINCS", {"execution": {"atr_min_pct": 0.5,
                                                       "atr_avg_ref": 99.0}})
check("globalis kuszob atjon, globalis MERCE nem (az a par sajatja)",
      got.get("atr_min_pct") == 0.5 and "atr_avg_ref" not in got, got)
check("without_vol_keys", ep.without_vol_keys(
    {"sma_period": 50, "atr_min_pct": 1, "atr_avg_ref": 2, "atr_period": 14})
    == {"sma_period": 50, "atr_period": 14})

# a motor precedenciaja: az instrumentum felulirja a keszlet elavult masolatat
from trading import live_trader as lt               # noqa: E402
_orig_lpp = lt.load_pair_params
lt.load_pair_params = lambda s, n: {"sma_period": 50, "atr_min_pct": 0.1}
try:
    merged = lt.strategy_params("AAA", "wpr_sma", {})
finally:
    lt.load_pair_params = _orig_lpp
check("strategy_params: az instrumentum kuszobe nyer az elavult masolat felett",
      merged.get("atr_min_pct") == 0.8, merged)

# ---------------------------------------------------------------------------
print("== 3. calibrate = a regi optimalizalo-szam ==")
from gates import vol_baseline as vb                 # noqa: E402
from strategy import get_strategy_by_name            # noqa: E402

rng = np.random.default_rng(7)
n = 3000
idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
c = 100 + np.cumsum(rng.normal(0, 0.3, n))
h = c + rng.uniform(0.05, 0.6, n)
lo = c - rng.uniform(0.05, 0.6, n)
m15 = pd.DataFrame({"open": c, "high": h, "low": lo, "close": c,
                    "tick_volume": 1, "spread": 1}, index=idx)
m1 = m15.iloc[:50].copy()
wpr = get_strategy_by_name("wpr_sma")
prm = {"sma_period": 50, "wpr_m15_period": 21, "wpr_m1_period": 21,
       "atr_period": 16, "point_size": 0.01}
regi = float(wpr.bt_indicators(m15, m1, prm)[0]["atr_avg"].iloc[0])
uj = vb.calibrate(m15, 16)
check("bitre azonos a regi (bt_indicators) keplettel", uj == regi, f"{uj} vs {regi}")
check("ures adat -> None", vb.calibrate(m15.iloc[:0], 14) is None)

# ---------------------------------------------------------------------------
print("== 4. Strategia-configok: nincs vol-kulcs ==")
for sn in ("wpr_sma", "pending_straddle", "candle_level_break"):
    cfg = json.loads((ROOT / "strategies" / "config" / f"{sn}.json")
                     .read_text(encoding="utf-8"))
    pm = ((cfg.get("param_meta") or {}).get("params") or {})
    opt = cfg.get("optimizer") or {}
    flat = {k for sec in cfg.values() if isinstance(sec, dict) for k in sec}
    bad = [k for k in ep.VOL_KEYS if k in pm or k in opt or k in flat]
    check(f"{sn}: nincs vol-kulcs", not bad, bad)
    check(f"{sn}: nincs ures 'market_filter' kategoria",
          "market_filter" not in ((cfg.get("param_meta") or {}).get("categories") or []))
wcfg = json.loads((ROOT / "strategies" / "config" / "wpr_sma.json").read_text(encoding="utf-8"))
check("wpr_sma: kimondja, hogy a Volatilitas-kapu FONTOS",
      "FONTOS" in (wcfg.get("_comment_volatility_gate") or ""))

# ---------------------------------------------------------------------------
print("== 5. A kapu ablaka ==")
from core import gate_params as gp                    # noqa: E402
from core import gates as g                           # noqa: E402

keys = [s.key for s in gp.specs_for(g.VOLATILITY)]
check("a Volatilitas-kapunak VAN szerkesztheto szama", set(keys) == set(ep.VOL_KEYS), keys)
check("a feliratok leforditva (nem a nyers kulcs)",
      all(not s.label.startswith("gp.") for s in gp.specs_for(g.VOLATILITY)))
check("also >= felso kuszob hiba",
      bool(gp.extra_errors(g.VOLATILITY, {"atr_min_pct": 2.0, "atr_max_pct": 1.5})))
check("0 = nincs hatar, nem hiba",
      not gp.extra_errors(g.VOLATILITY, {"atr_min_pct": 0.9, "atr_max_pct": 0.0}))

from dashboard import gate_dialog as gd              # noqa: E402
load, save = gd._STORE[g.VOLATILITY]
ep.save_execution_params("BBB", {"atr_min_pct": 0.3, "atr_avg_ref": 1.25})
save({}, "AAA", {"atr_min_pct": 0.7, "atr_max_pct": 2.0, "atr_baseline_bars": 0,
                 "atr_avg_ref": 31.0}, ["AAA", "BBB"])
a = load({}, "AAA")
b = load({}, "BBB")
check("a sajat parra minden kiment", a["atr_min_pct"] == 0.7 and a["atr_avg_ref"] == 31.0, a)
check("a masik parra a kuszob atment", b["atr_min_pct"] == 0.7, b)
check("a masik par SAJAT merceje NEM irodott felul", b["atr_avg_ref"] == 1.25, b)
check("0 -> a kulcs torolve (nincs hatar)",
      "atr_baseline_bars" not in ep._read_own("AAA"), ep._read_own("AAA"))

# ---------------------------------------------------------------------------
print("== 6. Az optimalizalo nem menti a keszletbe ==")
src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
check("a mentett params without_vol_keys-en megy at",
      '"params":        _ep_mod.without_vol_keys(result["params"])' in src)
check("az optimalizalo nem ir atr_avg_ref-et a keszletbe",
      'result["params"]["atr_avg_ref"]' not in src)

# a VALODI mappa erintetlen maradt (a teszt nem irhatott bele)
check("a valodi execution_params mappaban nincs tesztes fajl",
      not (_REAL / "AAA.json").exists() and not (_REAL / "BBB.json").exists())

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("Bukott:", ", ".join(_fail))
sys.exit(0 if all(_results) else 1)
