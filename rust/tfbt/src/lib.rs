//! TradeForge natív VÉGREHAJTÁSI mag — C-ABI, a Python `ctypes`-szal hívja.
//!
//! ⚠ ITT NINCS, ÉS NEM IS LESZ STRATÉGIA-LOGIKA. Ez a határ a projekt egyik
//! alapszabálya: **a stratégia EGY helyen van, Pythonban.**
//!
//! v3.34.0-ban volt itt egy `wpr_sma` jelzés-állapotgép (a
//! `core/signal_detector.py` „hű portja"), és a fejléc még meg is indokolta,
//! hogy a duplázás tudatos. **Ez hiba volt, és 2026-09-05-én kikerült.**
//! Ugyanazzal az érvvel utasítottuk el korábban az MQL5-ös szimulált
//! végrehajtást: *két forrás, ami külön romlik el* — a `BacktestReplayer` v4 és
//! a viz↔backtest paritás is ezen bukott el. A saját szabályunk alól nincs
//! kivétel azért, mert a második forrás történetesen gyors.
//!
//! ⚠ AZ ÁRA MÉRVE: a jelzés-mag elhagyása +0,554 mp/trial/ablak, azaz ~18 perc
//! egy 500 triales, 4 ablakos optimalizáláson. Ennyibe kerül, hogy a stratégia
//! egy helyen legyen — és megéri: a `.tfs` csomag így marad értelmes (a
//! stratégiát BEMÁSOLOD, nem újrafordítod), és minden stratégia egyenlő.
//!
//! ── AMI ITT MARADT, ÉS MIÉRT SZABAD ────────────────────────────────────
//! Az `exec` modul a VÉGREHAJTÁS: SL/TP a bid/ask modellel, breakeven,
//! trailing, cost-cut, napi limit, slot-keret, méretezés, jutalék/swap. Ez
//! semmit nem tud a stratégiáról — KÉSZ belépő-terveket (`signal`, `sl_pts`,
//! `tp_pts`, `gate_risk`, `entry_atr`) hajt végre, amiket a Python számol ki.
//! Ugyanaz a kategória, mint a `risk_manager` vagy a `trade_costs`: motor, nem
//! stratégia. Ezért nincs benne duplikáció, és ezért működik MINDEN
//! stratégiával — mérve a `trend_pullback`-en és a bollingeren is.
//!
//! ⚠ MIÉRT NEM PyO3. A PyO3 a CPython ABI-jához köt (Windowson az MSVC
//! toolchainhez is), és minden Python-frissítésnél újrafordítást kér. Egy sima
//! C-ABI könyvtárat a `ctypes` bármelyik Pythonból betölt, numpy-tömbök
//! mutatóival — nincs se ABI-, se fordító-függés.
//!
//! ⚠ EZ CSAK GYORSÍTÁS, NEM REFERENCIA. A viselkedés forrása a Python; ez
//! annak a hű portja. Eltérésnél a Python a helyes — ezért van rá paritás-teszt,
//! és ezért esik vissza a program Pythonra, ha a könyvtár nincs lefordítva.

pub mod exec;

/// A mag verziója — a Python oldal ezt ellenőrzi betöltéskor.
///
/// ⚠ EMELNI KELL, ha a viselkedés vagy a felület változik. Egy régi `.dll` egy
/// új Python-logika mellett NÉMÁN mást számolna.
///
/// 3 (2026-09-05): a `wpr_sma` jelzés-mag KIKERÜLT — a könyvtár felülete
/// megváltozott, a régi `.dll` már nem használható.
pub const KERNEL_ABI: i32 = 3;

#[no_mangle]
pub extern "C" fn tfbt_abi_version() -> i32 {
    KERNEL_ABI
}
