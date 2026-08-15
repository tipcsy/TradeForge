"""A backtest LAPKENT: ugyanaz az osztaly, csak keretbe epulve.

A doksi panasza: ugyanazt a parametert ket kulon kinezetben kellett kezelni. A
backtest ezert nem kulon ablak tobbe, hanem a Parameterek ablak "Futtatas" lapja.

⚠ A LEGFONTOSABB DONTES: a tartalom NEM masolat. Ugyanaz a `BacktestDialog`
epul a lapra, csak `host=` kerettel ablak helyett. Egy "majdnem ugyanolyan"
masodik valtozat pont abban terne el, ami RITKAN fut (megszakitas, hibaag,
MT5-export) — es az nem derulne ki, amig eppen kellene.

Ez a teszt azt orzi, hogy a beagyazott mod ne tegyen olyat, amit egy LAP nem
tehet: ne nyisson ablakot, ne fogja meg a grabot, es ne legyen rajta "Bezaras"
gomb (az a BEFOGLALO ablakot zarna be — a felhasznalo pedig azt hinne, csak a
backtestet csukja be).
"""
import copy
import pathlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()
# ⚠ A TESZT SOHA NEM IRHAT A VALODI BEALLITAS-TARBA. Az elso valtozatom a
# `run_mode`-ot a valodi `data/backtest_prefs.json`-ba mentette, es onnan a
# KOVETKEZO teszt is beolvasta — attol egy MASIK teszt bukott el. A tar
# fajljat temp mappara teritjuk, es a vegen visszaadjuk.
import tempfile as _tf
from core import backtest_prefs as _bp
_PREFS_TMP = pathlib.Path(_tf.mkdtemp(prefix="prefs_"))
_PREFS_ORIG = _bp._FILE
_bp._FILE = _PREFS_TMP / "backtest_prefs.json"
import atexit as _ax
import shutil as _sh


def _restore_prefs():
    _bp._FILE = _PREFS_ORIG
    _sh.rmtree(_PREFS_TMP, ignore_errors=True)


_ax.register(_restore_prefs)



results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    import tkinter as tk
    from dashboard import theme as _th
    from dashboard.backtest_dialog import BacktestDialog
    from strategy.settings import load_config
    from strategy import get_strategy_by_name

    root = tk.Tk(); root.withdraw()
    _th._FONTS.clear()
    fonts = _th.fonts()
    cfg = load_config("config.json")
    st = get_strategy_by_name("wpr_sma")
    sym = next(iter([s for s in cfg["pairs"] if not s.startswith("_")]), None)
    pair_cfg = cfg["pairs"][sym]
    params = {k: v for k, v in st.base_params(cfg).items()
              if not isinstance(v, (dict, list))}

    def _buttons(dlg):
        out = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Button):
                    try:
                        out.append(str(c.cget("text")))
                    except Exception:
                        pass
                walk(c)
        walk(dlg.win if dlg._host is None else dlg._host)
        return out

    # ── BEAGYAZOTT mod ─────────────────────────────────────────────────────
    holder = tk.Toplevel(root)
    holder.withdraw()
    page = tk.Frame(holder)
    page.pack(fill="both", expand=True)
    n_before = len(root.winfo_children())
    emb = BacktestDialog(holder, sym, cfg, st, params, pair_cfg, None,
                         fonts["header"], fonts["small"], host=page)
    root.update_idletasks()

    check("beagyazva NEM nyit uj ablakot",
          len(root.winfo_children()) == n_before,
          f"{n_before} -> {len(root.winfo_children())}")
    check("a `win` a BEFOGLALO ablak (az after/kepernyo-lekerdezes miatt kell)",
          emb.win is holder)
    check("a tartalom a kapott keretbe kerult", len(page.winfo_children()) > 0)
    _b = _buttons(emb)
    check("van indito gomb", any("Backtest" in t for t in _b), str(_b[:4]))
    # ⚠ A "Bezaras" a BEFOGLALO ablakot zarna be.
    check("beagyazva NINCS „Bezárás” gomb", not any("Bezár" in t for t in _b),
          str(_b))

    # A `shutdown()` widget-rombolas NELKUL all le — a befoglalo ablak
    # bezarasakor ezt hivja a gazda.
    emb.shutdown()
    check("shutdown() jelzi a lezarast", emb._closed is True)
    check("...de a widgeteket NEM semmisiti meg", page.winfo_exists() == 1)
    emb._close()
    check("beagyazva a _close() sem zarja be a befoglalo ablakot",
          holder.winfo_exists() == 1)
    holder.destroy()

    # ── ONALLO (regi) mod valtozatlan ──────────────────────────────────────
    parent = tk.Toplevel(root); parent.withdraw()
    solo = BacktestDialog(parent, sym, cfg, st, params, pair_cfg, None,
                          fonts["header"], fonts["small"])
    root.update_idletasks()
    check("onalloan SAJAT ablakot nyit", solo.win is not parent)
    _sb = _buttons(solo)
    check("onalloan VAN „Bezárás” gomb", any("Bezár" in t for t in _sb), str(_sb))
    solo._close()
    check("onalloan a _close() BEZARJA az ablakot", not solo.win.winfo_exists())
    parent.destroy()

    # ── A lap a Parameterek ablakban ───────────────────────────────────────
    from dashboard import instrument_dialog as idlg
    d = idlg.InstrumentParamsDialog(root, sym, cfg, st, fonts["header"],
                                    fonts["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    root.update_idletasks()
    # ⚠ A „Futtatas" mar NEM LAP, hanem a Parameter oldal SZAKASZA. Kulon lapon
    # oda kellett lapozni megnezni, MILYEN ertekkel fut — es pont ez volt a panasz.
    check("nincs kulon „Futtatás” lap", "Futtatás" not in d._shell.names(),
          str(d._shell.names()))
    check("van „Futtatás” SZAKASZ", "futtatas" in d._sections)
    check("van „Eredmény” SZAKASZ", "eredmeny" in d._sections)
    d._shell.show("Paraméter"); root.update_idletasks()
    check("a szakasz beagyazott backtestet epit", d._run_tab is not None)
    check("...ami NEM sajat ablak", d._run_tab.win is d.popup)
    # ⚠ LAPOS beagyazas: az oldal MAGA gorget. Sajat gorgetheto terulet ide
    # osszelapulna, es az egergorgo MINDKETTOT mozditana.
    check("beagyazva NINCS sajat gorgetheto terulet",
          d._run_tab._body_canvas is None)

    _first = d._run_tab
    d._shell.show("Áttekintés"); d._shell.show("Paraméter"); root.update_idletasks()
    check("valtozatlan parameternel NEM epul ujra (nem vesz el az allapot)",
          d._run_tab is _first)

    # ⚠ A backtest a MEGNYITASKORI parameterekkel dolgozik. Ha a Parameter lapon
    # atirsz valamit, egy regi peldany CSENDBEN a regi ertekekkel futna — a lap
    # fejlece viszont az ujakat sugallna.
    _key = next((k for k in d.entries if k == "sma_period"), None)
    if _key:
        d.entries[_key].delete(0, "end")
        d.entries[_key].insert(0, "123")
        d._shell.show("Áttekintés"); d._shell.show("Paraméter")
        root.update_idletasks()
        check("parameter-valtozas utan UJRAEPUL a szakasz",
              d._run_tab is not _first)
        check("...es az UJ erteket viszi", d._run_tab.params.get(_key) == 123,
              str(d._run_tab.params.get(_key)))
    else:
        check("nincs sma_period a parameterek kozott (kihagyva)", True)

    # ── A HAROM lapbol KETTO lett ──────────────────────────────────────────
    # A felhasznalo eszrevetele: "a Parameter, Futtatas, Optimalizalas igazabol
    # egy es ugyanaz — de valahogy megsem". A tores: a Futtatas EGYSZER futtat,
    # az Optimalizalas SOKSZOR — ugyanaz a kerdes, mas szammal. A szamot pedig
    # nem kell kulon beallitani: kiderul abbol, hany parametert pipaltal be.
    check("nincs kulon „Optimalizálás” lap", "Optimalizálás" not in d._shell.names(),
          str(d._shell.names()))

    # ⚠ A LAPON NINCS MASODIK PARAMETER-URLAP. A bejelentes szo szerint: "a
    # futtatas lapon meg mindig ott vannak a parameterek, igy zavaro, hogy
    # melyiket hasznalja epp". Ket szerkesztheto masolat ugyanarra az ertekre
    # pontosan ezt a kerdest szuli — es nincs ra jo valasz.
    check("beagyazva NINCS sajat parameter-urlap", not d._run_tab._pentries,
          f"{len(d._run_tab._pentries)} mezo")

    # ⚠ ES NINCS MASODIK INDITO GOMB SEM. A gazda terv-savjan all EGY gomb, ami a
    # bepipalt dimenziok szamabol dontl; egy masik gomb a TERVET is megkerulne
    # (2 hangolt parameternel egyetlen backtestet inditana).
    _vis = []

    def _walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Button):
                try:
                    t = str(c.cget("text"))
                    if t and c.winfo_ismapped():
                        _vis.append(t)
                except Exception:
                    pass
            _walk(c)

    root.update_idletasks()
    _walk(d._sections["futtatas"].body)
    # ⚠ EGYETLEN inditogomb, a FUTTATAS szakaszban — a magyarazata mellett. A
    # lathatosagot nem a helye oldja meg (a lap 3000 px magas), hanem az, hogy a
    # szakasz kinyitasa RAGORDUL.
    check("a szakaszban OTT az inditogomb",
          any(t.strip() == "Indítás" for t in _vis), str(_vis))
    _all_vis = []
    _vis = _all_vis
    _walk(d.popup)
    check("...es PONTOSAN EGY van belole az ablakban",
          sum(1 for t in _all_vis if t.strip() == "Indítás") == 1,
          str([t for t in _all_vis if "ndít" in t]))
    check("...es a beagyazott sajat gombja nincs kicsomagolva",
          not d._run_tab._btn_start.winfo_ismapped())
    # A widget viszont LETEZIK: a belso allapotvaltasok ra hivatkoznak.
    check("...de a widget letezik (a belso allapotvaltasokhoz)",
          d._run_tab._btn_start is not None)
    # ── EGY FORRAS: a duplikalt vezerlok LEKERULTEK a futtatasrol ─────────
    # A felhasznalo szo szerint: „azert raktuk egy helyre, hogy egy helyen legyen
    # allithato". Minden ilyen vezerlonek van sajat SZAKASZA feljebb a lapon; egy
    # masodik, szerkesztheto masolat pontosan azt a kerdest szuli, amiert az
    # egesz atalakitas elindult: „most akkor melyiket hasznalja?".
    _mapped = []

    def _walk_all(w):
        for c in w.winfo_children():
            try:
                t = str(c.cget("text")) if "text" in c.keys() else ""
            except Exception:
                t = ""
            if t and c.winfo_ismapped():
                _mapped.append(t)
            _walk_all(c)

    root.update_idletasks()
    _walk_all(d._sections["futtatas"].body)
    _joined = " | ".join(_mapped)
    check("NINCS „csak a kereskedesi orakban” kapcsolo",
          "kereskedési órákban" not in _joined, _joined[:160])
    check("NINCS „vegrehajtasi kapuk” mester-kapcsolo",
          "végrehajtási kapuk" not in _joined, _joined[:160])
    check("NINCS masodik Kockázatcsökkentés csoport",
          "Kockázatcsökkentés" not in _joined, _joined[:160])
    check("NINCS masodik Pozícióépítés csoport",
          "Pozícióépítés" not in _joined, _joined[:160])
    # A widgetek LETEZNEK (a belso lathatosag-logika rajuk epul), csak nem latszanak.
    check("...de a widgetek leteznek", d._run_tab._rr_name is not None
          and d._run_tab._hours_filter_var is not None)

    # ⚠ ES AZ ERTEK A SZAKASZBOL JON, FUTASKOR lekerdezve. A beagyazott peldany
    # csak PARAMETER-valtozasra epul ujra; egy atadott pillanatkep elavulna, es a
    # futas neman a regivel menne.
    # ⚠ A TESZT ALLITSA BE, amit mer — ne a felhasznalo configjara tamaszkodjon.
    # Az elso valtozat feltetelezte, hogy mind a 24 ora engedve van; amint a
    # Ger40 orait leszukitettek, elbukott, holott a kod helyes volt.
    for _h in range(24):
        d._hour_on[_h] = True
    check("mind a 24 ora -> nincs ora-szuro", d._run_tab._allowed_hours() is None,
          str(d._run_tab._allowed_hours()))
    d._hour_on[3] = False
    check("a szakaszban kikapcsolt ora AZONNAL hat (nincs ujraepites)",
          d._run_tab._allowed_hours() is not None
          and 3 not in d._run_tab._allowed_hours(),
          str(len(d._run_tab._allowed_hours() or [])) + " ora")
    d._hour_on[3] = True

    from core import risk_reduction as _rrx2
    from core import rr_state as _rrs2
    d._rr_name.set(_rrs2.NAME[_rrx2.PRESET_SHIELD]); d._on_rr_change(_rrs2.NAME[_rrx2.PRESET_SHIELD])
    check("az rr is a szakaszbol jon, elve",
          (d._run_tab._current_rr_spec() or {}).get("preset") == _rrx2.PRESET_SHIELD,
          str((d._run_tab._current_rr_spec() or {}).get("preset")))
    check("az epites is a szakaszbol",
          d._run_tab._current_build_cfg()["mode"] == d._bst.get_mode(sym))

    # ⚠ A KAPUK: beagyazva NINCS mester-kapcsolo, mert a Kapuk szakaszban
    # KAPUNKENT dontesz (`gates_backtest`). Egy folerendelt „mind vagy semmi"
    # elnyomhatna a pipakat — azok neman hatastalanok lennenek.
    import inspect as _insp
    from dashboard import backtest_dialog as _bdmod
    _ssrc = _insp.getsource(_bdmod.BacktestDialog._start)
    check("beagyazva a vegrehajtasi kapuk MINDIG elnek",
          "True if self._host is not None" in _ssrc, "")

    check("a terv-sáv a FUTTATÁS szakaszban él", d._tuned_lbl is not None)
    check("...és EGYETLEN Indítás gomb van", getattr(d, "_plan_btn", None) is not None)

    # ⚠ A FUTAS-ALLAPOT a gomb MELLETT all, nem a rajz dobozaban. Korabban a
    # `_sweep_box`-ban ult, amit az OPTIMALIZALAS ag epp elrejt (`pack_forget`):
    # az Indítás gomb elinditott egy orakig tarto optimalizalast, es SEMMI
    # visszajelzest nem adott. Pontosan igy nez ki egy „beragadt" program.
    # ⚠ A FUTAS ALLAPOTA a gomb MELLETT — de NEM a rajz dobozaban, amit az
    # OPTIMALIZALAS ag epp elrejt (`pack_forget`). Korabban ott ult: az Inditas
    # elinditott egy orakig tarto munkat, es SEMMI visszajelzest nem adott.
    check("a futas-allapot a FUTTATAS szakaszban van",
          getattr(d, "_run_status", None) is not None
          and str(d._sections["futtatas"].body) in str(d._run_status),
          str(getattr(d, "_run_status", None)))
    check("...NEM a rajz dobozaban (amit az OPT ag elrejt)",
          not str(d._run_status).startswith(str(d._sweep_box)),
          f"{d._run_status} vs {d._sweep_box}")
    _osrc = _insp.getsource(idlg.InstrumentParamsDialog._start_planned)
    check("az OPTIMALIZALAS ag a lathato cimkere ir",
          "_sw_status" not in _osrc and "_run_status" in _osrc, "")

    # ⚠ A terv a PILLANATNYI pipakat tukrozze: ha a felulet mast mond, mint ami
    # elindul, a felhasznalo orakra elindit valamit, amire nem szamitott.
    from core import opt_plan as _op
    if d._skip_vars:
        for _v in d._skip_vars.values():
            _v.set(False)
        d._refresh_opt_space()
        # ⚠ 0 hangolt -> a TENYLEGES mod automatikusan „Backtest" (a
        # „Hangolas" ures igeret volna), tehat a terv a backtest szoveget
        # mondja. A lenyeg valtozatlan: EGYETLEN futas indul.
        check("0 hangolt -> a terv EGYETLEN futast mond",
              "gyetlen futás" in d._tuned_lbl.cget("text"),
              d._tuned_lbl.cget("text").split(chr(10))[0])
        check("...es a tenyleges mod is backtest",
              d._effective_mode() == d.RUN_BACKTEST)
        _k = sorted(d._skip_vars)[0]
        d._skip_vars[_k].set(True)
        d._refresh_opt_space()
        check("1 hangolt -> VEGIGPROBALAS", "VÉGIGPRÓBÁLÁS" in d._tuned_lbl.cget("text"),
              d._tuned_lbl.cget("text").split("\n")[0])
        _k2 = sorted(d._skip_vars)[1]
        d._skip_vars[_k2].set(True)
        d._refresh_opt_space()
        check("2 hangolt -> RÁCS", "RÁCS" in d._tuned_lbl.cget("text"),
              d._tuned_lbl.cget("text").split("\n")[0])
        for _v in d._skip_vars.values():
            _v.set(True)
        d._refresh_opt_space()
        check("mind hangolva -> OPTIMALIZÁLÁS",
              "OPTIMALIZÁLÁS" in d._tuned_lbl.cget("text"),
              d._tuned_lbl.cget("text").split("\n")[0])

    # ⚠ A sopres IDOSZAKA a backtest mezoibol jon — EGY helyen allitod. Korabban
    # sajat datum-mezoi voltak, tehat ugyanazt ketszer kellett beirni, es a ket
    # ertek csendben elterhetett.
    import inspect as _insp
    _src = _insp.getsource(idlg.InstrumentParamsDialog._start_sweep)
    check("a söprés a backtest dátum-mezőiből dolgozik (nincs második hely)",
          "_start_var" in _src and "_sw_start" not in _src)

    # Minden lap megnyithato egymas utan (a lapok nem semmisitik egymast)
    ok_all = True
    for t in d._shell.names():
        try:
            d._shell.show(t); root.update_idletasks()
        except Exception:
            ok_all = False
    check("minden lap megnyithato egymas utan", ok_all)
    d.popup.destroy()
    root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
