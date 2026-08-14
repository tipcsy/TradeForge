"""Osszecsukhato szakasz: a becsukas a SZERKESZTEST rejtse el, ne az INFORMACIOT.

A latvanyterv szerint a parameter-ablak teljes szelessegu szakaszokbol all
(orak · kapuk · parameterek · kockazatcsokkentes · futtatas · eredmeny), es
napi munkaban legfeljebb ketto-harom kell nyitva.

⚠ A LEGFONTOSABB ALLITAS: a becsukott szakasz fejlece OSSZEGZEST mutat. Enelkul
a becsukas eppen azt a kerdest szulne, amit az egesz atalakitas megszuntetni
probal — „most akkor mi van beallitva?" —, es a felhasznalonak ki kellene
nyitnia, hogy megtudja.

⚠ ES AZ ALLAPOT MEGJEGYZODIK (par + strategia szinten). Egy ablak, amit minden
megnyitaskor ujra szet kell csukdosni, par nap alatt elveszi a kedvet a
hasznalatatol — es a becsukas EPP azert van, hogy a napi nezet gyors legyen.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception as e:
    TK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

from dashboard import section as sec

# ── 1. A MEGJEGYZES (Tk nelkul is merheto) ────────────────────────────────
# ⚠ A teszt SOHA nem irhat a valodi beallitas-tarba: temp fajlra teritjuk.
from core import backtest_prefs as bp

_tmp = Path(tempfile.mkdtemp(prefix="section_test_"))
_orig_file = getattr(bp, "_FILE", None)
if _orig_file is not None:
    bp._FILE = _tmp / "prefs.json"

DEF = {"orak": False, "kapuk": True, "parameterek": True}
check("hianyzo mentesnel az ALAPERTELMEZES ervenyes",
      sec.load_open("TEST", "wpr_sma", DEF) == DEF,
      str(sec.load_open("TEST", "wpr_sma", DEF)))

sec.save_open("TEST", "wpr_sma", "orak", True)
sec.save_open("TEST", "wpr_sma", "kapuk", False)
_got = sec.load_open("TEST", "wpr_sma", DEF)
check("a mentett allapot VISSZAJON", _got["orak"] is True and _got["kapuk"] is False,
      str(_got))
check("...a nem mentett marad alapertelmezett", _got["parameterek"] is True)

# ⚠ PAR+STRATEGIA szintu: mas paron a sajat beallitasod ervenyes, nem a szomszede.
check("mas par NEM oroköl", sec.load_open("MASIK", "wpr_sma", DEF) == DEF,
      str(sec.load_open("MASIK", "wpr_sma", DEF)))
check("mas strategia sem", sec.load_open("TEST", "masik_strat", DEF) == DEF)

if _orig_file is not None:
    bp._FILE = _orig_file
import shutil
shutil.rmtree(_tmp, ignore_errors=True)


# ── 2. A WIDGET ───────────────────────────────────────────────────────────
if TK:
    from dashboard import theme as th
    root = tk.Tk(); root.withdraw()
    th._FONTS.clear()
    fonts = th.fonts()

    log = []
    s = sec.Section(root, "orak", "kereskedési órák", fonts, open_=True,
                    on_toggle=lambda k, v: log.append((k, v)),
                    summary="08–17 · 10 óra engedve")
    s.pack()
    tk.Label(s.body, text="tartalom").pack()
    root.update_idletasks()

    # ⚠ A `winfo_ismapped` REJTETT ablaknal mindenre hamis — a CSOMAGOLAS
    # allapotat kell nezni (`winfo_manager`), kulonben a teszt mindig „csukva"-t
    # latna, es a nyitas-agat sosem merne.
    def packed(w):
        return w.winfo_manager() == "pack"

    check("indulaskor nyitva, a torzs csomagolva", s.is_open and packed(s.body))
    s.toggle(); root.update_idletasks()
    check("becsukva a torzs KIKERUL", (not s.is_open) and not packed(s.body))
    check("a becsukas ERTESIT", log == [("orak", False)], str(log))

    # ⚠ EZ A LENYEG: becsukva is latszik, MI VAN beallitva.
    check("becsukva is ott az OSSZEGZES a fejlecben",
          s._sum.cget("text") == "08–17 · 10 óra engedve", s._sum.cget("text"))
    s.set_summary("mind a 24 óra")
    check("az osszegzes frissitheto", s._sum.cget("text") == "mind a 24 óra")

    s.set_open(True); root.update_idletasks()
    check("ujra nyithato", s.is_open and packed(s.body))
    check("...es errol is ertesit", log == [("orak", False), ("orak", True)], str(log))

    # Ismetelt azonos allapot: NE ertesitsen ujra (kulonben a mentes minden
    # ujrarajzolaskor irna a lemezt).
    s.set_open(True)
    check("azonos allapotra nincs ujabb ertesites", len(log) == 2, str(log))
    s.set_open(False, notify=False)
    check("notify=False: valt, de nem ertesit",
          (not s.is_open) and len(log) == 2, str(log))

    # ⚠ A FEJLEC EGESZE kattinthato, nem csak a nyil: egy 12 px-es celpontot
    # nehez eltalalni.
    _bound = [w for w in (s.head, s._arrow, s._title, s._sum)
              if w.bind("<Button-1>")]
    check("a fejlec MINDEN resze kattinthato", len(_bound) == 4,
          f"{len(_bound)}/4")

    # A cim es az osszegzes kulon allithato (a hivo frissiti futas kozben is).
    s.set_title("kapuk"); check("a cim allithato", s._title.cget("text") == "kapuk")

    # Tobb szakasz egymas alatt — a `pack` alapbol teljes szelesseg.
    s2 = sec.Section(root, "kapuk", "kapuk", fonts, open_=False).pack()
    root.update_idletasks()
    check("csukottan indulhat", not s2.is_open and not packed(s2.body))
    check("a szakasz teljes szelessegre csomagol",
          s2.frame.pack_info().get("fill") == "x", str(s2.frame.pack_info()))

    root.destroy()
else:
    check("nincs tkinter (a widget-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
