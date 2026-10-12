"""Trailing indulása + a Pozíciók fül számai (Tibi, 2026-10-12).

„A Trail nem működik … akkor sem, amikor már be van húzva BE-be és onnan
indulna. Ki sem írja, hány pont az 1 R távolság."

A leletek, amiket ez a teszt őriz:
  1. a motor CSAK költség-tudatos BE után trailelt; a felület és az újraindítás
     utáni slot-helyreállítás ÁR alapján (SL a belépőn/túl) — kézzel a nyitóárra
     húzott stopnál a felület zöld Trailt mutatott, a motor sosem húzott;
  2. a táv-mező a stratégia paraméterfájljából olvasta a szorzót (v1.96.0 óta
     nincs ott) → ÜRES maradt;
  3. a „Ki →BE" tooltip a régi helyről vette a küszöböt, a `breakeven_r`-t nem nézte;
  4. nem volt 1 R pontban.

⚠ Se MT5, se valódi config/adatfájl.
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import risk_reduction as RR                            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. ár-alapú indulás ───────────────────────────────────────────────────
B = RR.sl_beyond_entry
check("BUY: SL a nyitón → igen", B(True, 100.0, 100.0))
check("BUY: SL a nyitó fölött → igen", B(True, 100.0, 100.5))
check("BUY: SL a nyitó alatt → nem", not B(True, 100.0, 99.5))
check("SELL: SL a nyitón/alatta → igen", B(False, 100.0, 100.0) and B(False, 100.0, 99.0))
check("SELL: SL a nyitó fölött → nem", not B(False, 100.0, 100.5))
check("nincs SL → nem", not B(True, 100.0, 0.0) and not B(False, 100.0, None))

from core import mt5_connector as MC                             # noqa: E402
_p = lambda t, o, sl: NS(type=t, price_open=o, sl=sl)
check("ugyanaz a szabály, mint a felület/slot-helyreállítás `_pos_risk_free`-je",
      all(B(t == 0, o, sl) == MC._pos_risk_free(_p(t, o, sl))
          for t in (0, 1) for o, sl in ((100, 100), (100, 101), (100, 99), (100, 0))))

_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a fő ág trailingje az ár-alapú indulást is elfogadja",
      "_do_trailing = ((is_rf or _price_rf)" in _src)
check("...és a szünet-ág is (ugyanaz a szabály)",
      "if ((is_rf or _rr_mod.sl_beyond_entry(" in _src)

# A trailing maga: SL a nyitón (SELL), az ár jócskán a javunkra → húz, és a nyitón
# rosszabbra sosem.
tr = RR.trailing_new_sl(False, 82707.0, 82600.0, 82707.0, entry_atr=60.0,
                        trail_distance_atr=0.4, trail_activation_atr=0.5,
                        point=0.01, digits=2)
check("SELL, SL a nyitón, ár 107 ponttal lejjebb → a trailing húz (24 pont követés)",
      tr is not None and abs(tr[0] - 82624.0) < 1e-6, tr)

# ── 2. move_to_breakeven sosem húz vissza ───────────────────────────────
class _Conn:
    def __init__(self, pos, spec):
        self.pos, self.spec, self.modified = pos, spec, []

    def positions(self, ticket=None):
        return [self.pos]

    def symbol_spec(self, sym):
        return self.spec

    def modify_sltp(self, t, sl, tp):
        self.modified.append(sl)
        return NS(ok=True)


_spec = NS(point=0.01, spread=10, digits=2, trade_stops_level=0, trade_tick_size=0.01)
_pos = NS(ticket=1, symbol="BTCUSD", type=1, price_open=82707.0, price_current=82500.0,
          sl=82600.0, volume=0.04, swap=0.0, commission=0.0, profit=8.0)
_c = _Conn(_pos, _spec)
_orig_get, _orig_plan = MC._connector.get, MC._breakeven_plan
try:
    MC._connector.get = lambda: _c
    MC._breakeven_plan = lambda p, info: (82706.0, True)     # BE-cél: a nyitó alatt 1
    ok = MC.move_to_breakeven(1)
    check("SELL: az SL már a BE-cél ALATT (jobb) → kész, NEM húzza vissza",
          ok and _c.modified == [], _c.modified)
    _pos.sl = 82746.0
    ok = MC.move_to_breakeven(1)
    check("...a BE-cél előtt → mozgat", ok and _c.modified == [82706.0], _c.modified)
finally:
    MC._connector.get, MC._breakeven_plan = _orig_get, _orig_plan

# ── 3. táv-mező: a kockázatcsökkentés szorzója × belépéskori ATR ─────────
from dashboard import gui as GUI                                 # noqa: E402
from core import rr_state as RS                                  # noqa: E402
_orig_spec = RS.spec_for
try:
    RS.spec_for = lambda sym: {"trail_distance_atr": 0.4, "breakeven_pct": 0.5,
                               "breakeven_r": 1.0, "preset": "off"}
    fake = NS(cfg={"pairs": {"BTCUSD": {"point_size": 0.01}}},
              dashboard_ref={"BTCUSD": NS(atr_price=50.0, point=0.01)},
              _pos_params=lambda s: {})
    v = GUI.DashboardWindow._trail_default(fake, "BTCUSD", {"entry_atr": 60.0})
    check("a táv a BELÉPÉSKORI ATR-ből: 0,4 × 60 / 0,01 = 2400 pont", v == 2400, v)
    v2 = GUI.DashboardWindow._trail_default(fake, "BTCUSD", None)
    check("entry_atr nélkül a mostani ATR (közelítés): 2000 pont", v2 == 2000, v2)
    check("a stratégia paraméterfájlja NEM kell hozzá (üres volt → üres mező)",
          v is not None)

    # ── 4. Kiszállás-cella: a motor küszöbe (breakeven_r) ──────────────────
    RS.effective_preset = (lambda s: "off")
    plan = GUI._exit_plan("BTCUSD", {}, {"cur_r": -0.5, "risk_price": 39.0, "risk_usd": 1.6,
                                          "entry": 82707.0, "cur": 82726.5,
                                          "tp": 82446.0, "dir_s": -1})
    check("„Ki →BE”", plan["text"] == "Ki →BE", plan["text"])
    check("a tooltip az R-küszöböt mondja, ha az be van állítva (breakeven_r=1)",
          "1 R" in plan["tooltip"], plan["tooltip"])
    check("...és a hátralévő utat is a motor küszöbéhez méri (+1,50R)",
          "+1.50R" in plan["tooltip"], plan["tooltip"])
finally:
    RS.spec_for = _orig_spec
    import importlib
    importlib.reload(RS)

# ── 5. 1R oszlop ──────────────────────────────────────────────────────────
check("van 1R oszlop a Pozíciók fülön",
      any(c[0] == "one_r" for c in GUI.POSITION_COLUMNS))

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
