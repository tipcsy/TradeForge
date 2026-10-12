"""A `K.Össz.` cella összesítő ablaka (`dashboard/gate_summary.py`).

Tibi (2026-10-12): a K.Össz.-re kattintva eddig semmi nem történt; az
instrumentum összes kapuját akarja látni — melyik él, melyik gátol / szabad —,
és stratégiánként be-/kikapcsolni.

⚠ A valódi config.json-t nem olvassa és nem írja.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import gates as G                                      # noqa: E402
from dashboard import gate_summary as GS                         # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


CFG = {"dashboard": {"gate_order": ["spread", "market", "momentum"]},
       "pairs": {"GOLD": {"strategies": ["wpr_sma", "csilla"],
                          "gates": {"market": {"wpr_sma": "block"},
                                    "momentum": {"wpr_sma": {"effect": "block",
                                                             "mode": "direction"}}}}}}
CTX = {"signal": "BUY", "market_name": "regime", "market_label": "Érdektelen",
       "market_state": "dead"}

R = {r["key"]: r for r in GS.rows(CFG, "GOLD", CTX, ["wpr_sma", "csilla"])}
check("minden regisztrált kapu kap sort", set(R) == set(G.KEYS), sorted(R))
check("a Beállításokban bekapcsolt kapu: enabled", R["market"]["enabled"])
check("...a ki nem kapcsolt (gate_order-ből hiányzó): NEM enabled",
      not R["volatility"]["enabled"] and not R["cost"]["enabled"])
check("kikapcsolt kapu stratégia-hatása: none + master_off forrás",
      R["volatility"]["per"]["wpr_sma"]["effect"] == G.EFFECT_NONE
      and R["volatility"]["per"]["wpr_sma"]["source"] == G.SRC_MASTER_OFF)
check("pár-szintű felülírás jelölve", R["market"]["per"]["wpr_sma"]["override"]
      and not R["market"]["per"]["csilla"]["override"])
check("a mért állapot a kapuét mutatja (kikapcsolt kapu: OFF)",
      R["volatility"]["state"] == G.OFF)

# ── mentés ────────────────────────────────────────────────────────────────
import copy                                                      # noqa: E402
c = copy.deepcopy(CFG)
ok = GS.apply_effects(c, "GOLD", {("market", "csilla"): G.EFFECT_REDUCE,
                                  ("market", "wpr_sma"): GS.INHERIT,
                                  ("momentum", "wpr_sma"): G.EFFECT_NONE})
gg = c["pairs"]["GOLD"]["gates"]
check("változás → True", ok)
check("új hatás beírva", gg["market"]["csilla"] == "reduce")
check("Örökölt → a pár-szintű felülírás TÖRLŐDIK", "wpr_sma" not in gg["market"])
check("⚠ a Lendület MÓDJA megmarad a hatás-váltáskor",
      gg["momentum"]["wpr_sma"] == {"effect": "none", "mode": "direction"},
      gg["momentum"]["wpr_sma"])
check("ugyanaz még egyszer → nincs változás",
      GS.apply_effects(c, "GOLD", {("market", "csilla"): G.EFFECT_REDUCE}) is False)
c2 = copy.deepcopy(CFG)
GS.apply_effects(c2, "GOLD", {("market", "wpr_sma"): GS.INHERIT,
                              ("momentum", "wpr_sma"): GS.INHERIT})
check("kiürült kapu-blokk → a `gates` kulcs is eltűnik a párról",
      "gates" not in c2["pairs"]["GOLD"], c2["pairs"]["GOLD"])

# ── a cella kattintható ─────────────────────────────────────────────────
from dashboard import canvas_cells as CC                         # noqa: E402
_hivas = []
cell = CC.cells_for({"symbol": "GOLD", "digits": 2,
                     "gates": {"badge": "⛔1", "on_badge": lambda: _hivas.append(1)}},
                    {})["badge"]
check("a K.Össz. cellának van kattintása", callable(cell.on_click))
cell.on_click()
check("...és az az összesítőt hívja", _hivas == [1])

# ── az ablak felépül (ha van Tk) ─────────────────────────────────────────
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    _TK = True
except Exception as _e:                                          # noqa: BLE001
    _TK = False
    print(f"KIHAGYVA: nincs tkinter ({_e})")
if _TK:
    try:
        d = GS.GateSummaryDialog(root, copy.deepcopy(CFG), "GOLD", ["wpr_sma", "csilla"],
                                 ctx=CTX)
        check("az ablak felépül", d.top.winfo_exists())
        check("csak a BEKAPCSOLT kapukra van választó (3 kapu × 2 stratégia)",
              len(d._vars) == 6, len(d._vars))
        check("változtatás nélkül nincs mit menteni", d._changes() == {})
        sv, cimkek, _ = d._vars[("market", "csilla")]
        sv.set(G.EFFECT_LABEL[G.EFFECT_BLOCK])
        check("egy választás → egy változás",
              d._changes() == {("market", "csilla"): G.EFFECT_BLOCK})
        d.top.destroy()
    finally:
        root.destroy()

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
