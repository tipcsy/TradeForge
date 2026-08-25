"""Egy gyertyát EGYSZER szabad feldolgozni — és a zárt gyertyát, nem a formálódót.

⚠ A LELET (2026-08-25). A felhasználó azt kérdezte, miért nem gyullad ki soha a
Bollinger három köre. A mérés szerint az utolsó 200 H1 gyertyán a kilenc pár
együtt a gyertyák **87%-án** mutatott volna legalább egy égő kört — a képernyőn
viszont soha egy sem.

AZ OK NEM A KIJELZÉS VOLT. A motor ciklusa **10 másodperc**, és minden körben
meghívja az `on_bar_close`-t. A `bollinger_squeeze` viszont minden híváskor
LÉPTET egyet ugyanazon a zárt gyertyán:

    bars_since_off:  0 → 1 → 2 → … → 6      (60 másodperc alatt)

A belépési ablak (`max_bars_after_squeeze = 5` **H1 gyertya**, azaz ~5 óra) így
a valóságban ~**50 másodpercig** élt. Ez nem kijelzési hiba: a stratégia ÉLES
jelzése is ezen múlik.

⚠ ÉS AMIÉRT NÉMA VOLT: a backtest hookja (`bt_on_high_close`) gyertyánként
EGYSZER fut, tehát a backtest a helyes viselkedést mérte. A live és a backtest
csendben KÉT KÜLÖNBÖZŐ stratégiát futtatott — a mért eredmény nem arról szólt,
ami élesben történik. Ez a projekt visszatérő hibaosztálya (lásd a
viz ↔ backtest paritást).

A KÉT INVARIÁNS, amit ez a teszt őriz MINDEN stratégiára:

  1. **Idempotencia.** Ugyanazzal az adattal többször hívva az `on_bar_close`
     az ELSŐ hívás után nem változtathat az állapoton, és nem adhat újabb jelet.
  2. **Zárt gyertya.** A döntés az utolsó ZÁRT soron születik, nem a formálódón
     — különben a live megelőzi a backtestet, és a jel „eltűnhet", ha a gyertya
     még elmozdul.

A `wpr_sma` és az `ml_ai` (kézzel írva) mindkettőt teljesítette; a
`bollinger_squeeze` és a `candle_level_break` (vázlatból) egyiket sem.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import pandas as pd

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core.params_store import params_file
from strategy import get_strategy_by_name, registered_strategy_names
from strategy.base import MarketData
from strategy.settings import config_for_strategy, load_config

cfg = load_config("config.json")


def _allapot(st):
    """A state összehasonlítható pillanatképe.

    ⚠ `__slots__`-os állapotot is kezelni kell: a `__dict__` ilyenkor nincs, és
    egy `repr()`-re visszaéss némán kivételt adna a későbbi összehasonlításnál."""
    d = getattr(st, "__dict__", None)
    if not isinstance(d, dict):
        mezok = getattr(type(st), "__slots__", ()) or ()
        d = {k: getattr(st, k, None) for k in mezok}
    return {k: (str(v) if hasattr(v, "isoformat") else v)
            for k, v in sorted(d.items()) if not k.startswith("_")}


def _md_for(strat, sym="Ger40", n=None):
    f = params_file(sym, strat.name)
    if f.exists():
        p = dict(json.load(open(f, encoding="utf-8")).get("params", {}))
    else:
        p = dict(strat.base_params(config_for_strategy(cfg, strat.name)) or {})
    # ⚠ A VÉGREHAJTÁSI paraméterek (atr_period, spread-kapu…) KÜLÖN fájlból
    # jönnek (`core/execution_params`), nem a stratégia configából — a motor is
    # így állítja össze (`live_trader.default_params`). Nélkülük a `wpr_sma`
    # `KeyError: 'atr_period'`-dal szállna el.
    from core import execution_params as _ep
    p.update(_ep.load_execution_params(sym, cfg) or {})
    pc = cfg["pairs"].get(sym, {})
    p.update(symbol=sym, point_size=pc.get("point_size", 0.01))
    p.setdefault("sess_start", pc.get("sess_start", 0))
    p.setdefault("sess_end", pc.get("sess_end", 24))
    bars = {}
    for tf in strat.timeframes():
        pq = ROOT / "data" / tf.label.lower() / f"{sym}.parquet"
        if not pq.exists():
            return None
        try:
            mennyi = n or max(strat.signal_warmup_bars(p, tf.label),
                              strat.warmup_bars(p, tf.label))
        except Exception:
            mennyi = n or strat.warmup_bars(p, tf.label)
        bars[tf.label] = pd.read_parquet(pq).tail(int(mennyi) + 50)
    return MarketData(symbol=sym, params=p, bars=bars)


nevek = registered_strategy_names()
check("van bejegyzett stratégia", bool(nevek), ", ".join(nevek))

for nev in nevek:
    strat = get_strategy_by_name(nev)
    md = _md_for(strat)
    if md is None:
        print(f"      ({nev}: nincs parquet — kihagyva)")
        continue

    # ── 1. IDEMPOTENCIA ────────────────────────────────────────────────
    # ⚠ A motor 10 MÁSODPERCENKÉNT hív, a jel-gyertya viszont 15-60 PERCES.
    # Ugyanarra a zárt gyertyára tehát tucatnyi hívás jut.
    st = strat.new_signal_state(md.symbol)
    st, elso_jel = strat.on_bar_close(st, md)

    # ⚠ AZ ÁLLAPOTOT AZ ABLAKBA ÁLLÍTJUK, ha a stratégia számlálót vezet.
    # A hibás ág („minden hívás léptet") CSAK akkor fut, ha a számláló aktív
    # (>= 0). A természetes állapot jellemzően −1 (nincs folyamatban lévő
    # szetup), és ott a hiba NÉMÁN átmenne a teszten — pontosan ezért maradt
    # észrevétlen hónapokig.
    for _mezo in ("bars_since_off",):
        if isinstance(getattr(st, _mezo, None), int):
            setattr(st, _mezo, 0)

    pillanat = _allapot(st)

    jelek = []
    for _ in range(12):                       # 2 perc a motor ütemében
        st, sig = strat.on_bar_close(st, md)
        jelek.append(sig)

    _most = _allapot(st)
    _elteres = {k: f"{pillanat.get(k)!r}→{v!r}"
                for k, v in _most.items() if pillanat.get(k) != v}
    check(f"⚠ '{nev}': ismételt hívás NEM változtat az állapoton",
          not _elteres, str(_elteres))

    check(f"'{nev}': ...és nem ad újabb jelet ugyanarra a gyertyára",
          all(s == "NONE" for s in jelek),
          f"{[s for s in jelek if s != 'NONE']}")

    # ── 2. A ZÁRT GYERTYA ──────────────────────────────────────────────
    # ⚠ FUNKCIONÁLIS próba: a FORMÁLÓDÓ (utolsó, még nyitott) gyertyát
    # drámaian elmozdítjuk a JEL-idősíkon. Ha a döntés a zárt soron születik,
    # ennek NINCS hatása. Ha a formálódón, akkor a live megelőzi a backtestet
    # — és a jel el is tűnhet, ha a gyertya később visszafordul.
    _jel_tf = strat.timeframes()[0].label

    st_a = strat.new_signal_state(md.symbol)
    st_a, jel_a = strat.on_bar_close(st_a, md)

    _b = {k: v.copy() for k, v in md.bars.items()}
    _d = _b[_jel_tf]
    _oszlop = [c for c in ("close", "high", "low", "open") if c in _d.columns]
    _i = _d.index[-1]
    for _c in _oszlop:                        # +5% az utolsó (nyitott) soron
        _d.loc[_i, _c] = float(_d[_c].iloc[-1]) * 1.05
    md_b = MarketData(symbol=md.symbol, params=md.params, bars=_b)
    st_b = strat.new_signal_state(md.symbol)
    st_b, jel_b = strat.on_bar_close(st_b, md_b)

    check(f"⚠ '{nev}': a döntés a ZÁRT gyertyán születik "
          f"(a formálódó elmozdítása nem számít)",
          jel_a == jel_b and _allapot(st_a) == _allapot(st_b),
          f"jel: {jel_a} vs {jel_b}")

print()

# ── 3. LIVE ↔ BACKTEST ÁLLAPOT-PARITÁS ─────────────────────────────────
# ⚠ EZ A LÉNYEGI. A backtest hookja gyertyánként EGYSZER fut. Ha a live
# `on_bar_close` ugyanazon az adaton MÁS állapotot ad, akkor a két út két
# külön stratégiát futtat — és a mért eredmény nem arról szól, ami élesben
# történik. Pontosan ez volt a Bollinger baja.
# ⚠ Csak az a két stratégia, amelyik UGYANAZT az állapotosztályt használja a
# live és a backtest oldalon (`new_signal_state` ≡ `bt_new_state`). A `wpr_sma`
# és az `ml_ai` szándékosan más alakú állapotot vezet a két úton (M1-kézbesítés,
# illetve modell-kontextus), ott ez az összehasonlítás zajt adna.
_MEZOK = {"bollinger_squeeze_breakout": ("bars_since_off", "in_squeeze"),
          "candle_level_break": ("broke_up", "broke_dn",
                                 "retested_up", "retested_dn")}
for nev in ("bollinger_squeeze_breakout", "candle_level_break"):
    strat = get_strategy_by_name(nev)
    md = _md_for(strat)
    if md is None:
        continue
    hi, _lo = strat.bt_indicators(md.bars[strat.timeframes()[0].label], None, md.params)

    # Backtest: gyertyánként EGYSZER, az utolsó ZÁRT sorig.
    bt = strat.bt_new_state(md.symbol)
    for i in range(len(hi) - 1):
        bt = strat.bt_on_high_close(bt, hi.iloc[i], md.params)

    # Live: a motor ütemében (10 mp), ugyanarra az adatra.
    lv = strat.new_signal_state(md.symbol)
    for _ in range(30):
        lv, _ = strat.on_bar_close(lv, md)
    # ⚠ A backtest állapota a TELJES ablak visszajátszásából jön; a live-énak
    # ugyanoda kell érnie. Ha a live nem játssza vissza az ablakot, itt −1 marad,
    # miközben a backtest egy folyamatban lévő szetupot lát — a motor tehát
    # „nem látja" azt, amit a backtest mért.

    _elt = {m: f"live={getattr(lv, m, None)!r} vs bt={getattr(bt, m, None)!r}"
            for m in _MEZOK[nev]
            if getattr(lv, m, None) != getattr(bt, m, None)}
    check(f"⚠ '{nev}': a live állapot EGYEZIK a backtestével "
          f"({', '.join(_MEZOK[nev])})",
          not _elt, str(_elt))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
