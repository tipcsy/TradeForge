"""A NATIV (Rust) MAG — gyorsitas, ami nem valtoztat eredmenyt (v3.34.0).

⚠ A KERES (2026-09-02, #9): „vizsgaljuk meg, hogy mennyit nyerunk egy 500-as
optimalizalassal, ha Rust-on vegezzuk el". A meres: a jelzes-allapotgep Rustban
929–1218x gyorsabb (negy paron), MINDEN paron bitre azonos jelzesszammal.

HAROM SZABALY, es mindharmat ITT orizzuk:

  1. A PYTHON A REFERENCIA. A nativ mag csak gyorsitas; ha a ketto elter, a
     Python a helyes. Ezert a legfontosabb allitas itt a PARITAS.
  2. RUST NELKUL IS MUKODIK MINDEN. A konyvtar hianya nem hiba — a program a
     Python-uton megy tovabb. EZ A TESZT RUST NELKULI GEPEN IS ZOLD.
  3. CSAK AMIT ISMER. A nativ ut strategiankent kulon engedelyezett
     (`native_kernel`), es minden mas esetben a Python fut. Egy „majdnem jo"
     nativ ut rosszabb, mint a semmi: neman MAS strategiat futtatna.

⚠ MIERT KELL EZ A TESZT AKKOR IS, HA NINCS RUST. Mert a SZERKEZETET is orzi: a
mezo-sorrendet a Rust `WprParams`-hoz kepest, a visszaeses letezeset, es hogy a
`.dll` ne kerulhessen a repoba. Ezek Rust nelkul is ellenorizhetok, es epp ezek
azok, amik egy masik gepen csendben elromlananak.
"""
import io
import os
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


from core import native                                  # noqa: E402
from strategy import get_strategy_by_name                 # noqa: E402
from strategy.base import Strategy                        # noqa: E402


# ══ 1. A SZERKEZET — Rust nelkul is ellenorizheto ══════════════════════
RS = io.open(ROOT / "rust" / "tfbt" / "src" / "lib.rs", encoding="utf-8").read()

# ⚠ A MEZO-SORREND KOTOTT. A Python egy sima `c_double` tombot ad at; ha a ket
# oldal sorrendje elcsuszik, a strategia MAS kuszobokkel futna — kivetel nelkul,
# neman. Ezert olvassuk ki a Rust `WprParams` mezoit, es vetjuk ossze.
_i = RS.index("pub struct WprParams {")
_j = RS.index("}", _i)
_rs_mezok = [ln.strip().split(":")[0].replace("pub ", "").strip()
             for ln in RS[_i:_j].splitlines()[1:] if ":" in ln]
_py_mezok = [k.replace("wpr_", "") for k in native.WPR_FIELDS]
check("a kuszob-mezok sorrendje egyezik a Rust `WprParams`-szal",
      _rs_mezok == _py_mezok, f"rust={_rs_mezok} py={_py_mezok}")

check("a Rust oldal ABI-verziot ad", "tfbt_abi_version" in RS)
check("a Python ugyanezt az ABI-t varja",
      f"KERNEL_ABI: i32 = {native.EXPECTED_ABI}" in RS,
      f"py={native.EXPECTED_ABI}")

# A `.dll` NEM kerulhet a repoba (binaris, gepfuggo).
_gi = io.open(ROOT / ".gitignore", encoding="utf-8").read()
check("a lefordított konyvtar ki van zarva a repobol",
      "rust/tfbt/target/" in _gi and "*.dll" in _gi)
check("a FORRAS viszont a repoban van",
      (ROOT / "rust" / "tfbt" / "Cargo.toml").exists())

# A strategia deklaralja a magot — es a nev VERZIOT is tartalmaz.
check("a `Strategy` alapja: NINCS nativ mag", Strategy.native_kernel == "",
      repr(Strategy.native_kernel))
_w = get_strategy_by_name("wpr_sma")
check("a wpr_sma deklaral magot, verzioval",
      _w.native_kernel == "wpr_sma_v1", _w.native_kernel)
_tobbi = [n for n in ("trend_pullback", "bollinger_squeeze_breakout", "ml_ai")
          if getattr(get_strategy_by_name(n), "native_kernel", "")]
check("a tobbi strategia NEM deklaral (a Python-ut a szabaly)", not _tobbi,
      ", ".join(_tobbi))

# A visszaeses a KODBAN is ott van, nem csak szandekban.
_bt = io.open(ROOT / "trading" / "backtest.py", encoding="utf-8").read()
check("a backtest a `native_kernel`-t nezi", 'native_kernel' in _bt)
check("...es `None`-nal a Python-uton megy tovabb", "_nat is not None" in _bt)
_nat_src = io.open(ROOT / "core" / "native.py", encoding="utf-8").read()
check("a betoltes ABI-t ellenoriz", "tfbt_abi_version" in _nat_src
      and "EXPECTED_ABI" in _nat_src)
check("a nativ ut KIKAPCSOLHATO (TFBT_NATIVE=0)", "TFBT_NATIVE" in _nat_src)


# ══ 2. PARITAS — csak ha a konyvtar tenyleg el ═════════════════════════
if not native.available():
    print(f"SKIP  a paritas-meres: {native.status()}")
    print("      (ez NEM hiba — a program Python-uton fut, ugyanazzal az")
    print("       eredmennyel. Forditas: python tools/build_native.py)")
else:
    import numpy as np
    import pandas as pd
    from trading.backtest import build_signal_series

    def _ket_ut(m15, m1, prm, pc):
        """`(python_jelzesek, nativ_jelzesek)` UGYANARRA az adatra."""
        _regi = os.environ.get("TFBT_NATIVE")
        try:
            os.environ["TFBT_NATIVE"] = "0"
            native._probalt, native._lib = False, None
            a = build_signal_series("T", m15, m1, prm, pc, strategy=_w)
            os.environ["TFBT_NATIVE"] = "1"
            native._probalt, native._lib = False, None
            b = build_signal_series("T", m15, m1, prm, pc, strategy=_w)
        finally:
            if _regi is None:
                os.environ.pop("TFBT_NATIVE", None)
            else:
                os.environ["TFBT_NATIVE"] = _regi
            native._probalt, native._lib = False, None
        return a.signals, b.signals

    # ⚠ AZ ADATNAK JELZEST KELL SZULNIE. A `wpr_sma` VISSZAHUZODASRA lep be — ar
    # az SMA folott, de a WPR az aljan —, ami csak akkor all elo, ha az SMA
    # sokkal lassabb a WPR ablakanal. Egy bolyongas NULLA jelzest ad, es akkor a
    # paritas ket ures halmazt hasonlitana ossze.
    n15 = 900
    n1 = n15 * 15
    t15, t1 = np.arange(n15), np.arange(n1)
    p15 = 100 + 0.10 * t15 + 4.0 * np.sin(t15 / 4.0)
    p1 = (100 + 0.10 * (t1 / 15.0) + 4.0 * np.sin(t1 / 60.0)
          + 0.8 * np.sin(t1 / 5.0))
    m15 = pd.DataFrame({"open": p15, "high": p15 + 0.4, "low": p15 - 0.4,
                        "close": p15},
                       index=pd.date_range("2026-01-01", periods=n15,
                                           freq="15min", tz="UTC"))
    m1 = pd.DataFrame({"open": p1, "high": p1 + 0.1, "low": p1 - 0.1,
                       "close": p1},
                      index=pd.date_range("2026-01-01", periods=n1,
                                          freq="1min", tz="UTC"))
    PRM = {"sma_period": 100, "wpr_m15_period": 14, "wpr_m1_period": 14,
           "atr_period": 14, "wpr_m15_sell_extreme": -20,
           "wpr_m15_buy_extreme": -80, "wpr_m15_sell_trigger": -50,
           "wpr_m15_buy_trigger": -50, "wpr_m1_sell_extreme": -20,
           "wpr_m1_buy_extreme": -80, "wpr_m1_sell_trigger": -50,
           "wpr_m1_buy_trigger": -50, "sl_atr_mult": 1.5, "tp_rr_ratio": 2.0,
           "point_size": 0.01}
    PC = {"point_size": 0.01, "pv1_point": 1.0}

    _py, _rs = _ket_ut(m15, m1, PRM, PC)
    check("a nativ es a Python jelzesei BITRE egyeznek", _py == _rs,
          f"py={len(_py)} nativ={len(_rs)}")
    check("...es volt mit osszevetni", len(_py) > 0, f"{len(_py)} jelzes")

    # ⚠ A KUSZOBOK TENYLEG ATMENNEK. Ha a mezok elcsusznanak, egy MASIK
    # kuszob-keszlettel ugyanaz a szam jonne ki — ezert MEGVALTOZTATJUK oket, es
    # elvarjuk, hogy MINDKET ut ugyanugy reagaljon.
    _szigoru = {**PRM, "wpr_m1_buy_extreme": -95, "wpr_m1_sell_extreme": -5}
    _py2, _rs2 = _ket_ut(m15, m1, _szigoru, PC)
    check("szigorubb kuszoboknel is egyeznek", _py2 == _rs2,
          f"py={len(_py2)} nativ={len(_rs2)}")
    check("...es a kuszob TENYLEG szamit (kevesebb jelzes)",
          len(_py2) < len(_py), f"{len(_py)} -> {len(_py2)}")

    # ELES adaton is, ha van (a CI-n nincs).
    _pq15 = ROOT / "data" / "m15" / "Ger40.parquet"
    _pq1 = ROOT / "data" / "m1" / "Ger40.parquet"
    if _pq15.exists() and _pq1.exists():
        _e15 = pd.read_parquet(_pq15).iloc[-12000:]
        _e1 = pd.read_parquet(_pq1).iloc[-180000:]
        _epy, _ers = _ket_ut(_e15, _e1, PRM, PC)
        check("ELES adaton is bitre egyeznek", _epy == _ers,
              f"py={len(_epy)} nativ={len(_ers)}")
    else:
        print("SKIP  az eles adatos osszevetes (nincs parquet)")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
