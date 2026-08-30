"""A karikak MAGYARAZATA, es az Inditas gomb LATHATOSAGA.

⚠ 1. A KARIKAK. A soron stadiumonkent egy kor mutatja, hol tart a belepo
szetupja — de SEHOL nem volt kiirva, MELYIK kor mit jelent. A jelolo a napi
hasznalat legfontosabb eleme; a jelrendszert a felhasznalonak kellett
kikovetkeztetnie a viselkedesbol.

A lista a STRATEGIA SAJAT deklaraciojabol epul (`columns()[0].stages`), nem
bedrotozott szovegbol. Ez nem stilus: a wpr_sma-nak es a bollingernek HAROM
stadiuma van, az ml_ai-nak KETTO — egy „harom karika" felirat maris hazudna, es
egy uj strategia neman rossz magyarazatot kapna.

⚠ 2. AZ INDITAS GOMB. Merve (Ger40, wpr_sma): a Parameter lap tartalma 3112 px,
az ablak a kepernyo 88%-an 1520 px — a Futtatas szakasz 1495 px-nel KEZDODIK,
tehat a benne ulo gomb pont az also el ala esett. Nagyobb ablak ezt NEM oldja
meg: nincs az a kepernyo, amin egy 3000 px-es lap elfer. A gomb ezert oda kerult,
ahol ennek az ablaknak MINDEN cselekvese van (Mentes · Megse) — es vele a futas
ALLAPOTA is, mert a visszajelzes ugyanugy nem lehet a lap aljara rejtve.
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
    TK = True
except Exception as e:
    TK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({e})")

from strategy import get_strategy_by_name

# ── 0. A STADIUMOK (Tk nelkul is merheto) ────────────────────────────────
_counts = {}
for _n in ("wpr_sma", "bollinger_squeeze_breakout", "ml_ai"):
    _counts[_n] = len(get_strategy_by_name(_n).columns()[0].stages)
check("a strategiak NEM egyforma szamu stadiumot deklaralnak",
      len(set(_counts.values())) > 1, str(_counts))
check("a wpr_sma-nak es a bollingernek 3",
      _counts["wpr_sma"] == 3 == _counts["bollinger_squeeze_breakout"])
check("az ml_ai-nak KETTO (ezert nem lehet bedrotozni a harmat)",
      _counts["ml_ai"] == 2, str(_counts["ml_ai"]))

if TK:
    from strategy.settings import load_config
    from dashboard import instrument_dialog as idlg, theme

    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    fonts = theme.fonts()
    cfg = load_config("config.json")

    def _texts(widget):
        out = []

        def walk(w):
            for c in w.winfo_children():
                try:
                    if "text" in c.keys():
                        t = str(c.cget("text"))
                        if t:
                            out.append(t)
                except tk.TclError:
                    pass
                walk(c)
        walk(widget)
        return out

    # ── 1. A LEGENDA minden strategian ───────────────────────────────────
    for name in ("wpr_sma", "bollinger_squeeze_breakout", "ml_ai"):
        st = get_strategy_by_name(name)
        d = idlg.InstrumentParamsDialog(root, "Ger40", cfg, st, fonts["header"],
                                        fonts["small"], lambda: None,
                                        root_cfg=copy.deepcopy(cfg))
        root.update_idletasks()
        blob = " ".join(_texts(d._shell.page("overview")))
        check(f"[{name}] van karika-magyarazat", "Mit jelentenek a karikák" in blob)
        # ⚠ A DARABSZAM a strategiaebol jon, nem bedrotozva.
        _n = len(st.columns()[0].stages)
        check(f"[{name}] a HELYES darabszamot mondja ({_n})",
              f"A soron {_n} kör" in blob, blob[blob.find("A soron"):][:40])
        # Minden stadium-cimke szerepel, SORSZAMOZVA (a soron balrol jobbra).
        _miss = [lab for _k, lab in st.columns()[0].stages if lab not in blob]
        check(f"[{name}] minden stadium neve kiirva", not _miss, str(_miss))
        check(f"[{name}] sorszamozva (a kor HELYE a soron)",
              all(f"{i}." in blob for i in range(1, _n + 1)))
        # ⚠ A SZINEK jelentese is kell: egy piros kor NEM hiba, hanem kesz
        # SELL-szetup. Enelkul a magyarazat felkesz.
        check(f"[{name}] a SZINEK jelentese is ott van",
              "zöld = BUY" in blob and "piros = SELL" in blob
              and "NEM hiba" in blob)

        # ⚠ A KOROK AZ ELO ALLAPOTOT MUTATJAK, nem disz-zoldet. Egy statikus
        # pelda-kor mellett a magyarazat elolvashato, de nem hasznalhato: a
        # kerdes nem az, hogy „mit jelentene, ha zold volna", hanem hogy MOST
        # melyik feltetel all.
        from dashboard import live_row as _lr
        _keys = [k for k, _ in st.columns()[0].stages]
        check(f"[{name}] provider NELKUL halvany (nem hazudunk zoldet)",
              all(d._legend_dots[k].cget("fg") == _lr._stage_color("muted")
                  for k in _keys),
              str({k: d._legend_dots[k].cget("fg") for k in _keys}))
        _fake = {"green": 0, "red": 1, "muted": 2}
        _want = {k: ["green", "red", "muted"][i % 3] for i, k in enumerate(_keys)}
        d.stage_cells_of = lambda sym, nm, _w=_want: {k: ("●", v) for k, v in _w.items()}
        d._refresh_legend_dots()
        root.update_idletasks()
        # ⚠ UGYANAZ A SZIN-FUGGVENY, mint a soron: ket kepletbol elobb-utobb ket
        # kulonbozo kep lenne, es itt epp az volna a baj, ha a magyarazat mast
        # mutatna, mint amit magyaraz.
        check(f"[{name}] elo allapotbol szinez (a sorral EGYEZO fuggvennyel)",
              all(d._legend_dots[k].cget("fg") == _lr._stage_color(v)
                  for k, v in _want.items()),
              str({k: d._legend_dots[k].cget("fg") for k in _keys}))
        d.popup.destroy()

    # ── 2. AZ INDITAS GOMB: a FUTTATAS szakaszban, BALRA ─────────────────
    # ⚠ A felhasznalo kerése: „az lenne a jo, ha a futtatasnal lenne, de akkor
    # rakjuk bal oldalra (rakhatjuk kozvetlen a mi fog tortenni ala)". A gomb
    # tehat ODA tartozik, ahol a magyarazata is van — a LATHATOSAGOT nem a
    # helye oldja meg, hanem az, hogy a szakasz kinyitasa RAGORDUL.
    d = idlg.InstrumentParamsDialog(root, "Ger40", cfg,
                                    get_strategy_by_name("wpr_sma"),
                                    fonts["header"], fonts["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    d._shell.show("params")
    top = d.popup
    top.deiconify(); top.update(); top.update_idletasks()

    _btn = d._plan_btn
    check("az Indítás a FUTTATÁS szakaszban van",
          str(d._sections["futtatas"].body) in str(_btn), str(_btn))
    check("...és PONTOSAN EGY van belőle az ablakban",
          sum(1 for t in _texts(top) if t.strip() == "Indítás") == 1,
          str([t for t in _texts(top) if "ndít" in t]))

    # ⚠ A LATHATOSAG: a lap 3000 px magas, a Futtatas szakasz 1495 px-nel
    # kezdodik — kinyitas utan a gombnak a latoterbe kell kerulnie, kulonben a
    # felhasznalo nem latja, mit nyitott ki.
    d._sections["futtatas"].set_open(False); top.update()
    d._sections["futtatas"].set_open(True); top.update(); top.update()
    _bottom = top.winfo_rooty() + top.winfo_height()
    check("a szakasz kinyitasa RAGORDUL (a gomb latoterbe kerul)",
          top.winfo_rooty() < _btn.winfo_rooty() < _bottom,
          f"gomb y={_btn.winfo_rooty()} ablak={top.winfo_rooty()}..{_bottom}")

    # ── 3. A MOD-VALASZTO ────────────────────────────────────────────────
    # ⚠ A futas tipusat eddig KIZAROLAG a pipak dontottek el: egyetlen
    # parameter megnezesehez ki kellett venni MINDEN pipat, utana vissza.
    check("van mod-valaszto", getattr(d, "_run_mode", None) is not None)
    d._run_mode.set(d.RUN_BACKTEST); d._on_run_mode(); top.update_idletasks()
    check("Backtest modban a TENYLEGES mod is backtest",
          d._effective_mode() == d.RUN_BACKTEST)
    # ...AKKOR IS, ha minden be van pipalva — epp ez a lenyeg.
    for _v in d._skip_vars.values():
        _v.set(True)
    d._refresh_opt_space(); top.update_idletasks()
    check("...akkor is, ha MINDEN parameter be van pipalva",
          d._effective_mode() == d.RUN_BACKTEST)
    check("...es a kiirt terv is EZT mondja (nem az optimalizalast)",
          "Egyetlen futás" in d._plan_short.cget("text"),
          d._plan_short.cget("text")[:70])

    # ⚠ ES FORDITVA: ha nincs mit hangolni, a „Hangolas" URES IGERET volna —
    # ilyenkor magatol Backtest, es a valaszto is megmondja, miert.
    d._run_mode.set(d.RUN_PLANNED)
    for _v in d._skip_vars.values():
        _v.set(False)
    d._refresh_opt_space(); top.update_idletasks()
    check("nincs bepipalt parameter -> magatol Backtest",
          d._effective_mode() == d.RUN_BACKTEST, d._run_mode.get())
    check("...es a Hangolás valaszto LETILTVA",
          str(d._rb_planned.cget("state")) == "disabled")
    check("...a felirata megmondja, miert",
          "nincs bepipált" in str(d._rb_planned.cget("text")),
          str(d._rb_planned.cget("text")))

    # A mod MEGJEGYZODIK (par + strategia szinten).
    d._run_mode.set(d.RUN_BACKTEST); d._on_run_mode()
    check("a valasztott mod megjegyzodik",
          d._load_run_mode() == d.RUN_BACKTEST, d._load_run_mode())

    top.withdraw()
    root.destroy()
else:
    check("nincs tkinter (a felulet-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
