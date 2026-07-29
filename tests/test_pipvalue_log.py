"""#11 (pip-ertek + lot-korlatok) es a forgo fajl-naplo tesztje."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import order_exec as ox
from core.risk_manager import calc_lot, calc_effective_slots

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class Info:
    def __init__(self, tv=0.0, ts=0.0, vmin=0.01, vmax=100.0, vstep=0.01):
        self.trade_tick_value, self.trade_tick_size = tv, ts
        self.volume_min, self.volume_max, self.volume_step = vmin, vmax, vstep


# ══ point_value ══════════════════════════════════════════════════════════════
# EURUSD EUR-szamlan: tick 0.00001, tick-ertek 0.879 EUR -> 1 pip (0.0001) = 8.79
check("EURUSD: tv/ts*pip = 8.79",
      abs(ox.point_value("EURUSD", 0.0001, Info(tv=0.879, ts=0.00001)) - 8.79) < 1e-9,
      str(ox.point_value("EURUSD", 0.0001, Info(tv=0.879, ts=0.00001))))
# UK100 EUR-szamlan: 1 pont = 1 GBP = ~1.17 EUR  (a configban KEREK 1.0 all!)
check("UK100: a broker ~1.17-et ad (a configban 1.0 van)",
      abs(ox.point_value("UK100", 1.0, Info(tv=1.17, ts=1.0)) - 1.17) < 1e-9)
check("hianyzo tick-ertek -> None", ox.point_value("X", 0.0001, Info()) is None)
check("nulla point_size -> None", ox.point_value("X", 0.0, Info(tv=1, ts=1)) is None)
check("nincs info -> None", ox.point_value("X", 0.0001, None) is None)

# ══ volume_bounds ══════════════════════════════════════════════════════════
vb = ox.volume_bounds(Info(vmin=0.25, vmax=50.0, vstep=0.25))
check("volume_bounds -> (min, max, step)", vb == (0.25, 50.0, 0.25), str(vb))
vb0 = ox.volume_bounds(Info(vmin=0.01, vmax=0.0, vstep=0.01))
check("volume_max=0 (nincs korlat) -> inf", vb0[1] == float("inf"))
check("hianyzo adat -> None", ox.volume_bounds(Info(vmin=0, vstep=0)) is None)

# ══ calc_lot: felso korlat ═════════════════════════════════════════════════
tcfg = {"account_risk_pct": 0.01, "max_open_slots": 4}
big = {"pv1_point": 1.0, "min_lot": 0.1, "lot_step": 0.1}          # nincs max_lot
lot_nocap = calc_lot(1_000_000, 5.0, big, tcfg, 1)
check("felso korlat nelkul nagy lot johet ki", lot_nocap > 100, str(lot_nocap))
capped = calc_lot(1_000_000, 5.0, {**big, "max_lot": 50.0}, tcfg, 1)
check("max_lot vagja (10014 Invalid volume helyett)", capped == 50.0, str(capped))
check("a vagas csak CSOKKENTI a kockazatot", capped < lot_nocap)
small = calc_lot(1000, 500.0, {**big, "max_lot": 50.0}, tcfg, 1)
check("min_lot tovabbra is also korlat", small == 0.1, str(small))

# ══ A valos hatas: elavult pv1_point -> rossz meret ══════════════════════════
BAL, SL = 10_000.0, 20.0
uk_cfg_wrong = {"pv1_point": 1.0,  "min_lot": 0.1, "lot_step": 0.1}   # a configban ez van
uk_cfg_real  = {"pv1_point": 1.17, "min_lot": 0.1, "lot_step": 0.1}   # a broker szerint
lot_wrong = calc_lot(BAL, SL, uk_cfg_wrong, tcfg, 4)
lot_real  = calc_lot(BAL, SL, uk_cfg_real,  tcfg, 4)
risk_target = BAL * tcfg["account_risk_pct"] / 4
risk_actual = lot_wrong * SL * 1.17          # a TENYLEGES kockazat a rossz lottal
check("UK100: az elavult 1.0 tul nagy lotot ad", lot_wrong > lot_real,
      f"{lot_wrong} vs {lot_real}")
check("...a tenyleges kockazat a celt tullepi (~+15%)",
      risk_actual > risk_target * 1.1,
      f"cel {risk_target:.2f}, tenyleges {risk_actual:.2f}")
check("a helyes pv1-gyel a kockazat a celon belul",
      lot_real * SL * 1.17 <= risk_target + 1e-9,
      f"{lot_real * SL * 1.17:.2f} <= {risk_target:.2f}")

# ══ Forgo fajl-naplo ═══════════════════════════════════════════════════════
import tempfile
from core import applog

tmp = Path(tempfile.mkdtemp())
applog.LOG_DIR, applog.LOG_PATH = tmp, tmp / "tradeforge.log"

p1 = applog.setup()
check("setup() letrehozza a naplot", p1 == tmp / "tradeforge.log")
root_handlers = len(logging.getLogger().handlers)
p2 = applog.setup()
check("idempotens (nem duplaz handlert)",
      p2 == p1 and len(logging.getLogger().handlers) == root_handlers)

logging.getLogger("teszt").info("Árvíztűrő ✦ belépő | SL → BE ⏭ 📋")
for h in logging.getLogger().handlers:
    h.flush()
txt = (tmp / "tradeforge.log").read_text(encoding="utf-8")
check("a magyar ekezetek es ikonok OLVASHATOK a fajlban (UTF-8)",
      "Árvíztűrő" in txt and "✦" in txt and "📋" in txt)
check("a sor tartalmazza az idobelyeget es a szintet",
      "INFO" in txt and "teszt" in txt)
check("forgatas be van allitva (RotatingFileHandler, 5 MB x 5)",
      any(getattr(h, "maxBytes", 0) == 5 * 1024 * 1024
          and getattr(h, "backupCount", 0) == 5
          for h in logging.getLogger().handlers))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
