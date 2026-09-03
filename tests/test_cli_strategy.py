"""A CLI optimalizalo PAR x STRATEGIA szinten dolgozik (P1, v1.98.0).

LELET (2026-08-05). A `python main.py optimize` MINDIG a config elsodleges
strategiajat hangolta:

    run_optimizer -> optimize_symbol(...)          # strategia-argumentum NELKUL
                  -> get_strategy(cfg)             # = strategy.name = wpr_sma

A `pairs.<sym>.strategies` es az `available_strategies` itt nem jatszott — az
`ml_ai`-t CLI-bol egyaltalan nem lehetett se optimalizalni, se tanitani. Raadasul
az `ml_ai` elavult-modell uzenete PONT ezt a parancsot ajanlotta, tehat aki
kovette, NEMAN a `wpr_sma`-t optimalizalta ujra.

A GUI OPT gombja mar per strategia dolgozott (`request_optimize(symbol, name)`) —
ez a kor hozza a CLI-t ugyanarra a szintre.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import main as M
from strategy import registered_strategy_names

REG = registered_strategy_names()

# ══ 1. Parancssor-ertelmezes ══════════════════════════════════════════════

P = M.parse_optimize_args

check("ures argumentum -> minden par, minden sajat strategia",
      P([]) == (None, None), str(P([])))
check("csak parok", P(["Ger40", "UsaTec"]) == (["Ger40", "UsaTec"], None),
      str(P(["Ger40", "UsaTec"])))
check("par + --strategy", P(["Ger40", "--strategy", "ml_ai"]) == (["Ger40"], ["ml_ai"]),
      str(P(["Ger40", "--strategy", "ml_ai"])))
check("--strategy par NELKUL (minden parra)",
      P(["--strategy", "ml_ai"]) == (None, ["ml_ai"]), str(P(["--strategy", "ml_ai"])))
check("a --strategy a par ELOTT is allhat",
      P(["--strategy", "ml_ai", "Ger40"]) == (["Ger40"], ["ml_ai"]),
      str(P(["--strategy", "ml_ai", "Ger40"])))
check("rovid alak (-s) + vesszos lista",
      P(["-s", "wpr_sma,ml_ai"]) == (None, ["wpr_sma", "ml_ai"]),
      str(P(["-s", "wpr_sma,ml_ai"])))
check("--strategy=ertek alak",
      P(["Ger40", "--strategy=ml_ai"]) == (["Ger40"], ["ml_ai"]),
      str(P(["Ger40", "--strategy=ml_ai"])))
check("ismetelt --strategy osszeadodik",
      P(["-s", "wpr_sma", "-s", "ml_ai"]) == (None, ["wpr_sma", "ml_ai"]),
      str(P(["-s", "wpr_sma", "-s", "ml_ai"])))
check("ertek nelkuli --strategy nem robban (a vegen levagva)",
      P(["Ger40", "--strategy"]) == (["Ger40"], None),
      str(P(["Ger40", "--strategy"])))

# ══ 2. Melyik strategiat futtatja egy paron ═══════════════════════════════

from ml.optimizer import resolve_cli_strategies as R

CFG = {"strategy": {"name": "wpr_sma"},
       "available_strategies": {"wpr_sma": True, "ml_ai": True},
       "pairs": {
           "BOTH": {"enabled": True, "strategies": ["wpr_sma", "ml_ai"]},
           "ONLY_ML": {"enabled": True, "strategies": ["ml_ai"]},
           "NOLIST": {"enabled": True},          # nincs lista -> az elsodleges
       }}

check("alapbol a par SAJAT listaja (nem az elsodleges!)",
      R(CFG, "BOTH") == ["wpr_sma", "ml_ai"], str(R(CFG, "BOTH")))
check("a JAVITAS lenyege: csak-ml_ai paron az ml_ai fut (nem a wpr_sma)",
      R(CFG, "ONLY_ML") == ["ml_ai"], str(R(CFG, "ONLY_ML")))
check("lista nelkul az elsodleges (a regi viselkedes)",
      R(CFG, "NOLIST") == ["wpr_sma"], str(R(CFG, "NOLIST")))
check("kifejezett --strategy felulirja a par listajat",
      R(CFG, "ONLY_ML", ["wpr_sma"]) == ["wpr_sma"],
      str(R(CFG, "ONLY_ML", ["wpr_sma"])))

# Egy `available_strategies`-ben KIKAPCSOLT strategiat a CLI se hangoljon nemán:
# a felulet sem kinalja, tehat a ket ut nem mondhat mast.
CFG_OFF = {"strategy": {"name": "wpr_sma"},
           "available_strategies": {"wpr_sma": True, "ml_ai": False},
           "pairs": {"BOTH": {"enabled": True, "strategies": ["wpr_sma", "ml_ai"]}}}
check("a kikapcsolt (available=false) strategia kimarad a CLI-bol is",
      R(CFG_OFF, "BOTH") == ["wpr_sma"], str(R(CFG_OFF, "BOTH")))

# ══ 3. run_optimizer: (par x strategia) tetelek, sajat celfajllal ═════════
#
# Az `optimize_symbol`-t es a `load_data`-t kicsereljuk: a valodi optimalizalas
# oraig futna, es itt nem is az erdekel — hanem hogy MELYIK strategiaval hivjuk,
# es HOVA mentunk.

import json
import tempfile

import ml.optimizer as O

calls = []
saved = []


def _fake_optimize_symbol(symbol, df15, df1, cfg, ib, progress=None, strategy=None):
    calls.append((symbol, getattr(strategy, "name", None)))
    return {"train_summary": {"trades": 1}, "test_summary": {"trades": 1},
            "params": {"x": 1}, "exec_gates": True}


tmpdir = Path(tempfile.mkdtemp())

_orig = (O.optimize_symbol, O.load_data, O.params_file, O.strategy_dir,
         O.stop_marker, O.migrate_flat_layout, O.set_active_strategy)
try:
    O.optimize_symbol = _fake_optimize_symbol
    O.load_data = lambda s: ("M15", "M1")
    O.migrate_flat_layout = lambda *a, **k: 0
    O.set_active_strategy = lambda *a, **k: None

    def _dir(strategy=None):
        d = tmpdir / (strategy or "?")
        d.mkdir(parents=True, exist_ok=True)
        return d

    O.strategy_dir = _dir
    O.params_file = lambda sym, strategy=None: _dir(strategy) / f"{sym}.json"
    O.stop_marker = lambda sym, strategy=None: _dir(strategy) / f"{sym}.stop"

    RUN_CFG = {"strategy": {"name": "wpr_sma"},
               "available_strategies": {"wpr_sma": True, "ml_ai": True},
               "optimizer": {"method": "optuna", "max_trials": 10},
               "pairs": {
                   "AAA": {"enabled": True, "strategies": ["wpr_sma", "ml_ai"]},
                   "BBB": {"enabled": True, "strategies": ["ml_ai"]},
                   "OFF": {"enabled": False, "strategies": ["wpr_sma"]},
               }}

    O.run_optimizer(RUN_CFG, ["AAA", "BBB"])
    check("minden (par x strategia) tetel lefut",
          sorted(calls) == [("AAA", "ml_ai"), ("AAA", "wpr_sma"), ("BBB", "ml_ai")],
          str(sorted(calls)))
    check("a letiltott par kimarad", not any(s == "OFF" for s, _ in calls))
    check("a BBB az ml_ai-val fut (nem az elsodlegessel)",
          ("BBB", "ml_ai") in calls and ("BBB", "wpr_sma") not in calls)

    # A KIMENET strategiankent kulon fajlba megy — nem irjak felul egymast.
    check("AAA/wpr_sma mentve", (tmpdir / "wpr_sma" / "AAA.json").exists())
    check("AAA/ml_ai mentve", (tmpdir / "ml_ai" / "AAA.json").exists())
    check("BBB/ml_ai mentve", (tmpdir / "ml_ai" / "BBB.json").exists())
    check("BBB/wpr_sma NINCS (nem futott)",
          not (tmpdir / "wpr_sma" / "BBB.json").exists())
    _e = json.loads((tmpdir / "ml_ai" / "BBB.json").read_text(encoding="utf-8"))
    check("a mentett bejegyzes a szimbolumot tartalmazza", _e.get("symbol") == "BBB")

    # Kifejezett --strategy: csak az fusson, MEG ott is, ahol nincs engedelyezve
    # (ez a „optimalizalj, mielott bekapcsolod" ut).
    calls.clear()
    O.run_optimizer(RUN_CFG, ["AAA"], ["ml_ai"])
    check("--strategy eseten CSAK az a strategia fut",
          calls == [("AAA", "ml_ai")], str(calls))

    # URES `strategies: []` = az ELSODLEGES (a keretrendszer szemantikaja,
    # `enabled_strategy_names`: "hianyzik/ures -> az elsodleges"). A CLI-nek a
    # MOTORT kell tukroznie, nem sajat szabalyt hoznia — ezert itt fut a wpr_sma.
    calls.clear()
    EMPTY_LIST = dict(RUN_CFG, pairs={"ZZZ": {"enabled": True, "strategies": []}})
    O.run_optimizer(EMPTY_LIST, ["ZZZ"])
    check("ures 'strategies' lista = az elsodleges (motor-paritas)",
          calls == [("ZZZ", "wpr_sma")], str(calls))

    # VALODI ures munkalista: a par egyetlen strategiaja ki van kapcsolva az
    # `available_strategies`-ben -> nincs mit futtatni. Beszedes figyelmeztetes,
    # NEM nema visszateres (kulonben ugy tunne, lefutott).
    calls.clear()
    NOJOB = dict(RUN_CFG,
                 available_strategies={"wpr_sma": True, "ml_ai": False},
                 pairs={"ZZZ": {"enabled": True, "strategies": ["ml_ai"]}})
    O.run_optimizer(NOJOB, ["ZZZ"])
    check("ures munkalista -> nem hiv optimalizalast", calls == [], str(calls))
finally:
    (O.optimize_symbol, O.load_data, O.params_file, O.strategy_dir,
     O.stop_marker, O.migrate_flat_layout, O.set_active_strategy) = _orig

# ══ 4. A dispatch tenyleg atadja a strategiat ═════════════════════════════

osrc = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
_run = osrc.split("def run_optimizer")[1].split("\ndef ")[0]
check("run_optimizer: az optimize_symbol STRATEGIAT kap",
      "strategy=strategy)" in _run)
check("run_optimizer: a celfajl EXPLICIT strategiaval kepzodik "
      "(az optimize_symbol atallitja a modul-szintu aktivat)",
      "params_file(symbol, sname)" in _run)
check("run_optimizer: a stop-marker is explicit strategiaval",
      "stop_marker(symbol, sname)" in _run)
check("run_optimizer: fogadja a strategies argumentumot",
      "def run_optimizer(cfg: dict, symbols: Optional[list[str]] = None,\n"
      "                  strategies: Optional[list[str]] = None):" in osrc)

# ══ 5. Az ml_ai uzenete a HELYES parancsra mutat ══════════════════════════

msrc = (ROOT / "strategies" / "ml_ai.py").read_text(encoding="utf-8")
check("az ml_ai elavult-modell uzenete --strategy ml_ai-t ajanl",
      "python main.py optimize %s --strategy ml_ai" in msrc)
check("nincs tobbe strategia NELKULI 'main.py optimize' ajanlas az ml_ai-ban",
      "python main.py optimize %s`)." not in msrc)

# ══ 6. main.py: ismeretlen / kikapcsolt strategia -> beszedes hiba ════════

nsrc = (ROOT / "main.py").read_text(encoding="utf-8")
check("main.py: a cmd_optimize fogad strategiakat",
      "def cmd_optimize(symbols=None, strategies=None):" in nsrc)
# ⚠ A SZOVEGEK a nyelvi katalogusban vannak (i18n) — a forrasban a KULCS all.
# Ket allitas: hivatkozik-e a kulcsra, ES a magyar szoveg tenyleg ezt mondja-e.
import json as _json
_HU_CAT = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
check("main.py: megkulonbozteti az ISMERETLEN es a KIKAPCSOLT nevet",
      "cli.strategy_unknown" in nsrc and "cli.strategy_off" in nsrc
      and "Ismeretlen stratégia" in _HU_CAT.get("cli.strategy_unknown", "")
      and "ki van kapcsolva" in _HU_CAT.get("cli.strategy_off", ""))
check("main.py: kiirja az elerheto neveket",
      "cli.available" in nsrc and "Elérhető: " in _HU_CAT.get("cli.available", ""))
check("main.py: a sugo mutatja a --strategy hasznalatat",
      "--strategy ml_ai" in nsrc and "-s wpr_sma,ml_ai" in nsrc)
check("README: a --strategy dokumentalva van",
      "--strategy ml_ai" in (ROOT / "README.md").read_text(encoding="utf-8"))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
