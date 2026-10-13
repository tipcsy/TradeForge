"""Instrumentum-ablak mentése: nincs maradék „market” hivatkozás (2026-10-13).

Tibi: új instrumentum (BRENT), csilla bekapcsolva, Mentés → „Mentési hiba:
'market'". A Piac-előszűrő sora 2026-10-12-én kikerült az ablakból (a Piac-KAPU
beállítása lett), de a mentés utáni visszajelzés még `now["market"]`-ot olvasott:
KeyError — a config ADDIGRA már kiíródott, a felület mégis hibát mutatott.

Az ablak felépítése MT5-öt és élő állapotot kér, ezért itt a FORRÁST nézzük: az
ablak állapot-szótárai (`_init`, `now`, `cur_vals`) nem kérhetnek olyan kulcsot,
amit már senki nem tölt.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
kod = "\n".join(l.split("#", 1)[0] for l in src.splitlines())   # kommentek nélkül
for nev in ("now", "cur_vals", "_init"):
    talalat = re.findall(rf'\b{nev}\[\s*["\'](market|market_viz)["\']\s*\]', kod)
    check(f"`{nev}[\"market…\"]` nem olvasódik", not talalat, talalat)

from core import bulk_apply as ba                                # noqa: E402
check("a tömeges sorok között sincs piac-sor",
      "market" not in ba.ROWS and "market_viz" not in ba.ROWS)

from core import i18n                                            # noqa: E402
_txt = i18n.t("gui.bulk.saved_one", names="wpr_sma, csilla")
check("a mentés-visszajelzés `market` nélkül is kitölthető", "wpr_sma" in _txt and "{" not in _txt,
      _txt)

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
