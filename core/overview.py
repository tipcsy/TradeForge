"""Egy (instrumentum, stratégia) páros ÁLLAPOTA — egy képernyőn.

A felhasználó kérése: „az első oldalon csak egy dashboard-szerű dolog lehetne,
ahol látod, hogy mikor kereskedik, meg a minőséget, meg ilyeneket."

⚠ A lap ÉRTÉKE nem a metrikák megismétlése — azok máshol is látszanak. Az érték
a FIGYELMEZTETÉSEK: azok az állapotok, amikben a program úgy néz ki, mintha
rendben volna, közben nem. Ezek szinte mind NÉMÁK ma:

  • a mentett paraméterek óta KÉZZEL átírtad a mezőket → a mentett minősítés
    már nem ahhoz a beállításhoz tartozik, amivel kereskedsz,
  • az optimalizálás MÁS kapu-beállítással futott, mint ami most él → a
    paraméterek olyan világból jönnek, ami élesben nem létezik,
  • a mentett minősítés a walk-forward VIZSGA-ablakaiból jön — de az optimalizáló
    ÉPPEN AZOKON választott, tehát az nem független mérés (mérve: 2,51× felfújás),
  • él a pár, de nincs mentett paraméter.

A modul TISZTA adat (nincs Tk-függése), hogy tesztelhető legyen és később a fő
dashboard is használhassa.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Figyelmeztetés-súlyok — a felület ez alapján színez és rendez.
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_RISK = "risk"


def _ts(v):
    """ISO időbélyeg → datetime (vagy None). A mentett fájlok többféle alakot
    használnak (`Z` végződés, offset nélkül), ezért engedékenyen olvassuk."""
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_days(v) -> float | None:
    d = _ts(v)
    if d is None:
        return None
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400.0


def hour_profile(test_summary: dict, allowed_hours) -> list:
    """Óránkénti kép: `[{hour, pnl, count, allowed}, …]` — 24 elem.

    A `hourly_pnl` a mentett minősítésből jön (az optimalizálás írja). Ez az
    egyetlen forrásunk arra, hogy MIKOR keres és mikor veszít a beállítás.

    ⚠ A mentett alak óránként `{"pnl": …, "count": …}` — nem puszta szám. A
    KÖTÉSSZÁM külön kell: egy óra lehet „enyhén mínuszos 3 kötésből" (zaj) vagy
    „enyhén mínuszos 300 kötésből" (rendszeres veszteség), és a kettőből
    ELLENTÉTES teendő következik. Régebbi fájlokban lehet puszta szám is, azt is
    elfogadjuk (count nélkül).
    """
    raw = (test_summary or {}).get("hourly_pnl") or {}
    pnl, cnt = {}, {}
    for k, v in raw.items():
        try:
            h = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            try:
                pnl[h] = float(v.get("pnl", 0.0))
            except (TypeError, ValueError):
                continue
            try:
                cnt[h] = int(v.get("count", 0) or 0)
            except (TypeError, ValueError):
                cnt[h] = 0
        else:
            try:
                pnl[h] = float(v)
            except (TypeError, ValueError):
                continue
    allow = set(int(h) for h in allowed_hours) if allowed_hours else None
    return [{"hour": h, "pnl": pnl.get(h), "count": cnt.get(h),
             "allowed": (True if allow is None else h in allow)}
            for h in range(24)]


def warnings(cfg: dict, symbol: str, strategy_name: str, data: dict,
             state: str = "", mode: str = "") -> list:
    """A NÉMA bajok listája: `[{sev, text}, …]`, súlyosság szerint rendezve."""
    from core import gates as _gt

    out = []
    data = data or {}
    ts = data.get("test_summary") or {}
    has_params = bool(data.get("params"))

    if not has_params:
        out.append({"sev": SEV_RISK if state == "live" else SEV_WARN,
                    "text": ("Nincs mentett paraméter ehhez a stratégiához"
                             + (" — miközben a pár ÉL." if state == "live" else "."))})

    # ⚠ Kézi szerkesztés az optimalizálás UTÁN: a mentett minősítés (minőség,
    # kötésszám, PF) MÁS paraméterekhez tartozik, mint amivel kereskedsz. A
    # felületen viszont a régi minősítés látszik — ez a legkönnyebben
    # észrevétlen félreértés.
    _opt, _man = _ts(data.get("optimized_at")), _ts(data.get("manually_edited_at"))
    if _man and (not _opt or _man > _opt):
        out.append({"sev": SEV_WARN,
                    "text": ("A paramétereket KÉZZEL módosítottad az optimalizálás "
                             "óta — a lenti minősítés a RÉGI beállításhoz tartozik.")})

    # ⚠ Kapu-eltérés: ha az optimalizálás más kapu-beállítással futott, mint ami
    # most él, a mentett paraméterek olyan világból jönnek, ami nem létezik.
    saved_gates = data.get("exec_gates")
    now_gates = bool((cfg.get("optimizer") or {}).get("exec_gates", True))
    if saved_gates is not None and bool(saved_gates) != now_gates:
        out.append({"sev": SEV_RISK,
                    "text": (f"Az optimalizálás {'KAPUKKAL' if saved_gates else 'KAPUK NÉLKÜL'} "
                             f"futott, most {'kapukkal' if now_gates else 'kapuk nélkül'} "
                             f"mérünk — a mentett paraméterek más feltételekhez valók.")})

    # ⚠ A mentett minősítés NEM független mérés: a walk-forward vizsga-ablakain
    # az optimalizáló ÉPPEN azok alapján választotta a nyertest. (Holdout-mérés:
    # a szennyezett OOS-számok 2,51×-esre fújtak.)
    if ts.get("trades"):
        out.append({"sev": SEV_INFO,
                    "text": ("A lenti minősítés a walk-forward vizsga-ablakaiból "
                             "jön — de az optimalizáló ÉPPEN azokon választott, "
                             "tehát ez nem független mérés.")})

    # ⚠ 100% FÖLÖTTI visszaesés: a mentett minősítésben ilyen szám azt jelenti,
    # hogy a szimulált számla a mérés közben LENULLÁZÓDOTT volna (a képlet a
    # csúcshoz méri a mélypontot). A felület eddig ezt ugyanolyan szürke
    # százalékként írta ki, mint egy 8%-os visszaesést — pedig a kettő nem
    # ugyanaz a kategória. (Ger40-en mérve: 162,5%.)
    _mdd = ts.get("max_drawdown")
    try:
        _mdd = float(_mdd)
    except (TypeError, ValueError):
        _mdd = None
    if _mdd is not None and _mdd >= 1.0:
        out.append({"sev": SEV_RISK,
                    "text": (f"A mentett minősítés visszaesése {_mdd * 100:.0f}% — "
                             f"a szimulált számla a mérés közben lenullázódott "
                             f"volna. Ez a beállítás így nem kereskedhető.")})

    n = int(ts.get("trades") or 0)
    if 0 < n < 30:
        out.append({"sev": SEV_WARN,
                    "text": f"Kevés kötés a minősítésben ({n}) — az eredmény zaj is lehet."})

    age = _age_days(data.get("optimized_at"))
    if age is not None and age > 60:
        out.append({"sev": SEV_WARN,
                    "text": f"Az optimalizálás {age:.0f} napja futott."})

    if state == "live" and mode == "signal":
        out.append({"sev": SEV_INFO,
                    "text": "A pár ÉL, de „csak jelzés” módban — nem nyit pozíciót."})

    # Egyetlen kapu sincs bekapcsolva → minden jel átmegy.
    try:
        eff = _gt.effects_for(cfg or {}, symbol, strategy_name)
        if all(e == _gt.EFFECT_NONE for e in eff.values()):
            out.append({"sev": SEV_WARN,
                        "text": "Egyetlen végrehajtási kapu sincs bekapcsolva."})
    except Exception:
        pass

    order = {SEV_RISK: 0, SEV_WARN: 1, SEV_INFO: 2}
    return sorted(out, key=lambda w: order.get(w["sev"], 9))


def build(cfg: dict, symbol: str, strategy, data: dict, df_m15=None) -> dict:
    """Az áttekintés teljes adata. `data`: a mentett params JSON."""
    from core import quality as _q
    from core import run_state as _rs
    from core import trade_mode as _tm
    from core import gates as _gt
    from core.params_store import resolve_trade_hours

    data = data or {}
    ts = data.get("test_summary") or {}
    try:
        state = _rs.get_state(cfg, symbol, strategy.name)
    except Exception:
        state = ""
    try:
        mode = _tm.mode_of(cfg, symbol, strategy.name)
    except Exception:
        mode = ""
    # ⚠ A `quality.grade` sorrendje (szoveg, SZIN-NEV, indok) — a masodik elem
    # SZEMANTIKUS nev ("red"/"muted"), nem Tk-szin. A nev -> szin forditas a
    # temae (`theme.color`); ha ezt a modell tenne meg, a szinvaltas ket helyen
    # elcsuszhatna. (Elso nekifutasra elvetettem a sorrendet, es a Tk az
    # "vesztesegs" INDOKOT probalta szinkent ertelmezni -> azonnali hiba.)
    try:
        grade_txt, grade_color_name, grade_why = _q.grade(ts, cfg)
    except Exception:
        grade_txt, grade_color_name, grade_why = "—", "muted", ""
    try:
        hours = resolve_trade_hours(
            symbol, strategy.name,
            (cfg.get("pairs", {}).get(symbol) or {}).get("trade_hours"))
    except Exception:
        hours = None
    try:
        eff = _gt.effects_for(cfg or {}, symbol, strategy.name)
    except Exception:
        eff = {}

    data_from = data_to = None
    if df_m15 is not None and len(df_m15):
        data_from, data_to = df_m15.index.min(), df_m15.index.max()

    return {
        "symbol": symbol, "strategy": strategy.name,
        "state": state, "mode": mode,
        "grade": grade_txt, "grade_why": grade_why,
        "grade_color_name": grade_color_name,
        "summary": ts,
        "hours": hour_profile(ts, hours),
        "hours_limited": hours is not None,
        "gates": eff,
        "optimized_at": data.get("optimized_at"),
        "optimized_age_days": _age_days(data.get("optimized_at")),
        "edited_at": data.get("manually_edited_at"),
        "data_from": data_from, "data_to": data_to,
        "warnings": warnings(cfg, symbol, strategy.name, data, state, mode),
    }
