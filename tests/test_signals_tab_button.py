"""A Jelzések fül „Kötés” gombjának HÁROM állapota.

⚠ A KÉRÉS (2026-09-02): „ha rányomtam a kötésre, akkor lehet jó lenne, ha
megváltozna a nyomógomb felirata Kötés-ről Kötve. (és inaktívvá kellene tenni.)
… Ugye nem jó, ha csak azt figyeljük, hogy megnyomtuk-e a gombot, mert lehet,
hogy itt, vagy lehet, hogy a telegrammon, és lehet, hogy manuálisan lett
megkötve.”

És: „ha látom, hogy két / három kötésünk is van, akkor simán az előzőeket is
érvényteleníthetjük. (Erre már csak egy felirat: lejárt.)” — a képen a Ger40 /
wpr_sma háromszor szerepelt (09:12, 08:39, 08:10).

A három állapot:

  Kötés   — a jelzés él, nincs pozíció → a gomb AKTÍV
  Kötve   — van nyitott pozíció ezen a páron ezzel a stratégiával → PASSZÍV
  Lejárt  — túlhaladta egy frissebb jelzés, VAGY régebbi a `max_age`-nél

⚠ A GOMBNYOMÁS MEGJEGYZÉSE NEM ELÉG, ezt a teszt ki is mondja: az állapot a
NYITOTT POZÍCIÓBÓL jön, tehát a Telegramról vagy kézzel az MT5-ben nyitott
pozíció is „Kötve”-t ad — a gombhoz hozzá sem kellett nyúlni.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core.i18n import t as _t
from dashboard.signals_tab import SignalsTab

# ── 1. A túlhaladás-jelölés (tiszta függvény, Tk nélkül) ──────────────────
# A képen látott valódi lista, a legfrissebbel kezdve.
SOROK = [
    {"time": "2026-09-02T09:25", "symbol": "EURCHF", "strategy": "trend_pullback",
     "direction": "BUY"},
    {"time": "2026-09-02T09:14", "symbol": "Usa500", "strategy": "wpr_sma",
     "direction": "SELL"},
    {"time": "2026-09-02T09:12", "symbol": "Ger40", "strategy": "wpr_sma",
     "direction": "SELL"},
    {"time": "2026-09-02T08:39", "symbol": "Ger40", "strategy": "wpr_sma",
     "direction": "SELL"},
    {"time": "2026-09-02T08:19", "symbol": "Usa500", "strategy": "wpr_sma",
     "direction": "SELL"},
    {"time": "2026-09-02T08:10", "symbol": "Ger40", "strategy": "wpr_sma",
     "direction": "SELL"},
]
SignalsTab._tulhaladt_jeloles(SOROK)
_t_map = {r["time"]: r["_tulhaladt"] for r in SOROK}

check("a legfrissebb Ger40 jelzés ÉL", _t_map["2026-09-02T09:12"] is False)
check("a 08:39-es Ger40 túlhaladt", _t_map["2026-09-02T08:39"] is True)
check("a 08:10-es Ger40 túlhaladt", _t_map["2026-09-02T08:10"] is True)
check("a legfrissebb Usa500 jelzés ÉL", _t_map["2026-09-02T09:14"] is False)
check("a 08:19-es Usa500 túlhaladt", _t_map["2026-09-02T08:19"] is True)
check("az egyetlen EURCHF jelzés ÉL", _t_map["2026-09-02T09:25"] is False)
check("pontosan 3 sor lett túlhaladt",
      sum(1 for r in SOROK if r["_tulhaladt"]) == 3)

# ⚠ A KULCS A PÁR + STRATÉGIA — nem az irány. Egy frissebb ELLENIRÁNYÚ jelzés
# a régit még inkább érvényteleníti.
_ellen = [{"time": "2026-09-02T10:00", "symbol": "Ger40", "strategy": "wpr_sma",
           "direction": "BUY"},
          {"time": "2026-09-02T09:00", "symbol": "Ger40", "strategy": "wpr_sma",
           "direction": "SELL"}]
SignalsTab._tulhaladt_jeloles(_ellen)
check("az ellenirányú friss jelzés is érvényteleníti a régit",
      _ellen[1]["_tulhaladt"] is True and _ellen[0]["_tulhaladt"] is False)

# ⚠ Ugyanaz a pár MÁS stratégiával külön szetup — nem üti egymást.
_ketstrat = [{"time": "2026-09-02T10:00", "symbol": "Ger40", "strategy": "a",
              "direction": "BUY"},
             {"time": "2026-09-02T09:00", "symbol": "Ger40", "strategy": "b",
              "direction": "BUY"}]
SignalsTab._tulhaladt_jeloles(_ketstrat)
check("a másik stratégia jelzését NEM üti ki",
      not any(r["_tulhaladt"] for r in _ketstrat))

# ── 2. A gomb felirata és állapota (Tk) ───────────────────────────────────
try:
    import tkinter as tk
    _probe = tk.Tk()
    _probe.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs használható tkinter ({type(e).__name__}: {e})")

if TK_OK:
    import tkinter as tk
    from datetime import datetime, timedelta, timezone

    def _ujjelzes(perc_kora=1, **extra):
        t = datetime.now(timezone.utc) - timedelta(minutes=perc_kora)
        r = {"time": t.isoformat(), "symbol": "Ger40", "strategy": "wpr_sma",
             "direction": "SELL", "price": 25816.0, "sl": 25844.0,
             "tp": 25760.0, "lot": 0.25}
        r.update(extra)
        return r

    def _allapot(sor, nyitott=None, max_ora=4.0):
        """A gomb (felirat, state) egy adott soron — igazi Tk-gombbal."""
        gyoker = tk.Tk()
        gyoker.withdraw()
        try:
            keret = tk.Frame(gyoker)
            tab = SignalsTab.__new__(SignalsTab)      # UI-építés nélkül
            tab._max_age = lambda: max_ora
            tab._open_of = (lambda s, st: nyitott)
            gomb = tk.Button(keret, text="?")
            tab._sor_frissit(sor, None, gomb)
            return gomb.cget("text"), str(gomb.cget("state"))
        finally:
            gyoker.destroy()

    _sz, _st = _allapot(_ujjelzes())
    check("friss jelzés, nincs pozíció → „Kötés”, aktív",
          _sz == _t("signals.trade") and _st == "normal", f"{_sz}/{_st}")

    _sz, _st = _allapot(_ujjelzes(), nyitott="SELL")
    check("van nyitott pozíció → „Kötve”, passzív",
          _sz == _t("signals.traded") and _st == "disabled", f"{_sz}/{_st}")

    # ⚠ EZ A LÉNYEG: a pozíció jöhetett a Telegramról vagy kézzel az MT5-ből.
    # A gombhoz hozzá sem nyúltunk, mégis „Kötve”.
    check("a „Kötve” NEM a gombnyomásból jön (Telegram / kézi MT5 is ilyen)",
          _allapot(_ujjelzes(), nyitott="BUY")[0] == _t("signals.traded"))

    _sz, _st = _allapot(_ujjelzes(_tulhaladt=True))
    check("túlhaladt jelzés → „Lejárt”, passzív",
          _sz == _t("signals.expired") and _st == "disabled", f"{_sz}/{_st}")

    _sz, _st = _allapot(_ujjelzes(perc_kora=5 * 60))
    check("a max_age-nél régebbi → „Lejárt”, passzív",
          _sz == _t("signals.expired") and _st == "disabled", f"{_sz}/{_st}")

    # ⚠ A SORREND: ha van pozíció, azt kell látni — akkor is, ha közben elévült.
    _sz, _st = _allapot(_ujjelzes(perc_kora=5 * 60), nyitott="SELL")
    check("pozíció + elévült jelzés → a „Kötve” nyer",
          _sz == _t("signals.traded"), _sz)

    # ⚠ A LEKÉRDEZÉS HIBÁJA NE ÁLLÍTSON SEMMIT: ha az MT5 épp elérhetetlen, a
    # „Kötve” azt hazudná, hogy van pozíciód.
    def _robban(sym, strat):
        raise RuntimeError("nincs MT5-kapcsolat")

    gyoker = tk.Tk()
    gyoker.withdraw()
    try:
        tab = SignalsTab.__new__(SignalsTab)
        tab._max_age = lambda: 4.0
        tab._open_of = _robban
        gomb = tk.Button(tk.Frame(gyoker), text="?")
        tab._sor_frissit(_ujjelzes(), None, gomb)
        check("az `open_of` hibája nem tesz „Kötve”-t (és nem is dob)",
              gomb.cget("text") == _t("signals.trade"))
    except Exception as ex:
        check("az `open_of` hibája nem tesz „Kötve”-t (és nem is dob)", False,
              f"{type(ex).__name__}: {ex}")
    finally:
        gyoker.destroy()

# ── 3. SIKERNÉL NINCS ABLAK ───────────────────────────────────────────────
# ⚠ A KÉRÉS (2026-09-02): „nem kell külön megnyitva figyelmeztetés ablak. (A
# kötve státuszból látszik, hogy megnyitva!)" A HIBA-ablak marad: ha a kötés
# nem ment ki, azt ki KELL mondani — a gomb ott „Kötés" marad, ami önmagában
# nem magyarázza meg, miért.
_st_src = (ROOT / "dashboard" / "signals_tab.py").read_text(encoding="utf-8")
check("sikeres kötésnél nincs visszaigazoló ablak",
      "showinfo" not in _st_src)
check("...de a SIKERTELEN kötés továbbra is szól", "showerror" in _st_src)

# ⚠ A VISSZAJELZÉS MOST A GOMB — ezért a pozíció-cache-t a ticket után AZONNAL
# frissíteni kell. Enélkül a gomb a háttérszál következő köréig (5 mp) „Kötés"
# maradna egy megnyitott pozíció mellett: pont a duplakattintás ablaka, és
# most nincs dialógus, ami feltartaná a kezet.
_gui_src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_ticket_ag = _gui_src.split("if ticket:", 1)[1].split("return ticket", 1)[0]
check("a ticket után azonnal frissül a pozíció-cache",
      "_signal_positions_refresh()" in _ticket_ag)
check("a cache-frissítő létezik",
      "def _signal_positions_refresh" in _gui_src)
# ⚠ ...és nem dobhat: a ticket UTÁN vagyunk, a pozíció NYITVA van.
_frissito = _gui_src.split("def _signal_positions_refresh", 1)[1].split(
    "\n    def ", 1)[0]
check("a cache-frissítő nem dobhat kivételt a nyitott pozíció után",
      "except Exception:" in _frissito)

# ── 3. A feliratok mindkét nyelven megvannak ──────────────────────────────
import json

for _nyelv in ("hu", "en"):
    _kat = json.loads((ROOT / "lang" / (_nyelv + ".json")).read_text(encoding="utf-8"))
    for _k in ("signals.trade", "signals.traded", "signals.expired"):
        check(f"{_nyelv}: van „{_k}” felirat", bool(_kat.get(_k)))
    check(f"{_nyelv}: a három felirat KÜLÖNBÖZŐ",
          len({_kat.get("signals.trade"), _kat.get("signals.traded"),
               _kat.get("signals.expired")}) == 3)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
