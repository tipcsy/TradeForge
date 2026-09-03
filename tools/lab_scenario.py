"""KÉZI LABORATÓRIUM — „mi lett volna, ha itt lépek be?"

    python tools/lab_scenario.py <forgatokonyv.json>
    python tools/lab_scenario.py --minta > sajat.json     (kiinduló sablon)

⚠ MIÉRT NEM ÍRTAM SAJÁT SZIMULÁTORT. A labor kérdése — „mi lett volna, ha itt
lépek be és itt mentesítem a kockázatot" — csak akkor válaszolható meg
hitelesen, ha UGYANAZ a végrehajtás fut, mint a backtestben. Egy külön
szimulátor a saját hibáit mérné, és a projekt épp ettől szenvedett már
többször (viz ↔ backtest paritás, a `BacktestReplayer` v4, a kutató-labor
`_map_to` hibája). Ezért ez a szkript **nem szimulál semmit**: a kézi belépőket
beadja a `trading.backtest.run_pair`-nek, és az futtatja őket — a teljes
menedzsmenttel (BE, trailing, részleges zárás, ráépítés, kiszállási jel).

── HOGYAN ─────────────────────────────────────────────────────────────────
A `run_pair` elfogad egy előre megépített JELÖLT-LISTÁT (`SignalSeries`): az
mondja meg, MELYIK M1 báron van belépő-jel. A labor ezt a listát cseréli le a
te belépőidre — minden más (kapuk, méretezés, SL/TP, menedzsment) változatlan.

⚠ EBBŐL KÖVETKEZIK A PARITÁS: nem MÉRNI kell, hanem szerkezeti. Ha a
forgatókönyv `"use_strategy_signals": true`, az eredmény bitre annyi, mint egy
sima backtest ugyanarra az időszakra — a teszt ezt ellenőrzi is.

── A FORGATÓKÖNYV ─────────────────────────────────────────────────────────
{
  "symbol": "UsaTec",
  "strategy": "wpr_sma",
  "from": "2026-08-27 00:00",
  "to":   "2026-08-27 23:59",
  "entries": [ {"time": "2026-08-27 01:30", "direction": "BUY",
                "sl": 29516.4, "tp_rr": 2.0} ],   // sl/tp_rr elhagyhato
  "breakeven_at": "2026-08-27 02:10",      // elhagyható
  "rr_preset": "off",                      // off | halving | shield | …
  "rr": {"breakeven_pct": 0.5,             // ennyi R-nel a stop a nyitora
         "trail_activation_atr": 1.0,      // ennyi ATR utan indul a trailing
         "trail_distance_atr": 1.5},       // ilyen tavolsagra huz
  "build": false,                          // pozícióépítés be/ki
  "balance": 1000.0
}

⚠ AZ IDŐK A SZERVER (adat) IDEJÉBEN értendők — ugyanabban, amit a charton
látsz. A `from`/`to` a vizsgált szakasz; a belépőknek ezen belül kell lenniük.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import pandas as pd

MINTA = {
    "symbol": "UsaTec",
    "strategy": "wpr_sma",
    "from": "2026-08-27 00:00",
    "to": "2026-08-27 23:59",
    "entries": [{"time": "2026-08-27 01:30", "direction": "BUY"}],
    "breakeven_at": None,
    "rr_preset": "off",
    "build": False,
    "balance": 1000.0,
    "use_strategy_signals": False,
    "exec_gates": False,
}


def _hiba(uzenet: str) -> None:
    """⚠ Kimondjuk, MI a baj, és általában azt is, hogyan javítsd. Egy labor,
    ami csak annyit mond, hogy „nem sikerült", használhatatlan."""
    print(f"HIBA: {uzenet}")
    raise SystemExit(2)


def _szoveg(nyers: bytes) -> str:
    """A fájl szövege — BÁRMELYIK szokásos Windows-kódolásban.

    ⚠ A SAJÁT DOKUMENTÁLT INDÍTÁSOM TÖRT MEG EZEN. A súgó azt mondja:
    `python tools/lab_scenario.py --minta > sajat.json` — csakhogy a Windows
    PowerShell (5.1) `>` operátora UTF-16LE-t ír BOM-mal. Egy UTF-8-ként
    beolvasott UTF-16 fájl értelmetlen, és a labor azt mondaná rá: „a
    forgatókönyv nem érvényes JSON" — ami IGAZ, de a felhasználót a saját
    mintaállománya ellen fordítja. A BOM egyértelműen megmondja, mi ez."""
    import codecs
    for bom, kod in ((codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
                     (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16'),
                     (codecs.BOM_UTF8, 'utf-8-sig')):
        if nyers.startswith(bom):
            return nyers.decode(kod)
    return nyers.decode("utf-8")


def betolt(ut: Path) -> dict:
    try:
        fk = json.loads(_szoveg(ut.read_bytes()))
    except FileNotFoundError:
        _hiba(f"nincs ilyen fájl: {ut}")
    except UnicodeDecodeError as ex:
        _hiba(f"a forgatókönyv kódolása nem olvasható ({ex}) — mentsd UTF-8-ban")
    except json.JSONDecodeError as ex:
        _hiba(f"a forgatókönyv nem érvényes JSON ({ex})")
    for kulcs in ("symbol", "from", "to"):
        if not fk.get(kulcs):
            _hiba(f"hiányzó kulcs a forgatókönyvben: '{kulcs}'")
    return fk


def _ido(x, mit: str, tz=None):
    """Időpont az ADAT időzónájában.

    ⚠ A parquet indexe időzóna-tudatos (UTC = a bróker szerver-ideje), a
    forgatókönyvbe viszont naiv időt írsz — ahogy a charton látod. A kettő
    összehasonlítása `TypeError`-t dob, méghozzá a backtest FORRÓ HURKÁBAN, ha
    nem itt, a határon rendezzük el."""
    try:
        t = pd.Timestamp(x)
    except Exception:
        _hiba(f"értelmezhetetlen időpont ({mit}): {x!r}")
    if tz is not None:
        t = t.tz_localize(tz) if t.tzinfo is None else t.tz_convert(tz)
    return t


def futtat(fk: dict) -> dict:
    from strategy import get_strategy_by_name
    from strategy.settings import config_for_strategy, load_config
    from trading import backtest as bt
    from trading.live_trader import default_params, strategy_params

    cfg = load_config(ROOT / "config.json")
    sym = str(fk["symbol"])
    pair_cfg = (cfg.get("pairs") or {}).get(sym)
    if not pair_cfg:
        _hiba(f"a(z) {sym} nincs a config.json `pairs` blokkjában")
    strat_nev = str(fk.get("strategy") or "").strip()
    if not strat_nev:
        from strategy import default_strategy_name
        strat_nev = default_strategy_name(cfg)
    try:
        strategy = get_strategy_by_name(strat_nev)
    except Exception:
        _hiba(f"ismeretlen stratégia: {strat_nev!r}")
    cs = config_for_strategy(cfg, strat_nev)
    params = strategy_params(sym, strat_nev, cs, fallback=default_params(strategy, cs))

    _sajat_belepo = not bool(fk.get("use_strategy_signals", False))
    _kapuk = bool(fk.get("exec_gates", not _sajat_belepo))
    if _sajat_belepo and not _kapuk:
        # ⚠ A STRATÉGIA SAJÁT VOLATILITÁS-SZŰRŐJE IS FELÜLÍRANDÓ. A `bt_entry`
        # hook nem csak a mérethez kell: ha a gyertya a `atr_min_pct` /
        # `atr_max_pct` sávján kívül esik, `None`-t ad, és a belépő KIMARAD —
        # a végrehajtási kapuktól FÜGGETLENÜL. Kézi laborban ez azt jelentené,
        # hogy a „mi lett volna, ha itt lépek be" kérdésre gyakran az jön
        # vissza, hogy „nem léptél volna be" — ami nem válasz.
        #
        # ⚠ ÉS MIÉRT A PARAMÉTERBEN, ÉS NEM A MOTORBAN: a `0` a szűrő
        # dokumentált kikapcsolt értéke (`gates.vol_baseline.band`), tehát ehhez
        # nem kell új ág a backtestben. A jelölt-lista UGYANEBBŐL a dictből
        # épül, így az ujjlenyomat-ellenőrzés is rendben van.
        params = {**params, "atr_min_pct": 0, "atr_max_pct": 0}

    df15, df1 = bt.load_data(sym)
    if df15 is None or df1 is None:
        _hiba(f"nincs letöltött adat a(z) {sym} párhoz — `python main.py download`")

    _tol, _ig = str(fk["from"]), str(fk["to"])
    # A JELÖLT-LISTA: ugyanazokkal a paraméterekkel épül, amivel futtatunk —
    # különben a `run_pair` (jogosan) nemet mondana rá.
    sorozat = bt.build_signal_series(sym, df15, df1, params, pair_cfg,
                                     strategy=strategy,
                                     test_start=_tol, test_end=_ig)
    if len(sorozat.m1) == 0:
        _hiba(f"a megadott időszakra ({_tol} … {_ig}) nincs M1 adat")

    _sajat = _sajat_belepo
    _bejegyzett = []
    _szintek = []                    # [(idő, sl_ár, tp_rr), …] — kézi szintek
    if _sajat:
        # ⚠ A KÉZI BELÉPŐK CSERÉLIK a stratégia jelzéseit. A `signals` kulcsa az
        # M1 tábla POZÍCIÓ-INDEXE, ezért az időpontot arra kell fordítani.
        _idx = sorozat.m1.index
        uj = {}
        for be in (fk.get("entries") or []):
            t = _ido(be.get("time"), "belépő", _idx.tz)
            irany = str(be.get("direction") or "BUY").upper()
            if irany not in ("BUY", "SELL"):
                _hiba(f"a belépő iránya csak BUY vagy SELL lehet: {irany!r}")
            # A LEGKÖZELEBBI M1 bár — de csak ha tényleg közel van. Egy órával
            # arrébb tett belépő NEM ugyanaz a kötés; inkább szóljunk.
            poz = _idx.get_indexer([t], method="nearest")
            if len(poz) == 0 or poz[0] < 0:
                _hiba(f"a(z) {t} belépőhöz nincs M1 bár az időszakban")
            _tenyleges = _idx[poz[0]]
            if abs((_tenyleges - t).total_seconds()) > 300:
                _hiba(f"a(z) {t} belépőhöz a legközelebbi M1 bár {_tenyleges} — "
                      f"több mint 5 perc eltérés. Hétvége/szünet? Adj meg olyan "
                      f"időpontot, ahol van adat.")
            uj[int(poz[0])] = irany
            _bejegyzett.append((_tenyleges, irany))
            # ── KÉZI SL / TP ─────────────────────────────────────────────
            # A charton húzott stop ára + az R-szorzó. Elhagyható: enélkül a
            # stratégia ATR-alapú terve marad.
            if be.get("sl") is not None:
                _szintek.append((_tenyleges, float(be["sl"]),
                                 float(be.get("tp_rr", 2.0))))
        sorozat.signals = uj

    _rr = None
    if fk.get("rr_preset"):
        from core import risk_reduction as _rrm
        _p = str(fk["rr_preset"])
        if _p not in _rrm.PRESETS:
            _hiba(f"ismeretlen rr-preset: {_p!r} — {', '.join(_rrm.PRESETS)}")
        _rr = {**_rrm.default_config(), "preset": _p}
        # ⚠ A BE / TRAILING BEÁLLÍTHATÓ. A felhasználó jelzése (2026-09-03):
        # „nem is tudom állítani, hogy mikor induljon a trailing, és mikor húzza
        # be az SL-t BE-be". Ezek a kockázatcsökkentés paraméterei
        # (`core.risk_reduction`), és eddig a mentett alapértéket kapták — a
        # laborban viszont épp ezeket akarod variálni.
        for _k, _v in (fk.get("rr") or {}).items():
            if _k != "preset":
                _rr[_k] = _v

    _manual = None
    if fk.get("breakeven_at"):
        _manual = {"breakeven_at": _ido(fk["breakeven_at"], "breakeven_at",
                                        sorozat.m1.index.tz)}
    if _szintek:
        _manual = {**(_manual or {}), "levels": _szintek}

    _build = None
    if fk.get("build"):
        from core import position_build as _pb
        _build = {"mode": _pb.MODE_AUTO}

    res = bt.run_pair(
        sym, df15, df1, params, pair_cfg, cfg.get("trading") or {},
        float(fk.get("balance") or 1000.0),
        test_start=_tol, test_end=_ig, strategy=strategy,
        rr=_rr, build=_build, record_events=True, cfg=cfg,
        exec_gates=_kapuk, signal_series=sorozat, manual_events=_manual)
    return {"res": res, "sym": sym, "strategy": strat_nev,
            "bejegyzett": _bejegyzett, "sajat": _sajat, "kapuk": _kapuk,
            "balance": float(fk.get("balance") or 1000.0),
            "jel_db": len(sorozat.signals)}


def _perc(t) -> str:
    """Időpont PERCRE — a másodperc és az időzóna-toldalék nélkül.

    ⚠ A teljes `2026-08-27 01:30:00+00:00` 25 karakter, a fejléc 20-as oszlopa
    mellett ELCSÚSZTATJA az egész sort, és épp az árak oszlopai válnak
    olvashatatlanná. A másodperc M1-es adaton mindig 00, az időzóna pedig a
    fejlécben egyszer kimondható."""
    try:
        return t.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(t)


def kiir(ki: dict) -> None:
    res, sym = ki["res"], ki["sym"]
    print(f"{sym} / {ki['strategy']}  —  "
          + ("KÉZI belépők" if ki["sajat"] else "a STRATÉGIA belépői")
          + ("  · végrehajtási kapuk BE" if ki["kapuk"]
             else "  · kapuk és volatilitás-szűrő KI"))
    if ki["sajat"]:
        for t, irany in ki["bejegyzett"]:
            print(f"   megadva: {_perc(t)}  {irany}")
        if not ki["bejegyzett"]:
            print("   (nem adtál meg belépőt — a futás üres lesz)")
    print()
    zart = res.closed
    if not zart and not res.trades:
        # ⚠ NEM HALLGATUNK: a nulla kötés lehet az, hogy a KAPU fogta meg
        # (spread, volatilitás, együttállás), és ezt tudni kell.
        if ki["kapuk"]:
            print("Egyetlen kötés sem született, és a VÉGREHAJTÁSI KAPUK be "
                  "vannak kapcsolva — a spread-, volatilitás- vagy "
                  "TF-együttállás-kapu valamelyike megfoghatta.")
            print('Ha a kézi belépőt kapuk NÉLKÜL akarod látni, tedd a '
                  'forgatókönyvbe:  "exec_gates": false')
        else:
            print("Egyetlen kötés sem született, pedig a végrehajtási kapuk "
                  "ki vannak kapcsolva. A méretezés (min_lot / szabad slot / "
                  "napi limit) foghatta meg — vagy a megadott időpontra nem "
                  "esik használható bár.")
        return
    # ⚠ AZ ÁR A PONT-MÉRET SZERINTI TIZEDESEKKEL. A `%.5g` egy Ger40/UsaTec
    # szintnél „29532"-t ad a belépőre ÉS a stopra is — a kettő ránézésre
    # egyforma, és épp a stop TÁVOLSÁGA tűnik el. (Ugyanez a hiba a Telegram-
    # ajánlat szövegében is elsült.)
    _pont = float((res.trades[0].point_size if res.trades else 0.0) or 0.0)
    import math as _m
    _tiz = 0 if _pont <= 0 else min(8, max(0, int(round(-_m.log10(_pont)))))

    def _ar(v):
        return f"{float(v):.{_tiz}f}" if v is not None else "—"

    _w = max(12, _tiz + 8)
    print(f"{'belépő':<17} {'ir':<4} {'ár':>{_w}} {'SL (nyitó)':>{_w}} "
          f"{'TP':>{_w}} {'kilépő':<17} {'P&L':>9} {'R':>7}  vége")
    print("-" * (104 + 3 * _tiz))
    _ossz_r = 0.0
    for t in res.trades:
        try:
            _1r = t.risk_usd or 0.0
            _r = (t.pnl_usd / _1r) if _1r else 0.0
        except (TypeError, ZeroDivisionError):
            _r = 0.0
        _ossz_r += _r
        # ⚠ A NYITÓ stopot mutatjuk, nem a `trade.sl`-t: az utóbbi a BE/trailing
        # után már ELMOZDULT, tehát a táblázatban a stop-TÁVOLSÁG (az 1 R)
        # eltűnne. Hogy hova mozdult a stop, azt az esemény-napló mondja meg.
        _d = 1 if t.direction == "BUY" else -1
        _sl0 = t.open_price - _d * t.sl_points * t.point_size
        print(f"{_perc(t.open_time):<17} {t.direction:<4} {_ar(t.open_price):>{_w}} "
              f"{_ar(_sl0):>{_w}} {_ar(t.tp):>{_w}} "
              f"{(_perc(t.close_time) if t.close_time else '—'):<17} "
              f"{t.pnl_usd:>+9.2f} {_r:>+7.2f}  {t.status}"
              + (f"  [{t.rr_technique}]" if t.rr_technique else ""))
    print("-" * (104 + 3 * _tiz))
    _s = res.summary(ki["balance"])
    print(f"{len(zart)} lezárt kötés · összesen {sum(t.pnl_usd for t in zart):+.2f} "
          f"· {_ossz_r:+.2f} R")
    if _s.get("trades"):
        # ⚠ A `win_rate` ARÁNY (0–1), nem százalék — az első kiírásom „1.0%"-ot
        # mutatott 100% helyett. A `max_drawdown` kulcs neve sem `max_dd`.
        print(f"találat {100 * _s.get('win_rate', 0):.1f}% · "
              f"PF {_s.get('profit_factor', 0):.2f} · "
              f"max DD {_s.get('max_drawdown', 0):.2f}")
    # ⚠ AZ ESEMÉNY-NAPLÓ A LÉNYEG: ebből látszik, MIKOR mozdult a stop, mikor
    # épített, mikor zárt részlegesen — a labor épp erre való.
    for t in res.trades:
        if not t.events:
            continue
        print(f"\n   {_perc(t.open_time)} {t.direction} eseményei:")
        for ev in t.events:
            _tipus, _t, _ar, _sl, _tp, _lot, _komment = (list(ev) + [""] * 7)[:7]
            _reszlet = []
            if _ar:
                _reszlet.append(f"ár {_ar:g}")
            if _sl:
                _reszlet.append(f"SL {_sl:g}")
            if _tp:
                _reszlet.append(f"TP {_tp:g}")
            if _lot:
                _reszlet.append(f"lot {_lot:g}")
            if _komment:
                _reszlet.append(str(_komment))
            print(f"      {_perc(_t):<17} {_tipus:<14} " + " · ".join(_reszlet))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("forgatokonyv", nargs="?", help="a JSON fájl útja")
    ap.add_argument("--minta", action="store_true",
                    help="kiinduló forgatókönyv-sablon a kimenetre")
    a = ap.parse_args(argv)
    if a.minta:
        print(json.dumps(MINTA, ensure_ascii=False, indent=2))
        return 0
    if not a.forgatokonyv:
        ap.print_help()
        return 2
    kiir(futtat(betolt(Path(a.forgatokonyv))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
