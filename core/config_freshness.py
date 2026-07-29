"""
Config-frissesség: a PILLANATKÉP-jellegű értékek elévülésének jelzése.

Két érték a `config.json`-ban nem állandó, hanem a bróker MOSTANI állapotát rögzíti:

  • **`pv1_point`** — 1 lot × 1 pont értéke a számla devizájában. Nem számla-devizás
    instrumentumnál az ÁRFOLYAMMAL sodródik.
  • **`swap_*_per_lot`** — a kamat-alapú (CFD) swap az AKTUÁLIS árra vonatkozik,
    tehát az árral együtt mozog; a bróker a kamatlábat is módosíthatja.

Az ÉLŐ motor a `pv1_point`-ot minden méretezéskor MT5-ből frissíti, tehát élesben
akkor is helyesen köt, ha a config elavult. A **backteszt és az optimalizálás
viszont a configból dolgozik** — ott egy elévült érték csendben más mérettel és más
költséggel számol, mint a valóság. Ez a modul ezt teszi láthatóvá.

NEM ír és nem javít: csak MÉR és SZÓL. A javítás a felhasználó dolga:

    python tools/refresh_point_values.py --write
    python tools/refresh_costs.py --write
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Ennél nagyobb relatív eltérésnél szólunk. A pv1 szűkebb: az közvetlenül a
# pozícióméretet (és így a kockázatot) skálázza.
PV1_TOL = 0.05        # 5%
SWAP_TOL = 0.25       # 25% — a swap eleve ingadozóbb, ne legyen zajos a jelzés


def _rel(a: float, b: float) -> float:
    """|a−b| / |b| — 0.0, ha a viszonyítási alap nulla (nem tudunk arányt mondani)."""
    if not b:
        return 0.0
    return abs(a - b) / abs(b)


def check(cfg: dict) -> list:
    """A configtól ÉRDEMBEN eltérő párok listája: `[(szimbólum, mező, config, élő)]`.

    Üres lista = minden friss (vagy nem mérhető). MT5-kapcsolat nélkül üres — a
    hívónak nem kell külön kezelnie."""
    try:
        import MetaTrader5 as mt5
        from core import mt5_connector as mc
        from core import order_exec
        from tools.refresh_costs import swap_from_symbol
    except Exception:
        return []

    out = []
    for symbol, pc in (cfg.get("pairs") or {}).items():
        # MINDEN konfigurált párt nézünk, a letiltottakat is: a backtestet és az
        # optimalizálást letiltott páron is futtatod, és ott is a config értékei
        # számítanak. (Az `enabled` csak azt mondja meg, hogy ÉLESBEN kereskedünk-e.)
        if not isinstance(pc, dict):
            continue
        try:
            with mc.MT5_LOCK:
                info = mt5.symbol_info(symbol)
            if info is None:
                continue
            point_size = float(pc.get("point_size") or 0.0)
            if point_size <= 0:
                continue

            live_pv1 = order_exec.point_value(symbol, point_size, info)
            cfg_pv1 = float(pc.get("pv1_point") or 0.0)
            if live_pv1 and cfg_pv1 and _rel(live_pv1, cfg_pv1) > PV1_TOL:
                out.append((symbol, "pv1_point", cfg_pv1, live_pv1))

            sl_live, ss_live = swap_from_symbol(mt5, info, point_size)
            for key, live in (("swap_long_per_lot", sl_live),
                              ("swap_short_per_lot", ss_live)):
                cfgv = float(pc.get(key) or 0.0)
                # Csak ha MINDKETTŐ értelmes: a 0 ↔ nem-0 átmenet lehet egyszerű
                # „még nincs kitöltve" állapot, arról a tool úgyis szól.
                if live and cfgv and _rel(live, cfgv) > SWAP_TOL:
                    out.append((symbol, key, cfgv, live))
        except Exception:
            continue
    return out


def log_report(cfg: dict) -> None:
    """Induláskori ellenőrzés — EGY összevont figyelmeztetés, ha van elévült érték.

    Miért egyben: páronként külön sor a naplóban elveszne; így egy blokkban ott a
    teljes kép és a pontos parancs, amivel javítható."""
    stale = check(cfg)
    if not stale:
        log.info("Config-frissesség: a pont-érték és a swap egyezik a brókerrel.")
        return
    lines = [f"      {s:<9} {field:<20} config {c:>12.5g}  ←→  bróker {l:>12.5g}"
             for s, field, c, l in stale]
    need_pv1 = any(f == "pv1_point" for _, f, _, _ in stale)
    need_swap = any(f.startswith("swap") for _, f, _, _ in stale)
    cmds = []
    if need_pv1:
        cmds.append("python tools/refresh_point_values.py --write")
    if need_swap:
        cmds.append("python tools/refresh_costs.py --write")
    log.warning(
        "Config-frissesség: %d érték ELTÉR a brókertől. Az ÉL helyesen méretez "
        "(MT5-ből frissít), de a BACKTESZT és az OPTIMALIZÁLÁS a configból dolgozik "
        "— tehát mást mér, mint amit kötünk.\n%s\n   Javítás:\n      %s",
        len(stale), "\n".join(lines), "\n      ".join(cmds))
