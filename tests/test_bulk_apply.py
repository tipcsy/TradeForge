"""„Minden instrumentumra": MELYIK beallitas terjed szet.

Keres: az instrumentum-beallitasoknal lehessen egyszerre minden parra alkalmazni.

A veszely nem a funkcioban van, hanem a naiv megvalositasban: ha a pipa az ablak
TELJES allapotat masolja, akkor aki csak a vizualizacios pipat akarja mindenhova,
annak a KOTES-MODJA is ratodik minden parra -- egyetlen kattintas valodi
megbizasokat kapcsolhat be 10 instrumentumon.

Ezert a szabaly: csak a TENYLEGESEN MEGVALTOZTATOTT sorok terjednek. Ez a teszt
ezt a szabalyt orzi.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()   # a cp1250 konzol elszall a figyelmezteto jelen

from core import bulk_apply as ba

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def snap(**kw):
    """Ablak-pillanatkep alapertekekkel; a kw felulirja."""
    base = {"strategies": ["wpr_sma"],
            "viz":    {"wpr_sma": True,  "ml_ai": True},
            "trades": {"wpr_sma": True,  "ml_ai": True},
            "mode":   {"wpr_sma": "live", "ml_ai": "signal"},
            "market": "Nincs",
            "market_viz": True}
    base.update(kw)
    return base


# ══ 1. Valtozas nelkul semmi nem terjed ═══════════════════════════════════
check("azonos pillanatkep -> nincs terjedo sor",
      ba.changed_rows(snap(), snap()) == set())

# ══ 2. A LENYEG: csak a MEGVALTOZTATOTT sor terjed ═══════════════════════
only_viz = ba.changed_rows(snap(), snap(viz={"wpr_sma": False, "ml_ai": True}))
check("csak a viz valtozott -> csak az terjed", only_viz == {"viz"}, str(only_viz))
check("...a KOTES-MOD NEM terjed vele", "mode" not in only_viz)
check("...es a strategia-lista sem", "strategies" not in only_viz)

# Ez a bejelentes magja: a viz-pipa atallitasa NEM nyulhat a penzhez.
check("a csak-viz valtozas NEM erint penzt", ba.affects_money(only_viz) is False)

# ══ 3. Tobb sor egyszerre ════════════════════════════════════════════════
multi = ba.changed_rows(snap(), snap(viz={"wpr_sma": False, "ml_ai": True},
                                     market="regime_adx"))
check("ket sor valtozott -> mindketto terjed", multi == {"viz", "market"}, str(multi))

# ══ 4. Penzt erinto sorok ════════════════════════════════════════════════
mode_ch = ba.changed_rows(snap(), snap(mode={"wpr_sma": "live", "ml_ai": "live"}))
check("kotes-mod valtozas -> PENZT ERINT",
      mode_ch == {"mode"} and ba.affects_money(mode_ch))
strat_ch = ba.changed_rows(snap(), snap(strategies=["wpr_sma", "ml_ai"]))
check("strategia bekapcsolasa -> PENZT ERINT",
      strat_ch == {"strategies"} and ba.affects_money(strat_ch))
check("a megjelenitesi sorok NEM erintenek penzt",
      ba.affects_money({"viz", "trades", "market_viz"}) is False)
check("vegyes halmaz -> penzt erint (eleg egy)",
      ba.affects_money({"viz", "mode"}) is True)
check("ures halmaz -> nem erint penzt", ba.affects_money(set()) is False)

# ══ 5. Ismeretlen kulcs NEM terjed ═══════════════════════════════════════
# Egy jovobeli segedmezo, ami veletlenul a pillanatkepbe kerul, ne kerüljön
# nemán az osszes instrumentumra.
a = snap(); b = snap()
a["_belso_segedmezo"] = 1
b["_belso_segedmezo"] = 2
check("ismeretlen kulcs valtozasa NEM terjed",
      ba.changed_rows(a, b) == set(), str(ba.changed_rows(a, b)))

# Hianyzo kulcs egyik oldalon -> szinten nem terjed (nem talalgatunk)
c = snap(); del c["market"]
check("felig hianyzo kulcs -> nem terjed", "market" not in ba.changed_rows(c, snap()))

# ══ 6. Cel-instrumentumok ════════════════════════════════════════════════
PAIRS = {"GOLD": {}, "Ger40": {}, "EURUSD": {"enabled": False}, "rossz": "nem dict"}
t1 = ba.targets(PAIRS, "GOLD", False)
check("apply_all=False -> csak a sajatja", t1 == ["GOLD"], str(t1))
t2 = ba.targets(PAIRS, "GOLD", True)
check("apply_all=True -> a sajatja ELSOKENT", t2[0] == "GOLD", str(t2))
check("...a tobbi rendezve", t2[1:] == ["EURUSD", "Ger40"], str(t2))
check("a LETILTOTT par is celpont (backteszt/kesobbi elesites is hasznalja)",
      "EURUSD" in t2)
check("a nem-dict bejegyzes kimarad", "rossz" not in t2)
check("ures pairs -> csak a sajatja", ba.targets({}, "X", True) == ["X"])
check("None pairs -> nem robban", ba.targets(None, "X", True) == ["X"])

# ══ 7. Az osszefoglalo szoveg ════════════════════════════════════════════
s = ba.summary({"mode", "viz"})
check("az osszefoglalo megjeloli a penzt erintot", "PÉNZT ÉRINT" in s, s.replace("\n", " | "))
check("...es a megjelenitesit nem",
      "PÉNZT ÉRINT" not in ba.summary({"viz", "trades"}))
check("determinisztikus sorrend", ba.summary({"viz", "mode"}) == ba.summary({"mode", "viz"}))
check("ures halmaz -> ures szoveg", ba.summary(set()) == "")
check("minden sornak van emberi neve",
      all(ba.label_of(k) and ba.label_of(k) != k for k in ba.ROWS))

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
