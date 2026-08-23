"""A perzisztencia-réteg ne nyeljen el hibát — ott a némaság ADATVESZTÉS.

⚠ A KÉRÉS (2026-08-18): „a hibákat ne nyeljük el, hanem egy logfájlba kerüljenek
be… nem kapunk róla értesítést, mert mindent »elnyelünk«."

A felület-szintű hook (v2.64.0) az egész Tk-visszahívási felületet lefedte. Ez a
lépés a MARADÉKBÓL a legkockázatosabbat veszi: azokat a helyeket, ahol az elnyelt
kivétel nem egy hiányzó képpontot jelent, hanem HIBÁS VISELKEDÉST a következő
indítás után.

⚠ Nem mindegyik `except: pass` hiba — egy `tk.TclError` bezáráskor jogosan néma.
Ezért NEM vak cserét csináltunk: fájlonként eldöntve, melyik marad (kommenttel,
hogy miért), melyik `log.debug`, és melyik valódi hiba.

A KIVÁLASZTOTT NÉGY HELY, és hogy mi történik, ha hallgat:

  * `core/adopted.py`, `core/position_meta.py` — a ticket→stratégia és a
    belépéskori kockázat (1 R) nyilvántartása. A bróker oldalán ez az adat NEM
    létezik. Ha az írás elbukik, a bejegyzés csak a memóriában él: minden
    működni látszik, majd újraindítás után a pozíció GAZDÁTLAN.
  * `core/mt5_connector.py` — a szerver-eltolás. Ez a KERESKEDÉSI NAP
    definíciója (napi P&L, veszteséglimit, óra-kapu) és a piac-állapoté. A
    projektben már okozott valódi hibát.
  * `ml/optimizer.py` — a befejezés-marker. Ha nem jön létre, a study örökre
    „befejezetlen", és a program MINDEN indításkor újraindít egy már kész, 500
    trialos futást.
"""
import ast
import io
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class _Capture(logging.Handler):
    """Egy modul naplóját fogjuk el — a MÉRÉS az, hogy tényleg megszólal-e."""

    def __init__(self, level=logging.DEBUG):
        super().__init__(level=level)
        self.rows = []

    def emit(self, r):
        self.rows.append((r.levelno, r.getMessage()))

    def texts(self, min_level=logging.WARNING):
        return [m for lv, m in self.rows if lv >= min_level]


def _with_log(mod, fn, min_level=logging.WARNING):
    h = _Capture()
    mod.log.addHandler(h)
    _prev = mod.log.level
    mod.log.setLevel(logging.DEBUG)
    _disabled = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        fn()
    finally:
        logging.disable(_disabled)
        mod.log.setLevel(_prev)
        mod.log.removeHandler(h)
    return h.texts(min_level), h.texts(logging.DEBUG)


# ── 1. A NYILVÁNTARTÁSOK: sérült fájl + elbukó mentés ──────────────────
from core import adopted as ad
from core import position_meta as pm

for _mod, _name in ((ad, "adopted"), (pm, "position_meta")):
    _tmp = Path(tempfile.mkdtemp(prefix="tfv_sw_"))
    _real = _mod.PATH
    _mod.PATH = _tmp / "store.json"
    try:
        # (a) SÉRÜLT fájl → üresen indul, de SZÓL. Enélkül ez semmiben nem
        # különbözik az „még nincs bejegyzés" állapottól.
        _mod.PATH.write_text("{ ez nem json", encoding="utf-8")
        _mod._loaded = False
        _mod._state.clear()
        _warn, _all = _with_log(_mod, _mod.load)
        check(f"{_name}: a SÉRÜLT fájl figyelmeztetést ad", bool(_warn),
              str(_warn)[:90])
        check(f"{_name}: ...és kimondja, hogy ÜRESEN indul",
              any("ÜRESEN" in w for w in _warn), str(_warn)[:90])
        check(f"{_name}: ...de a program FUT tovább (üres állapot)",
              _mod._state == {})

        # (b) ELBUKÓ MENTÉS → a legrosszabb néma hiba: a memóriában megvan.
        _mod.PATH = _tmp / "nincs_ilyen_konyvtar" / "x" / "store.json"
        (_tmp / "nincs_ilyen_konyvtar").write_text("nem konyvtar", encoding="utf-8")
        _warn2, _ = _with_log(_mod, _mod._save_locked, logging.ERROR)
        check(f"{_name}: az elbukó MENTÉS HIBÁT naplóz", bool(_warn2),
              str(_warn2)[:90])
        check(f"{_name}: ...és kimondja, hogy újraindításkor elveszik",
              any("elveszik" in w for w in _warn2), str(_warn2)[:90])
    finally:
        _mod.PATH = _real
        _mod._loaded = False
        _mod._state.clear()
        shutil.rmtree(_tmp, ignore_errors=True)

# ⚠ A VALÓDI fájlokhoz NEM nyúltunk (a futtató őre is ezt figyeli).
check("a valódi nyilvántartás-útvonalak visszaálltak",
      "adopted_positions.json" in str(ad.PATH)
      and "position_meta.json" in str(pm.PATH), f"{ad.PATH.name} / {pm.PATH.name}")


# ── 2. A SZERVER-ELTOLÁS ───────────────────────────────────────────────
from core import mt5_connector as mc

_tmp2 = Path(tempfile.mkdtemp(prefix="tfv_off_"))
_real_of = mc._offset_file
try:
    _bad = _tmp2 / "server_offset.json"
    _bad.write_text("{{{ nem json", encoding="utf-8")
    mc._offset_file = lambda: _bad
    mc._server_offset["v"] = None
    _warn3, _ = _with_log(mc, mc._load_offset)
    check("eltolás: a SÉRÜLT fájl figyelmeztetést ad", bool(_warn3), str(_warn3)[:90])
    check("...és megmondja a következményt (a nap határa)",
          any("kereskedési nap" in w for w in _warn3), str(_warn3)[:90])

    # ⚠ A HIÁNYZÓ fájl viszont NORMÁLIS (még sosem mértünk) — arra NEM szólunk.
    mc._offset_file = lambda: _tmp2 / "sosem_volt.json"
    mc._server_offset["v"] = None
    _warn4, _ = _with_log(mc, mc._load_offset)
    check("...a HIÁNYZÓ fájlra viszont NEM (az normális)", not _warn4, str(_warn4))
finally:
    mc._offset_file = _real_of
    mc._server_offset["v"] = None
    shutil.rmtree(_tmp2, ignore_errors=True)


# ── 3. AZ OPTIMALIZÁLÓ MARKEREI ───────────────────────────────────────
_src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
_i = _src.find("done_flag.touch()")
_blk = _src[_i:_i + 700]
check("a befejezés-marker hibája naplózódik", "log.warning" in _blk)
check("...és megmondja a következményt (auto-újraindul)",
      "AUTOMATIKUSAN újraindul" in _blk, _blk[:0])
_j = _src.find("done_marker(symbol, strategy.name).touch()")
check("a done-marker hibája is", "log.warning" in _src[_j:_j + 500])


# ── 4. A MÉRŐSZÁM: hány néma elnyelés maradt ──────────────────────────
# ⚠ Ez a sor NEM bukik el — MÉR. A „majd rendbe tesszük" különben évekig igaz
# marad; így a fogyás számon kérhető. A maradék TÚLNYOMÓ része felület
# (dashboard), amit a Tk-hook amúgy is elkap a visszahívás szintjén.
def _count():
    per_file, broad, total = {}, {}, 0
    for f in ROOT.rglob("*.py"):
        sp = str(f)
        if ".venv" in sp or (ROOT / "tests") in f.parents:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        n = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Try)
                for h in node.handlers
                if len(h.body) == 1 and isinstance(h.body[0], ast.Pass))
        # ⚠ A TÁG (catch-all) elnyelés a veszélyes: az MINDENT elnyel, a jövőbeli
        # hibákat is. Egy SZŰK, kommentezett `except (TypeError, ValueError)`
        # (pl. egy elrontott számmező átugrása) jogos — azt nem számoljuk hibának.
        broad[f.relative_to(ROOT).as_posix()] = sum(
            1 for node in ast.walk(tree) if isinstance(node, ast.Try)
            for h in node.handlers
            if len(h.body) == 1 and isinstance(h.body[0], ast.Pass)
            and (h.type is None or ast.unparse(h.type) == "Exception"))
        if n:
            per_file[f.relative_to(ROOT).as_posix()] = n
            total += n
    return total, per_file, broad


_total, _per, _broad = _count()
_top = sorted(_per.items(), key=lambda kv: -kv[1])[:5]
print(f"      (néma elnyelés: {_total} — top: "
      + ", ".join(f"{k} {v}" for k, v in _top) + ")")
check("a mérés lefutott (a szám a naplóban marad)", _total >= 0)
# ⚠ A KERESKEDÉSI ÚT tiszta legyen: ezekben a modulokban a maradék NULLA vagy
# INDOKOLT. Ha valaki új néma elnyelést tesz ide, ITT bukjon el.
for _f in ("core/adopted.py", "core/position_meta.py", "core/mt5_connector.py",
           "trading/live_trader.py"):
    check(f"{_f}: nincs TÁG (catch-all) néma elnyelés", _broad.get(_f, 0) == 0,
          str(_broad.get(_f, 0)))
print(f"      (ebből TÁG catch-all: {sum(_broad.values())})")


# ── 5. A MOTOR HÉT HELYE (2. kör) ──────────────────────────────────────
# ⚠ Kettő közülük NEM kijelzés:
#   * a TF-együttállás kapu-függvénye — hibánál a kapu NEM blokkol („fail open").
#     Ez lehet a helyes választás, de némán semmiképp: kívülről pontosan úgy néz
#     ki, mint egy átengedő kapu.
#   * a piac-állapot — a `core.gates` a `market_label`-t EBBŐL olvassa, tehát
#     hiba esetén a Piac-kapu ÜRES címkével dönt.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")

check("van egyszer-szólj segéd (a 30 mp-es ciklus miatt)",
      "def _warn_once(" in _lt)
# ⚠ A ZAJ ÖNMAGÁBAN IS elrejti a leletet: percenként tucatnyi azonos sor mellett
# a ritka, fontos üzenet elveszik. Ezért az ismétlés `debug`-ra megy.
_i = _lt.find("def _warn_once(")
check("...és az ismétlés csak debug", "log.debug" in _lt[_i:_i + 400]
      and "log.warning" in _lt[_i:_i + 400])

for _key, _why in (("tf_align_gate", "a kapu fail-open volta"),
                   ("market_state", "a Piac-kapu üres címkéje"),
                   ("live_cells", "a stratégia saját hookja"),
                   ("sl_journal", "az SL-mozgás audit-nyoma")):
    check(f"szól: {_why}", f'"{_key}"' in _lt or f"'{_key}'" in _lt, _key)

check("a kapu-hiba KIMONDJA, hogy nem blokkol", "fail open" in _lt)
check("az SL-napló KIMONDJA, mit veszítünk",
      "nem lesznek visszakövethetők" in _lt)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
