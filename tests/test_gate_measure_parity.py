"""A KAPU-MERES ATKOLTOZOTT — es ugyanazt kell adnia (0007).

⚠ MI VALTOZOTT. A kapuk merese eddig a `live_trader` egyik fuggvenyenek
kozepen elt, kapunkent kulon, kezzel beirt blokkban. Ez azt jelentette, hogy egy
kapu NEM volt „egy darabban mozdithato": a modulja a `gates/` alatt volt, a
merese meg a motorban. Egy `.tfg`-vel telepitett kapu igy a lemezen ult volna,
listaban sehol, es a motor SOHA nem hivta volna.

Mostantol minden kapu a SAJAT `measure(ctx)`-et adja, es a keret hivja vegig
oket. A KOD SZO SZERINT koltozott — de ezt bizonyitani kell, nem allitani.

⚠ EZ EGY DIFFERENCIAL-TESZT. A REGI, inline logika itt SZO SZERINT szerepel
(`_regi_*` fuggvenyek), es minden bemeneten osszevetjuk az UJ, modularis uttal.
Ha a ketto barhol elter, a teszt megnevezi a bemenetet.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

from core import gate_bands as _gb  # noqa: E402
from core import gates as G         # noqa: E402
from gates import cost_gate as _cg  # noqa: E402
from gates import momentum as _mom  # noqa: E402
from gates import tf_align as _tfa  # noqa: E402
from gates import vol_baseline as _vb  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def _egyezik(a, b) -> bool:
    """Ket ertek egyezese NaN-TUDATOSAN (`nan != nan` a Pythonban)."""
    if isinstance(a, float) and isinstance(b, float):
        if a != a and b != b:          # mindketto NaN
            return True
    return a == b


class Ds:
    def __init__(self, market_state=""):
        self.market_state = market_state
        self.momentum = None


class SymInfo:
    def __init__(self, spread=0.0):
        self.spread = spread


# ── A REGI, INLINE LOGIKA — szo szerint a `live_trader`-bol ─────────────
def _regi_spread(spread_ok, pts, cap, bands):
    failed = not spread_ok
    level = _gb.scalar_level(pts, cap) if bands.get("spread") else None
    return failed, level


def _regi_tf(cfg, symbol, strat, signal, closes, bands):
    tf_gate_ok, level = True, None
    if signal != "NONE":
        try:
            _en, _tfs, _sma, _gate = _tfa.config_for(cfg, symbol, strat)
            if _en:
                _cl = closes(_tfs, _sma + 5)
                _dir, _signs = _tfa.alignment(_cl, _tfs, _sma)
                tf_gate_ok = _tfa.gate_ok(_dir, signal)
                if bands.get("tf_align"):
                    level = _tfa.aligned_count(_signs, signal)
        except Exception:
            tf_gate_ok = True
    return (not tf_gate_ok), level


def _regi_market(cfg, symbol, signal, ds):
    ok, level = True, None
    if signal != "NONE":
        _cat = getattr(ds, "market_state", "") or ""
        if _cat and _cat in G.market_adverse(cfg or {}, symbol):
            ok = False
        level = _cat
    return (not ok), level


def _regi_momentum(cfg, pair_cfg, symbol, strat, signal, closes, ds, bands):
    ok, level = True, None
    if signal != "NONE":
        try:
            _mcfg = G.momentum_config(pair_cfg, cfg)
            _mval = _mom.rpm(closes(_mom.needed_timeframes(_mcfg),
                                    _mom.needed_bars(_mcfg)), _mcfg)
            ds.momentum = _mval
            _mmode = G.mode_for(cfg or {}, symbol, strat)
            if _mmode in (G.MOM_IDLE, G.MOM_BOTH) and _mom.is_idle(_mval, _mcfg):
                ok = False
            if _mmode in (G.MOM_DIR, G.MOM_BOTH):
                _mdir = _mom.direction(_mval)
                if _mdir and _mdir != signal:
                    ok = False
            if bands.get("momentum"):
                level = _gb.momentum_level(_mval, signal, _mmode, _mcfg)
        except Exception:
            ok = True
    return (not ok), level


def _regi_vol(hi_row, params, bands):
    failed = bool(hi_row is not None
                  and _vb.failed(hi_row.get("atr"), params, hi_row.get("atr_avg", 0)))
    level = (_gb.level_volatility(hi_row.get("atr"), params, hi_row.get("atr_avg", 0))
             if hi_row is not None and bands.get("volatility") else None)
    return failed, level


def _regi_cost(sl, tp, sym_info, pair_cfg, cfg, bands):
    _spr = float(getattr(sym_info, "spread", 0) or 0)
    _cap = G.cost_max_distortion(pair_cfg, cfg)
    failed = _cg.failed(sl, tp, _spr, _cap)
    level = (_gb.scalar_level(_cg.distortion(sl, tp, _spr), _cap)
             if bands.get("cost") else None)
    return failed, level


# ── A BEMENETEK ────────────────────────────────────────────────────────
def _closes(tfs, n):
    """Determinisztikus zaroarak — emelkedo sorozat minden idosikra."""
    return {tf: [100.0 + i * 0.5 for i in range(n)] for tf in (tfs or [])}


def _closes_ures(tfs, n):
    return {}


CFG_ALAP = {"pairs": {"X": {}}}
CFG_ADVERSE = {"gates": {"market": {"adverse": ["dead", "uncertain"]}}}
CFG_MOM = {"gates": {"momentum": {"mode": "both"}}}

ESETEK = []
for signal in ("BUY", "SELL", "NONE"):
    for bands in ({}, {"spread": [[0.5, "reduce"]], "tf_align": [[1, "block"]],
                       "momentum": [[0.5, "reduce"]], "volatility": [[0.5, "block"]],
                       "cost": [[0.5, "block"]]}):
        for cfg in (CFG_ALAP, CFG_ADVERSE, CFG_MOM):
            for cl in (_closes, _closes_ures):
                ESETEK.append((signal, bands, cfg, cl))

# ── 1. SPREAD ──────────────────────────────────────────────────────────
_e = 0
for signal, bands, cfg, cl in ESETEK:
    for ok in (True, False):
        for pts, cap in ((1.0, 2.0), (3.0, 2.0), (0.0, 0.0)):
            ctx = G.GateCtx(symbol="X", strategy="s", signal=signal, cfg=cfg,
                            spread_ok=ok, spread_points=pts, spread_cap=cap,
                            bands=bands)
            if G.measure("spread", ctx) != _regi_spread(ok, pts, cap, bands):
                _e += 1
check("SPREAD: az új mérés = a régi", _e == 0, f"{_e} eltérés")

# ── 2. TF-EGYUTTALLAS ──────────────────────────────────────────────────
_e = 0
for signal, bands, cfg, cl in ESETEK:
    ctx = G.GateCtx(symbol="X", strategy="s", signal=signal, cfg=cfg,
                    closes=cl, bands=bands)
    if G.measure("tf_align", ctx) != _regi_tf(cfg, "X", "s", signal, cl, bands):
        _e += 1
check("TF-EGYÜTTÁLLÁS: az új mérés = a régi", _e == 0, f"{_e} eltérés")

# ── 3. PIAC ────────────────────────────────────────────────────────────
_e = 0
for signal, bands, cfg, cl in ESETEK:
    for cat in ("", "dead", "uncertain", "trend", "range"):
        ctx = G.GateCtx(symbol="X", strategy="s", signal=signal, cfg=cfg,
                        ds=Ds(cat), bands=bands)
        if G.measure("market", ctx) != _regi_market(cfg, "X", signal, Ds(cat)):
            _e += 1
check("PIAC: az új mérés = a régi", _e == 0, f"{_e} eltérés")

# ── 4. LENDULET ────────────────────────────────────────────────────────
_e = 0
for signal, bands, cfg, cl in ESETEK:
    _ds_uj, _ds_regi = Ds(), Ds()
    ctx = G.GateCtx(symbol="X", strategy="s", signal=signal, cfg=cfg,
                    pair_cfg={}, ds=_ds_uj, closes=cl, bands=bands)
    if G.measure("momentum", ctx) != _regi_momentum(
            cfg, {}, "X", "s", signal, cl, _ds_regi, bands):
        _e += 1
    # ⚠ A MELLEKHATAS is egyezzen: a fordulatszam a kijelzes-allapotba iródik.
    # ⚠ NaN-TUDATOSAN: adathianynal a fordulatszam `nan`, es `nan != nan` —
    # a naiv osszehasonlitas 12 HAMIS elterest jelzett, mikozben a ket ag
    # ugyanazt adta. (Elsore epp ebbe futottam bele.)
    if not _egyezik(_ds_uj.momentum, _ds_regi.momentum):
        _e += 1
check("LENDÜLET: az új mérés = a régi (a mellékhatással együtt)", _e == 0,
      f"{_e} eltérés")

# ── 5. VOLATILITAS ─────────────────────────────────────────────────────
_e = 0
_PAR = {"atr_min_pct": 0.3, "atr_max_pct": 2.0, "atr_avg_ref": 1.0}
for signal, bands, cfg, cl in ESETEK:
    for hi in (None, {"atr": 0.1, "atr_avg": 1.0}, {"atr": 1.0, "atr_avg": 1.0},
               {"atr": 9.0, "atr_avg": 1.0}):
        ctx = G.GateCtx(symbol="X", strategy="s", signal=signal, cfg=cfg,
                        params=_PAR, hi_row=hi, bands=bands)
        if G.measure("volatility", ctx) != _regi_vol(hi, _PAR, bands):
            _e += 1
check("VOLATILITÁS: az új mérés = a régi", _e == 0, f"{_e} eltérés")

# ── 6. KOLTSEG (terv-fazis) ────────────────────────────────────────────
_e = 0
for signal, bands, cfg, cl in ESETEK:
    for sl, tp, spr in ((100.0, 200.0, 2.0), (10.0, 20.0, 8.0), (50.0, 0.0, 1.0)):
        si = SymInfo(spr)
        ctx = G.GateCtx(symbol="X", strategy="s", signal=signal, cfg=cfg,
                        pair_cfg={}, sl_points=sl, tp_points=tp, sym_info=si,
                        bands=bands)
        if G.measure("cost", ctx) != _regi_cost(sl, tp, si, {}, cfg, bands):
            _e += 1
check("KÖLTSÉG: az új mérés = a régi", _e == 0, f"{_e} eltérés")


# ── 7. A SZERKEZET, ami ezt egyaltalan lehetove teszi ──────────────────
check("minden kapunak van MODULJA", all(G.gate_module(k) is not None for k in G.KEYS),
      str([k for k in G.KEYS if G.gate_module(k) is None]))
check("...és mindegyiknek `measure(ctx)`-e",
      all(callable(getattr(G.gate_module(k), "measure", None)) for k in G.KEYS))
check("a FÁZISOK a valóságot tükrözik",
      G.keys_in_phase(G.PHASE_SIGNAL) == ("spread", "tf_align", "market",
                                          "momentum", "volatility")
      and G.keys_in_phase(G.PHASE_PLAN) == ("cost",),
      f"{G.keys_in_phase(G.PHASE_SIGNAL)} | {G.keys_in_phase(G.PHASE_PLAN)}")

# ⚠ A MOTOR NE MERJEN TOBBE KAPUNKENT. Ez a regresszio-or: a kezi blokkok
# konnyen visszakerulnek egy kesobbi szerkesztessel, es akkor a `.tfg`-vel
# telepitett kapu megint nemán tetlen lenne.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
for _k in ("SPREAD", "TF_ALIGN", "MARKET", "MOMENTUM", "VOLATILITY", "COST"):
    check(f"a motor nem méri kézzel a(z) {_k} kaput",
          f"_gate_failed[_gates.{_k}]" not in _lt)
check("...hanem a fázis szerinti hurokból", "keys_in_phase" in _lt)

# FAIL-OPEN: egy elszallo meres NEM blokkolhat.
class _Robban:
    @staticmethod
    def measure(ctx):
        raise RuntimeError("szandekos")


_regi_mod = G.gate_module
try:
    G.gate_module = lambda k: _Robban
    check("elszálló mérés → NEM blokkol (fail-open)",
          G.measure("spread", G.GateCtx()) == (False, None))
finally:
    G.gate_module = _regi_mod

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
