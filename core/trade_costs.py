"""
Kereskedési költségek — jutalék és swap (tiszta logika, MT5/pandas nélkül).

A backteszt eddig CSAK a spreadet modellezte. A valóságban két további tétel van:

  • **Jutalék** — pozíciónként, a lot arányában, oda-vissza (nyitás+zárás). FX-en
    és indexeken tipikusan fix $/lot; CFD-ken gyakran 0.
  • **Swap (rollover)** — minden szerver-éjfél átlépésekor, a lot arányában.
    Előjeles: lehet levonás (a gyakori) és jóváírás is.

Miért számít ez EZEN a rendszeren külön is: a Felező/Pajzs a pozíció egy részét
korán zárja, a maradékot (runnert) pedig ADDIG tartja, amíg a kiszállási jel /
trailing engedi — vagyis épp a runner szedi össze a swapot. Költség nélkül a
technika hozadéka szisztematikusan optimista. Ugyanez az elv áll a költség-tudatos
breakeven mögött is (a BE-puffernek fedeznie kell a jutalék+swapot).

A számokat NEM találjuk ki: a `tools/refresh_costs.py` a SAJÁT MT5-előzményedből
méri ki őket (a deal-ök `commission`/`swap` mezője a számla devizájában van), és
írja a config `pairs.<sym>` kulcsaiba:

    "commission_per_lot":   7.0     # ODA-VISSZA, 1.0 lotra, POZITÍV = költség
    "swap_long_per_lot":   -2.35    # 1.0 lotra / éjszaka, ELŐJELES (MT5-konvenció)
    "swap_short_per_lot":   0.41
    "swap_3x_weekday":      2       # ezen a napon háromszoros a swap (0=hétfő)

Hiányzó kulcs → 0.0, azaz a régi (költségmentes) viselkedés — a meglévő configok
eredménye nem változik magától, csak ha kitöltöd.
"""

from __future__ import annotations

DAY_SEC = 86400
DEFAULT_3X_WEEKDAY = 2          # szerda — a legtöbb bróker ekkor számol 3 napot


def nights_held(open_ts: float, close_ts: float,
                rollover3_weekday: "int | None" = DEFAULT_3X_WEEKDAY) -> float:
    """Hány swap-forduló esik a tartás alá (a 3×-os nap háromszoros súllyal).

    `open_ts`/`close_ts`: unix másodperc a BRÓKER faliórájában (a backtest gyertya-
    ideje is az). A forduló a szerver-éjfél: minden átlépett éjfél egy swap.

    A 3×-os nap konvenciója brókeronként eltérhet (van, aki pénteken számol
    háromszorosat). Az ITT használt szabály: ha a HAJNALBAN KEZDŐDŐ nap hétköznap-
    indexe egyezik a `rollover3_weekday`-jel, az a forduló háromszoros. A pontos
    napot a `symbol_info.swap_rollover3days` mondja meg — a `refresh_costs.py`
    onnan tölti. `None` → nincs háromszoros nap."""
    if close_ts <= open_ts:
        return 0.0
    first = int(open_ts // DAY_SEC) + 1          # az első átlépett éjfél napja
    last = int(close_ts // DAY_SEC)              # az utolsó (a zárás napjának kezdete)
    if last < first:
        return 0.0
    total = 0.0
    for day in range(first, last + 1):
        # 1970-01-01 csütörtök volt → a hétfő-alapú index eltolása 3.
        weekday = (day + 3) % 7
        total += 3.0 if (rollover3_weekday is not None
                         and weekday == rollover3_weekday) else 1.0
    return total


def commission_usd(lot: float, pair_cfg: dict) -> float:
    """A kereskedés ODA-VISSZA jutaléka a számla devizájában (POZITÍV = költség)."""
    per_lot = float((pair_cfg or {}).get("commission_per_lot", 0.0) or 0.0)
    return abs(per_lot) * float(lot)


def swap_usd(lot: float, direction: str, open_ts: float, close_ts: float,
             pair_cfg: dict) -> float:
    """A tartás alatt felhalmozott swap, ELŐJELESEN (negatív = levonás).

    A lot a NYITÓ méret: a részlegesen zárt (Felező/Pajzs) pozíciónál ez felülbecsli
    kissé a swapot, mert a runner kisebb lottal fut tovább — de a hibázás iránya
    KONZERVATÍV (inkább több költség), ami egy backtestben a helyes irány."""
    cfg = pair_cfg or {}
    key = "swap_long_per_lot" if direction == "BUY" else "swap_short_per_lot"
    per_lot_night = float(cfg.get(key, 0.0) or 0.0)
    if per_lot_night == 0.0:
        return 0.0
    w3 = cfg.get("swap_3x_weekday", DEFAULT_3X_WEEKDAY)
    n = nights_held(open_ts, close_ts, None if w3 is None else int(w3))
    return per_lot_night * float(lot) * n


def apply(pnl_gross: float, lot: float, direction: str,
          open_ts: float, close_ts: float, pair_cfg: dict) -> tuple:
    """`(nettó_pnl, jutalék, swap)` — a bruttó (csak spreades) P&L-ből.

    nettó = bruttó − jutalék + swap  (a swap előjeles: a jóváírás növeli)."""
    comm = commission_usd(lot, pair_cfg)
    swp = swap_usd(lot, direction, open_ts, close_ts, pair_cfg)
    return pnl_gross - comm + swp, comm, swp


def configured(pair_cfg: dict) -> bool:
    """Van-e EGYÁLTALÁN költség beállítva erre a párra? (A jelentés ezzel tudja
    kiírni, hogy az eredmény költségmentes — nehogy valósnak tűnjön.)"""
    cfg = pair_cfg or {}
    return any(float(cfg.get(k, 0.0) or 0.0) != 0.0
               for k in ("commission_per_lot", "swap_long_per_lot",
                         "swap_short_per_lot"))
