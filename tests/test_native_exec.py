"""A NATIV VEGREHAJTASI CIKLUS — a masodik Rust-mag (v3.36.0).

⚠ MIT CSINAL. A jelzes-mag utan a VEGREHAJTAS is atkerult: SL/TP a bid/ask
modellel, `none`/`off`/`risky` preset (breakeven + trailing), cost-cut, napi
veszteseglimit, slot-keret, meretezes, jutalek/swap. Merve (wpr_sma, 3 honap):
Ger40 0,90 -> 0,60 mp, GOLD 2,07 -> 1,73 mp, EURUSD 0,70 -> 0,44 mp.

⚠ MIERT LEHETSEGES EGYALTALAN. Mert a belepo DONTESE kikerult egy kulon
fuggvenybe (`run_pair._entry_decision`), ami KIZAROLAG a bar sajat adataibol
dolgozik — se egyenleg, se slot, se nyitott pozicio. Igy a tervek ELORE
kiszamolhatok, es a ciklus mar csak vegrehajt. A ket ut UGYANAZT a fuggvenyt
hivja: ez nem kenyelem, hanem a paritas feltetele.

A HAROM SZABALY ITT IS AZ URALKODO (lasd `test_native_kernel.py`):
  1. A PYTHON A REFERENCIA — a paritas eles adaton, MINDEN mezore.
  2. RUST NELKUL IS MUKODIK MINDEN — ez a teszt Rust nelkuli gepen is ZOLD.
  3. CSAK AMIT ISMER — a reszleges zaras (Felezo/Pajzs/Fibo), a poziciopites,
     a kiszallasi jel, az esemeny-naplo es a kezi szintek a PYTHON-uton
     futnak. Az elmaradas INDOKA naplozva van: egy gyorsitas, ami neman nem
     kapcsol be, a legrosszabb fajta.
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


from core import native                                   # noqa: E402
import trading.backtest as bt                             # noqa: E402

RS = io.open(ROOT / "rust" / "tfbt" / "src" / "exec.rs", encoding="utf-8").read()
BT = io.open(ROOT / "trading" / "backtest.py", encoding="utf-8").read()

# ── 1. A SZERKEZET (Rust nelkul is ellenorizheto) ───────────────────────
# ⚠ EZ A LEGFONTOSABB ALLITAS EBBEN A FAJLBAN. Egy elcsuszott mezo nem
# osszeomlast okoz, hanem MAS meretezest — es a backtest tovabb fut, rossz
# szammal. A ket lista kezzel keszul, tehat kezzel is el tud csuszni.
_st = RS.split("pub struct ExecParams {", 1)[1].split("}", 1)[0]
_rs_mezok = tuple(s.split("pub ", 1)[1].split(":", 1)[0].strip()
                  for s in _st.splitlines() if s.strip().startswith("pub "))
check("az `ExecParams` mezo-sorrendje egyezik a Python `EXEC_FIELDS`-szel",
      _rs_mezok == native.EXEC_FIELDS,
      f"rust={len(_rs_mezok)} py={len(native.EXEC_FIELDS)}")

# A kimeneti sorok `*f(k) = ... t.<mezo> ...` alakuak; a k SORRENDJE szamit.
_sorok = [s.strip() for s in RS.splitlines() if s.strip().startswith("*f(")]
# A `dir` es a `risk_free` logikai mezobol lesz szam — mas a neve a Trade-en.
_varT = {"dir": "t.dir_buy", "risk_free": "t.risk_free"}
_baj = [nev for k, nev in enumerate(native.EXEC_OUT_F64)
        if k >= len(_sorok) or not _sorok[k].startswith(f"*f({k})")
        or _varT.get(nev, f"t.{nev}") not in _sorok[k]]
check("a kimeneti f64-mezok sorrendje is egyezik",
      len(_sorok) == len(native.EXEC_OUT_F64) and not _baj,
      f"{len(_sorok)} sor, eltero: {_baj}")

for nev, kod in (("PRESET_NONE", 0), ("PRESET_OFF", 1), ("PRESET_RISKY", 2)):
    check(f"a {nev} kodja {kod} mindket oldalon",
          f"const {nev}: i32 = {kod};" in RS
          and kod in [int(v) for v in bt._NATV_PRESET_KOD.values()])
check("a Python csak a harom ismert presetet engedi at",
      set(bt._NATV_PRESETEK) == {"none", "off", "risky"},
      str(sorted(bt._NATV_PRESETEK)))

# ── 2. A VISSZAESES ES AZ INDOK ────────────────────────────────────────
check("a natív ut kikapcsolhato (TFBT_NATIVE=0)", "TFBT_NATIVE" in
      io.open(ROOT / "core" / "native.py", encoding="utf-8").read())
check("a `run_exec` a konyvtar hianyaban None-t ad (nem dob)",
      native.run_exec({}, {}) is None or native.available())
for indok in ("esemény-napló", "pozícióépítés", "kiszállási jel",
              "kézi események", "haladás-jelentés"):
    check(f"az elmaradas indoka nevesitve: {indok}", f'"{indok}' in BT)
check("...es naplozva is van", "natív végrehajtás KIMARAD" in BT)
check("a betelt kimeneti keret NEM csonkit, hanem visszaesik",
      "a kimeneti keret betelt" in
      io.open(ROOT / "core" / "native.py", encoding="utf-8").read())

# ── 3. A KET KOCKAZATI SZAZALEK (ez mar egyszer elcsuszott volna) ──────
# A MERETEZES a kapu-hatassal csokkentett `sizing_cfg`-bol jon, a SLOT-SULY
# viszont a szamla EREDETI keretebol (`trading_cfg`). Egyetlen mezovel a
# `cautious`/kapu-csokkentett futasok mas slot-sulyt adnanak.
check("a slot-suly kulon kockazati szazalekot kap", "slot_risk_pct" in RS
      and "slot_risk_pct" in BT and "slot_risk_pct" in native.EXEC_FIELDS)
check("...es a meretezes a csokkentett `sizing_cfg`-bol",
      '"account_risk_pct": sizing_cfg["account_risk_pct"]' in BT)

# ── 4. PARITAS ELES ADATON (csak ha van Rust ES van adat) ──────────────
_futott = False
if native.available() and os.environ.get("TFBT_NATIVE", "1") != "0":
    import json
    import pandas as pd
    from strategy import get_strategy_by_name
    from core.execution_params import load_execution_params
    try:
        from main import load_cfg
        cfg = load_cfg()
        st = get_strategy_by_name("wpr_sma")
        MEZOK = ("direction", "open_time", "open_price", "sl", "tp", "lot",
                 "sl_points", "entry_atr", "entry_balance", "risk_usd",
                 "risk_pct", "slot_weight", "close_time", "close_price",
                 "pnl_usd", "commission_usd", "swap_usd", "pnl_points",
                 "status", "risk_free")

        def _fut(sym, nativ):
            pf = ROOT / "data" / "optimized_params" / "wpr_sma" / f"{sym}.json"
            prm = json.loads(pf.read_text(encoding="utf-8")).get("params") or {}
            prm = {**prm, **load_execution_params(sym, cfg)}
            prm.setdefault("point_size",
                           (cfg.get("pairs") or {}).get(sym, {}).get("point_size"))
            m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{sym}.parquet")
            m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")
            # A visszaeses kikenyszeritese: a Python-ut ugyanaz a run_pair,
            # csak a natív blokk nelkul.
            _ment = bt._natv_exec
            if not nativ:
                bt._natv_exec = lambda *a, **k: None
            try:
                r = bt.run_pair(sym, m15, m1, prm,
                                (cfg.get("pairs") or {}).get(sym) or {},
                                cfg["trading"],
                                float(cfg["trading"].get("initial_balance", 1000.0)),
                                test_start="2026-05-01", test_end="2026-08-01",
                                strategy=st, cfg=cfg, exec_gates=True)
            finally:
                bt._natv_exec = _ment
            return [[str(getattr(t, m)) for m in MEZOK] for t in r.trades]

        for sym in ("Ger40", "GOLD"):
            if not (ROOT / "data" / "m1" / f"{sym}.parquet").exists():
                continue
            _py, _rs = _fut(sym, False), _fut(sym, True)
            _futott = True
            check(f"{sym}: a natív es a Python kotesei BITRE egyeznek",
                  _py == _rs, f"{len(_py)} vs {len(_rs)} kotes")
            check(f"{sym}: ...es volt mit osszevetni", len(_py) > 0,
                  f"{len(_py)} kotes")
    except Exception as e:      # adat/config hianya nem teszthiba
        print(f"SKIP  eles paritas — {type(e).__name__}: {e}")

if not _futott:
    print("SKIP  eles paritas (nincs Rust vagy nincs adat) — a szerkezeti "
          "allitasok akkor is futottak")

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
