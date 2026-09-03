"""MEGBÍZÁS-HIBÁK: egyszer elmondva, aztán összegezve.

⚠ A LELET (2026-09-03). A felület azt írta: „43 hiba a naplóban". Mind a 43
UGYANAZ volt: `UsaInd`, `lot=0.05`, `retcode=10019 No money`, kilenc perc alatt
(16:48:51 → 16:57:29). A motor körönként újra megpróbálta ugyanazt a megbízást,
a bróker pedig minden alkalommal fedezethiánnyal utasította el.

A szám IGAZ volt, de egyetlen helyzetet írt le negyvenháromszor — és pontosan
azt nyomta volna el, ami tényleg új. Egy hibaszámláló, amit a felhasználó
megszokik figyelmen kívül hagyni, rosszabb, mintha nem lenne.

⚠ NEM ELNÉMÍTÁS. A projekt szabálya az ellenkezője: a néma hiba a legdrágább
(lásd `silent-thread-death`). Amit teszünk:

  * az ELSŐ előfordulás `ERROR`, a teljes részlettel ÉS egy emberi
    magyarázattal (a puszta retcode nem mondja meg, mit lehet kezdeni vele);
  * az ismétlődés `DEBUG`;
  * negyedóránként egy `WARNING`-összegzés a darabszámmal — így a helyzet nem
    tűnik el, ha tartósan fennáll;
  * fedezethiánynál SZÜNET, mert a fedezet nem lesz több tizenkét másodperc
    alatt. ⚠ Szünet, NEM végleges tiltás: az egyenleg változhat.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from trading import live_trader as lt


class _Fog(logging.Handler):
    """A modul naplóját fogjuk el — a MÉRÉS az, hogy milyen SZINTEN szólal meg."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.sorok = []

    def emit(self, r):
        self.sorok.append((r.levelno, r.getMessage()))


_h = _Fog()
lt.log.addHandler(_h)
_regi = lt.log.level
lt.log.setLevel(logging.DEBUG)
logging.disable(logging.NOTSET)

try:
    lt._ORDER_HIBA.clear()
    lt._FEDEZET_SZUNET.clear()

    # ── 1. AZ ELSŐ hiba ERROR, a magyarázattal ───────────────────────────
    lt._order_hiba_jelent("UsaInd", 10019, "retcode=10019 No money | lot=0.05")
    _err = [m for lv, m in _h.sorok if lv >= logging.ERROR]
    check("az első előfordulás ERROR", len(_err) == 1, str(len(_err)))
    check("...és EMBERI magyarázatot is ad (nem csak a kódot)",
          "fedezet" in _err[0].lower(), _err[0][:90])

    # ── 2. AZ ISMÉTLŐDÉS csak DEBUG ──────────────────────────────────────
    _h.sorok.clear()
    for _ in range(42):
        lt._order_hiba_jelent("UsaInd", 10019, "retcode=10019 No money | lot=0.05")
    _szintek = {lv for lv, _ in _h.sorok}
    check("a további 42 ismétlés NEM ERROR", logging.ERROR not in _szintek,
          str(sorted(_szintek)))
    check("...és nem is WARNING (még nem telt le a negyedóra)",
          logging.WARNING not in _szintek, str(sorted(_szintek)))
    check("az ismétlődés SZÁMLÁLÓDIK",
          lt._ORDER_HIBA[("UsaInd", 10019)]["db"] == 43,
          str(lt._ORDER_HIBA[("UsaInd", 10019)]["db"]))

    # ── 3. NEGYEDÓRÁNKÉNT összegzés — a helyzet nem tűnik el ─────────────
    # ⚠ Ez a különbség az elnémítás és a szűrés között. Ha tartósan fennáll,
    # újra meg kell szólalnia.
    _h.sorok.clear()
    lt._ORDER_HIBA[("UsaInd", 10019)]["jelentve"] -= lt.ORDER_HIBA_JELENTES_MP + 1
    lt._order_hiba_jelent("UsaInd", 10019, "retcode=10019 No money | lot=0.05")
    _warn = [m for lv, m in _h.sorok if lv == logging.WARNING]
    check("negyedóra után ÖSSZEGZŐ figyelmeztetés", len(_warn) == 1, str(len(_warn)))
    check("...és benne van a DARABSZÁM", "44" in _warn[0], _warn[0][:100])

    # ── 4. MÁS pár / MÁS retcode KÜLÖN hiba ──────────────────────────────
    # ⚠ Enélkül egy ÚJ probléma a régi ismétlésének látszana.
    _h.sorok.clear()
    lt._order_hiba_jelent("Ger40", 10019, "retcode=10019 No money")
    lt._order_hiba_jelent("UsaInd", 10016, "retcode=10016 Invalid stops")
    check("másik pár ugyanazzal a kóddal: ÚJ hiba (ERROR)",
          sum(1 for lv, _ in _h.sorok if lv >= logging.ERROR) == 2,
          str([lv for lv, _ in _h.sorok]))

    # ── 5. FEDEZET-SZÜNET ────────────────────────────────────────────────
    check("a fedezet-hiba kódja fel van sorolva", 10019 in lt.FEDEZET_RETCODE)
    check("a szünet HOSSZA értelmes (percek, nem másodpercek)",
          lt.FEDEZET_SZUNET_MP >= 300, str(lt.FEDEZET_SZUNET_MP))

    # ⚠ SZÜNET, NEM VÉGLEGES TILTÁS: az egyenleg változhat (zár egy pozíció).
    _src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
    check("a szünet LEJÁR (nem örökös tiltás)",
          "time.time() < _szunet" in _src)
    check("a sikeres megbízás TÖRLI a szünetet",
          "_order_hiba_rendben(symbol)" in _src
          and "_FEDEZET_SZUNET.pop(symbol, None)" in _src)

    # ── 6. A SIKER törli a hiba-állapotot ────────────────────────────────
    lt._FEDEZET_SZUNET["UsaInd"] = time.time() + 999
    lt._order_hiba_rendben("UsaInd")
    check("siker után nincs UsaInd hiba-állapot",
          not any(k[0] == "UsaInd" for k in lt._ORDER_HIBA)
          and "UsaInd" not in lt._FEDEZET_SZUNET)
    check("...de a MÁSIK pár állapota megmarad",
          ("Ger40", 10019) in lt._ORDER_HIBA)
finally:
    lt.log.removeHandler(_h)
    lt.log.setLevel(_regi)
    lt._ORDER_HIBA.clear()
    lt._FEDEZET_SZUNET.clear()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
