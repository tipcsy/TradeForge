"""A szerver-eltolas IDOZONA-tulajdonsag, nem a tick kora.

⚠ A LELET (2026-08-15, SZOMBAT). A felhasznalo ujrainditotta a programot, es a
napi P&L a PENTEKI -14,88$-t hozta. A fejlecben a „broker-ora" penteken
22:59-en ALLT.

Ok: az eltolast `tick.time - most` adja, ami CSAK friss tick mellett az
idozona-eltolas. Zart piacon (hetvege, unnep) azt meri, MENNYI IDEJE nem jott
arajanlat — szombat 09:14 UTC-n a penteki utolso tickbol -10,24 ora.
Kovetkezmenyek:

  • a fejlec broker-oraja megall az utolso ticknel,
  • a `server_day_bounds` szerint a „mai" nap meg PENTEK,
  • a napi P&L a penteki osszeget mutatja ujrainditas utan is,
  • ⚠ es a NAPI VESZTESEGLIMIT kapuja ugyanezt a szamot nezi: hetfo reggel az
    elso tick elott a penteki vesztesegbol indulna.

A vedelem ket lepcsos:
  1. Egy broker idozona-eltolasa EGESZ ORA. Friss tickbol a nyers kulonbseg
     percre pontosan egesz ora; elavultbol tetszoleges -> csak az elsot fogadjuk el.
  2. A jo erteket ELTESSZUK lemezre, es egy uj meres legfeljebb 1 orat (oravaltas)
     terhet el tole — kulonben egy veletlenul egesz orara eso elavult tick
     feluliRNA a jot.
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


import datetime as dt

from core import mt5_connector as C

H = 3600.0


# ── 1. A KVANTALAS: mi szamit MERESNEK ───────────────────────────────────
_cases = [
    (3 * H - 12,      3 * H,  "friss tick, +3h zona (12 mp regi)"),
    (2 * H + 40,      2 * H,  "friss tick, +2h zona (40 mp regi)"),
    (-5 * H + 5,     -5 * H,  "negativ zona is jo"),
    (0.0,             0.0,    "UTC-broker"),
    (-10.24 * H,      None,   "PENTEKI tick szombaton (a valos eset)"),
    (3 * H + 600,     None,   "tick 10 perce — mar nem meres"),
    (-72 * H,         None,   "harom napja allo piac"),
    (20 * H,          None,   "irrealisan nagy"),
]
for raw, want, cim in _cases:
    got = C._quantize_offset(raw)
    ok = (got is None and want is None) or (got is not None and want is not None
                                            and abs(got - want) < 1)
    check(f"{cim:38s} ({raw / H:+6.2f}h)", ok,
          f"kapott={got if got is None else got / H}")


# ── 2. PERZISZTENCIA: a hetvegi indulas is tudja ─────────────────────────
# ⚠ A TESZT NEM IRHAT a valodi tarba: temp fajlra teritjuk.
import tempfile
_tmp = Path(tempfile.mkdtemp(prefix="offs_"))
_orig = C._offset_file
C._offset_file = lambda: _tmp / "server_offset.json"
try:
    C._server_offset["v"] = None
    check("meres nelkul nincs eltolas", C._load_offset() is None)
    C._save_offset(3 * H)
    C._server_offset["v"] = None                 # „ujraindult a program"
    check("ujraindulas utan a LEMEZROL jon", C._load_offset() == 3 * H,
          str(C._load_offset()))

    # ── 3. A NAP HATARA ezzel mar HELYES ─────────────────────────────────
    # Szombat 09:14 UTC + 3h = szombat 12:14 szerver -> a szerver-nap SZOMBAT.
    frm, to = C.server_day_bounds()
    _now_srv = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3 * H)
    check("a szerver-nap a BROKER naptara szerinti MAI nap",
          frm.date() == _now_srv.date() and (to - frm).days == 1,
          f"{frm.date()} -> {to.date()} (szerver most: {_now_srv.date()})")
    check("a szerver-datum is egyezik", C.server_today() == _now_srv.date(),
          f"{C.server_today()} vs {_now_srv.date()}")

    # ── 4. AZ UTOLSO RES: elavult tick, ami VELETLENUL egesz ora ─────────
    # ⚠ Hetvegen MINDEN tick elavult, es a kor veletlenul is eshet egesz ora
    # kozelebe. Egy broker idozonaja viszont legfeljebb ORAVALTASKOR mozdul,
    # azaz PONTOSAN 1 orat — ennel nagyobb ugrast nem hiszunk el.
    _prev = C._load_offset()
    for cand, elvart, cim in ((4 * H, True,  "oravaltas +1h"),
                              (2 * H, True,  "oravaltas -1h"),
                              (-10 * H, False, "hamis, elavult tickbol"),
                              (9 * H, False, "6 oras ugras")):
        _elfogad = abs(cand - _prev) <= 3600
        check(f"{cim:26s} ({cand / H:+.0f}h)", _elfogad == elvart,
              "elfogadva" if _elfogad else f"eldobva, marad {_prev / H:+.0f}h")
finally:
    C._offset_file = _orig
    C._server_offset["v"] = None
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)


# ── 5. A FORRAS: a meres tenyleg a kvantalt uton megy ────────────────────
import inspect
_src = inspect.getsource(C.server_offset_sec)
check("a server_offset_sec KVANTAL", "_quantize_offset(raw)" in _src)
check("...elavult ticknel a KORABBI erteket viszi tovabb",
      "_load_offset()" in _src, "")
check("...es nem irja felul a jot egy tavoli meressel",
      "abs(off - _prev) > 3600" in _src)
# A nap-hatar a PERZISZTALT erteket lassa (nem csak a memoriabelit).
for _fn in (C.server_day_bounds, C.server_today):
    check(f"a {_fn.__name__} a perzisztalt eltolast hasznalja",
          "_load_offset()" in inspect.getsource(_fn))


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
