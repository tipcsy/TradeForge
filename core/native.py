"""
NATÍV GYORSÍTÓ MAG — opcionális, és soha nem kötelező.

⚠ A KÉRÉS (2026-09-02, #9): „vizsgáljuk meg, hogy mennyit nyerünk egy 500-as
optimalizálással, ha Rust-on végezzük el… hol érdemes meghúzni a határt?"

A profilozás azt mutatta, hogy egy trial 0,8%-a valódi számítás, a többi
értelmezés. A jelzés-állapotgép Rustban ugyanazon az adaton **929–1218×** gyorsabb
(négy páron mérve), MINDEN páron bitre azonos jelzésszámmal.

── HÁROM SZABÁLY, AMIT EZ A MODUL KIKÉNYSZERÍT ─────────────────────────
1. **A PYTHON A REFERENCIA.** A natív mag csak gyorsítás; ha a kettő eltér, a
   Python a helyes. Ezért van rá paritás-teszt, és ezért nem kerül soha olyan
   helyzetbe, hogy „valószínűleg jó".
2. **RUST NÉLKÜL IS MŰKÖDIK MINDEN.** A könyvtár hiánya nem hiba: a program
   ilyenkor a Python-úton megy tovább, ugyanazzal az eredménnyel, csak lassabban.
   A tesztcsomagnak Rust nélküli gépen is zöldnek kell lennie.
3. **CSAK AMIT ISMER.** A natív út stratégiánként külön engedélyezett
   (`Strategy.native_kernel`), és a hívó minden más esetben a Pythonra esik
   vissza. Egy „majdnem jó" natív út rosszabb, mint a semmi: némán MÁS
   stratégiát futtatna.

── MIÉRT `ctypes`, ÉS NEM PyO3 ─────────────────────────────────────────
A PyO3 a CPython ABI-jához köt (Windowson az MSVC-toolchainhez is), és minden
Python-frissítésnél újrafordítást kér. Egy sima C-ABI könyvtárat a `ctypes`
bármelyik Pythonból betölt, numpy-tömbök mutatóival — nincs se ABI-, se
fordító-függés. Fordítás: `python tools/build_native.py`.

⚠ AZ ABI-VERZIÓ NEM DÍSZ. Egy régi `.dll` egy új Python-logika mellett NÉMÁN
mást számolna. A betöltés ezért ellenőrzi a `tfbt_abi_version()`-t, és eltérésnél
NEM használja a könyvtárat — inkább lassabban, mint rosszul.
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# A natív mag ABI-verziója, amit EZ a Python-kód elvár (lásd `rust/tfbt/src/lib.rs`).
EXPECTED_ABI = 1

ROOT = Path(__file__).resolve().parents[1]
_LIB_NAMES = ("tfbt.dll", "libtfbt.so", "libtfbt.dylib")

_lib = None            # a betöltött könyvtár, vagy None
_probalt = False       # egyszer próbálkozunk, aztán megjegyezzük
_ok_indok = ""         # miért NEM használjuk (a felület/napló ebből tud szólni)


def library_path():
    """A lefordított könyvtár útja, ha létezik."""
    for d in (ROOT / "rust" / "tfbt" / "target" / "release", ROOT / "rust"):
        for n in _LIB_NAMES:
            p = d / n
            if p.exists():
                return p
    return None


def _load():
    global _lib, _probalt, _ok_indok
    if _probalt:
        return _lib
    _probalt = True
    # ⚠ KIKAPCSOLHATÓ. Egy gyanús eredménynél az első kérdés az legyen, hogy
    # „ugyanaz jön ki natív mag nélkül is?" — ehhez kell egy kapcsoló, ami nem
    # igényel újrafordítást vagy fájl-törlést.
    if os.environ.get("TFBT_NATIVE", "1") == "0":
        _ok_indok = "kikapcsolva (TFBT_NATIVE=0)"
        return None
    p = library_path()
    if p is None:
        _ok_indok = "nincs lefordítva (python tools/build_native.py)"
        return None
    try:
        lib = ctypes.CDLL(str(p))
        lib.tfbt_abi_version.restype = ctypes.c_int
        abi = int(lib.tfbt_abi_version())
        if abi != EXPECTED_ABI:
            _ok_indok = (f"ABI-eltérés: a könyvtár {abi}, a program "
                         f"{EXPECTED_ABI} — fordítsd újra")
            log.warning("Natív mag KIMARAD — %s (%s)", _ok_indok, p)
            return None
        lib.tfbt_wpr_sma_signals.restype = ctypes.c_int64
        lib.tfbt_wpr_sma_signals.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_int64, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p,
        ]
        _lib = lib
        log.info("Natív mag betöltve: %s (ABI %d)", p.name, abi)
    except OSError as e:
        _ok_indok = f"nem tölthető be: {e}"
        log.warning("Natív mag KIMARAD — %s", _ok_indok)
    return _lib


def available() -> bool:
    return _load() is not None


def status() -> str:
    """Emberi állapot a naplóhoz/felülethez: `""` ha él, különben az OK."""
    _load()
    return "" if _lib is not None else (_ok_indok or "nem elérhető")


# ⚠ A MEZŐK SORRENDJE KÖTÖTT — ugyanaz, mint a `WprParams` a Rust oldalon. Egy
# elcsúszott mező némán MÁS küszöbökkel futtatná a stratégiát; ezért van rá teszt.
WPR_FIELDS = ("wpr_m15_sell_extreme", "wpr_m15_buy_extreme",
              "wpr_m15_sell_trigger", "wpr_m15_buy_trigger",
              "wpr_m1_sell_extreme", "wpr_m1_buy_extreme",
              "wpr_m1_sell_trigger", "wpr_m1_buy_trigger")


def wpr_sma_signals(m15, m1, params: dict, delta_ns: int):
    """A `wpr_sma` jelölt-listája natívan: `{m1_index: "BUY"|"SELL"}`.

    `None`, ha a natív út nem használható (nincs könyvtár, hiányzó oszlop,
    hiányzó küszöb) — a hívó ilyenkor a Python-úton megy tovább.

    ⚠ NEM DOB KIVÉTELT egy hiányzó feltétel miatt. Egy gyorsítás nem állíthatja
    meg a programot; a helyes válasz a visszaesés, nem a leállás."""
    import numpy as np

    lib = _load()
    if lib is None:
        return None
    for oszlop in ("close", "sma", "wpr", "atr"):
        if oszlop not in m15.columns:
            return None
    if "wpr" not in m1.columns:
        return None
    _t = params.get("wpr_m15_trigger", -50)
    _t1 = params.get("wpr_m1_trigger", -50)
    _alap = {"wpr_m15_sell_trigger": _t, "wpr_m15_buy_trigger": _t,
             "wpr_m1_sell_trigger": _t1, "wpr_m1_buy_trigger": _t1}
    try:
        ertekek = [float(params[k]) if k in params else float(_alap[k])
                   for k in WPR_FIELDS]
    except (KeyError, TypeError, ValueError):
        return None

    def _f8(s):
        return np.ascontiguousarray(s.to_numpy(), dtype=np.float64)

    t15 = np.ascontiguousarray(m15.index.values.astype("int64"))
    t1 = np.ascontiguousarray(m1.index.values.astype("int64"))
    c15, s15, w15, a15 = (_f8(m15["close"]), _f8(m15["sma"]),
                          _f8(m15["wpr"]), _f8(m15["atr"]))
    w1 = _f8(m1["wpr"])
    n15, n1 = len(t15), len(t1)
    prm = (ctypes.c_double * len(ertekek))(*ertekek)
    out_idx = np.empty(max(n1, 1), dtype=np.int64)
    out_dir = np.empty(max(n1, 1), dtype=np.uint8)

    def _p(a):
        return a.ctypes.data

    db = lib.tfbt_wpr_sma_signals(
        _p(t15), _p(c15), _p(s15), _p(w15), _p(a15), n15,
        _p(t1), _p(w1), n1, ctypes.c_int64(int(delta_ns)),
        ctypes.cast(prm, ctypes.c_void_p), _p(out_idx), _p(out_dir))
    if db < 0:
        log.warning("Natív mag hibakódot adott (%d) — Python-út", db)
        return None
    return {int(out_idx[i]): ("BUY" if out_dir[i] == 1 else "SELL")
            for i in range(int(db))}
