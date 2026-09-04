""".tfs — a strategia-csomag (v3.31.0).

⚠ A KERES (2026-09-02): „Mi is csinalhatnank valami tfs (TradeForgeStrategy)
kiterjesztesu egyedi fajlt (ami egy atnevezett zip lenne.) … Nalunk is alapvetoen
3-4 fajl van amit be lehetne csomagolni: programkod.py, docs/valami_hu.md,
docs/valami_en.md, config.json"

AMIT ITT ORZUNK, FONTOSSAGI SORRENDBEN:

  1. A TELEPITES SOSEM FELIG SIKERUL. Egy felig telepitett strategiat a
     felderites megtalal, a hianyzo fele miatt viszont importhibaval esik szet —
     es a naplo egy nappal kesobb mar senkinek nem mond semmit. Ezert a
     kicsomagolas ideiglenes mappaba megy, es CSAK a teljes ellenorzes utan
     kerul a helyere.
  2. A ZIP-SLIP ZARVA. Egy zip-bejegyzes neve lehet `../../valami`; naiv
     kicsomagolasnal ez a projekten KIVULRE ir.
  3. A SEGEDMODULOK IS UTAZNAK. Az `ml_ai` ket sajat modult hasznal
     (`ml_features`, `ml_train`); egy csomag, ami csak egy `.py`-t visz, ezt a
     strategiat nem tudna atadni — a hiany pedig a betoltes UTAN derulne ki.
  4. Az API-kapu itt is ervenyes (lasd `test_strategy_contract.py`).

⚠ EZ A TESZT SOHA NEM IR AZ ELES `strategies/` MAPPABA. A telepitest ideiglenes
celra iranyitja (`paths.DIR`), es a vegen visszaallitja. A projektben ez a
szabaly mar ketszer vert vissza (lasd `tests/run_all.py` orzo-fejleceit).
"""
import io
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


from strategy import pack, paths                      # noqa: E402
from strategy import registered_strategy_names        # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tfs_teszt_"))
EREDETI_DIR = paths.DIR


def _ures_cel() -> Path:
    """Friss, URES `strategies/`-szeru mappa a telepitesnek."""
    d = TMP / f"cel{len(list(TMP.glob('cel*')))}"
    (d / "config").mkdir(parents=True)
    (d / "docs").mkdir(parents=True)
    return d


def _ujracsomagol(forras: Path, cel: Path, modosit=None) -> Path:
    """A csomag masolata, tetszoleges modositassal (`{arch: uj_bajtok}` vagy a
    manifest atirasa). Igy tudunk SERULT/ROSSZINDULATU csomagot elmerni anelkul,
    hogy kezzel kellene zipet gyartani."""
    modosit = modosit or {}
    with zipfile.ZipFile(forras) as be:
        elemek = {i.filename: be.read(i.filename) for i in be.infolist()
                  if not i.is_dir()}
    elemek.update({k: v for k, v in modosit.items() if v is not None})
    for k, v in modosit.items():
        if v is None:
            elemek.pop(k, None)
    with zipfile.ZipFile(cel, "w", zipfile.ZIP_DEFLATED) as ki:
        for n, b in elemek.items():
            ki.writestr(n, b)
    return cel


# ══ 1. CSOMAGOLAS: a tartalom az, aminek lennie kell ═══════════════════
csomag = pack.build("wpr_sma", TMP)
man = pack.inspect(csomag)
check("a csomag `.tfs` kiterjesztesu", csomag.suffix == pack.SUFFIX, csomag.name)
check("a manifest megnevezi a strategiat", man["name"] == "wpr_sma")
check("...es az API-verziot", int(man["api"]) >= 1, str(man.get("api")))
check("...es hogy melyik program keszitette", "TradeForge" in man["created_by"],
      man["created_by"])
check("a modul benne van", "wpr_sma.py" in man["_files"])
check("a config benne van", "config.json" in man["_files"])
check("a leiras is (mindket nyelven)",
      "docs/wpr_sma.md" in man["_files"] and "docs/wpr_sma.en.md" in man["_files"],
      str(man["_files"]))
check("minden fajlrol van ellenorzoosszeg",
      set(man["sha256"]) == set(man["_files"]), str(set(man["_files"]) ^ set(man["sha256"])))

# ⚠ A SEGEDMODULOK. Enelkul az `ml_ai` csomagja hasznalhatatlan lenne.
check("az ml_ai segedmoduljait megtalalja",
      pack.helper_modules("ml_ai") == ["ml_features", "ml_train"],
      str(pack.helper_modules("ml_ai")))
check("egy segedmodul nelkuli strategianal ures a lista",
      pack.helper_modules("wpr_sma") == [], str(pack.helper_modules("wpr_sma")))
ml = pack.build("ml_ai", TMP)
man_ml = pack.inspect(ml)
check("...es a csomagba is bekerulnek",
      {"ml_features.py", "ml_train.py"} <= set(man_ml["_files"]),
      str(man_ml["_files"]))
# ⚠ EGY MASIK STRATEGIA NEM SEGEDMODUL: az onallo egyseg.
_masok = {f"{n}.py" for n in registered_strategy_names()} - {"ml_ai.py"}
check("masik strategia NEM kerul a csomagba",
      not (_masok & set(man_ml["_files"])),
      str(_masok & set(man_ml["_files"])))


# ══ 2. TELEPITES ideiglenes celba ══════════════════════════════════════
try:
    cel = _ures_cel()
    paths.DIR = cel
    m = pack.install(csomag, overwrite=True)
    _van = sorted(str(Path(f).relative_to(cel)).replace("\\", "/")
                  for f in m["installed"])
    check("a telepites a helyere teszi a fajlokat",
          _van == ["config/wpr_sma.json", "docs/wpr_sma.en.md",
                   "docs/wpr_sma.md", "wpr_sma.py"], str(_van))
    check("...es tenyleg leteznek", all(Path(f).exists() for f in m["installed"]))

    # ══ 3. A TELEPITES SOSEM FELIG SIKERUL ═════════════════════════════
    # ⚠ EZ A LEGFONTOSABB ALLITAS. Serult csomagnal a cel mappa MARADJON URES:
    # egy felig telepitett strategiat a felderites megtalalna, es importhibaval
    # esne szet — egy nappal kesobb pedig senki nem tudna, miert.
    cel2 = _ures_cel()
    paths.DIR = cel2
    serult = _ujracsomagol(csomag, TMP / "serult.tfs",
                           {"wpr_sma.py": b"# megbutykolva\n"})
    try:
        pack.install(serult, overwrite=True)
        _hiba = "nem dobott hibat"
    except pack.PackError as e:
        _hiba = ""
        _uzenet = str(e)
    check("a SERULT csomag elutasitva (ellenorzoosszeg)", not _hiba,
          _hiba or _uzenet[:60])
    _maradek = [p for p in cel2.rglob("*") if p.is_file()]
    check("...es a cel mappa ERINTETLEN maradt", not _maradek,
          ", ".join(p.name for p in _maradek))
finally:
    paths.DIR = EREDETI_DIR

check("a teszt visszaallitotta az eles utvonalat", paths.DIR == EREDETI_DIR)


# ══ 4. ZIP-SLIP es a nem megengedett fajlok ════════════════════════════
for rossz_nev in ("../gonosz.py", "..\\gonosz.py", "docs/../../gonosz.py",
                  "melyebb/mappa/x.py"):
    z = _ujracsomagol(csomag, TMP / "slip.tfs", {rossz_nev: b"x = 1\n"})
    try:
        pack.inspect(z)
        ok = False
    except pack.PackError:
        ok = True
    check(f"elutasitja a bejegyzest: {rossz_nev}", ok)

z = _ujracsomagol(csomag, TMP / "rosszfajl.tfs", {"adat.bin": b"\x00\x01"})
try:
    pack.inspect(z)
    _ok = False
except pack.PackError:
    _ok = True
check("elutasitja a nem megengedett fajltipust (.bin)", _ok)


# ══ 5. A MANIFEST ellenorzese ══════════════════════════════════════════
def _manifest_csere(uj: dict, nev="man.tfs") -> Path:
    m = json.loads(zipfile.ZipFile(csomag).read("manifest.json").decode("utf-8"))
    m.update(uj)
    return _ujracsomagol(csomag, TMP / nev,
                         {"manifest.json": json.dumps(m).encode("utf-8")})


for mezo, ertek, cimke in (
        ({"kind": "valami-mas"}, None, "idegen `kind`"),
        ({"format": pack.PACK_FORMAT + 1}, None, "UJABB csomag-formatum"),
        ({"name": ""}, None, "hianyzo strategia-nev")):
    try:
        pack.inspect(_manifest_csere(mezo))
        _ok = False
    except pack.PackError:
        _ok = True
    check(f"elutasitja: {cimke}", _ok)

# ⚠ MANIFEST NELKUL ez nem is a mi formatumunk.
nincs_man = _ujracsomagol(csomag, TMP / "nincsman.tfs", {"manifest.json": None})
try:
    pack.inspect(nincs_man)
    _ok = False
except pack.PackError as e:
    _ok = "manifest" in str(e).lower()
check("manifest nelkul elutasit, es meg is mondja", _ok)

# Nem zip
(TMP / "nemzip.tfs").write_bytes(b"nem zip vagyok")
try:
    pack.inspect(TMP / "nemzip.tfs")
    _ok = False
except pack.PackError:
    _ok = True
check("a nem-zip fajlt is elutasitja", _ok)


# ══ 6. AZ API-KAPU a csomagra is ervenyes ══════════════════════════════
from strategy.base import STRATEGY_API                # noqa: E402
jovo = _manifest_csere({"api": STRATEGY_API + 3, "name": "_teszt_uj"}, "jovo.tfs")
_m, _gondok = pack.check(jovo)
check("egy UJABB API-ju csomag nem telepitheto", bool(_gondok), str(_gondok))
check("...es a PROGRAM frissiteset keri",
      any("TradeForge" in g for g in _gondok), str(_gondok))

# Letezo nev: gond — de `overwrite` mellett nem.
_m2, _g2 = pack.check(csomag)
check("letezo nevre figyelmeztet", bool(_g2), str(_g2))
_m3, _g3 = pack.check(csomag, overwrite=True)
check("...de `overwrite` mellett nem", not _g3, str(_g3))


# ══ 7. A CLI ott van, ahol keresni fogjuk ══════════════════════════════
_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("a `pack` parancs letezik", '"pack":' in _main)
check("a `install` parancs letezik", '"install":' in _main)
# ⚠ A telepites KODOT hoz be: ne lehessen veletlenul, egy leutessel megtenni.
check("a telepites megerositest ker (--yes)", "--yes" in _main)
check("...es KIMONDJA, hogy futtathato kodrol van szo",
      "PYTHON KODOT" in _main)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
