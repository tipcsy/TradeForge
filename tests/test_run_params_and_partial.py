"""Ket lelet a Futtatas szakaszrol: elavult parameterek es a nema Pajzs.

⚠ 1. AZ INDITAS A REGI ERTEKEKKEL FUTOTT. A beagyazott backtest a
FELEPITESKORI parameter-pillanatkeppel dolgozik; az ujraepites csak lapvaltaskor
vagy a szakasz kinyitasakor futott le. A leggyakoribb munkamenetben viszont —
atirod a mezot, es ROGTON Inditast nyomsz UGYANAZON a lapon — egyik sem tortenik
meg. A felulet kozben azt allitotta: „ha ott atirsz valamit, ez a lap magatol
frissul".

A felhasznalo igy vette eszre: „hiaba allitom a tp_rr_ratio-t 1,00-rol 2,00-ra,
a celar mintha nem valtozott volna" — a kotes-listaban MINDEN sor +/-1,00R-en
zart. Nem a celar-szamitas volt rossz: a futas nem is latta az uj erteket.

⚠ 2. A PAJZS NEM CSINALT SEMMIT. A reszleges zaras a `trigger_R`-nel lep eletbe
(alap 1,0), a celar viszont `tp_rr_ratio` = 1,0 volt — a CELAR er oda elobb, es
a TELJES poziciot zarja. A Pajzs be volt kapcsolva, es soha nem hatott. A
`trigger_R` addig CSAK fajlbol volt allithato.
"""
import copy
import pathlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

# ⚠ A teszt nem irhat a valodi beallitas-tarba.
import tempfile as _tf
from core import backtest_prefs as _bp
_TMP = pathlib.Path(_tf.mkdtemp(prefix="rp_"))
_ORIG = _bp._FILE
_bp._FILE = _TMP / "backtest_prefs.json"
import atexit as _ax
import shutil as _sh
# ⚠ ES A KOCKAZAT-ALLAPOT SEM. A `_on_be_trail_save` a VALODI
# `data/risk_mode.json`-ba ir (per par preset + parameterek) — az elso
# valtozatom bele is irt egy alapertekkel egyezo kulcsot, amitol a
# `test_rr_owns_be_trail` elbukott („a par ertekei veletlenul epp az
# alapertekek?"). Egy teszt SOHA nem nyulhat a felhasznalo kereskedesi
# beallitasaihoz.
from core import rr_state as _rrst
_RR_ORIG = _rrst.PATH
_rrst.PATH = _TMP / "risk_mode.json"
_rrst._loaded = False
try:
    _rrst.load()
except Exception:
    pass


def _restore():
    _rrst.PATH = _RR_ORIG
    _rrst._loaded = False
    try:
        _rrst.load()
    except Exception:
        pass
    _sh.rmtree(_TMP, ignore_errors=True)


_ax.register(_restore)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import risk_reduction as _rr

# ── 0. A KOZOS IGAZSAGFORRAS (Tk nelkul) ─────────────────────────────────
# Ugyanaz az elv, mint a `be_trail_active`-nal: a felulet ez alapjan dont, mit
# MUTAT — egy hatastalan mezo azt igerne, hogy allithato.
check("a Felezo a halving_fraction-t hasznalja",
      _rr.partial_active(_rr.PRESET_HALVING) == {"trigger_R", "halving_fraction"},
      str(_rr.partial_active(_rr.PRESET_HALVING)))
check("a Pajzs a shield_fraction-t",
      _rr.partial_active(_rr.PRESET_SHIELD) == {"trigger_R", "shield_fraction"})
check("a Pajzs↔Fibo is (Pajzsra oldodhat)",
      "trigger_R" in _rr.partial_active(_rr.PRESET_SHIELD_FIBO))
# ⚠ Ahol NINCS reszleges zaras, ott a trigger_R-nek nincs szerepe.
for _p in (_rr.PRESET_OFF, _rr.PRESET_NONE, _rr.PRESET_RISKY, _rr.PRESET_FIBO):
    check(f"a(z) {_p!r} preseten NINCS reszleges zaras",
          not _rr.partial_active(_p), str(_rr.partial_active(_p)))


try:
    import tkinter as tk
    _p0 = tk.Tk(); _p0.destroy()
    TK = True
except Exception:
    TK = False

if TK:
    from strategy.settings import load_config
    from strategy import get_strategy_by_name
    from dashboard import instrument_dialog as idlg, theme
    from core import rr_state as _rrs

    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    fonts = theme.fonts()
    cfg = load_config("config.json")
    d = idlg.InstrumentParamsDialog(root, "Ger40", cfg,
                                    get_strategy_by_name("wpr_sma"),
                                    fonts["header"], fonts["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    d._shell.show("Paraméter")
    root.update_idletasks()

    # ── 1. AZ INDITAS A FRISS ERTEKKEL fut ───────────────────────────────
    bt = d._run_tab
    check("van beagyazott backtest", bt is not None)
    _old = bt.params.get("tp_rr_ratio")
    d.entries["tp_rr_ratio"].delete(0, "end")
    d.entries["tp_rr_ratio"].insert(0, str(float(_old or 1.0) + 1.0))
    # ⚠ EZ A LENYEG: lapvaltas NELKUL, ahogy a felhasznalo csinalja.
    check("atiras utan a beagyazott meg a REGIT tartja",
          bt.params.get("tp_rr_ratio") == _old, str(bt.params.get("tp_rr_ratio")))
    d._sync_run_params()
    check("a szinkron atviszi az UJ erteket",
          bt.params.get("tp_rr_ratio") == float(_old or 1.0) + 1.0,
          str(bt.params.get("tp_rr_ratio")))
    # ...es az INDITAS maga vegzi el, nem kell kezzel hivni.
    import inspect
    _src = inspect.getsource(idlg.InstrumentParamsDialog._start_planned)
    check("az Indítás MAGA szinkronizal (nem a felhasznalo dolga)",
          "_sync_run_params()" in _src)
    # Vissza az eredetire
    d.entries["tp_rr_ratio"].delete(0, "end")
    d.entries["tp_rr_ratio"].insert(0, str(_old))
    d._sync_run_params()

    # ── 2. A RESZLEGES ZARAS mezoi a feluleten ───────────────────────────
    def _visible():
        return {k for k, fr in d._bt_frames.items() if fr.winfo_manager()}

    d._rr_name.set(_rrs.NAME[_rr.PRESET_OFF]); d._on_rr_change(_rrs.NAME[_rr.PRESET_OFF])
    root.update_idletasks()
    check("BE+trailing preseten NINCS trigger-mezo", "trigger_R" not in _visible(),
          str(_visible()))
    d._rr_name.set(_rrs.NAME[_rr.PRESET_SHIELD]); d._on_rr_change(_rrs.NAME[_rr.PRESET_SHIELD])
    root.update_idletasks()
    check("Pajzson MEGJELENIK a trigger es a hanyad",
          {"trigger_R", "shield_fraction"} <= _visible(), str(_visible()))
    check("...de a Felezo hanyada NEM (az mas preset)",
          "halving_fraction" not in _visible(), str(_visible()))

    # ── 3. A FIGYELMEZTETES: „a Pajzs nem csinal semmit" ─────────────────
    # ⚠ Ez a lelet lenyege. Ha a trigger nem esik a celar ELE, a reszleges zaras
    # SOHA nem hat — a feluleten viszont a preset „Pajzs"-t mutat.
    d.entries["tp_rr_ratio"].delete(0, "end"); d.entries["tp_rr_ratio"].insert(0, "1.0")
    d._bt_vars["trigger_R"].set("1.0"); d._warn_trigger_vs_tp()
    _w = d._trig_warn.cget("text")
    check("trigger == celar -> FIGYELMEZTET", bool(_w) and "SOHA" in _w, _w[:80])
    check("...es JAVASLATOT is ad", "0.8" in _w or "0,8" in _w, _w[-70:])
    d._bt_vars["trigger_R"].set("0.8"); d._warn_trigger_vs_tp()
    check("a trigger a celar ELE huzva -> nincs figyelmeztetes",
          not d._trig_warn.cget("text"), d._trig_warn.cget("text")[:60])
    # A celar EMELESE is feloldja.
    d._bt_vars["trigger_R"].set("1.0")
    d.entries["tp_rr_ratio"].delete(0, "end"); d.entries["tp_rr_ratio"].insert(0, "2.0")
    d._warn_trigger_vs_tp()
    check("...vagy a celar feljebb tolasa", not d._trig_warn.cget("text"))
    # Ahol nincs reszleges zaras, ott NE beszeljen rola.
    d._rr_name.set(_rrs.NAME[_rr.PRESET_OFF]); d._on_rr_change(_rrs.NAME[_rr.PRESET_OFF])
    d.entries["tp_rr_ratio"].delete(0, "end"); d.entries["tp_rr_ratio"].insert(0, "1.0")
    d._bt_vars["trigger_R"].set("1.0"); d._warn_trigger_vs_tp()
    check("nem reszleges preseten NINCS figyelmeztetes",
          not d._trig_warn.cget("text"), d._trig_warn.cget("text")[:60])

    # ── 4. A HANYAD ARANY, nem szazalek ──────────────────────────────────
    # ⚠ Egy beirt „75" nem 75%-ot jelentene, hanem 75-szorost — a motor a lot
    # ennyiszereset zarna. Az elutasitas NEM nema: a mezo visszaall a hatora.
    d._rr_name.set(_rrs.NAME[_rr.PRESET_SHIELD]); d._on_rr_change(_rrs.NAME[_rr.PRESET_SHIELD])
    _keep = d._bt_vars["shield_fraction"].get()
    for _bad in ("75", "0", "1.0", "-0.5"):
        d._bt_vars["shield_fraction"].set(_bad)
        d._on_be_trail_save("shield_fraction")
        check(f"a(z) {_bad!r} hanyad ELUTASITVA",
              d._bt_vars["shield_fraction"].get() != _bad,
              d._bt_vars["shield_fraction"].get())
    d._bt_vars["shield_fraction"].set("0.6"); d._on_be_trail_save("shield_fraction")
    check("ervenyes hanyad ELFOGADVA", d._bt_vars["shield_fraction"].get() == "0.6")
    d._bt_vars["shield_fraction"].set(_keep); d._on_be_trail_save("shield_fraction")

    # ── 5. FUTAS KOZBEN NINCS UJRAEPITES ─────────────────────────────────
    # ⚠ A LELET: „546 futas kesz" kiirodott, rajz sehol. Az ujraepites eldobja a
    # szakasz tartalmat es NULLAZZA a vegigprobalas tengelyeit (`_sw_axes`), a
    # hatterszal viszont fut tovabb — a vegen az UJ, csomagolatlan vaszonra
    # probalna rajzolni ures tengelyekkel, es a `_redraw_sweep` NEMAN kilepett.
    import threading as _th
    d._sw_axes = [("x", [1, 2])]
    d._sw_stop = _th.Event()                  # „epp fut egy vegigprobalas"
    _tab_before = d._run_tab
    d._maybe_build_run()
    check("futas kozben NEM epul ujra a szakasz", d._run_tab is _tab_before)
    check("...es a tengelyek MEGMARADNAK", d._sw_axes == [("x", [1, 2])],
          str(d._sw_axes))
    d._sw_stop = None
    d._bt_running = True                      # „epp fut egy backtest"
    d._maybe_build_run()
    check("futo backtest alatt sem", d._run_tab is _tab_before)
    d._bt_running = False

    # ⚠ ES HA MEGIS elvesznenek a tengelyek: NE legyen nema. Egy „kesz" felirat
    # ures hely folott pontosan az a nema allapot, amit kerulunk.
    d._sw_rows = [{"x": 1, "total_pnl": 1.0}]
    d._sw_axes = []
    d._redraw_sweep()
    check("tengely nelkul KIIRJA, hogy elveszett a rajz",
          "elvesztek" in d._sw_status.cget("text"), d._sw_status.cget("text")[:70])

    d.popup.destroy()
    root.destroy()
else:
    check("nincs tkinter (a felulet-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
