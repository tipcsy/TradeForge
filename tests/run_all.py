"""
Az összes teszt lefuttatása egy paranccsal:

    python tests/run_all.py            # mind
    python tests/run_all.py package    # csak a névben illeszkedők

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


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(p for p in HERE.glob("test_*.py") if pattern in p.name)
    if not files:
        print(f"Nincs illeszkedő teszt: {pattern!r}")
        return 1

    total = passed = 0
    failed: list = []
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
        print(f"{'PASS' if ok else 'FAIL'}  {f.name:<32} {n}/{m}")
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
    print(f"{passed}/{total} allitas  |  {len(files) - len(failed)}/{len(files)} fajl PASS")
    if failed:
        print("BUKOTT: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
