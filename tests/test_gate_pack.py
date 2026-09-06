"""`.tfg` — a KAPU-CSOMAG (0007).

⚠ MIT KELL BIZONYITANI. Nem azt, hogy a zip elkeszul — azt, hogy egy IDEGEN
gepen keszult kapu telepites utan TENYLEG MER. A `.tfs`-nel ez adott volt (a
strategiat a registry deriti fel); a kapuknal viszont a meres a motor kozepen,
kezzel beirva elt, tehat egy telepitett kapu a lemezen ult volna, listaban
sehol. A v3.47.0 ezt oldotta meg — ez a teszt azt orzi, hogy meg is maradt.

⚠ A BIZTONSAGI KAPUK ITT IS KELLENEK, es ugyanazok, mint a `.tfs`-nel:
zip-slip, csak megengedett fajlok, ellenorzoosszeg, ketlepcsos telepites.
Egy `.tfg` FUTTATHATO PYTHON KOD.
"""
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

from core import gates as G      # noqa: E402
from gates import pack           # noqa: E402
from gates import paths as _gp   # noqa: E402

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


KULCS = "teszt_kapu_0007"
MODUL = "teszt_kapu_0007_gate"

MODUL_KOD = f'''"""Teszt-kapu — a `.tfg` korut ellenorzesehez."""

GATE = {{"key": "{KULCS}", "default_effect": "none", "phase": "signal"}}


def measure(ctx):
    """Bukik, ha a jel SELL. (Csak azert, hogy legyen merheto viselkedes.)"""
    return ctx.signal == "SELL", None
'''


def _csomag(cel: Path, *, kulcs=KULCS, modul=MODUL, kod=MODUL_KOD, api=None,
            phase="signal", doksi=True, sha_rontas=False, extra=None) -> Path:
    """Egy `.tfg` OSSZEALLITASA kezzel — pontosan ugy, ahogy egy idegen gepen
    keszult csomag erkezne."""
    tartalom = {f"{modul}.py": kod.encode("utf-8")}
    if doksi:
        tartalom[f"docs/{kulcs}.md"] = b"# Teszt-kapu\n\nA korut ellenorzesehez.\n"
    man = {
        "kind": pack.KIND, "format": pack.PACK_FORMAT, "key": kulcs,
        "module": f"{modul}.py", "phase": phase,
        "api": pack.GATE_API if api is None else api,
        "version": "1.0.0", "created_by": "teszt",
        "helpers": [], "docs": [f"docs/{kulcs}.md"] if doksi else [],
        "sha256": {},
    }
    import hashlib
    for a, b in tartalom.items():
        h = hashlib.sha256(b).hexdigest()
        man["sha256"][a] = ("0" * 64) if sha_rontas else h
    with zipfile.ZipFile(cel, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(man, ensure_ascii=False))
        for a, b in tartalom.items():
            z.writestr(a, b)
        for a, b in (extra or {}).items():
            z.writestr(a, b)
    return cel


def _takarit():
    """A telepitett teszt-kapu eltavolitasa — a teszt ne hagyjon maga utan semmit."""
    for p in (_gp.DIR / f"{MODUL}.py", _gp.docs_dir() / f"{KULCS}.md",
              _gp.docs_dir() / f"{KULCS}.en.md"):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    import sys as _s
    _s.modules.pop(f"gates.{MODUL}", None)
    G.refresh_registry()


_takarit()          # ha egy korabbi futas felenget hagyta
TMP = Path(tempfile.mkdtemp(prefix="tfg_teszt_"))

try:
    # ── 1. A BEEPITETT kapuk becsomagolhatok ────────────────────────────
    _hiba = []
    for k in G.KEYS:
        try:
            q = pack.build(k, out_dir=str(TMP))
            m = pack.inspect(q)
            if not any(f.startswith("docs/") for f in m["_files"]):
                _hiba.append(f"{k}: nincs doksi a csomagban")
            if m["module"] != f"{G.entry_of(k)['module']}.py":
                _hiba.append(f"{k}: rossz modul-nev")
        except Exception as e:
            _hiba.append(f"{k}: {type(e).__name__}: {e}")
    check_("mind a hat beépített kapu becsomagolható (a doksijával)",
           not _hiba, "; ".join(_hiba))

    # ⚠ A DOKSI A KULCSROL kapja a nevet, nem a modulrol: `spread_gate.py` ->
    # `docs/spread.md`. Ha a csomagolo a modul nevet hasznalna, a telepitett
    # kapu leirasa NEMAN nem jelenne meg.
    _m = pack.inspect(pack.build("spread", out_dir=str(TMP)))
    check_("a doksi a KULCSRÓL kapja a nevét (spread_gate.py → docs/spread.md)",
           "docs/spread.md" in _m["_files"] and "spread_gate.py" in _m["_files"],
           str(_m["_files"]))

    # ── 2. A TELJES KORUT: idegen csomag -> telepites -> TENYLEG MER ────
    _p = _csomag(TMP / "uj.tfg")
    _man, _gondok = pack.check(_p)
    check_("egy ÚJ kulcsú csomag telepíthető", not _gondok, str(_gondok))
    check_("a kapu telepítés ELŐTT nincs a registryben", KULCS not in G.KEYS)

    _res = pack.install(_p)
    check_("a telepítés után MEGJELENIK a registryben", KULCS in G.KEYS,
           str(G.KEYS))
    check_("...a fázisa is átjön", G.phase_of(KULCS) == G.PHASE_SIGNAL)
    check_("...a modulja betölthető", G.gate_module(KULCS) is not None)

    # ⚠ EZ A LENYEG: a motor TENYLEG hivja-e?
    _f_sell, _ = G.measure(KULCS, G.GateCtx(signal="SELL"))
    _f_buy, _ = G.measure(KULCS, G.GateCtx(signal="BUY"))
    check_("a telepített kapu MÉR (SELL-re bukik, BUY-ra nem)",
           _f_sell is True and _f_buy is False, f"sell={_f_sell} buy={_f_buy}")
    check_("...és benne van a JEL-fázis hurokjában",
           KULCS in G.keys_in_phase(G.PHASE_SIGNAL))

    # ⚠ A TELEPITETT KAPU NEM SZOL BELE, amig be nem kapcsolod.
    check_("a telepített kapu hatása `none` (nem kezd némán kereskedni)",
           G.default_effect_of(KULCS) == G.EFFECT_NONE)
    check_("...és a telepítő ezt VISSZA IS ADJA", _res.get("needs_enable") is True)
    check_("a telepített fájlok listája megvan", bool(_res.get("installed")))

    # ── 3. FELULIRAS ───────────────────────────────────────────────────
    _m2, _g2 = pack.check(_p)
    check_("ugyanaz a kulcs másodszor NEM telepíthető", bool(_g2), str(_g2))
    _m3, _g3 = pack.check(_p, overwrite=True)
    check_("...felülírással viszont igen", not _g3, str(_g3))

    _takarit()
    check_("a takarítás után eltűnik a registryből", KULCS not in G.KEYS)

    # ── 4. BIZTONSAGI KAPUK ────────────────────────────────────────────
    # ZIP-SLIP: a projekten KIVULRE mutato bejegyzes.
    for _rossz in ("../kilogo.py", "docs/../../kilogo.md", "/abs.py",
                   "melyebb/mappa/x.py"):
        _pz = _csomag(TMP / "slip.tfg", extra={_rossz: b"x"})
        try:
            pack.inspect(_pz)
            check_(f"zip-slip elutasítva: {_rossz!r}", False, "ÁTMENT!")
        except pack.PackError:
            check_(f"zip-slip elutasítva: {_rossz!r}", True)

    # NEM MEGENGEDETT KITERJESZTES (a `.tfs` json-t enged, a `.tfg` NEM: egy
    # kapu szamai a config.json-ban laknak, paronkent — azt egy csomag nem
    # hozhatja magaval).
    _pj = _csomag(TMP / "json.tfg", extra={"config.json": b"{}"})
    try:
        pack.inspect(_pj)
        check_("a `.tfg` NEM enged config.json-t", False, "ÁTMENT!")
    except pack.PackError:
        check_("a `.tfg` NEM enged config.json-t (a kapu számai a configban laknak)",
               True)

    # ELLENORZOOSSZEG
    _ps = _csomag(TMP / "serult.tfg", sha_rontas=True)
    try:
        pack.install(_ps)
        check_("sérült csomag elutasítva", False, "TELEPÜLT!")
    except pack.PackError as e:
        check_("sérült csomag elutasítva (ellenőrzőösszeg)", "SÉRÜLT" in str(e))
    check_("...és NEM települt félig", KULCS not in G.KEYS
           and not (_gp.DIR / f"{MODUL}.py").exists())

    # ROSSZ FAJTA: egy `.tfs`-t adunk ide.
    _pt = TMP / "strat.tfs"
    with zipfile.ZipFile(_pt, "w") as z:
        z.writestr("manifest.json", json.dumps(
            {"kind": "tradeforge-strategy", "format": 1, "name": "x"}))
    try:
        pack.inspect(_pt)
        check_("egy `.tfs` NEM megy át kapu-csomagként", False, "ÁTMENT!")
    except pack.PackError as e:
        check_("egy `.tfs` NEM megy át kapu-csomagként, és BESZÉDESEN mondja",
               "STRATÉGIA" in str(e), str(e)[:60])

    # API-VERZIO: a ket irany KET KULON uzenet (mas a teendo).
    _pa = _csomag(TMP / "ujabb.tfg", api=pack.GATE_API + 1)
    _ok, _i = pack.compatible(pack.GATE_API + 1)
    check_("újabb API → „frissítsd a programot”", not _ok and "frissítsd" in _i, _i)
    _ok2, _i2 = pack.compatible(pack.GATE_API - 1)
    check_("régebbi API → „a kaput át kell írni”",
           not _ok2 and "át kell írni" in _i2, _i2)

    # HIANYZO DOKSI es ISMERETLEN FAZIS
    _pd = _csomag(TMP / "nodoc.tfg", doksi=False)
    check_("doksi nélküli csomag NEM telepíthető",
           any("leírás" in g for g in pack.check(_pd)[1]))
    _pf = _csomag(TMP / "rosszfazis.tfg", phase="valamikor")
    check_("ismeretlen mérési fázis → elutasítás",
           any("fázis" in g for g in pack.check(_pf)[1]))

    # ── 5. A FELDERITES HIBAI NEM NEMAK ────────────────────────────────
    # `measure` nelkuli modul: a felderites kihagyja (es naploz).
    _rossz_modul = _gp.DIR / f"{MODUL}.py"
    _rossz_modul.write_text(
        f'GATE = {{"key": "{KULCS}", "phase": "signal"}}\n', encoding="utf-8")
    G.refresh_registry()
    check_("`measure` nélküli modul NEM kerül be a registrybe", KULCS not in G.KEYS)
    _takarit()

finally:
    _takarit()
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)

# ── 5b. A FELULETI BEKOTES ─────────────────────────────────────────────
# ⚠ A `.tfs`-nel a csomagolas a ⚙ Beallitas -> Strategiak lapon van. A kapuknal
# ugyanez a KAPUK lapra kerult. Ez forras-szintu or: egy kesobbi szerkesztes
# konnyen kiejti a gombokat, es akkor a `.tfg` csak parancssorbol lenne elerheto
# — a felhasznalo szamara pedig „nincs is".
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check_("a felulet a KAPU-csomagolot hasznalja (gates.pack)",
       "from gates import pack as _gpack" in _gui)
for _k in ("gpack.btn.install", "gpack.btn.export"):
    check_(f"...és ott a gomb ({_k})", f'_t("{_k}")' in _gui)
check_("a telepites utan a lista AZONNAL bovul",
       "_gate_ed.add(man[\"key\"]" in _gui,
       "különben a sikeres telepítés után „nem történt semmi”")
check_("...és a felhasznalo megtudja, hogy a kapu meg nem szur",
       '_t("gpack.msg.needs_enable")' in _gui)
# A megerosites ELOTT lathato, mit hozunk be — a telepites KODOT hoz be.
check_("a megerősítő ablak felsorolja a fajlokat",
       "gpack.dlg.confirm.body" in _gui and "files=" in _gui)

import json as _json
for _lang in ("hu", "en"):
    _d = _json.loads((ROOT / "lang" / f"{_lang}.json").read_text(encoding="utf-8"))
    _hiany = [k for k in ("gpack.btn.install", "gpack.btn.export", "gpack.hint",
                          "gpack.dlg.open", "gpack.dlg.save",
                          "gpack.dlg.overwrite.title", "gpack.dlg.overwrite.body",
                          "gpack.dlg.confirm.title", "gpack.dlg.confirm.body",
                          "gpack.filetype", "gpack.msg.installed",
                          "gpack.msg.needs_enable", "gpack.msg.pick_first")
              if k not in _d]
    check_(f"{_lang}: minden `.tfg` felirat megvan", not _hiany, str(_hiany))


# ── 6. A KERET epsege a teszt UTAN ─────────────────────────────────────
check_("a beépített kapuk sértetlenek maradtak",
       G.KEYS == ("spread", "tf_align", "market", "momentum", "cost", "volatility"),
       str(G.KEYS))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
