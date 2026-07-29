"""#12 — a backteszt jutalek- es swap-modellezese."""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import trade_costs as tc

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def ts(y, m, d, hh=12, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp()


# ══ nights_held: hany swap-fordulo ═════════════════════════════════════════
# 2026-07-27 hetfo. Ellenorzes:
check("a datum-alap helyes (2026-07-27 hetfo)",
      datetime(2026, 7, 27, tzinfo=timezone.utc).weekday() == 0)

check("napon beluli zaras -> 0 ejszaka",
      tc.nights_held(ts(2026, 7, 27, 8), ts(2026, 7, 27, 20), None) == 0.0)
check("egy ejfel atlepese -> 1",
      tc.nights_held(ts(2026, 7, 27, 20), ts(2026, 7, 28, 8), None) == 1.0)
check("harom ejfel -> 3",
      tc.nights_held(ts(2026, 7, 27, 20), ts(2026, 7, 30, 8), None) == 3.0)
check("zaras = nyitas -> 0", tc.nights_held(ts(2026, 7, 27), ts(2026, 7, 27), None) == 0.0)
check("visszafele ido -> 0", tc.nights_held(ts(2026, 7, 28), ts(2026, 7, 27), None) == 0.0)

# 3x-os nap (szerda = 2). 07-29 szerda.
check("a szerdai fordulo HAROMSZOROS",
      tc.nights_held(ts(2026, 7, 28, 20), ts(2026, 7, 29, 8), 2) == 3.0)
check("kedd->szerda->csutortok = 3 + 1 = 4",
      tc.nights_held(ts(2026, 7, 28, 20), ts(2026, 7, 30, 8), 2) == 4.0)
check("3x kikapcsolva (None) -> ugyanaz 2 ejszaka",
      tc.nights_held(ts(2026, 7, 28, 20), ts(2026, 7, 30, 8), None) == 2.0)
check("penteki 3x nap is beallithato (4)",
      tc.nights_held(ts(2026, 7, 30, 20), ts(2026, 7, 31, 8), 4) == 3.0)

# ══ jutalek ════════════════════════════════════════════════════════════════
cfg = {"commission_per_lot": 7.0}
check("jutalek = per_lot * lot (oda-vissza)", tc.commission_usd(0.5, cfg) == 3.5)
check("negativan megadott jutalek is koltseg (abs)",
      tc.commission_usd(1.0, {"commission_per_lot": -7.0}) == 7.0)
check("nincs kulcs -> 0", tc.commission_usd(1.0, {}) == 0.0)

# ══ swap ═══════════════════════════════════════════════════════════════════
scfg = {"swap_long_per_lot": -2.0, "swap_short_per_lot": 0.5, "swap_3x_weekday": 2}
sw = tc.swap_usd(1.0, "BUY", ts(2026, 7, 27, 20), ts(2026, 7, 28, 8), scfg)
check("BUY swap 1 ejszaka -> -2.0", sw == -2.0, str(sw))
sw = tc.swap_usd(2.0, "SELL", ts(2026, 7, 27, 20), ts(2026, 7, 28, 8), scfg)
check("SELL swap POZITIV is lehet (jovairas): 2 lot -> +1.0", sw == 1.0, str(sw))
sw = tc.swap_usd(1.0, "BUY", ts(2026, 7, 28, 20), ts(2026, 7, 29, 8), scfg)
check("a szerdai fordulo haromszoros swapot ad (-6.0)", sw == -6.0, str(sw))
check("napon belul nincs swap",
      tc.swap_usd(1.0, "BUY", ts(2026, 7, 27, 8), ts(2026, 7, 27, 20), scfg) == 0.0)
check("nincs kulcs -> 0", tc.swap_usd(1.0, "BUY", ts(2026, 7, 27), ts(2026, 7, 30), {}) == 0.0)

# ══ apply: netto P&L ═══════════════════════════════════════════════════════
full = {"commission_per_lot": 7.0, "swap_long_per_lot": -2.0,
        "swap_short_per_lot": 0.5, "swap_3x_weekday": 2}
net, c, s = tc.apply(100.0, 1.0, "BUY", ts(2026, 7, 27, 20), ts(2026, 7, 28, 8), full)
check("netto = brutto - jutalek + swap (100 - 7 - 2 = 91)", net == 91.0, str(net))
check("a jutalek es a swap kulon is visszajon", c == 7.0 and s == -2.0)

net0, c0, s0 = tc.apply(100.0, 1.0, "BUY", ts(2026, 7, 27, 8), ts(2026, 7, 27, 20), {})
check("koltseg nelkuli config -> a regi (valtozatlan) eredmeny",
      net0 == 100.0 and c0 == 0.0 and s0 == 0.0)

check("configured(): ures -> False", tc.configured({}) is False)
check("configured(): van jutalek -> True", tc.configured({"commission_per_lot": 7}) is True)

# ══ A LENYEG: a hosszan tartott runner tobbet fizet ════════════════════════
# Ket azonos brutto eredmenyu kotes: egy napon beluli, es egy 5 napig tartott.
napon_beluli, _, _ = tc.apply(50.0, 1.0, "BUY", ts(2026, 7, 27, 8),
                              ts(2026, 7, 27, 20), full)
runner, _, s_run = tc.apply(50.0, 1.0, "BUY", ts(2026, 7, 27, 8),
                            ts(2026, 8, 1, 20), full)
check("azonos brutto mellett a HOSSZAN tartott runner nettoja rosszabb",
      runner < napon_beluli, f"{runner:.2f} < {napon_beluli:.2f}")
check("...a kulonbseg pontosan a felhalmozott swap",
      abs((napon_beluli - runner) - abs(s_run)) < 1e-9,
      f"swap={s_run:.2f}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
