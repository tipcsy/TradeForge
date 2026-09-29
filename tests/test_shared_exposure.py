"""0029/6b: közös kitettségi korlát minden számlán át.

Tibi döntése (2026-09-30): egy instrumentumon az ÖSSZES számlán egyszerre
legfeljebb N nyitott pozíció (alap 1) — ha az egyik brókeren már van GOLD,
a másik nem nyit. Lásd core/shared_exposure (a két szándékos szűkítés).
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

from core import shared_exposure as SE                          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


at = NS(id="act", tag="Act")
rob = NS(id="rob", tag="Rob")
xtb = NS(id="xtb", tag="Xtb")

# ── korlát ───────────────────────────────────────────────────────────────
check("alap: 1", SE.limit_of({}) == 1)
check("0 = kikapcsolva (szándékosan)", SE.limit_of({SE.KULCS: 0}) == 0)
check("hibás érték → az alap, nem a kikapcsolás", SE.limit_of({SE.KULCS: "sok"}) == 1)

# ── döntés ───────────────────────────────────────────────────────────────
check("⚠ egy brókernél NINCS korlát (viselkedés változatlan)",
      SE.decide("GOLD", 3, {"GOLD": 5}, 1, 1)[0] is True)
check("a másik számlán van GOLD → itt NEM nyit (N=1)",
      SE.decide("GOLD", 0, {"GOLD": 1}, 1, 2)[0] is False)
check("...és megmondja, miért", "közös korlát" in SE.decide("GOLD", 0, {"GOLD": 1}, 1, 2)[1])
check("⚠ csak a SAJÁT számlán van → a korlát nem hat (a házirend dönt)",
      SE.decide("GOLD", 2, {}, 1, 2)[0] is True)
check("más instrumentum nem számít", SE.decide("GOLD", 0, {"Ger40": 3}, 1, 2)[0] is True)
check("N=2: egy a másikon, itt még nyithat", SE.decide("GOLD", 0, {"GOLD": 1}, 2, 2)[0] is True)
check("N=2: egy ott + egy itt → nem", SE.decide("GOLD", 1, {"GOLD": 1}, 2, 2)[0] is False)
check("kikapcsolva (0) → mindig nyithat", SE.decide("GOLD", 0, {"GOLD": 9}, 0, 2)[0] is True)

# ── a többi számla képe ─────────────────────────────────────────────────
kepek = {
    "rob": {"positions_detail": [{"symbol": "GOLD"}, {"symbol": "GOLD"}, {"symbol": "EURUSD"}],
            "stopped": True, "ts": 0},              # ⚠ NEM fut, régi kép
    "xtb": {"positions_by_symbol": {"GOLD": {"count": 1}}},   # 5c előtti kép
}
masok, ismeretlen = SE.other_counts([at, rob, xtb], "act", lambda p: kepek.get(p.id))
check("⚠ a NEM futó motor utolsó képe is számít (a pozíciói nyitva vannak)",
      masok.get("GOLD", 0) >= 2, str(masok))
check("a régi (aggregált) képformátum is olvasható", masok.get("GOLD") == 3, str(masok))
check("a saját számla nem számít bele", SE.other_counts([at, rob], "rob",
      lambda p: kepek.get(p.id))[0] == {})
_, ism = SE.other_counts([at, rob, NS(id="ftmo", tag="Ftmo")], "act",
                         lambda p: kepek.get(p.id))
check("a SOSEM látott bróker jelezve (a hívó naplózza)", ism == ["Ftmo"], str(ism))

# ── a motor és a config-ellenőrzés bekötése ─────────────────────────────
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor a slot-keret ELŐTT ellenőriz",
      _lt.find("if not _shared_exposure_ok(trading_cfg, symbol, signal):")
      < _lt.find("            if not slot_mgr.can_open_risk(_risk_ccy):")
      and "_shared_exposure_ok(trading_cfg, symbol, signal)" in _lt)
check("⚠ egy brókernél a motor MT5-hívás nélkül visszatér",
      "if len(profs) <= 1:\n        return True" in _lt)

from core import config_check as CC                              # noqa: E402
cfg = {"brokers": [{"id": "act", "tag": "Act", "login": 1, "server": "a"},
                   {"id": "rob", "tag": "Rob", "login": 2, "server": "b"}],
       "trading": {},
       "pairs": {"GOLD": {"run_state": {"wpr_sma": "live"},
                          "brokers": {"rob": {"run_state": {"wpr_sma": "live"}}}},
                 "Ger40": {"run_state": {"wpr_sma": "live"}}}}
_out = []
CC._check_shared_instruments(cfg, _out)
check("figyelmeztet: GOLD/wpr_sma két brókeren is LIVE",
      len(_out) == 1 and _out[0]["symbol"] == "GOLD", str(_out))
_out1 = []
CC._check_shared_instruments({"pairs": cfg["pairs"], "broker": {"login": 1}}, _out1)
check("egy brókernél nincs ilyen figyelmeztetés", _out1 == [])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
