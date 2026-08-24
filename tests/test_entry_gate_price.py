"""A jel-replay a TF-együttállás kapunak ÁRAT adjon át — ne indikátor-értéket.

⚠ A LELET (2026-08-24, a felhasználó vette észre): *„Most kaptam egy jelzést,
GER-40-en viszont a VIZ semmit sem mutat."*

A `wpr_sma.visual_objects` a kapunak a `cw` változót adta át azzal a kommenttel,
hogy az „a döntést hozó M1-gyertya záróára" — csakhogy a `cw` a `m1_wprs[j]`,
azaz a **Williams %R** értéke (−100…0). A kapu idősíkonként `sign(ár − SMA)`-t
néz; egy −44-es „ár" MINDEN idősík SMA-ja alatt van, tehát a kapu válasza az
értéktől FÜGGETLENÜL `BUY=False, SELL=True` volt.

KÖVETKEZMÉNY, és amiért ez nem kozmetikai hiba:

  * a charton **SOHA nem jelent meg BUY jelölő** a kapuzott párokon;
  * a SELL jelölők viszont **szűrés nélkül** mentek ki — olyanok is, amiket a
    motor a kapuval blokkolt volna;
  * tehát a viz↔backtest paritás MINDKÉT irányban sérült, miközben a chart
    magabiztosan mutatott valamit.

Mérve a hiba napján (Ger40, ~50 napos ablak): kapu nélkül 626 BUY + 330 SELL,
a hibás kapuval **0 BUY + 330 SELL**, a javítottal 317 BUY + 189 SELL.

AZ ŐRZÖTT INVARIÁNS (funkcionális, nem forrás-keresés): minden érték, amit a
stratégia a kapunak átad, legyen egy VALÓDI M1 ZÁRÓÁR az adatablakból. Ez a
megfogalmazás egy indikátor-értéket, egy elgépelt indexet és egy elcsúszott
gyertyát is elkap — nem csak azt az egy hibát, ami megtörtént.
"""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()
logging.disable(logging.ERROR)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy import get_strategy_by_name
from strategy.base import MarketData
from strategy.settings import load_config, config_for_strategy
from core.execution_params import load_execution_params
from trading.backtest import load_data
from trading.live_trader import default_params

cfg = load_config("config.json")
st = get_strategy_by_name("wpr_sma")
cs = config_for_strategy(cfg, "wpr_sma")

sym = next((s for s in ("Ger40", "UsaTec", "UsaInd", "EURUSD")
            if s in (cfg.get("pairs") or {})), None)
d15, d1 = (load_data(sym) if sym else (None, None))

if d15 is None or d1 is None or len(d15) < 4000:
    check("van adat az ellenőrzéshez", False, f"{sym}: nincs elég parquet")
else:
    prm = {**default_params(st, cs), **load_execution_params(sym, cfg),
           "point_size": cfg["pairs"][sym].get("point_size", 0.0001)}
    bars = {"M15": d15.iloc[-4000:], "M1": d1.iloc[-20000:]}
    m1_closes = set(round(float(x), 8) for x in bars["M1"]["close"].to_numpy())
    lo = float(bars["M1"]["low"].min())
    hi = float(bars["M1"]["high"].max())

    seen = []            # amit a kapu KAPOTT

    def spy(t, price, direction):
        seen.append((int(t), float(price), direction))
        return True      # mindent átenged → a rekordok száma a felső korlát

    md = MarketData(symbol=sym, params=prm, bars=bars, show_signals=True)
    md.entry_gate = spy
    recs = []
    md.on_entry_record = recs.append
    st.visual_objects(md)

    check("a kapu egyáltalán meg lett hívva", len(seen) > 0, f"{len(seen)} hívás")

    # ── A LÉNYEG: amit a kapu kap, az ÁR legyen ────────────────────────────
    bad_range = [p for _t, p, _d in seen if not (lo <= p <= hi)]
    check("⚠ a kapunak átadott érték az ÁRSÁVBAN van",
          not bad_range,
          f"{len(bad_range)} kívül esik, pl. {bad_range[:3]} "
          f"(sáv: {lo:.2f}..{hi:.2f})")

    not_close = [p for _t, p, _d in seen if round(p, 8) not in m1_closes]
    check("...és pontosan egy VALÓDI M1 záróár", not not_close,
          f"{len(not_close)} nem záróár, pl. {not_close[:3]}")

    # ⚠ Az indikátor-érték konkrét cáfolata: a WPR sávja −100…0. Ha bármelyik
    # átadott érték ebbe esne egy olyan instrumentumon, ahol az ár POZITÍV, az
    # önmagában a régi hiba.
    if lo > 0:
        wpr_like = [p for _t, p, _d in seen if -100.0 <= p <= 0.0]
        check("...és nem indikátor-érték (a WPR −100…0 sávja)", not wpr_like,
              f"{len(wpr_like)} esik a WPR sávba")

    # ── A TÜNET, ami a felhasználónak feltűnt ─────────────────────────────
    # Mindent átengedő kapuval MINDKÉT irány jelölője megszületik. A hibás
    # kódnál a kapu válasza az átadott értéktől független volt, és a BUY-ok
    # KIVÉTEL NÉLKÜL elvesztek — a chart némán csak SELL-eket mutatott.
    dirs = {r["d"] for r in recs}
    check("mindkét irány belépője megszületik", dirs == {"BUY", "SELL"},
          str(sorted(dirs)))

    # ── PARITÁS: a viz és a backtest UGYANAZT az árat adja a kapunak ───────
    # A backtest a belépő M1-gyertya záróárát adja át (`_bar_c`). Ha a viz
    # ugyanazt a gyertyát ugyanazzal az árral kérdezi, a két kapu ugyanúgy dönt.
    _t_to_close = {int(t.timestamp()): round(float(c), 8)
                   for t, c in zip(bars["M1"].index, bars["M1"]["close"])}
    mismatch = [(t, p) for t, p, _d in seen
                if t in _t_to_close and _t_to_close[t] != round(p, 8)]
    check("a kapott ár a HÍVOTT IDŐPONT gyertyájáé (nincs elcsúszás)",
          not mismatch, f"{len(mismatch)} csúszik, pl. {mismatch[:2]}")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
