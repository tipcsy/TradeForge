"""TESZT-CSOPORTOK — melyik teszt melyik területet érinti?

⚠ A KÉRÉS (2026-09-02): „csoportosítsuk a teszteket, és csak azokat futtassuk,
ami az adott feladatkört érinti… a lényeg, hogy ha egy területhez hozzányúlsz,
akkor tudd, hogy melyik területet érintheti még."

⚠ MIÉRT NEM KÉZZEL KARBANTARTOTT LISTA. Egy `test_x.py → motor` táblázat az első
héten pontos, a harmadikon már nem: egy teszt új importot kap, és a besorolás
csendben hazudik — a „lefuttattam a motor-csoportot" hamis biztonság lenne. Kézzel
csak MODULOKAT sorolunk be (a `core/spread_gate.py` jövőre is kapu lesz); a
TESZTEK hovatartozása ebből, a tényleges importjaikból SZÁMÍTÓDIK.

⚠ A LUSTA IMPORTOK IS SZÁMÍTANAK. A projektben rengeteg függvényen belüli
`from core import x` van (indítási idő miatt). Ha csak a fájl tetejét néznénk, a
függőségi kép a felét mutatná — ezért az EGÉSZ fájlt bejárjuk.

⚠ KÉT KÜLÖNBÖZŐ KÉRDÉS, KÉT KÜLÖNBÖZŐ VÁLASZ. A csoport a KÖZVETLEN importokból
lesz („miről szól a teszt"), az `--erinti` a TRANZITÍV lezárásból („mit törhet el
egy változtatás"). Ha a csoport is tranzitív lenne, a `core.i18n` 116 tesztet
húzna be a 137-ből — ami igaz, de csoportnak használhatatlan.

Használat (a `run_all.py`-ból):

    python tests/run_all.py --csoportok              # mi van, és mennyi
    python tests/run_all.py --csoport motor          # egy (vagy több) csoport
    python tests/run_all.py --kihagy felulet         # minden, a villogók nélkül
    python tests/run_all.py --erinti core/gates.py   # ami EZT a fájlt érinti
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESZT_DIR = ROOT / "tests"

# A projekt saját csomagjai — csak ezeket követjük (a numpy/pandas nem érdekes).
CSOMAGOK = ("core", "trading", "strategy", "strategies", "gates",
            "dashboard", "ml", "tools", "tests")

# ── A NÉVVEL ELLÁTOTT CSOPORTOK ───────────────────────────────────────────
# Egy csoport = modul-előtagok halmaza. Egy teszt ANNYI csoportba tartozik,
# ahányat érint — ez szándékos: egy backtest-teszt, ami a felületet is húzza,
# mindkettőben benne van, és ha bármelyikhez hozzányúlsz, lefut.
#
# ⚠ ITT MODULOK vannak besorolva, nem tesztek — és ez a különbség a lényeg.
# Egy modul hovatartozása stabil (a `core/spread_gate.py` jövőre is kapu), egy
# teszté nem. A teszt besorolása ebből SZÁMÍTÓDIK, a tényleges importjaiból.
CSOPORTOK = {
    # ⚠ A kapu-MÉRÉSEK v3.29.1 óta a `gates/` csomagban vannak; a KERET maradt a
    # `core`-ban (`gates`, `gate_bands`, `gate_params`, `gate_layout`).
    "motor": ("trading.", "gates.", "core.gates", "core.gate_bands",
              "core.gate_params", "core.market_state",
              "core.market_strategy", "core.regime", "core.signal_detector",
              "core.indicator_engine", "core.risk_manager", "core.order_exec",
              "core.mt5_connector", "core.risk_reduction", "core.risky_mode",
              "core.rr_state", "core.exit_signal", "core.position_build",
              "core.build_state", "core.execution_params", "core.trade_costs",
              "core.live_lock", "core.position_meta",
              "core.adopted", "core.pnl_split", "core.correlation",
              "core.trade_mode"),
    # ⚠ KÉT csomag (v3.29.0): a KERET (`strategy/`) és a TARTALOM
    # (`strategies/`). Egy csoportba tartoznak: aki az egyikhez nyúl, a
    # másikat is elronthatja.
    "strategia": ("strategy.", "strategies."),
    "felulet": ("dashboard.", "core.gate_layout", "core.overview",
                "tools.ui_preview"),
    "optimalizalo": ("ml.", "core.opt_activity", "core.opt_lock", "core.opt_plan",
                     "core.sweep", "core.param_constraints", "core.quality",
                     "core.training_overlap", "core.backtest_prefs"),
    "vizualizacio": ("core.mt5_visual", "core.mt_charts", "core.mt_deploy",
                     "core.viz_prefs", "tools.viz_export", "tools.viz_render"),
    "labor": ("tools.lab_",),
    "kutatas": ("tools.research.", "tools.gate_ab", "tools.cost_gate_ab",
                "tools.nested_ab", "tools.ma_exit_ab", "tools.feature_analysis",
                "tools.regime_analysis", "tools.tf_align_analysis"),
    "adat": ("tools.build_bars", "tools.download_history", "tools.download_ticks",
             "tools.mt5_export", "core.fs_cache", "core.config_freshness",
             "core.symbol_policy", "core.params_store", "core.run_state",
             "core.bulk_apply", "core.config_check", "core.scope_check"),
    "nyelv": ("core.i18n",),
    "ertesites": ("core.notify", "core.telegram", "core.telegram_cmd",
                  "core.console_cmd", "core.console_tui", "core.signal_offer"),
    "licenc": ("core.licence", "core.licence_gate"),
    "naplo": ("core.applog",),
}

# ⚠ A SEMLEGES MODUL NEM CSOPORTKÉPZŐ. A `core.applog`-ot 93 teszt importálja a
# 137-ből — nem azért, mert a naplózásról szólnak, hanem mert a konzol-kódolást
# ez rendezi. Ha csoportot képezne, a „naplo" csoport majdnem az egész csomag
# lenne, a szám pedig semmit nem mondana. Ezért csak AKKOR sorol be, ha a
# tesztnek NINCS más projekt-importja — olyankor viszont tényleg a naplóról szól.
SEMLEGES = ("core.applog",)

# ⚠ AZ ŐRÖK KÜLÖN CSOPORT, és NEM importok alapján. Ezek a szerkezeti
# ellenőrzések (verzió, definiálatlan nevek, néma hibák, konfig-koherencia,
# kódolás, higiénia) az EGÉSZ kódbázist nézik — ha import szerint sorolnánk be
# őket, mindenhova beleesnének, és minden részleges futás lelassulna. Viszont
# olcsók, ezért MINDEN részleges futás viszi őket (lásd `run_all.py`).
#
# ⚠ A NEVEK LÉTEZÉSÉT ŐRIZNI KELL. Ez a lista már egyszer HAZUDOTT: két olyan
# fájlnév állt benne, ami sosem létezett (`test_config_coherence.py`,
# `test_tests_dont_write_config.py`) — az őr-csoport némán kettővel kevesebbet
# futtatott. Ezért van rá teszt (`test_csoportok.py`).
OROK = ("test_version_discipline.py", "test_no_undefined_names.py",
        "test_silent_swallows.py", "test_config_check.py", "test_hygiene.py",
        "test_i18n.py", "test_subprocess_encoding.py",
        "test_csoportok.py")


def _projekt_modulok() -> dict:
    """`{modul_nev: Path}` a projekt saját .py fájljaira."""
    ki = {}
    for cs in CSOMAGOK:
        d = ROOT / cs
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(ROOT).with_suffix("")
            ki[".".join(rel.parts)] = p
    for p in ROOT.glob("*.py"):
        ki[p.stem] = p
    return ki


def _importok(p: Path) -> set:
    """Egy fájl ÖSSZES projekt-importja — a függvényeken belüliekkel együtt."""
    try:
        fa = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
    except (SyntaxError, OSError):
        return set()
    ki = set()
    for n in ast.walk(fa):
        if isinstance(n, ast.Import):
            for a in n.names:
                ki.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.level:           # relatív import — a csomagon belül marad
                continue
            if n.module:
                ki.add(n.module)
                for a in n.names:
                    ki.add(f"{n.module}.{a.name}")
    return {m for m in ki
            if m.split(".")[0] in CSOMAGOK or m in ("version", "main")}


def fuggosegi_graf() -> dict:
    """`{modul: {közvetlenül importált projekt-modulok}}`."""
    mod = _projekt_modulok()
    graf = {}
    for nev, p in mod.items():
        graf[nev] = {m for m in _importok(p) if m in mod}
    return graf


def lezaras(kezdo: set, graf: dict) -> set:
    """Tranzitív lezárás: mindaz, amit a `kezdo` modulok elérnek."""
    latott, sor = set(), list(kezdo)
    while sor:
        m = sor.pop()
        if m in latott:
            continue
        latott.add(m)
        sor.extend(graf.get(m, ()))
    return latott


def teszt_terkep() -> dict:
    """`{teszt_fájlnév: (KÖZVETLEN importok, TRANZITÍVAN elért modulok)}`.

    ⚠ A KETTŐ MÁS KÉRDÉSRE VÁLASZOL, és ezt szét kell tartani:

    * **közvetlen** = MIRŐL SZÓL a teszt. Ebből lesz a csoport.
    * **tranzitív** = MIT TÖRHET EL egy változtatás. Ebből lesz az `--erinti`.

    Mérve (2026-09-03): a tranzitív lezárás szerint a `core/i18n.py` 116 tesztet
    érint a 137-ből — ami IGAZ (majdnem minden eljut oda), de csoportosításnak
    használhatatlan: egy „nyelv" csoport, ami az egészet tartalmazza, nem
    csoport. A közvetlen import viszont pontosan azt mondja meg, hogy a teszt
    maga MIT vizsgál."""
    graf = fuggosegi_graf()
    mod = _projekt_modulok()
    ki = {}
    for p in sorted(TESZT_DIR.glob("test_*.py")):
        kozvetlen = {m for m in _importok(p) if m in mod}
        ki[p.name] = (kozvetlen, lezaras(kozvetlen, graf))
    return ki


def _illeszkedik(modulok: set, elotagok) -> bool:
    return any(m.startswith(e) or m == e.rstrip(".")
               for m in modulok for e in elotagok)


def csoportok_szerint(terkep: dict = None) -> dict:
    """`{csoport: [teszt fájlnevek]}`."""
    terkep = terkep if terkep is not None else teszt_terkep()
    ki = {cs: [] for cs in CSOPORTOK}
    ki["orok"] = [n for n in sorted(terkep) if n in OROK]
    for nev, (kozvetlen, _tranzitiv) in sorted(terkep.items()):
        erdemi = {m for m in kozvetlen if m not in SEMLEGES}
        hasznalt = kozvetlen if not erdemi else erdemi
        for cs, elotagok in CSOPORTOK.items():
            if _illeszkedik(hasznalt, elotagok):
                ki[cs].append(nev)
    # ⚠ AKI SEHOVA NEM ESIK, az sem veszhet el: egy teszt, ami egyik csoportban
    # sincs benne, SOHA nem futna részleges futásban — és épp az ilyen csendes
    # kimaradásból lesz a „zöld volt a teszt, mégis eltört" eset.
    _besorolt = {n for lista in ki.values() for n in lista}
    ki["egyeb"] = [n for n in sorted(terkep) if n not in _besorolt]
    return ki


def erintett_tesztek(cel: str, terkep: dict = None) -> list:
    """Mely tesztek érintik a megadott FÁJLT vagy modult?

    `cel` lehet útvonal (`core/gates.py`) vagy modulnév (`core.gates`)."""
    terkep = terkep if terkep is not None else teszt_terkep()
    m = cel.replace("\\", "/").removesuffix(".py").replace("/", ".")
    return [n for n, (_kozv, tranzitiv) in sorted(terkep.items())
            if m in tranzitiv]


def valogatas(nevek, terkep: dict = None) -> list:
    """A megadott csoportokhoz tartozó teszt-fájlnevek — RENDEZVE, egyszer.

    ⚠ AZ ŐRÖK ÉS AZ `egyeb` MINDIG BENNE VANNAK, és ez nem kényelmi döntés.
    Az őrök az egész kódbázist nézik (olcsók, bármit elronthat egy változtatás),
    az `egyeb` pedig azokat a teszteket tartalmazza, amiket az importjaikból NEM
    lehetett besorolni — épp ezért nem tudjuk róluk kijelenteni, hogy nem
    érinti őket a mostani munka. Egy be nem sorolható tesztet kihagyni annyi,
    mint a nem-tudást biztonságnak nevezni."""
    terkep = terkep if terkep is not None else teszt_terkep()
    g = csoportok_szerint(terkep)
    ismeretlen = [n for n in nevek if n not in g]
    if ismeretlen:
        raise KeyError("Nincs ilyen csoport: " + ", ".join(ismeretlen)
                       + "  |  van: " + ", ".join(sorted(g)))
    ki = set(g["orok"]) | set(g["egyeb"])
    for n in nevek:
        ki |= set(g[n])
    return sorted(ki)


def kozvetlen_importalok(cel: str, terkep: dict = None) -> set:
    """Mely tesztek importálják KÖZVETLENÜL a megadott modult?

    Az `erintett_tesztek` tranzitív (konzervatív) válaszát ezzel lehet
    rangsorolni: elöl az, ami tényleg erről szól."""
    terkep = terkep if terkep is not None else teszt_terkep()
    m = cel.replace("\\", "/").removesuffix(".py").replace("/", ".")
    return {n for n, (kozv, _t) in terkep.items() if m in kozv}
