"""Teljes szelessegu szakaszok: az orak es a kockazatcsokkentes.

A latvanyterv szerint a parameter-ablak szakaszai a TELJES szelesseget hasznaljak
(oszlopokba tordelve a kapuk 6-10 sora es a parameterek 20+ sora egymas mellett
ranezesre osszemerhetetlen volt — „a kapuk nagyon elvesznek a jobb oldalon").

⚠ MIT ALLIT EZ A TESZT, es miert epp azt:

1. A 24 ora EGYENLOEN osztozik a szelessegen. Enelkul az ablakot szelesitve a
   racs balra huzodna, jobbra ures hely maradna, es a kattinthato celpontok
   12 px-esek maradnanak — pont az a rossz celzas, ami miatt a Section fejlecen
   is MIND a negy widget kattinthato.

2. A becsukott kockazat-szakasz fejlece TOBBET mond a preset nevenel. A szakasz
   HAROM FUGGETLEN tengelyt tartalmaz (preset · runner · epites) + ket
   kapcsolot; ha becsukva csak az elso latszik, a becsukas eppen azt a kerdest
   szuli ujra, amit meg kellene szuntetnie: „most akkor mi van bekapcsolva?"
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

# ⚠⚠ AZ ELES ALLAPOTOT NEM IRJUK. Ez a teszt VALODI `InstrumentParamsDialog`-ot
# epit, es a kockazatcsokkento vezerlok erintese a valodi `data/risk_mode.json`-ba
# ment — vagyis atallitja a felhasznalo per-par beallitasat. A `PATH` ideiglenes
# fajlra teritese az egyetlen biztos vedelem (a csonkolas minden uj hivasi utnal
# megkerulheto). A `tests/run_all.py` ore fogta meg ezt is.
import atexit as _atexit, pathlib as _pathlib, shutil as _shutil, tempfile as _tempfile
from core import rr_state as _rrs_guard
_RR_REAL = _rrs_guard.PATH
_RR_TMP = _pathlib.Path(_tempfile.mkdtemp(prefix="tfv_rr_")) / "risk_mode.json"
if _RR_REAL.exists():
    _shutil.copy2(_RR_REAL, _RR_TMP)          # az induló állapot maradjon élethű
_rrs_guard.PATH = _RR_TMP
_atexit.register(lambda: setattr(_rrs_guard, "PATH", _RR_REAL))
_atexit.register(lambda: _shutil.rmtree(_RR_TMP.parent, ignore_errors=True))

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

if TK:
    from strategy.settings import load_config
    from strategy import get_strategy_by_name
    from dashboard import instrument_dialog as idlg, theme

    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    f = theme.fonts()
    cfg = load_config("config.json")
    live = copy.deepcopy(cfg)
    sym = next(s for s in cfg["pairs"] if not s.startswith("_"))
    d = idlg.InstrumentParamsDialog(root, sym, cfg,
                                    get_strategy_by_name("wpr_sma"),
                                    f["header"], f["small"], lambda: None,
                                    root_cfg=live)
    root.update_idletasks()

    # ── 1. ORAK: 24 egyenlo oszlop, a teljes szelessegen ──────────────────
    _hb = d._hour_btns[0]
    grid = _hb.master.master            # colf -> hours_frame
    check("az ora-racs a teljes szelessegre csomagol",
          grid.pack_info().get("fill") == "x", str(grid.pack_info()))

    _cols = [grid.grid_columnconfigure(h) for h in range(24)]
    check("mind a 24 oszlop SULYOZOTT (nyulik)",
          all(int(c.get("weight", 0)) == 1 for c in _cols),
          str([c.get("weight") for c in _cols[:4]]))
    # ⚠ Az `uniform` nelkul a P&L-szamot tartalmazo oszlopok szelesebbek
    # lennenek, es a racs „lelegezne" a szamok hosszatol.
    check("...es EGYFORMA szelesek (uniform)",
          len({str(c.get("uniform")) for c in _cols}) == 1
          and str(_cols[0].get("uniform")) != "",
          str(_cols[0].get("uniform")))

    # A cimke fix karakter-szelesseggel nem nyulna a helyere.
    check("az ora-cimken nincs fix karakter-szelesseg",
          not str(_hb.cget("width")).strip("0 ") or int(_hb.cget("width")) == 0,
          str(_hb.cget("width")))
    check("az ora-cimke vizszintesen kitolt", _hb.pack_info().get("fill") == "x",
          str(_hb.pack_info()))
    # A `sticky`-t a Tk sajat sorrendjeben adja vissza ('nesw'), ezert HALMAZKENT
    # hasonlitunk — kulonben a teszt a betuk sorrendjere bukna, nem a viselkedesre.
    check("az ora-cella a racsban is kitolt",
          set(_hb.master.grid_info().get("sticky", "")) == set("nsew"),
          str(_hb.master.grid_info().get("sticky")))

    # ⚠ ES MERJUK IS MEG. A `weight`/`uniform` beallitasa meg nem bizonyitja, hogy
    # a cellak tenyleg nonek: ha barhol kozben hianyzik a `fill`, a racs szelesedne,
    # a gombok nem. Ezert szelesitjuk az ABLAKOT, es a tenyleges px-t nezzuk.
    # ⚠ A REJTETT ablak minden szelessege 1 px — a merés csak MEGJELENITVE
    # ervenyes. (Enelkul a teszt „1 -> 1"-et latna, es sosem bukna el.)
    # ⚠ ES A SZAKASZ LEGYEN NYITVA, a lap pedig ELOL. Az orak alapbol CSUKOTTAN
    # indulnak (napi munkaban ritkan kellenek) — a csukott szakasz torzse nincs
    # csomagolva, tehat a gyerekei sosem kapnanak geometriat.
    d._shell.show("Paraméter")
    d._sections["orak"].set_open(True)
    _top = _hb.winfo_toplevel()
    _top.deiconify()
    # ⚠ MINDKET meret legyen a tartalom TERMESZETES igenye FOLOTT (~1300 px):
    # az alatt a lap vizszintesen gorgetheto, es a belso keret a TARTALOM
    # szelesseget veszi fel — olyankor az ablak szelesitese joggal NEM mozdit a
    # cellakon. A racs nyulasa ott merheto, ahol egyaltalan van szabad hely.
    _top.geometry("1400x800"); _top.update()
    _w_keskeny = d._hour_btns[23].winfo_width()
    _top.geometry("1900x800"); _top.update()
    _w_szeles = d._hour_btns[23].winfo_width()
    _top.withdraw()
    check("szelesitve az ora-cellak NONEK", _w_szeles > _w_keskeny,
          f"1400px -> {_w_keskeny}px cella; 1900px -> {_w_szeles}px cella")

    # ── 2. A KOCKAZAT-SZAKASZ OSSZEGZESE ──────────────────────────────────
    from core import rr_state as _rr, risk_reduction as _rrx
    _PS, _PO = _rrx.PRESET_SHIELD, _rrx.PRESET_OFF
    d._rr_name.set(_rr.NAME[_PS])
    d._on_rr_change(_rr.NAME[_PS])
    root.update_idletasks()
    _sum = d._sections["kockazat"]._sum.cget("text")
    check("a preset neve ott van", _rr.NAME[_PS] in _sum, _sum)
    # ⚠ A runner CSAK Felezo/Pajzsnal ertelmes — es epp ott kell latszania,
    # mert ott dol el, mi tortenik a reszleges zaras UTAN maradt darabbal.
    check("Pajzsnal a RUNNER is", "runner" in _sum, _sum)

    d._cc_var.set(True); d._on_cost_cut_change()
    check("a cost-cut bekerul", "cost-cut" in d._sections["kockazat"]._sum.cget("text"),
          d._sections["kockazat"]._sum.cget("text"))
    d._cc_var.set(False); d._on_cost_cut_change()
    check("...es ki is kerul",
          "cost-cut" not in d._sections["kockazat"]._sum.cget("text"))

    # Ki presetnel a runner NEM latszik -> az osszegzesbol is kimarad
    d._rr_name.set(_rr.NAME[_PO]); d._on_rr_change(_rr.NAME[_PO])
    root.update_idletasks()
    check("Ki-nel a runner KIMARAD az osszegzesbol",
          "runner" not in d._sections["kockazat"]._sum.cget("text"),
          d._sections["kockazat"]._sum.cget("text"))

    # ── 3. VIZSZINTES GORGETES: a TELJES oldalra, es CSAK HA KELL ─────────
    # ⚠ Egy szakaszra rakott csuszka azt a latszatot keltene, hogy csak ott log
    # ki valami — holott a szomszed szakasz epp ugy levagodhat, csak nincs
    # csuszkaja. Es egy allandoan ott ulo, kihasznalatlan csuszka ugyanaz a zaj,
    # mint egy mindig latszo „nincs hiba" felirat.
    _cv = d._body_canvas
    _hbar = [w for w in _cv.master.winfo_children()
             if isinstance(w, tk.Scrollbar) and str(w.cget("orient")) == "horizontal"]
    check("van vizszintes csuszka az OLDAL aljan", len(_hbar) == 1, str(_hbar))
    if _hbar:
        _hb2 = _hbar[0]
        _top.deiconify()
        _top.geometry("1900x800"); _top.update()
        # ⚠ A TORDELT cimkek nem hizlalhatjak a lapot: a `_autowrap` a VASZON
        # szelessegehez tord, tehat a szoveg soha nem szul csuszkat. (Egy
        # tordeletlen cimke 2 220 px-et kert — a csuszka 1 900 px-en sem tunt el,
        # es az orak sem nyultak.)
        check("szeles ablakon a csuszka NEM latszik", not _hb2.winfo_manager(),
              f"manager={_hb2.winfo_manager()!r}")
        _top.geometry("420x800"); _top.update()
        check("keskeny ablakon MEGJELENIK", bool(_hb2.winfo_manager()),
              f"manager={_hb2.winfo_manager()!r}")
        # ⚠ A csomagolasi SORREND: a canvas `expand=True`, tehat ha a csuszka
        # utana kerulne be, nem maradna neki hely — meglenne, de lathatatlanul.
        check("...es tenyleg LATSZIK is (magassaga van)", _hb2.winfo_height() > 1,
              f"{_hb2.winfo_height()}px")
        _top.geometry("1900x800"); _top.update()
        check("ujra szelesitve ELTUNIK", not _hb2.winfo_manager(),
              f"manager={_hb2.winfo_manager()!r}")
        _top.withdraw()

    # ── 3b. A TORDELES NEM CSATOLHAT VISSZA a gorgetesre ──────────────────
    # ⚠ Ez a teszt egy BEFAGYAST oriz. A hosszu terv-szoveget tordelni kell
    # (tordeletlenul 2 220 px-et kert, es EMIATT logott ki a teljes lap), de ha
    # a `wraplength` a SZULO szelessegehez kotodik, vegtelen ciklus keletkezik:
    #
    #   wraplength <- szulo szelessege -> a cimke igenyelt szelessege valtozik
    #             -> a lap igenye valtozik -> a scroll_area atmeretezi a belso
    #             keretet (max(w, need)) -> a szulo szelessege valtozik -> ...
    #
    # Merve: a Tk `update()` NEM tert vissza. A vaszon szelessege viszont az
    # ABLAK merete — fuggetlen bemenet, amit nem a tartalom allit.
    _cfg_binds = d._body_canvas.bind("<Configure>")
    check("a tordeles a VASZON szelessegere van kotve", bool(_cfg_binds),
          "nincs <Configure> a vaszonon")
    check("...es a terv-cimke tenylegesen tordel",
          int(d._tuned_lbl.cget("wraplength") or 0) > 0,
          str(d._tuned_lbl.cget("wraplength")))
    # ⚠ ES A KORLAT: a tordelt cimke SOHA nem lehet szelesebb a vaszonnal —
    # kulonben megis o szulne a vizszintes csuszkat.
    _top.deiconify(); _top.geometry("1500x800"); _top.update()
    check("a tordelt cimke nem szelesebb a vasznanal",
          d._tuned_lbl.winfo_reqwidth() <= d._body_canvas.winfo_width(),
          f"cimke={d._tuned_lbl.winfo_reqwidth()} vaszon={d._body_canvas.winfo_width()}")
    _top.withdraw()

    # ── 4. A SZAKASZOK TELJES SZELESSEGUEK ────────────────────────────────
    _bad = [k for k, sc in d._sections.items()
            if sc.frame.pack_info().get("fill") != "x"]
    check("MINDEN szakasz teljes szelessegre csomagol", not _bad, str(_bad))

    root.destroy()
else:
    check("nincs tkinter (kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
