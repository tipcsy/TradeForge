"""A KOZOS kapu-beallito ablak — core/gate_params.py + dashboard/gate_dialog.py.

Amit oriz:
  • A Spread cellara kattintva a SPREAD KAPU harom szama nyilik, nem a teljes
    wpr_sma-parameterlista (ez volt a panasz).
  • Az ertekek ellenorzese a TISZTA retegben tortenik, es hiba eseten NEM MENT
    — a reszleges mentes a legrosszabb: a fele beallitas elmenne, a masik nem.
  • A mert blokk ugyanabbol a ctx-bol dolgozik, amibol a kapu DONT — nem kulon
    szamolt "kb. ugyanaz".
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# A mert blokk NYILAKAT ir ki (M1 ↑ M5 ↑ M15 ↓), a Windows-konzol pedig cp1250:
# enelkul a `print` szallna el, nem a teszt. (A `run_all.py` maga is ezt hivja.)
from core import applog
applog.harden_console()

from core import gate_params as gp
from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. A kapuk sajat szamai ════════════════════════════════════════════════
sp = {s.key: s for s in gp.specs_for(g.SPREAD)}
check("a Spread kapunak SAJAT szamai vannak (nem a strategiae)",
      set(sp) == {"max_spread_atr_ratio", "min_spread_mult", "atr_period"},
      str(sorted(sp)))
check("a spread ATR-hanyada a kapu parametere, alap 0.20",
      sp["max_spread_atr_ratio"].default == 0.20)
check("minden regisztralt kapunak van leiroja vagy tudatosan ures",
      all(isinstance(gp.specs_for(k), tuple) for k in g.KEYS))


# ══ 2. Ellenorzes — ami elgepeles, az ne jusson a motorig ══════════════════
v, err = gp.parse(sp["max_spread_atr_ratio"], "0,35")
check("magyar tizedesvesszo is elfogadott (0,35 -> 0.35)", v == 0.35 and not err,
      f"{v!r} {err!r}")

v, err = gp.parse(sp["max_spread_atr_ratio"], "20")
check("a tartomanyon KIVULI ertek hibat ad (20 > 5.0)", bool(err), str(err))

v, err = gp.parse(sp["atr_period"], "nem szam")
check("a nem-szam hibat ad", bool(err), str(err))

v, err = gp.parse(sp["atr_period"], "")
check("az ures mezo hibat ad", bool(err), str(err))

v, err = gp.parse(sp["atr_period"], "14")
check("az ervenyes egesz atmegy", v == 14 and not err)

vals, errs = gp.parse_all(g.SPREAD, {"max_spread_atr_ratio": "0.25",
                                     "min_spread_mult": "2",
                                     "atr_period": "-3"})
check("parse_all osszegyujti a hibakat, a jokat viszont ertelmezi",
      len(errs) == 1 and vals["max_spread_atr_ratio"] == 0.25, f"{vals} {errs}")

# TF-egyuttallas: 2..6 idosik — egyetlen idosik nem "egyuttallas"
check("egyetlen idosik hibat ad",
      bool(gp.extra_errors(g.TF_ALIGN, {"timeframes": [15]})))
check("harom idosik rendben", not gp.extra_errors(g.TF_ALIGN,
                                                  {"timeframes": [1, 5, 15]}))
check("hetnel tobb idosik hibat ad",
      bool(gp.extra_errors(g.TF_ALIGN,
                           {"timeframes": [1, 5, 15, 30, 60, 240, 1440]})))


# ══ 3. A MERT blokk a kapu SAJAT ctx-ebol jon ══════════════════════════════
class _DS:
    spread_pts = 180
    atr_price = 6.56
    tf_align_signs = [1, 1, -1]
    tf_align_labels = ["M1", "M5", "M15"]
    tf_align_dir = None
    market_strategy = "regime"
    market_state_label = "Oldalazas"


ctx = g.ctx_from_state(_DS(), {"max_spread_atr_ratio": 0.20, "atr_period": 14},
                       {"point_size": 0.01, "backtest_spread_points": 45})
rows = dict(gp.measured_rows(g.SPREAD, ctx))
check("a mert blokk a JELENLEGI spreadet mutatja", "180" in rows["Jelenlegi spread"],
      rows.get("Jelenlegi spread"))
check("...es a SZAMITOTT hatart (ugyanaz, amivel a kapu dont)",
      rows.get("Számított határ") == f"{ctx['max_spread_points']:.0f} pont",
      rows.get("Számított határ"))
check("...es az ATR-t, amibol a hatar jott", "ATR (fő időkeret)" in rows)
check("a normal spread is latszik (a padlo ehhez mer)",
      "45" in rows.get("Instrumentum normál spreadje", ""))

al = dict(gp.measured_rows(g.TF_ALIGN, ctx))
check("az Egyutt mert blokkja az idosik-nyilakat mutatja",
      "M1 ↑" in al["Idősík-irányok"] and "M15 ↓" in al["Idősík-irányok"],
      al.get("Idősík-irányok"))
check("...es hogy nincs egyuttallas", al["Együttállás"] == "nincs")

mk = dict(gp.measured_rows(g.MARKET, ctx))
check("a Piac mert blokkja az osztalyozot es a besorolast mutatja",
      mk["Osztályozó"] == "regime" and mk["Jelenlegi besorolás"] == "Oldalazas",
      str(mk))


# ══ 4. Az ablak — valodi Tk-val, ha van ════════════════════════════════════
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA (Tk resz): {type(e).__name__}: {e}")

if TK_OK:
    from dashboard import gate_dialog as gd
    from dashboard import theme as _theme

    root = tk.Tk()
    root.withdraw()
    _theme.fonts()
    try:
        cfg = {"pairs": {"GOLD": {"point_size": 0.01,
                                  "backtest_spread_points": 45,
                                  "tf_align": {"enabled": True,
                                               "timeframes": [1, 5, 15],
                                               "sma_period": 50}},
                         "Ger40": {"point_size": 0.1}},
               "execution": {"max_spread_atr_ratio": 0.20, "min_spread_mult": 1.5,
                             "atr_period": 14}}

        # A spread tarolo FAJLBA ir — a teszt ne piszkitsa a data/ mappat.
        written = []
        gd.register_store(
            g.SPREAD,
            lambda c, s: {"max_spread_atr_ratio": 0.20, "min_spread_mult": 1.5,
                          "atr_period": 14},
            lambda c, s, vals, syms: written.append((sorted(syms), dict(vals))))

        # ── Spread ablak ──────────────────────────────────────────────────
        d = gd.GateDialog(root, cfg, "GOLD", g.SPREAD, ["wpr_sma", "ml_ai"],
                          ctx=ctx, all_symbols=["GOLD", "Ger40"])
        check("a Spread ablak a harom kapu-szamot tolti be",
              set(d.raw_values()) == {"max_spread_atr_ratio", "min_spread_mult",
                                      "atr_period"}, str(d.raw_values()))
        check("...es minden strategiara van hatas-valaszto",
              set(d._eff_vars) == {"wpr_sma", "ml_ai"}, str(set(d._eff_vars)))

        # ERVENYTELEN ertek -> NEM ment, es megmondja, mit javits
        d._vars["max_spread_atr_ratio"].set("99")
        d._save()
        check("ervenytelen erteknel NEM ment", not written, str(written))
        check("...es kiirja a hibat", "javítsd" in d.lbl_err.cget("text"),
              d.lbl_err.cget("text"))
        check("...az ablak NYITVA marad (nem vesznek el a beirt ertekek)",
              bool(d.top.winfo_exists()))

        # Ervenyes ertek -> ment, es a hatas a configba kerul
        d._vars["max_spread_atr_ratio"].set("0,30")
        d._eff_vars["ml_ai"].set(g.EFFECT_LABEL[g.EFFECT_REDUCE])
        d._save()
        check("ervenyes erteknel ment (a magyar tizedesvesszot is ertve)",
              written and written[0][1]["max_spread_atr_ratio"] == 0.30,
              str(written))
        check("alapbol CSAK az adott instrumentumra ment",
              written[0][0] == ["GOLD"], str(written[0][0]))
        check("a per-strategia hatas a config.json-ba kerul",
              g.effect_for(cfg, "GOLD", "ml_ai", g.SPREAD) == g.EFFECT_REDUCE,
              json.dumps(cfg["pairs"]["GOLD"].get("gates"), ensure_ascii=False))
        check("...a masik strategiae erintetlen marad (blokkol, mint eddig)",
              g.effect_for(cfg, "GOLD", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)
        # ...ES NEM is irodott ki: az erintetlen legordulo „Orokolt (…)"-on all,
        # a mentes pedig csak az ELTERES-t rogziti.
        check("...az erintetlen strategia NEM kap felulirast a configban",
              "wpr_sma" not in ((cfg["pairs"]["GOLD"].get("gates") or {})
                                .get(g.SPREAD) or {}),
              json.dumps(cfg["pairs"]["GOLD"].get("gates"), ensure_ascii=False))

        # ══ A LEGFONTOSABB VEDELEM ═══════════════════════════════════════
        # Az „Egyutt" hatasa a REGI `tf_align.gate` listabol is orokolheto. Ha a
        # mentes minden strategiara kiirna az eppen ervenyes erteket, egy puszta
        # ablak-megnyitas + Mentes NEMAN `none`-ra irna — vagyis KIKAPCSOLNA a
        # kaput, ugy hogy a felhasznalo semmit nem allitott.
        cfg_legacy = {"pairs": {"UsaTec": {"point_size": 0.1}},
                      "tf_align": {"gate": ["wpr_sma"]}}
        check("kiindulas: a legacy lista szerint az Egyutt BLOKKOL",
              g.effect_for(cfg_legacy, "UsaTec", "wpr_sma", g.TF_ALIGN)
              == g.EFFECT_BLOCK)
        dl = gd.GateDialog(root, cfg_legacy, "UsaTec", g.TF_ALIGN, ["wpr_sma"],
                           ctx={}, all_symbols=["UsaTec"])
        dl._save()                       # a felhasznalo semmit nem allitott
        check("puszta Mentes NEM kapcsolja ki az orokolt kapu-hatast",
              g.effect_for(cfg_legacy, "UsaTec", "wpr_sma", g.TF_ALIGN)
              == g.EFFECT_BLOCK,
              json.dumps(cfg_legacy["pairs"]["UsaTec"], ensure_ascii=False))

        # ── „Az osszes instrumentumra" ────────────────────────────────────
        written.clear()
        d2 = gd.GateDialog(root, cfg, "GOLD", g.SPREAD, ["wpr_sma"], ctx=ctx,
                           all_symbols=["GOLD", "Ger40"])
        d2._all_var.set(True)
        d2._save()
        check("az „osszes instrumentumra” pipa MINDEN parra ment",
              written and written[0][0] == ["GOLD", "Ger40"], str(written))
        check("...es a hatas is atmegy a masik parra",
              g.effect_for(cfg, "Ger40", "wpr_sma", g.SPREAD) == g.EFFECT_BLOCK)

        # ── Egyutt (TF-egyuttallas) ───────────────────────────────────────
        d3 = gd.GateDialog(root, cfg, "GOLD", g.TF_ALIGN, ["wpr_sma"], ctx=ctx,
                           all_symbols=["GOLD"])
        rv = d3.raw_values()
        check("az Egyutt ablak a mentett idosikokat tolti be",
              sorted(rv["timeframes"]) == [1, 5, 15], str(rv.get("timeframes")))
        check("...es az SMA-periodust", str(rv["sma_period"]) == "50",
              str(rv.get("sma_period")))
        # Egyetlen idosik -> nem ment
        for mins, bv in d3._vars["timeframes"].items():
            bv.set(mins == 15)
        d3._save()
        check("egyetlen idosikkal NEM ment",
              sorted(((cfg["pairs"]["GOLD"].get("tf_align") or {})
                      .get("timeframes") or [])) == [1, 5, 15],
              str(cfg["pairs"]["GOLD"].get("tf_align")))
        # Ket idosik -> ment
        for mins, bv in d3._vars["timeframes"].items():
            bv.set(mins in (5, 15))
        d3._vars["sma_period"].set("80")
        d3._save()
        _ta = cfg["pairs"]["GOLD"]["tf_align"]
        check("ket idosikkal ment, es az SMA is frissul",
              sorted(_ta["timeframes"]) == [5, 15] and _ta["sma_period"] == 80,
              str(_ta))

        # ── Piac ──────────────────────────────────────────────────────────
        d4 = gd.GateDialog(root, cfg, "GOLD", g.MARKET, ["wpr_sma"], ctx=ctx,
                           all_symbols=["GOLD"])
        adv = d4._vars["adverse"]
        for cat, bv in adv.items():
            bv.set(cat in ("dead",))
        d4._save()
        check("a Piac ablak a „kedvezotlen” listat menti",
              g.market_adverse(cfg, "GOLD") == {"dead"},
              str(g.market_adverse(cfg, "GOLD")))

        # Az ALAPERTELMEZESSEL egyezo lista NE keruljon a configba (a config csak
        # az ELTERES-t rogzitse — kulonben egy jovobeli alapertek-valtozas neman
        # hatastalan maradna ezen a paron).
        d5 = gd.GateDialog(root, cfg, "GOLD", g.MARKET, ["wpr_sma"], ctx=ctx,
                           all_symbols=["GOLD"])
        for cat, bv in d5._vars["adverse"].items():
            bv.set(cat in g.MARKET_ADVERSE_DEFAULT)
        d5._save()
        check("az alapertelmezessel egyezo lista NEM irodik ki a configba",
              "adverse" not in ((cfg["pairs"]["GOLD"].get("gates") or {})
                                .get(g.MARKET) or {}),
              json.dumps(cfg["pairs"]["GOLD"].get("gates"), ensure_ascii=False))
        # ── Lendulet (a negyedik kapu — a kozos vazat "ingyen" kapja) ─────
        dm = gd.GateDialog(root, cfg, "GOLD", g.MOMENTUM, ["wpr_sma", "ml_ai"],
                           ctx={"momentum": 1.2, "momentum_idle_threshold": 0.35},
                           all_symbols=["GOLD"])
        check("a Lendulet ablak a meresi parametereket tolti be",
              {"basis", "idle_threshold", "sma_fast", "sma_mid", "sma_slow",
               "timeframes", "tf_sma", "vol_window", "timeframe"}
              == set(dm.raw_values()), str(sorted(dm.raw_values())))
        check("...es a hatas MELLE mod-valaszto is van (csak itt)",
              set(dm._mode_vars) == {"wpr_sma", "ml_ai"} and not d._mode_vars,
              str(set(dm._mode_vars)))
        # A harom SMA-nak novekvonek kell lennie
        dm._vars["sma_fast"].set("200")
        dm._save()
        check("a rossz sorrendu SMA-k (gyors > lassu) NEM mentodnek",
              "gyors < k" in dm.lbl_err.cget("text"), dm.lbl_err.cget("text"))
        dm._vars["sma_fast"].set("10")
        dm._eff_vars["wpr_sma"].set(g.EFFECT_LABEL[g.EFFECT_BLOCK])
        dm._mode_vars["wpr_sma"].set(g.MOM_MODE_LABEL[g.MOM_DIR])
        dm._vars["idle_threshold"].set("0,5")
        dm._save()
        check("a Lendulet hatasa ES modja is a configba kerul",
              g.effect_for(cfg, "GOLD", "wpr_sma", g.MOMENTUM) == g.EFFECT_BLOCK
              and g.mode_for(cfg, "GOLD", "wpr_sma") == g.MOM_DIR,
              json.dumps(cfg["pairs"]["GOLD"]["gates"].get(g.MOMENTUM),
                         ensure_ascii=False))
        _mc = g.momentum_config(cfg["pairs"]["GOLD"], cfg)
        check("...es a meresi parameterek is (a magyar tizedesvesszot ertve)",
              _mc["idle_threshold"] == 0.5 and _mc["sma_fast"] == 10, str(_mc))
        check("az alapertekkel egyezo mezo NEM keszit config-bejegyzest",
              "vol_window" not in cfg["pairs"]["GOLD"]["gates"][g.MOMENTUM],
              json.dumps(cfg["pairs"]["GOLD"]["gates"][g.MOMENTUM],
                         ensure_ascii=False))

    finally:
        root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
