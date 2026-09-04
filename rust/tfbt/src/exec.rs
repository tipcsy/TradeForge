//! A VEGREHAJTASI CIKLUS natív magja — a `run_pair` bar-ciklusának hű portja.
//!
//! ⚠ EZ CSAK GYORSITAS, NEM REFERENCIA. A viselkedés forrása a Python
//! (`trading/backtest.py`); ez annak a portja. Eltérésnél a Python a helyes, és
//! a natív út a hibás — ezért van rá paritás-teszt éles adaton, és ezért esik
//! vissza a program Pythonra, ha bármi nem támogatott.
//!
//! ⚠ AMIT EZ A MAG TUD (2a lépcső):
//!   * SL/TP a BID/ASK modellel, `sl_first` sorrenddel,
//!   * `none` / `off` / `risky` preset (BE + trailing),
//!   * cost-cut (idő-stop),
//!   * méretezés (`calc_lot` + `calc_effective_slots`), slot-súly és keret,
//!   * napi veszteség-limit, szesszió-óra, jutalék + swap.
//!
//! ⚠ AMIT NEM (a hívó ilyenkor NEM hívja, a Python-út dönt): részleges zárás
//! (halving/shield/fibo/thirds/shield_fibo), pozícióépítés, kiszállási jel,
//! eseménynapló, kézi események, `max_lot`. Egy „majdnem jó" mag rosszabb, mint
//! a semmi: némán MÁS kereskedést futtatna.
//!
//! ⚠ A BELÉPŐ DÖNTÉSE NEM ITT VAN. A kapukat, a `bt_entry` tervét és a jelzést a
//! Python számolja ki ELŐRE, bárra bontva. Ezek a JEL-bárokon dőlnek el (pár száz
//! alkalom egy futásban), tehát a portolásukon nincs sebesség-nyereség — viszont
//! ott van a legfrissebb logika (sávos kapuk), és a duplázásuk lenne a legnagyobb
//! paritás-kockázat.

use std::slice;

const DAY_SEC: f64 = 86_400.0;
const NS_PER_SEC: f64 = 1_000_000_000.0;

pub const PRESET_NONE: i32 = 0;
pub const PRESET_OFF: i32 = 1;
pub const PRESET_RISKY: i32 = 2;

const ST_OPEN: u8 = 0;
const ST_SL: u8 = 1;
const ST_TP: u8 = 2;
const ST_CUT: u8 = 3;

/// ⚠ A MEZOK SORRENDJE KOTOTT — a Python `core.native` ugyanebben a sorrendben
/// tolti fel. Egy elcsuszott mezo NEMAN mas kereskedest futtatna; teszt orzi.
#[repr(C)]
pub struct ExecParams {
    pub point_size: f64,
    pub pv1_point: f64,
    pub min_lot: f64,
    pub lot_step: f64,
    pub max_open_slots: f64,
    pub account_risk_pct: f64,
    pub daily_limit_usd: f64,
    pub daily_limit_pct: f64,
    pub initial_balance: f64,
    pub be_pct: f64,
    pub be_buffer_points: f64,
    pub trail_act_atr: f64,
    pub trail_dist_atr: f64,
    pub risky_trail_factor: f64,
    pub commission_per_lot: f64,
    pub swap_long_per_lot: f64,
    pub swap_short_per_lot: f64,
    pub cost_cut_ns: f64,
    pub sl_first: f64,
    pub preset: f64,
    pub rollover3_weekday: f64,
    pub cost_cut_on: f64,
    /// ⚠ KET KULONBOZO kockazati szazalek van, es ez NEM elirás. A MERETEZES
    /// (`account_risk_pct`) a kapu-hatassal csokkentett ertek, a SLOT-SULY
    /// viszont a szamla EREDETI keretehez meri a poziciot (`trading_cfg`).
    /// Egyetlen mezovel a `cautious`/kapu-csokkentett futasok mas slot-sulyt
    /// adnanak, mint a Python — vagyis mas koteseket.
    pub slot_risk_pct: f64,
    /// A brókeri felső lot-korlát (`volume_max`); 0 = nincs.
    pub max_lot: f64,
}

#[derive(Clone)]
struct Trade {
    dir_buy: bool,
    open_i: i64,
    open_ns: i64,
    open_price: f64,
    sl: f64,
    tp: f64,
    lot: f64,
    sl_points: f64,
    entry_atr: f64,
    entry_balance: f64,
    risk_usd: f64,
    slot_weight: f64,
    risk_free: bool,
    close_i: i64,
    close_price: f64,
    status: u8,
    pnl: f64,
    comm: f64,
    swap: f64,
}

/// `core.trade_costs.nights_held` hű portja.
fn nights_held(open_ts: f64, close_ts: f64, rollover3: i32) -> f64 {
    if close_ts <= open_ts {
        return 0.0;
    }
    let first = (open_ts / DAY_SEC).floor() as i64 + 1;
    let last = (close_ts / DAY_SEC).floor() as i64;
    if last < first {
        return 0.0;
    }
    let mut total = 0.0;
    for day in first..=last {
        // 1970-01-01 csutortok volt → a hetfo-alapu index eltolasa 3.
        let weekday = ((day + 3) % 7) as i32;
        total += if rollover3 >= 0 && weekday == rollover3 { 3.0 } else { 1.0 };
    }
    total
}

/// A Python `round()` BANKARI kerekitese (a felet a PAROS fele).
///
/// ⚠ NEM `f64::round`. Az a felet MINDIG felfele viszi; a Python nem. Egy .5-os
/// eset itt eltero slotszamot adna, azon at eltero lotot — vagyis mas kotest.
fn banker_round(x: f64) -> f64 {
    let f = x.floor();
    let d = x - f;
    if (d - 0.5).abs() < 1e-12 {
        if (f as i64) % 2 == 0 { f } else { f + 1.0 }
    } else {
        x.round()
    }
}

/// `core.risk_manager.calc_effective_slots` hű portja.
fn effective_slots(balance: f64, sl_points: f64, p: &ExecParams, risk_pct: f64) -> f64 {
    let actual = p.min_lot * sl_points * p.pv1_point;
    if actual <= 0.0 {
        return p.max_open_slots;
    }
    let slots = banker_round(balance * risk_pct / actual * p.max_open_slots);
    slots.max(1.0).min(p.max_open_slots)
}

/// `core.risk_manager.calc_lot` hű portja (FLOOR-ra kerekit, aztan min_lot).
fn calc_lot(balance: f64, sl_points: f64, p: &ExecParams, risk_pct: f64, eff: f64) -> f64 {
    if sl_points <= 0.0 || p.pv1_point <= 0.0 {
        return p.min_lot;
    }
    let raw = (balance * risk_pct / eff) / (sl_points * p.pv1_point);
    let mut lot = (raw / p.lot_step).floor() * p.lot_step;
    if lot < p.min_lot {
        lot = p.min_lot;
    }
    // A broker FELSO korlatja — a vagas a kockazatot csak CSOKKENTI.
    if p.max_lot > 0.0 && lot > p.max_lot {
        lot = p.max_lot;
    }
    lot
}

/// `core.risk_manager.slot_weight` hű portja.
fn slot_weight(risk_ccy: f64, balance: f64, p: &ExecParams) -> f64 {
    let per_slot = if p.max_open_slots > 0.0 {
        balance * p.slot_risk_pct / p.max_open_slots
    } else {
        0.0
    };
    if !(per_slot > 0.0) || !(risk_ccy > 0.0) {
        return 1.0;
    }
    risk_ccy / per_slot
}

/// `core.risk_manager.fits_budget` hű portja.
fn fits_budget(occupied_w: f64, new_w: f64, max_slots: f64) -> bool {
    const EPS: f64 = 1e-9;
    if new_w <= 0.0 {
        return true;
    }
    if new_w > max_slots {
        return occupied_w <= EPS;
    }
    occupied_w + new_w <= max_slots + EPS
}

/// `trading.backtest._update_stops` hű portja (BE + trailing).
fn update_stops(t: &mut Trade, high: f64, low: f64, p: &ExecParams, risky: bool) {
    let atr = t.entry_atr;
    let trail_ok = atr > 0.0;
    let trail_act = if risky { 0.0 } else { p.trail_act_atr * atr };
    let trail_dist = p.trail_dist_atr * atr * if risky { p.risky_trail_factor } else { 1.0 };
    let be_buf = p.be_buffer_points * p.point_size;

    if t.dir_buy {
        if (risky || p.be_pct > 0.0) && !t.risk_free {
            let trig = if risky {
                t.open_price
            } else {
                t.open_price + (t.tp - t.open_price) * p.be_pct
            };
            if high >= trig {
                t.sl = t.open_price + be_buf;
                t.risk_free = true;
            }
        }
        if t.risk_free && trail_ok && high >= t.open_price + trail_act {
            let new_sl = high - trail_dist;
            if new_sl > t.sl {
                t.sl = new_sl;
            }
        }
    } else {
        if (risky || p.be_pct > 0.0) && !t.risk_free {
            let trig = if risky {
                t.open_price
            } else {
                t.open_price - (t.open_price - t.tp) * p.be_pct
            };
            if low <= trig {
                t.sl = t.open_price - be_buf;
                t.risk_free = true;
            }
        }
        if t.risk_free && trail_ok && low <= t.open_price - trail_act {
            let new_sl = low + trail_dist;
            if new_sl < t.sl {
                t.sl = new_sl;
            }
        }
    }
}

/// A végrehajtási ciklus. Visszaad: a kötések száma, vagy negatív hibakód.
///
/// # Safety
/// A hívónak érvényes, `n` hosszú bemeneti és legalább `max_trades` hosszú
/// kimeneti tömböket kell adnia.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn tfbt_run_exec(
    n: usize,
    t_ns: *const i64,
    high: *const f64,
    low: *const f64,
    close: *const f64,
    spread: *const f64,
    close_spread: *const f64,
    day_idx: *const i64,
    off_hour: *const u8,
    signal: *const u8,
    sl_pts: *const f64,
    tp_pts: *const f64,
    gate_risk: *const f64,
    entry_atr: *const f64,
    p: *const ExecParams,
    max_trades: usize,
    out_i64: *mut i64,   // 3 × max_trades: open_i, close_i, status
    out_f64: *mut f64,   // 15 × max_trades (lásd lent)
) -> i64 {
    if p.is_null() || n == 0 || out_i64.is_null() || out_f64.is_null() {
        return -1;
    }
    let p = &*p;
    let t_ns = slice::from_raw_parts(t_ns, n);
    let hi = slice::from_raw_parts(high, n);
    let lo = slice::from_raw_parts(low, n);
    let cl = slice::from_raw_parts(close, n);
    let spr = slice::from_raw_parts(spread, n);
    let csp = slice::from_raw_parts(close_spread, n);
    let day = slice::from_raw_parts(day_idx, n);
    let offh = slice::from_raw_parts(off_hour, n);
    let sig = slice::from_raw_parts(signal, n);
    let slp = slice::from_raw_parts(sl_pts, n);
    let tpp = slice::from_raw_parts(tp_pts, n);
    let grisk = slice::from_raw_parts(gate_risk, n);
    let eatr = slice::from_raw_parts(entry_atr, n);

    let sl_first = p.sl_first != 0.0;
    let preset = p.preset as i32;
    let risky = preset == PRESET_RISKY;
    let manage = preset != PRESET_NONE;
    let rollover3 = p.rollover3_weekday as i32;
    let cc_on = p.cost_cut_on != 0.0;

    let mut balance = p.initial_balance;
    let mut open: Vec<Trade> = Vec::new();
    let mut done: Vec<Trade> = Vec::new();
    // Napi P&L: a napok szama keves (par szaz), ezert egyszeru parosito vektor.
    let mut daily: Vec<(i64, f64)> = Vec::new();
    let mut dl_balance = f64::NAN;
    let mut dl_cache = 0.0f64;

    for i in 0..n {
        let bar_c = cl[i];
        let s = spr[i];
        let bid_hi = hi[i];
        let bid_lo = lo[i];
        let ask_hi = hi[i] + s;
        let ask_lo = lo[i] + s;

        let di = day[i];
        let mut dloss = 0.0;
        for (k, v) in daily.iter() {
            if *k == di {
                dloss = *v;
                break;
            }
        }
        if balance != dl_balance {
            dl_balance = balance;
            dl_cache = if p.daily_limit_usd > 0.0 {
                p.daily_limit_usd
            } else {
                balance * p.daily_limit_pct
            };
        }
        let limit_hit = dloss <= -dl_cache;

        // ── Nyitott poziciok ──────────────────────────────────────────
        let mut k = 0usize;
        while k < open.len() {
            let mut closed = false;
            {
                let t = &mut open[k];
                let (tp_hit, sl_hit) = if t.dir_buy {
                    (bid_hi >= t.tp, bid_lo <= t.sl)
                } else {
                    (ask_lo <= t.tp, ask_hi >= t.sl)
                };
                if sl_hit && (sl_first || !tp_hit) {
                    t.close_price = t.sl;
                    t.status = ST_SL;
                    closed = true;
                } else if tp_hit {
                    t.close_price = t.tp;
                    t.status = ST_TP;
                    closed = true;
                } else if manage {
                    if t.dir_buy {
                        update_stops(t, bid_hi, bid_lo, p, risky);
                    } else {
                        update_stops(t, ask_hi, ask_lo, p, risky);
                    }
                }
                // Cost-cut: N jel-gyertya utan meg veszteseges → korai zaras.
                if !closed && cc_on
                    && (t_ns[i] - t.open_ns) as f64 >= p.cost_cut_ns
                {
                    let px = if t.dir_buy { bar_c } else { bar_c + s };
                    let veszt = if t.dir_buy {
                        px < t.open_price
                    } else {
                        px > t.open_price
                    };
                    if veszt {
                        t.close_price = px;
                        t.status = ST_CUT;
                        closed = true;
                    }
                }
                if closed {
                    t.close_i = i as i64;
                    let mut diff = t.close_price - t.open_price;
                    if !t.dir_buy {
                        diff = -diff;
                    }
                    let gross = (diff / p.point_size) * t.lot * p.pv1_point;
                    let comm = p.commission_per_lot * t.lot;
                    let nights = nights_held(
                        t.open_ns as f64 / NS_PER_SEC,
                        t_ns[i] as f64 / NS_PER_SEC,
                        rollover3,
                    );
                    let per = if t.dir_buy {
                        p.swap_long_per_lot
                    } else {
                        p.swap_short_per_lot
                    };
                    let swap = per * t.lot * nights;
                    t.comm = comm;
                    t.swap = swap;
                    let net = gross - comm + swap;
                    // ⚠ ELOJELES NULLA. Az IEEE megkulonbozteti a -0,0-t a
                    // +0,0-tol; a ket ertek egyenlo, de MASKENT irodik ki (a
                    // CSV-ben „-0.0"), es a paritas-teszt is elbukna rajta.
                    // A Python ugyanezt a szamitast +0,0-ra hozza ki.
                    t.pnl = if net == 0.0 { 0.0 } else { net };
                }
            }
            if closed {
                let t = open.remove(k);
                balance += t.pnl;
                let mut megvan = false;
                for e in daily.iter_mut() {
                    if e.0 == di {
                        e.1 += t.pnl;
                        megvan = true;
                        break;
                    }
                }
                if !megvan {
                    daily.push((di, t.pnl));
                }
                done.push(t);
            } else {
                k += 1;
            }
        }

        // ── Slotok ────────────────────────────────────────────────────
        let mut occupied = 0.0f64;
        let mut occupied_w = 0.0f64;
        for t in open.iter() {
            if !t.risk_free {
                occupied += 1.0;
                occupied_w += t.slot_weight;
            }
        }

        // ── Belepo ────────────────────────────────────────────────────
        let sg = sig[i];
        if sg != 0 && (p.max_open_slots - occupied) > 0.0 && offh[i] == 0 && !limit_hit {
            let sl_points = slp[i];
            if sl_points > 0.0 {
                let risk_pct = p.account_risk_pct * grisk[i];
                let eff = effective_slots(balance, sl_points, p, risk_pct);
                let lot = calc_lot(balance, sl_points, p, risk_pct, eff);
                let w = slot_weight(lot * sl_points * p.pv1_point, balance, p);
                if fits_budget(occupied_w, w, p.max_open_slots) {
                    let mut esp = csp[i];
                    if !(esp > 0.0) {
                        esp = s;
                    }
                    let dir_buy = sg == 1;
                    let open_price = if dir_buy { bar_c + esp } else { bar_c };
                    let d = sl_points * p.point_size;
                    let dtp = tpp[i] * p.point_size;
                    let (sl_price, tp_price) = if dir_buy {
                        (open_price - d, open_price + dtp)
                    } else {
                        (open_price + d, open_price - dtp)
                    };
                    open.push(Trade {
                        dir_buy,
                        open_i: i as i64,
                        open_ns: t_ns[i],
                        open_price,
                        sl: sl_price,
                        tp: tp_price,
                        lot,
                        sl_points,
                        entry_atr: eatr[i],
                        entry_balance: balance,
                        risk_usd: lot * sl_points * p.pv1_point,
                        slot_weight: w,
                        risk_free: false,
                        close_i: -1,
                        close_price: f64::NAN,
                        status: ST_OPEN,
                        pnl: 0.0,
                        comm: 0.0,
                        swap: 0.0,
                    });
                }
            }
        }
    }

    // A nyitva maradtak a vegere — ugyanabban a sorrendben, ahogy a Python teszi.
    for t in open.drain(..) {
        done.push(t);
    }

    let m = done.len().min(max_trades);
    for (j, t) in done.iter().take(m).enumerate() {
        *out_i64.add(j) = t.open_i;
        *out_i64.add(max_trades + j) = t.close_i;
        *out_i64.add(2 * max_trades + j) = t.status as i64;
        let f = |k: usize| out_f64.add(k * max_trades + j);
        *f(0) = if t.dir_buy { 1.0 } else { 2.0 };
        *f(1) = t.open_price;
        *f(2) = t.close_price;
        *f(3) = t.sl;
        *f(4) = t.tp;
        *f(5) = t.lot;
        *f(6) = t.sl_points;
        *f(7) = t.entry_atr;
        *f(8) = t.entry_balance;
        *f(9) = t.risk_usd;
        *f(10) = t.slot_weight;
        *f(11) = t.pnl;
        *f(12) = t.comm;
        *f(13) = t.swap;
        *f(14) = if t.risk_free { 1.0 } else { 0.0 };
    }
    m as i64
}
