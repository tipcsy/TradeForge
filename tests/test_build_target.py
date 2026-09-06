"""0001 — A CSOMAG KOZOS CELARA (`target_r`).

A felhasznalo dontese: „legyen egy celar, pl. 20 R", es „elso korben a TP celar
legyen, ne az SL celar". A cel a TELJES csomagra szol (atlagar + ossz-kockazat).

⚠ EZ A TESZT AZ ALAPERTELMEZETT VISELKEDES VALTOZATLANSAGAT is orzi: a
`target_r` alapja 0, es akkor a csomag TP NELKUL fut — pontosan mint a
bevezetese elott. Ha alapbol bekapcsolna, a projekt osszes korabbi meresi
eredmenyet ervenytelenitene (a memoria szerint a celar ELHAGYASA volt a
legnagyobb egyetlen javulas, +0,031 R).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import position_build as pb
from core import build_state as bst
import trading.live_trader as lt
from trading import backtest as bt

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. package_target — a szamtan ══════════════════════════════════════════
# Egy lab: 0,10 lot, 200 pont stop, pv1=1,0 -> kockazat = 0,10*200*1,0 = 20
LOT, PV1, PS, SLP, AVG = 0.10, 1.0, 0.00001, 200.0, 1.10000
RISK = LOT * SLP * PV1

tp1 = pb.package_target(AVG, "BUY", RISK, 1.0, LOT, PV1, PS)
check("1 R cel tavolsaga = a belepo STOP-tavolsaga",
      abs((tp1 - AVG) / PS - SLP) < 1e-6, f"{(tp1 - AVG) / PS:.4f} pont")
tp20 = pb.package_target(AVG, "BUY", RISK, 20.0, LOT, PV1, PS)
check("20 R = 20x az 1 R tavolsaga",
      abs((tp20 - AVG) - 20 * (tp1 - AVG)) < 1e-9, f"{tp20:.5f}")
tp20s = pb.package_target(AVG, "SELL", RISK, 20.0, LOT, PV1, PS)
check("SELL a masik oldalra, ugyanakkora tavra",
      abs((AVG - tp20s) - (tp20 - AVG)) < 1e-9, f"{tp20s:.5f}")

# ⚠ A `pv1_point` PONTONKENTI: a point_size nelkul a cel a point_size
# reciprokanak aranyaban lenne hibas (EURUSD-n 10 000x). Ezt orzi ez a sor.
check("a cel ARANYOS a point_size-zal (nem pontot ad ar helyett)",
      abs(pb.package_target(AVG, "BUY", RISK, 1.0, LOT, PV1, PS * 10) - AVG
          - 10 * (tp1 - AVG)) < 1e-9)

# ⚠ HIANYZO ADATNAL 0.0 (nincs cel), NEM kitalalt ar
for nev, args in (
        ("nincs cel (target_r=0)", (AVG, "BUY", RISK, 0.0, LOT, PV1, PS)),
        ("nincs kockazat",         (AVG, "BUY", 0.0, 20.0, LOT, PV1, PS)),
        ("nincs lot",              (AVG, "BUY", RISK, 20.0, 0.0, PV1, PS)),
        ("nincs pv1_point",        (AVG, "BUY", RISK, 20.0, LOT, 0.0, PS)),
        ("nincs point_size",       (AVG, "BUY", RISK, 20.0, LOT, PV1, 0.0)),
        ("szemet bemenet",         (AVG, "BUY", "x", 20.0, LOT, PV1, PS))):
    check(f"{nev} -> 0.0 (nem talal ki arat)", pb.package_target(*args) == 0.0)

# A CSOMAGRA szol: ket azonos lab -> az ossz-kockazat ES az ossz-lot is 2x,
# tehat a TAVOLSAG valtozatlan (nem 2x). Ez a „csomagra, nem az elso labra".
tp_pkg = pb.package_target(AVG, "BUY", 2 * RISK, 1.0, 2 * LOT, PV1, PS)
check("ket azonos lab: a cel-tavolsag valtozatlan (csomag-szemlelet)",
      abs(tp_pkg - tp1) < 1e-9, f"{tp_pkg:.5f}")

# ══ 2. Az ALAP valtozatlan ═════════════════════════════════════════════════
check("default_config: target_r = 0 (nincs cel)",
      pb.default_config()["target_r"] == 0.0)
check("build_state _KEYS: a target_r mentheto", "target_r" in bst._KEYS)
check("build_state: negativ target_r -> 0.0 (a TP nem kerulhet rossz oldalra)",
      bst._norm({"mode": "auto", "target_r": -5}).get("target_r") == 0.0)
check("build_state: ervenyes target_r megmarad",
      bst._norm({"mode": "auto", "target_r": 20}).get("target_r") == 20.0)

# ══ 3. Trade.tp_eff — melyik celar el ══════════════════════════════════════
def _tr(legs, tp=1.2, pkg_tp=0.0):
    t = bt.Trade(symbol="X", direction="BUY", open_time=None, open_price=1.1,
                 sl=1.09, tp=tp, lot=0.1, point_size=PS, pv1_point=PV1,
                 sl_points=SLP)
    t.legs, t.pkg_tp = legs, pkg_tp
    return t


check("egyleges pozicio -> a belepeskori TP el", _tr([]).tp_eff == 1.2)
check("egy lab a legs-ben meg nem 'epitett'", _tr([(1.1, 0.1)]).tp_eff == 1.2)
check("EPITETT csomag cel NELKUL -> 0.0 (TP nelkul fut, mint eddig)",
      _tr([(1.1, 0.1), (1.11, 0.07)]).tp_eff == 0.0)
check("EPITETT csomag CELLAL -> a KOZOS celar (nem az elso lab TP-je)",
      _tr([(1.1, 0.1), (1.11, 0.07)], pkg_tp=1.5).tp_eff == 1.5)

# ══ 3b. package_trail_stop — a KUSZO kozos stop (0001 / 2. kor) ════════════
# A felhasznalo megfogalmazasa: „ugy szukiti az SL-t pozitivba, ahogy kezdi
# elerni a celarat". Alap: atlagar 1,10 · cel 1,14 (span 0,04) · trail 0,5.
_A, _C = 1.10, 1.14
ptr = pb.package_trail_stop

check("meg nincs halados -> nincs mozgatas (0.0)", ptr(_A, "BUY", 1.09, _C, 0.5) == 0.0)
check("pont az atlagaron -> nincs mozgatas", ptr(_A, "BUY", _A, _C, 0.5) == 0.0)
check("a cel negyedenel -> a cel-tav 1/8-a profitban",
      abs(ptr(_A, "BUY", 1.11, _C, 0.5) - 1.105) < 1e-9,
      f"{ptr(_A, 'BUY', 1.11, _C, 0.5):.5f}")
check("a cel felenel -> a cel-tav negyedenel",
      abs(ptr(_A, "BUY", 1.12, _C, 0.5) - 1.11) < 1e-9)
check("a celnal -> a cel-tav felenel (trail_pct = 0,5)",
      abs(ptr(_A, "BUY", _C, _C, 0.5) - 1.12) < 1e-9)
# ⚠ A CELT TULLEPO ar (res/csuszas) nem viheti a stopot a cel FOLE
check("a celt tullepve is legfeljebb a trail_pct-ig (1-re vagott halados)",
      abs(ptr(_A, "BUY", 1.20, _C, 0.5) - 1.12) < 1e-9,
      f"{ptr(_A, 'BUY', 1.20, _C, 0.5):.5f}")
check("trail_pct = 1,0 -> a stop az arral egyutt er a celba",
      abs(ptr(_A, "BUY", _C, _C, 1.0) - _C) < 1e-9)

# ⚠ CSAK ELORE: visszahuzodo arnal NEM lazitunk
check("szorosabb stop -> mozgatunk", ptr(_A, "BUY", 1.12, _C, 0.5, current_sl=1.105) > 0)
check("azonos stop -> nem mozgatunk", ptr(_A, "BUY", 1.12, _C, 0.5, current_sl=1.11) == 0.0)
check("LAZABB stop -> nem mozgatunk (a csuszo stop nem huzodik vissza)",
      ptr(_A, "BUY", 1.11, _C, 0.5, current_sl=1.11) == 0.0)

# SELL tukorkep
check("SELL: a cel felenel a cel-tav negyedenel",
      abs(ptr(1.10, "SELL", 1.08, 1.06, 0.5) - 1.09) < 1e-9)
check("SELL: csak elore (kisebb stop a jobb)",
      ptr(1.10, "SELL", 1.08, 1.06, 0.5, current_sl=1.09) == 0.0)

for nev, args in (("nincs kuszas (pct=0)", (_A, "BUY", 1.12, _C, 0.0)),
                  ("nincs cel",            (_A, "BUY", 1.12, 0.0, 0.5)),
                  ("rossz oldali cel",     (_A, "BUY", 1.12, 1.05, 0.5)),
                  ("szemet bemenet",       (_A, "BUY", "x", _C, 0.5))):
    check(f"{nev} -> 0.0", ptr(*args) == 0.0)

check("default_config: target_trail_pct = 0 (nincs kuszas)",
      pb.default_config()["target_trail_pct"] == 0.0)
check("build_state _KEYS: a target_trail_pct mentheto",
      "target_trail_pct" in bst._KEYS)
check("build_state: 1 folott 1,0-ra vagva",
      bst._norm({"mode": "auto", "target_trail_pct": 5}).get("target_trail_pct") == 1.0)
check("build_state: negativ -> 0,0",
      bst._norm({"mode": "auto", "target_trail_pct": -1}).get("target_trail_pct") == 0.0)


# ══ 4. AZ EL: a cel MINDEN lab TP-jere ugyanugy kerul ══════════════════════
MAGIC = 100
SYM = "EURUSD"


class P:
    def __init__(self, ticket, price_open, volume, sl, magic=MAGIC, symbol=SYM):
        self.ticket, self.price_open, self.volume = ticket, price_open, volume
        self.sl, self.magic, self.symbol, self.tp, self.type = sl, magic, symbol, 0.0, 0


class Info:
    digits, point, trade_tick_size, trade_stops_level = 5, PS, PS, 0
    filling_mode, spread = 3, 5


class Tick:
    bid, ask = 1.1050, 1.1051


class Slots:
    def add(self, t, risk_ccy=0.0):
        pass

    def set_risk_free(self, t):
        pass


class Strat:
    def magic(self, cfg):
        return MAGIC


class FakeMT5:
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1

    def __init__(self, positions, after):
        self._pos, self._after, self.calls = positions, after, 0

    def positions_get(self, symbol=None, ticket=None):
        self.calls += 1
        _l = self._after if self.calls > 1 else self._pos
        if ticket is not None:
            return [p for p in _l if p.ticket == ticket]
        return _l

    def symbol_info(self, s):
        return Info()

    def symbol_info_tick(self, s):
        return Tick()


class FakeBState:
    """⚠ A teszt SOSEM a valodi `data/build_mode.json`-t olvassa."""

    def __init__(self, target_r):
        self._t = target_r

    def get_config(self, symbol):
        return {**pb.default_config(), "target_r": self._t}


_orig = (lt.mt5, lt.open_position, lt.mt5_connector.modify_position_sltp,
         lt.get_strategy_by_name, lt.adopted.strategy_of, lt.adopted.tickets_for,
         lt.adopted.adopt, lt.position_meta.record, lt.position_meta.risk_of,
         lt._pos_risk_ccy_of, lt._bstate, lt._run_cfg)


def epits(target_r, riskek):
    """Egy raepites `target_r` mellett -> a `modify_position_sltp` hivasok."""
    regi = P(1, 1.1000, 0.10, 1.0980)
    uj = P(999, 1.1051, 0.07, 1.0980)
    lt.mt5 = FakeMT5([regi], [regi, uj])
    lt._run_cfg = {"broker": {"magic": MAGIC},
                   "pairs": {SYM: {"point_size": PS, "pv1_point": PV1}}}
    lt.get_strategy_by_name = lambda n: Strat()
    lt.adopted.strategy_of = lambda t: None
    lt.adopted.tickets_for = lambda n: set()
    lt.adopted.adopt = lambda *a, **k: None
    lt._magic_to_strategy.clear()
    lt._magic_to_strategy[MAGIC] = "A"
    lt.build_runtime.clear()
    lt.position_state.clear()
    lt._run_slot_mgr = Slots()
    lt.open_position = lambda *a, **k: 999
    lt.position_meta.record = lambda *a, **k: None
    lt.position_meta.risk_of = lambda t: riskek.get(t)
    lt._pos_risk_ccy_of = lambda *a, **k: 0.0
    lt._bstate = FakeBState(target_r)
    hivasok = []
    lt.mt5_connector.modify_position_sltp = lambda t, sl, tp: (
        hivasok.append((t, round(sl, 5), round(tp, 5))) or True)
    lt.build_runtime[(SYM, "A")] = {"ready": True, "direction": "BUY",
                                    "next_lot": 0.07}
    lt.manual_build(SYM, "A")
    return hivasok


# 4a) target_r = 0 (ALAP) -> tp = 0.0 minden labon (a MAI viselkedes)
h = epits(0.0, {1: 20.0, 999: 10.0})
check("ALAP (target_r=0): minden lab TP-je 0.0 — valtozatlan viselkedes",
      len(h) == 2 and all(c[2] == 0.0 for c in h), str(h))

# 4b) target_r = 20 -> MINDEN lab UGYANAZT a celt kapja, es az helyes
h = epits(20.0, {1: 20.0, 999: 10.0})
_avg = pb.average_price([(1.1000, 0.10), (1.1051, 0.07)])
_var = pb.package_target(_avg, "BUY", 30.0, 20.0, 0.17, PV1, PS)
check("CELLAL: mindket lab UGYANAZT a TP-t kapja (a csomag EGYBEN zar)",
      len(h) == 2 and h[0][2] == h[1][2] and h[0][2] > 0, str(h))
check("CELLAL: a TP a KOZOS celar (atlagar + ossz-kockazat)",
      abs(h[0][2] - round(_var, 5)) < 1e-5, f"{h[0][2]} vs {_var:.5f}")

# 4c) HIANYZO belepo-kockazat -> NINCS cel (inkabb semmi, mint alultervezett)
h = epits(20.0, {1: 20.0})          # a 999-nek nincs bejegyzese
check("hianyzo belepo-kockazat -> TP nelkul fut (nem alultervezett cel)",
      len(h) == 2 and all(c[2] == 0.0 for c in h), str(h))

# ══ 5. AZ EL: a KUSZO kozos stop (`package_trail`) ═════════════════════════
class TickPx:
    def __init__(self, bid, ask):
        self.bid, self.ask = bid, ask


def kuszas(target_r, pct, ar, sl_most, riskek=None, labak=2):
    """Egy `package_trail` hivas -> a `modify_sl` hivasok [(ticket, sl)]."""
    riskek = riskek if riskek is not None else {1: 20.0, 999: 10.0}
    pos = [P(1, 1.1000, 0.10, sl_most), P(999, 1.1051, 0.07, sl_most)][:labak]
    lt.mt5 = FakeMT5(pos, pos)
    lt._magic_to_strategy.clear()
    lt._magic_to_strategy[MAGIC] = "A"
    lt.get_strategy_by_name = lambda n: Strat()
    lt.adopted.strategy_of = lambda t: None
    lt.adopted.tickets_for = lambda n: set()
    lt.position_meta.risk_of = lambda t: riskek.get(t)
    lt._bstate = type("B", (), {"get_config": staticmethod(
        lambda s: {**pb.default_config(), "target_r": target_r,
                   "target_trail_pct": pct})})()
    hiv = []
    lt.modify_sl = lambda t, sl: (hiv.append((t, round(sl, 5))) or True)
    lt.package_trail(SYM, "A", {"point_size": PS, "pv1_point": PV1},
                     TickPx(ar, ar + PS), Info())
    return hiv


_orig_msl = lt.modify_sl

# A csomag: 0,10@1,1000 + 0,07@1,1051 -> atlagar ~1,1021, ossz-kockazat 30,
# ossz-lot 0,17 -> a 20 R-es cel ~1,1374 (a 4b pont mar leellenorizte).
_avg2 = pb.average_price([(1.1000, 0.10), (1.1051, 0.07)])
_cel2 = pb.package_target(_avg2, "BUY", 30.0, 20.0, 0.17, PV1, PS)

h = kuszas(20.0, 0.0, 1.12, _avg2)
check("KUSZAS KI (pct=0): nincs SL-modositas", h == [], str(h))
h = kuszas(0.0, 0.5, 1.12, _avg2)
check("nincs CELAR: nincs kuszas (nincs mihez merni)", h == [], str(h))
h = kuszas(20.0, 0.5, _avg2 - 0.001, _avg2)
check("az ar meg az atlagar ALATT: nincs kuszas", h == [], str(h))

h = kuszas(20.0, 0.5, 1.12, _avg2)
_var2 = pb.package_trail_stop(_avg2, "BUY", 1.12, _cel2, 0.5, current_sl=_avg2)
check("KUSZAS: MINDKET lab UGYANAZT a stopot kapja",
      len(h) == 2 and h[0][1] == h[1][1], str(h))
check("KUSZAS: a stop a szamolt kuszo ertek",
      h and abs(h[0][1] - round(_var2, 5)) < 1e-5, f"{h[0][1] if h else '-'} vs {_var2:.5f}")
check("KUSZAS: a stop az atlagar FOLOTT (profitban)", h and h[0][1] > _avg2)

# ⚠ Ha a mostani stop mar szorosabb, NEM lazitunk vissza.
h = kuszas(20.0, 0.5, 1.12, _var2 + 0.002)
check("mar szorosabb stop -> NEM lazitunk vissza", h == [], str(h))

# ⚠ Hianyzo belepo-kockazat -> nincs kuszas (mint a celarnal)
h = kuszas(20.0, 0.5, 1.12, _avg2, riskek={1: 20.0})
check("hianyzo belepo-kockazat -> nincs kuszas", h == [], str(h))

# ⚠ EGYLEGES pozicio: a kuszas NEM nyul hozza (ott a BE/trailing a gazda)
h = kuszas(20.0, 0.5, 1.12, _avg2, labak=1)
check("egyleges pozicio -> a csomag-kuszas nem nyul hozza", h == [], str(h))

lt.modify_sl = _orig_msl

(lt.mt5, lt.open_position, lt.mt5_connector.modify_position_sltp,
 lt.get_strategy_by_name, lt.adopted.strategy_of, lt.adopted.tickets_for,
 lt.adopted.adopt, lt.position_meta.record, lt.position_meta.risk_of,
 lt._pos_risk_ccy_of, lt._bstate, lt._run_cfg) = _orig

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
