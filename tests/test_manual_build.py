"""#6 (raepitett lab stop-garanciaja) + a csomag STRATEGIA-hatokore.

A csomag = a strategiahoz RENDELT poziciok: a magicjevel nyitottak + a feluletrol
hozzarendelt (orokbefogadott) keziek. Egy masik strategia labaihoz sosem nyulunk.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import position_build as pb
from core import mt5_connector as mc
import trading.live_trader as lt

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ package_stop: tiszta logika ════════════════════════════════════════════
stop, clamped = pb.package_stop(100.0, "BUY", 100.5, 1.0, 0.01)
check("BUY: atlagar a min. stop-tavolsagon belul -> vagas", clamped)
check("BUY: a vagott stop ervenyes", abs(stop - 99.49) < 1e-9, str(stop))
check("BUY: a vagott stop az ATLAG ALATT (kis minusz, nem nulla)", stop < 100.0)
stop, clamped = pb.package_stop(100.0, "BUY", 105.0, 1.0, 0.01)
check("BUY: tavolsagon kivul -> nincs vagas", (not clamped) and stop == 100.0)
stop, clamped = pb.package_stop(100.0, "SELL", 99.5, 1.0, 0.01)
check("SELL: tul kozel -> a stop az ATLAG FOLOTT", clamped and stop > 100.0, str(stop))
check("nincs broker-korlat -> nincs vagas",
      pb.package_stop(100.0, "BUY", 100.5, 0.0, 0.0) == (100.0, False))


# ══ Kozos elokeszites ══════════════════════════════════════════════════════
MAGIC_A, MAGIC_B = 100, 200
SYM = "EURUSD"


class P:
    def __init__(self, ticket, price_open, volume, sl, magic, symbol=SYM):
        self.ticket, self.price_open, self.volume = ticket, price_open, volume
        self.sl, self.magic, self.symbol, self.tp, self.type = sl, magic, symbol, 0.0, 0


class Info:
    digits, point, trade_tick_size, trade_stops_level = 5, 0.00001, 0.00001, 0
    filling_mode, spread = 3, 5


class Tick:
    bid, ask = 1.1050, 1.1051


class Slots:
    def __init__(self):
        self.added, self.rf, self.risks = [], [], []

    def add(self, t, risk_ccy=0.0):
        # A slot KOCKAZATI KERET (core.risk_manager): a motor a pozicio
        # kockazatat is atadja, ebbol szamol sulyt.
        self.added.append(t)
        self.risks.append(risk_ccy)

    def set_risk_free(self, t):
        self.rf.append(t)


class Strat:
    def __init__(self, m):
        self._m = m

    def magic(self, cfg):
        return self._m


class FakeMT5:
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1

    def __init__(self, positions, after=None):
        self._pos, self._after, self.calls = positions, after, 0

    def positions_get(self, symbol=None, ticket=None):
        self.calls += 1
        return self._after if (self.calls > 1 and self._after is not None) else self._pos

    def symbol_info(self, s):
        return Info()

    def symbol_info_tick(self, s):
        return Tick()


orig = (lt.mt5, lt.open_position, mc.modify_position_sltp, lt.get_strategy_by_name,
        lt.adopted.strategy_of, lt.adopted.tickets_for, lt.adopted.adopt)


def setup(positions, after, sltp_results=None, stops_level=0, adopted_map=None):
    Info.trade_stops_level = stops_level
    sltp_results = sltp_results or {}
    adopted_map = adopted_map or {}          # ticket -> strategia
    lt.mt5 = FakeMT5(positions, after)
    lt._run_cfg = {"broker": {"magic": MAGIC_A}}
    lt.get_strategy_by_name = lambda n: Strat(MAGIC_A if n == "A" else MAGIC_B)
    lt.adopted.strategy_of = lambda t: adopted_map.get(t)
    lt.adopted.tickets_for = lambda n: {t for t, s in adopted_map.items() if s == n}
    lt.adopted.adopt = lambda *a, **k: None
    lt.build_runtime.clear()
    lt.position_state.clear()
    lt._run_slot_mgr = Slots()
    opened = {}
    lt.open_position = lambda *a, **k: opened.setdefault("t", 999)
    calls = []

    def fake_sltp(ticket, sl, tp):
        ok = sltp_results.get(ticket, True)
        calls.append((ticket, round(sl, 5), tp, ok))
        return ok

    mc.modify_position_sltp = fake_sltp
    return calls, opened


def ready(strat="A"):
    lt.build_runtime[(SYM, strat)] = {"ready": True, "direction": "BUY", "next_lot": 0.5}


# ══ strategy_of_ticket / strategy_positions ════════════════════════════════
setup([], None, adopted_map={7: "A"})
lt._magic_to_strategy.clear()
lt._magic_to_strategy.update({MAGIC_A: "A", MAGIC_B: "B"})
check("orokbefogadott ticket -> a hozzarendelt strategia",
      lt.strategy_of_ticket(7, MAGIC_B) == "A")
check("nem orokbefogadott -> a magic dont", lt.strategy_of_ticket(3, MAGIC_B) == "B")
check("ismeretlen magic + nincs hozzarendeles -> None",
      lt.strategy_of_ticket(3, 999) is None)

# A: 1 sajat (magic A) + 1 orokbefogadott kezi (magic 0); B: 1 sajat; + masik szimbolum
allpos = [P(1, 1.1000, 1.0, 1.0950, MAGIC_A),
          P(2, 1.1010, 1.0, 1.0960, 0),          # kezi, A-ra osztva
          P(3, 1.1020, 1.0, 1.0970, MAGIC_B),    # B strategiaja
          P(4, 1.2000, 1.0, 1.1900, MAGIC_A, symbol="GBPUSD")]
setup(allpos, None, adopted_map={2: "A"})
pa = {p.ticket for p in lt.strategy_positions(SYM, "A")}
pbs = {p.ticket for p in lt.strategy_positions(SYM, "B")}
check("A csomagja = sajat magic + orokbefogadott (masik szimbolum nelkul)",
      pa == {1, 2}, str(sorted(pa)))
check("B csomagja csak a sajatja", pbs == {3}, str(sorted(pbs)))

# ══ manual_build: CSAK a sajat labak ═══════════════════════════════════════
after = allpos + [P(999, 1.1051, 0.5, 1.0950, MAGIC_A)]
calls, opened = setup(allpos, after, adopted_map={2: "A"})
ready("A")
ok = lt.manual_build(SYM, "A")
touched = sorted(c[0] for c in calls)
check("raepites -> True", ok)
check("CSAK az A labai kaptak kozos stopot (B es a masik szimbolum NEM)",
      touched == [1, 2, 999], str(touched))
check("a B strategia lab (3) erintetlen", 3 not in touched)
check("az orokbefogadott kezi lab (2) BENNE van a csomagban", 2 in touched)
check("a TP torolve mindenhol", all(c[2] == 0.0 for c in calls))
check("mind kockazatmentes", sorted(lt._run_slot_mgr.rf) == [1, 2, 999])

# ══ build_runtime per (szimbolum, strategia) — nincs felulirás ═════════════
lt.build_runtime.clear()
lt.build_runtime[(SYM, "A")] = {"ready": True, "direction": "BUY", "next_lot": 0.5}
lt.build_runtime[(SYM, "B")] = {"ready": False, "direction": "SELL", "next_lot": 0.1}
check("ket strategia allapota egyutt el ugyanarra a szimbolumra",
      lt.build_runtime[(SYM, "A")]["direction"] == "BUY"
      and lt.build_runtime[(SYM, "B")]["direction"] == "SELL")
check("a nem-ready strategiara nem epit", lt.manual_build(SYM, "B") is False)

# Strategia nelkuli hivas: ket jelolt -> nem tippel
check("ket epito strategia + nincs megadva strategia -> nem tippel",
      lt.manual_build(SYM) is False)
# Egyetlen jelolt -> feloldja
lt.build_runtime.pop((SYM, "B"))
calls, opened = setup(allpos, after, adopted_map={2: "A"})
ready("A")
check("egyetlen epito strategia -> feloldja strategia-nev nelkul is",
      lt.manual_build(SYM) is True)

# ══ A #6 hibaagai (a strategia-hatokorrel egyutt) ══════════════════════════
calls, opened = setup(allpos, after, {999: False}, adopted_map={2: "A"})
ready("A")
ok = lt.manual_build(SYM, "A")
check("stop-hiba -> MEGIS True (az AUTO ne duplazzon)", ok)
check("a bukott lab NINCS kockazatmentesnek jelolve", 999 not in lt._run_slot_mgr.rf)
check("a sikeres labak igen", {1, 2} <= set(lt._run_slot_mgr.rf))

calls, opened = setup(allpos, allpos, adopted_map={2: "A"})   # az uj lab nem jelenik meg
ready("A")
ok = lt.manual_build(SYM, "A")
check("hianyzo lab -> True, de NINCS stop-allitas regi listabol",
      ok and not calls, f"{len(calls)} hivas")
check("...es semmi sincs kockazatmentesnek jelolve", not lt._run_slot_mgr.rf)

calls, opened = setup(allpos, after, stops_level=500, adopted_map={2: "A"})
ready("A")
lt.manual_build(SYM, "A")
check("vagott stop -> SENKI nem kockazatmentes", not lt._run_slot_mgr.rf)

calls, opened = setup([P(1, 1.1000, 1.0, 0.0, MAGIC_A)], after, adopted_map={})
ready("A")
check("stop nelkuli csomag -> nem epit", lt.manual_build(SYM, "A") is False)
check("...es nem is nyitott labat", "t" not in opened)

(lt.mt5, lt.open_position, mc.modify_position_sltp, lt.get_strategy_by_name,
 lt.adopted.strategy_of, lt.adopted.tickets_for, lt.adopted.adopt) = orig

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
