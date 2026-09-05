"""
NATÍV GYORSÍTÓ MAG — opcionális, és soha nem kötelező.

⚠ A KÉRÉS (2026-09-02, #9): „vizsgáljuk meg, hogy mennyit nyerünk egy 500-as
optimalizálással, ha Rust-on végezzük el… hol érdemes meghúzni a határt?"

⚠ ITT NINCS STRATÉGIA-LOGIKA. A natív mag a VÉGREHAJTÁST gyorsítja (SL/TP,
breakeven, trailing, méretezés, slot, jutalék/swap) — kész belépő-terveket
hajt végre, amiket a Python számol ki. A stratégia EGY helyen van, Pythonban.

v3.34.0-ban volt itt egy `wpr_sma`-specifikus jelzés-mag is; 2026-09-05-én
KIKERÜLT, mert a stratégia-logika duplázása szembement a saját szabályunkkal
(lásd `rust/tfbt/src/lib.rs` fejléce). Ára mérve: ~18 perc egy 500 triales
optimalizáláson — ennyibe kerül, hogy a `.tfs` csomag értelmes maradjon.

── HÁROM SZABÁLY, AMIT EZ A MODUL KIKÉNYSZERÍT ─────────────────────────
1. **A PYTHON A REFERENCIA.** A natív mag csak gyorsítás; ha a kettő eltér, a
   Python a helyes. Ezért van rá paritás-teszt, és ezért nem kerül soha olyan
   helyzetbe, hogy „valószínűleg jó".
2. **RUST NÉLKÜL IS MŰKÖDIK MINDEN.** A könyvtár hiánya nem hiba: a program
   ilyenkor a Python-úton megy tovább, ugyanazzal az eredménnyel, csak lassabban.
   A tesztcsomagnak Rust nélküli gépen is zöldnek kell lennie.
3. **CSAK AMIT ISMER.** A natív út visszaesik Pythonra minden olyan esetben,
   amit nem ismer (részleges zárás, pozícióépítés, kiszállási jel, kézi
   szintek). Egy „majdnem jó" natív út rosszabb, mint a semmi: némán MÁS
   eredményt adna. Az elmaradás INDOKA naplózva van.

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
EXPECTED_ABI = 3

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


# ⚠ A MEZŐK SORRENDJE KÖTÖTT — ugyanaz, mint az `ExecParams` a Rust oldalon
# (`rust/tfbt/src/exec.rs`). Egy elcsúszott mező némán MÁS méretezéssel, MÁS
# stoppal futtatná a backtestet; ezért van rá teszt.
EXEC_FIELDS = (
    "point_size", "pv1_point", "min_lot", "lot_step",
    "max_open_slots", "account_risk_pct",
    "daily_limit_usd", "daily_limit_pct", "initial_balance",
    "be_pct", "be_buffer_points", "trail_act_atr", "trail_dist_atr",
    "risky_trail_factor",
    "commission_per_lot", "swap_long_per_lot", "swap_short_per_lot",
    "cost_cut_ns", "sl_first", "preset", "rollover3_weekday", "cost_cut_on",
    "slot_risk_pct", "max_lot",
)

# A kimeneti f64-mezők sorrendje (`out_f64`, `k * max_trades + j`).
EXEC_OUT_F64 = (
    "dir", "open_price", "close_price", "sl", "tp", "lot", "sl_points",
    "entry_atr", "entry_balance", "risk_usd", "slot_weight",
    "pnl", "comm", "swap", "risk_free",
)

# A `status` kódja a Rust oldalon (`ST_*`).
EXEC_STATUS = {0: "open", 1: "sl", 2: "tp", 3: "cut"}

# A bemeneti tömbök neve és típusa — a hívó ezeket adja át.
_EXEC_I64 = ("t_ns", "day_idx")
_EXEC_F64 = ("high", "low", "close", "spread", "close_spread",
             "sl_pts", "tp_pts", "gate_risk", "entry_atr")
_EXEC_U8 = ("off_hour", "signal")


def run_exec(bars: dict, params: dict, max_trades: int = 50000):
    """A backtest VÉGREHAJTÁSI ciklusa natívan.

    `bars`: bárononkénti bemenet (numpy tömbök, mind `n` hosszú) — az árak, a
    spread, a nap indexe, az óra-tiltás, és a MÁR ELDÖNTÖTT belépő-tervek
    (`signal`/`sl_pts`/`tp_pts`/`gate_risk`/`entry_atr`, lásd
    `trading.backtest.run_pair._entry_decision`).
    `params`: az `EXEC_FIELDS` kulcsai.

    Visszaad kötés-szótárak listáját (nyitási sorrendben zárva, a végén a
    nyitva maradtak — ugyanaz a sorrend, mint a Pythoné), vagy `None`, ha a
    natív út nem használható.

    ⚠ NEM DOB KIVÉTELT. Egy gyorsítás nem állíthatja meg a backtestet; a helyes
    válasz a `None` és a Python-út."""
    import numpy as np

    lib = _load()
    if lib is None:
        return None
    try:
        n = int(len(bars["t_ns"]))
        if n == 0:
            return []
        arr = {}
        for k in _EXEC_I64:
            arr[k] = np.ascontiguousarray(bars[k], dtype=np.int64)
        for k in _EXEC_F64:
            arr[k] = np.ascontiguousarray(bars[k], dtype=np.float64)
        for k in _EXEC_U8:
            arr[k] = np.ascontiguousarray(bars[k], dtype=np.uint8)
        for k, a in arr.items():
            if len(a) != n:
                return None
        prm = (ctypes.c_double * len(EXEC_FIELDS))(
            *[float(params[k]) for k in EXEC_FIELDS])
    except (KeyError, TypeError, ValueError):
        return None

    mt = max(int(max_trades), 1)
    out_i = np.zeros(3 * mt, dtype=np.int64)
    out_f = np.zeros(15 * mt, dtype=np.float64)

    if not hasattr(lib, "_tfbt_exec_kesz"):
        lib.tfbt_run_exec.restype = ctypes.c_int64
        lib.tfbt_run_exec.argtypes = (
            [ctypes.c_size_t] + [ctypes.c_void_p] * 13
            + [ctypes.c_void_p, ctypes.c_size_t,
               ctypes.c_void_p, ctypes.c_void_p])
        lib._tfbt_exec_kesz = True

    def _p(a):
        return a.ctypes.data

    db = lib.tfbt_run_exec(
        n, _p(arr["t_ns"]), _p(arr["high"]), _p(arr["low"]), _p(arr["close"]),
        _p(arr["spread"]), _p(arr["close_spread"]), _p(arr["day_idx"]),
        _p(arr["off_hour"]), _p(arr["signal"]), _p(arr["sl_pts"]),
        _p(arr["tp_pts"]), _p(arr["gate_risk"]), _p(arr["entry_atr"]),
        ctypes.cast(prm, ctypes.c_void_p), mt, _p(out_i), _p(out_f))
    if db < 0:
        log.warning("Natív végrehajtás hibakódot adott (%d) — Python-út", db)
        return None
    db = int(db)
    # ⚠ A TÚLCSORDULÁS NEM CSENDES. Ha több kötés lenne, mint amennyi kifér, a
    # natív út a lista ELEJÉT adná vissza — egy CSONKÍTOTT backtest pedig
    # rosszabb, mint a lassabb, de teljes. Ilyenkor inkább Python.
    if db >= mt:
        log.warning("Natív végrehajtás: a kimeneti keret betelt (%d) — Python-út", db)
        return None

    kotesek = []
    for j in range(db):
        t = {"open_i": int(out_i[j]),
             "close_i": int(out_i[mt + j]),
             "status": EXEC_STATUS.get(int(out_i[2 * mt + j]), "open")}
        for k, nev in enumerate(EXEC_OUT_F64):
            t[nev] = float(out_f[k * mt + j])
        kotesek.append(t)
    return kotesek
