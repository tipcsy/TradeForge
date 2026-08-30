"""
A kapu-ablak GORDITHETOSEGE es a Lendulet ALLAPOT-SZOTARA.

Ket eles hiba ellen ved:

1. A Lendulet-kapunak nyolc parametere van, alatta meg a strategiankenti hatas
   blokk — ez 720x420-as ablakban a felen tullogott, gorditosav nelkul NEMAN.
   A teszt ezert nem azt allitja, hogy "van sav", hanem hogy a tartalom
   MAGASABB a lathato teruletnel ES megis elerheto.

2. Az allapot korabban "porog" volt, ami elenk piacot sugallt, holott a meres
   csak annyit mond, hogy nem all. A teszt a szotar HAROM agat rogziti
   (alapjarat / fut / nincs adat), es hogy a szam is ott van a szo mellett.

⚠ Ez a teszt NEM valt ki mentest, tehat a config.json-hoz nem nyul.
"""

import pathlib
import sys
import tkinter as tk

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

from core import gate_params as gp        # noqa: E402
from core import gates as g               # noqa: E402

_fail = []
_results = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


# ---------------------------------------------------------------------------
print("== Lendulet allapot-szotar ==")

s_run = gp.momentum_state_text(1.24, 0.35)
s_idle = gp.momentum_state_text(0.12, 0.35)
s_nan = gp.momentum_state_text(float("nan"), 0.35)

check("a 'porog' szo eltunt", "porog" not in s_run and "örög" not in s_run, s_run)
check("kuszob folott: 'fut'", s_run.startswith("fut"), s_run)
check("kuszob alatt: ALAPJARAT", "ALAPJ" in s_idle and "bukik" in s_idle, s_idle)
check("adathiany kulon ag", "nincs adat" in s_nan and "tenged" in s_nan, s_nan)
check("a szam is ott van a szo mellett", "1.24" in s_run and "0.35" in s_run, s_run)
check("negativ fordulat is 'fut' (abszolut ertek)",
      gp.momentum_state_text(-0.90, 0.35).startswith("fut"))
check("kuszob HATARAN meg fut (>=)", gp.momentum_state_text(0.35, 0.35).startswith("fut"))

for word in ("alapj", "fut", "szöb"):
    check(f"a szotar emliti: {word!r}", word in gp.MOMENTUM_STATES, gp.MOMENTUM_STATES)

rows = dict(gp.measured_rows(g.MOMENTUM,
                             {"momentum": 0.12, "momentum_idle_threshold": 0.35}))
check("a 'Lehetseges allapotok' sor megjelenik",
      any("llapotok" in k for k in rows), str(list(rows)))
check("az Allapot sor a szotar szerinti", any("ALAPJ" in v for v in rows.values()))

# A leiras-lap is nevezze meg az allapotokat (kulonben a ket hely szetcsuszik)
doc = g.doc_text(g.MOMENTUM) or ""
check("a leiras felsorolja az allapotokat",
      "alapj" in doc.lower() and "**fut**" in doc and "nincs adat" in doc.lower(),
      f"{len(doc)} karakter")

# ---------------------------------------------------------------------------
print("== Kapu-ablak: gorditheto Beallitas lap ==")

root = tk.Tk()
root.withdraw()
try:
    import json
    cfg_p = pathlib.Path(__file__).resolve().parents[1] / "config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    before = cfg_p.stat().st_mtime if cfg_p.exists() else None

    from dashboard.gate_dialog import GateDialog
    d = GateDialog(root, cfg, "GER40", g.MOMENTUM, ["wpr_sma", "ml_ai"],
                   ctx={"momentum": 0.12, "momentum_idle_threshold": 0.35})
    d.top.geometry("720x420")
    root.update_idletasks()
    root.update()

    SET = "settings"
    DOC = "docs"
    page = d._shell.page(SET)
    sbs = [c for c in walk(page) if isinstance(c, tk.Scrollbar)]
    cvs = [c for c in walk(page) if isinstance(c, tk.Canvas)]

    check("a Beallitas lapon PONTOSAN egy gorditosav van", len(sbs) == 1, str(len(sbs)))
    check("a gorditosav lathato", bool(sbs and sbs[0].winfo_ismapped()))
    bb = cvs[0].bbox("all") if cvs else None
    tall = bool(bb and bb[3] > cvs[0].winfo_height())
    check("a tartalom tenyleg tullog (kulonben a teszt semmit nem bizonyit)",
          tall, f"{bb[3] if bb else '?'} > {cvs[0].winfo_height() if cvs else '?'}")

    # Az also blokk (hatas strategiankent) a gorgetheto teruleten belul van-e
    labels = [c for c in walk(page) if isinstance(c, tk.Label)]
    check("a strategia-nevek a gorgetheto lapon vannak",
          any("wpr_sma" in (c.cget("text") or "") for c in labels))

    # Lapvaltas: a leiras sajat Text-je gorget, a beallitas vaszna nem hallgatozik
    d._shell.show(DOC)
    root.update_idletasks()
    root.update()
    check("leiras-lapon a Beallitas vaszna nincs kirakva",
          not cvs[0].winfo_ismapped())
    check("nem nyilt kulon Toplevel a leirasnak",
          len([w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]) == 1)

    if before is not None:
        check("a config.json NEM valtozott", cfg_p.stat().st_mtime == before)
finally:
    root.destroy()

# ---------------------------------------------------------------------------
print("== Kozos gorgetheto modul ==")
from dashboard import scroll_area, instrument_dialog          # noqa: E402
check("az instrumentum-ablak ugyanazt hasznalja",
      instrument_dialog._scrollable is scroll_area.scrollable)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
