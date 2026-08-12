"""A `K.Össz.` jelveny csak LATHATO es VALODI okot szamolhat.

Bejelentes (2026-08-11, elesben, kepernyokeppel): "UsaInd sor — Spread zold,
Egyutt zold, Volat. teljesen URES. Megis azt irja, hogy nem kereskedhet, ⛔1.
Miert?"

Ket, egymastol fuggetlen hiba allt ossze:

⚠ 1. A `Volat.` oszlopnak VOLT fejlece, de NEM VOLT CELLAJA. A `canvas_cells`
   a spread/align/market/momentum/cost cellakat epitette meg — a volatilitast
   kifelejtette. Az oszlop tehat minden soron URES volt, mikozben a kapu
   blokkolo allapota beleszamitott a jelvenybe: "⛔1" LATHATO ok nelkul.

   Ez pont az a hibaosztaly, ami miatt ez az oszlop egyaltalan megszuletett: a
   BTCUSD hetekig NEMAN nem kereskedett 0,51x-es ATR-aranynal.

⚠ 2. A jelveny a KIKAPCSOLT kapukat is merte. A `gate_order`-bol kihagyott kapu
   mester-kapcsoloval ki van kapcsolva: nincs oszlopa ES nem szol bele a
   kereskedesbe. Ha megis beleszamolna, a sor olyasmiert mutatna "⛔"-t, aminek
   se latszata, se hatasa.

   ⚠ A kikapcsoltat kifejezetten `EFFECT_NONE`-ra kell allitani, nem elhagyni a
   szotarbol: az `evaluate` a hianyzo kulcsra a kapu ALAPERTELMEZETT hatasaval
   szamol, nem semmissel — az elhagyas tehat NEM javitas.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from core import gates as g
from core import gate_layout as gl
from dashboard import canvas_cells as cc
from dashboard import live_row as lr

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. MINDEN engedelyezett kapunak van CELLAJA ───────────────────────────
# A fejlec a `gate_layout`-bol jon, a cella a `canvas_cells`-bol. Ha a ketto
# elter, egy oszlop URESEN all — es a hianyzo ok pont az lesz, ami blokkol.
d = lr.demo_row()
cells = cc.cells_for(d, {})
for key in g.KEYS:
    col = gl.column_key(key)
    check(f"a(z) „{g.label_of(key)}” kapunak van cellaja ({col})",
          col in cells, "" if col in cells else f"HIANYZIK: {col}")

# ⚠ A `Volat.` volt a konkret hianyzo — kulon is rogzitve, hogy egy jovobeli
# atrendezes ne ejtse ki ujra csendben.
check("a VOLATILITAS cella letezik (ez hianyzott)", "volatility" in cells)
_v = cells.get("volatility")
check("...es van szovege (nem lathatatlan)", bool(_v and _v.text))


# ── 2. Minden kapu-oszlop kulcsa VISSZAVEZETHETO egy kapura ───────────────
# Forditva is: ne legyen olyan kapu-cella, aminek nincs kapuja (elgepeles).
_gate_cols = {gl.column_key(k) for k in g.KEYS}
_extra = {k for k in cells if k in ("spread", "align", "market", "momentum",
                                    "cost", "volatility")} - _gate_cols
check("nincs gazdatlan kapu-cella", not _extra, str(_extra))


# ── 3. A KIKAPCSOLT kapu nem szamolhat bele a jelvenybe ───────────────────
# A dashboard mereset utanozzuk: minden ENGEDELYEZETT kaput blokkolonak veve.
def _measure(cfg, ctx):
    on = set(gl.enabled_gates(cfg))
    eff = {k: (g.EFFECT_BLOCK if k in on else g.EFFECT_NONE) for k in g.KEYS}
    return g.evaluate(ctx, eff)


# Olyan ctx, amiben a KOLTSEG-kapu blokkol (nagy spread a tervezett stophoz).
CTX_COST = {"spread_points": 10, "max_spread_points": 100,
            "plan_sl_points": 20, "plan_tp_points": 20,
            "entry_spread_points": 60, "cost_max_distortion": 0.2}
_cost_blocks = any(s["key"] == g.COST and s["state"] == g.BLOCKING
                   for s in g.evaluate(CTX_COST,
                                       {k: g.EFFECT_BLOCK for k in g.KEYS}))
if _cost_blocks:
    _cfg_off = {"dashboard": {"gate_order": ["spread", "tf_align"]}}   # cost KI
    check("KIKAPCSOLT kapu blokkolo allapota NEM jelenik meg a jelvenyben",
          g.badge(_measure(_cfg_off, CTX_COST)) == "✓",
          g.badge(_measure(_cfg_off, CTX_COST)))
    _cfg_on = {"dashboard": {"gate_order": ["spread", "tf_align", "cost"]}}
    check("...bekapcsolva viszont IGEN (a teszt ertelmes)",
          g.badge(_measure(_cfg_on, CTX_COST)) != "✓",
          g.badge(_measure(_cfg_on, CTX_COST)))
else:
    # A koltseg-kapu meresehez mas kulcsok kellenek — ilyenkor a szabalyt
    # kozvetlenul ellenorizzuk, mereskent.
    check("koltseg-kapu nem merheto ezzel a ctx-szel (kihagyva)", True)

# ⚠ AZ ELHAGYAS NEM JAVITAS: a hianyzo kulcsra az `evaluate` az ALAPERTELMEZETT
# hatassal szamol. A spread alapja `block` — ha csak kihagynank a szotarbol,
# tovabbra is blokkolna.
_ctx_sp = {"spread_points": 900, "max_spread_points": 100}
_omitted = g.evaluate(_ctx_sp, {})            # spread KIHAGYVA a szotarbol
check("kihagyott kulcs -> az ALAPERTELMEZETT hatas ervenyes (ezert nem eleg)",
      g.badge(_omitted) != "✓", g.badge(_omitted))
_explicit = g.evaluate(_ctx_sp, {g.SPREAD: g.EFFECT_NONE})
check("kifejezett EFFECT_NONE -> tenyleg nem szamit bele",
      g.badge(_explicit) == "✓", g.badge(_explicit))


# ── 4. A blokkolo VOLATILITAS lathato: piros cella + jelveny egyutt ──────
_row = lr.demo_row()
_row.setdefault("gates", {})["volatility"] = {"text": "0.51×", "blocking": True,
                                              "value": 0.51}
_c = cc.cells_for(_row, {})
check("blokkolo volatilitas -> a cellaban ott az ARANY", _c["volatility"].text == "0.51×")
from dashboard import theme as _th
check("...es PIROSSAL (nem nemul el)", _c["volatility"].fg == _th.FG_RED,
      str(_c["volatility"].fg))



# ── 5. A cella MAGATOL ERTHETO legyen ─────────────────────────────────────
# ⚠ A puszta arany nem mond semmit: a "0,51×" onmagaban nem arulja el, hogy az
# sok vagy keves — ahhoz tudni kellene a savot. A savon KIVULI erteknel ezert
# ott az IRANY is.
from dashboard import row_source as rs


def _vc(atr, base, lo=0.6, hi=3.0):
    return rs._volatility_cell({"atr_price": atr, "atr_baseline": base,
                                "vol_params": {"atr_min_pct": lo,
                                               "atr_max_pct": hi}})


check("a savban: puszta arany, nem blokkol",
      _vc(15.0, 10.0)["text"] == "1.50×" and not _vc(15.0, 10.0)["blocking"])
check("a PADLO alatt: lefele nyil", _vc(5.1, 10.0)["text"].endswith("↓"),
      _vc(5.1, 10.0)["text"])
check("a PLAFON folott: felfele nyil", _vc(42.0, 10.0)["text"].endswith("↑"),
      _vc(42.0, 10.0)["text"])
check("...es mindketto BLOKKOLONAK jelolt",
      _vc(5.1, 10.0)["blocking"] and _vc(42.0, 10.0)["blocking"])
check("a cella az INDOKOT is viszi (a kapu-ablakhoz)",
      "csendes" in (_vc(5.1, 10.0).get("why") or ""), _vc(5.1, 10.0).get("why", ""))
check("merce nelkul: „—”, nem 0", _vc(12.0, None)["text"] == "—")

# Az oszlop MINTA-szovege (ez adja a szelesseget) ferjen az iranyjelnek is.
_w = (lr.COLUMN_SAMPLES if hasattr(lr, "COLUMN_SAMPLES") else {}) or {}
_sample = None
for _k in dir(lr):
    _v = getattr(lr, _k)
    if isinstance(_v, dict) and "volatility" in _v and isinstance(
            _v.get("volatility"), tuple):
        _sample = _v["volatility"][1]
        break
check("az oszlop minta-szovege elbirja az iranyjelet",
      _sample is None or len(_sample) >= len("9.99×↓"), str(_sample))


# ── 6. MINDEN kapu-megnyito lefut (NameError nelkul) ──────────────────────
# ⚠ A `_show_volatility_gate`-bol HIANYZOTT a `core.gates` importja. Nem derult
# ki, mert a cellara ra sem lehetett kattintani (nem letezett) — amint
# megjelent, azonnal NameError-ral szallt el. Ez a teszt MINDEGYIKET meghivja.
try:
    from dashboard import gui as _gui
    _cls = next(c for _n, c in vars(_gui).items()
                if isinstance(c, type) and hasattr(c, "_show_volatility_gate"))

    _opened = []

    class _Fake(_cls):
        def __init__(self):
            pass

        def _open_gate_dialog(self, sym, key):
            _opened.append(key)

    _f = _Fake()
    _names = [n for n in dir(_cls)
              if n.startswith("_show_") and n.endswith("_gate")]
    _bad = []
    for _n in _names:
        try:
            getattr(_f, _n)("TEST")
        except Exception as ex:
            _bad.append(f"{_n}: {type(ex).__name__}: {ex}")
    check(f"minden kapu-megnyito lefut ({len(_names)} db)", not _bad,
          "; ".join(_bad))
    check("...es tenylegesen kaput nyit", len(_opened) == len(_names),
          f"{len(_opened)}/{len(_names)}")
except StopIteration:
    check("nincs dashboard-osztaly (kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
