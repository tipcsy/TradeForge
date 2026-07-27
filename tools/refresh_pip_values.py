"""
Pip-érték és lot-korlátok FRISSÍTÉSE a brókertől a `config.json`-ba.

Miért kell
----------
A `pairs.<sym>.pv1_usd` (1 lot × 1 pip értéke a SZÁMLA devizájában) egyetlen
PILLANATKÉP arról, amikor az instrumentumot felvetted. Két baja lehet:

  • **Elavult.** Nem számla-devizás instrumentumnál (EUR-számlán minden USD/GBP/
    JPY-alapú) az érték az ÁRFOLYAMMAL sodródik, tehát a tényleges kockázat
    eltér a beállított %-tól.
  • **Kézzel beírt.** Érdemes ellenőrizni, hogy a config értéke egyezik-e azzal,
    amit a bróker MOST mond. (Megjegyzés: az index-CFD-k kerek `1.0` értéke ennél
    a brókernél HELYES — ezek a számla devizájában vannak denominálva.)

Az ÉLŐ motor a v1.65.6 óta MT5-ből frissíti a pip-értéket minden méretezéskor,
tehát élesben helyesen köt akkor is, ha a config elavult. A BACKTESZT és az
OPTIMALIZÁLÁS viszont a configból dolgozik — ezért érdemes ezt időnként lefuttatni,
különben a mért eredmény más mérettel számol, mint az él.

Használat
---------
    python tools/refresh_pip_values.py            # csak MEGMUTATJA az eltéréseket
    python tools/refresh_pip_values.py --write    # be is írja a config.json-ba
    python tools/refresh_pip_values.py --days 365 # ennyi nap a spread-mediánhoz

Alapból NEM ír (a config.json a te élő beállításod). A `--write` a
`pv1_usd`, `min_lot`, `lot_step`, `max_lot` és `backtest_spread_pips` mezőket
frissíti; minden mást (engedélyezés, órák, stratégiák, run_state) érintetlenül hagy.

A `backtest_spread_pips` a VALÓS ELŐZMÉNY mediánjából jön (a `data/m1/<sym>.parquet`
`avg_spread` oszlopa, a kereskedett órákra szűrve), NEM a pillanatnyi tickből — egy
tick a nap egy véletlen pillanata, a backtestre érvényes szám viszont a tipikus
spread. Ha nincs elég historikus adat, a tick a tartalék.
"""

import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CFG_PATH = ROOT / "config.json"
M1_DIR = ROOT / "data" / "m1"

# Ennyi relatív eltérés fölött tekintjük „érdemi" változásnak (a kijelzéshez).
SIGNIFICANT = 0.02

# A spread-becsléshez ennyi nap előzményt nézünk (a spread évek alatt változik —
# a bróker módosíthatja, és a volatilitási rezsim is más volt). Felülírható: --days
SPREAD_DAYS = 180
MIN_SPREAD_BARS = 500      # ennyi gyertya alatt nem hiszünk a mediánnak


def traded_hours(symbol: str, pair_cfg: dict) -> set:
    """Azok az ÓRÁK, amikben a pár ténylegesen kereskedik — a spread-mediánt csak
    ezekre számoljuk. Éjjel/hétvégén a spread sokszorosa a nappalinak, és az
    torzítaná a becslést olyan órákkal, amikben soha nem lépünk be.

    A motor per-stratégia órákat használ (`resolve_trade_hours`); a spread viszont
    PÁR-szintű beállítás, ezért a pár stratégiáinak ÚNIÓJÁT vesszük. Ha egyik
    stratégiánál sincs mentett óra, a `sess_start`/`sess_end` tartomány marad."""
    from core.params_store import resolve_trade_hours, list_strategies
    legacy = pair_cfg.get("trade_hours")
    hours: set = set()
    for strat in (list(pair_cfg.get("strategies") or []) or list_strategies()):
        hrs = resolve_trade_hours(symbol, strat, legacy)
        if hrs:
            hours |= set(int(h) for h in hrs)
    if not hours and legacy:
        hours = set(int(h) for h in legacy)
    if not hours:
        hours = set(range(int(pair_cfg.get("sess_start", 0)),
                          int(pair_cfg.get("sess_end", 24))))
    return hours


def spread_from_history(symbol: str, pair_cfg: dict, days: int):
    """A TIPIKUS spread pipben a valós előzményből: az `avg_spread` MEDIÁNJA a
    kereskedett órákra szűrve. `(median, n_bar, p75)` vagy None.

    Miért nem a pillanatnyi tick: a `backtest_spread_pips` az EGÉSZ backtestre
    érvényes egyetlen szám, egy tick viszont a nap/hét egy véletlen pillanata.
    A median a napszakok és a hírek zaját is kisimítja; a p75-öt tájékoztatásul
    adjuk vissza (mennyire hosszú a farok)."""
    f = M1_DIR / f"{symbol}.parquet"
    if not f.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(f, columns=["avg_spread"])
    except Exception:
        return None
    if df.empty or "avg_spread" not in df.columns:
        return None
    if days > 0 and len(df):
        cutoff = df.index[-1] - pd.Timedelta(days=days)
        df = df[df.index >= cutoff]
    hours = traded_hours(symbol, pair_cfg)
    if hours:
        df = df[df.index.hour.isin(hours)]
    sp = df["avg_spread"].astype(float)
    sp = sp[sp > 0]
    pip = float(pair_cfg.get("pip_size") or 0.0)
    if pip <= 0 or len(sp) < MIN_SPREAD_BARS:
        return None
    return float(sp.median() / pip), int(len(sp)), float(sp.quantile(0.75) / pip)


def _pip_size(info) -> float:
    """A pip mérete a szimbólum tizedeseiből — ugyanaz a szabály, amit a felület
    használ új instrumentum felvételekor (a config `pip_size`-a a mérvadó, ez csak
    tartalék, ha az hiányzik)."""
    d = info.digits
    if d in (4, 5):
        return info.point * 10
    if d in (2, 3):
        return info.point * 100
    return info.point


def main() -> int:
    write = "--write" in sys.argv
    days = SPREAD_DAYS
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass

    from core import mt5_connector, order_exec, applog
    applog.harden_console()
    from strategy.settings import load_config

    cfg = load_config(CFG_PATH)
    if not mt5_connector.connect(cfg):
        print("Nem sikerult csatlakozni az MT5-hoz.")
        return 1

    import MetaTrader5 as mt5

    raw = json.loads(CFG_PATH.read_text(encoding="utf-8"),
                     object_pairs_hook=OrderedDict)
    pairs = raw.get("pairs", {})

    rows, spread_rows, changed = [], [], 0
    try:
        for symbol, pc in pairs.items():
            if not isinstance(pc, dict):
                continue
            with mt5_connector.MT5_LOCK:
                mt5.symbol_select(symbol, True)
                info = mt5.symbol_info(symbol)
            if info is None:
                rows.append((symbol, "—", "—", "NINCS ilyen szimbolum a brokerne1"))
                continue

            pip_size = float(pc.get("pip_size") or _pip_size(info))
            pv1_new  = order_exec.pip_value(symbol, pip_size, info)
            vb       = order_exec.volume_bounds(info)
            if pv1_new is None:
                rows.append((symbol, pc.get("pv1_usd"), "—", "nincs tick-ertek"))
                continue

            pv1_old = float(pc.get("pv1_usd") or 0.0)
            diff = (abs(pv1_new - pv1_old) / pv1_old) if pv1_old > 0 else 1.0
            note = ""
            if diff > SIGNIFICANT:
                note = f"ELTERES {diff*100:+.1f}%"
                changed += 1
            rows.append((symbol, f"{pv1_old:.4f}", f"{pv1_new:.4f}", note))

            # ── Spread: a valós ELŐZMÉNY mediánja a kereskedett órákra ──────
            # Tartalék a pillanatnyi tick, ha nincs elég historikus adat.
            hist = spread_from_history(symbol, pc, days)
            if hist is not None:
                sp_new, n_bar, sp_p75 = hist
                sp_src = f"median {n_bar} bar (p75 {sp_p75:.2f})"
            elif pip_size > 0 and info.point > 0:
                sp_new = info.spread * info.point / pip_size
                sp_src = "PILLANATNYI tick (nincs eleg elozmeny)"
            else:
                sp_new, sp_src = None, "-"
            sp_old = pc.get("backtest_spread_pips")
            spread_rows.append((symbol, sp_old, sp_new, sp_src))

            if write:
                pc["pv1_usd"] = round(pv1_new, 4)
                if vb:
                    vmin, vmax, vstep = vb
                    pc["min_lot"]  = vmin
                    pc["lot_step"] = vstep
                    if vmax != float("inf"):
                        pc["max_lot"] = vmax
                if sp_new is not None:
                    pc["backtest_spread_pips"] = round(sp_new, 2)
    finally:
        mt5_connector.disconnect()

    w = max((len(r[0]) for r in rows), default=8)
    print(f"\n{'szimbolum'.ljust(w)}  {'config':>10}  {'broker':>10}  megjegyzes")
    print("-" * (w + 36))
    for sym, old, new, note in rows:
        print(f"{str(sym).ljust(w)}  {str(old):>10}  {str(new):>10}  {note}")

    if spread_rows:
        w2 = max(len(r[0]) for r in spread_rows)
        print(f"\n{'szimbolum'.ljust(w2)}  {'spread regi':>11}  {'spread uj':>9}  forras")
        print("-" * (w2 + 45))
        for sym, so, sn, src in spread_rows:
            so_s = f"{so:.2f}" if isinstance(so, (int, float)) else "-"
            sn_s = f"{sn:.2f}" if isinstance(sn, (int, float)) else "-"
            flag = ""
            if isinstance(so, (int, float)) and isinstance(sn, (int, float)) and so > 0:
                d = (sn - so) / so
                if abs(d) > 0.15:
                    flag = f"  <- {d*100:+.0f}%"
            print(f"{str(sym).ljust(w2)}  {so_s:>11}  {sn_s:>9}  {src}{flag}")

    if not write:
        print(f"\n{changed} instrumentumnal erdemi ({SIGNIFICANT*100:.0f}% folotti) "
              f"elteres. NEM irtam semmit — a beirashoz:")
        print("    python tools/refresh_pip_values.py --write")
        return 0

    raw["pairs"] = pairs
    CFG_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"\nconfig.json FRISSITVE ({changed} erdemi elteres).")
    print("A backteszt/optimalizalas mostantol a helyes merettel szamol — a korabbi "
          "eredmenyek ehhez kepest eltolodhatnak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
