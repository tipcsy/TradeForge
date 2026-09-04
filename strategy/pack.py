"""
`.tfs` — a TradeForge stratégia-csomag: egy stratégia EGY fájlban.

⚠ A KÉRÉS (2026-09-02): „Mi is csinálhatnánk valami tfs (TradeForgeStrategy)
kiterjesztésű egyedi fájlt (ami egy átnevezett zip lenne.) … Nálunk is
alapvetően 3-4 fájl van amit be lehetne csomagolni: programkód.py,
docs/valami_hu.md, docs/valami_en.md, config.json"

Pontosan ez. A `.tfs` egy sima zip, ezen a tartalommal:

    manifest.json          mi ez, kinek készült, mi van benne
    <név>.py               a stratégia modulja
    config.json            a stratégia saját beállításai
    docs/<név>.md          a leírás (magyar)
    docs/<név>.en.md       a leírás (angol) — opcionális
    <segéd>.py             a stratégia SAJÁT segédmoduljai — opcionális

⚠ A SEGÉDMODULOK NEM ELMÉLETI LEHETŐSÉG. Az `ml_ai` két saját modult használ
(`ml_features`, `ml_train`), amiket a keret nem ismer. Egy csomag, ami csak
EGY `.py`-t tud vinni, ezt a stratégiát nem tudná átadni — a hiány pedig
importhibaként, a betöltés után derülne ki.

── AMIT EZ A MODUL NEM CSINÁL, ÉS MIÉRT ────────────────────────────────
Nem tölt le semmit, és nem is fog. Egy `.tfs` FUTTATHATÓ PYTHON KÓD: aki
telepíti, ugyanazt vállalja, mintha egy `.exe`-t indítana el. A felhasználó ezt
a tervezéskor tudomásul vette („Egy kicsit a B…"), de a program ettől még nem
válik letöltő-kezelővé: a fájl a te gépedről jön, a te kezeddel.

Nem visz optimalizált paramétert sem (`data/optimized_params/`), sem betanított
modellt. Azok EREDMÉNYEK, nem a stratégia — és páronként/számlánként mások. Egy
frissen telepített stratégiát tehát optimalizálni kell, mielőtt kereskedne; ezt
a `install()` vissza is adja (`needs_optimize`).

── A BIZTONSÁGI KAPUK (mind a HÁROM kellett) ───────────────────────────
1. **Zip-slip**: egy zip-bejegyzés neve lehet `../../valami` vagy abszolút út.
   Kicsomagoláskor ez a projekten KÍVÜLRE írna. Minden nevet ellenőrzünk.
2. **Csak a megengedett fájlok**: modul, config, docs. Semmi más — se
   `__pycache__`, se adat, se rejtett fájl.
3. **Ellenőrzőösszeg**: a manifest minden fájlról tárol egy sha256-ot, és a
   telepítés összeveti. Egy félig letöltött vagy megbütykölt csomag HANGOSAN
   bukik, nem félig települ.

⚠ A TELEPÍTÉS KÉTLÉPCSŐS: előbb ideiglenes mappába csomagolunk ki és MINDENT
ellenőrzünk, és csak utána mozgatjuk a helyére. Egy félig telepített stratégia
rosszabb, mint a semmi: a felderítés megtalálná, a hiányzó fele miatt pedig
importhibával esne szét — és a napló egy nappal később már senkinek nem mondana
semmit.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

# A CSOMAG-formátum verziója. ⚠ NEM azonos a stratégia API-verziójával: ez azt
# mondja meg, hogyan néz ki a zip, az meg azt, milyen szerződésre írták a
# stratégiát. A kettő külön mozog — egy új mező a manifestben nem tesz egy
# stratégiát inkompatibilissé.
PACK_FORMAT = 1

SUFFIX = ".tfs"
KIND = "tradeforge-strategy"

# Amit egy csomag TARTALMAZHAT. Bármi más → elutasítás.
_ALLOWED_SUFFIX = {".py", ".json", ".md"}
_MANIFEST = "manifest.json"


class PackError(Exception):
    """A csomag hibás vagy nem telepíthető. Az üzenet EMBERNEK szól: mindig
    megmondja, mi a baj és mit lehet tenni."""


# ---------------------------------------------------------------------------
# Készítés
# ---------------------------------------------------------------------------

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def helper_modules(name: str) -> list:
    """Egy stratégia SAJÁT segédmoduljai a `strategies/` csomagban.

    Az, amit a stratégia modulja `from strategies import X` / `strategies.X`
    alakban használ, és ami maga NEM stratégia. Így az `ml_ai` csomagja
    magától viszi az `ml_features`-t és az `ml_train`-t — nem kell listát
    karbantartani, ami úgyis elavulna."""
    import ast
    from strategy import paths as _paths
    from strategy import registered_strategy_names

    src = _paths.DIR / f"{name}.py"
    if not src.exists():
        return []
    strategiak = set(registered_strategy_names())
    talalt, sor = [], [src]
    latott = {name}
    while sor:
        f = sor.pop()
        try:
            fa = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for n in ast.walk(fa):
            nevek = set()
            if isinstance(n, ast.ImportFrom) and n.module and not n.level:
                if n.module == _paths.PACKAGE:
                    nevek = {a.name for a in n.names}
                elif n.module.startswith(_paths.PACKAGE + "."):
                    nevek = {n.module.split(".", 1)[1].split(".")[0]}
            elif isinstance(n, ast.Import):
                nevek = {a.name.split(".", 1)[1].split(".")[0]
                         for a in n.names
                         if a.name.startswith(_paths.PACKAGE + ".")}
            for m in nevek:
                # ⚠ EGY MÁSIK STRATÉGIA NEM SEGÉDMODUL. Ha egy stratégia
                # importál egy másikat, azt NEM csomagoljuk bele — az önálló
                # egység. (A `test_gates_package`/`test_strategy_layout` őrök
                # épp az ilyen kereszt-függést tiltják.)
                if m in latott or m in strategiak:
                    continue
                p = _paths.DIR / f"{m}.py"
                if p.exists():
                    latott.add(m)
                    talalt.append(m)
                    sor.append(p)
    return sorted(talalt)


def build(name: str, out_dir=None, version: str = "1.0.0") -> Path:
    """Egy TELEPÍTETT stratégia becsomagolása `.tfs`-be. A kész fájl útját adja.

    A csomag a stratégia MOSTANI állapotát rögzíti: a modult, a segédmoduljait,
    a configját és a leírásait."""
    from strategy import paths as _paths, registered_strategy_names
    from strategy import get_strategy_by_name
    from version import APP_NAME, APP_VERSION

    if name not in registered_strategy_names():
        raise PackError(f"Nincs ilyen (betöltött) stratégia: {name!r}")
    modul = _paths.DIR / f"{name}.py"
    if not modul.exists():
        raise PackError(f"A stratégia modulja nem található: {modul}")
    cfg = _paths.config_file(name)
    if not cfg.exists():
        raise PackError(f"A stratégia configja nem található: {cfg}")

    st = get_strategy_by_name(name)
    segedek = helper_modules(name)
    dokik = sorted(p for p in _paths.docs_dir().glob(f"{name}.*md"))

    out_dir = Path(out_dir) if out_dir else (_paths.ROOT / "data" / "packs")
    out_dir.mkdir(parents=True, exist_ok=True)
    cel = out_dir / f"{name}-{version}{SUFFIX}"

    tartalom = {f"{name}.py": modul, "config.json": cfg}
    for m in segedek:
        tartalom[f"{m}.py"] = _paths.DIR / f"{m}.py"
    for d in dokik:
        tartalom[f"docs/{d.name}"] = d

    manifest = {
        "kind": KIND,
        "format": PACK_FORMAT,
        "name": name,
        "api": int(getattr(st, "api", 1)),
        "version": str(version),
        "created_by": f"{APP_NAME} v{APP_VERSION}",
        "module": f"{name}.py",
        "helpers": [f"{m}.py" for m in segedek],
        "docs": [f"docs/{d.name}" for d in dokik],
        "sha256": {k: _sha(v) for k, v in tartalom.items()},
    }
    with zipfile.ZipFile(cel, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        for arch, p in tartalom.items():
            z.write(p, arch)
    return cel


# ---------------------------------------------------------------------------
# Beolvasás / ellenőrzés
# ---------------------------------------------------------------------------

def _safe_name(arch: str) -> bool:
    """Biztonságos-e egy zip-bejegyzés neve?

    ⚠ EZ A ZIP-SLIP KAPU. Egy zip-bejegyzés neve lehet `../../config.json` vagy
    `C:/Windows/...`; naiv kicsomagolásnál ez a projekten KÍVÜLRE ír. A
    szabály szándékosan szűk: legfeljebb egy `docs/` alkönyvtár, semmi más."""
    if not arch or arch.startswith(("/", "\\")) or ":" in arch:
        return False
    reszek = arch.replace("\\", "/").split("/")
    if any(r in ("", ".", "..") for r in reszek):
        return False
    if len(reszek) > 2 or (len(reszek) == 2 and reszek[0] != "docs"):
        return False
    return Path(arch).suffix in _ALLOWED_SUFFIX


def inspect(path) -> dict:
    """A csomag manifestje TELEPÍTÉS NÉLKÜL — a felület ebből mutatja meg,
    mit hoznál be. Hibás csomagnál `PackError`."""
    p = Path(path)
    if not p.exists():
        raise PackError(f"Nincs ilyen fájl: {p}")
    try:
        with zipfile.ZipFile(p) as z:
            nyers = z.read(_MANIFEST)
            nevek = [i.filename for i in z.infolist() if not i.is_dir()]
    except KeyError:
        raise PackError(f"Ez nem TradeForge-csomag: hiányzik a {_MANIFEST}.")
    except zipfile.BadZipFile:
        raise PackError("A fájl nem olvasható zip (sérült vagy nem `.tfs`).")
    try:
        man = json.loads(nyers.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PackError(f"A {_MANIFEST} nem olvasható: {e}")
    if man.get("kind") != KIND:
        raise PackError(f"Ez nem stratégia-csomag (kind={man.get('kind')!r}).")
    if int(man.get("format", 0)) > PACK_FORMAT:
        raise PackError(
            f"A csomag ÚJABB formátumú (format {man.get('format')}, ez a program "
            f"{PACK_FORMAT}-ig tud) → frissítsd a TradeForge-ot.")
    if not man.get("name"):
        raise PackError("A csomagban nincs stratégia-név.")
    rossz = [n for n in nevek if n != _MANIFEST and not _safe_name(n)]
    if rossz:
        raise PackError("A csomag nem megengedett bejegyzést tartalmaz: "
                        + ", ".join(sorted(rossz)[:5]))
    man["_files"] = sorted(n for n in nevek if n != _MANIFEST)
    return man


def check(path, *, overwrite: bool = False) -> tuple:
    """`(manifest, gondok)` — telepíthető-e, és ha nem, MIÉRT.

    A `gondok` üres listája jelenti a „telepíthető"-t. A felület ezt írja ki a
    megerősítés előtt: a telepítés kódot hoz be, tehát ne legyen meglepetés.

    ⚠ AZ `overwrite` ITT VAN, NEM A HÍVÓNÁL. Egy korábbi változatban a hívó a
    gond SZÖVEGÉBŐL szűrte ki a „már van ilyen nevű"-t — ami az első fordításnál
    (vagy egy ékezet-eltérésnél) némán elromlott volna: a felülírás nem
    működött volna, és semmi nem mondta volna meg, miért."""
    man = inspect(path)
    from strategy import contract, registered_strategy_names
    gondok = []
    ok, indok = contract.compatible(man.get("api"))
    if not ok:
        gondok.append(indok)
    if not overwrite and man["name"] in registered_strategy_names():
        gondok.append(f"már van ilyen nevű stratégia: {man['name']!r} "
                      f"(felülíráshoz kérd külön)")
    if man.get("module") not in man["_files"]:
        gondok.append(f"hiányzik a modul ({man.get('module')})")
    if "config.json" not in man["_files"]:
        gondok.append("hiányzik a config.json")
    if not any(f.startswith("docs/") for f in man["_files"]):
        gondok.append("nincs leírás a csomagban (docs/<név>.md)")
    return man, gondok


# ---------------------------------------------------------------------------
# Telepítés
# ---------------------------------------------------------------------------

def install(path, *, overwrite: bool = False) -> dict:
    """A csomag telepítése a `strategies/` csomagba. A manifestet adja vissza,
    kiegészítve azzal, hogy mi történt.

    ⚠ KÉTLÉPCSŐS. Előbb ideiglenes mappába csomagolunk ki és mindent
    ellenőrzünk (ellenőrzőösszeg is), és CSAK UTÁNA mozgatjuk a helyére. Egy
    félig telepített stratégia rosszabb, mint a semmi: a felderítés megtalálná,
    a hiányzó fele miatt pedig importhibával esne szét."""
    import tempfile
    from strategy import paths as _paths

    man, gondok = check(path, overwrite=overwrite)
    if gondok:
        raise PackError("A csomag nem telepíthető:\n• " + "\n• ".join(gondok))

    nev = man["name"]
    with tempfile.TemporaryDirectory(prefix="tfs_") as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(Path(path)) as z:
            for arch in man["_files"]:
                cel = tmp / arch
                cel.parent.mkdir(parents=True, exist_ok=True)
                cel.write_bytes(z.read(arch))
        # ⚠ AZ ELLENŐRZŐÖSSZEG ITT DŐL EL, a mozgatás ELŐTT. Egy megbütykölt
        # vagy félig letöltött csomag így nem jut el a `strategies/`-ig.
        vart = man.get("sha256") or {}
        elteres = [a for a in man["_files"]
                   if vart.get(a) and _sha(tmp / a) != vart[a]]
        if elteres:
            raise PackError("A csomag SÉRÜLT (az ellenőrzőösszeg nem egyezik): "
                            + ", ".join(elteres))

        celok = {}
        for arch in man["_files"]:
            if arch.startswith("docs/"):
                celok[arch] = _paths.docs_dir() / Path(arch).name
            elif arch == "config.json":
                celok[arch] = _paths.config_file(nev)
            else:
                celok[arch] = _paths.DIR / arch
        for c in celok.values():
            c.parent.mkdir(parents=True, exist_ok=True)
        for arch, cel in celok.items():
            shutil.move(str(tmp / arch), str(cel))

    # ⚠ A REGISTRY GYORSÍTÓTÁRA ELAVULT. Enélkül a frissen telepített stratégia
    # csak a program ÚJRAINDÍTÁSA után jelenne meg — a felhasználó pedig azt
    # látná, hogy „nem történt semmi".
    import strategy as _pkg
    _pkg._REGISTRY = None
    _pkg._INSTANCES.clear()
    _pkg._INCOMPATIBLE.clear()

    man["installed"] = sorted(str(c) for c in celok.values())
    # ⚠ A CSOMAG NEM VISZ OPTIMALIZÁLT PARAMÉTERT: az EREDMÉNY, nem a stratégia
    # (és páronként más). A frissen telepített stratégiát tehát optimalizálni
    # kell, mielőtt kereskedne — a hívó ezt írja ki, hogy ne csendben derüljön ki.
    from core.params_store import PARAMS_DIR
    man["needs_optimize"] = not any((PARAMS_DIR / nev).glob("*.json"))
    return man
