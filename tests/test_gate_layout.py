"""Mely kapuk latszanak, milyen sorrendben — es mit jelent a KIKAPCSOLT.

A user kerese (Obsidian, 2026-08-07): a Beallitas ablakban legyen ket lista
(Kikapcsolt / Bekapcsolt), sorrenddel; es „kikapcsolva egyetlen instrumentumra
sem lesz hatassal".

EZ A LEGFONTOSABB ALLITAS ITT: a kikapcsolas KET dolgot jelent EGYUTT —
  1. az oszlop nem latszik, ES
  2. a kapu EGYETLEN instrumentumon sem szol bele a kereskedesbe.
Ha csak elrejtenenk az oszlopot, a kapu LATHATATLANUL blokkolhatna tovabb.

...es a per-par beallitasok kozben NEM vesznek el: felfuggesztjuk oket.
"""
import pathlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import gate_layout as gl
from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. Alapertelmezes: a MAI viselkedes ═══════════════════════════════════
check("hianyzo config -> MINDEN kapu, a REGISTRY sorrendjeben",
      gl.enabled_gates({}) == list(g.KEYS), str(gl.enabled_gates({})))
check("...es semmi nincs kikapcsolva", gl.disabled_gates({}) == [])

# ══ 2. A LISTA dont — kor es sorrend ══════════════════════════════════════
cfg = {"dashboard": {"gate_order": ["cost", "spread"]}}
check("csak a listaban szereplok engedelyezettek",
      gl.enabled_gates(cfg) == ["cost", "spread"], str(gl.enabled_gates(cfg)))
check("a tobbi KIKAPCSOLT",
      set(gl.disabled_gates(cfg)) == {g.TF_ALIGN, g.MARKET, g.MOMENTUM},
      str(gl.disabled_gates(cfg)))
check("a SORREND a listat koveti (nem a REGISTRY-t)",
      gl.enabled_gates(cfg)[0] == "cost")
check("ures lista -> egyetlen kapu sem",
      gl.enabled_gates({"dashboard": {"gate_order": []}}) == [])

# Az OSZLOP-kulcs elter a KAPU-kulcstol egy helyen (`tf_align` -> `align`)
check("a tf_align oszlopa `align`", gl.column_key(g.TF_ALIGN) == "align")
check("...es visszafele is", gl.gate_key("align") == g.TF_ALIGN)
check("a lista OSZLOP-kulcsokkal is lekerheto",
      gl.enabled_columns({"dashboard": {"gate_order": ["tf_align", "spread"]}})
      == ["align", "spread"])
check("az oszlop-kulcs a configban is elfogadott (`align`)",
      gl.enabled_gates({"dashboard": {"gate_order": ["align"]}}) == [g.TF_ALIGN])

# Robusztussag: elgepeles ne tuntessen el kaput NEMAN
check("ismeretlen kulcs egyszeruen kimarad",
      gl.enabled_gates({"dashboard": {"gate_order": ["spread", "nincs_ilyen"]}})
      == ["spread"])
check("ismetlodes nem duplaz",
      gl.enabled_gates({"dashboard": {"gate_order": ["spread", "spread"]}})
      == ["spread"])

# ══ 3. A KIKAPCSOLAS HATASTALANIT — ez a lenyeg ═══════════════════════════
# Egy par, ahol a spread-kapu KIFEJEZETTEN blokkolora van allitva.
live = {"dashboard": {"gate_order": list(g.KEYS)},
        "pairs": {"GOLD": {"gates": {g.SPREAD: {"wpr_sma": g.EFFECT_BLOCK}}}}}
check("bekapcsolva a per-par beallitas ervenyes",
      g.effect_for(live, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)

off = {"dashboard": {"gate_order": [k for k in g.KEYS if k != g.SPREAD]},
       "pairs": live["pairs"]}
check("KIKAPCSOLVA a kapu SEHOL nem szol bele",
      g.effect_for(off, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_NONE)
check("...a motor igy meg sem meri",
      not g.active(g.effects_for(off, "GOLD", "wpr_sma"), g.SPREAD))
_eff, _src = g.effect_with_source(off, "GOLD", "wpr_sma", g.SPREAD)
check("...es a felulet MEGMONDJA, miert (nem hazudik sima 'Ki'-t)",
      _src == g.SRC_MASTER_OFF, _src)
check("...az indoklas emberi", "KIKAPCSOLVA" in g.SOURCE_LABEL[g.SRC_MASTER_OFF])

# FELFUGGESZT, NEM TOROL: a per-par beallitas a configban marad
check("a per-par beallitas NEM veszett el",
      off["pairs"]["GOLD"]["gates"][g.SPREAD]["wpr_sma"] == g.EFFECT_BLOCK)
back = {"dashboard": {"gate_order": list(g.KEYS)}, "pairs": off["pairs"]}
check("...visszakapcsolva ujra el",
      g.effect_for(back, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)

# A tobbi kapura NINCS hatassal
check("a kikapcsolas csak AZT az egy kaput erinti",
      g.effect_for(off, "GOLD", "wpr_sma", g.TF_ALIGN)
      == g.effect_for(live, "GOLD", "wpr_sma", g.TF_ALIGN))

# ══ 4. Iras a configba ════════════════════════════════════════════════════
c = {}
gl.apply_order(c, ["cost", "align", "spread"])
check("a TELJES listat kiirja (a fajlbol deruljon ki a sorrend)",
      c["dashboard"]["gate_order"] == ["cost", g.TF_ALIGN, "spread"],
      str(c["dashboard"]["gate_order"]))
gl.apply_order(c, ["spread", "hulyeseg", "spread"])
check("iraskor is szurunk (ismeretlen/ismetlodo kulcs)",
      c["dashboard"]["gate_order"] == ["spread"])
check("a kiirt lista visszaolvasva ugyanaz",
      gl.enabled_gates(c) == ["spread"])

# ══ 5. A BEALLITAS ABLAK — ket eles hiba orzese ═══════════════════════════
try:
    import tkinter as _tk
    _p = _tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA (Tk resz): {type(e).__name__}: {e}")

if TK_OK:
    import dashboard.gui as _G
    from dashboard import theme as _th
    from trading.live_trader import PairDashboardState as _PDS
    _th._FONTS.clear()
    _G.DashboardWindow._start_bg_poller = lambda self: None
    _G.DashboardWindow._poll_mt5 = lambda self: None
    _G.OptimizerController._ensure_pool = lambda self: None
    _G.DashboardWindow._save_main_config = lambda self: True
    # ⚠ A ⚙ mentes-aga a VALODI `ROOT/config.json`-ba ir (`write_config_file`) —
    # a `_save_main_config` stubolasa NEM eleg, az egy MASIK ut. Egy korabbi
    # valtozat ezt nem teritette el, es a teszt LETAROLTA a felhasznalo eles
    # configjat, broker-adatokkal egyutt. A ROOT-ot teritjuk el, ahogy a
    # `test_strategy_availability.py` is teszi.
    import tempfile as _tf
    _tmp = pathlib.Path(_tf.mkdtemp(prefix="tf_gatelayout_"))
    _root_orig = _G.ROOT
    _G.ROOT = _tmp
    _cfg = {"strategy": {"name": "wpr_sma"},
            "available_strategies": {"wpr_sma": True, "ml_ai": True},
            "trading": {"account_risk_pct": 0.01, "max_open_slots": 4,
                        "daily_loss_limit_pct": 0.015, "daily_loss_limit_usd": 0},
            "dashboard": {"layout": "canvas",
                          "gate_order": ["spread", "momentum", "cost", "tf_align"]},
            "pairs": {"GOLD": {"enabled": True, "point_size": 0.01,
                               "pv1_point": 0.88, "min_lot": 0.01,
                               "lot_step": 0.01, "strategies": ["wpr_sma"]}}}
    _ds = _PDS(symbol="GOLD", trained=True, enabled=True)
    _ds.digits = 2
    _w = None
    try:
        _w = _G.DashboardWindow(_cfg, {"GOLD": _ds}, {"GOLD": "LIVE"}, {},
                                on_play_pair=None, on_stop_pair=None)
        _w.root.geometry("300x200"); _w.root.update()
        _w._show_settings(); _w.root.update()
        _top = [x for x in _w.root.winfo_children()
                if isinstance(x, _tk.Toplevel)][0]

        def _walk(x, out=None):
            out = [] if out is None else out
            out.append(x)
            for c in x.winfo_children():
                _walk(c, out)
            return out

        # (a) A GOMBSOR az ABLAK alja, a tartalom ELOTT csomagolva. A `pack` a
        # hivas sorrendjeben oszt helyet: ha a tartalom kapna meg eloszor a
        # teruletet `expand=True`-val, a gombok kis ablaknal KISZORULNANAK — ezt
        # panaszolta a felhasznalo ("csak akkor latszik, ha szelesebbre nyitom").
        _sides = [sl.pack_info().get("side") for sl in _top.pack_slaves()]
        check("a gombsor az ablak ALJARA, a tartalom ELE van csomagolva",
              _sides[:2] == ["bottom", "bottom"] and _sides[-1] == "top",
              str(_sides))
        _save_btn = next(b for b in _walk(_top)
                         if isinstance(b, _tk.Button) and b.cget("text") == "Mentés")
        _cancel_btn = next(b for b in _walk(_top)
                           if isinstance(b, _tk.Button) and b.cget("text") == "Mégse")
        _bad = []
        for _geo in ("900x700", "520x300", "420x220"):
            _top.geometry(_geo); _top.update()
            _y = _save_btn.winfo_rooty() - _top.winfo_rooty()
            if not _save_btn.winfo_ismapped() or not (0 <= _y < _top.winfo_height()):
                _bad.append(f"{_geo}: mapped={_save_btn.winfo_ismapped()} y={_y}")
        check("a Mentés/Mégse KIS ablaknál is látszik", not _bad, "; ".join(_bad))
        check("a Mégse is ott van", _cancel_btn.winfo_ismapped())

        # (b) A FULVALTAS nem dobhat "bad window path name"-t. A hiba oka egy
        # `popup = _page["Json"]` ujrakotes volt: a mentes vegi `popup.destroy()`
        # emiatt a LAPOT torolte az ABLAK helyett.
        _tabs = [l for l in _walk(_top) if isinstance(l, _tk.Label)
                 and l.cget("text") in ("Json", "Kapuk", "Stratégiák")]
        check("mindharom bal ful letezik", len(_tabs) == 3,
              str([l.cget("text") for l in _tabs]))
        _err = None
        try:
            for _l in _tabs + list(reversed(_tabs)):
                _l.event_generate("<Button-1>", when="now")
                _top.update()
        except Exception as _e:
            _err = f"{type(_e).__name__}: {_e}"
        check("a fülváltás hiba nélkül megy (oda-vissza is)", _err is None, str(_err))
        check("a Json lap NEM semmisült meg",
              all(l.winfo_exists() for l in _tabs))

        # (c) A kapu KIVETELE AZONNAL latszodjon. Eles hiba: a user kivette a
        # Lenduletet, mentett — es az oszlop MARADT. A lista a tabla
        # felepitesekor kerul a `collapsed`-be, es a mentes utan senki nem szolt
        # a tablanak; csak ujraindulaskor tunt volna el.
        _tbl = getattr(_w, "_live2", None)
        if _tbl is not None and hasattr(_tbl, "set_gate_columns"):
            check("indulaskor ott a Lendulet oszlop", (0, "momentum") in _tbl._items)
            _w.cfg["dashboard"]["gate_order"] = ["spread", "cost", "tf_align"]
            _w._apply_gate_columns(); _w.root.update()
            check("kivetel utan AZONNAL eltunik (nem kell ujraindulas)",
                  (0, "momentum") not in _tbl._items)
            check("...a tobbi oszlop viszont megmarad", (0, "spread") in _tbl._items)
            _w.cfg["dashboard"]["gate_order"] = ["spread", "momentum", "cost", "tf_align"]
            _w._apply_gate_columns(); _w.root.update()
            check("visszatetel utan ujra megjelenik", (0, "momentum") in _tbl._items)
            # ⚠ A tabla OSZLOP-kulcsokat tarol (`align`), nem kapu-kulcsokat
            # (`tf_align`) — a kettо egy helyen ter el (lasd `gate_layout`).
            check("valtozatlan listara NEM epit ujra (nincs felesleges villanas)",
                  _tbl.set_gate_columns(gl.enabled_columns(_w.cfg)) is False,
                  str(gl.enabled_columns(_w.cfg)))

        # A Mentés az ABLAKOT zárja (nem a lapot)
        _save_btn.invoke(); _w.root.update()
        check("a Mentés az ABLAKOT zárja be", not _top.winfo_exists())
        check("a mentes a TEMP mappaba irt, nem a valodi config.json-ba",
              (_tmp / "config.json").exists(), str(_tmp))
    finally:
        _G.ROOT = _root_orig
        if _w is not None:
            _w.root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
