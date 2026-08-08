"""
ML tanítás-pipeline — a Trading-with-AI train_evaluate/label_outcomes portja.

Az Optimalizálás gomb az ml_ai stratégiánál EZT futtatja (az optimizer
`fit`-dispatch-én át, subprocess-ben): címkézés → session-szűrés → irányonként
LightGBM (fallback: RandomForest) tanítás → küszöb-kalibráció → modell-mentés a
modelltárba (data/models/ml_ai/<SYMBOL>.pkl). Az out-of-sample TESZT nem itt
történik: az optimizer a közös úton (run_pair a test_start utáni időszakon, a
frissen mentett modellel) backtesteli és minősíti — pontosan úgy, ahogy élőben
viselkedne.

Eltérés a forrástól: a küszöböt a TRAIN-farok kalibrációs szeletén választjuk
(mint a forrás RETRAIN-módja), SOHA nem a test-időszakon (a forrás backtest-módja
a test-en kalibrált → szivárgás volt a kiértékelésbe).
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timezone

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

from strategy import ml_features as mlf
from strategy import ml_ai


# ---------------------------------------------------------------------------
# Címkézés — UGYANAZZAL az SL/TP sémával, amivel a stratégia méretez
# ---------------------------------------------------------------------------

def label_outcomes(feats: pd.DataFrame, params: dict, point_size: float,
                   lookahead: int, spread_points: float = 0.0) -> pd.DataFrame:
    """Gyertyánként: ha a záráson belépnék LONG-ba (ill. SHORT-ba), a TP előbb
    üt-e, mint az SL, a következő `lookahead` gyertyán belül? label = 1 (TP) /
    0 (SL vagy kifutás). A long és a short független.

    Az SL/TP a stratégia `sl_tp_points` sémája: dynamic_sltp → ATR14 × sl_atr_mult,
    TP = SL × tp_rr_ratio; különben fix sl_points/tp_points. Így a modell PONTOSAN
    arra a kérdésre tanul, amit a végrehajtás feltesz.

    ⚠ `spread_points` — A CÍMKE NEM LEHET SPREAD NÉLKÜLI. A gyertyák BID árak; egy
    LONG-ot ASK-on nyitsz és BID-en zársz, egy SHORT-ot BID-en nyitsz és ASK-on
    zársz. Mindkét irányban IGAZ, hogy az SL egy spreaddel közelebb, a TP egy
    spreaddel távolabb van, mint amit a nyers bid-gyertyákon mérnénk.

    Miért számít ennyire: 2026-08-07-i mérés, friss OOS. EURCHF-en/EURGBP-n az
    SL (ATR14 × 1.5) mindössze ~43-47 pont, a tipikus spread 14-15 — a stop
    HARMADA. A spread nélküli címke ott 37,6/38,8%-os alap-találatot mutatott, a
    spreaddel számolt 23,1/23,2%-ot. A modell tehát olyan célra tanult és olyan
    küszöbre kalibrálódott, ami a valóságban nem elérhető: éles OOS-on a
    backtest 16,5%-os TP-arányt hozott a címke ígérte 44,6% helyett."""
    closes = feats["close"].values
    highs  = feats["high"].values
    lows   = feats["low"].values
    atrs   = feats["atr14"].values
    n = len(feats)

    dynamic = bool(params.get("dynamic_sltp", True))
    sl_mult = float(params.get("sl_atr_mult", 1.5))
    rr      = float(params.get("tp_rr_ratio", 2.0))
    fix_sl  = float(params.get("sl_points", 0) or 0) * point_size
    fix_tp  = fix_sl * rr
    spread  = max(0.0, float(spread_points or 0.0)) * point_size

    # ⚠ GYERTYÁNKÉNTI SPREAD, ha van. Egyetlen MEDIÁN spread azokban az órákban
    # becsüli alá a költséget, ahol a valóság a legrosszabb — és pont ezeket az
    # órákat kedveli meg a modell, amint idő-jellemzőt kap. Mérve (EURCHF, M1):
    #
    #   09h   17,5 pont spread / 13 pont gyertya-tartomány  =  1,3×
    #   22h   20,1 / 6                                      =  3,4×
    #   23h  103,0 / 7                                      = 14,7×   (rollover)
    #
    # A medián 15,4. A 23h-s címke tehát 6,7×-es kedvezményt kapott, és az így
    # „megtanult" 22–23h-s belépő élesben biztos veszteség. A jelenség NEM az
    # idő-jellemző hibája: az csak MEGTALÁLTA a címke hibáját.
    sp_arr = None
    if "avg_spread" in feats.columns:
        _s = feats["avg_spread"].to_numpy(dtype=float)
        _s = np.where(np.isfinite(_s) & (_s > 0), _s, spread)
        sp_arr = _s

    label_long  = np.zeros(n, dtype=np.int8)
    label_short = np.zeros(n, dtype=np.int8)

    for i in range(n - lookahead):
        if dynamic:
            a = atrs[i]
            if not a or np.isnan(a) or a <= 0:
                continue
            sl = a * sl_mult
            tp = sl * rr
        else:
            sl, tp = fix_sl, fix_tp
            if sl <= 0:
                continue

        sp_i = spread if sp_arr is None else sp_arr[i]

        # ⚠ A BELÉPŐ és az ÚT spreadje KÜLÖN. A gyertyák BID árak.
        #   LONG:  ASK-on nyit (close + spread_i), BID-en zár → az úton NINCS spread.
        #   SHORT: BID-en nyit (close),            ASK-on zár → az úton MINDEN
        #          bárnál az ADOTT bár spreadje számít.
        # A korábbi változat a BELÉPŐ bár spreadjét fagyasztotta rá az egész útra.
        # Ez pont ott hazudik, ahol a spread a legjobban ingadozik: egy EURCHF
        # short 22:30-kor „nyerőnek" számított, holott a 23h-s rollover (103 pont
        # spread!) a stopot azonnal kiütötte — a bid elmozdulása nélkül is. Mérve:
        # a címke 55,2%-ot mondott ugyanazokon a kötéseken, amiken a backtest
        # 17,8%-ot; az eltérések 41%-a mind a 21:45–22:30 sávból jött. A modell
        # tehát ELÉRHETETLEN kimenetre tanult, és az idő-jellemzővel pontosan ezt
        # az órát tanulta meg „jónak".
        entry_l = closes[i] + sp_i          # LONG: ask
        entry_s = closes[i]                 # SHORT: bid
        tp_l, sl_l = entry_l + tp, entry_l - sl
        tp_s, sl_s = entry_s - tp, entry_s + sl

        for j in range(i + 1, i + lookahead + 1):
            if lows[j] <= sl_l:
                break
            if highs[j] >= tp_l:
                label_long[i] = 1
                break
        for j in range(i + 1, i + lookahead + 1):
            sp_j = spread if sp_arr is None else sp_arr[j]
            if highs[j] + sp_j >= sl_s:
                break
            if lows[j] + sp_j <= tp_s:
                label_short[i] = 1
                break

    out = feats.copy()
    out["label_long"]  = label_long
    out["label_short"] = label_short
    return out


# ---------------------------------------------------------------------------
# Osztályozó (LightGBM, fallback: RandomForest) — mint a forrásban
# ---------------------------------------------------------------------------

def _make_classifier(pos_ratio: float):
    """(model, engine_név). A pos_ratio a pozitív osztály súlyozásához."""
    try:
        import lightgbm as lgb
        return lgb.LGBMClassifier(
            n_estimators=200, max_depth=6, min_child_samples=10,
            scale_pos_weight=pos_ratio, n_jobs=-1, random_state=42,
            verbosity=-1,
        ), "lightgbm"
    except ImportError:
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=10,
            class_weight={0: 1, 1: pos_ratio}, random_state=42, n_jobs=-1,
        ), "randomforest"


# A küszöb elfogadásához MINIMÁLISAN szükséges jel-darabszám a kalibrációs
# szeleten. Ez nem kozmetika — enélkül a modell rendszeresen ZAJRA élesedett:
#
#   Ger40 (2026-08-06-i tanítás): long irány BEKAPCSOLVA 12 jel alapján,
#   „75% találattal". Éles OOS-on ugyanez a modell 0 kötést adott.
#
# Az ok szerkezeti: a kalibráció 51 küszöb-jelöltet próbál végig, és a LEGJOBB
# találati arányút választja. Néhány mintából a legjobbat kiválasztva a magas
# win-rate nem képesség, hanem a keresés mellékterméke (maximum-torzítás). A
# régi korlát (n < 6) ezt gyakorlatilag szabadon engedte.
#
# 40: a kalibrációs szelet ~5000 sor, a lefedettség-sapka 8% (≈400 jel), tehát
# a 40 ~1% lefedettség — elérhető, de már ad valamennyi statisztikai alapot
# (0.5 körüli arányon a szórás ~8 százalékpont). Configból hangolható:
# `optimizer.training.min_calibration_signals`.
MIN_CALIB_SIGNALS = 40

# A modell MINIMÁLIS megkülönböztető ereje (AUC a fold-on kívüli
# valószínűségeken). 0,50 = érmefeldobás; 0,52 alatt a küszöb „találati
# aránya" nem képességet mér, hanem azt, hogy 51 jelöltből a legjobbat
# választottuk. Mérve (2026-08-08, 11 pár × 2 irány): az AUC 0,490–0,562
# között szórt, tehát a készlet ÉRDEMBEN nem hordoz irányjelet — a padló
# ezért nem profit-szűrő, hanem a NULLA-jelre élesedés tiltása.
# Configból: `optimizer.training.min_model_auc`.
MIN_MODEL_AUC = 0.52


def oof_proba(X: np.ndarray, y: np.ndarray, ratio: float,
              n_splits: int = 5, purge: int = 32):
    """FOLD-ON KÍVÜLI valószínűségek: minden sorhoz olyan modell adja, amelyik
    azt a sort NEM látta. `(proba, engine)`.

    MIÉRT KELL. A küszöb csak akkor jelent bármit, ha a modell, amire vonatkozik,
    ugyanúgy „idegenként” nézi az adatot, mint majd élesben. A korábbi megoldás
    a train utolsó 20%-án kalibrált egy 80%-on tanított modellel, majd a mentett
    csomagba a TELJES train-en ÚJRATANÍTOTT modellt tette — a küszöb így más
    eloszlásra vonatkozott, mint amire alkalmaztuk. A végső modell a saját
    tanítóadatán már közel tökéletes (AUC 0,87–0,92), tehát ott a 0,81-es küszöb
    a TÉNYLEGES nyerőket válogatta ki; friss adaton (AUC ~0,50) ugyanaz a küszöb
    már csak érmét dob. Innen a 70% → 26% szakadék.

    ⚠ TISZTÍTÁS (purge). A címke `lookahead` gyertyát néz előre, tehát egy sor
    kimenete átfed a következő ~32 soréval. Tisztítás nélkül a fold határán a
    tanító rész a teszt-rész JÖVŐJÉT is látná — a szivárgás pont azt a torzítást
    hozná vissza, ami ellen az egész eljárás szól. Ezért a fold köré `purge`
    sornyi sávot kivágunk a tanító részből."""
    n = len(X)
    proba = np.full(n, np.nan)
    engine = ""
    bounds = np.linspace(0, n, n_splits + 1, dtype=int)
    for k in range(n_splits):
        lo, hi = bounds[k], bounds[k + 1]
        if hi <= lo:
            continue
        mask = np.ones(n, dtype=bool)
        mask[max(0, lo - purge):min(n, hi + purge)] = False   # fold + tisztító sáv
        if mask.sum() < 200:
            continue
        y_tr = y[mask]
        if len(set(y_tr.tolist())) < 2:
            continue
        m, engine = _make_classifier(ratio)
        m.fit(X[mask], y_tr)
        if len(getattr(m, "classes_", [0, 1])) < 2:
            continue
        proba[lo:hi] = m.predict_proba(X[lo:hi])[:, 1]
    return proba, engine


def _calibrate_threshold(proba: np.ndarray, y: np.ndarray,
                         min_wr: float, max_coverage: float,
                         min_signals: int = MIN_CALIB_SIGNALS) -> tuple[float, dict]:
    """Küszöb-választás a kalibrációs szeleten (a forrás két-menetes logikája):
    max win-rate, lefedettség-sapkával; ha a szoros sapka alatt nincs érvényes
    küszöb, lazítunk (2×, majd korlátlan). Nincs érvényes küszöb (WR < min_wr
    VAGY túl kevés jel) → 1.01 (az irány de facto kikapcsolva).

    A `min_signals` a MAXIMUM-TORZÍTÁS elleni védelem — lásd a konstans fölött."""
    best_t, best_score = 1.01, 0.0
    too_few = 0
    for cap in (max_coverage, max_coverage * 2, 1.0):
        for t in np.arange(0.44, 0.95, 0.01):
            mask = proba >= t
            n = int(mask.sum())
            if n < min_signals:
                too_few += 1
                break
            coverage = n / len(proba)
            if coverage > cap:
                continue
            wr = float((y[mask] == 1).mean())
            score = wr ** 2 * coverage ** 0.15
            if score > best_score and wr >= min_wr:
                best_t, best_score = float(t), score
        if best_score > 0.0:
            break
    mask = proba >= best_t
    n = int(mask.sum())
    stats = {
        "threshold":  best_t,
        "signals":    n,
        "coverage":   n / len(proba) if len(proba) else 0.0,
        "win_rate":   float((y[mask] == 1).mean()) if n else 0.0,
        "enabled":    best_score > 0.0,
        "min_signals": int(min_signals),
    }
    if best_score <= 0.0 and too_few:
        stats["reason"] = (f"nincs küszöb legalább {min_signals} jellel "
                           f"(a kevesebb mintán a magas találati arány a keresés "
                           f"mellékterméke lenne)")
    return best_t, stats


def _train_direction(train_all: pd.DataFrame, label_col: str, features: list,
                     min_wr: float, max_coverage: float,
                     min_signals: int = MIN_CALIB_SIGNALS,
                     purge: int = 32, n_splits: int = 5,
                     min_auc: float = MIN_MODEL_AUC) -> tuple[dict | None, dict]:
    """Egy irány (long/short) tanítása.

    A küszöb és az AUC a TELJES train-re vett FOLD-ON KÍVÜLI valószínűségekből
    jön (`oof_proba`) — tehát mindkettő olyan előrejelzéseken alapul, amiket a
    modell „idegenként" adott. A mentett modell utána a teljes train-en tanul, de
    a küszöb már ugyanarra az eloszlásra vonatkozik, amit élesben látni fog.

    Visszaad: (bundle_irány | None, statisztika)."""
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    y_all = train_all[label_col].to_numpy()
    pos, neg = int((y_all == 1).sum()), int((y_all == 0).sum())
    if pos < 10 or neg < 10:
        return None, {"enabled": False, "reason": f"kevés minta (pos={pos}, neg={neg})"}
    ratio = min(neg / max(pos, 1), 5)

    scaler = StandardScaler().fit(train_all[features].to_numpy(dtype=float))
    X_all = scaler.transform(train_all[features].to_numpy(dtype=float))

    # ── Becsületes valószínűségek a TELJES train-re ────────────────────────
    proba, engine = oof_proba(X_all, y_all, ratio, n_splits=n_splits, purge=purge)
    ok = ~np.isnan(proba)
    if ok.sum() < max(200, min_signals * 5):
        return None, {"enabled": False,
                      "reason": f"kevés fold-on kívüli minta ({int(ok.sum())})"}
    p_ok, y_ok = proba[ok], y_all[ok]
    try:
        auc = float(roc_auc_score(y_ok, p_ok))
    except ValueError:
        auc = float("nan")

    # ── AUC-PADLÓ: ne élesedjünk olyan modellre, ami nem tud megkülönböztetni ──
    # Ha az AUC ~0,5, akkor a valószínűség NEM hordoz információt, tehát bármely
    # küszöb „jó" találati aránya kizárólag a keresés mellékterméke (51 jelöltből
    # a legjobb). A `min_signals` a MINTASZÁM felől véd, ez a JELFORRÁS felől — a
    # kettő külön hiba, és 2026-08-08-án mindkettő elő is fordult.
    if auc == auc and auc < min_auc:
        return None, {"enabled": False, "auc": auc, "engine": engine,
                      "train_rows": len(train_all), "oof_rows": int(ok.sum()),
                      "threshold": 1.01, "signals": 0, "win_rate": 0.0,
                      "reason": (f"AUC {auc:.3f} < {min_auc:.2f} — a modell nem "
                                 f"különbözteti meg a kimeneteket, a küszöb "
                                 f"találati aránya szelekciós zaj lenne")}

    thr, stats = _calibrate_threshold(p_ok, y_ok, min_wr, max_coverage, min_signals)

    # ── A mentett modell: a TELJES train-en ────────────────────────────────
    model, engine2 = _make_classifier(ratio)
    model.fit(X_all, y_all)
    if len(getattr(model, "classes_", [0, 1])) < 2:
        return None, {"enabled": False, "reason": "csak egy osztály a train-ben"}

    stats.update({"auc": auc, "engine": engine or engine2,
                  "train_rows": len(train_all), "oof_rows": int(ok.sum()),
                  "tp_rate": float(y_all.mean())})
    return {"model": model, "scaler": scaler, "threshold": thr}, stats


# ---------------------------------------------------------------------------
# Fő belépő — az optimizer fit-dispatch-e hívja (subprocess-ben)
# ---------------------------------------------------------------------------

def train_symbol(symbol: str, df_m15: pd.DataFrame, cfg: dict, pair_cfg: dict,
                 test_start: str, progress_callback=None) -> dict:
    """A pár mindkét irányának tanítása + a modell-csomag mentése.

    df_m15: a TELJES M15 előzmény (az optimizer nem szeleteli train_start-tól —
    a tanítás a saját lookback-jét alkalmazza). A test_start UTÁNI adat sosem
    kerül a tanításba/kalibrációba (azon az optimizer közös OOS-backtestje mér).
    Visszaad: {"params", "train_summary"} vagy {"error"}."""
    steps_total = 6
    _done = 0

    def _step(label: str = ""):
        nonlocal _done
        # Leállítás-kérés (GUI STOP → stop-marker): lépés-határon szakítunk.
        # A RuntimeError-t az optimizer fit-dispatch-e kezeli (user-cancel út).
        try:
            from core.params_store import stop_marker
            if stop_marker(symbol, "ml_ai").exists():
                raise RuntimeError(f"leállítás-kérés a(z) {label or _done}. lépésnél")
        except ImportError:
            pass
        _done += 1
        if progress_callback is not None:
            try:
                progress_callback(_done, steps_total, None)
            except Exception:
                pass

    tr_cfg = (cfg.get("optimizer", {}) or {}).get("training", {}) or {}
    lookahead    = int(tr_cfg.get("label_lookahead_bars", 32))
    min_wr       = float(tr_cfg.get("min_model_win_rate", 0.4))
    max_coverage = float(tr_cfg.get("max_signal_coverage", 0.08))
    min_signals  = int(tr_cfg.get("min_calibration_signals", MIN_CALIB_SIGNALS))
    # A fold-on kívüli kalibráció szeletszáma. Több fold = becsületesebb, de
    # arányosan lassabb (fold-onként egy tanítás). 5 a szokásos kompromisszum.
    n_splits     = max(2, int(tr_cfg.get("calibration_folds", 5)))
    min_auc      = float(tr_cfg.get("min_model_auc", MIN_MODEL_AUC))
    lookback_yrs = float(tr_cfg.get("lookback_years", 3))

    from strategy import get_strategy_by_name
    strategy = get_strategy_by_name("ml_ai")
    params = strategy.base_params(cfg)
    pip = float(pair_cfg["point_size"])

    # ── Jel-idősík ─────────────────────────────────────────────────────────
    # A hívó (optimizer) a TELJES M15 előzményt adja; ha a beállított jel-idősík
    # más, ITT mintázzuk át. A modell így PONTOSAN azokon a gyertyákon tanul,
    # amiket a backtest és az él is látni fog — az idősík a modell-csomagba is
    # bekerül, és eltérésnél a `load_bundle` KIHAGYJA a modellt.
    tf_min = ml_ai.signal_tf_min()
    df_sig = (df_m15 if ml_ai._infer_tf_min(df_m15) == tf_min
              else ml_ai.resample_ohlc(df_m15, tf_min))
    if len(df_sig) < mlf.WARMUP_BARS + 500:
        return {"error": f"túl kevés M{tf_min} gyertya a tanításhoz "
                         f"(n={len(df_sig)}); tölts le hosszabb előzményt"}

    # ── Feature-ök + címkék ────────────────────────────────────────────────
    feats = mlf.build_feature_frame(df_sig, pip)
    _step("features")
    # A pár TIPIKUS spreadje (a `tools/refresh_point_values.py` a valós előzmény
    # mediánjából tölti) — enélkül a címke elérhetetlen célt tűzne ki.
    _spread_pts = float(pair_cfg.get("backtest_spread_points", 0) or 0)
    feats = label_outcomes(feats, params, pip, lookahead, _spread_pts)
    _step("címkézés")

    # ── Session-szűrés (a live/backtest session-kapujával azonos órák) ─────
    sess_s = int(pair_cfg.get("sess_start", 0))
    sess_e = int(pair_cfg.get("sess_end", 24))
    hours = feats.index.hour
    if sess_s == sess_e or (sess_s <= 0 and sess_e >= 24):
        sess = feats
    elif sess_s < sess_e:
        sess = feats[(hours >= sess_s) & (hours < sess_e)]
    else:                                          # átforduló session (pl. 22–6)
        sess = feats[(hours >= sess_s) | (hours < sess_e)]
    sess = sess.dropna(subset=mlf.FEATURES + ["label_long", "label_short"])

    # ── Train-ablak: test_start ELŐTT, lookback_years mélységig ────────────
    ts_test = pd.Timestamp(test_start)
    if sess.index.tzinfo is not None:
        ts_test = ts_test.tz_localize("UTC")
    train_all = sess[sess.index < ts_test]
    if lookback_yrs > 0:
        cutoff = ts_test - pd.DateOffset(years=lookback_yrs)
        train_all = train_all[train_all.index >= cutoff]
    # A címkézés az utolsó `lookahead` sorra nem tud kimenetet → ki a train-ből
    # (a jövője már a test-időszakba lógna át).
    if len(train_all) > lookahead:
        train_all = train_all.iloc[:-lookahead]
    if len(train_all) < 500:
        return {"error": f"túl kevés tanítóadat (n={len(train_all)})"}
    _step("szűrés")

    # ── Irányonkénti tanítás ───────────────────────────────────────────────
    features = list(mlf.FEATURES)
    bundle: dict = {"symbol": symbol, "features": features}
    dir_stats: dict = {}
    for direction, label_col in (("long", "label_long"), ("short", "label_short")):
        # A tisztító sáv PONTOSAN a címke horizontja: ennyi soron át fed át két
        # szomszédos minta kimenete (lásd `oof_proba`).
        d, stats = _train_direction(train_all, label_col, features,
                                    min_wr, max_coverage, min_signals,
                                    purge=lookahead, n_splits=n_splits,
                                    min_auc=min_auc)
        if d is None:
            d = {"model": None, "scaler": None, "threshold": 1.01}
        bundle[direction] = d
        dir_stats[direction] = stats
        log.info("  %s %-5s: %s | küszöb=%.2f | cal-jelek=%s | cal-WR=%.2f | AUC=%s",
                 symbol, direction,
                 "AKTÍV" if stats.get("enabled") else
                 f"KIKAPCSOLVA ({stats.get('reason', 'WR alacsony')})",
                 d["threshold"], stats.get("signals", 0),
                 stats.get("win_rate", 0.0),
                 f"{stats.get('auc', float('nan')):.3f}")
        _step(direction)

    # ── Mentés a modelltárba ───────────────────────────────────────────────
    bundle["meta"] = {
        # A jellemzők NORMALIZÁLÁSI EGYSÉGE. Az SMC-távolságok ezzel osztódnak
        # (`compute_smc`), tehát a modell + scaler ehhez az egységhez van illesztve.
        # A v1.67.0-s pip→pont migráció ezt megváltoztatta: a régi (pip-skálájú)
        # modellek bemenete 10-100×-osra ugrott volna — NÉMÁN, értelmetlen
        # predikciókkal. Ezért bélyegezzük, és a betöltés ellenőrzi.
        "feature_unit": "point",
        # A JEL-IDŐSÍK, amin a modell tanult. Ugyanaz a fajta csendes csapda,
        # mint a `feature_unit`: más idősíkon a bemenet szerkezetileg érvényes
        # marad, csak MÁS gyertyákat ír le. A `load_bundle` ellenőrzi, és
        # eltérésnél kihagyja a modellt (nem kereskedünk vele).
        "signal_tf_min": tf_min,
        "trained_at":   datetime.now(timezone.utc).isoformat(),
        "test_start":   str(ts_test.date()),
        "train_rows":   len(train_all),
        "train_from":   str(train_all.index[0]),
        "train_to":     str(train_all.index[-1]),
        "sess":         [sess_s, sess_e],
        "label":        {"lookahead": lookahead,
                         "dynamic_sltp": bool(params.get("dynamic_sltp", True)),
                         "sl_atr_mult": params.get("sl_atr_mult"),
                         "tp_rr_ratio": params.get("tp_rr_ratio"),
                         "sl_points": params.get("sl_points")},
        "stats":        dir_stats,
    }
    ml_ai.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out = ml_ai.model_path(symbol)
    tmp = out.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(bundle, f)
    tmp.replace(out)
    log.info("  %s — modell mentve: %s", symbol, out)
    _step("mentés")

    # ── Train-összegző (a params-fájlba kerül; a TEST a közös úton fut) ────
    n_sig = sum(s.get("signals", 0) for s in dir_stats.values())
    wrs = [s.get("win_rate", 0.0) for s in dir_stats.values() if s.get("signals", 0)]
    train_summary = {
        "mode":       "training",
        "trades":     int(n_sig),                     # kalibrációs jelek száma
        "win_rate":   float(np.mean(wrs)) if wrs else 0.0,
        "long":       dir_stats.get("long", {}),
        "short":      dir_stats.get("short", {}),
        "train_rows": len(train_all),
    }
    return {"params": dict(params), "train_summary": train_summary}
