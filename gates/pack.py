"""
`.tfg` — a TradeForge KAPU-csomag: egy kapu EGY fájlban.

Ugyanaz a minta, mint a `.tfs`-é (`strategy/pack.py`), és SZÁNDÉKOSAN ugyanaz:
ami ott bevált — a zip-slip zár, az ellenőrzőösszeg, a kétlépcsős telepítés —,
az itt is kell, és két különböző megoldás két külön romlást jelentene.

A `.tfg` egy sima zip, ezzel a tartalommal:

    manifest.json          mi ez, melyik kapu, mi van benne
    <modul>.py             a kapu MÉRÉSE (`GATE` + `measure(ctx)`)
    docs/<kulcs>.md        a leírás (magyar)
    docs/<kulcs>.en.md     a leírás (angol) — opcionális
    <segéd>.py             a kapu SAJÁT segédmoduljai — opcionális

── AMI MÁS, MINT A STRATÉGIÁNÁL ────────────────────────────────────────
1. **NINCS külön config-fájl.** Egy stratégia beállításai saját JSON-ban élnek
   (`strategies/config/<név>.json`); egy kapu számai a `config.json` `gates`
   szekciójában, PÁRONKÉNT és STRATÉGIÁNKÉNT örökölve. Azt egy csomag nem
   hozhatja magával — az a TE beállításod, nem a kapué.

2. **A doksi a KULCSRÓL kapja a nevét, nem a modulról.** `spread_gate.py` →
   `docs/spread.md`. Ez a `core.gates.doc_path` szerződése; ha a csomagoló a
   modul nevét használná, a telepített kapu leírása némán nem jelenne meg.

3. **A telepített kapu HATÁSA `none`.** Egy `.tfs` kikapcsolva kerül be; egy
   kapunál ennek a megfelelője az, hogy nem szól bele a kereskedésbe, amíg be
   nem kapcsolod. Egy frissítés SOHA nem kezdhet el némán másképp kereskedni.

── AMIT EZ A MODUL NEM CSINÁL, ÉS MIÉRT ────────────────────────────────
Nem tölt le semmit. Egy `.tfg` FUTTATHATÓ PYTHON KÓD: aki telepíti, ugyanazt
vállalja, mintha egy `.exe`-t indítana el. Ezért a parancssoron `--yes` kell,
és nem lesz belőle letöltő-kezelő.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

# A CSOMAG-formátum verziója. ⚠ NEM azonos a kapu API-verziójával: ez azt mondja
# meg, hogyan néz ki a zip, az meg azt, milyen szerződésre írták a kaput.
PACK_FORMAT = 1

SUFFIX = ".tfg"
KIND = "tradeforge-gate"

# A KAPU-SZERZŐDÉS verziója: `GATE` szótár + `measure(ctx) -> (bukott, szint)`.
# Ha ez változik (más aláírás, más visszatérés), a szám nő, és a régi csomag
# BESZÉDES hibát kap — nem importhibát a betöltés után.
GATE_API = 1

_ALLOWED_SUFFIX = {".py", ".md"}
_MANIFEST = "manifest.json"


class PackError(Exception):
    """A csomag hibás vagy nem telepíthető. Az üzenet EMBERNEK szól: mindig
    megmondja, mi a baj és mit lehet tenni."""


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


def compatible(api) -> tuple:
    """`(rendben, indok)` — elfogadjuk-e ezt a kapu-API-verziót?

    A két irány KÉT KÜLÖN üzenet, mert a teendő is más: egy régi csomagot át
    kell írni, egy újabbhoz a programot kell frissíteni."""
    try:
        api = int(api)
    except (TypeError, ValueError):
        return False, "a csomag nem mondja meg, milyen kapu-API-ra készült"
    if api > GATE_API:
        return False, (f"a csomag ÚJABB kapu-API-ra készült (api {api}, ez a "
                       f"program {GATE_API}-ig tud) → frissítsd a TradeForge-ot")
    if api < GATE_API:
        return False, (f"a csomag RÉGEBBI kapu-API-ra készült (api {api}, "
                       f"a mostani {GATE_API}) → a kaput át kell írni")
    return True, ""


# ---------------------------------------------------------------------------
# Készítés
# ---------------------------------------------------------------------------

def helper_modules(module: str) -> list:
    """Egy kapu SAJÁT segédmoduljai a `gates/` csomagban.

    Ugyanaz a bejárás, mint a stratégiáknál: amit a kapu modulja `from gates
    import X` alakban használ, és ami maga NEM kapu. Így nem kell listát
    karbantartani, ami úgyis elavulna."""
    import ast

    from core import gates as _g
    from gates import paths as _gp

    src = _gp.DIR / f"{module}.py"
    if not src.exists():
        return []
    # ⚠ EGY MÁSIK KAPU NEM SEGÉDMODUL. Ha egy kapu importálna egy másikat, azt
    # NEM csomagoljuk bele — az önálló egység. (A `gates/__init__` szabálya is
    # ez: „egy kapu-modul nem tudhat a másikról".)
    kapu_modulok = {g.get("module") for g in _g.REGISTRY} | {"paths", "pack"}
    talalt, sor, latott = [], [src], {module}
    while sor:
        f = sor.pop()
        try:
            fa = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for n in ast.walk(fa):
            nevek = set()
            if isinstance(n, ast.ImportFrom) and n.module and not n.level:
                if n.module == _gp.PACKAGE:
                    nevek = {a.name for a in n.names}
                elif n.module.startswith(_gp.PACKAGE + "."):
                    nevek = {n.module.split(".", 1)[1].split(".")[0]}
            elif isinstance(n, ast.Import):
                nevek = {a.name.split(".", 1)[1].split(".")[0] for a in n.names
                         if a.name.startswith(_gp.PACKAGE + ".")}
            for m in nevek:
                if m in latott or m in kapu_modulok:
                    continue
                p = _gp.DIR / f"{m}.py"
                if p.exists():
                    latott.add(m)
                    talalt.append(m)
                    sor.append(p)
    return sorted(talalt)


def build(key: str, out_dir=None, version: str = "1.0.0", out_file=None) -> Path:
    """Egy TELEPÍTETT kapu becsomagolása `.tfg`-be. A kész fájl útját adja."""
    from core import gates as _g
    from gates import paths as _gp
    from version import APP_NAME, APP_VERSION

    if key not in _g.KEYS:
        raise PackError(f"Nincs ilyen kapu: {key!r}")
    modul_nev = _g.entry_of(key).get("module")
    if not modul_nev:
        raise PackError(f"A(z) {key!r} kapuhoz nincs modul bejegyezve.")
    modul = _gp.DIR / f"{modul_nev}.py"
    if not modul.exists():
        raise PackError(f"A kapu modulja nem található: {modul}")

    segedek = helper_modules(modul_nev)
    # ⚠ A DOKSI A KULCSRÓL kapja a nevét (`gates/docs/<kulcs>.md`), nem a
    # modulról — ez a `core.gates.doc_path` szerződése.
    dokik = sorted(p for p in _gp.docs_dir().glob(f"{key}.*md"))

    if out_file:
        cel = Path(out_file)
        cel.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(out_dir) if out_dir else (_gp.ROOT / "data" / "packs")
        out_dir.mkdir(parents=True, exist_ok=True)
        cel = out_dir / f"{key}-{version}{SUFFIX}"

    tartalom = {f"{modul_nev}.py": modul}
    for m in segedek:
        tartalom[f"{m}.py"] = _gp.DIR / f"{m}.py"
    for d in dokik:
        tartalom[f"docs/{d.name}"] = d

    manifest = {
        "kind": KIND,
        "format": PACK_FORMAT,
        "key": key,
        "module": f"{modul_nev}.py",
        "phase": _g.phase_of(key),
        "api": GATE_API,
        "version": str(version),
        "created_by": f"{APP_NAME} v{APP_VERSION}",
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
    """Biztonságos-e egy zip-bejegyzés neve? (ZIP-SLIP kapu.)

    Egy zip-bejegyzés neve lehet `../../valami` vagy `C:/Windows/...`; naiv
    kicsomagolásnál ez a projekten KÍVÜLRE ír. A szabály szándékosan szűk:
    legfeljebb egy `docs/` alkönyvtár, semmi más."""
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
        raise PackError("A fájl nem olvasható zip (sérült vagy nem `.tfg`).")
    try:
        man = json.loads(nyers.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PackError(f"A {_MANIFEST} nem olvasható: {e}")
    if man.get("kind") != KIND:
        # ⚠ BESZÉDESEN: a leggyakoribb tévedés az, hogy valaki egy `.tfs`-t ad
        # ide (vagy fordítva). Mondjuk meg, mit kapott, ne csak azt, hogy rossz.
        _mi = man.get("kind")
        if _mi == "tradeforge-strategy":
            raise PackError("Ez egy STRATÉGIA-csomag (.tfs), nem kapu-csomag. "
                            "Telepítsd a stratégia-telepítővel.")
        raise PackError(f"Ez nem kapu-csomag (kind={_mi!r}).")
    if int(man.get("format", 0)) > PACK_FORMAT:
        raise PackError(
            f"A csomag ÚJABB formátumú (format {man.get('format')}, ez a program "
            f"{PACK_FORMAT}-ig tud) → frissítsd a TradeForge-ot.")
    if not man.get("key"):
        raise PackError("A csomagban nincs kapu-kulcs.")
    rossz = [n for n in nevek if n != _MANIFEST and not _safe_name(n)]
    if rossz:
        raise PackError("A csomag nem megengedett bejegyzést tartalmaz: "
                        + ", ".join(sorted(rossz)[:5]))
    man["_files"] = sorted(n for n in nevek if n != _MANIFEST)
    return man


def check(path, *, overwrite: bool = False) -> tuple:
    """`(manifest, gondok)` — telepíthető-e, és ha nem, MIÉRT."""
    from core import gates as _g

    man = inspect(path)
    gondok = []
    ok, indok = compatible(man.get("api"))
    if not ok:
        gondok.append(indok)
    if not overwrite and man["key"] in _g.KEYS:
        gondok.append(f"már van ilyen kulcsú kapu: {man['key']!r} "
                      f"(felülíráshoz kérd külön)")
    if man.get("module") not in man["_files"]:
        gondok.append(f"hiányzik a modul ({man.get('module')})")
    if not any(f.startswith("docs/") for f in man["_files"]):
        gondok.append("nincs leírás a csomagban (docs/<kulcs>.md)")
    _f = str(man.get("phase") or _g.PHASE_SIGNAL)
    if _f not in _g.PHASES:
        gondok.append(f"ismeretlen mérési fázis: {_f!r} "
                      f"(csak {', '.join(_g.PHASES)} lehet)")
    return man, gondok


# ---------------------------------------------------------------------------
# Telepítés
# ---------------------------------------------------------------------------

def install(path, *, overwrite: bool = False) -> dict:
    """A csomag telepítése a `gates/` csomagba.

    ⚠ KÉTLÉPCSŐS. Előbb ideiglenes mappába csomagolunk ki és MINDENT
    ellenőrzünk (ellenőrzőösszeg is), és CSAK UTÁNA mozgatjuk a helyére. Egy
    félig telepített kapu rosszabb, mint a semmi: a felderítés megtalálná, a
    hiányzó fele miatt pedig a betöltés bukna — és a naplóban egy nappal később
    már senkinek nem mondana semmit."""
    import tempfile

    from core import gates as _g
    from gates import paths as _gp

    man, gondok = check(path, overwrite=overwrite)
    if gondok:
        raise PackError("A csomag nem telepíthető:\n• " + "\n• ".join(gondok))

    with tempfile.TemporaryDirectory(prefix="tfg_") as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(Path(path)) as z:
            for arch in man["_files"]:
                cel = tmp / arch
                cel.parent.mkdir(parents=True, exist_ok=True)
                cel.write_bytes(z.read(arch))
        # ⚠ AZ ELLENŐRZŐÖSSZEG ITT DŐL EL, a mozgatás ELŐTT.
        vart = man.get("sha256") or {}
        elteres = [a for a in man["_files"]
                   if vart.get(a) and _sha(tmp / a) != vart[a]]
        if elteres:
            raise PackError("A csomag SÉRÜLT (az ellenőrzőösszeg nem egyezik): "
                            + ", ".join(elteres))

        celok = {}
        for arch in man["_files"]:
            if arch.startswith("docs/"):
                celok[arch] = _gp.docs_dir() / Path(arch).name
            else:
                celok[arch] = _gp.DIR / arch
        for c in celok.values():
            c.parent.mkdir(parents=True, exist_ok=True)
        for arch, cel in celok.items():
            shutil.move(str(tmp / arch), str(cel))

    # ⚠ A REGISTRY ELAVULT. Enélkül a frissen telepített kapu csak a program
    # ÚJRAINDÍTÁSA után jelenne meg — a felhasználó pedig azt látná, hogy a
    # telepítés lefutott, és mégsem történt semmi.
    _g.refresh_registry()

    man["installed"] = sorted(str(c) for c in celok.values())
    # ⚠ A KAPU HATÁSA `none`, amíg be nem kapcsolod. Ezt a hívó írja ki, hogy
    # ne csendben derüljön ki: egy telepített kapu addig NEM szól bele semmibe.
    man["needs_enable"] = _g.default_effect_of(man["key"]) == _g.EFFECT_NONE
    man["active"] = man["key"] in _g.KEYS
    return man
