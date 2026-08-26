"""
Az összes teszt lefuttatása egy paranccsal:

    python tests/run_all.py                  # mind
    python tests/run_all.py package          # csak a névben illeszkedők
    python tests/run_all.py --no-live-data   # az éles adatot igénylők nélkül

Nincs pytest-függés: minden teszt önálló szkript, ami a végén `0`/`1` kilépési
kóddal tér vissza, és kiírja a saját `n/m teszt PASS` sorát. Ez a futtató csak
összesít — így egy teszt önmagában is futtatható (`python tests/test_x.py`),
ami hibakeresésnél a leggyorsabb út.

KÜLÖN PROCESSZBEN futnak: több teszt modul-szintű globális állapotot állít
(pl. `core.opt_activity`, `set_active_strategy`), és egy közös processzben
ezek átszivárognának egymásba — ami a legrosszabb fajta hiba: a tesztek
sorrendtől függően buknának.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# A Windows-konzol cp1250: az ékezetes összesítő sor különben elszáll/torzul.
sys.path.insert(0, str(ROOT))
try:
    from core import applog
    applog.harden_console()
except Exception:
    pass


# ⚠⚠ A TESZT SOHA NE ÍRJA A FELHASZNÁLÓ ÁLLAPOTÁT.
#
# Ez a projektben már HÁROMSZOR megtörtént: `run_mode` a `backtest_prefs.json`-ba,
# `shield_fraction` a `risk_mode.json`-ba, és 2026-08-18-án a legsúlyosabb — egy
# valódi `DashboardWindow`-t építő teszt 2 páros dummy configja RÁÍRÓDOTT a 10
# páros ÉLES `config.json`-ra. Mentés nem volt; a helyreállítás csak azért
# sikerült, mert a program épp futott, és a memóriájából vissza tudta írni.
#
# Az egyes tesztekben elhelyezett csonkok NEM elég erősek: minden új hívási út
# (Play/Stop, slot, kapu-kapcsoló, automatikus leállítás) megkerülheti őket.
# Ezért a FUTTATÓ őrzi az éles fájlokat: lenyomat előtte, ellenőrzés utána — és
# ha bármi megváltozott, HANGOSAN szól, a bűnös fájl nevével.
_GUARDED = ("config.json", "data/backtest_prefs.json", "data/risk_mode.json")


def _fingerprint() -> dict:
    import hashlib
    out = {}
    for rel in _GUARDED:
        f = ROOT / rel
        try:
            out[rel] = hashlib.sha1(f.read_bytes()).hexdigest() if f.exists() else None
        except Exception:
            out[rel] = "?"
    return out


def _app_fut() -> bool:
    """Fut-e ÉPPEN a TradeForge? Ha igen, a „bepiszkolt" fájlokat NAGY
    valószínűséggel Ő írta, nem a teszt.

    ⚠ EZ NEM KOZMETIKA. Az őr azt a tesztet nevezi meg, amelyik épp FUTOTT,
    amikor az eltérést ÉSZREVETTE — nem azt, aki írt. Ha közben él az
    alkalmazás (ami a `config.json`-ba menti a Play/Stop állapotot és a
    slot-számot), az őr ártatlan teszteket vádol. Megtörtént 2026-08-25-én
    kétszer, két KÜLÖNBÖZŐ tesztre. Egy tévesen riasztó őrt pedig egy idő után
    figyelmen kívül hagy az ember — pont azt veszítenénk el, amiért készült.

    A jel: a viz-szál 30 másodpercenként ír; ha bármelyik `TFV_*.csv` frissebb
    két percnél, az alkalmazás él. Nincs hozzá se processz-lista, se új
    függőség."""
    try:
        import time
        from core.mt5_visual import PREFIX, files_dir
        d = files_dir()
        if d is None:
            return False
        most = time.time()
        return any(most - f.stat().st_mtime < 120
                   for f in d.glob(PREFIX + "*.csv"))
    except Exception:
        return False


def _skiplist() -> dict:
    """A `requires_live_data.txt` tartalma: fájlnév → indok.

    Ezek a tesztek a felhasználó ÉLES `config.json`-jából és `data/` mappájából
    dolgoznak, amik a `.gitignore`-ban vannak. Egy friss klónon (tehát a CI-ben)
    nincs mit mérniük, ezért — a projekt szabálya szerint — hangosan buknak.
    A `--no-live-data` kapcsoló ezeket kihagyja, de KIÍRJA: a csendes kihagyás
    pont annyira káros, mint a csendes átmenés."""
    out = {}
    f = HERE / "requires_live_data.txt"
    if not f.exists():
        return out
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        name, _, why = ln.partition("#")
        out[name.strip()] = why.strip()
    return out


def main() -> int:
    args = [a for a in sys.argv[1:]]
    no_live = "--no-live-data" in args
    if no_live:
        args.remove("--no-live-data")
    pattern = args[0] if args else ""
    files = sorted(p for p in HERE.glob("test_*.py") if pattern in p.name)
    if not files:
        print(f"Nincs illeszkedő teszt: {pattern!r}")
        return 1

    skipped: list = []
    if no_live:
        _skip = _skiplist()
        keep = []
        for f in files:
            if f.name in _skip:
                skipped.append((f.name, _skip[f.name]))
            else:
                keep.append(f)
        files = keep
        for _n, _w in skipped:
            print(f"SKIP  {_n:<32} {_w}")
        if not files:
            print("Minden illeszkedő teszt kihagyva.")
            return 1

    _before = _fingerprint()
    total = passed = 0
    failed: list = []
    _dirty: dict = {}          # fájl → az a teszt, ami után elváltozott
    for f in files:
        # PYTHONIOENCODING: a gyerek-processz stdoutja cso, amit a Python a
        # LOCALE szerint kodol (Windowson cp1250) — egy ekezeten tuli karakter
        # (pl. ⚠) ott UnicodeEncodeError-t dobna, es a teszt a HIBAJA HELYETT
        # kodolasi hibaval bukna. Itt fentrol rendezzuk, minden teszthez.
        import os
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, str(f)], cwd=str(ROOT), env=env,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        # Az utolsó „n/m teszt PASS" sor az összesítő
        line = next((ln for ln in reversed(out.splitlines()) if "teszt PASS" in ln), "")
        n = m = 0
        if line:
            try:
                n, m = (int(x) for x in line.split()[0].split("/"))
            except Exception:
                pass
        total += m
        passed += n
        ok = (r.returncode == 0)
        # ⚠ AZONNAL ellenőrzünk, hogy a BŰNÖS teszt neve derüljön ki — a végén
        # már csak azt tudnánk, hogy „valamelyik".
        _now = _fingerprint()
        for _rel, _h in _now.items():
            if _h != _before[_rel] and _rel not in _dirty:
                _dirty[_rel] = f.name
                _before[_rel] = _h            # hogy a többi tesztre ne áradjon
        print(f"{'PASS' if ok else 'FAIL'}  {f.name:<32} {n}/{m}"
              + ("   ⚠ ÍRTA AZ ÉLES ÁLLAPOTOT" if f.name in _dirty.values() else ""))
        if not ok:
            failed.append(f.name)
            # A bukott ÁLLÍTÁSOK sorai — enélkül újra kellene futtatni kézzel
            for ln in out.splitlines():
                if ln.startswith("FAIL") or "Traceback" in ln:
                    print(f"        {ln}")
            tail = out.strip().splitlines()[-3:]
            if any("Traceback" in ln for ln in out.splitlines()):
                for ln in tail:
                    print(f"        {ln}")

    # Az osszesito sor SZANDEKOSAN ekezet nelkuli: a Windows-konzol cp1250, es a
    # tobbi teszt kimenete is ezt a konvenciot koveti. Igy sehol nem torzul.
    print("-" * 52)
    if _dirty:
        # ⚠ Ez NEM stilisztikai kifogas: az eles config felulirasa adatvesztes.
        _el = _app_fut()
        if _el:
            print("!! A FELHASZNALO ALLAPOTA MEGVALTOZOTT — de KOZBEN FUT A "
                  "TRADEFORGE:")
        else:
            print("!! A TESZTEK MEGVALTOZTATTAK A FELHASZNALO ALLAPOTAT:")
        for _rel, _who in _dirty.items():
            print(f"     {_rel}  <-  a(z) {_who} futasa kozben")
        if _el:
            print("   ⚠ A futo alkalmazas maga is irja ezeket (Play/Stop, "
                  "slot-szam, kockazati mod), tehat a megnevezett teszt")
            print("     VALOSZINULEG ARTATLAN. Biztos itelethez zard be a "
                  "TradeForge-ot, es futtasd ujra a csomagot.")
        else:
            print("   A tesztnek a ROOT-ot ideiglenes mappara kell teritenie "
                  "(lasd test_live2_wiring.py).")
    print(f"{passed}/{total} allitas  |  {len(files) - len(failed)}/{len(files)} fajl PASS"
          + (f"  |  {len(skipped)} kihagyva (eles adat kell)" if skipped else ""))
    if failed:
        print("BUKOTT: " + ", ".join(failed))
    # ⚠ Az éles állapot felülírása ÖNMAGÁBAN bukás — akkor is, ha minden
    # állítás átment. Az adatvesztés nem „figyelmeztetés".
    #
    # ⚠ KIVÉVE, ha közben FUT az alkalmazás: akkor nem tudjuk eldönteni, ki
    # írt, és egy ártatlan tesztre adott bukás pont a bizalmat rombolná az
    # őrben. Ilyenkor a figyelmeztetés marad, a kilépési kód nem.
    return 1 if (failed or (_dirty and not _app_fut())) else 0


if __name__ == "__main__":
    sys.exit(main())
