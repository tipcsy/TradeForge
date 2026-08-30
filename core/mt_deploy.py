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

# ── ÁLLAPOT-KÓDOK ──────────────────────────────────────────────────────────
# ⚠ A KÓD AZ AZONOSÍTÓ, A SZÖVEG CSAK A KIJELZÉS. Ezek az állapotok korábban
# magyar mondatok voltak (`"MÁS FORRÁSHOZ készült"`), és a felület EZEKRE
# hasonlított. Lefordítva egyik ág sem tüzelt volna: a „más forráshoz készült"
# figyelmeztetés — a modul legfontosabb üzenete, mert ilyenkor a terminálban MÁS
# fut, mint amit a repóban látsz — némán eltűnt volna.
# Kitelepítés (deploy_status):
ST_MISSING, ST_FRESH, ST_STALE = "missing", "fresh", "stale"
# A repóban TÁROLT lefordított (compiled_status):
ST_NOT_STORED, ST_MATCH, ST_OTHER_SOURCE = "not_stored", "match", "other_source"
# A terminálban KINT lévő lefordított (compiled_behind):
ST_NOT_COMPILED, ST_OLDER, ST_OK = "not_compiled", "older", "ok"

STATES = (ST_MISSING, ST_FRESH, ST_STALE, ST_NOT_STORED, ST_MATCH,
          ST_OTHER_SOURCE, ST_NOT_COMPILED, ST_OLDER, ST_OK)


def state_label(code: str) -> str:
    """Állapot-kód → a felületen mutatott felirat, az aktív nyelven."""
    from core.i18n import t as _t
    return _t(f"deploy.state.{code}") if code in STATES else str(code)


# A repó forrásmappái platformonként, és a terminálon belüli MQL-gyökér.
# ⚠ Az MT5-höz a `tools/` is hozzátartozik: a backtest-visszajátszó és a két
# néző ott lakik (történelmi okból). Ha csak az `mt5/`-öt néznénk, azok
# csendben kimaradnának a kitelepítésből.
_SRC = {MT4: (("mt4",), "*.mq4", "MQL4"),
        MT5: (("mt5", "tools"), "*.mq5", "MQL5")}

# Melyik fájl HOVA megy a terminálon belül. Alap: `Indicators`.
# ⚠ Az EXPERT (`OnTick`) az `Experts` mappába való — az `Indicators`-ba téve a
# terminál fel sem kínálja a Strategy Testerben.
_EXPERTS = {"BacktestReplayer"}

# Mi micsoda — a felület ezt írja ki a fájlnév mellé. A szöveg a fájlok saját
# fejlécéből származik, nem találgatás.
_DESC = {
    "TradeForgeViz": ("belépő-jelzések, SL/TP, kötések",
                      "a fő megjelenítő: a Python írta jelzés-fájlt rajzolja a chartra"),
    "TradeForgeWPR": ("Williams %R a stratégia matekjával",
                      "külön al-ablak; a paramétereit a motor fájljából veszi"),
    "TradeForgeBands": ("állapot-sáv (TBAND)",
                        "külön al-ablak: mikor van nyitva a jelzési ablak"),
    "TradeForgeProbe": ("diagnosztika",
                        "nem rajzol; megmondja, eléri-e a terminál a fájlokat"),
    "BacktestReplayer": ("EXPERT — a Python backtestjét játssza vissza",
                         "a Strategy Testerbe való (nem a chartra); az esemény-"
                         "naplót játssza le, nem szimulál újra"),
    "BacktestPnLViewer": ("a visszajátszás P&L-görbéje", "a Replayer CSV-jéből"),
    "BacktestTradesViewer": ("a visszajátszás kötései a charton",
                             "a Replayer CSV-jéből"),
}

# Melyik indikátort kell RÁHÚZNI a chartra, platformonként — a felület ezt írja
# ki, mert a két platform MÁS: MT4-en a három rész külön indikátor, MT5-ön a
# fő megjelenítő maga rajzolja az al-ablakokat.
USAGE = {
    MT4: ("MT4-en MIND A HÁROM indikátort rá kell húzni a chartra "
          "(TradeForgeViz + TradeForgeWPR + TradeForgeBands), és mindháromnál "
          "ugyanazt az utótagot kell beállítani (visszajátszáshoz `_BT`)."),
    MT5: ("MT5-ön elég a TradeForgeViz — a WPR és a Bands külön al-ablak, csak "
          "akkor kell, ha azokat is látni akarod."),
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def subfolder_of(src: Path) -> str:
    """A terminálon belüli célmappa neve ehhez a fájlhoz."""
    return "Experts" if src.stem in _EXPERTS else "Indicators"


def describe(src: Path) -> tuple:
    """`(rövid, használat)` — mit csinál ez a fájl. Ismeretlen → üres."""
    return _DESC.get(src.stem, ("", ""))


def sources(platform: str) -> list:
    """A kitelepítendő források a repóból (indikátorok ÉS expertek)."""
    subs, pat, _ = _SRC.get(platform, (None, None, None))
    if not subs:
        return []
    out = []
    for sub in subs:
        d = repo_root() / sub
        if d.is_dir():
            out.extend(sorted(d.glob(pat)))
    return out


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
            d = root / mql
            if d.is_dir() and d not in out:
                out.append(d)
    for r in (extra_roots or []):
        d = Path(r)
        if d.name.upper() not in ("MQL4", "MQL5"):
            d = d / mql
        if d.is_dir() and d not in out:
            out.append(d)
    return out


def dest_for(mql_root: Path, src: Path) -> Path:
    """A konkrét célfájl: `<MQL4|MQL5>/<Indicators|Experts>/<név>`."""
    return mql_root / subfolder_of(src) / src.name


# ---------------------------------------------------------------------------
# A LEFORDÍTOTT (.ex4/.ex5) tárolása a repóban — verzió-ellenőrzéssel
# ---------------------------------------------------------------------------
# A kérés: „ne tároljuk mégiscsak le az ex4/ex5 fájlokat? Ha azok is verziózva
# vannak, akkor nem lehet gond a tárolással (figyelmeztetés jöhet, ha nem
# egyezik a verzió)."
#
# ⚠ A `#property version` NEM elég: kézzel írják, és két különböző forrás
# viselheti ugyanazt. Ezért a jegyzék a forrás TARTALMÁNAK ujjlenyomatát tárolja
# (sha1) — az akkor is eltér, ha a verziószámot elfelejtették emelni. A
# verziószámot is elmentjük, mert EMBERI olvasásra az mond valamit.

_MANIFEST = "compiled.json"


def _compiled_dir(platform: str) -> Path:
    return repo_root() / ("mt4" if platform == MT4 else "mt5") / "compiled"


def _sha1(p: Path) -> str:
    import hashlib
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def source_version(src: Path) -> str:
    """A `#property version "x.yz"` a forrásból (üres, ha nincs)."""
    import re
    try:
        m = re.search(r'#property\s+version\s+"([^"]+)"',
                      src.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def _manifest(platform: str) -> dict:
    import json
    p = _compiled_dir(platform) / _MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def compiled_status(platform: str) -> list:
    """A repóban TÁROLT lefordított fájlok állapota a forráshoz képest.

    `state`: `ST_NOT_STORED` · `ST_MATCH` · `ST_OTHER_SOURCE` (kódok — a
    feliratot a `state_label()` adja).
    """
    man = _manifest(platform)
    cdir = _compiled_dir(platform)
    ext = ".ex4" if platform == MT4 else ".ex5"
    out = []
    for src in sources(platform):
        ex = cdir / (src.stem + ext)
        rec = man.get(ex.name) or {}
        if not ex.exists():
            st = ST_NOT_STORED
        elif rec.get("source_sha1") == _sha1(src):
            st = ST_MATCH
        else:
            st = ST_OTHER_SOURCE
        out.append({"file": src.name, "compiled": ex.name, "state": st,
                    "version": source_version(src),
                    "stored_version": rec.get("source_version", "")})
    return out


def capture_compiled(platform: str, extra_roots=None,
                     include_appdata: bool = True) -> dict:
    """A terminálban LEFORDÍTOTT fájlok beemelése a repóba, jegyzékkel.

    Ezt a MetaEditoros F7 UTÁN kell futtatni: a frissen fordított `.ex4`/`.ex5`
    bekerül a repóba, és MELLÉ íródik, melyik forrás-tartalomból készült. Így a
    következő kitelepítéskor a lefordított is mehet — és ha közben a forrás
    változott, azt a `compiled_status` KIMONDJA.
    """
    import json
    from datetime import datetime, timezone

    ext = ".ex4" if platform == MT4 else ".ex5"
    cdir = _compiled_dir(platform)
    cdir.mkdir(parents=True, exist_ok=True)
    man = _manifest(platform)
    res = {"taken": [], "missing": [], "errors": []}
    for src in sources(platform):
        newest, newest_m = None, -1.0
        for root in targets(platform, extra_roots, include_appdata):
            deployed = dest_for(root, src)
            cand = deployed.with_suffix(ext)
            if not cand.exists() or not deployed.exists():
                continue
            # ⚠ CSAK olyan binárist veszünk át, ami BIZONYÍTHATÓAN a MOSTANI
            # forrásból készült. Két feltétel, és mindkettő kell:
            #   (a) a terminálban levő FORRÁS byte-azonos a repóéval — különben
            #       a bináris egy MÁSIK szöveghez tartozik,
            #   (b) a bináris ÚJABB annál a forrásnál — különben előbb készült.
            #
            # Enélkül a jegyzék a MOSTANI forrás ujjlenyomatát írná egy RÉGI
            # binárishoz, és a felület magabiztosan „egyezik"-et mutatna. Ez
            # pontosan az az állapot, ami ellen az egész modul készült — és az
            # első futáskor elő is állt: a verzió-sor hozzáadása után a
            # beolvasás a régi .ex5-öket az új forráshoz kötötte volna.
            if not _same_bytes(src, deployed):
                continue
            if cand.stat().st_mtime < deployed.stat().st_mtime:
                continue
            m = cand.stat().st_mtime
            if m > newest_m:
                newest, newest_m = cand, m
        if newest is None:
            res["missing"].append(src.name)
            continue
        try:
            shutil.copy2(newest, cdir / (src.stem + ext))
        except OSError as ex_:
            res["errors"].append(f"{src.name}: {ex_}")
            continue
        man[src.stem + ext] = {
            "source_sha1": _sha1(src),
            "source_version": source_version(src),
            "captured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "from": str(newest),
        }
        res["taken"].append(src.stem + ext)
    try:
        (cdir / _MANIFEST).write_text(
            json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as ex_:
        res["errors"].append(str(ex_))
    return res


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
            dst = dest_for(tgt, src)
            if not dst.exists():
                st = ST_MISSING
            elif _same_bytes(src, dst):
                st = ST_FRESH
            else:
                st = ST_STALE
            out.append({"target": dst.parent, "file": src.name, "state": st,
                        "kind": subfolder_of(src)})
    return out


def deploy(platform: str, extra_roots=None, dry_run: bool = False,
           include_appdata: bool = True) -> dict:
    """A források kimásolása MINDEN megtalált célmappába.

    Visszaad: `{"copied": [...], "skipped": [...], "errors": [...], "targets": n}`.
    A `skipped` a már azonos fájl (nem írunk feleslegesen — a terminál a
    fájlváltozásra újrafordíthat/újratölthet).
    """
    res = {"copied": [], "skipped": [], "errors": [], "targets": 0,
           "stale_compiled": []}
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
    # A TAROLT leforditottak: csak azt visszuk ki, ami a MOSTANI forrashoz
    # keszult — kulonben a terminalban ujra a "regi fut, uj forras" allapot allna
    # elo, csak eppen a repobol szallitva.
    _cs = {c["file"]: c for c in compiled_status(platform)}
    _cdir = _compiled_dir(platform)
    _ext = ".ex4" if platform == MT4 else ".ex5"

    for tgt in tgts:
        for src in srcs:
            dst = dest_for(tgt, src)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
            except OSError as ex:
                res["errors"].append(f"{dst.parent}: {ex}")
                continue
            pairs = [(src, dst)]
            _c = _cs.get(src.name) or {}
            if _c.get("state") == ST_MATCH:
                pairs.append((_cdir / (src.stem + _ext), dst.with_suffix(_ext)))
            elif _c.get("state") == ST_OTHER_SOURCE:
                res["stale_compiled"].append(src.name)
            for s_, d_ in pairs:
                if not s_.exists():
                    continue
                if d_.exists() and _same_bytes(s_, d_):
                    res["skipped"].append(str(d_))
                    continue
                if dry_run:
                    res["copied"].append(str(d_))
                    continue
                try:
                    shutil.copy2(s_, d_)
                    res["copied"].append(str(d_))
                except OSError as ex:
                    res["errors"].append(f"{d_}: {ex}")
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
            s = dest_for(tgt, src)
            c = s.with_suffix(ext)
            if not c.exists():
                out.append({"target": s.parent, "file": src.name,
                            "state": ST_NOT_COMPILED})
            elif s.exists() and c.stat().st_mtime < s.stat().st_mtime:
                out.append({"target": s.parent, "file": src.name,
                            "state": ST_OLDER})
            else:
                out.append({"target": s.parent, "file": src.name, "state": ST_OK})
    return out
