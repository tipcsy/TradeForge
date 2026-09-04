//! TradeForge natív backtest-mag — C-ABI, a Python `ctypes`-szal hívja.
//!
//! ⚠ MIÉRT LÉTEZIK. Egy trial (Ger40, 6 hónap, 152 833 M1 + 10 193 M15 bár)
//! 1,88 mp, és ebből 0,8% a valódi, vektorizált számítás. A többi értelmezés.
//! A jelzés-állapotgép Rustban ugyanezen az adaton 0,39 ms alatt fut le — négy
//! páron 929–1218× a Pythonhoz képest, MINDEN páron bitre azonos jelzésszámmal.
//!
//! ⚠ EZ CSAK GYORSÍTÁS, NEM REFERENCIA. A viselkedés forrása továbbra is a
//! Python (`core/signal_detector.py`); ez a fájl annak a HŰ PORTJA. Ha a kettő
//! eltér, a Python a helyes, és a natív út hibás — ezért van rá paritás-teszt,
//! és ezért esik vissza a program Pythonra, ha a könyvtár nincs lefordítva.
//! A tesztcsomagnak Rust NÉLKÜLI gépen is zöldnek kell lennie.
//!
//! ⚠ MIÉRT NEM PyO3. A PyO3 a CPython ABI-jához köt (Windowson az MSVC
//! toolchainhez is), és minden Python-frissítésnél újrafordítást kér. Egy sima
//! C-ABI könyvtárat a `ctypes` bármelyik Pythonból betölt, numpy-tömbök
//! mutatóival — nincs se ABI-, se fordító-függés.
//!
//! ⚠ A STRATÉGIA-LOGIKA ITT DUPLÁN VAN, ÉS EZ TUDATOS. Egy stratégia attól még
//! Python-modul marad (`.tfs`), hogy VAN hozzá natív mag; a natív mag egy
//! SZÁRMAZTATOTT, ellenőrizhető gyorsítás. Ezért kell minden magnak nevet és
//! verziót adni (`wpr_sma_v1`): a Python oldal csak akkor használja, ha a
//! stratégia kifejezetten ezt a magot deklarálja.

pub mod exec;

use std::slice;

#[derive(Clone, Copy, PartialEq)]
enum Dir {
    None,
    Buy,
    Sell,
}

/// A `core.signal_detector.PairState` mezői — ugyanaz a szerkezet.
struct State {
    dir: Dir,
    m15_window_open: bool,
    m15_extreme_seen: bool,
    m15_opposite_seen: bool,
    m1_armed: bool,
}

impl State {
    fn new() -> Self {
        State {
            dir: Dir::None,
            m15_window_open: false,
            m15_extreme_seen: false,
            m15_opposite_seen: false,
            m1_armed: false,
        }
    }
}

/// A `wpr_sma` küszöbei. A sorrend RÖGZÍTETT: a Python oldal ugyanebben a
/// sorrendben tölti fel a tömböt (`core/native.py`), és a kettőt egy teszt
/// köti össze — egy elcsúszott mező némán MÁS stratégiát futtatna.
#[repr(C)]
pub struct WprParams {
    pub m15_sell_extreme: f64,
    pub m15_buy_extreme: f64,
    pub m15_sell_trigger: f64,
    pub m15_buy_trigger: f64,
    pub m1_sell_extreme: f64,
    pub m1_buy_extreme: f64,
    pub m1_sell_trigger: f64,
    pub m1_buy_trigger: f64,
}

/// A `check_m15_signal` hű portja (core/signal_detector.py).
#[inline]
fn m15_signal(s: &mut State, close: f64, sma: f64, wpr: f64, p: &WprParams) {
    let new_dir = if close < sma {
        Dir::Sell
    } else if close > sma {
        Dir::Buy
    } else {
        Dir::None
    };
    if new_dir != s.dir {
        s.m15_window_open = false;
        s.m15_extreme_seen = false;
        s.m15_opposite_seen = false;
    }
    s.dir = new_dir;

    match new_dir {
        Dir::Sell => {
            // (a) kiinduló (felső) extrém: felfegyverez; nyitott zónát érvénytelenít
            if wpr >= p.m15_sell_extreme {
                s.m15_extreme_seen = true;
                if s.m15_window_open {
                    s.m15_window_open = false;
                    s.m15_opposite_seen = false;
                }
            }
            // (b) másik (alsó) extrém a nyitott zónában
            if s.m15_window_open && wpr <= p.m15_buy_extreme {
                s.m15_opposite_seen = true;
            }
            // (c) kifutás: alsó extrém után a trigger felfelé visszaütése
            if s.m15_window_open && s.m15_opposite_seen && wpr >= p.m15_sell_trigger {
                s.m15_window_open = false;
                s.m15_extreme_seen = false;
                s.m15_opposite_seen = false;
            }
            // (d) nyitás: felfegyverzett + a trigger lefelé átütése
            if !s.m15_window_open && s.m15_extreme_seen && wpr <= p.m15_sell_trigger {
                s.m15_window_open = true;
                s.m15_opposite_seen = false;
            }
        }
        Dir::Buy => {
            if wpr <= p.m15_buy_extreme {
                s.m15_extreme_seen = true;
                if s.m15_window_open {
                    s.m15_window_open = false;
                    s.m15_opposite_seen = false;
                }
            }
            if s.m15_window_open && wpr >= p.m15_sell_extreme {
                s.m15_opposite_seen = true;
            }
            if s.m15_window_open && s.m15_opposite_seen && wpr <= p.m15_buy_trigger {
                s.m15_window_open = false;
                s.m15_extreme_seen = false;
                s.m15_opposite_seen = false;
            }
            if !s.m15_window_open && s.m15_extreme_seen && wpr >= p.m15_buy_trigger {
                s.m15_window_open = true;
                s.m15_opposite_seen = false;
            }
        }
        Dir::None => {
            s.m15_window_open = false;
            s.m15_extreme_seen = false;
            s.m15_opposite_seen = false;
        }
    }
    // A zárt (vagy irányt váltott) ablak az M1 felfegyverzést is nullázza.
    if !s.m15_window_open {
        s.m1_armed = false;
    }
}

/// A `check_m1_entry` hű portja. Visszaad: 0 = nincs, 1 = BUY, 2 = SELL.
#[inline]
fn m1_entry(s: &mut State, prev: f64, cur: f64, p: &WprParams) -> u8 {
    if !s.m15_window_open {
        s.m1_armed = false;
        return 0;
    }
    match s.dir {
        Dir::Sell => {
            if cur >= p.m1_sell_extreme {
                s.m1_armed = true;
            }
            if s.m1_armed && prev > p.m1_sell_trigger && p.m1_sell_trigger >= cur {
                s.m1_armed = false;
                return 2;
            }
        }
        Dir::Buy => {
            if cur <= p.m1_buy_extreme {
                s.m1_armed = true;
            }
            if s.m1_armed && prev < p.m1_buy_trigger && p.m1_buy_trigger <= cur {
                s.m1_armed = false;
                return 1;
            }
        }
        Dir::None => {}
    }
    0
}

/// A mag verziója — a Python oldal ezt ellenőrzi betöltéskor.
///
/// ⚠ EMELNI KELL, ha a viselkedés változik. Egy régi `.dll` egy új Python-logika
/// mellett NÉMÁN mást számolna; a verzió-eltérésnél a Python inkább nem
/// használja a natív utat, mint hogy rossz számot adjon.
pub const KERNEL_ABI: i32 = 2;

#[no_mangle]
pub extern "C" fn tfbt_abi_version() -> i32 {
    KERNEL_ABI
}

/// A `wpr_sma` jelölt-listája.
///
/// Bemenet (mind a hívó tulajdona, csak olvassuk):
///   `t15`, `close15`, `sma15`, `wpr15`, `atr15`  — `n15` elem
///   `t1`, `wpr1`                                 — `n1` elem
///   `delta_ns`  egy JEL-gyertya hossza nanoszekundumban
///   `p`         a küszöbök
/// Kimenet (a hívó foglalja, legalább `n1` elem):
///   `out_idx`   a jelző M1 bárok INDEXE
///   `out_dir`   1 = BUY, 2 = SELL
/// Visszaad: a jelzések száma, vagy negatív hibakód.
///
/// ⚠ A NaN-ŐRÖK a Python `bt_on_high_close`/`bt_on_low_close` őreinek felelnek
/// meg: NaN indikátornál az M15 állapotgép KIMARAD (de a mutató lép), NaN
/// WPR-nél az M1 belépő „NONE". Enélkül a warmup-szakasz eltérne.
///
/// # Safety
/// A hívónak érvényes, `n15`/`n1` hosszú, egymást át nem fedő tömböket kell
/// adnia, és `out_idx`/`out_dir` legalább `n1` férőhelyűnek kell lennie.
#[no_mangle]
pub unsafe extern "C" fn tfbt_wpr_sma_signals(
    t15: *const i64,
    close15: *const f64,
    sma15: *const f64,
    wpr15: *const f64,
    atr15: *const f64,
    n15: usize,
    t1: *const i64,
    wpr1: *const f64,
    n1: usize,
    delta_ns: i64,
    p: *const WprParams,
    out_idx: *mut i64,
    out_dir: *mut u8,
) -> i64 {
    if t15.is_null() || close15.is_null() || sma15.is_null() || wpr15.is_null()
        || atr15.is_null() || t1.is_null() || wpr1.is_null() || p.is_null()
        || out_idx.is_null() || out_dir.is_null()
    {
        return -1;
    }
    if n15 == 0 || n1 == 0 {
        return 0;
    }
    let t15 = slice::from_raw_parts(t15, n15);
    let c15 = slice::from_raw_parts(close15, n15);
    let s15 = slice::from_raw_parts(sma15, n15);
    let w15 = slice::from_raw_parts(wpr15, n15);
    let a15 = slice::from_raw_parts(atr15, n15);
    let t1 = slice::from_raw_parts(t1, n1);
    let w1 = slice::from_raw_parts(wpr1, n1);
    let p = &*p;
    let oi = slice::from_raw_parts_mut(out_idx, n1);
    let od = slice::from_raw_parts_mut(out_dir, n1);

    let mut st = State::new();
    let mut ptr: usize = 0;
    let mut db: i64 = 0;
    let mut prev = f64::NAN;

    for i in 0..n1 {
        let ti = t1[i];
        while ptr + 1 < n15 && t15[ptr + 1] + delta_ns <= ti {
            ptr += 1;
            if !(s15[ptr].is_nan() || w15[ptr].is_nan() || a15[ptr].is_nan()) {
                m15_signal(&mut st, c15[ptr], s15[ptr], w15[ptr], p);
            }
        }
        let cur = w1[i];
        if i > 0 && !(prev.is_nan() || cur.is_nan()) {
            let d = m1_entry(&mut st, prev, cur, p);
            if d != 0 {
                oi[db as usize] = i as i64;
                od[db as usize] = d;
                db += 1;
            }
        }
        prev = cur;
    }
    db
}
