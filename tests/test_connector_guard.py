"""0032/1d: ŐR — a bróker-hívások CSAK a csatlakozón át.

A motor és a felület a bróker-semleges `core.connector`-t hívja; az MT5-
specifikus hívás egyetlen helye a `core/connector_mt5.py`. Ha egy új kód
közvetlenül `mt5.order_send(` / `mt5.positions_get(` / … hívna, egy második
bróker-típus (API) mellett NÉMÁN az MT5-öt érné el — ez az őr megfogja.

Kivétel (szándékos, dokumentált — Obsidian 0032):
  • `core/connector_mt5.py` — maga a megvalósítás;
  • `tools/` — offline eszközök (előzmény-letöltés, kutatás), nem a motor;
  • a KAPCSOLÓDÁS (`initialize/login/shutdown/account_info/terminal_info`)
    az `mt5_connector`-ban — az az MT5-csatlakozó belső dolga, nem ez az őr
    tiltja.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                          # noqa: E402
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


TILTOTT = ("order_send", "positions_get", "history_deals_get", "symbol_info",
           "symbol_info_tick", "copy_rates_from_pos", "order_calc_margin")
# csak a KÖZVETLEN `mt5.` (a felület `_mt5`-je a dashboard.mt5_view homlokzat,
# amely helyi módban a csatlakozót, külső módban a motort hívja — lásd lent)
minta = re.compile(r"(?<![\w.])mt5\.(" + "|".join(TILTOTT) + r")\(")
KIVETEL = {"core/connector_mt5.py"}

talalat = []
for mappa in ("core", "trading", "dashboard", "strategy", "strategies", "gates"):
    for p in (ROOT / mappa).rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel in KIVETEL:
            continue
        for i, sor in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            kod = sor.split("#", 1)[0]
            if minta.search(kod):
                talalat.append(f"{rel}:{i}: {sor.strip()[:90]}")
main = (ROOT / "main.py").read_text(encoding="utf-8").splitlines()
talalat += [f"main.py:{i}: {s.strip()[:90]}" for i, s in enumerate(main, 1)
            if minta.search(s.split("#", 1)[0])]

check("⚠ a motor/felület/stratégiák NEM hívnak közvetlenül MT5 bróker-műveletet",
      not talalat, "; ".join(talalat[:5]))
check("az őr valóban talál, ha van (nem néma)",
      bool(minta.search("x = mt5.positions_get()"))
      and not minta.search("_connector.get().positions()"))
# a felület `_mt5` neve MINDIG a homlokzat (dashboard.mt5_view)
rossz = []
for p in (ROOT / "dashboard").rglob("*.py"):
    for i, sor in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"\bas _mt5\b", sor) and "mt5_view" not in sor:
            rossz.append(f"{p.name}:{i}")
check("a felület `_mt5`-je mindenhol a dashboard.mt5_view homlokzat", not rossz, str(rossz))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
