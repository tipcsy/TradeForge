"""
VOLATILITAS oszlop — az utolso blokkolo ok, ami eddig sehol nem latszott.

2026-08-08-ig minden blokkolo ok LATHATO kapu volt (Spread, Egyutt, Piac,
Lendulet, Koltseg) — a volatilitas-szuro viszont a strategia `bt_entry`-jeben
rejtozott. A BTCUSD hetekig nemam nem kereskedett, mert az ATR a kalibralt sav
ala csuszott (0,51x): 26 jelbol mind a 26 elbukott, a chart ures maradt, es
semmi nem arulta el, miert.

⚠ AZ OSZLOP MUTAT, NEM DONT. A szures helye valtozatlan. Ha ez a kapu allithato
hatast kapna, az vagy DUPLAN szurne, vagy `none`-ra allitva azt igerne, hogy
kikapcsoltad a szurest — a neman hatastalan beallitas pont az, amit ez a projekt
a legrosszabbnak tart. A teszt ezt a hatarvonalat orzi.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import core.applog as _applog
_applog.harden_console()

from core import gates as g                      # noqa: E402
from core import gate_layout as gl               # noqa: E402
from core import gate_params as gp               # noqa: E402
from core import config_check as cc              # noqa: E402
from dashboard import row_source as rs           # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


class DS:
    """A dashboard-allapot duck-typed masa (mint a tobbi row_source teszt)."""
    def __init__(self, atr=None, base=None):
        self.atr_price = atr
        self.atr_baseline = base
        self.spread_pts = None
        self.strategy_cells = {}
        self.market_state_label = ""


PRM = {"atr_min_pct": 0.9, "atr_max_pct": 3.2, "atr_avg_ref": 272.75}
PC = {"point_size": 0.01}

# ---------------------------------------------------------------------------
print("== VALODI KAPU (v3.27.0): a hatasa DONT ==")
# ⚠ v3.27.0 elott ez a kapu CSAK KIJELZES volt: a `decide` atugorta, a szures
# pedig a strategia `bt_entry`-jeben futott. A felhasznalo kifogasa ez volt:
# "van egy kapunk, ami nem szur, csak mutat — annak meg mi ertelme van?"
# Mostantol a kapu dont, es a `none` TENYLEG azt jelenti, hogy nincs szures.
check("a volatilitas kapu regisztralva van", g.VOLATILITY in g.KEYS)
check("...es `block`-kal indul (a v3.27.0 ELOTTI viselkedes megorzese)",
      g.default_effect_of(g.VOLATILITY) == g.EFFECT_BLOCK,
      g.default_effect_of(g.VOLATILITY))

dec = g.decide({g.VOLATILITY: True, g.SPREAD: True},
               {g.VOLATILITY: g.EFFECT_BLOCK, g.SPREAD: g.EFFECT_BLOCK})
check("a decide BLOKKOL, ha a meres bukik", g.VOLATILITY in dec["blocked"],
      str(dec["blocked"]))
check("kockazatcsokkentesre is hat",
      g.decide({g.VOLATILITY: True},
               {g.VOLATILITY: g.EFFECT_REDUCE})["risk_factor"] < 1.0)
check("`none` hatasnal NEM szol bele",
      not g.decide({g.VOLATILITY: True},
                   {g.VOLATILITY: g.EFFECT_NONE})["blocked"])

# PARAMETER-VEZERELT: az `exec_gates=False` NEM kapcsolja ki (a kuszobeit a
# strategia soport parameterei adjak — kulonben a sopres hatastalan parametert
# merne).
_eff_off = g.effects_for({}, "X", "wpr_sma", exec_gates=False)
check("exec_gates=False mellett is el", _eff_off[g.VOLATILITY] == g.EFFECT_BLOCK,
      str(_eff_off))
check("...de a tobbi kapu kimarad",
      all(_eff_off[k] == g.EFFECT_NONE for k in g.KEYS if k != g.VOLATILITY),
      str(_eff_off))

# ...es a config-ellenorzes SZOL, ha a kaput a Beallitasokban kikapcsoltak,
# holott van mit szurni: a v3.27.0 elotti configokban a `gate_order`-bol
# kivenni MEGJELENITESI dontes volt, most viszont a szurest is leveszi.
cfg_off = {"dashboard": {"gate_order": ["spread"]},
           "pairs": {"X": {"point_size": 0.01, "pv1_point": 1.0,
                           "commission_per_lot": 0, "swap_long_per_lot": 0,
                           "swap_short_per_lot": 0}}}
fs = [f for f in cc.check(cfg_off) if f["code"] == "volatility_gate_off"]
check("a config-ellenorzes jelzi a nema kikapcsolast", len(fs) == 1, f"{len(fs)} lelet")
if fs:
    check("...es megnevezi a kuszoboket",
          "atr_min_pct" in fs[0]["message"], fs[0]["message"][:60])
cfg_on = {"dashboard": {"gate_order": ["spread", "volatility"]},
          "pairs": cfg_off["pairs"]}
check("bekapcsolt kapunal nincs lelet",
      not [f for f in cc.check(cfg_on) if f["code"] == "volatility_gate_off"])

# ---------------------------------------------------------------------------
print("== A cella: arany + blokkolo allapot ==")
ctx_out = g.ctx_from_state(DS(140.19, 272.75), PRM, PC)
cell = rs._volatility_cell(ctx_out)
# ⚠ Az ARANY a lenyeg; a savon KIVULI erteknel a cella az IRANYT is kiirja
# ("0,51×↓" = a padlo alatt). A puszta arany onmagaban nem arulja el, hogy az
# sok vagy keves — ahhoz tudni kellene a savot.
check("a BTCUSD-eset 0.51x-et mutat", cell["text"].startswith("0.51×"), cell["text"])
check("...es az IRANYT is (a padlo alatt)", cell["text"].endswith("↓"), cell["text"])
check("...es BLOKKOLONAK jelzi", cell["blocking"] is True)
check("...a rendezheto ertek is megvan", abs(cell["value"] - 0.514) < 0.01,
      str(cell["value"]))

cell_ok = rs._volatility_cell(g.ctx_from_state(DS(300.0, 272.75), PRM, PC))
check("savon belul NEM blokkol", cell_ok["blocking"] is False, cell_ok["text"])
cell_hi = rs._volatility_cell(g.ctx_from_state(DS(1000.0, 272.75), PRM, PC))
check("tul kaotikus is blokkol", cell_hi["blocking"] is True, cell_hi["text"])

for tag, ds in (("nincs ATR", DS(None, 272.75)), ("nincs merce", DS(140.0, None)),
                ("egyik sincs", DS(None, None))):
    c = rs._volatility_cell(g.ctx_from_state(ds, PRM, PC))
    check(f"{tag} -> '—', nem blokkol", c["text"] == "—" and not c["blocking"])

# A kattintas atmegy
c_click = rs._volatility_cell(g.ctx_from_state(DS(140.19, 272.75), PRM, PC),
                              on_click=lambda s: s, symbol="BTCUSD")
check("a cella kattinthato", callable(c_click.get("on_click")))

# ---------------------------------------------------------------------------
print("== A kapu-ablak MEGMONDJA az okot ==")
rows = dict(gp.measured_rows(g.VOLATILITY, ctx_out))
for k in ("Mostani ATR", "Arány", "Engedett sáv", "Állapot", "A mérce fajtája"):
    check(f"a(z) {k!r} sor megjelenik", k in rows, str(list(rows))[:70])
check("az Allapot megmondja, hogy TUL CSENDES",
      "csendes" in rows.get("Állapot", ""), rows.get("Állapot", "")[:60])
check("a merce fajtaja: befagyasztott", "befagyasztott" in rows.get("A mérce fajtája", ""))

rows_roll = dict(gp.measured_rows(
    g.VOLATILITY, g.ctx_from_state(DS(140.19, 140.0),
                                   {**PRM, "atr_baseline_bars": 96 * 90}, PC)))
check("gordulo mercenel ezt irja ki",
      "gördülő" in rows_roll.get("A mérce fajtája", ""),
      rows_roll.get("A mérce fajtája", ""))
check("...es akkor RENDBEN az allapot", "RENDBEN" in rows_roll.get("Állapot", ""),
      rows_roll.get("Állapot", "")[:40])

# ---------------------------------------------------------------------------
print("== Beilleszkedik a kapu-vazba ==")
check("az oszlop-sorrendben ott van", "volatility" in gl.enabled_columns({}),
      str(gl.enabled_columns({})))
check("ki-be kapcsolhato, mint a tobbi",
      "volatility" not in gl.enabled_columns(
          {"dashboard": {"gate_order": ["spread"]}}))
check("van leirasa", (g.doc_text(g.VOLATILITY) or "").strip() != "" and
      "Valódi kapu" in g.doc_text(g.VOLATILITY),
      g.doc_text(g.VOLATILITY)[:60])
check("a leiras a valodi meressel indokol", "0,51" in g.doc_text(g.VOLATILITY))

from dashboard import live_row as lr             # noqa: E402
# A fejlec mondja meg, MIHEZ kepest merunk: az „×" jelzi, hogy ez ARANY (a
# kalibralt mercehez), nem abszolut ATR.
check("van fejlec-szovege", (lr.header_text("volatility") or "").startswith("Volat."),
      lr.header_text("volatility"))
check("van szelesseg-mintaja", "volatility" in lr._SAMPLE)

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
