"""A KOTTA — egy `(instrumentum × stratégia)` cella teljes állapota egy képben.

Ez az, amit a karmester LÁT. Az F0 fázisban még nem dönt belőle semmi: a
pillanatkép a mérés összefogása, és a „miért nem kötött?" jelentés forrása.

⚠ EGY IGAZSÁGFORRÁS. A cella állapota ma öt-hat modulban szétszórva él (szándék,
kötés-mód, telemetria, élő teljesítmény, mentett eredmény, paraméter-eredet).
Amíg mindegyik hívó maga szedi össze, minden hívó MÁST fog látni — a felület, a
jelentés és a későbbi házirendek külön-külön csúsznak el. Itt egyszer áll össze.

⚠ TISZTA MODUL: se MT5, se pandas, se tkinter, se fájlírás. Amit a külvilágból
tudni kell — MELYIK stratégiák engedélyezettek a páron —, azt a hívó adja be
(`strategies_of`), ugyanúgy, ahogy a `core.console_cmd.Context` teszi. ⚠ MIÉRT:
a lista feloldása (`strategy.enabled_strategy_names`) a `strategy` csomagból jön,
ami pandas-t húz — és a mérő rétegnek működnie kell ott is, ahol az nincs.
"""

from __future__ import annotations

from conductor import expectation as _exp
from conductor import metrics as _met
from conductor import telemetry as _tlm

DEFAULT_WINDOW_DAYS = 90


def cell(cfg: dict, symbol: str, strategy: str, *, strategies_of=None,
         day=None, days: int = DEFAULT_WINDOW_DAYS, live_rows=None) -> dict:
    """Egy cella pillanatképe.

    `strategies_of(symbol) -> list`: a páron ENGEDÉLYEZETT stratégiák (a motor
    listája). Hiányában az `enabled` mezője `None` — „nem tudjuk", nem „nem".
    `live_rows`: ha a hívó több cellához már beolvasta a naplót, adja be."""
    from core import run_state as _rs
    from core import trade_mode as _tm

    engedett = None
    if strategies_of is not None:
        try:
            engedett = strategy in (strategies_of(symbol) or [])
        except Exception:
            engedett = None

    tel = _tlm.cell(symbol, strategy, day)
    elo = _met.cell(symbol, strategy, days=days, rows=live_rows)
    elo["trades_per_day"] = _met.trades_per_day(elo, days)
    vart = _exp.expected(symbol, strategy, cfg)
    d = _exp.divergence(elo, vart)

    return {
        "symbol": symbol,
        "strategy": strategy,
        # ── SZÁNDÉK ÉS MÓD ───────────────────────────────────────────────
        # ⚠ A MOTOR KÉPLETE: `engedélyezett ÉS szándék=live`. A szándék
        # önmagában nem elég — a `run_state` bejegyzés akkor is ott marad, ha a
        # stratégiát közben kikapcsoltad a páron.
        "enabled": engedett,
        "intent": _rs.get_state(cfg, symbol, strategy),
        "mode": _tm.mode_of(cfg, symbol, strategy),
        "running": (bool(engedett) and _rs.get_state(cfg, symbol, strategy) == _rs.LIVE
                    if engedett is not None else None),
        # ── MÉRÉS ────────────────────────────────────────────────────────
        "today": tel,
        "live": elo,
        "expected": vart,
        "divergence": d,
        "window_days": days,
    }


def letezik(cfg: dict, symbol: str, strategy: str, *, strategies_of=None) -> bool:
    """VAN-E MÉG ilyen cella? — egy helyen megválaszolva.

    ⚠ MIÉRT KELL KÜLÖN KÉRDÉS. A mátrix mindig a configból SZÁMOLÓDIK, tehát egy
    eltávolított stratégia sora magától eltűnik belőle. A postaláda és az
    optimalizálás-sor viszont SAJÁT, TARTÓS állapotot őriz egy
    `(instrumentum, stratégia)` cellára — és az ott marad akkor is, ha a cella
    közben megszűnt. Az eredmény egy javaslat olyan stratégiára, amit tegnap
    levettél a párról: elfogadni nem lehet (az újraérvényesítés elbukik), de ott
    ül a listában, és azt tanítja, hogy a postaládát nem kell komolyan venni.

    ⚠ A BIZONYTALANSÁG NEM MEGSZŰNÉS. Ha a stratégia-listát nem tudjuk feloldani
    (nincs `strategies_of`, vagy elszáll), IGAZAT adunk vissza: inkább maradjon
    egy fölösleges tétel, mint hogy egy átmeneti hiba eltemesse a valódi
    javaslatokat. A törlés visszafordíthatatlan, a zaj nem."""
    p = (cfg.get("pairs") or {}).get(symbol)
    if not isinstance(p, dict):
        return False                      # az instrumentum maga sincs meg
    if strategies_of is None:
        return True
    try:
        return strategy in (strategies_of(symbol) or [])
    except Exception:
        return True


def cells(cfg: dict, pairs=None, *, strategies_of=None, day=None,
          days: int = DEFAULT_WINDOW_DAYS) -> list:
    """MINDEN cella pillanatképe — EGY naplóolvasásból.

    `pairs`: a vizsgált instrumentumok (alapból a config `pairs` kulcsai)."""
    sorok = _met.closed_rows(days)
    syms = list(pairs if pairs is not None
                else [s for s, p in (cfg.get("pairs") or {}).items()
                      if isinstance(p, dict)])
    ki = []
    for sym in sorted(syms):
        nevek = []
        if strategies_of is not None:
            try:
                nevek = list(strategies_of(sym) or [])
            except Exception:
                nevek = []
        for n in nevek:
            ki.append(cell(cfg, sym, n, strategies_of=strategies_of, day=day,
                           days=days, live_rows=sorok))
    return ki
