"""A BACKTEST FORRO UTJA — a per-bar hozzaferes ne kopjon vissza (v3.33.0).

⚠ A LELET (2026-09-04, a Rust-kerdes profilozasabol). Egy trial (Ger40, 6 honap,
152 833 M1 + 10 193 M15 bar) 2,76 mp volt, es ebbol MINDOSSZE 0,8% a valodi,
vektorizalt szamitas. A tobbi ertelmezes. A ket legdragabb tetel:

    M15 allapotgep `.iloc[ptr]`-rel        0,348 mp
    ...ugyanaz tombokbol                   0,027 mp   → 13×

es a mutato-lepteteshez KET pandas Timestamp osszehasonlitasa MINDEN M1 baron
(152 833× trialonkent), holott ket int64 is eleg.

A javitas utan: 2,76 → 1,88 mp, es a kotesek/P&L 5 paron BITRE azonosak.

⚠ MIERT KELL OR EGY GYORSITASHOZ. Mert a gyorsitas VISSZAKOPHAT: egy kesobbi
javitas „gyorsan" beir egy `m15.iloc[ptr]`-t a ciklusba, minden teszt zold marad,
es a 13× csendben elvesz. A sebesseg-romlas ugyanolyan nema hiba, mint a tobbi —
csak nem eredmenyben latszik, hanem idoben.

⚠ ES AMIT EZ A TESZT NEM ENGED: hogy a gyorsitas MEGVALTOZTASSA az eredmenyt.
Az utolso szakasz a REGI (pandas-soros) utat jatssza ujra, es a jelzeseknek
bitre egyeznie kell.
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


SRC = io.open(ROOT / "trading" / "backtest.py", encoding="utf-8").read()


def _fuggveny(nev: str) -> str:
    """Egy fuggveny forrasa (a kovetkezo top-level `def`-ig)."""
    i = SRC.index(f"def {nev}(")
    j = SRC.find("\ndef ", i + 1)
    return SRC[i:j if j > 0 else len(SRC)]


# ══ 1. A KOZOS SEGEDEK LETEZNEK ════════════════════════════════════════
for nev in ("_oszlop_tombok", "_epoch_ns", "_row_at"):
    check(f"van `{nev}` seged", f"def {nev}(" in SRC)


# ══ 2. A FORRO CIKLUSOKBAN NINCS PER-BAR `.iloc` ═══════════════════════
# ⚠ A `.iloc` onmagaban nem tilos (a keret-elokeszitesben teljesen rendben van);
# a CIKLUSON BELUL viszont baronkent epit uj pandas Series-t.
for nev in ("build_signal_series", "run_pair"):
    src = _fuggveny(nev)
    rossz = [ln.strip() for ln in src.splitlines()
             if "m15.iloc[m15_ptr]" in ln or "m15.iloc[ptr]" in ln]
    check(f"{nev}: nincs per-bar `m15.iloc[...]` az allapotgephez", not rossz,
          "; ".join(rossz[:2]))
    check(f"{nev}: a sort a kozos `_row_at` adja", "_row_at(" in src)


# ══ 3. A MUTATO-LEPTETES int64-en megy, nem Timestampen ════════════════
# ⚠ Ez a MINDEN M1 BARON lefuto osszehasonlitas — a leggyakrabban vegrehajtott
# sor az egesz backtestben.
for nev in ("build_signal_series", "run_pair"):
    src = _fuggveny(nev)
    check(f"{nev}: a mutato-leptetes int64-en", "_t15_ns[" in src and "_delta_ns" in src)
    rossz = [ln.strip() for ln in src.splitlines()
             if "m15_times[m15_ptr + 1] + _m15_delta" in ln]
    check(f"{nev}: nincs Timestamp-aritmetika a ciklusban", not rossz,
          "; ".join(rossz[:1]))

# NANOSZEKUNDUM, nem masodperc: a masodpercre kerekites egy nem egesz masodperces
# idosik-deltanal NEMAN elcsusztatna a gyertyahatart.
_ep = _fuggveny("_epoch_ns")
check("az idobelyeg NANOSZEKUNDUMBAN megy", '"int64"' in _ep and "1_000_000_000" not in _ep,
      _ep.splitlines()[-1].strip())


# ══ 4. A SOR-SZERZODES VALTOZATLAN ═════════════════════════════════════
# A `bt_*` hookok harom dolgot hasznalnak: `row[...]`, `row.get(...)`, `row.name`.
import pandas as pd                                   # noqa: E402
from trading.backtest import _row_at, _oszlop_tombok, _epoch_ns   # noqa: E402

_df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]},
                   index=pd.date_range("2026-01-01", periods=2, freq="15min",
                                       tz="UTC"))
_c, _a = _oszlop_tombok(_df)
_r = _row_at(_c, _a, list(_df.index), 1)
check("a sor indexelheto (`row['a']`)", _r["a"] == 2.0)
check("a sor `.get`-elheto, alapertekkel",
      _r.get("b") == 4.0 and _r.get("nincs", 7) == 7)
check("a sornak van `.name`-je (az ml_ai kulcskent hasznalja)",
      _r.name == _df.index[1], str(_r.name))
check("az epoch-tomb int64 es ns-ben van",
      _epoch_ns(_df.index).dtype == "int64"
      and int(_epoch_ns(_df.index)[1] - _epoch_ns(_df.index)[0]) == 900_000_000_000,
      str(_epoch_ns(_df.index)))


# ══ 5. AZ EREDMENY VALTOZATLAN — a REGI utat ujrajatszva ═══════════════
# ⚠ EZ A LENYEG. A tobbi allitas szerkezeti; ez azt meri, hogy a gyorsitas
# VISELKEDES-SEMLEGES: a regi (pandas-soros, Timestamp-aritmetikas) valtozat
# ugyanazokat a jelzeseket adja, mint a mostani.
try:
    import numpy as np
    from strategy import get_strategy_by_name
    from trading.backtest import (_prepare_frames, _prepare_params,
                                  _signal_bar_delta, build_signal_series)

    st = get_strategy_by_name("wpr_sma")
    # ⚠ AZ ADATNAK JELZEST KELL SZULNIE, kulonben a teszt semmit nem bizonyit:
    # egy ures halmaz mindig egyezik egy masik ures halmazzal. A `wpr_sma`
    # VISSZAHUZODASRA lep be — ar az SMA FOLOTT (trend), de a WPR az aljan
    # (rovid tavon tuladott). Ez csak akkor all elo, ha az SMA sokkal LASSABB,
    # mint a WPR ablaka; ezert emelkedo trend + gyors lenges, sma_period=100.
    # (Egy egyszeru bolyongas vagy egy lassu szinusz NULLA jelzest ad — ki is
    # probaltam, ezert all itt ez a megjegyzes.)
    n15, n1 = 900, 900 * 15
    idx15 = pd.date_range("2026-01-01", periods=n15, freq="15min", tz="UTC")
    idx1 = pd.date_range("2026-01-01", periods=n1, freq="1min", tz="UTC")
    _t15 = np.arange(n15)
    _t1 = np.arange(n1)
    p15 = 100 + 0.10 * _t15 + 4.0 * np.sin(_t15 / 4.0)
    p1 = (100 + 0.10 * (_t1 / 15.0) + 4.0 * np.sin(_t1 / 60.0)
          + 0.8 * np.sin(_t1 / 5.0))
    m15 = pd.DataFrame({"open": p15, "high": p15 + 0.4, "low": p15 - 0.4,
                        "close": p15}, index=idx15)
    m1 = pd.DataFrame({"open": p1, "high": p1 + 0.1, "low": p1 - 0.1,
                       "close": p1}, index=idx1)
    prm = {"sma_period": 100, "wpr_m15_period": 14, "wpr_m1_period": 14,
           "atr_period": 14, "wpr_m15_sell_extreme": -20,
           "wpr_m15_buy_extreme": -80, "wpr_m15_sell_trigger": -50,
           "wpr_m15_buy_trigger": -50, "wpr_m1_sell_extreme": -20,
           "wpr_m1_buy_extreme": -80, "wpr_m1_sell_trigger": -50,
           "wpr_m1_buy_trigger": -50, "sl_atr_mult": 1.5, "tp_rr_ratio": 2.0,
           "point_size": 0.01}
    pc = {"point_size": 0.01, "pv1_point": 1.0}

    uj = build_signal_series("T", m15, m1, prm, pc, strategy=st)

    # A REGI ut ujrajatszva: `.iloc` + Timestamp-aritmetika.
    _p = _prepare_params("T", prm, pc)
    _m15, _m1 = _prepare_frames(m15, m1, _p, st, None, None)
    _d = _signal_bar_delta(st, _p)
    _times = _m15.index.to_list()
    _state = st.bt_new_state("T")
    _ptr, _prev, _regi = 0, None, {}
    for _i in range(len(_m1.index)):
        _t = _m1.index[_i]
        _row = _m1.iloc[_i]
        while _ptr + 1 < len(_times) and _times[_ptr + 1] + _d <= _t:
            _ptr += 1
            _state = st.bt_on_high_close(_state, _m15.iloc[_ptr], _p)
        if _prev is not None:
            _s = st.bt_on_low_close(_state, _prev, _row, _p)
            if _s != "NONE":
                _regi[_i] = _s
        _prev = _row

    check("a jelzesek BITRE egyeznek a regi uttal", uj.signals == _regi,
          f"uj={len(uj.signals)} regi={len(_regi)}")
    check("...es tenyleg volt mit osszevetni", len(_regi) > 0, f"{len(_regi)} jelzes")
except Exception as _ex:                     # pragma: no cover
    check("a regi-ut osszevetes lefutott", False, f"{type(_ex).__name__}: {_ex}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
