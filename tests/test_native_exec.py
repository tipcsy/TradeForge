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

# ── 1/b. A LEGFONTOSABB SZABALY: NINCS STRATEGIA-LOGIKA A RUSTBAN ──────
# ⚠ EZ AZ OR A `test_native_kernel.py` HELYET VETTE AT (2026-09-05). Addig a
# `wpr_sma` jelzes-allapotgepe DUPLAN letezett: Pythonban es Rustban. A
# felhasznalo mutatott ra, hogy ez szembemegy a sajat szabalyunkkal — ugyanazzal
# az ervvel utasitottuk el az MQL5-os szimulalt vegrehajtast: KET FORRAS, AMI
# KULON ROMLIK EL. A strategia EGY helyen van, Pythonban.
#
# Ez a teszt azt orzi, hogy ne kusszon vissza. Ha valaki strategia-logikat tesz
# a Rustba, ITT bukik el — nem fel ev mulva egy neman elteren futo backteszten.
# ⚠ A KOMMENTEKET LE KELL VAGNI. A `lib.rs` fejlece epp arrol szol, hogy MIT
# vezettunk ki es miert — abban szerepel a `wpr_sma` neve. Az or a KODOT nezi.
def _kod_nelkul_komment(txt: str) -> str:
    ki, i, n = [], 0, len(txt)
    while i < n:
        if txt.startswith("//", i):                 # sor-komment (a //! is)
            i = txt.find(chr(10), i)
            if i < 0:
                break
        elif txt.startswith("/*", i):               # blokk-komment
            v = txt.find("*/", i)
            i = n if v < 0 else v + 2
        else:
            ki.append(txt[i]); i += 1
    return "".join(ki)


_RS_ALL = _kod_nelkul_komment("".join(
    (ROOT / "rust" / "tfbt" / "src" / f).read_text(encoding="utf-8")
    for f in ("lib.rs", "exec.rs")))
from strategy import registered_strategy_names                # noqa: E402
_nevek = [n for n in registered_strategy_names() if n.lower() in _RS_ALL.lower()]
check("a Rust konyvtarban NINCS strategia-nev", not _nevek, str(_nevek))
for _jel in ("wpr", "sma_period", "keltner", "bollinger", "stoch", "signal_detector"):
    check(f"...es nincs benne strategia-fogalom: `{_jel}`",
          _jel not in _RS_ALL.lower())
check("egyetlen strategia sem deklaral natív magot",
      not any(hasattr(_s, "native_kernel")
              for _s in [__import__("strategy", fromlist=["x"]).get_strategy_by_name(n)
                         for n in registered_strategy_names()]))
check("a lib.rs kimondja, hogy ez SZANDEKOS hatar",
      "NINCS, ÉS NEM IS LESZ STRATÉGIA-LOGIKA" in
      (ROOT / "rust" / "tfbt" / "src" / "lib.rs").read_text(encoding="utf-8"))

# ── 1/c. A KONYVTAR a repobol ki, a FORRAS benne ───────────────────────
_gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
check("a lefordított konyvtar ki van zarva a repobol",
      any(x in _gi for x in ("*.dll", "rust/tfbt/target", "target/")), "")
check("a Rust FORRAS viszont a repoban van",
      (ROOT / "rust" / "tfbt" / "src" / "exec.rs").exists())

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

        # /!\ EZ A BLOKK KORABBAN URESEN MENT AT (javitva 2026-09-08).
        # A `run_pair`-t `signal_series` NELKUL hivta, a nativ ut viszont pont
        # akkor marad ki ("nincs elore epitett jelolt-lista") — tehat MINDKET
        # kar a Python-uton futott, es a "BITRE egyeznek" allitas onmagat
        # hasonlitotta ossze. Ugyanaz a vakuum-teszt osztaly, mint a labor
        # 0-vs-0 paritasa. Emiatt NEM fogta meg a `breakeven_r` ABI-rest sem.
        # Most: (1) jelolt-listat adunk, (2) MEGKOVETELJUK, hogy a nativ ut
        # tenylegesen lefusson, (3) es kulon ellenorizzuk a kimaradast.
        TOL, IG = "2026-05-01", "2026-08-01"

        def _adat(sym):
            pf = ROOT / "data" / "optimized_params" / "wpr_sma" / f"{sym}.json"
            prm = json.loads(pf.read_text(encoding="utf-8")).get("params") or {}
            prm = {**prm, **load_execution_params(sym, cfg)}
            prm.setdefault("point_size",
                           (cfg.get("pairs") or {}).get(sym, {}).get("point_size"))
            m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{sym}.parquet")
            m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{sym}.parquet")
            return prm, m15, m1

        def _fut(sym, nativ, rr_spec):
            """`(kotesek, futott_e_a_nativ)`."""
            prm, m15, m1 = _adat(sym)
            ser = bt.build_signal_series(
                sym, m15, m1, prm, (cfg.get("pairs") or {}).get(sym) or {},
                strategy=st, test_start=TOL, test_end=IG)
            _ment = bt._natv_exec
            _hivas = {"n": 0}

            def _spy(*a, **k):
                out = _ment(*a, **k)
                if out is not None:
                    _hivas["n"] += 1
                return out

            bt._natv_exec = (lambda *a, **k: None) if not nativ else _spy
            try:
                r = bt.run_pair(sym, m15, m1, prm,
                                (cfg.get("pairs") or {}).get(sym) or {},
                                cfg["trading"],
                                float(cfg["trading"].get("initial_balance", 1000.0)),
                                test_start=TOL, test_end=IG,
                                strategy=st, cfg=cfg, exec_gates=True,
                                rr=rr_spec, signal_series=ser)
            finally:
                bt._natv_exec = _ment
            return ([[str(getattr(t, m)) for m in MEZOK] for t in r.trades],
                    _hivas["n"] > 0)

        from core import risk_reduction as _rrx
        _RR_NATV = {**_rrx.default_config(), "preset": _rrx.PRESET_OFF,
                    "breakeven_r": 0.0}
        _RR_BE_R = {**_RR_NATV, "breakeven_r": 1.0}

        for sym in ("Ger40", "GOLD"):
            if not (ROOT / "data" / "m1" / f"{sym}.parquet").exists():
                continue
            _py, _ = _fut(sym, False, _RR_NATV)
            _rs, _ran = _fut(sym, True, _RR_NATV)
            _futott = True
            check(f"{sym}: /!\ a natív ut TENYLEG lefutott (nem ures paritas)",
                  _ran, "a nativ blokk nem hivodott meg")
            check(f"{sym}: a natív es a Python kotesei BITRE egyeznek",
                  _py == _rs, f"{len(_py)} vs {len(_rs)} kotes")
            check(f"{sym}: ...es volt mit osszevetni", len(_py) > 0,
                  f"{len(_py)} kotes")
            # /!\ A `breakeven_r`-t a natív ABI NEM ismeri (`EXEC_FIELDS`:
            # van `be_pct`, nincs `be_r`). Merve: azonos jelolt-listan 87 vs
            # 166 kotes. Amig a Rust oldal nem tudja, KI KELL MARADNIA.
            _br, _ran_br = _fut(sym, True, _RR_BE_R)
            check(f"{sym}: /!\ breakeven_r mellett a natív ut KIMARAD",
                  not _ran_br, "a nativ ut lefutott, pedig nem ismeri a be_r-t")
            _br_py, _ = _fut(sym, False, _RR_BE_R)
            check(f"{sym}: ...es igy a ket ut TOVABBRA is egyezik",
                  _br == _br_py, f"{len(_br)} vs {len(_br_py)} kotes")
    except Exception as e:      # adat/config hianya nem teszthiba
        print(f"SKIP  eles paritas — {type(e).__name__}: {e}")

if not _futott:
    print("SKIP  eles paritas (nincs Rust vagy nincs adat) — a szerkezeti "
          "allitasok akkor is futottak")

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
