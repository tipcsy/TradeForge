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
      _mine and all(s["state"] == "hiányzik" for s in _mine),
      str({s["state"] for s in _mine}))

res = md.deploy(md.MT5, [fake], include_appdata=False)
check("a kitelepites masolt", len(res["copied"]) >= len(md.sources(md.MT5)),
      f"{len(res['copied'])} fajl")
check("...es nem hibazott", not res["errors"], str(res["errors"]))

st2 = md.status(md.MT5, [fake], include_appdata=False)
check("kitelepites utan MINDEN friss",
      st2 and all(s["state"] == "friss" for s in st2),
      str({s["state"] for s in st2}))

# ⚠ Masodszorra NEM ir feleslegesen: a terminal a fajl-valtozasra ujratolt,
# tehat egy folosleges masolas ok nelkul indit ujra mindent.
res2 = md.deploy(md.MT5, [fake], include_appdata=False)
check("masodszorra mar nem masol (mind friss)", not res2["copied"],
      str(res2["copied"][:2]))
check("...hanem kihagyottkent szamolja", len(res2["skipped"]) == len(st2))

# ── 3. ELAVULT eszlelese — EZ a modul letjogosultsaga ─────────────────────
_first = md.sources(md.MT5)[0]
_dst = fake / "MQL5" / "Indicators" / _first.name
_dst.write_text("// MAS TARTALOM\n", encoding="utf-8")
_after = {s["file"]: s["state"] for s in md.status(md.MT5, [fake], include_appdata=False)}
check("a MEGVALTOZOTT fajl ELAVULT-nak latszik",
      _after.get(_first.name) == "elavult", str(_after.get(_first.name)))
check("...a tobbi valtozatlanul friss",
      all(v == "friss" for k, v in _after.items() if k != _first.name))
_r3 = md.deploy(md.MT5, [fake], include_appdata=False)
check("az elavultat FELULIRJA", any(_first.name in c for c in _r3["copied"]))

# ── 4. A LEFORDITOTT allapota ─────────────────────────────────────────────
# ⚠ Ez a legalattomosabb allapot: az uj forras kint van, de mellette a REGI
# .ex5 — es a terminal AZT futtatja. A "kitelepitve" tehat NEM jelenti, hogy az
# uj kod fut.
cb = {c["file"]: c["state"] for c in md.compiled_beside(md.MT5, [fake], include_appdata=False)}
check("forditas nelkul: „nincs fordítva”",
      all(v == "nincs fordítva" for v in cb.values()), str(set(cb.values())))
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
      cb2.get(_first.name) == "RÉGEBBI a forrásnál", str(cb2.get(_first.name)))

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



# ── 8. FORDITAS: a sikert a KIMENETEN merjuk, nem a kilepesi kodon ────────
# ⚠ Ezen a gepen a MetaEditor MINDEN dokumentalt alakra (`/compile:`, `+/log`,
# `+/portable`, relativ ut) 0,2 mp alatt kilepett rc=0-val, naplo nelkul — es
# NEM forditott: sem az .ex4/.ex5 nem frissult, sem uj fajl nem keletkezett
# sehol a gepen. Ha csak a kilepesi kodot neznenk, a felulet magabiztosan
# "rendben"-t irna, a terminal pedig tovabbra is a REGI leforditottat futtatna.
import inspect as _i
_src = _i.getsource(md.compile_file)
check("a forditas a KIMENET idejet nezi (nem csak a kilepesi kodot)",
      "before" in _src and "after > before" in _src)
check("...es sikert CSAK akkor jelent", "lefordítva" in _src)
check("rc=0 + valtozatlan kimenet -> NEM siker, es megmondja a teendot",
      "nem fordított" in _src and "F7" in _src)
# A naplo UTF-16; utf-8-cal olvasva a hibauzenet elveszne.
check("a naplot UTF-16-kent olvassa", 'encoding="utf-16"' in _src)

# A MetaEditor keresese a PORTABLE telepitesekben is (ott van, ahol a terminal).
_me4 = md.metaeditor(md.MT4, _roots)
_me5 = md.metaeditor(md.MT5, _roots)
check("MT4 MetaEditor megvan", _me4 is not None, str(_me4))
check("MT5 MetaEditor megvan", _me5 is not None, str(_me5))
# ⚠ A MEGFELELO peldany kell: az MT4-e .mq4-et fordit, az MT5-e .mq5-ot.
if _me4 and _me5:
    check("a ket platform KULON MetaEditort kap", _me4 != _me5)
    check("az MT4-e MQL4-es telepitesbol jon",
          (Path(_me4).parent / "MQL4").is_dir(), str(_me4))
    check("az MT5-e MQL5-os telepitesbol jon",
          (Path(_me5).parent / "MQL5").is_dir(), str(_me5))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
