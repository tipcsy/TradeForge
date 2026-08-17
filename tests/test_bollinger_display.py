"""A bollinger HARMOM kore es a chart-szalagja.

⚠ A LELET (a felhasznalotol): „a Bollinger sosem mutat semmilyen pottyot, sem az
osszeszukulesre, sem a tagulasra. Nem lathato, hogy mikor fog jelzest kuldeni."

Harom kulon hiba volt egyszerre:

1. A kijelzes FRISS `SqueezeState`-et leptetett EGY gyertyaval. A `release` es az
   `entry` viszont FELHALMOZOTT allapotbol el (`bars_since_off`, ill. a jel) —
   egyetlen lepes utan szinte sosem gyulladhattak ki.

2. Az `entry` kort a `last_signal` adta, ami RAGADOS (sosem torlodik). Merve
   (GOLD, 1500 H1-gyertya): a gyertyak 92,5%-an vilagitott volna. Egy allando
   kor nem jelzes, hanem disz.

3. A `release` kor `d != 0`-t kovetelt, a `_trend_dir` viszont KIKAPCSOLT
   trend-szurovel DEFINICIO SZERINT 0-t ad (`require_trend_alignment=False` —
   pl. GOLD-on). A kor tehat nem azert maradt sotet, mert nem tortenik semmi.
   Merve: GOLD 0,0%, mikozben ugyanabban az idoszakban 9 belepo tuzelt.

⚠ ES A SZALAG: a strategia EGYETLEN `Indicator` rekordot sem kuldott, tehat a
Bollinger-szalagot semelyik chart-idosikon nem rajzolta ki semmi.
"""
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


import logging
logging.disable(logging.INFO)

import strategy.bollinger_squeeze as B
from strategy import get_strategy_by_name
from strategy.base import MarketData
from strategy.settings import config_for_strategy, load_config
from trading.backtest import load_data
from trading.live_trader import default_params, strategy_params

SN = "bollinger_squeeze_breakout"
st = get_strategy_by_name(SN)
cfg = load_config("config.json")
cs = config_for_strategy(cfg, SN)


def _params(sym):
    p = strategy_params(sym, SN, cs, fallback=default_params(st, cs))
    return {**p, "point_size": cfg["pairs"][sym]["point_size"]}


# ── 1. A KIJELZES VISSZAJATSSZA az allapotot ─────────────────────────────
_src = (ROOT / "strategy" / "bollinger_squeeze.py").read_text(encoding="utf-8")
def _code(txt):
    """A forras KOMMENTEK nelkul. ⚠ A javitast MAGYARAZO komment emliti a regi
    megoldast (`last_signal`, `.iloc[i]`) — egy nyers szoveg-keresés emiatt
    hamisan bukna. A viselkedest a KOD hordozza."""
    out = []
    for ln in txt.splitlines():
        _c = ln.split("#", 1)[0]
        if _c.strip():
            out.append(_c)
    return chr(10).join(out)


_i = _src.find("def compute_display")
_blk = _code(_src[_i:_i + 2600])
check("a kijelzes VEGIGJATSSZA a sorozatot (nem egy friss allapotot leptet)",
      "for _r in _recs[:-1]:" in _blk, "")
# ⚠ A kijelzes KORONKENT es PARONKENT fut — a pandas soronkenti indexelese itt
# 7x lassabb (merve: 42 ms vs 6 ms 1001 gyertyara).
check("...`records`-bol, nem `.iloc[i]`-bol (a kijelzes-ut forro)",
      'ind.to_dict("records")' in _blk and ".iloc[i]" not in _blk)


# ── 2. A HAROM KOR A MOSTANI helyzetet mondja ────────────────────────────
_m = _code(_src[_src.find("def _marks"):_src.find("def compute_display")])
check("az entry kor NEM a ragados `last_signal`-bol jon",
      "last_signal" not in _m, "meg mindig a last_signal-t nezi")
check("...hanem a MOSTANI gyertya kitoresebol",
      "_breakout_signal(row, params)" in _m)
# ⚠ A release a TENYLEGES ablakot nezze, ne a nyers `bars_since_off >= 0`-t.
check("a release az ABLAKOT nezi (min..max gyertya a feloldas utan)",
      "min_bars_since_squeeze" in _m and "max_bars_after_squeeze" in _m)
check("...es kikapcsolt trend-szuronel is vilagit (sarga)",
      'dot(in_window,' in _m and '"yellow"' in _m)


# ── 3. MERES valodi adaton ───────────────────────────────────────────────
# ⚠ A szamok a LENYEG: egy kor akkor jelzes, ha RITKA. A 92%-on vilagito kor
# nem mond semmit.
for sym in ("GOLD", "Ger40"):
    d, _ = load_data(sym)
    p = _params(sym)
    ind = B.compute_indicators(d.tail(6000), p)
    recs = ind.to_dict("records")
    s = B.SqueezeState(symbol=sym)
    n = {"squeeze": 0, "release": 0, "entry": 0}
    for i, r in enumerate(recs[:-1]):
        s = B._advance(s, r, p)
        for k, c in st._marks(s, recs[i + 1], p).items():
            if c.color != "muted":
                n[k] += 1
    tot = len(recs) - 1
    _pct = {k: v / tot * 100 for k, v in n.items()}
    check(f"[{sym}] az osszeszukules-kor ESEMENY (1..25%)",
          1 < _pct["squeeze"] < 25, f"{_pct['squeeze']:.1f}%")
    # ⚠ A trend-szuro allapotatol FUGGETLENUL vilagitania kell, ha az ablak nyitva.
    check(f"[{sym}] a felfegyverzes-kor is ESEMENY (>0)",
          _pct["release"] > 0, f"{_pct['release']:.1f}% "
          f"(trend-szuro: {p.get('require_trend_alignment')})")
    # A kitores a legritkabb — ez a tenyleges jel.
    check(f"[{sym}] a kitores-kor RITKA (<5%) es nem nulla",
          0 < _pct["entry"] < 5, f"{_pct['entry']:.1f}%")
    check(f"[{sym}] a kitores ritkabb, mint a felfegyverzes",
          n["entry"] < n["release"], f"{n['entry']} vs {n['release']}")

    # A kijelzes-ut ugyanezt adja (nem egy masodik keplet).
    md = MarketData(symbol=sym, params=p, bars={"M15": d.tail(4000)})
    _cells = st.compute_display(md)["marks"]
    check(f"[{sym}] a compute_display mind a 3 kort visszaadja",
          set(_cells) == {"squeeze", "release", "entry"}, str(sorted(_cells)))


# ── 4. A SZALAG a charton ────────────────────────────────────────────────
_v = _code(_src[_src.find("def visual_objects"):])
check("a szalag KIRAJZOLODIK", "bb_ub" in _v and "bb_lb" in _v and "bb_mb" in _v)
# ⚠ NEM az MT5 sajat Bollingerjet kerjuk: az a CHART idosikjan szamolna, a
# strategia viszont a JEL-idosikon (alapbol H1) dont.
check("...a TENYLEGES ertekekbol, nem MT5-indikator-kereskent",
      "bb{_key}_" in _v and "Indicator(" not in _v)
check("...es korlatozott szamu gyertyara (nem az egesz ablakra)",
      "_BAND_BARS" in _src and "ind.tail(_BAND_BARS)" in _v)
check("...a NaN-ok kiszurve (a warmup eleje ures)", "a != a or b != b" in _v)

_d, _ = load_data("GOLD")
_md = MarketData(symbol="GOLD", params=_params("GOLD"), bars={"M15": _d.tail(4000)})
_objs = st.visual_objects(_md)
_band = [o for o in _objs if getattr(o, "name", "").startswith("bb")]
check("elesben is keszul szalag", len(_band) > 100, f"{len(_band)} szakasz")
_cols = {o.color for o in _band}
check("...harom vonal (kozep + ket szel)", _cols == {"gray", "blue"}, str(_cols))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
