"""A chart KÜLÖNBÖZTESSE MEG a tényleges kötést a kimaradó jelzéstől.

⚠ A LELET (2026-08-31). A felhasználó egy `trend_pullback` jelzés-csomót
elemzett a charton, és ötből HÁRMAT olvasott kötésnek — „2 lett volna
veszteséges, és egy nyereséges". A valóság: a motor KETTŐT kötött volna
(egy páron egyszerre egy pozíció lehet), és a csomó nettó **+1,00 R** volt,
nem veszteséges. A másik csomóban 10 jelzésből EGY kötés lett.

A chart nem hazudott — csak nem mondta el a különbséget: minden jelzést
ugyanazzal az öt objektummal (vonal + címke + belépő/SL/TP) rajzolt ki, akkor
is, ha az élesben sosem lett volna kötés. Ez ugyanaz a néma osztály, mint a
viz-sáv romlása és a warmup-mélység eltérése: a kép magabiztos, és mást mutat,
mint amit a motor csinál.

A JAVÍTÁS: `visual.mark_blocked` végigjátssza a jelzés-sorozatot (egy pozíció
egyszerre), és a kimaradókra `skip`-et ír; az `entry_marks` az ilyet VÉKONY
SZÜRKE vonalnak rajzolja — látszik, hogy volt jel, de semmi nem sugall kötést.
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

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import strategy.visual as viz

# ── Egy zsinór M1 bár, ismert csúcsokkal/aljakkal ─────────────────────────
_N = 200
_IDX = pd.date_range("2026-08-27 00:00", periods=_N, freq="1min", tz="UTC")


def barok(high, low):
    return pd.DataFrame({"high": np.asarray(high, dtype=float),
                         "low": np.asarray(low, dtype=float)}, index=_IDX)


def _t(i):
    return int(_IDX[i].timestamp())


# Alap: 100-as ár, a 20. báron 90-re esik (SL), a 60.-on 120-ra megy (TP).
_h = np.full(_N, 100.0)
_l = np.full(_N, 100.0)
_l[20] = 90.0
_h[60] = 120.0
BARS = barok(_h, _l)

# ── 1. A LÉNYEG: nyitott pozíció alatt a jelzés KIMARAD ───────────────────
recs = [{"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0},
        {"t": _t(10), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0},
        {"t": _t(30), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0}]
n = viz.mark_blocked(recs, BARS, "teszt")
check("⚠ a nyitott pozíció alatti jelzés KIMARAD", n == 1 and recs[1].get("skip") == 1,
      f"{n} kimaradó")
check("...a pozíciót NYITÓ jelzés nem marad ki", not recs[0].get("skip"))
check("...a ZÁRÁS UTÁNI jelzés újra köt", not recs[2].get("skip"))

# ── 2. A STOP nyer, ha egy báron belül mindkettő teljesül ─────────────────
# ⚠ Ugyanaz a konzervatív konvenció, mint a `tools/research/lab.simulate`-ben:
# különben a chart és a mérés MÁST mondana ugyanarra a csomóra.
_h2, _l2 = np.full(_N, 100.0), np.full(_N, 100.0)
_h2[20], _l2[20] = 130.0, 90.0                  # egy báron belül SL is, TP is
r2 = [{"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 120.0},
      {"t": _t(25), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 120.0}]
viz.mark_blocked(r2, barok(_h2, _l2), "teszt")
check("⚠ ütközésnél a STOP zár (mint a kutató-laborban)", not r2[1].get("skip"))

# ── 3. Ami az ablak végéig nyitva marad, MINDENT tilt utána ───────────────
_lapos = barok(np.full(_N, 100.0), np.full(_N, 100.0))
r3 = [{"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0},
      {"t": _t(50), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0},
      {"t": _t(150), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0}]
viz.mark_blocked(r3, _lapos, "teszt")
check("⚠ a végig NYITVA maradó pozíció után minden kimarad",
      [bool(r.get("skip")) for r in r3] == [False, True, True])

# ── 4. SELL-oldal: tükrözve ───────────────────────────────────────────────
_h4, _l4 = np.full(_N, 100.0), np.full(_N, 100.0)
_h4[20] = 110.0                                  # SELL SL felfelé
r4 = [{"t": _t(0), "d": "SELL", "e": 100.0, "sl": 105.0, "tp": 80.0},
      {"t": _t(10), "d": "SELL", "e": 100.0, "sl": 105.0, "tp": 80.0},
      {"t": _t(30), "d": "SELL", "e": 100.0, "sl": 105.0, "tp": 80.0}]
viz.mark_blocked(r4, barok(_h4, _l4), "teszt")
check("SELL: a stop FÖLFELÉ zár",
      [bool(r.get("skip")) for r in r4] == [False, True, False])

# ── 5. Idempotens és sorrend-független ────────────────────────────────────
_masolat = [dict(r) for r in recs]
viz.mark_blocked(recs, BARS, "teszt")
check("⚠ újraszámoláskor a RÉGI jelölés nem él túl (idempotens)",
      [r.get("skip") for r in recs] == [r.get("skip") for r in _masolat])
_kevert = [dict(recs[2]), dict(recs[0]), dict(recs[1])]
for r in _kevert:
    r.pop("skip", None)
viz.mark_blocked(_kevert, BARS, "teszt")
check("kevert sorrendből is ugyanaz (időrendbe rakja)",
      [bool(r.get("skip")) for r in _kevert] == [False, True, False])

# ── 6. Adathiány: NE tiltson vaktában ─────────────────────────────────────
r6 = [{"t": _t(0), "d": "BUY", "e": 100.0, "sl": None, "tp": None},
      {"t": _t(5), "d": "BUY", "e": 100.0, "sl": 95.0, "tp": 130.0}]
check("SL nélküli rekord nem foglal le semmit",
      viz.mark_blocked(r6, BARS, "teszt") == 0)
r7 = [dict(recs[0]), dict(recs[1])]
for r in r7:
    r.pop("skip", None)
check("⚠ olvashatatlan bároknál NEM jelöl (a régi kép marad, de HANGOSAN)",
      viz.mark_blocked(r7, None, "teszt") == 0)

# ── 7. A RAJZ: a kimaradó jelzés ne nézzen ki kötésnek ────────────────────
_kot = viz.entry_marks({"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0,
                        "tp": 130.0, "lab": "TrPull BUY"})
_kim = viz.entry_marks({"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0,
                        "tp": 130.0, "lab": "TrPull BUY", "skip": 1})
check("a KÖTŐ jelölő változatlan (5 objektum)", len(_kot) == 5, f"{len(_kot)}")
check("⚠ a KIMARADÓ jelölő EGYETLEN vonal", len(_kim) == 1, f"{len(_kim)}")
check("⚠ ...és NINCS SL/TP/belépő vonala (az kötést sugallna)",
      not [o for o in _kim
           if str(getattr(o, "name", "")).startswith(("sl_", "tp_", "m1entry_"))])
check("⚠ ...és nincs CÍMKÉJE sem",
      not [o for o in _kim if str(getattr(o, "name", "")).startswith("m1lbl_")])
check("a kimaradó vonal SZÜRKE és vékony",
      _kim[0].color == "muted" and _kim[0].width == 1,
      f"{_kim[0].color}/{_kim[0].width}")
check("...a kötőé színes és vastag",
      _kot[0].color == "green" and _kot[0].width == 2)
check("⚠ a NEVE ugyanaz marad (az MT5 upsert-el: a szürkéből zöld LEHET, "
      "ha egy régebbi pozíció közben lezárt)",
      _kim[0].name == _kot[0].name, _kim[0].name)

# ── 8. A NAPLÓ is őrizze meg ──────────────────────────────────────────────
# ⚠ Enélkül az ablakon KÍVÜLI múlt megint úgy nézne ki, mintha minden
# jelzésből kötés lett volna.
from strategy import signal_journal as sj
_n = sj._norm({"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0, "skip": 1})
check("⚠ a napló megőrzi a `skip` jelölést", bool(_n) and _n.get("skip") == 1)
check("...és a `skip` a KIÍRT mezők között van", "skip" in sj._FIELDS)
_n2 = sj._norm({"t": _t(0), "d": "BUY", "e": 100.0, "sl": 95.0})
check("a kötő rekordban nincs fölösleges mező", _n2 is not None and "skip" not in _n2)

# ── 9. MINDEN rajzoló stratégia használja ─────────────────────────────────
# ⚠ Nem elég a `trend_pullback`-et javítani: ugyanez a félreolvasás a `wpr_sma`
# és a `bollinger_squeeze` chartján is megvolt.
for _f in ("trend_pullback.py", "wpr_sma.py", "bollinger_squeeze.py"):
    _src = (ROOT / "strategy" / _f).read_text(encoding="utf-8")
    if "viz.entry_marks(rec)" not in _src:
        continue
    check(f"{_f}: a kötne/kimarad jelölést KÉRI", "viz.mark_blocked(" in _src)

# ── 10. ÉLES ADATON: tényleg kevesebb a kötés, mint a jelzés ──────────────
_pq = ROOT / "data" / "m1" / "UsaTec.parquet"
if _pq.exists():
    from strategy import get_strategy_by_name
    from strategy.base import MarketData
    from strategy.settings import config_for_strategy, load_config
    from trading.live_trader import default_params, strategy_params
    SN, SYM = "trend_pullback", "UsaTec"
    st = get_strategy_by_name(SN)
    cfg = load_config("config.json")
    _cs = config_for_strategy(cfg, SN)
    p = strategy_params(SYM, SN, _cs, fallback=default_params(st, _cs))
    p = {**p, "symbol": SYM, "point_size": cfg["pairs"][SYM]["point_size"]}
    d1 = pd.read_parquet(_pq).tail(st.visual_lookback_bars(p, "M1"))
    d15 = pd.read_parquet(ROOT / "data" / "m15" / f"{SYM}.parquet").tail(
        st.visual_lookback_bars(p, "M15"))
    _r = []
    md = MarketData(symbol=SYM, params=p, bars={"M1": d1, "M15": d15})
    md.on_entry_record = _r.append
    objs = st.visual_objects(md)
    _kimarado = sum(1 for x in _r if x.get("skip"))
    check("éles adat: van jelzés", len(_r) > 0, f"{len(_r)} jelzés")
    check("⚠ éles adat: a jelzések egy része KIMARAD (ez volt a félreolvasás)",
          0 < _kimarado < len(_r),
          f"{len(_r) - _kimarado} kötne / {len(_r)} jelzés")
    # A rajzon is látszania kell: kevesebb SL-vonal, mint jelölő.
    _sig = [o for o in objs if str(getattr(o, "name", "")).startswith("m1sig")]
    _sl = [o for o in objs if str(getattr(o, "name", "")).startswith("sl_")]
    check("⚠ minden jelzésnek van vonala, de csak a KÖTŐKNEK van SL-je",
          len(_sig) == len(_r) and len(_sl) == len(_r) - _kimarado,
          f"{len(_sig)} vonal / {len(_sl)} SL")
else:
    print("      (nincs UsaTec M1 parquet — az éles adatos rész kimarad)")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
