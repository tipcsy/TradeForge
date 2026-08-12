"""MQL-indikátorok kitelepítése a MetaTrader terminálokba.

A felhasználói dokumentáció kérése (Kapcsolat lap):

    „Indikátor(ok) másolása a megfelelő MetaTrader mappába … Innentől eszméletlen
     fontos az MQ4 verziókezelése!"

⚠ MIÉRT KELL EZ EGYÁLTALÁN. A `.mq4`/`.mq5` fájlok a repóban élnek, a terminál
viszont a SAJÁT `MQL4\\Indicators` mappájából olvas. Eddig kézzel kellett
másolni — és ez a hibaosztály: a repóban javított indikátor mellett a terminál
csendben a RÉGIT futtatta tovább, a felhasználó pedig a javítást kereste volna a
képernyőn. (Pontosan ez történt az MT4-es visszajátszás fejlesztése közben:
kilenc verzió, mind néma hiba, mert nem volt egyértelmű, melyik fut.)

A modul TISZTA: nincs Tk- és MT5-függése, csak fájlrendszer — így tesztelhető.

⚠ AMIT NEM CSINÁL: nem FORDÍT. Az `.ex4`/`.ex5` előállításához a MetaEditor kell
(`metaeditor64.exe /compile:…`), ami terminálonként külön telepítés. A modul
megkeresi, és ha megvan, felkínálja — de a hiányát KIMONDJA, nem tesz úgy,
mintha kész volna. Fordítás nélkül a terminálban az `.mq4` melletti RÉGI `.ex4`
futna tovább, ami a legrosszabb eset: az új forrás ott van, mégsem az fut.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

MT4, MT5 = "MT4", "MT5"

# A repó forrásmappái platformonként, és a terminálon belüli célmappa.
_SRC = {MT4: ("mt4", "*.mq4", "MQL4"), MT5: ("mt5", "*.mq5", "MQL5")}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sources(platform: str) -> list:
    """A kitelepítendő indikátor-források a repóból."""
    sub, pat, _ = _SRC.get(platform, (None, None, None))
    if not sub:
        return []
    d = repo_root() / sub
    return sorted(d.glob(pat)) if d.is_dir() else []


def _terminal_roots() -> list:
    """A MetaQuotes `Terminal\\<hash>` mappák (a telepített terminál-profilok)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    base = Path(appdata) / "MetaQuotes" / "Terminal"
    if not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        try:
            if d.is_dir() and d.name.lower() not in ("common",):
                out.append(d)
        except OSError:
            continue
    return out


def discover_roots(extra_bases=None, max_depth: int = 3) -> list:
    """PORTABLE telepítések keresése: mappák, amikben van `MQL4` vagy `MQL5`.

    ⚠ Ez nem finomkodás. Ezen a gépen az AppData-profilokban EGYETLEN MT5
    indikátor sem volt kint — a valódi telepítés a `C:\\Metatrades\\<broker>\\`
    mappákban él (portable mód). Ha csak az AppData-t néznénk, a Kapcsolat lap
    magabiztosan azt mondaná, hogy „kitelepítve", miközben a terminál a régit
    futtatja. Portable módban ugyanis az AppData-profil ÜRESEN marad.

    Sekély keresés (alapból 3 szint), néhány szokásos gyökérből — nem járjuk be
    a lemezt. A 3 szint azért kell, mert a tipikus elrendezés
    ``C:/Metatrades/<broker>/MQL5``; kettővel a keresés CSENDBEN üresen tért
    volna vissza, és a lap azt mondta volna, hogy nincs telepítés.
    """
    bases = [Path(b) for b in (extra_bases or [])]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "SystemDrive"):
        v = os.environ.get(env)
        if v:
            bases.append(Path(v if v.endswith("\\") else v + "\\")
                         if env == "SystemDrive" else Path(v))
    out, seen = [], set()

    # A rendszermappákban nincs terminál, viszont hatalmasak — kihagyva a
    # keresés a másodperc törtrésze marad.
    _SKIP = {"WINDOWS", "$RECYCLE.BIN", "SYSTEM VOLUME INFORMATION",
             "PROGRAMDATA", "PERFLOGS", "ONEDRIVETEMP", "APPDATA", "NODE_MODULES",
             "DOCUMENTS AND SETTINGS", "INETPUB"}

    def _scan(d: Path, depth: int):
        if depth > max_depth:
            return
        try:
            for child in d.iterdir():
                if not child.is_dir():
                    continue
                name = child.name.upper()
                if name in _SKIP:
                    continue
                if name in ("MQL4", "MQL5"):
                    if child.parent not in seen:
                        seen.add(child.parent)
                        out.append(child.parent)
                    continue
                if depth < max_depth:
                    _scan(child, depth + 1)
        except OSError:
            return

    for b in bases:
        if b.is_dir():
            _scan(b, 1)
    return out


def targets(platform: str, extra_roots=None,
            include_appdata: bool = True) -> list:
    """A LÉTEZŐ `…\\MQL4|MQL5\\Indicators` célmappák.

    Két helyről gyűjt, mert a valóságban mindkettő előfordul:
      • az AppData-beli terminál-profilok (szabványos telepítés),
      • a terminál TELEPÍTÉSI mappája (portable mód — ott a `MQL4` a program
        mellett van, és az AppData-profil üres marad).

    ⚠ A kettőt nem szabad összekeverni: portable módban az AppData-ba másolt
    fájlt a terminál SOSEM látja meg — csendben a régit futtatná.

    ⚠ `include_appdata=False` → CSAK a megadott gyökerek. Ez nem kényelmi
    kapcsoló: enélkül nem lehet EGY terminálba telepíteni, és a teszt sem tudna
    ideiglenes mappán dolgozni — a `deploy` a valódi terminálokba is írna. (Írt
    is: az első futáskor 15 fájlt tett a felhasználó AppData-profiljaiba, amit
    vissza kellett vonni.)
    """
    mql = _SRC.get(platform, (None, None, None))[2]
    if not mql:
        return []
    out = []
    if include_appdata:
        for root in _terminal_roots():
            d = root / mql / "Indicators"
            if d.is_dir():
                out.append(d)
    for r in (extra_roots or []):
        d = Path(r)
        if d.name.lower() != "indicators":
            d = d / mql / "Indicators"
        if d.is_dir() and d not in out:
            out.append(d)
    return out


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and \
            a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def status(platform: str, extra_roots=None, include_appdata: bool = True) -> list:
    """Mi a helyzet MOST? `[{target, file, state}, …]`.

    `state`: `"friss"` (a terminálban ugyanaz van), `"elavult"` (más),
    `"hiányzik"` (nincs kint).
    """
    out = []
    for tgt in targets(platform, extra_roots, include_appdata):
        for src in sources(platform):
            dst = tgt / src.name
            if not dst.exists():
                st = "hiányzik"
            elif _same_bytes(src, dst):
                st = "friss"
            else:
                st = "elavult"
            out.append({"target": tgt, "file": src.name, "state": st})
    return out


def deploy(platform: str, extra_roots=None, dry_run: bool = False,
           include_appdata: bool = True) -> dict:
    """A források kimásolása MINDEN megtalált célmappába.

    Visszaad: `{"copied": [...], "skipped": [...], "errors": [...], "targets": n}`.
    A `skipped` a már azonos fájl (nem írunk feleslegesen — a terminál a
    fájlváltozásra újrafordíthat/újratölthet).
    """
    res = {"copied": [], "skipped": [], "errors": [], "targets": 0}
    tgts = targets(platform, extra_roots, include_appdata)
    res["targets"] = len(tgts)
    srcs = sources(platform)
    if not srcs:
        res["errors"].append(f"nincs {platform} forrás a repóban")
        return res
    if not tgts:
        res["errors"].append(
            f"nem találtam {platform} terminál-mappát "
            f"(AppData\\MetaQuotes\\Terminal\\…\\{_SRC[platform][2]}\\Indicators). "
            f"Portable módban add meg a terminál telepítési mappáját.")
        return res
    for tgt in tgts:
        for src in srcs:
            dst = tgt / src.name
            if dst.exists() and _same_bytes(src, dst):
                res["skipped"].append(str(dst))
                continue
            if dry_run:
                res["copied"].append(str(dst))
                continue
            try:
                shutil.copy2(src, dst)
                res["copied"].append(str(dst))
            except OSError as ex:
                res["errors"].append(f"{dst}: {ex}")
    return res


def metaeditor(platform: str, extra_roots=None) -> Path | None:
    """A MetaEditor futtatható (a fordításhoz), ha megtalálható.

    ⚠ ELŐSZÖR a megadott (felderített) terminál-mappákban keres. Portable
    telepítésnél a MetaEditor a terminál MELLETT van — ezen a gépen mind a hat
    telepítésben ott volt, miközben a Program Files alatt egyetlen MT5-ös sem.
    A Program Files csak tartalék.

    Fontos, hogy a MEGFELELŐ példányt találjuk meg: az MT4 MetaEditora `.mq4`-et
    fordít, az MT5-é `.mq5`-öt — a másikkal a fordítás hibára fut.
    """
    want = "MQL4" if platform == MT4 else "MQL5"
    names = ("metaeditor64.exe", "metaeditor.exe")
    for r in (extra_roots or []):
        d = Path(r)
        if not (d / want).is_dir():
            continue          # nem ehhez a platformhoz tartozó telepítés
        for n in names:
            for p in (d / n, d / n.replace("metaeditor", "MetaEditor")):
                if p.exists():
                    return p
        try:
            for f in d.iterdir():
                if f.is_file() and f.name.lower() in names:
                    return f
        except OSError:
            continue
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if not base or not Path(base).is_dir():
            continue
        try:
            for d in Path(base).iterdir():
                if not d.is_dir() or not (d / want).is_dir():
                    continue
                for n in names:
                    p = d / n
                    if p.exists():
                        return p
        except OSError:
            continue
    return None


def compile_file(exe: Path, src: Path, timeout: int = 120) -> tuple:
    """Egy forrás lefordítása MetaEditorral. `(ok, üzenet)`.

    A hívás `metaeditor64.exe /compile:"<fájl>" /log:"<napló>"`.

    ⚠ HÁROM dolog, amitől ez másképp viselkedik, mint egy szokásos CLI:

    1. A **kilépési kód a HIBÁK SZÁMA**, nem 0/1 — a 0 a siker. Ha ezt
       elvétenénk, minden fordítás „sikeresnek" látszana.
    2. A napló **UTF-16**-ban készül. `utf-8`-cal olvasva olvashatatlan
       karakterhalmaz jönne, és a hibaüzenet elveszne.
    3. A MetaEditor a naplót a forrás MELLÉ írja, ha nem adunk `/log`-ot — ezért
       adunk, különben a terminál mappájában szemetelnénk.
    """
    import subprocess
    import tempfile as _tf

    # ⚠ A SIKERT A KIMENETEN MÉRJÜK, nem a kilépési kódon. Ezen a gépen (MT4
    # build és MT5 build egyaránt) a MetaEditor MINDEN dokumentált alakra
    # (`/compile:`, `+/log`, `+/portable`, relatív út) 0,2 mp alatt kilépett
    # rc=0-val, napló nélkül — és NEM fordított: sem az `.ex4`/`.ex5` nem
    # frissült, sem új fájl nem keletkezett sehol a gépen.
    #
    # Ha csak a kilépési kódot néznénk, a felület magabiztosan „rendben"-t írna,
    # a terminál pedig továbbra is a RÉGI lefordítottat futtatná. Ez a
    # legrosszabb kimenet: a felhasználó azt hinné, kész — pontosan az a
    # hibaosztály, ami miatt ez a modul megszületett.
    compiled = src.with_suffix(".ex4" if src.suffix == ".mq4" else ".ex5")
    before = compiled.stat().st_mtime if compiled.exists() else 0.0

    log_path = Path(_tf.gettempdir()) / f"tf_compile_{src.stem}.log"
    try:
        proc = subprocess.run(
            [str(exe), f"/compile:{src}", f"/log:{log_path}"],
            capture_output=True, timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return False, f"{src.name}: a fordítás {timeout} mp után sem végzett"
    except OSError as ex:
        return False, f"{src.name}: nem indítható a MetaEditor ({ex})"

    text = ""
    try:
        if log_path.exists():
            text = log_path.read_text(encoding="utf-16", errors="replace")
    except (OSError, UnicodeError):
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    finally:
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass

    errs = [ln.strip() for ln in text.splitlines()
            if ": error" in ln.lower()]
    if errs:
        return False, f"{src.name}: {errs[0]}"
    after = compiled.stat().st_mtime if compiled.exists() else 0.0
    if after > before:
        return True, f"{src.name}: lefordítva"
    if rc != 0:
        return False, f"{src.name}: {rc} hiba"
    # rc=0, nincs hibaüzenet, de a kimenet SEM készült el.
    return False, (f"{src.name}: a MetaEditor nem fordított (a parancssori "
                   f"fordítás ezen a verzión nem működik) — nyisd meg a fájlt a "
                   f"MetaEditorban és nyomj F7-et")


def compile_all(platform: str, extra_roots=None, include_appdata: bool = True,
                exe: "Path | None" = None) -> dict:
    """A KITELEPÍTETT források lefordítása minden célmappában.

    ⚠ A célmappában levő PÉLDÁNYT fordítjuk, nem a repóbelit: a MetaEditor a
    fordítást a forrás mellé teszi, és a terminál CSAK a saját mappájából tölt.
    A repóban fordítva az `.ex4` ott keletkezne, ahol soha senki nem olvassa.
    """
    res = {"ok": [], "failed": [], "errors": []}
    tgts = targets(platform, extra_roots, include_appdata)
    if not tgts:
        res["errors"].append(f"nincs {platform} célmappa")
        return res
    for tgt in tgts:
        # Portable módban a MetaEditor a terminál gyökerében van — az a
        # célmappa két szinttel feljebb (…\MQL5\Indicators).
        _exe = exe or metaeditor(platform, [tgt.parent.parent]) or \
            metaeditor(platform, extra_roots)
        if _exe is None:
            res["errors"].append(f"{tgt}: nem találom a MetaEditort")
            continue
        for src in sources(platform):
            dst = tgt / src.name
            if not dst.exists():
                continue
            ok, msg = compile_file(Path(_exe), dst)
            (res["ok"] if ok else res["failed"]).append(f"{tgt.parent.parent.name}: {msg}")
    return res


def compiled_beside(platform: str, extra_roots=None, include_appdata: bool = True) -> list:
    """A célmappákban levő LEFORDÍTOTT fájlok kora a forráshoz képest.

    ⚠ Ez a legalattomosabb állapot: az új `.mq4` kint van, de mellette a RÉGI
    `.ex4` — és a terminál AZT futtatja. A felhasználó a javítást keresné a
    képernyőn, hiába.
    """
    ext = ".ex4" if platform == MT4 else ".ex5"
    out = []
    for tgt in targets(platform, extra_roots, include_appdata):
        for src in sources(platform):
            s = tgt / src.name
            c = tgt / (src.stem + ext)
            if not c.exists():
                out.append({"target": tgt, "file": src.name, "state": "nincs fordítva"})
            elif s.exists() and c.stat().st_mtime < s.stat().st_mtime:
                out.append({"target": tgt, "file": src.name, "state": "RÉGEBBI a forrásnál"})
            else:
                out.append({"target": tgt, "file": src.name, "state": "rendben"})
    return out
