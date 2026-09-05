"""AZ `enabled` ES A `run_state` KET KULON DOLOG — es nem szabad osszemosni.

⚠ MI TORTENT (2026-09-05). A `wpr_sma` referencia-alapvonal lett: 12 paron
`stopped`, de ENGEDELYEZVE marad, hogy hangolhato es backtestelheto legyen.
A `set_state` viszont igy zart:

    pc["enabled"] = any(v == LIVE for v in rs.values())

vagyis az UTOLSO strategia leallitasa a PART is kikapcsolta. Kilenc helyen
szurnek az `enabled`-re — koztuk a `run_optimizer`, a `download_history` es a
`download_ticks` —, tehat EGYETLEN Play/Stop-nyomas utan a par nemán kiesett
volna a hangolasbol ES az adat-frissitesbol. Az alapvonal elavult volna,
anelkul hogy barki csinalt volna valamit.

Eddig ezt egy VELETLEN takarta: a nem engedelyezett strategiak elavult `live`
bejegyzesei tartottak eletben az `enabled`-et. Amint azok kikerultek, a csapda
elesedett.

A KET JELENTES:
    enabled    = a par JATEKBAN van (adat, backteszt, hangolas, megjelenites)
    run_state  = kereskedunk-e vele MOST

A motor amugy is a kettő SZORZATAVAL dolgozik (`_enabled & _intent`).
"""
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

from core import run_state as rs  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def _cfg():
    return {"pairs": {
        "GOLD": {"enabled": True, "strategies": ["wpr_sma"],
                 "run_state": {"wpr_sma": "stopped"}},
        "UsaTec": {"enabled": True, "strategies": ["wpr_sma", "trend_pullback"],
                   "run_state": {"wpr_sma": "stopped", "trend_pullback": "live"}},
        "KI": {"enabled": False, "strategies": ["wpr_sma"], "run_state": {}},
    }}


# ── 1. A CSAPDA REPRODUKALASA: leallitas NEM kapcsolhatja ki a part ──────
c = _cfg()
rs.set_state(c, "GOLD", "wpr_sma", "stopped")
check("az UTOLSO strategia leallitasa NEM kapcsolja ki a part",
      c["pairs"]["GOLD"]["enabled"] is True, str(c["pairs"]["GOLD"]))

c = _cfg()
rs.set_state(c, "UsaTec", "trend_pullback", "stopped")
check("...akkor sem, ha ezzel MINDEN strategia stopped lett",
      c["pairs"]["UsaTec"]["enabled"] is True,
      str(c["pairs"]["UsaTec"]["run_state"]))

# ⚠ EZ A LENYEG: a par maradjon az optimalizalando/letoltendo listaban.
c = _cfg()
rs.set_state(c, "GOLD", "wpr_sma", "stopped")
_ap = {s for s, p in c["pairs"].items() if isinstance(p, dict) and p.get("enabled", False)}
check("...es igy BENNE MARAD az `enabled`-re szuro listakban (hangolas, adat)",
      "GOLD" in _ap, str(sorted(_ap)))


# ── 2. FELFELE viszont szinkronizal ──────────────────────────────────────
c = _cfg()
rs.set_state(c, "KI", "wpr_sma", "live")
check("`live`-ra allitas BEKAPCSOLJA a part (felfele szinkron megmarad)",
      c["pairs"]["KI"]["enabled"] is True)


# ── 3. A SZANDEK maga valtozatlanul mukodik ──────────────────────────────
c = _cfg()
rs.set_state(c, "GOLD", "wpr_sma", "live")
check("a szandek atall live-ra", rs.get_state(c, "GOLD", "wpr_sma") == "live")
rs.set_state(c, "GOLD", "wpr_sma", "stopped")
check("...es vissza stopped-ra", rs.get_state(c, "GOLD", "wpr_sma") == "stopped")
check("a leallitott strategia NEM szerepel a live listaban",
      rs.live_strategies(c, "GOLD", ["wpr_sma"]) == [])
check("a live strategia IGEN",
      rs.live_strategies(_cfg(), "UsaTec", ["wpr_sma", "trend_pullback"])
      == ["trend_pullback"])


# ── 4. A REGI KEPLET NEM JOHET VISSZA ────────────────────────────────────
# ⚠ Ez a legfontosabb or: egy jovobeli „takaritas" konnyen visszateszi a
# tomor egysorost, mert ARTATLANNAK latszik.
_src = (ROOT / "core" / "run_state.py").read_text(encoding="utf-8")
_kod = "\n".join(l for l in _src.splitlines() if not l.strip().startswith("#"))
check("a `enabled = any(... LIVE ...)` egysoros NINCS a kodban",
      'pc["enabled"] = any(' not in _kod,
      "a leallitas nem szamolhatja ujra az enabled-et")
check("...es a felfele szinkron megvan", 'if state == LIVE:' in _kod)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
