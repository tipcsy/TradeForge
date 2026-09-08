"""A futásidejű POZÍCIÓ-REKORDNAK egy gazdája van (v3.57.0).

⚠ A LELET (2026-09-08). A `live_trader.position_state[ticket]` szótárt ÖT helyen
hoztuk létre, két modulban, és mindenhol `setdefault`-tal — vagyis **aki előbb
ér oda, az nyer**, a többi már nem javít rajta. Az öt alak nem is egyezett:

    live_trader:2201  (no-trade ág)   6 kulcs, original_sl = pos.sl
    live_trader:2422  (process_pair)  6 kulcs, original_sl = pos.sl
    live_trader:3553  (csomag-stop)   {}  ← ÜRES szótár
    gui:5796          (kézi BE)       5 kulcs, entry_atr nélkül
    gui:5849          _DEFAULT_PSTATE 5 kulcs, original_sl = 0.0  ← !!

⚠ ÉS VOLT ELÉRHETŐ ÚT, AHOL A FELÜLET NYER. A `process_pair` csak `LIVE`/
`CLOSING` páron fut (`live_trader.py`, a fő ciklus). Egy STOPPED páron nyitva
maradt (vagy örökbefogadott) pozíciónál tehát a Pozíciók fül trailing-kapcsolója
hozza létre a rekordot — `original_sl = 0.0`-val. A motor `setdefault`-ja utána
MÁR TALÁL bejegyzést, tehát a valódi stopot SOHA nem írja bele: az a pozíció
élete végéig hibás 1 R-rel fut (a BE-küszöb, a Felező/Pajzs triggere és a
Harmados szintjei mind ebből számolnak).

A GYÖKÉR: a `0.0` KÉT dolgot jelentett egyszerre — „nincs stop" és „nem tudjuk".
Most szétválik: az ISMERETLEN az `None`.

A JAVÍTÁS LÉNYEGE nem az egységes alak, hanem hogy az ismeretlen eredeti stop
KÉSŐBB PÓTOLHATÓ (`pstate.ensure`) — így mindegy, ki ér oda előbb.
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


from core import pstate as ps


# ══ 1. A 0.0 NEM ár: az ismeretlen az None ═══════════════════════════════
for bad, cimke in ((0, "0"), (0.0, "0.0"), (None, "None"), (-1.2, "negatív"),
                   ("x", "nem szám"), ("", "üres")):
    check(f"normalise_sl({cimke}) → None", ps.normalise_sl(bad) is None)
check("normalise_sl(érvényes ár) → az ár", ps.normalise_sl(1.1950) == 1.1950)
check("...stringből is", ps.normalise_sl("1.195") == 1.195)


# ══ 2. A rekord TELJES alakja egy helyen ═════════════════════════════════
r = ps.new()
check("a new() minden mezőt megad", set(r) == set(ps.FIELDS), str(sorted(r)))
check("⚠ az ismeretlen eredeti stop None (nem 0.0)", r["original_sl"] is None)
check("a trailing alapból BE", r["trailing_enabled"] is True)
check("a be_done alapból KI", r["be_done"] is False)
check("az entry_atr 0.0 (a motor tölti fel)", r["entry_atr"] == 0.0)
check("⚠ a 0.0-s stop is ISMERETLEN lesz (MT5: nincs stop)",
      ps.new(original_sl=0.0)["original_sl"] is None)
check("...az érvényes viszont megmarad",
      ps.new(original_sl=1.195)["original_sl"] == 1.195)


# ══ 3. ensure(): létrehoz, KIEGÉSZÍT, és PÓTOL ═══════════════════════════
store = {}
a = ps.ensure(store, 1, original_sl=1.1950)
check("ensure: új rekord a tárolóba került", store.get(1) is a)
check("...és teljes", set(a) == set(ps.FIELDS))
check("...az eredeti stoppal", a["original_sl"] == 1.1950)

# CSONKA rekord (ezt adta a csomag-stop `{}`-je) → kiegészül
store[2] = {"be_done": True}
b = ps.ensure(store, 2)
check("⚠ a CSONKA rekord kiegészül (a csomag-stop üres szótára)",
      set(b) == set(ps.FIELDS), str(sorted(b)))
check("...és a meglévő értéket NEM írja felül", b["be_done"] is True)

# ⚠ A LELET MAGA: a FELÜLET ér oda előbb, a MOTOR később pótol
store3 = {}
gui_rec = ps.ensure(store3, 3)                     # Pozíciók fül: trailing kapcsoló
gui_rec["trailing_enabled"] = False
check("⚠ a felület által létrehozott rekord eredeti stopja ISMERETLEN",
      gui_rec["original_sl"] is None)
motor_rec = ps.ensure(store3, 3, original_sl=1.2050, be_done=False)   # Play → motor
check("⚠⚠ A JAVÍTÁS: a motor PÓTOLJA az ismeretlen eredeti stopot",
      motor_rec["original_sl"] == 1.2050, str(motor_rec["original_sl"]))
check("...ugyanaz a rekord (a felület beállítása megmarad)",
      motor_rec is gui_rec and motor_rec["trailing_enabled"] is False)

# ...de az ISMERTET soha nem írja felül (a stop menet közben elmozdul)
moved = ps.ensure(store3, 3, original_sl=1.2090)
check("⚠ az ISMERT eredeti stopot SOHA nem írja felül (BE/trailing elmozdítja)",
      moved["original_sl"] == 1.2050, str(moved["original_sl"]))

# A be_done — mint a régi setdefault — csak LÉTREHOZÁSKOR számít
store4 = {}
ps.ensure(store4, 4, original_sl=1.0, be_done=True)
check("be_done=True létrehozáskor érvényesül", store4[4]["be_done"] is True)
ps.ensure(store4, 4, be_done=False)
check("...meglévő rekord jelölését NEM billenti vissza (visszafelé kompatibilis)",
      store4[4]["be_done"] is True)


# ══ 4. one_r_price: 0.0 = NEM TUDHATÓ ════════════════════════════════════
check("ismert eredeti stopból",
      abs(ps.one_r_price(1.2000, {"original_sl": 1.1950}) - 0.0050) < 1e-9)
check("az ELMOZDÍTOTT stop nem számít (az eredeti nyer)",
      abs(ps.one_r_price(1.2000, {"original_sl": 1.1950}, 1.1990) - 0.0050) < 1e-9)
check("ismeretlen eredeti → a MOSTANI stop a közelítés",
      abs(ps.one_r_price(1.2000, {}, 1.1950) - 0.0050) < 1e-9)
check("⚠ ismeretlen eredeti ÉS nincs stop (sl=0) → 0.0, NEM a nyitóár",
      ps.one_r_price(1.2000, {}, 0.0) == 0.0)
check("...üres/None rekorddal is", ps.one_r_price(1.2000, None, 0.0) == 0.0)
check("⚠ a régi képlet itt a NYITÓÁRAT adta volna",
      abs(1.2000 - 0.0) == 1.2000, "|nyitóár − 0| = nyitóár")

check("original_sl(): a rekordé nyer", ps.original_sl({"original_sl": 1.1}, 1.9) == 1.1)
check("original_sl(): ismeretlennél a mostani", ps.original_sl({}, 1.9) == 1.9)
check("original_sl(): ha az sem, None", ps.original_sl({}, 0.0) is None)


# ══ 5. EGY GAZDA: a régi teremtők eltűntek ═══════════════════════════════
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")

check("⚠ SEHOL nincs több `position_state.setdefault`",
      "position_state.setdefault" not in _lt
      and "position_state.setdefault" not in _gui)
_kod_gui = [ln for ln in _gui.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
check("⚠ a felületnek NINCS saját rekord-alakja (_DEFAULT_PSTATE)",
      not [ln for ln in _kod_gui if "_DEFAULT_PSTATE" in ln],
      str([ln.strip()[:40] for ln in _kod_gui if "_DEFAULT_PSTATE" in ln]))
check("mindhárom motor-teremtő az ensure-t hívja",
      _lt.count("_pst.ensure(position_state") == 3,
      f"{_lt.count('_pst.ensure(position_state')} db")
check("és mindhárom felületi is",
      _gui.count("_pst.ensure(position_state") == 3,
      f"{_gui.count('_pst.ensure(position_state')} db")
check("⚠ a felület a KÖZÖS olvasót használja az 1 R-hez",
      "_pst.original_sl(pstate, sl)" in _gui)
check("⚠ a kézzel írt `.get(\"original_sl\", ...)` alak sehol",
      'get("original_sl", sl)' not in _gui and 'get("original_sl", pos.sl)' not in _lt)

# A motor burkolata tényleg a közös függvényre mutat.
import trading.live_trader as lt


class _P:
    def __init__(self, sl, po=1.2000):
        self.price_open, self.sl = po, sl


check("a live_trader._one_r_price a közös függvényt hívja",
      "_pst.one_r_price(" in _lt)
check("...és ugyanazt adja", lt._one_r_price(_P(1.1950), {}) == ps.one_r_price(
    1.2000, {}, 1.1950))
check("⚠ stop nélküli pozíción 0.0 (a regresszió)", lt._one_r_price(_P(0.0), {}) == 0.0)

# A `core` nem függhet a `trading`-től (réteg-szabály).
_pst_src = (ROOT / "core" / "pstate.py").read_text(encoding="utf-8")
check("⚠ a core.pstate NEM importál trading/dashboard modult",
      "import trading" not in _pst_src and "import dashboard" not in _pst_src
      and "from trading" not in _pst_src and "from dashboard" not in _pst_src)

print()
n, m = sum(results), len(results)
print(f"{n}/{m} teszt PASS")
sys.exit(0 if n == m else 1)
