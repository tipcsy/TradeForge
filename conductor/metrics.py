"""ÉLŐ GÖRDÜLŐ TELJESÍTMÉNY — per `(instrumentum × stratégia)`.

⚠ A LELET. A dashboard „Minőség" oszlopa a MENTETT, out-of-sample backtest
eredményből jön (`core/quality.py`) — vagyis abból, amit az optimalizálás
*ígért*. Hogy a cella ÉLESBEN mit teljesít, sehol nem áll össze: a nyersanyag
megvan (`trades.csv`, `pnl_split`, `position_meta`), az aggregátum nincs. A
karmester két legfontosabb száma épp ebből jön:

  • a cella saját teljesítménye (PF, expectancy, kötésszám) — a `scoring.py`
    célfüggvényének bemenete;
  • az ÉLŐ ↔ VÁRT eltérés — az egyetlen túlillesztés-védelem, ami élesben is mér.

── MIBŐL ──────────────────────────────────────────────────────────────────
A motor `trades.csv`-jéből, a `close` eseményekből. ⚠ EGY `close` sor = EGY
befejezett pozíció: a Felező/Pajzs RÉSZLEGES zárásai nem külön sorok, és a
`closed_deal_summary` az ÖSSZES záró dealt összegzi — tehát a `pnl_usd` a teljes
realizált eredmény. Aki „részleges zárás = külön kötés"-nek számolná, a
kötésszámot felfújná és a PF-et elrontaná.

⚠ ÉS MIÉRT NEM VEZETÜNK SAJÁT NYILVÁNTARTÁST. Mert egy külön karmester-napló a
lezárt kötésekről előbb-utóbb MÁS számot adna ugyanarra a napra, mint a
Telegram-üzenet és a napi összesítő — ez a projekt visszatérő hibaosztálya. Egy
forrás, több olvasó.

── AMIT A SZÁMOK NEM MONDANAK MEG ─────────────────────────────────────────
⚠ A PROFIT FACTOR KIS MINTÁN HAZUDIK. A `core/quality.py` MÉRT adata (Ger40, 998
valódi kötés, igazi PF 1,10): 5 kötésen a minták 14%-a 3 FÖLÖTTI PF-et mutat, 15
kötésen 4,5%-a. Ezért minden cella viszi a `trades` darabszámot, és a hívónak
(karmester, jelentés) KÖTELESSÉGE nézni: a `confidence()` ezt egyetlen 0..1
szorzóvá alakítja, hogy egy csillogó, de vékony cella ne nyerhesse meg a
slot-versenyt egy unalmas, de bizonyított ellen.

⚠ A VÉGTELEN PF NEM PF. Ha nem volt veszteséges kötés, a hányados nem
végtelen, hanem ÉRTELMEZHETETLEN — `None`-t adunk vissza. Egy „PF = ∞" a
rangsorban minden mást megverne, pedig épp azt jelenti, hogy nincs elég adat.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta, timezone

from conductor import paths as _paths

log = logging.getLogger(__name__)

# ⚠ MÉRT KÜSZÖB, NEM ÍZLÉS (core/quality.py, 2026-08-23): 50 kötésnél a
# bootstrap 95%-os sávja 1,82-ig ér, vagyis egy „Jó" (PF ≥ 1,4) még mindig lehet
# véletlen, de már csak ~3% eséllyel. Ez a bizonyíték-szorzó félértéke.
CONFIDENCE_TRADES = 50


def confidence(trades: int, full_at: int = CONFIDENCE_TRADES) -> float:
    """0..1 bizonyíték-szorzó a kötésszámból.

    `trades = full_at` → 0,5; `2 × full_at` → 0,67; 5× → 0,83. SOSEM éri el az
    1-et: több adat mindig jobb, de a bizonyosság nem teljes."""
    n = max(0, int(trades or 0))
    if n <= 0:
        return 0.0
    return n / (n + max(1, int(full_at)))


def _ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f        # NaN kiszűrése


def closed_rows(days: int = 90, now=None) -> list:
    """A `trades.csv` LEZÁRÁS-sorai az elmúlt `days` napból.

    ⚠ NEM DOB és nem néma: hiányzó vagy olvashatatlan naplónál üres listát ad,
    DE naplóz — az üres eredmény különben megkülönböztethetetlen volna a
    „nem volt kötés"-től."""
    ut = _paths.trades_csv()
    if not ut.exists():
        return []
    hatar = (now or datetime.now(timezone.utc)) - timedelta(days=max(1, int(days)))
    ki = []
    try:
        with open(ut, encoding="utf-8", newline="") as f:
            for sor in csv.DictReader(f):
                if (sor.get("event") or "").strip() != "close":
                    continue
                t = _ts(sor.get("time"))
                if t is None or t < hatar:
                    continue
                pnl = _num(sor.get("pnl_usd"))
                if pnl is None:
                    # ⚠ P&L nélkül a sor nem kötés-adat, hanem zaj: beszámítva a
                    # kötésszámot növelné (a bizonyíték-szorzót is!), a PF-et
                    # viszont nem. Kihagyjuk — de megszámoljuk a naplóban.
                    continue
                ki.append({"time": t,
                           "symbol": (sor.get("symbol") or "").strip(),
                           "strategy": (sor.get("strategy") or "").strip(),
                           "pnl": pnl,
                           "ticket": (sor.get("ticket") or "").strip()})
    except Exception as ex:
        log.warning("conductor.metrics: a(z) %s nem olvasható: %s", ut.name, ex)
        return []
    return ki


def _ures() -> dict:
    return {"trades": 0, "wins": 0, "losses": 0, "net": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0,
            "profit_factor": None, "win_rate": None, "expectancy": None,
            "best": None, "worst": None, "first": None, "last": None,
            "confidence": 0.0}


def _osszegez(rows: list) -> dict:
    r = _ures()
    if not rows:
        return r
    nyer = [x["pnl"] for x in rows if x["pnl"] > 0]
    veszt = [x["pnl"] for x in rows if x["pnl"] < 0]
    # ⚠ A NULLA P&L-es kötés SEM nyerő, SEM vesztő — de KÖTÉS. A win_rate
    # nevezője ezért a teljes darabszám, nem a nyerő+vesztő.
    r["trades"] = len(rows)
    r["wins"], r["losses"] = len(nyer), len(veszt)
    r["gross_profit"] = round(sum(nyer), 2)
    r["gross_loss"] = round(-sum(veszt), 2)
    r["net"] = round(sum(x["pnl"] for x in rows), 2)
    r["win_rate"] = round(len(nyer) / len(rows), 4)
    r["expectancy"] = round(r["net"] / len(rows), 4)
    # ⚠ Veszteség NÉLKÜL a PF nem végtelen, hanem értelmezhetetlen.
    r["profit_factor"] = (round(r["gross_profit"] / r["gross_loss"], 3)
                          if r["gross_loss"] > 0 else None)
    r["best"] = round(max(x["pnl"] for x in rows), 2)
    r["worst"] = round(min(x["pnl"] for x in rows), 2)
    r["first"] = min(x["time"] for x in rows).isoformat(timespec="seconds")
    r["last"] = max(x["time"] for x in rows).isoformat(timespec="seconds")
    r["confidence"] = round(confidence(len(rows)), 4)
    return r


def cell(symbol: str, strategy: str, days: int = 90, now=None,
         rows: "list | None" = None) -> dict:
    """EGY cella gördülő élő teljesítménye.

    `rows`: ha a hívó már beolvasta a naplót (több cellához), adja be — így a
    fájl egyszer olvasódik, nem cellánként."""
    sorok = closed_rows(days, now) if rows is None else rows
    return _osszegez([x for x in sorok
                      if x["symbol"] == symbol and x["strategy"] == strategy])


def all_cells(days: int = 90, now=None) -> dict:
    """MINDEN cella: `{"SYM|strategia": {...}}` — EGY naplóolvasásból."""
    sorok = closed_rows(days, now)
    kosar: dict = {}
    for x in sorok:
        kosar.setdefault(f"{x['symbol']}|{x['strategy']}", []).append(x)
    return {k: _osszegez(v) for k, v in kosar.items()}


def trades_per_day(m: dict, days: int) -> "float | None":
    """Kötés/nap a mért ablakban — az ÉLŐ aktivitás, amit a VÁRT-hoz mérünk.

    ⚠ AZ ABLAK a kérés napjaiból jön, NEM az első és az utolsó kötés közötti
    időből. Utóbbi egy elszáradt cellánál hazudna: ha egy pár 90 napból csak az
    első kettőben kötött, a „két nap alatt 6 kötés" 3/nap-ot adna, miközben a
    valóság 0,07 — és épp az elszáradást akarjuk észrevenni."""
    n = int((m or {}).get("trades") or 0)
    d = max(1, int(days))
    return round(n / d, 4) if n else 0.0
