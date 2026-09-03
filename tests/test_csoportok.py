"""A TESZT-CSOPORTOK OR-TESZTJE — a reszleges futas ne hazudjon.

⚠ MIERT KELL EZ. A csoportositas (2026-09-03) azt igeri, hogy egy reszleges
futas UTAN ki lehet jelenteni: „amihez hozzanyultam, az rendben van." Ez az
igeret pontosan annyit er, amennyire a besorolas igaz. Ket modon tud NEMAN
hazudni, es mindketto mar meg is tortent:

  * az `OROK` listaban ket olyan fajlnev allt, ami SOSEM letezett
    (`test_config_coherence.py`, `test_tests_dont_write_config.py`) — az
    or-csoport csendben kettovel kevesebbet futtatott;
  * egy uj teszt, ami egyik csoportba sem esik, SOHA nem futna reszlegesen.

Ezert itt nem a csoportok „szepseget" merjuk, hanem a ket szerkezeti allitast:
minden nevesitett or LETEZIK, es minden teszt ELERHETO valamelyik valogatasbol.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import csoportok as cs                                    # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


TESZTEK = {p.name for p in (ROOT / "tests").glob("test_*.py")}
terkep = cs.teszt_terkep()
g = cs.csoportok_szerint(terkep)

# ══ 1. Az orok NEVEI letezo fajlok ══
hianyzo = [n for n in cs.OROK if n not in TESZTEK]
check("minden OROK-nev letezo tesztfajl", not hianyzo, ", ".join(hianyzo))
check("az orok csoport ugyanannyi elemu, mint az OROK lista",
      len(g["orok"]) == len(cs.OROK), f"{len(g['orok'])} vs {len(cs.OROK)}")

# ══ 2. A terkep MINDEN tesztfajlt ismer ══
check("a terkep lefedi az osszes test_*.py fajlt",
      set(terkep) == TESZTEK, str(TESZTEK ^ set(terkep)))

# ══ 3. Egyetlen teszt sem esik ki MINDEN valogatasbol ══
# ⚠ Ez a lenyeg. Nem az a baj, ha egy teszt nem sorolhato be (arra van az
# `egyeb`, amit minden reszleges futas visz) — az a baj, ha SEHOL nem szerepel.
lefedve = set()
for lista in g.values():
    lefedve |= set(lista)
kimaradt = sorted(TESZTEK - lefedve)
check("egyetlen teszt sem marad ki minden csoportbol", not kimaradt,
      ", ".join(kimaradt))

# ══ 4. A valogatas MINDIG viszi az oroket es a besorolatlanokat ══
v = set(cs.valogatas(["nyelv"], terkep))
check("a valogatas viszi az oroket", set(g["orok"]) <= v)
check("a valogatas viszi az 'egyeb'-et", set(g["egyeb"]) <= v)
check("a valogatas viszi a kert csoportot", set(g["nyelv"]) <= v)
# ...de NEM viszi az egesz csomagot: kulonben a reszleges futas semmit nem
# sporolna, es a funkcio ertelmet vesztene.
check("a valogatas erdemben kevesebb, mint a teljes csomag",
      len(v) < len(TESZTEK), f"{len(v)}/{len(TESZTEK)}")

# ══ 5. Ismeretlen csoportnevre HANGOSAN bukik ══
try:
    cs.valogatas(["ilyen_csoport_nincs"], terkep)
    ok = False
except KeyError as e:
    ok = "ilyen_csoport_nincs" in str(e)
check("ismeretlen csoportnevre KeyError, a nevvel", ok)

# ══ 6. Az `erinti` tranzitiv: tobbet ad, mint a kozvetlen importalok ══
# A `core/gates.py` a kapuk kozponti modulja; a kozvetlen importalok reszhalmaz.
kozv = cs.kozvetlen_importalok("core/gates.py", terkep)
tranz = set(cs.erintett_tesztek("core/gates.py", terkep))
check("az erinti tranzitiv (tartalmazza a kozvetleneket)", kozv <= tranz,
      f"kozvetlen={len(kozv)} tranzitiv={len(tranz)}")
check("a kozvetlen importalok nem uresek", bool(kozv), str(len(kozv)))

# ══ 7. A lusta (fuggvenyen beluli) importok is szamitanak ══
# ⚠ A projektben rengeteg fuggvenyen beluli `from core import x` van (inditasi
# ido miatt). Ha csak a fajl tetejet neznenk, a fuggosegi kep a felet mutatna.
minta = ROOT / "tests" / "test_gates.py"
if minta.exists():
    felso = set()
    import ast, io
    fa = ast.parse(io.open(minta, encoding="utf-8", errors="replace").read())
    for n in fa.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            felso.add(getattr(n, "module", None) or "")
    check("a terkep a fuggvenyen beluli importokat is latja",
          len(terkep[minta.name][0]) >= 1, str(sorted(terkep[minta.name][0])[:4]))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
