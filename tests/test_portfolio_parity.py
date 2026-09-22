"""PORTFÓLIÓ ↔ EGYPÁROS PARITÁS — ugyanaz a pár, ugyanaz az időszak, két út.

⚠ MIÉRT (2026-09-22). A `run_pair` (egypáros backtest, a natív maggal) és a
`run_portfolio_backtest` (portfólió, saját ~670 soros Python-ciklus) a
pozíció-kezelés KÉT LEÍRÁSA. A projekt visszatérő hibaosztálya, hogy két leírás
némán szétcsúszik (`duplication-produced-its-own-bug`, `vacuous-parity-tests`);
itt ez egyszer már megtörtént (auto-risky, a shortok ingyen spreadje), és a
kettő paritását eddig EGYETLEN teszt sem mérte. A felhasználó döntése: a
portfólió-BT úgy viselkedjen, mint az élő rendszer — az egypáros backtest az él
modellje, tehát az egyelemű portfóliónak BITRE azt kell adnia.

MIT MÉR. Egy hangolt páron, egy rögzített időszakon, AZONOS beállításokkal
(params, rr, risky, kapuk, órák, slot, tőke):
  1. a kötések SZÁMA egyezik;
  2. a belépők (idő, irány) halmaza egyezik;
  3. a kilépések (idő, státusz) és a kötésenkénti P&L egyezik (1 centen belül);
  4. a végegyenleg egyezik.
Ami eltér, azt KIÍRJA (az első 5 különbséget), hogy a javítás célzott legyen.

⚠ ÉLES ADAT KELL: `data/m1`, `data/m15`, `data/optimized_params` és a valódi
`config.json` (a `requires_live_data.txt`-ben). A `PARITAS_PAR` / `PARITAS_TOL`
/ `PARITAS_IG` környezeti változóval más pár/időszak is mérhető.

Futtatás:  python tests/test_portfolio_parity.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import applog
applog.harden_console()

import logging
logging.getLogger().setLevel(logging.WARNING)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


SYM = os.environ.get("PARITAS_PAR", "Ger40")
STRAT = os.environ.get("PARITAS_STRAT", "wpr_sma")
FROM = os.environ.get("PARITAS_TOL", "2026-06-01")
TO = os.environ.get("PARITAS_IG", "2026-09-01")
BAL = 1000.0

from strategy.settings import load_config
from strategy import get_strategy_by_name
from trading import backtest as bt
from core import risky_mode, rr_state
from core.params_store import params_file, set_active_strategy, resolve_trade_hours
from core.execution_params import load_execution_params

cfg = load_config(ROOT / "config.json")
# Diagnosztika: `PARITAS_NOLIMIT=1` → a napi veszteség-limit MINDKÉT úton kikapcsolva.
# Az eltérések egy része a limit KÜLÖNBÖZŐ napokon való elérése (a halmozott
# kötések vesztesége miatt) — ezzel választható szét az ok és a következmény.
if os.environ.get("PARITAS_NOLIMIT"):
    cfg["trading"]["daily_loss_limit_usd"] = 1e9
    print("(napi limit KI — diagnosztika)")
strategy = get_strategy_by_name(STRAT)
set_active_strategy(STRAT)
pf = params_file(SYM, STRAT)
if not pf.exists():
    print(f"NINCS hangolt params: {pf} — a teszt nem mérhető ezen a páron")
    sys.exit(0)
data = json.load(open(pf, encoding="utf-8"))
params = {**data.get("params", {}), **load_execution_params(SYM, cfg)}
pair_cfg = cfg["pairs"][SYM]
trading_cfg = cfg["trading"]
risky_mode.load()
rr_state.load()
risky = risky_mode.is_risky(SYM)
rr_spec = rr_state.spec_for(SYM)                       # a per-pár preset — mint a portfólió „Auto"-ja
hours = resolve_trade_hours(SYM, STRAT, pair_cfg.get("trade_hours"))   # mint az él
allowed = set(hours) if hours else None
print(f"pár={SYM} strat={STRAT} {FROM}→{TO} risky={risky} preset={rr_spec.get('preset')} "
      f"órák={'mind' if allowed is None else sorted(allowed)} slots={trading_cfg['max_open_slots']}")

df15, df1 = bt.load_data(SYM)
if df15 is None:
    print("NINCS adat — a teszt nem mérhető")
    sys.exit(0)

# ── 1. egypáros út (a natív maggal, ha van) ───────────────────────────────
r1 = bt.run_pair(SYM, df15, df1, params, pair_cfg, trading_cfg, BAL,
                 test_start=FROM, test_end=TO, strategy=strategy,
                 allowed_hours=allowed, risky=risky, rr=rr_spec,
                 cfg=cfg, exec_gates=True)
t1 = list(r1.closed)

# ── 2. egyelemű portfólió ─────────────────────────────────────────────────
r2 = bt.run_portfolio_backtest(cfg, [SYM], FROM, TO, initial_balance=BAL,
                               rr=None, strategy_name=STRAT,
                               max_slots=trading_cfg["max_open_slots"],
                               build=False, exec_gates=True)
t2 = list(r2.get("trades", []))


def kulcs(t):
    return (str(t.open_time), t.direction)


def sor(t):
    return (f"{t.direction} {t.open_time} → {t.close_time} {t.status} "
            f"pnl={t.pnl_usd:+.2f} lot={t.lot}")


k1 = {kulcs(t): t for t in t1}
k2 = {kulcs(t): t for t in t2}
csak1 = sorted(set(k1) - set(k2))
csak2 = sorted(set(k2) - set(k1))
kozos = sorted(set(k1) & set(k2))

print(f"egypáros: {len(t1)} kötés, P&L {sum(t.pnl_usd for t in t1):+.2f}$ | "
      f"portfólió: {len(t2)} kötés, P&L {sum(t.pnl_usd for t in t2):+.2f}$ "
      f"(végegyenleg {r2.get('final_balance', 0):.2f})")
check("a kötések SZÁMA egyezik", len(t1) == len(t2), f"{len(t1)} vs {len(t2)}")
check("a BELÉPŐK (idő, irány) halmaza egyezik", not csak1 and not csak2,
      f"csak egypáros: {len(csak1)}, csak portfólió: {len(csak2)}")
# ⚠ HALMOZÁS: az egypáros út (és a natív mag) egy páron TÖBB egyidejű pozíciót
# enged (csak a slot-szám korlátoz), az élő motor NEM („egy szimbólumon egyszerre
# csak egy pozíció", live_trader). A portfólió az él szabályát követi. Ezért a
# csak-egypáros kötések közül azokat, amelyek nyitott pozíció MELLÉ nyíltak,
# külön számoljuk: ez nem a portfólió hibája, hanem az egypáros út eltérése.
_t1s = sorted(t1, key=lambda t: t.open_time)
_halmozott = {kulcs(a) for i, a in enumerate(_t1s)
              if any(b.close_time is not None and b.close_time > a.open_time for b in _t1s[:i])}
_csak1_halm = [k for k in csak1 if k in _halmozott]
print(f"   csak-egypáros kötésből HALMOZOTT (nyitott mellé nyílt): {len(_csak1_halm)} / {len(csak1)}"
      f"  (az egypáros összes halmozott kötése: {len(_halmozott)})")
for k in csak1[:5]:
    print("   csak EGYPÁROS:  " + sor(k1[k]) + ("  [HALMOZOTT]" if k in _halmozott else ""))
for k in csak2[:5]:
    print("   csak PORTFÓLIÓ: " + sor(k2[k]))

elt_kilep = [k for k in kozos
             if (str(k1[k].close_time), k1[k].status) != (str(k2[k].close_time), k2[k].status)]
check("a közös kötések KILÉPÉSE (idő, státusz) egyezik", not elt_kilep,
      f"{len(elt_kilep)} eltér / {len(kozos)} közös")
for k in elt_kilep[:5]:
    print("   egypáros:  " + sor(k1[k]))
    print("   portfólió: " + sor(k2[k]))

elt_pnl = [k for k in kozos if abs(k1[k].pnl_usd - k2[k].pnl_usd) > 0.01]
check("a közös kötések P&L-je egyezik (1 cent)", not elt_pnl,
      f"{len(elt_pnl)} eltér / {len(kozos)} közös")
for k in elt_pnl[:5]:
    print(f"   {k}: egypáros {k1[k].pnl_usd:+.2f} (lot {k1[k].lot}, sl {k1[k].sl_points:.0f}) "
          f"| portfólió {k2[k].pnl_usd:+.2f} (lot {k2[k].lot}, sl {k2[k].sl_points:.0f})")

veg1 = BAL + sum(t.pnl_usd for t in t1)
check("a VÉGEGYENLEG egyezik (1 cent)", abs(veg1 - float(r2.get("final_balance", 0))) <= 0.01,
      f"{veg1:.2f} vs {r2.get('final_balance', 0):.2f}")

jo = sum(results)
print(f"\n{jo}/{len(results)} teszt PASS")
sys.exit(0 if jo == len(results) else 1)
