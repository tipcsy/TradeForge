"""A kapu-hatas beallito felulet — dashboard/instrument_dialog.py.

A terv 8. pontja: a kapu-hatas a STRATEGIA beallito ablakaban allithato, mert az
mar eleve per (instrumentum x strategia) nyilik. A felulet kiirja, hogy egy ertek
OROKOLT vagy ezen a paron beallitott.

A LEGFONTOSABB, AMIT ITT ORZUNK: a valtoztatas a VALODI configba megy. A dialogus
`self.cfg`-je a strategia NEZETE (`config_for_strategy` -> deepcopy), tehat abba
irni semmit nem tenne — a legordulo neman nem mentene. Ezert kap kulon `root_cfg`-t.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

# ── A deepcopy-csapda: ablak nelkul is bizonyithato ───────────────────────
from strategy.settings import config_for_strategy

_cfg = {"pairs": {"GOLD": {"x": 1}}, "strategy": {"name": "wpr_sma"}}
_view = config_for_strategy(_cfg, "wpr_sma")
_view["pairs"]["GOLD"]["x"] = 999
check("a strategia-NEZET MASOLAT (ezert kell a root_cfg)",
      _cfg["pairs"]["GOLD"]["x"] == 1)

if TK_OK:
    from dashboard import theme as _t
    from dashboard.instrument_dialog import InstrumentParamsDialog
    from strategy import get_strategy_by_name
    from core import gates as g

    def make_cfg():
        return {
            "strategy": {"name": "wpr_sma"},
            "available_strategies": ["wpr_sma", "ml_ai"],
            "gates": {"tf_align": {"default": "none", "wpr_sma": "block"}},
            "trading": {"account_risk_pct": 0.01, "max_open_slots": 4},
            "pairs": {"GOLD": {"enabled": True, "point_size": 0.01,
                               "pv1_point": 0.88, "min_lot": 0.01,
                               "lot_step": 0.01, "backtest_spread_points": 48.0,
                               "strategies": ["wpr_sma", "ml_ai"]}},
        }

    def with_dialog(fn, strategy="wpr_sma"):
        cfg = make_cfg()
        saved = {"n": 0}
        root = tk.Tk()
        root.withdraw()
        _t._FONTS.clear()
        f = _t.fonts()
        try:
            d = InstrumentParamsDialog(
                root, "GOLD", cfg, get_strategy_by_name(strategy),
                f["header"], f["small"],
                lambda: saved.__setitem__("n", saved["n"] + 1), root_cfg=cfg)
            root.update_idletasks()
            return fn(d, cfg, saved)
        finally:
            root.destroy()

    # ══ 1. Mind a harom kapu megjelenik ═══════════════════════════════════
    check("mind a harom kapunak van vezerloje",
          with_dialog(lambda d, c, s: set(d._gate_vars) == set(g.KEYS)))

    # ══ 2. A valtoztatas a VALODI configba megy ═══════════════════════════
    def set_market_reduce(d, cfg, saved):
        d._gate_vars[g.MARKET].set(g.EFFECT_LABEL["reduce"])
        d._on_gate_change(g.MARKET)
        return cfg, saved

    cfg, saved = with_dialog(set_market_reduce)
    check("a felulriras a pairs.<SYM>.gates ala kerul",
          cfg["pairs"]["GOLD"]["gates"]["market"]["wpr_sma"] == "reduce",
          str(cfg["pairs"]["GOLD"].get("gates")))
    check("...es a mentes MEGTORTENT (nem var a Mentes gombra)", saved["n"] >= 1)
    check("a feloldas is az uj erteket adja",
          g.effect_for(cfg, "GOLD", "wpr_sma", g.MARKET) == "reduce")
    check("a MASIK strategiat NEM erinti",
          g.effect_for(cfg, "GOLD", "ml_ai", g.MARKET) == "none")

    # ══ 3. Visszaallitas orokoltre — a kulcs ELTUNIK ══════════════════════
    # Ha csak "none"-ra allitanank, az FELULIRAS lenne (a felsobb szint valtozasat
    # tobbe nem kovetne). A visszavonasnak tenylegesen torolnie kell.
    def set_then_inherit(d, cfg, saved):
        d._gate_vars[g.MARKET].set(g.EFFECT_LABEL["reduce"])
        d._on_gate_change(g.MARKET)
        d._gate_vars[g.MARKET].set(d._gate_choices(g.MARKET)[0])   # "Örökölt (…)"
        d._on_gate_change(g.MARKET)
        return cfg

    cfg2 = with_dialog(set_then_inherit)
    check("orokoltre visszaallitva a par-szintu kulcs ELTUNIK",
          "gates" not in cfg2["pairs"]["GOLD"],
          str(cfg2["pairs"]["GOLD"].get("gates")))
    check("...es a forras ujra 'orokolt'",
          g.effect_with_source(cfg2, "GOLD", "wpr_sma", g.MARKET)[1] != g.SRC_PAIR)

    # ══ 4. Az "Orokolt (…)" felirat KIIRJA, mit kapnal vissza ═════════════
    def choices(d, cfg, saved):
        return d._gate_choices(g.TF_ALIGN), d._gate_choices(g.MARKET)

    tf_ch, mk_ch = with_dialog(choices)
    check("az orokolt tetel a tenyleges orokolt erteket mutatja (tf_align: block)",
          tf_ch[0] == f'Örökölt ({g.EFFECT_LABEL["block"]})', tf_ch[0])
    check("...a piacnal a beepitett 'Ki'",
          mk_ch[0] == f'Örökölt ({g.EFFECT_LABEL["none"]})', mk_ch[0])
    check("mind a harom hatas valaszthato",
          all(g.EFFECT_LABEL[e] in tf_ch for e in g.EFFECTS))
    check("a 'csak jelzes' NEM szerepel a valaszthatok kozt",
          not any("jelz" in t.lower() for t in tf_ch))

    # ══ 5. A masik strategia ablaka a SAJAT ertekere all ══════════════════
    def ml_default(d, cfg, saved):
        return d._gate_vars[g.TF_ALIGN].get()

    _ml = with_dialog(ml_default, "ml_ai")
    check("az ml_ai ablakaban a tf_align orokolt 'Ki' (nem a wpr_sma 'block'-ja)",
          _ml == f'Örökölt ({g.EFFECT_LABEL["none"]})', _ml)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
