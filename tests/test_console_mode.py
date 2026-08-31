"""Konzolos (fej nélküli) futás: futás-zár + közös parancs-réteg.

⚠ MIÉRT VAN ERRE SZÜKSÉG. A felhasználó gyenge gépen (VM) is futtatná a
motort, felület nélkül. A szétválasztás nagyrészt megvolt — a motor saját
szálban fut, és a felület modul-szintű szótárakból olvas —, de KÉT dolog
hiányzott, és mindkettő némán romlana el:

  1. **Futás-zár.** A licenc a BRÓKERSZÁMLÁHOZ kötődik, nem a géphez: két
     processz ugyanazon a gépen, ugyanazzal a számlával MINDKETTŐ átmegy a
     licenc-kapun, és mindkettő kereskedik. Az optimalizálóval ez már meg is
     történt élesben (2026-08-04) — ott elrontott mérés lett belőle, itt dupla
     kötés lenne.
  2. **Egy parancs-réteg, nem három.** A konzol, a TUI és a Telegram ugyanazt a
     hat műveletet kínálja. Külön megírva három forrás romlana el külön — ez a
     projekt visszatérő hibaosztálya.

⚠ A teszt MT5 NÉLKÜL fut: a `console_cmd.Context` minden külső hatást hívható
függvényként kap, tehát egy szótárral és néhány lambdával lejátszható.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import os
import tempfile

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import console_cmd as cc
from core import live_lock

# ── 1. FUTÁS-ZÁR ──────────────────────────────────────────────────────────
# ⚠ A zár a valódi `data/` mappába írna; a teszt SOHA nem nyúlhat a felhasználó
# állapotához (ez a projektben már háromszor megtörtént), ezért ideiglenes
# könyvtárba irányítjuk.
_tmp = Path(tempfile.mkdtemp(prefix="tf_lock_"))
live_lock.DIR = _tmp

SZAMLA = "1234567"
ok1, akadaly1 = live_lock.acquire(SZAMLA, note="teszt")
check("a zár megszerezhető", ok1 and akadaly1 is None)
check("...és a fájl a SZÁMLA nevét viseli",
      live_lock.lock_path(SZAMLA).name == f"live_{SZAMLA}.lock",
      live_lock.lock_path(SZAMLA).name)
check("a saját zárunkba nem akadunk bele (újrahívás)",
      live_lock.acquire(SZAMLA)[0])
check("a zár ÉL", live_lock.is_held(SZAMLA))

# ⚠ MÁS SZÁMLA SZABADON FUT. Egy demó és egy éles számla egyszerre teljesen
# szabályos — a tiltás csak UGYANARRA a számlára szól.
check("⚠ MÁS számlán szabad futni", live_lock.acquire("9999999")[0])

# Idegen (élő) processz zára → elutasítás, és MEGMONDJA, hol fut a másik.
import json
_idegen = {"pid": 1, "host": "masik-gep", "started_at": 0.0,
           "cmd": "main.py console", "version": "9.9.9"}
live_lock.lock_path("777").write_text(json.dumps(_idegen), encoding="utf-8")
_elt = live_lock._pid_alive
live_lock._pid_alive = lambda pid: True          # „a másik processz él"
ok2, akadaly2 = live_lock.acquire("777")
check("⚠ IDEGEN, élő zárnál NEM indul", not ok2)
_leiras = live_lock.describe(akadaly2 or {})
check("...és megmondja, HOL fut a másik",
      "masik-gep" in _leiras and "pid 1" in _leiras, _leiras)

# Elárvult zár (halott pid) ÁTVEHETŐ — különben egy összeomlás után soha
# többé nem indulna el a program, és a felhasználó egy fájlt keresne.
live_lock._pid_alive = lambda pid: pid == os.getpid()
check("⚠ ELÁRVULT zár átvehető", live_lock.acquire("777")[0])
live_lock._pid_alive = _elt

check("idegen zárat NEM törlünk",
      live_lock.release(SZAMLA) and not live_lock.release("nincs_ilyen"))

# ⚠ A ZÁR VÉDELEM, NEM FELTÉTEL: ha nem sikerül KIÍRNI, az indulás nem áll le
# (egy írásvédett mappa miatt ne maradjon menedzsment nélkül egy pozíció) — de
# a hiányzó fájl a hívónak JELZI, hogy a védelem elveszett.
live_lock.DIR = _tmp / "nem_letezo" / "melyen"
_eredeti_mkdir = Path.mkdir
def _bukik(self, *a, **kw):
    raise OSError("teszt: nem írható")
Path.mkdir = _bukik
try:
    _ok3, _ = live_lock.acquire("555")
    check("⚠ írhatatlan mappánál is ELINDUL (a zár nem feltétel)", _ok3)
    check("⚠ ...de a zár-fájl HIÁNYA jelzi, hogy nincs védelem",
          not live_lock.lock_path("555").exists())
finally:
    Path.mkdir = _eredeti_mkdir
    live_lock.DIR = _tmp

# A hívó (main.py console) pontosan ezt a hiányt nézi, és szól róla.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("⚠ a konzolos indítás JELZI a védtelen futást",
      "console.lock.unprotected" in _main
      and "lock_path(_szamla).exists()" in _main)


# ── 2. A PARANCS-RÉTEG ────────────────────────────────────────────────────
class _DS:
    """A `PairDashboardState` egyetlen mezője, ami minket érdekel."""
    def __init__(self, pnl=None):
        self.position_pnl = pnl


def ctx_epit(poz=None, pnl=None, mentes=True):
    cfg = {
        "pairs": {
            "Ger40": {"point_size": 0.01, "enabled": True,
                      "strategies": ["wpr_sma", "bollinger_squeeze"],
                      "run_state": {"wpr_sma": "live",
                                    "bollinger_squeeze": "live"}},
            "EURUSD": {"point_size": 0.00001, "enabled": False,
                       "strategies": ["wpr_sma"],
                       "run_state": {"wpr_sma": "stopped"}},
        },
        "strategy": {"name": "wpr_sma"},
    }
    zart = []
    return cfg, zart, cc.Context(
        cfg=cfg,
        save_config=lambda: mentes,
        positions=lambda: list(poz or []),
        close_position=lambda t: (zart.append(t) or True),
        account=lambda: {"balance": 1000.0, "currency": "EUR", "daily_pnl": -12.5},
        dashboard={"Ger40": _DS(pnl)},
        instrument_state={"Ger40": "LIVE", "EURUSD": "STOPPED"},
        strategies_of=lambda s: list((cfg["pairs"].get(s) or {}).get("strategies") or []),
        engine_alive=lambda: True,
        last_cycle_ts=lambda: __import__("time").time(),
    )


cfg, zart, ctx = ctx_epit()

# ── help / ismeretlen ──
check("a `help` felsorolja a parancsokat",
      len(cc.dispatch(ctx, "help").lines) >= len(cc.COMMANDS))
_r = cc.dispatch(ctx, "nincsilyen")
check("⚠ ismeretlen parancsnál SEGÍT, nem hallgat",
      not _r.ok and bool(_r.lines) and "nincsilyen" in _r.lines[0])
check("üres sor nem hiba", cc.dispatch(ctx, "   ").ok)

# ⚠ A TELEGRAM-ALAK is menjen: `/pos` ugyanaz, mint `pos`. Enélkül a következő
# körben a bot parancsait külön kellene értelmezni — két forrás.
check("⚠ a `/` előtagú (Telegram-)alak is működik",
      cc.dispatch(ctx, "/pairs").ok and cc.dispatch(ctx, "/help").ok)
check("az aliasok működnek (`q`, `list`)",
      cc.dispatch(ctx, "q").quit and cc.dispatch(ctx, "list").ok)

# ── pairs ──
_sorok = cc.dispatch(ctx, "pairs").lines
check("a `pairs` mindkét instrumentumot mutatja",
      any("Ger40" in x for x in _sorok) and any("EURUSD" in x for x in _sorok))
check("⚠ a futó stratégiát MEGJELÖLI (szándék=live)",
      any("wpr_sma*" in x for x in _sorok))

# ── pos / close ──
POZ = [{"ticket": 111, "symbol": "Ger40", "type": "BUY", "volume": 0.1,
        "price_open": 100.0, "sl": 95.0, "tp": 110.0, "profit": 12.3}]
cfg, zart, ctx = ctx_epit(poz=POZ, pnl=12.3)
check("a `pos` kiírja a pozíciót",
      any("111" in x for x in cc.dispatch(ctx, "pos").lines))
_r = cc.dispatch(ctx, "close 111")
# ⚠ A ZÁRÁS MEGERŐSÍTÉST KÉR, és a megerősítésig SEMMI nem történik. Ugyanez a
# mechanizmus szolgálja majd ki a Telegram gombjait.
check("⚠ a `close` először MEGERŐSÍTÉST kér", bool(_r.confirm) and not zart,
      _r.confirm)
_r = cc.dispatch(ctx, "close 111", confirmed=True)
check("...megerősítve zár", zart == [111])
check("⚠ ...és MEGMONDJA, hogy a stratégia tovább fut",
      any("stop" in x for x in _r.lines))
check("nem létező ticketnél nem zár semmit",
      not cc.dispatch(ctx, "close 999").ok)
check("`close` argumentum nélkül: használat", not cc.dispatch(ctx, "close").ok)

# ── play: a NEM ENGEDÉLYEZETT stratégia nem indítható ──
# ⚠ EZ A LÉNYEG. A motor a `_enabled & _intent` szorzatot futtatja: egy nem
# engedélyezett stratégiánál a szándék `live`-ban ragadna a configban, a
# felület futónak mutatná, a motor pedig sosem futtatná. Némán.
cfg, zart, ctx = ctx_epit()
_r = cc.dispatch(ctx, "play EURUSD ml_ai")
check("⚠ nem ENGEDÉLYEZETT stratégia NEM indítható", not _r.ok)
check("...és a config sem íródik át",
      (cfg["pairs"]["EURUSD"].get("run_state") or {}).get("ml_ai") is None)
check("...az üzenet megmondja, hol lehet bekapcsolni",
      any("EURUSD" in x and "ml_ai" in x for x in _r.lines))

_r = cc.dispatch(ctx, "play EURUSD")
check("a `play` stratégia nélkül MINDET indítja", _r.ok)
check("...a szándék a configba került",
      cfg["pairs"]["EURUSD"]["run_state"]["wpr_sma"] == "live")
check("...és a pár LIVE lett", ctx.instrument_state["EURUSD"] == "LIVE")
check("ismeretlen pár: beszédes hiba",
      not cc.dispatch(ctx, "play NINCSILYEN").ok)
check("⚠ kis/nagybetű nem számít a pár nevében",
      cc.dispatch(ctx, "play ger40 wpr_sma").ok)

# ── stop: a maradék stratégia dönt, nem a megjelenítés ──
# ⚠ 2026-08-23: a Stop a MEGJELENÍTÉSI listát nézve arra jutott, hogy nem
# maradt élő stratégia, a szimbólumot STOPPED-re tette, és a motor egy másik,
# ENGEDÉLYEZETT és FUTÓ stratégiát is leállított — három páron.
cfg, zart, ctx = ctx_epit()
_r = cc.dispatch(ctx, "stop Ger40 wpr_sma")
check("egy stratégia leállítása nem viszi el a párat",
      ctx.instrument_state["Ger40"] == "LIVE" and _r.ok)
check("⚠ ...és kiírja, MI fut tovább",
      any("bollinger_squeeze" in x for x in _r.lines))
check("a szándék `stopped` lett",
      cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "stopped")

cfg, zart, ctx = ctx_epit()
_r = cc.dispatch(ctx, "stop Ger40")
check("az UTOLSÓ leállítása (pozíció nélkül) a párat is leállítja",
      ctx.instrument_state["Ger40"] == "STOPPED" and not _r.confirm)

# ⚠ NYITOTT POZÍCIÓVAL a leállítás KIVEZETÉS: a motor tovább kezeli (BE,
# trailing, kiszállás), de új belépő nem nyílik. Ezt a felhasználónak TUDNIA
# kell, mielőtt igent mond — ezért kérdés, nem néma végrehajtás.
cfg, zart, ctx = ctx_epit(poz=POZ, pnl=12.3)
_r = cc.dispatch(ctx, "stop Ger40")
check("⚠ nyitott pozíciónál a `stop` MEGERŐSÍTÉST kér", bool(_r.confirm))
check("...és a megerősítésig semmi nem változik",
      cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "live"
      and ctx.instrument_state["Ger40"] == "LIVE")
_r = cc.dispatch(ctx, "stop Ger40", confirmed=True)
check("⚠ megerősítve KIVEZETÉS lesz (nem STOPPED)",
      ctx.instrument_state["Ger40"] == "CLOSING", ctx.instrument_state["Ger40"])

# ⚠ A pozíciót a BRÓKERTŐL is észre kell venni: fej nélküli indulás után a
# dashboard-állapot néhány körig üres, de a pozíció akkor is ott van.
cfg, zart, ctx = ctx_epit(poz=POZ, pnl=None)
check("⚠ a nyitott pozíciót a dashboard nélkül is látja",
      bool(cc.dispatch(ctx, "stop Ger40").confirm))

# ── mentés-hiba: NE hallgassunk ──
cfg, zart, ctx = ctx_epit(mentes=False)
_r = cc.dispatch(ctx, "play EURUSD")
check("⚠ ha a config MENTÉSE bukik, azt kimondja",
      not _r.ok and any("config" in x.lower() or "restart" in x.lower()
                        for x in _r.lines))

# ── balance / state ──
cfg, zart, ctx = ctx_epit()
check("a `balance` az egyenleget ÉS a mai eredményt adja",
      any("1000" in x and "12.5" in x for x in cc.dispatch(ctx, "balance").lines))

_sorok = cc.dispatch(ctx, "state").lines
check("a `state` életjelet ad", len(_sorok) >= 4)
# ⚠ A „minden rendben" nem lehet díszlet: az ELMARADT kört meg kell mondania.
ctx.last_cycle_ts = lambda: 0.0
check("⚠ ha még egy kör sem futott le, azt írja ki",
      any("kör" in x or "cycle" in x for x in cc.dispatch(ctx, "state").lines))
import time as _t
ctx.last_cycle_ts = lambda: _t.time() - 600
check("⚠ az ELMARADT kört megjelöli",
      any("⚠" in x for x in cc.dispatch(ctx, "state").lines))

# ── 3. A MOTOR SEAM-JEI ───────────────────────────────────────────────────
# ⚠ Az `engine_alive` SZÁNDÉKOSAN nem a szál `is_alive()`-ja: az akkor is True,
# ha a szál egy végtelen várakozásban ragadt. A 2026-08-XX-i néma szál-halálnál
# a kérdés nem az volt, hogy LÉTEZIK-e a szál, hanem hogy HALAD-e.
from trading import live_trader as lt
lt.last_cycle_ts = 0.0
check("⚠ kör nélkül a motor NEM 'halad'", not lt.engine_alive())
lt.last_cycle_ts = _t.time()
check("friss kör → halad", lt.engine_alive())
lt.last_cycle_ts = _t.time() - 3600
check("⚠ elavult kör → NEM halad (a szál élhet, mégsem dolgozik)",
      not lt.engine_alive())
lt.last_cycle_ts = 0.0

check("a leállítás-kérés jelezhető és lekérdezhető",
      not lt.stop_requested())
lt.request_stop()
check("...és a motor látja", lt.stop_requested())
lt._STOP.clear()

# ── 4. A KATALÓGUS ────────────────────────────────────────────────────────
# ⚠ A konzol FELÜLET, nem napló: a szövegei a katalógusból jöjjenek, különben
# angol nyelvre kapcsolva magyarul szólna — pont az i18n-munka után.
import json
_hu = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
_en = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
_ck = [k for k in _hu if k.startswith("console.")]
check("vannak `console.*` kulcsok", len(_ck) > 40, f"{len(_ck)} kulcs")
_hianyzo = [k for k in _ck if k not in _en]
check("⚠ MINDEN console-kulcs le van fordítva angolra",
      not _hianyzo, f"hiányzik: {_hianyzo[:5]}")
# A helykitöltők MINDEN nyelvben ugyanazok — különben a `format` elszáll, és a
# felirat a nyers kulcsra esik vissza.
import re
_elter = []
for k in _ck:
    a = set(re.findall(r"\{(\w+)", _hu[k]))
    b = set(re.findall(r"\{(\w+)", _en[k]))
    if a != b:
        _elter.append(k)
check("⚠ a helykitöltők egyeznek a két nyelvben", not _elter, str(_elter[:3]))

# ⚠ A parancs a katalógusban is angol maradjon (a `help` sorai a NEVET adják).
from core import i18n as _i18n
_i18n.set_language("en")
_r = cc.dispatch(ctx, "help")
check("⚠ angol nyelven is ANGOL parancsnevek látszanak",
      any("play" in x for x in _r.lines) and any("Commands" in x for x in _r.lines))
_i18n.set_language("hu")

# ── 5. Nincs MT5-függés ───────────────────────────────────────────────────
# ⚠ A parancs-réteg MT5- és tkinter-mentes kell legyen — különben a tesztek és
# a Telegram-oldal sem tudná használni hálózat nélkül.
# A vizsgálat AST-alapú: a KOMMENTBEN szabad említeni az MT5-öt, IMPORTÁLNI nem.
import ast as _ast
_fa = _ast.parse((ROOT / "core" / "console_cmd.py").read_text(encoding="utf-8"))
_tiltott = ("MetaTrader5", "mt5_connector", "tkinter", "dashboard.gui")


def _importok(node):
    out = []
    for n in _ast.walk(node):
        if isinstance(n, _ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, _ast.ImportFrom):
            out += [f"{n.module or ''}.{a.name}" for a in n.names]
    return out


_kivul = [n for n in _ast.walk(_fa)
          if isinstance(n, _ast.FunctionDef) and n.name != "live_context"]
# A modul-szintű importok külön (a `walk` a függvényekbe is belemenne).
_modul_import = []
for n in _fa.body:
    if isinstance(n, (_ast.Import, _ast.ImportFrom)):
        _modul_import += _importok(n)
_rossz = [i for i in _modul_import if any(t in i for t in _tiltott)]
for _f in _kivul:
    _rossz += [i for i in _importok(_f) if any(t in i for t in _tiltott)]
check("⚠ a parancsok NEM importálnak MT5-öt/tkintert (csak a live_context)",
      not _rossz, str(_rossz))

# ── 6. A SÚGÓ egy KONZOLON is kiírható ────────────────────────────────────
# ⚠ `python main.py` argumentum nélkül `UnicodeEncodeError`-ral szállt el a
# Windows-konzolon (cp1250): a súgó nyilai (→) miatt stack trace jött a
# parancsok listája helyett. Épp azzal kezdi egy konzolos felhasználó.
import subprocess
_p = subprocess.run([sys.executable, "main.py"], cwd=str(ROOT),
                    capture_output=True, text=True, errors="replace")
check("⚠ `python main.py` KIÍRJA a súgót (nem száll el a kódlapon)",
      _p.returncode == 0 and "console" in _p.stdout,
      (_p.stderr or "")[-120:] or f"rc={_p.returncode}")
check("...és a `console` parancs regisztrálva van",
      "console" in _p.stdout)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
