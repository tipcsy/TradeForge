"""A KAPUK SAJAT CSOMAGJA — a rendezes ne kopjon vissza (v3.29.1).

⚠ A KERES (2026-09-02): „Most vettem eszre, hogy az osszes kapu a core-ban
helyezkedik el! Ez igy szerintem hibas. A kapu ugyanolyan szabadon
»koltoztethetonek« kellene lennie, mint a strategianak."

    core/gates.py · gate_bands · gate_params · gate_layout   a KERET
    gates/                                                   a TARTALOM
        spread_gate · cost_gate · momentum · tf_align · vol_baseline + docs/

⚠ EZ EGY MOZGATAS, NEM ATTERVEZES — es ezt jobb kimondani. A kapuk MERESET a
motor tovabbra is kozvetlenul hivja (ott, ahol az irany es a friss adat van;
lasd `core.gates.decide`), tehat itt NINCS olyan szabaly, hogy „a keret sosem
importalhat a tartalombol" — a strategiaknal az volt a lenyeg, itt mas.

AMI VISZONT ITT A KOVETELMENY, es amit ez az or oriz:

  1. egy kapu-modul NEM tud a masikrol (kulonben nem kulon-kulon mozdithatok);
  2. egy kapu NEM ismer strategiat (a kapu a VEGREHAJTAS resze, nem a jele);
  3. a LEIRAS a kapuval egyutt koltozik (`gates/docs/`) — ez a `.tfg` csomagolas
     (#3) elofeltetele: egy kapu egy darabban mozdithato legyen;
  4. a `core/` mar nem tartja egyik athelyezett modult sem (nincs ket masolat).
"""
import ast
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


from core import gates as g          # noqa: E402
from gates import paths as gp        # noqa: E402

MEROK = {"spread_gate", "cost_gate", "momentum", "tf_align", "vol_baseline"}


def _imports(p: Path) -> set:
    try:
        fa = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
    except (SyntaxError, OSError):
        return set()
    out = set()
    for n in ast.walk(fa):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module)
            out |= {f"{n.module}.{a.name}" for a in n.names}
    return out


# ══ 1. A CSOMAG TARTALMA ════════════════════════════════════════════════
_van = {p.stem for p in (ROOT / "gates").glob("*.py")} - {"__init__", "paths"}
check("a gates/ csomagban PONTOSAN a kapu-merok vannak", _van == MEROK,
      f"tobblet={sorted(_van - MEROK)} hianyzik={sorted(MEROK - _van)}")
_maradt = [m for m in MEROK if (ROOT / "core" / f"{m}.py").exists()]
check("a core/-ban NEM maradt masolat", not _maradt, ", ".join(_maradt))


# ══ 2. EGY KAPU NEM TUD A MASIKROL, ES NEM ISMER STRATEGIAT ════════════
# ⚠ Ha egy kapu a masikat hivna, a ketto egyben mozdithato csak — es epp ez
# ellen szol a kulon csomag. A strategia-ismeret pedig retegvetes: a kapu a
# VEGREHAJTAS resze, a jelet nem o adja.
_baj = []
for p in sorted((ROOT / "gates").glob("*.py")):
    if p.stem in ("__init__", "paths"):
        continue
    for imp in _imports(p):
        gyoker = imp.split(".")[0]
        modul = imp.split(".")[1] if "." in imp else ""
        if gyoker == "gates" and modul in MEROK and modul != p.stem:
            _baj.append(f"{p.name} → {imp}")
        if gyoker in ("strategy", "strategies"):
            _baj.append(f"{p.name} → {imp}")
check("egy kapu-modul sem hiv masik kaput vagy strategiat", not _baj,
      "; ".join(_baj))


# ══ 3. A LEIRAS A KAPUVAL KOLTOZOTT ════════════════════════════════════
check("a docs/ a gates/ alatt van", gp.docs_dir().is_dir(), str(gp.docs_dir()))
_hiany = [k for k in g.KEYS if not g.doc_path(k).exists()]
check("minden regisztralt kapunak van leirasa", not _hiany, ", ".join(_hiany))
_regi = [p.name for p in (ROOT / "core" / "docs").glob("*.md")
         if p.name.split(".")[0] in set(g.KEYS)]
check("a core/docs/-ban nem maradt kapu-leiras", not _regi, ", ".join(_regi))
# ⚠ A `core/docs/` NEM tunt el: fejlesztoi jegyzeteket tart (`tick_storage.md`),
# amit a felulet sosem mutat. Ha ez ures lenne, tul sokat mozgattunk.
check("a core/docs/ megmaradt a fejlesztoi jegyzeteknek",
      (ROOT / "core" / "docs" / "tick_storage.md").exists())


# ══ 4. AZ UTVONAL EGY FORRASBOL (mint a strategiaknal) ═════════════════
_sajat = [p.name for p in (ROOT / "gates").glob("*.py")
          if p.name != "paths.py"
          and 'parent / "docs"' in io.open(p, encoding="utf-8").read()]
_sajat += ["core/gates.py"] if 'parent / "docs"' in io.open(
    ROOT / "core" / "gates.py", encoding="utf-8").read() else []
check("senki nem szamol sajat docs-utvonalat", not _sajat, ", ".join(_sajat))


# ══ 5. A MOTOR TENYLEG AZ UJ HELYROL MER ═══════════════════════════════
# Nem eleg, hogy a fajlok atkerultek: a hivoknak is oda kell nyulniuk.
_lt = io.open(ROOT / "trading" / "live_trader.py", encoding="utf-8").read()
_bt = io.open(ROOT / "trading" / "backtest.py", encoding="utf-8").read()
check("az elo motor a gates csomagbol mer",
      "from gates import" in _lt, "live_trader")
check("a backtest is", "from gates import" in _bt, "backtest")
_regi_imp = [n for n, src in (("live_trader", _lt), ("backtest", _bt))
             for m in MEROK if f"core.{m}" in src or f"from core import {m}" in src]
check("egyik motor sem hivatkozik a REGI helyre", not _regi_imp,
      ", ".join(sorted(set(_regi_imp))))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
