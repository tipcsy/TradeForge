"""A KIÍRT verzió és a commit-üzenetben hirdetett verzió nem csúszhat szét.

⚠ A LELET (2026-09-02). A `version.py` **öt funkción keresztül** nem emelkedett:
3.10.1-en állt, miközben a commitok sorra v3.11.0, v3.11.1, v3.12.0, v3.13.0,
v3.14.0, v3.15.0-t hirdettek. A drift a `6c5bba5` (v3.10.2) commitnál kezdődött,
és nyolc commiton át észrevétlen maradt.

Miért fájt: a verzió a felület fejlécében LÁTSZIK, és pontosan arra való, hogy
meg tudd mondani, melyik build fut. Ha az ablakcím makacsul „v3.10.1"-et ír,
miközben öt új funkció van benne, akkor a szám nem információ, hanem zaj — és
egy hibabejelentésnél a rossz verzió rossz irányba viszi a keresést.

⚠ Ez a fajta hiba SOSEM bukik meg magától: minden működik, semmi nem dob
kivételt, a teszt-készlet zöld. Csak a kijelzés hazudik. Ezért kell őr.

── A SZABÁLYOK ────────────────────────────────────────────────────────────
1. Ha a HEAD commit ÜZENETE hirdet verziót `(vX.Y.Z)` alakban, akkor a HEAD-en
   lévő `version.py`-nak UGYANAZT kell mondania. Nem a munkafát nézzük: az a
   következő commit előkészítése, ott az eltérés természetes.
2. A verzió nem mehet VISSZAFELÉ a szülőhöz képest.
3. A munkafa verziója legalább akkora, mint a legutóbbi commitokban hirdetett
   legnagyobb — ez fogja meg a fenti driftet akkor is, ha valaki a HEAD-et
   verziószám nélküli üzenettel írja.

Nem git-repóban (kicsomagolt forrás, EXE-build) a teszt KIHAGYJA magát: az őr
hiánya ne akadályozza a futtatást ott, ahol nincs mit őrizni.
"""
import re
import subprocess
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


# ⚠ A ZÁRÓ zárójelhez kötjük, nem a nyitóhoz. Az első próbám `\(v...\)`-t
# keresett, és így a projekt SAJÁT szokásos alakját hagyta ki:
#   „Kezi laboratorium: ... (3. pont / 1. lepcso, v3.15.0)"
# — ott a `(` nem a `v` előtt áll. Az őr erre azt mondta volna, hogy „a HEAD
# nem hirdet verziót", és NÉMÁN nem őrzött volna semmit. A záró zárójel viszont
# mindkét alakban ott van, a szövegbeli „v4"-et pedig továbbra sem fogja meg
# (nincs benne pont, és nem zárójel követi).
# A verzio a targysor VEGEN is allhat zarojel nelkul: „… — v3.22.0".
# ⚠ EZ MAGA IS LELET (2026-09-03): a sajat commitom epp igy nezett ki, a minta
# pedig zaro zarojelhez kototte — az or CSENDBEN kihagyta az 1. szabalyt, es
# 8 helyett 7 ellenorzest futtatott. Csak a darabszam arulta el. Egy or, ami
# nemán kevesebbet ellenoriz, rosszabb annal, mint amelyik hangosan hibazik.
UZENET_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?=\)|\s*$)")
FORRAS_RE = re.compile(r'APP_VERSION\s*=\s*["\'](\d+)\.(\d+)\.(\d+)["\']')


def _verzio_szovegbol(szoveg: str, minta: re.Pattern):
    m = minta.search(szoveg or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _v(t) -> str:
    return ".".join(str(x) for x in t) if t else "—"


def _git(*args) -> "str | None":
    """Git-kimenet, vagy `None` ha nincs git / nem repó."""
    try:
        k = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return k.stdout if k.returncode == 0 else None


# ── 0. Az őr maga ─────────────────────────────────────────────────────────
# ⚠ Egy mintaillesztő, amit nem próbáltunk ki, csendben mindenre nemet mondhat
# — és akkor az őr örökké zöld, miközben nem őriz semmit.
check("az üzenet-minta felismeri a `(v3.16.0)` alakot",
      _verzio_szovegbol("Valami jo dolog (v3.16.0)", UZENET_RE) == (3, 16, 0))
check("...és a projekt másik alakját is: `(..., v3.15.0)`",
      _verzio_szovegbol("Kezi laboratorium (3. pont / 1. lepcso, v3.15.0)",
                        UZENET_RE) == (3, 15, 0))
check("...és a targysor VEGEN allo alakot is: `— v3.22.0`",
      _verzio_szovegbol("Kezi labor: lejatszas (BID/ASK) — v3.22.0",
                        UZENET_RE) == (3, 22, 0))
check("...és NEM harap rá a szövegbeli „v4\"-re",
      _verzio_szovegbol("a BacktestReplayer v4 azert keszult", UZENET_RE) is None)
check("a forrás-minta kiolvassa az APP_VERSION-t",
      _verzio_szovegbol('APP_VERSION = "3.16.0"', FORRAS_RE) == (3, 16, 0))

# ── 1. A munkafa verziója ─────────────────────────────────────────────────
_munkafa = _verzio_szovegbol((ROOT / "version.py").read_text(encoding="utf-8"),
                             FORRAS_RE)
check("a version.py-ban van értelmezhető APP_VERSION", _munkafa is not None,
      _v(_munkafa))

_fej = _git("rev-parse", "HEAD")
if _fej is None:
    print("KIHAGYVA: nincs git-repó — a commit-üzenetekhez kötött szabályok "
          "nem ellenőrizhetők.")
else:
    # ── 2. HEAD üzenete ↔ HEAD version.py-ja ──────────────────────────────
    _uzenet = _git("log", "-1", "--format=%s") or ""
    _hirdetett = _verzio_szovegbol(_uzenet, UZENET_RE)
    _fej_forras = _git("show", "HEAD:version.py") or ""
    _fej_verzio = _verzio_szovegbol(_fej_forras, FORRAS_RE)

    if _hirdetett is None:
        print("MEGJEGYZÉS: a HEAD üzenete nem hirdet verziót — az 1. szabály "
              "nem alkalmazható.")
    else:
        check("a HEAD üzenetében hirdetett verzió = a HEAD version.py-ja",
              _hirdetett == _fej_verzio,
              f"üzenet {_v(_hirdetett)} / version.py {_v(_fej_verzio)}")

    # ── 3. A verzió nem megy visszafelé ───────────────────────────────────
    _szulo = _git("rev-parse", "HEAD~1")
    if _szulo is None:
        print("MEGJEGYZÉS: nincs szülő commit (első commit / sekély klón).")
    else:
        _sz_verzio = _verzio_szovegbol(_git("show", "HEAD~1:version.py") or "",
                                       FORRAS_RE)
        if _sz_verzio and _fej_verzio:
            check("a verzió nem csökkent a szülőhöz képest",
                  _fej_verzio >= _sz_verzio,
                  f"{_v(_sz_verzio)} → {_v(_fej_verzio)}")

    # ── 4. A DRIFT maga: a munkafa nem maradhat le az üzenetek mögött ──────
    # ⚠ EZ AZ A SZABÁLY, AMI A LELETET ELKAPTA VOLNA. A `6c5bba5` óta minden
    # commit nagyobb verziót hirdetett, mint amit a program kiírt.
    _log = _git("log", "-40", "--format=%s") or ""
    _emlitett = [v for v in (_verzio_szovegbol(s, UZENET_RE)
                             for s in _log.splitlines()) if v]
    if _emlitett:
        _max = max(_emlitett)
        check("a version.py nem maradt le a commit-üzenetek mögött",
              _munkafa is not None and _munkafa >= _max,
              f"version.py {_v(_munkafa)} / üzenetekben {_v(_max)}")
    else:
        print("MEGJEGYZÉS: az utolsó 40 commit egyike sem hirdet verziót.")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
