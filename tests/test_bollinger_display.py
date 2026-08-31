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
      "_recs[:-1]" in _blk and "_advance(st," in _blk, "")
# ⚠ A kijelzes KORONKENT es PARONKENT fut — a pandas soronkenti indexelese itt
# 7x lassabb (merve: 42 ms vs 6 ms 1001 gyertyara).
check("...`records`-bol, nem `.iloc[i]`-bol (a kijelzes-ut forro)",
      'ind.to_dict("records")' in _blk and ".iloc[i]" not in _blk)


# ── 2. A HAROM KOR A MOSTANI helyzetet mondja ────────────────────────────
_m = _code(_src[_src.find("def _marks"):_src.find("def compute_display")])
# ⚠ EZ AZ ŐR ÁTALAKULT, és a miértje fontos. Eredetileg azt tiltotta, hogy a
# kitörés köre a `last_signal`-ból jöjjön — az RAGADÓS (sosem törlődik), tehát az
# első jel után ÖRÖKRE világított volna (mérve: a gyertyák 92,5%-án). Egy állandó
# kör nem jelzés, hanem dísz.
#
# 2026-08-25 óta a kör MÉGIS használja a `last_signal`-t — de KIZÁRÓLAG akkor, ha
# a jel a LEGUTÓBBI zárt gyertyán tüzelt (`last_signal_time == last_bar_time`).
# Enélkül a jelzés pillanata SOHA nem látszott: a `_advance` a jel után lezárja
# az ablakot, a kijelzés pedig utána fut (99 jelzésből 0-szor).
#
# A ragadósság ellen tehát már NEM a szöveg-keresés véd, hanem a MÉRÉS lentebb:
# „a kitores-kor RITKA (<5%)". Az a helyes őr — a viselkedést nézi, nem a betűt.
check("a kitores kore CSAK a tuzeles gyertyajan nezi a `last_signal`-t",
      "last_signal_time" in _m and "last_bar_time" in _m,
      "hianyzik az idobelyeg-osszehasonlitas")
check("...hanem a MOSTANI gyertya kitoresebol",
      "_breakout_signal(row, params)" in _m)
# ⚠ A release a TENYLEGES ablakot nezze, ne a nyers `bars_since_off >= 0`-t.
check("a release az ABLAKOT nezi (min..max gyertya a feloldas utan)",
      "min_bars_since_squeeze" in _m and "max_bars_after_squeeze" in _m)
check("...es kikapcsolt trend-szuronel is vilagit (sarga)",
      'dot(in_window or _tuzelt,' in _m and '"yellow"' in _m)


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
    _insq = 0
    for i, r in enumerate(recs[:-1]):
        s = B._advance(s, r, p)
        if bool(r.get("squeeze", False)):
            _insq += 1            # a NYERS squeeze-állapot (a kör forrása)
        for k, c in st._marks(s, recs[i + 1], p).items():
            if c.color != "muted":
                n[k] += 1
    tot = len(recs) - 1
    _pct = {k: v / tot * 100 for k, v in n.items()}
    _pct_insq = _insq / tot * 100
    # ⚠ A KORLÁT MÉRÉSEN ALAPUL — és ez a HARMADIK nekifutás. Érdemes tudni,
    # miért, mert mindkét korábbi modell HELYESNEK LÁTSZOTT, amíg a paraméterek
    # nem mozdultak:
    #
    #   1. (08-26) `max_bars_after_squeeze`-hez kötve — rossz magyarázó változó:
    #      a kör dominánsan az `in_sq`-tól ég, nem az ablaktól. Elbukott, amikor
    #      a Ger40 újraoptimalizálásakor a paraméter megváltozott.
    #   2. (08-31) „az `in_sq` a `bw_percentile` FÖLÉ nem mehet" — ez is téves:
    #      a küszöb egy GÖRDÜLŐ kvantilis (`rolling(look).quantile(pct)`), nem
    #      globális. Ha a sávszélesség eloszlása időben elmozdul, a saját gördülő
    #      küszöbe alá eső gyertyák aránya a `bw_percentile` FÖLÉ is kerülhet.
    #      Mérve (6 pár): Ger40 +0,4, a többi −4…−29 pont.
    #
    # A `bw_percentile` tehát KÖZELÍTÉS, nem korlát. A margó ezt ismeri el.
    _bwp = float(p.get("bw_percentile", 20) or 20)
    check(f"[{sym}] az összeszűkülés a `bw_percentile` KÖRÜL/ALATT van",
          _pct_insq <= _bwp + 5.0,
          f"{_pct_insq:.1f}% (bw_percentile={_bwp:.0f})")

    check(f"[{sym}] a kör az összeszűkülésnél TÖBBET mutat (ablak is)",
          _pct["squeeze"] >= _pct_insq - 0.01,
          f"kör {_pct['squeeze']:.1f}% vs in_sq {_pct_insq:.1f}%")
    check(f"[{sym}] ...de nem dísz (a `bw_percentile` + 20 pont alatt)",
          _pct["squeeze"] < _bwp + 20, f"{_pct['squeeze']:.1f}%")
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
    # ⚠ LAPOS szotar: `{stadium_kulcs: Cell}`. Itt korabban
    # `compute_display(md)["marks"]` allt — vagyis a teszt a HIBAS alakot
    # rogzitette, es ezzel be is fagyasztotta: a strategia egy szinttel
    # melyebben adta vissza a cellakat, a motor `c.text`-je elszallt, a sor
    # pedig uresen maradt. A teszt az IMPLEMENTACIOT tukrozte, nem a
    # SZERZODEST. A szerzodest most kulon meri: `test_strategy_cell_contract`.
    _cells = st.compute_display(md)
    check(f"[{sym}] a compute_display mind a 3 kort visszaadja",
          set(_cells) == {"squeeze", "release", "entry"}, str(sorted(_cells)))
    from strategy.base import Cell as _Cell
    check(f"[{sym}] ...LAPOSAN, Cell-ertekekkel",
          all(isinstance(v, _Cell) for v in _cells.values()),
          str({k: type(v).__name__ for k, v in _cells.items()}))


# ── 3b. A három kör FOLYAMAT-JELZŐ ─────────────────────────────
#
# ⚠ A FELHASZNÁLÓ LELETE: „egy kör jelent meg, abból is a KÖZÉPSŐ — ami azért
# fura, mert az első feltételnek kellett volna előbb teljesülnie".
#
# A megfigyelés helyes volt, de nem hibáról szólt: a `squeeze_off` DEFINÍCIÓ
# SZERINT azon a gyertyán igaz, ahol a szűkülés VÉGET ÉR — az ablak pontosan
# akkor nyílik, amikor az összeszűkülés megszűnik. A két kör magától SOSEM
# éghetett együtt (mérve 9 páron: együtt 1,0%).
#
# A döntés: FOLYAMAT-JELZŐ. A korábbi lépcső égve marad, amíg a belőle nyílt
# szakasz tart, és az epizód végén MIND elalszik — nem lesz „ragadós" dísz.
#
# ⚠ ÉS EGY HARMADIK LYUK, ami közben derült ki: a KITÖRÉS köre a jelzés
# pillanatában SOHA nem gyulladt ki. A `_advance` a jel után lezárja az ablakot
# (`bars_since_off = -1`), a kijelzés pedig UTÁNA fut — már zárt ablakot látott.
# Mérve: 99 tényleges jelzésből 0-szor látszott. Pont az a pillanat volt
# láthatatlan, amit nézni érdemes.

_LEPCSOK = ("squeeze", "release", "entry")
for sym in ("Ger40", "GOLD"):
    d, _ = load_data(sym)
    p = _params(sym)
    ind = B.compute_indicators(d.tail(8000), p)
    recs, idx = ind.to_dict("records"), ind.index
    s = B.SqueezeState(symbol=sym)
    n = jel = jel_lathato = nem_monoton = teljes = 0
    for i in range(len(recs) - 1):
        # A MOTOR sorrendje: előbb léptet, azután rajzol — a formálódó sorral.
        s = B._advance(s, recs[i], p)
        s.last_bar_time = idx[i]
        tuzelt = s.pending != "NONE"
        if tuzelt:
            s.last_signal_time = idx[i]
        s.pending = "NONE"
        eg = [st._marks(s, recs[i + 1], p)[k].color != "muted" for k in _LEPCSOK]
        n += 1
        if all(eg):
            teljes += 1
        if any(eg[j] and not eg[j - 1] for j in (1, 2)):
            nem_monoton += 1
        if tuzelt:
            jel += 1
            if eg[2]:
                jel_lathato += 1

    check(f"[{sym}] ⚠ a lépcsők MONOTONOK (nincs későbbi a korábbi nélkül)",
          nem_monoton == 0, f"{nem_monoton} kivétel {n} gyertyából")
    check(f"[{sym}] ⚠ a jelzés pillanata LÁTSZIK (mind a 3 kör ég)",
          jel > 0 and jel_lathato == jel, f"{jel_lathato}/{jel}")
    # ⚠ ÉS NEM DÍSZ: a teljes hármas ritka marad. Egy állandóan világító kör
    # nem jelzés — pontosan ezért esett ki annak idején a `last_signal`.
    check(f"[{sym}] ...de nem is dísz (a teljes hármas < 5%)",
          0 < 100 * teljes / n < 5, f"{100 * teljes / n:.1f}%")


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
