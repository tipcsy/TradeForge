"""A foképernyo jelmagyarazata + a kockazatcsokkento preset elerhetosege (v2.2.0).

BEJELENTES: „Live stopped kivezetes, nem tanitott, Optimalizalas... Risky Felezo
Pajzs... Ezekre mar nem nagyon van a fokepernyon hely, mert ezek mar nem itt
allithatoak."

KET dolog volt mogotte:

  1. A jelmagyarazat a `classic` nezet SZINKODJAIT irja le (a szimbolum neve
     allapot szerint szinezodik, es a soron van egy kattinthato „R" preset-gomb).
     A 2.0 sorban EGYIK SEM letezik — a szimbolum mindig FG_WHITE, preset-cella
     pedig nincs —, tehat mind a 12 elem felrevezet, es elvisz egy savnyi helyet.

  2. A VALODI hiany: a preset per INSTRUMENTUM el, es a 2.0-ban sehol nem volt
     allithato egy nyitott pozicio NELKULI parra. A Poziciok-ful menuje csak
     meglevo pozicionál nyilik, a `classic` „R" gombja pedig nincs a 2.0-ban.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. Melyik preset valaszthato — KOZOS szabaly ══════════════════════════
#
# Korabban ez a szabaly CSAK a Poziciok-ful menujeben elt, kezzel beirva. Most
# tiszta fuggveny, tehat a menu es az uj ablak-valaszto nem tud szetcsuszni.

from core import risk_reduction as R

check("felezheto lot, normal szamla -> semmi nincs tiltva",
      R.preset_blockers(1.0, 0.01, 0.01, False) == {})
_nf = R.preset_blockers(0.01, 0.01, 0.01, False)
check("nem felezheto lot -> a RESZLEGES ZARAST igenylok tiltva",
      set(_nf) == set(R.PARTIAL_CLOSE_PRESETS), str(sorted(_nf)))
check("...es az OK is megvan (a felulet kiirja)",
      all(v == "nem felezhető" for v in _nf.values()), str(_nf))
_nt = R.preset_blockers(1.0, 0.01, 0.01, True)
check("NETTING szamla -> ugyanazok tiltva, MAS okkal",
      set(_nt) == set(R.PARTIAL_CLOSE_PRESETS)
      and all(v == "NETTING számla" for v in _nt.values()), str(_nt))
check("NINCS pozicio (cur_lot=None) -> a lot-alapu tiltas NEM ervenyes",
      R.preset_blockers(None, 0.01, 0.01, False) == {})
check("...de a netting-korlat akkor is all (az a SZAMLA tulajdonsaga)",
      set(R.preset_blockers(None, 0.01, 0.01, True)) == set(R.PARTIAL_CLOSE_PRESETS))

# A csak stopot mozgato technikak SOSEM tiltottak (nem zarnak reszt).
for _p in (R.PRESET_NONE, R.PRESET_OFF, R.PRESET_RISKY, R.PRESET_FIBO, R.PRESET_THIRDS):
    check(f"a(z) {_p!r} sosem tiltott (nem zar reszt)",
          _p not in R.preset_blockers(0.01, 0.01, 0.01, True))

# A Poziciok-ful menuje is a KOZOS szabalyt hasznalja (nem sajat masolatot).
gsrc = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a Poziciok-menu a kozos preset_blockers-t hivja",
      "_rrx.preset_blockers(cur_lot, min_lot, lot_step, _netting)" in gsrc)
check("...es nincs tobbe kezi 'nem felezheto' szoveg a menuben",
      '_why = "NETTING számla" if _netting else "nem felezhető"' not in gsrc)

# ══ 2. A preset PENZT ERINT a tomeges alkalmazasban ═══════════════════════

from core import bulk_apply as B

check("a preset sor ismert a bulk_apply-ban", "rr_preset" in B.ROWS)
check("...PENZT ERINTOKENT (nyomatekosabb figyelmeztetes)",
      B.affects_money({"rr_preset"}) is True)
check("csak a MEGVALTOZOTT sor terjed",
      B.changed_rows({"rr_preset": "off", "market": "x"},
                     {"rr_preset": "shield", "market": "x"}) == {"rr_preset"})

# ══ 3–4. Felulet: jelmagyarazat + preset-valaszto ═════════════════════════

try:
    import tkinter as _tk
    _tk.Tk().destroy()
    HAS_TK = True
except Exception as _e:
    HAS_TK = False
    print(f"SKIP  tkinter nem elerheto ({_e})")

if HAS_TK:
    import core.rr_state as rrs
    import core.risky_mode as rm
    _tmp = Path(tempfile.mkdtemp())
    rrs.PATH = _tmp / "risk_mode.json"
    rrs._STATE = {}
    rm.PATH = _tmp / "risky_mode.json"

    import dashboard.gui as G
    from dashboard import theme as _t
    from trading.live_trader import PairDashboardState

    CFG = {"strategy": {"name": "wpr_sma"}, "trading": {"max_open_slots": 4},
           "dashboard": {"layout": "live2"},
           "pairs": {"GOLD": {"enabled": True, "point_size": 0.01,
                              "min_lot": 0.01, "lot_step": 0.01,
                              "strategies": ["wpr_sma"]}}}
    _t._FONTS.clear()
    for _m in ("_start_refresh_loops", "_start_bg_poller", "_poll_mt5", "_ensure_pool"):
        setattr(G.DashboardWindow, _m, lambda self: None)
    G.DashboardWindow._save_main_config = lambda self: True

    w = None
    try:
        ds = PairDashboardState(symbol="GOLD", trained=True, enabled=True)
        ds.digits, ds.bid, ds.ask = 2, 2000.0, 2000.5
        w = G.DashboardWindow(copy.deepcopy(CFG), {"GOLD": ds}, {"GOLD": "LIVE"}, {},
                              on_play_pair=None, on_stop_pair=None)
        w.root.withdraw()
        w.root.update_idletasks()

        # ── 3. A jelmagyarazat elrendezes-fuggo ALAPERTELMEZESE ───────────
        _d = w.cfg["dashboard"]
        _d.pop("show_legend", None)
        _d["layout"] = "live2"
        check("live2: alapbol NINCS jelmagyarazat (egyik eleme sem igaz ott)",
              w._show_legend() is False)
        _d["layout"] = "classic"
        check("classic: alapbol VAN (ott a szinkodok ervenyesek)",
              w._show_legend() is True)
        _d["show_legend"] = True
        _d["layout"] = "live2"
        check("live2 + kifejezett true -> latszik (aki keri, visszakapja)",
              w._show_legend() is True)
        _d["show_legend"] = False
        _d["layout"] = "classic"
        check("classic + kifejezett false -> eltunik",
              w._show_legend() is False)
        _d.pop("show_legend", None)
        _d["layout"] = "live2"

        # ── 4. A preset-valaszto az INSTRUMENTUM-ablakban ─────────────────
        check("kiindulas: a preset meg alapertelmezett",
              rrs.effective_preset("GOLD") == "off", rrs.effective_preset("GOLD"))

        w._show_instrument_settings("GOLD")
        w.root.update_idletasks()
        _tops = [c for c in w.root.winfo_children()
                 if isinstance(c, _tk.Toplevel) and "instrumentum" in c.title()]
        check("az instrumentum-ablak megnyilt", len(_tops) == 1, str(len(_tops)))
        if _tops:
            _oms, _btns = [], []

            def _walk(x):
                for c in x.winfo_children():
                    if isinstance(c, _tk.OptionMenu):
                        _oms.append(c)
                    if isinstance(c, _tk.Button):
                        _btns.append(c)
                    _walk(c)
            _walk(_tops[0])
            check("van preset-valaszto (az utolso OptionMenu)", len(_oms) >= 2,
                  str(len(_oms)))
            _rr = _oms[-1]
            _m = _rr["menu"]
            _labels = [_m.entrycget(i, "label") for i in range(_m.index("end") + 1)]
            check("MINDEN preset felkinalva", len(_labels) == len(rrs.CYCLE),
                  str(_labels))
            check("...emberi nevekkel (nem betukoddal)",
                  "Pajzs" in _labels and "Felező" in _labels, str(_labels))

            # Valasztas + Mentes -> a per-par allapotba ir (NEM a config.json-ba)
            _m.invoke(_labels.index("Pajzs"))
            _save = [b for b in _btns if "Ment" in b.cget("text")]
            check("van Mentes gomb", bool(_save))
            if _save:
                _save[0].invoke()
                w.root.update_idletasks()
                check("a preset MENTODOTT (a 2.0-ban eddig sehogy nem ment)",
                      rrs.effective_preset("GOLD") == "shield",
                      rrs.effective_preset("GOLD"))
                check("...a per-par allapotfajlba, nem a config.json-ba",
                      json.loads(rrs.PATH.read_text(encoding="utf-8"))
                      .get("GOLD", {}).get("preset") == "shield")
                check("a sor-allapot is koveti (a tabla azonnal helyes)",
                      getattr(ds, "rr_preset", None) == "shield")
                check("a config.json-ba NEM szivargott preset",
                      "rr_preset" not in (w.cfg["pairs"]["GOLD"]))
    finally:
        if w is not None:
            for c in list(w.root.winfo_children()):
                if isinstance(c, _tk.Toplevel):
                    try:
                        c.grab_release()
                    except Exception:
                        pass
                    c.destroy()
            w.root.destroy()

# ══ 5. A pelda-config dokumentalja a kapcsolot ════════════════════════════

_ex = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
check("config.example: van show_legend kulcs", "show_legend" in _ex["dashboard"])
check("...null ertekkel (= az elrendezes dontson)",
      _ex["dashboard"]["show_legend"] is None)
check("...es magyarazattal", "_comment_legend" in _ex["dashboard"])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
