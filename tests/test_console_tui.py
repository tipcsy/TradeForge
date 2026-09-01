"""A táblázatos konzolos nézet (`--tui`) — MIT mutat, és honnan veszi.

⚠ MIÉRT EZ A KÉT KÉRDÉS. A TUI a `core.console_cmd` MÁSODIK megjelenítője.
A veszély nem a rajzolás csúnyasága, hanem hogy **saját lekérdezést** kezdjen
írni: onnantól két helyen kellene karbantartani ugyanazt a szabályt (mikor
„fut" egy stratégia, mikor „halad" a motor), és a kettő elcsúszna. Ugyanaz a
hibaosztály, mint a viz-sáv romlása és a warmup-mélység lelete.

⚠ AMIT NEM TESZTELÜNK: a billentyű-figyelést és a sorszerkesztést. Egy valódi
terminál viselkedését teszttel nem lehet hűen utánozni, ezért a `fut()` hurok
szándékosan VÉKONY, és minden eldönthető — hogy MI látszik — a tiszta `kep()`
függvényben van.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import io
import time

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import console_cmd as cc
from core import console_tui as tui

# ⚠ A `rich` NEM kötelező futásidejű függőség. Ha nincs telepítve, a teszt nem
# BUKIK, hanem kimarad — és az `elerheto()` pontosan ezt a döntést adja a
# hívónak is (nem egy elkapott importhibából derül ki).
if not tui.elerheto():
    print("      (nincs `rich` telepítve — a TUI-teszt kimarad)")
    print()
    print("0/0 teszt PASS")
    sys.exit(0)

from rich.console import Console


class _DS:
    def __init__(self, pnl=None):
        self.position_pnl = pnl


CFG = {
    "pairs": {
        "Ger40":  {"strategies": ["wpr_sma", "bollinger_squeeze"],
                   "run_state": {"wpr_sma": "live",
                                 "bollinger_squeeze": "stopped"}},
        "UsaTec": {"strategies": ["wpr_sma"], "run_state": {"wpr_sma": "live"}},
        "EURUSD": {"strategies": ["wpr_sma"], "run_state": {"wpr_sma": "stopped"}},
    },
    "strategy": {"name": "wpr_sma"},
}
POZ = [{"ticket": 111, "symbol": "Ger40", "type": "BUY", "volume": 0.1,
        "price_open": 23456.7, "sl": 23400.0, "tp": 23600.0, "profit": 12.3},
       {"ticket": 112, "symbol": "UsaTec", "type": "SELL", "volume": 0.2,
        "price_open": 29530.3, "sl": 29600.0, "tp": 29300.0, "profit": -4.8}]


def ctx_epit(poz=POZ, kor=3.0, mt5=True, szamla=True):
    return cc.Context(
        cfg=CFG,
        save_config=lambda: True,
        positions=lambda: list(poz),
        close_position=lambda t: True,
        account=(lambda: {"balance": 981.23, "currency": "EUR",
                          "daily_pnl": -12.5}) if szamla else dict,
        dashboard={"Ger40": _DS(12.3), "UsaTec": _DS(-4.8), "EURUSD": _DS(None)},
        instrument_state={"Ger40": "LIVE", "UsaTec": "CLOSING",
                          "EURUSD": "STOPPED"},
        strategies_of=lambda s: list(CFG["pairs"][s]["strategies"]),
        last_cycle_ts=lambda: time.time() - kor,
        mt5_ok=lambda: mt5,
        licence_status=lambda: {"allapot": "ok", "lejar_nap": 312},
    )


def rajzol(ctx, width=110, height=None) -> str:
    """A kép SZÖVEGKÉNT — így ellenőrizhető, mi látszik."""
    buf = io.StringIO()
    Console(file=buf, width=width, height=height or 60, force_terminal=False,
            no_color=True).print(tui.kep(ctx, height))
    return buf.getvalue()


def sok_par_ctx(n=15, n_poz=3):
    nev = [f"SYM{i:02d}" for i in range(n)]
    cfg = {"pairs": {x: {"strategies": ["wpr_sma"],
                         "run_state": {"wpr_sma": "live"}} for x in nev},
           "strategy": {"name": "wpr_sma"}}
    poz = [{"ticket": 100 + i, "symbol": nev[i], "type": "BUY", "volume": 0.1,
            "price_open": 100.0, "sl": 95.0, "tp": 110.0, "profit": 1.0}
           for i in range(min(n_poz, n))]
    return cc.Context(
        cfg=cfg, save_config=lambda: True, positions=lambda: poz,
        close_position=lambda t: True,
        account=lambda: {"balance": 981.0, "currency": "EUR", "daily_pnl": -1.0},
        dashboard={x: _DS(1.0) for x in nev},
        instrument_state={x: "LIVE" for x in nev},
        strategies_of=lambda s: ["wpr_sma"],
        last_cycle_ts=lambda: time.time() - 3,
        licence_status=lambda: {"allapot": "ok", "lejar_nap": 358})


ctx = ctx_epit()
kep = rajzol(ctx)

# ── 1. MI LÁTSZIK ─────────────────────────────────────────────────────────
from version import APP_VERSION
check("a fejlécben a verzió", APP_VERSION in kep)
check("...és az egyenleg + a mai eredmény",
      "981.23" in kep and "-12.50" in kep)
check("minden instrumentum látszik",
      all(s in kep for s in ("Ger40", "UsaTec", "EURUSD")))
check("...az állapotukkal", all(s in kep for s in ("LIVE", "CLOSING", "STOPPED")))
check("a nyitott pozíciók látszanak",
      "111" in kep and "112" in kep and "23456.7" in kep)
check("...SL/TP-vel együtt", "23400" in kep and "23600" in kep)
check("a motor életjele a fejlécben", "3 mp" in kep or "3 s" in kep, kep[:1] and "")

# ⚠ EGY ÜRES TÁBLA ÉS EGY „nincs pozíció" SOR NEM UGYANAZ: az üres tábla úgy
# néz ki, mintha a lekérdezés nem sikerült volna.
_ures = rajzol(ctx_epit(poz=[]))
check("⚠ pozíció nélkül KIÍRJA, hogy nincs (nem üres táblát mutat)",
      "Nincs nyitott" in _ures)

# ── 2. A FORRÁS: a közös lekérdezés, nem külön képlet ─────────────────────
# ⚠ EZ A TESZT LELKE. Ha a TUI a saját lekérdezését írná meg, a kép és a
# szöveges parancs ugyanarról a párról MÁST mondhatna.
import ast
_fa = ast.parse((ROOT / "core" / "console_tui.py").read_text(encoding="utf-8"))
_hivott = {n.func.attr for n in ast.walk(_fa)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check("⚠ a pár-sorokat a KÖZÖS `pair_rows` adja", "pair_rows" in _hivott)
check("⚠ a pozíciókat a KÖZÖS `position_rows`", "position_rows" in _hivott)
check("⚠ az életjelet a KÖZÖS `state_rows`", "state_rows" in _hivott)
# ...és a parancsok is onnan mennek — a TUI nem értelmez parancsot maga.
check("⚠ a parancsokat a KÖZÖS `dispatch` hajtja végre", "dispatch" in _hivott)
check("⚠ a TUI nem nyúl a confighoz és nem ír állapotot",
      "set_state" not in _hivott and "save_config" not in _hivott)

# A kép és a `pairs` parancs UGYANAZT mondja arról, mi fut.
_szoveg = "\n".join(cc.dispatch(ctx, "pairs").lines)
for _sym in ("Ger40", "UsaTec", "EURUSD"):
    _fut_szoveg = f"wpr_sma*" in [x for x in _szoveg.splitlines()
                                  if x.startswith(_sym)][0]
    _fut_sor = [r for r in cc.pair_rows(ctx) if r["symbol"] == _sym][0]
    _fut_tabla = any(f for _, f in _fut_sor["strategies"])
    check(f"{_sym}: a kép és a `pairs` parancs EGYET mond",
          _fut_szoveg == _fut_tabla)

# ── 3. A BAJ LÁTSZIK-E ────────────────────────────────────────────────────
# ⚠ Egy zöld pipa, ami nem néz semmit, rosszabb a semminél. Az ELMARADT kört és
# a hiányzó MT5-kapcsolatot a fejlécnek meg kell mutatnia — ez a fej nélküli
# futás EGYETLEN visszajelzése.
_beteg = rajzol(ctx_epit(kor=600.0, mt5=False))
check("⚠ az ELMARADT kör látszik a fejlécben", "600 mp" in _beteg or "600 s" in _beteg)
check("⚠ a hiányzó MT5-kapcsolat is", "NEM" in _beteg or "NO" in _beteg)

# Színnel is: az „igen"/„nem" nem csak szöveg, hanem zöld/piros.
_buf = io.StringIO()
Console(file=_buf, width=110, force_terminal=True).print(
    tui.kep(ctx_epit(kor=600.0, mt5=False)))
check("⚠ ...és SZÍNNEL kiemelve (nem csak szövegben)",
      "\x1b[" in _buf.getvalue())

# Számla-lekérdezés nélkül se legyen néma.
check("⚠ ha az egyenleg nem kérdezhető le, azt KIÍRJA",
      "nem kérdezhet" in rajzol(ctx_epit(szamla=False)))

# ── 4. Szűk terminál ──────────────────────────────────────────────────────
# ⚠ SSH-n gyakori a 80 oszlop. A fejléc korábban KÉT OSZLOPBAN állt, és ott
# betördelődött egymás alá — a kép összekuszálódott.
_szuk = rajzol(ctx, width=80)
check("80 oszlopon is olvasható marad",
      "Ger40" in _szuk and "981.23" in _szuk
      and max(len(l) for l in _szuk.splitlines()) <= 80,
      f"leghosszabb sor: {max(len(l) for l in _szuk.splitlines())}")

# ── 4b. A KÉP NEM LÓGHAT TÚL A KÉPERNYŐN ──────────────────────────────────
# ⚠ EZ A LEGFONTOSABB MÉRETSZABÁLY, és élesben derült ki. 15 instrumentumnál a
# kép magasabb lett a terminálnál; egy a képernyőnél magasabb élő területet a
# rich nem tud helyben frissíteni, ezért TÖRLI és ÚJRARAJZOLJA az egészet — a
# felhasználó ezt „ugrálásként" látta. A javítás: a magasság ismeretében
# levágjuk, ami nem fér ki.
for _n, _h in ((15, 24), (15, 30), (40, 24), (3, 24), (40, 60)):
    _sorok = rajzol(sok_par_ctx(_n), width=100,
                    height=_h).rstrip(chr(10)).split(chr(10))
    check(f"⚠ {_n} pár / {_h} soros terminál: a kép BELEFÉR",
          len(_sorok) <= _h, f"{len(_sorok)} sor")

# ...és ami lemaradt, arról SZÓL — nem csendben tűnik el.
_vagott = rajzol(sok_par_ctx(40), width=100, height=24)
check("⚠ a levágott instrumentumok száma KI VAN ÍRVA",
      "még" in _vagott or "more" in _vagott, "")

# ⚠ A POZÍCIÓ AZ ELSŐBB: abban valódi pénz van, a pár-lista a `pairs`
# paranccsal bármikor teljesen kilistázható.
_szuk_h = rajzol(sok_par_ctx(40, n_poz=3), width=100, height=24)
check("⚠ szűk képernyőn is MINDEN nyitott pozíció látszik",
      all(f"10{i}" in _szuk_h for i in range(3)))

# Magasság nélkül (pl. napló, teszt) a régi viselkedés: nincs vágás.
check("magasság nélkül nincs vágás",
      all(f"SYM{i:02d}" in rajzol(sok_par_ctx(15), width=100) for i in range(15)))

# ── 4c. A HUROK: miért nem ugrál ──────────────────────────────────────────
# ⚠ A `fut()` egy valódi terminált vezérel — azt teszttel nem lehet hűen
# utánozni. Amit viszont ELLENŐRIZHETÜNK: a három beállítás, ami a villogást és
# az akadozást megszünteti, tényleg ott van.
_tui_src = (ROOT / "core" / "console_tui.py").read_text(encoding="utf-8")
check("⚠ KÜLÖN képernyő-puffer (`screen=True`) — nem a görgethető kimenetbe rajzol",
      "screen=True" in _tui_src)
check("⚠ a frissítés KÉZI (`auto_refresh=False`) — változatlan tartalmat nem rajzol újra",
      "auto_refresh=False" in _tui_src)
check("⚠ a kép a terminál MAGASSÁGÁVAL rajzolódik",
      "kep(ctx, con.size.height)" in _tui_src)
# ⚠ A billentyű-figyelés SŰRŰBB, mint a rajzolás: korábban egy ütemen mentek,
# és a leütésre akár 2 másodpercet kellett várni — ami elakadásnak látszott.
import re as _re
_poll = _re.search(r"time\.sleep\(([\d.]+)\)", _tui_src)
check("⚠ a billentyűre sűrűbben figyel, mint ahogy rajzol",
      _poll and float(_poll.group(1)) < tui.FRISSITES_MP,
      f"{_poll.group(1) if _poll else '?'} mp vs {tui.FRISSITES_MP} mp")

# ⚠ EGY KÉPHEZ EGY LEKÉRDEZÉS. A pozíció-lista az MT5-ből jön (és pozíciónként
# egy `symbol_info`-t is kér); ha a sor-keret számítása és a rajzolás külön
# kérdezné le, minden kép KÉTSZER terhelné a terminált. A kijelzés-út ebben a
# projektben már okozott GIL-fogást (7,64 → 0,31 mp/kör).
_hivas = {"par": 0, "poz": 0}
_c = sok_par_ctx(15)
_eredeti_poz = _c.positions
_c.positions = lambda: (_hivas.__setitem__("poz", _hivas["poz"] + 1)
                        or _eredeti_poz())
_eredeti_str = _c.strategies_of
_c.strategies_of = lambda s: (_hivas.__setitem__("par", _hivas["par"] + 1)
                              or _eredeti_str(s))
rajzol(_c, width=100, height=30)
check("⚠ egy képhez EGYSZER kérdezzük le a pozíciókat", _hivas["poz"] == 1,
      f"{_hivas['poz']} lekérdezés")
check("⚠ ...és a pár-listát is (nem instrumentumonként kétszer)",
      _hivas["par"] == 15, f"{_hivas['par']} hívás 15 párra")

# ── 5. A katalógus ────────────────────────────────────────────────────────
import json
_hu = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
_en = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
_tk = [k for k in _hu if k.startswith("console.tui.")]
check("vannak `console.tui.*` kulcsok", len(_tk) >= 10, f"{len(_tk)}")
check("⚠ mind le van fordítva angolra",
      not [k for k in _tk if k not in _en])

from core import i18n as _i18n
_i18n.set_language("en")
_ang = rajzol(ctx)
_i18n.set_language("hu")
check("⚠ angol nyelven ANGOL fejlécek (a nézet is a katalógusból él)",
      "Instrument" in _ang and "Strategies" in _ang and "State" in _ang)

# ── 6. A `rich` NEM kötelező ──────────────────────────────────────────────
# ⚠ Egy hiányzó megjelenítő-csomag nem állíthatja meg a KERESKEDÉST. A hívó az
# `elerheto()`-ből dönt, és a parancssoros mód megy tovább.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("⚠ a `--tui` az `elerheto()`-t kérdezi (nem importhibát kap el)",
      "console_tui.elerheto()" in _main)
check("⚠ ...és hiányzó `rich`-nél a parancssor MEGY TOVÁBB",
      "console.tui.missing" in _main)
check("a `rich` a requirements.txt-ben van",
      "rich>=" in (ROOT / "requirements.txt").read_text(encoding="utf-8"))
# A modul betölthető `rich` nélkül is: a rajzoló importok a FÜGGVÉNYEKBEN vannak.
_tfa = ast.parse((ROOT / "core" / "console_tui.py").read_text(encoding="utf-8"))
_modul_szintu = []
for n in _tfa.body:
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        _modul_szintu += [getattr(n, "module", "") or ""] + [a.name for a in n.names]
check("⚠ a `rich` NEM modul-szintű import (különben a modul se töltődne be)",
      not [m for m in _modul_szintu if "rich" in str(m)])

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
