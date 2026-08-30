"""MQL-indikatorok kitelepitese: mi van kint, es mi elavult?

A doksi kerese (Kapcsolat lap): "Indikator(ok) masolasa a megfelelo MetaTrader
mappaba … Innentol eszmeletlen fontos az MQ4 verziokezelese!"

⚠ MIERT ALLAPOT-KOZPONTU EZ, es nem csak egy masolo gomb: a `.mq4`/`.mq5` a
repoban el, a terminal a SAJATJABOL olvas. Ha a ketto elter, a terminal CSENDBEN
a regit futtatja — es a javitast hiaba keresed a kepernyon. Pontosan ez tortent
az MT4-es visszajatszas fejlesztesekor: kilenc verzio, mind nema hiba, mert nem
volt egyertelmu, melyik fut.

⚠ ES EGY VALODI LELET, amit ez a modul azonnal kidobott ezen a gepen: az
AppData-profilokban EGYETLEN MT5 indikator sem volt kint — a valodi telepites a
`C:/Metatrades/<broker>/` mappakban el (portable mod). Ha csak az AppData-t
neznenk, a lap magabiztosan azt mondana, hogy "kitelepitve". Ezert keres a modul
a portable telepitesek kozott is.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from core import mt_deploy as md

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A FORRASOK ─────────────────────────────────────────────────────────
for pf, ext in ((md.MT4, ".mq4"), (md.MT5, ".mq5")):
    src = md.sources(pf)
    check(f"{pf}: van forras a repoban", len(src) > 0, f"{len(src)} fajl")
    check(f"{pf}: mind {ext}", all(p.suffix == ext for p in src),
          str([p.name for p in src if p.suffix != ext]))
check("ismeretlen platform -> ures (nem robban)", md.sources("MT9") == [])


# ── 2. KITELEPITES egy IDEIGLENES „terminalba” ────────────────────────────
# ⚠ A teszt SOHA nem ir valodi terminal-mappaba: temp gyoker, es CSAK azt adjuk
# at `extra_roots`-ként. (Az AppData-profilok viszont valodiak — ezert a
# `deploy`-t nem hivjuk `extra_roots` nelkul.)
tmp = Path(tempfile.mkdtemp(prefix="mtdeploy_test_"))
fake = tmp / "Broker MT5"
(fake / "MQL5" / "Indicators").mkdir(parents=True)

tg = md.targets(md.MT5, [fake], include_appdata=False)
# ⚠ include_appdata=False → CSAK a temp mappa. Enelkul a `deploy` a VALODI
# terminal-mappakba is irna: az elso futaskor 15 fajlt tett a felhasznalo
# AppData-profiljaiba, amit vissza kellett vonni. A teszt SOHA nem nyulhat a
# felhasznalo terminaljaihoz.
check("csak a megadott gyoker celoz (nincs AppData mellekhatas)",
      len(tg) == 1 and str(tg[0]).startswith(str(fake)), str(tg))

st = md.status(md.MT5, [fake], include_appdata=False)
_mine = st
check("kezdetben MINDEN hianyzik",
      _mine and all(s["state"] == md.ST_MISSING for s in _mine),
      str({s["state"] for s in _mine}))

res = md.deploy(md.MT5, [fake], include_appdata=False)
check("a kitelepites masolt", len(res["copied"]) >= len(md.sources(md.MT5)),
      f"{len(res['copied'])} fajl")
check("...es nem hibazott", not res["errors"], str(res["errors"]))

st2 = md.status(md.MT5, [fake], include_appdata=False)
check("kitelepites utan MINDEN friss",
      st2 and all(s["state"] == md.ST_FRESH for s in st2),
      str({s["state"] for s in st2}))

# ⚠ Masodszorra NEM ir feleslegesen: a terminal a fajl-valtozasra ujratolt,
# tehat egy folosleges masolas ok nelkul indit ujra mindent.
res2 = md.deploy(md.MT5, [fake], include_appdata=False)
check("masodszorra mar nem masol (mind friss)", not res2["copied"],
      str(res2["copied"][:2]))
# ⚠ A kihagyottak kozt a FORRAS es a hozza tarolt BINARIS is szerepelhet,
# ezert legalabb annyi, ahany forras — nem pontosan annyi.
check("...hanem kihagyottkent szamolja", len(res2["skipped"]) >= len(st2),
      f"{len(res2['skipped'])} kihagyott / {len(st2)} forras")

# ── 3. ELAVULT eszlelese — EZ a modul letjogosultsaga ─────────────────────
_first = md.sources(md.MT5)[0]
_dst = fake / "MQL5" / "Indicators" / _first.name
_dst.write_text("// MAS TARTALOM\n", encoding="utf-8")
_after = {s["file"]: s["state"] for s in md.status(md.MT5, [fake], include_appdata=False)}
check("a MEGVALTOZOTT fajl ELAVULT-nak latszik",
      _after.get(_first.name) == md.ST_STALE, str(_after.get(_first.name)))
check("...a tobbi valtozatlanul friss",
      all(v == md.ST_FRESH for k, v in _after.items() if k != _first.name))
_r3 = md.deploy(md.MT5, [fake], include_appdata=False)
check("az elavultat FELULIRJA", any(_first.name in c for c in _r3["copied"]))

# ── 4. A LEFORDITOTT allapota ─────────────────────────────────────────────
# ⚠ Ez a legalattomosabb allapot: az uj forras kint van, de mellette a REGI
# .ex5 — es a terminal AZT futtatja. A "kitelepitve" tehat NEM jelenti, hogy az
# uj kod fut.
cb = {c["file"]: c["state"] for c in md.compiled_beside(md.MT5, [fake], include_appdata=False)}
# ⚠ Ahol a repoban VAN tarolt (egyezo) binaris, oda a kitelepites azt is kivitte
# — ott tehat mar "rendben" all. Amihez nincs tarolt, az "nincs fordítva".
_stored = {c["file"] for c in md.compiled_status(md.MT5) if c["state"] == md.ST_MATCH}
check("ahol nincs tarolt binaris, ott „nincs fordítva”",
      all(v == md.ST_NOT_COMPILED for k, v in cb.items() if k not in _stored),
      str({k: v for k, v in cb.items() if k not in _stored and v != md.ST_NOT_COMPILED}))
check("...ahol viszont van tarolt, azt a kitelepites KI IS VITTE",
      all(cb.get(k) == md.ST_OK for k in _stored if k in cb),
      str({k: cb.get(k) for k in _stored if k in cb}))
import os
import time
_ex = fake / "MQL5" / "Indicators" / (_first.stem + ".ex5")
_ex.write_bytes(b"regi")
# ⚠ A `shutil.copy2` MEGORZI a forras modositasi idejet, tehat a kitelepitett
# .mq5 a REPO ideje. A "regi leforditott" tehat ahhoz kepest legyen regebbi —
# a mostani idohoz merve a teszt hamisan atmenne/bukna.
_src_mt = (fake / "MQL5" / "Indicators" / _first.name).stat().st_mtime
os.utime(_ex, (_src_mt - 3600, _src_mt - 3600))
cb2 = {c["file"]: c["state"] for c in md.compiled_beside(md.MT5, [fake], include_appdata=False)}
check("a REGEBBI leforditottat eszreveszi",
      cb2.get(_first.name) == md.ST_OLDER, str(cb2.get(_first.name)))

# ── 5. Nincs celmappa -> BESZEDES hiba, nem nema no-op ────────────────────
_empty = tmp / "nincs_itt_terminal"
_empty.mkdir()
_r4 = md.deploy(md.MT5, [_empty], include_appdata=False)
check("nincs celmappa -> hibauzenet (nem csendes siker)",
      bool(_r4["errors"]) and not _r4["copied"], str(_r4))
check("...es az uzenet megmondja, mit tegyen",
      "Portable" in (_r4["errors"][0] if _r4["errors"] else ""),
      (_r4["errors"] or [""])[0][:70])

# ── 6. dry_run nem ir ─────────────────────────────────────────────────────
_fresh = tmp / "Broker2 MT4"
(_fresh / "MQL4" / "Indicators").mkdir(parents=True)
_d = md.deploy(md.MT4, [_fresh], dry_run=True, include_appdata=False)
check("dry_run: jelenti, mit MASOLNA", len(_d["copied"]) > 0)
check("...de tenylegesen NEM ir",
      not any((_fresh / "MQL4" / "Indicators").iterdir()))

shutil.rmtree(tmp, ignore_errors=True)


# ── 7. A felderites ne jarja be a lemezt ──────────────────────────────────
import time as _t
_t0 = _t.time()
_roots = md.discover_roots()
_el = _t.time() - _t0
check("a felderites GYORS (nem lemez-bejaras)", _el < 8.0, f"{_el:.1f} mp")
check("minden talalt gyokerben van MQL4 vagy MQL5",
      all((Path(r) / "MQL4").is_dir() or (Path(r) / "MQL5").is_dir()
          for r in _roots), str(_roots[:2]))



# ── 8. MI MICSODA: al-mappa + leiras ─────────────────────────────────────
# A keres: "nem latom, milyen fajlokat is szeretne odamasolni … egy rovid
# leiras sem artana, hogy melyik mit csinal".
_mt5 = {p.stem: p for p in md.sources(md.MT5)}
check("az MT5 forrasok kozt ott a tools/ tartalma is",
      "BacktestReplayer" in _mt5, str(sorted(_mt5)))
# ⚠ Az EXPERT az `Experts` mappaba valo — az `Indicators`-ba teve a terminal
# fel sem kinalja a Strategy Testerben.
check("a BacktestReplayer EXPERT-kent celoz",
      md.subfolder_of(_mt5["BacktestReplayer"]) == "Experts")
check("a TradeForgeViz INDIKATORKENT celoz",
      md.subfolder_of(_mt5["TradeForgeViz"]) == "Indicators")
check("minden forrasnak van leirasa",
      all(md.describe(p)[0] for pf in (md.MT4, md.MT5) for p in md.sources(pf)),
      str([p.name for pf in (md.MT4, md.MT5) for p in md.sources(pf)
           if not md.describe(p)[0]]))
check("van hasznalati utmutato mindket platformra",
      bool(md.USAGE.get(md.MT4)) and bool(md.USAGE.get(md.MT5)))
# A ket platform MAS hasznalatu — ez a szoveg lenyege.
check("...es a ketto NEM ugyanaz", md.USAGE[md.MT4] != md.USAGE[md.MT5])


# ── 9. A LEFORDITOTT TAROLASA es a VERZIO-ELLENORZES ─────────────────────
# A keres: "ne taroljuk megiscsak le az ex4/ex5 fajlokat? Ha azok is verziozva
# vannak, akkor nem lehet gond a tarolassal (figyelmeztetes johet, ha nem
# egyezik a verzio!)".
#
# ⚠ A `#property version` NEM eleg: kezzel irjak, es ket kulonbozo forras
# viselheti ugyanazt. Ezert a jegyzek a forras TARTALMANAK ujjlenyomatat
# tarolja — az akkor is elter, ha a verzioszamot elfelejtettek emelni.
check("a forras-verzio kiolvashato",
      md.source_version(md.sources(md.MT4)[0]) != "",
      md.source_version(md.sources(md.MT4)[0]))

_cs = md.compiled_status(md.MT5)
check("minden forrasra van tarolt-allapot", len(_cs) == len(md.sources(md.MT5)))
check("az allapot ertelmes ertek",
      all(c["state"] in (md.ST_NOT_STORED, md.ST_MATCH, md.ST_OTHER_SOURCE)
          for c in _cs), str({c["state"] for c in _cs}))

import inspect as _i
_src = _i.getsource(md.capture_compiled)
check("a beolvasas a forras SHA-jat is rogziti (nem csak a verziot)",
      "source_sha1" in _src and "source_version" in _src)
_dep = _i.getsource(md.deploy)
# ⚠ A tarolt binaris CSAK akkor mehet ki, ha a MOSTANI forrashoz keszult —
# kulonben ugyanaz a "regi fut, uj forras" allapot allna elo, csak a repobol
# szallitva.
check("a kitelepites csak EGYEZO leforditottat visz ki",
      "ST_MATCH" in _dep and "stale_compiled" in _dep)


# ── 10. A BEOLVASAS NEM KOTHET REGI BINARIST UJ FORRASHOZ ────────────────
# ⚠ Ez elo is allt: a verzio-sor hozzaadasa utan a beolvasas a MEG A REGI
# forrasbol forditott .ex5-oket az UJ forras ujjlenyomatahoz kotötte volna, es a
# felulet magabiztosan "egyezik"-et mutatott volna. Pontosan az az allapot, ami
# ellen az egesz modul keszult.
_t2 = Path(tempfile.mkdtemp(prefix="mtcapture_test_"))
_term = _t2 / "Broker MT4"
_ind = _term / "MQL4" / "Indicators"
_ind.mkdir(parents=True)
_src0 = md.sources(md.MT4)[0]
_dep = _ind / _src0.name
shutil.copy2(_src0, _dep)                       # kitelepitve (byte-azonos)
_exf = _dep.with_suffix(".ex4")
_exf.write_bytes(b"binaris")
os.utime(_exf, None)                            # a binaris UJABB a forrasnal

_cdir = md._compiled_dir(md.MT4)
_backup = None
if _cdir.exists():
    _backup = Path(tempfile.mkdtemp()) / "compiled_backup"
    shutil.copytree(_cdir, _backup)
    shutil.rmtree(_cdir)

r1 = md.capture_compiled(md.MT4, [_term], include_appdata=False)
check("egyezo forras + ujabb binaris -> ATVESZI",
      _src0.stem + ".ex4" in r1["taken"], str(r1))

# Most a TERMINALBAN levo forras ELTER a repotol (mintha kozben szerkesztettuk
# volna a repo-forrast, es meg nem telepitettuk ki).
_dep.write_text("// MAS SZOVEG" + chr(10), encoding="utf-8")
shutil.rmtree(_cdir, ignore_errors=True)
r2 = md.capture_compiled(md.MT4, [_term], include_appdata=False)
check("ELTERO forras -> NEM veszi at (nem koti hamisan)",
      _src0.name in r2["missing"] and not r2["taken"], str(r2))

# Es ha a binaris REGEBBI a forrasnal, akkor sem.
shutil.copy2(_src0, _dep)
os.utime(_exf, (_dep.stat().st_mtime - 60, _dep.stat().st_mtime - 60))
shutil.rmtree(_cdir, ignore_errors=True)
r3 = md.capture_compiled(md.MT4, [_term], include_appdata=False)
check("REGEBBI binaris -> NEM veszi at", _src0.name in r3["missing"], str(r3))

shutil.rmtree(_cdir, ignore_errors=True)
if _backup is not None:
    shutil.copytree(_backup, _cdir)
shutil.rmtree(_t2, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
