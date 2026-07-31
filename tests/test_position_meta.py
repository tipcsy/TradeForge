"""A belepeskori kockazat (1 R) rogzitese — core/position_meta.py.

Az R alapja a belepeskor kockaztatott osszeg. Ez a nyitas pillanataban dol el es
UTOLAG NEM rekonstrualhato (a BE/trailing feluirja az SL-t, a pstate memoriabeli,
a lezart kotes R-je pedig a zaras utan is kell). Ezek a tesztek azt orzik, hogy a
szam helyesen keletkezik, tulel egy ujraindulast es egy lezarast.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import position_meta as pm

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def fresh_store():
    """Uj, ures tarolo egy temp fajlban — a VALODI data/position_meta.json-t
    sosem piszkaljuk (a test_hygiene ezt kulon is szamon kerne)."""
    tmp = Path(tempfile.mkdtemp()) / "position_meta.json"
    pm.PATH = tmp
    pm._state.clear()
    pm._loaded = True
    return tmp


# ══ 1. A kockazat-keplet ═══════════════════════════════════════════════════
# risk = lot × sl_points × pv1_point — ez a calc_lot megforditasa.

check("alap keplet: 0.5 lot x 200 pont x 0.88 = 88.0",
      abs(pm.risk_from_points(0.5, 200, 0.88) - 88.0) < 1e-9)
check("1 lot x 1 pont x 1 = 1.0",
      abs(pm.risk_from_points(1.0, 1, 1.0) - 1.0) < 1e-9)

# Ervenytelen bemenet -> 0.0 (a hivo ilyenkor NEM ir bejegyzest)
check("nulla lot -> 0.0", pm.risk_from_points(0, 200, 0.88) == 0.0)
check("nulla sl_points -> 0.0", pm.risk_from_points(0.5, 0, 0.88) == 0.0)
check("nulla pv1 -> 0.0", pm.risk_from_points(0.5, 200, 0) == 0.0)
check("negativ lot -> 0.0", pm.risk_from_points(-1, 200, 0.88) == 0.0)
check("None bemenet -> 0.0", pm.risk_from_points(None, 200, 0.88) == 0.0)
check("szoveg bemenet -> 0.0", pm.risk_from_points("x", 200, 0.88) == 0.0)

# ARAKBOL (kezi/orokbefogadott pozicio)
# GOLD: point_size 0.01, nyito 4000.00, SL 3998.00 -> 200 pont
check("arakbol: 2.00 ar-tav / 0.01 = 200 pont -> 88.0",
      abs(pm.risk_from_prices(0.5, 4000.00, 3998.00, 0.01, 0.88) - 88.0) < 1e-9)
check("az IRANY nem szamit (SELL: SL a nyito FOLOTT)",
      abs(pm.risk_from_prices(0.5, 4000.00, 4002.00, 0.01, 0.88) - 88.0) < 1e-9)

# ── A LEGFONTOSABB EL: stop nelkul NINCS ertelmezheto kockazat ──
check("SL=0 (nincs stop) -> 0.0, NEM kitalalt ertek",
      pm.risk_from_prices(0.5, 4000.00, 0.0, 0.01, 0.88) == 0.0)
check("SL=None -> 0.0",
      pm.risk_from_prices(0.5, 4000.00, None, 0.01, 0.88) == 0.0)
check("hianyzo point_size -> 0.0",
      pm.risk_from_prices(0.5, 4000.00, 3998.00, 0, 0.88) == 0.0)

# ══ 2. Rogzites es visszaolvasas ═══════════════════════════════════════════
fresh_store()

check("record() igazat ad ervenyes kockazatnal",
      pm.record(111, "GOLD", "wpr_sma", 15.0, lot=0.5, sl_points=200,
                entry_price=4000.0) is True)
check("risk_of() a rogzitett erteket adja", pm.risk_of(111) == 15.0)
check("ismeretlen ticket -> None", pm.risk_of(999) is None)
check("None ticket -> None", pm.risk_of(None) is None)

# ── 0 kockazat NEM kerul be: a 0-val valo osztas hamis vegtelen R-t adna ──
check("record() 0 kockazattal NEM ir be", pm.record(222, "GOLD", "wpr_sma", 0.0) is False)
check("...es tenyleg nincs bejegyzes", pm.risk_of(222) is None)
check("record() negativ kockazattal sem ir", pm.record(223, "GOLD", "x", -5.0) is False)

# ── A belepeskori adat EGYSZER keletkezik: nem irhato felul ──
check("meglevo ticket NEM irodik felul",
      pm.record(111, "GOLD", "wpr_sma", 999.0) is False)
check("...az eredeti ertek megmaradt", pm.risk_of(111) == 15.0)

# ══ 3. R-szamitas ══════════════════════════════════════════════════════════
# 15$ = 1R. Ha nyertem 1R-t az +15$, ha 2R-t az +30$.
check("+15$ nyereseg = +1.0 R", abs(pm.r_multiple(111, 15.0) - 1.0) < 1e-9)
check("+30$ nyereseg = +2.0 R", abs(pm.r_multiple(111, 30.0) - 2.0) < 1e-9)
check("-15$ veszteseg = -1.0 R", abs(pm.r_multiple(111, -15.0) + 1.0) < 1e-9)
check("+7.5$ = +0.5 R", abs(pm.r_multiple(111, 7.5) - 0.5) < 1e-9)
check("rogzitett kockazat nelkul az R None (a kijelzes '-' legyen)",
      pm.r_multiple(999, 30.0) is None)

# ══ 4. Perzisztencia — tuleli az ujraindulast ══════════════════════════════
tmp = pm.PATH
pm._state.clear()
pm._loaded = False          # mintha uj processz indulna
pm.load()
check("ujraindulas utan is megvan a kockazat", pm.risk_of(111) == 15.0)

raw = json.loads(tmp.read_text(encoding="utf-8"))
check("a fajlban a ticket a kulcs", "111" in raw)
check("a fajl a lotot is orzi", raw["111"].get("lot") == 0.5)
check("a fajl a strategiat is orzi", raw["111"].get("strategy") == "wpr_sma")

# ══ 5. Lezaras — a bejegyzes MEGMARAD ══════════════════════════════════════
# A lezart kotes R-je (napi P&L R-ben) csak ebbol szamolhato: a pozicio mar nincs.
pm.mark_closed(111)
check("lezaras utan is megvan a kockazat", pm.risk_of(111) == 15.0)
check("lezaras utan is szamolhato az R", abs(pm.r_multiple(111, 30.0) - 2.0) < 1e-9)
check("a bejegyzes kap closed_at-ot", bool(pm.meta_of(111).get("closed_at")))

# ══ 6. prune — a retencio ══════════════════════════════════════════════════
fresh_store()
pm.record(301, "GOLD", "wpr_sma", 10.0)
pm.record(302, "UK100", "ml_ai", 20.0)
pm.mark_closed(302)

# keep_days=0 -> SOHA ne torolj (a felhasznaloi keres szerint)
pm.prune(open_tickets={301}, keep_days=0)
check("keep_days=0 -> a lezart bejegyzes MEGMARAD", pm.risk_of(302) == 20.0)
check("keep_days=0 -> a nyitott is megmarad", pm.risk_of(301) == 10.0)

# A regi lezart bejegyzes eltunik, ha van retencio
_old = "2020-01-01T00:00:00+00:00"
pm._state["302"]["closed_at"] = _old
pm.prune(keep_days=3)
check("regi lezart bejegyzes torlodik keep_days=3 mellett", pm.risk_of(302) is None)
check("...a nyitott bejegyzes ERINTETLEN", pm.risk_of(301) == 10.0)

# A program allasa kozben zart pozicio: nincs a nyitottak kozt -> lezartkent jeloljuk
fresh_store()
pm.record(401, "GOLD", "wpr_sma", 12.0)
pm.prune(open_tickets=set(), keep_days=0)
check("a mar nem nyitott ticket lezartkent jelolodik",
      bool((pm.meta_of(401) or {}).get("closed_at")))
check("...de az erteke megmarad (keep_days=0)", pm.risk_of(401) == 12.0)

# ══ 7. Serult fajl nem dontheti le a programot ═════════════════════════════
tmp2 = Path(tempfile.mkdtemp()) / "position_meta.json"
tmp2.write_text("{ ez nem json", encoding="utf-8")
pm.PATH = tmp2
pm._state.clear()
pm._loaded = False
pm.load()
check("serult JSON -> ures allapot, nincs kivetel", pm.risk_of(111) is None)

# A 0/negativ kockazatu bejegyzest a betoltes is kiszuri (regi/serult fajlbol)
tmp3 = Path(tempfile.mkdtemp()) / "position_meta.json"
tmp3.write_text(json.dumps({
    "501": {"symbol": "GOLD", "strategy": "x", "risk_ccy": 0},
    "502": {"symbol": "GOLD", "strategy": "x", "risk_ccy": 11.0},
}), encoding="utf-8")
pm.PATH = tmp3
pm._state.clear()
pm._loaded = False
pm.load()
check("betolteskor a 0 kockazatu bejegyzes kiesik", pm.risk_of(501) is None)
check("...az ervenyes megmarad", pm.risk_of(502) == 11.0)

# ══ 7b. risk_of_closed — a "Lezart" ful R-jenek kockazat-forrasa ═══════════
# Ket forras: (1) a ROGZITETT ertek, (2) tartalek a NYITO ORDER SL-jebol. A
# tartalek a v1.81.0 ELOTT nyitott kotesekhez kell — enelkul az R-oszlop minden
# multbeli kotesnel kiurulne.
fresh_store()
_pc = {"point_size": 0.01, "pv1_point": 0.88}

# GOLD: 0.5 lot, nyito 4000, nyito-order SL 3998 -> 200 pont -> 88.0
_row = {"position": 700, "symbol": "GOLD", "volume": 0.5,
        "price_open": 4000.0, "sl": 3998.0, "pnl": 44.0}
check("tartalek: a nyito order SL-jebol szamol",
      abs(pm.risk_of_closed(_row, _pc) - 88.0) < 1e-9)

# A ROGZITETT ertek NYER a tartalek felett (az a pontos: nyitaskori pv1-gyel)
pm.record(700, "GOLD", "wpr_sma", 90.0)
check("a rogzitett ertek elonyt elvez a tartalekkal szemben",
      pm.risk_of_closed(_row, _pc) == 90.0)

# Stop nelkul nincs R — se rogzites, se hasznalhato SL
check("SL nelkuli kotes -> None (a ful '-'-t mutasson)",
      pm.risk_of_closed({"position": 701, "symbol": "GOLD", "volume": 0.5,
                         "price_open": 4000.0, "sl": 0.0}, _pc) is None)
check("hianyzo par-config -> None",
      pm.risk_of_closed({"position": 702, "symbol": "X", "volume": 0.5,
                         "price_open": 4000.0, "sl": 3998.0}, {}) is None)
check("nem-dict bemenet -> None", pm.risk_of_closed(None, _pc) is None)

# ── A PAJZS-ESET: emiatt allt at a ful a penz-alapu R-re ──
# Belepo 4000, SL 3990 (10 ar-egyseg). 1 lot, 1 ar-egyseg = 1$ -> kockazat 10$.
# 75% zarva 1R-nel (4010), a runner 3R-nel (4030).
#   realizalt penz: 0,75 x 10 + 0,25 x 30 = 15$  -> 1,5 R
#   az AR-alapu keplet a VEGSO 4030-cal szamolna -> 3,0 R  (KETSZERES tevedes)
fresh_store()
pm.record(800, "GOLD", "wpr_sma", 10.0)
_penz_r = pm.r_multiple(800, 15.0)
_ar_r = (4030.0 - 4000.0) / abs(4000.0 - 3990.0)
check("Pajzs: a penz-alapu R helyesen 1,5", abs(_penz_r - 1.5) < 1e-9,
      f"{_penz_r:.2f}R")
check("Pajzs: az AR-alapu 3,0 lett volna", abs(_ar_r - 3.0) < 1e-9, f"{_ar_r:.2f}R")
check("Pajzs: a ket definicio KETSZERES eltterest ad", abs(_ar_r / _penz_r - 2.0) < 1e-9)

# ══ 8. A PAROS modul (core/adopted.py) ugyanazt a retencios szabalyt koveti ═══
# A ket nyilvantartas retenciojat EGY config ertek vezerli, tehat a keep_days=0
# jelentesenek is azonosnak kell lennie — kulonben az egyik tarolo elveszitene a
# lezart kotesek adatat, a masik meg megtartana.
from core import adopted as ad

ad.PATH = Path(tempfile.mkdtemp()) / "adopted_positions.json"
ad._state.clear()
ad._loaded = True
ad.adopt(601, "wpr_sma", "GOLD")
ad.mark_closed(601)
ad._state["601"]["closed_at"] = "2020-01-01T00:00:00+00:00"

ad.prune(keep_days=0)
check("adopted: keep_days=0 -> a regi lezart bejegyzes is MEGMARAD",
      ad.strategy_of(601) == "wpr_sma")
ad.prune(keep_days=3)
check("adopted: keep_days=3 -> a regi lezart bejegyzes torlodik",
      ad.strategy_of(601) is None)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
