"""
A 2.0 sor ADATA az élő állapotból — tiszta leképezés.

A `dashboard/live_row.py` szándékosan csak megjelenít: egy sima dictet kap. Ez a
modul állítja elő azt a dictet a motor pillanatképeiből. Külön modul, mert így

  • a leképezés MT5 és tkinter nélkül tesztelhető (minden forrás beadható),
  • a megjelenítés és az adat-összeszedés nem keveredik — a `classic` úton az
    ilyen keveredés miatt lett a Minőség-oszlop néma „—" egy hiányzó import
    miatt (a `except Exception` elnyelte a `NameError`-t).

MINDEN KÜLSŐ FORRÁS BEADHATÓ (`owner_of`, `risk_of`, `quality_of`, …). Nincs
benne rejtett globális állapot, tehát a teszt pontosan azt méri, amit a
felület mutatni fog.

────────────────────────────────────────────────────────────────────────────
A `K.Össz.` JELENTÉSE — egy döntés, amit itt kell rögzíteni

A kapuk hatása stratégiánként állítható, a `K.Össz.` viszont INSTRUMENTUM-szintű
cella. Mit számoljon?

    „Hány kapu áll BLOKKOLÓ ÁLLAPOTBAN" — a MÉRÉS, stratégiától függetlenül.

Nem azt, hogy „hány kapu blokkol engem", mert az stratégiánként más, és egyetlen
cellába nem fér bele. Ez egybevág a terv logikájával: a kapu-oszlopok a PIACI
TÉNYT mondják („mi a helyzet"), a stratégia jelzés-cellájának KERETE pedig az
engedélyt („engem ez blokkol-e"). A kettő szándékosan más kérdésre válaszol.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from core import gates as _g


def _spread_cell(ctx: dict) -> dict:
    """`250/1312` — az aktuális és a megengedett spread PONTBAN.

    Konkrét szám, nem betűkód: az 1. kör tanulsága szerint az `S`/`E`/`E2` típusú
    jelölést senki nem tudja fejben tartani, a két szám viszont önmagát magyarázza.

    A `value` a RENDEZÉSHEZ kell: a kijelzett szövegből visszafejteni a számot
    törékeny volna (a `—` és a `250/—` alak is előfordul)."""
    import math
    cur, cap = ctx.get("spread_points"), ctx.get("max_spread_points")
    if cur is None:
        return {"text": "—", "blocking": False, "value": None}
    # A `spread_gate` VÉGTELENT ad, ha nincs érvényes ATR (fail-open: ilyenkor
    # nem szűrünk). Ez indulaskor, a bemelegítés előtt normális állapot — de a
    # cellába „inf"-et írni értelmetlen volna, ezért `—`: nincs korlát MOST.
    if not cap or not math.isfinite(cap):
        return {"text": f"{cur:.0f}/—", "blocking": False, "value": cur}
    return {"text": f"{cur:.0f}/{cap:.0f}", "blocking": cur > cap, "value": cur}


def _momentum_cell(ctx: dict, on_click=None, symbol: str = None) -> dict:
    """`↑1.24` — a piac „fordulatszáma": előjel = irány, nagyság = mennyire pörög.

    A `blocking` CSAK az alapjáratot jelzi (a mért érték a küszöb alatt van). Az
    irány-szűrő szándékosan NEM látszik itt: az irány-tudatos döntés a motoré, a
    sor pedig az instrumentum szintjén áll, ahol nincs jel-irány — különben a
    cella olyat ígérne, amit ezen a szinten nem lehet tudni (ugyanaz a
    szétválasztás, mint a `tf_align`-nál).

    A `value` a RENDEZÉSHEZ kell (a `↑`/`↓` előjelet visszafejteni törékeny)."""
    import math
    from core import momentum as _m
    val = ctx.get("momentum")
    click = (lambda: on_click(symbol)) if (on_click and symbol) else None
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return {"text": "—", "blocking": False, "value": None, "on_click": click}
    thr = ctx.get("momentum_idle_threshold")
    idle = _m.is_idle(val, {"idle_threshold": thr}) if thr is not None else False
    return {"text": _m.cell_text(val), "blocking": idle, "value": float(val),
            "on_click": click}


def _volatility_cell(ctx: dict, on_click=None, symbol: str = None) -> dict:
    """`0.51×` — a mostani ATR a kalibrált mércéhez képest.

    A `blocking` azt jelenti, hogy az ATR a stratégia engedett sávján KÍVÜL van,
    tehát a motor NEM lépne be — akkor sem, ha minden más stimmel. Ez az egyetlen
    blokkoló ok, ami eddig sehol nem látszott: a BTCUSD hetekig némán nem
    kereskedett 0,51×-es aránnyal (lásd `core/vol_baseline.py`).

    ⚠ Ez az oszlop MUTAT, nem dönt: a szűrés a stratégia `bt_entry`-jében van."""
    import math
    from core import vol_baseline as _vb
    atr = ctx.get("atr_price")
    base = ctx.get("atr_baseline")
    click = (lambda: on_click(symbol)) if (on_click and symbol) else None
    if not atr or not base or (isinstance(atr, float) and math.isnan(atr)):
        return {"text": "—", "blocking": False, "value": None, "on_click": click}
    st = _vb.status(float(atr), ctx.get("vol_params") or {}, float(base))
    r = st["ratio"]
    if r != r:
        return {"text": "—", "blocking": False, "value": None, "on_click": click}
    # ⚠ A PUSZTA ARÁNY nem mond semmit: a „0,51×" önmagában nem árulja el, hogy
    # az sok vagy kevés — ahhoz tudni kellene a sávot. Ezért a sávon KÍVÜLI
    # értékhez odatesszük az IRÁNYT is: „0,51×↓" = a padló alatt (túl csendes),
    # „4,20×↑" = a plafon fölött (túl kaotikus). Így a cella magától érthető,
    # a pontos küszöböket pedig a rákattintás nyitotta ablak mutatja.
    mark = ""
    if not st["ok"]:
        _lo, _hi = st.get("lo") or 0.0, st.get("hi") or 0.0
        mark = "↓" if (_lo > 0 and float(atr) < _lo) else ("↑" if _hi > 0 else "")
    return {"text": f"{r:.2f}×{mark}", "blocking": not st["ok"],
            "value": float(r), "why": st.get("why", ""), "on_click": click}


def _cost_cell(ctx: dict, on_click=None, symbol: str = None) -> dict:
    """`3.4:1 +70%` — a megteendő ÚT aránya és a hátrány a kifizetéshez képest.

    A `blocking` a pár küszöbéhez mér. Fontos, amit NEM mond: a kifizetés aránya
    (és így a nullszaldó win-rate) a spreadtől nem változik — csak az út lesz
    hosszabb a nyeréshez, mint a vesztéshez."""
    import math
    from core import cost_gate as _cg
    sl, tp = ctx.get("plan_sl_points"), ctx.get("plan_tp_points")
    sp, cap = ctx.get("spread_points"), ctx.get("cost_max_distortion")
    click = (lambda: on_click(symbol)) if (on_click and symbol) else None
    d = _cg.distortion(sl, tp, sp) if (sl and tp) else float("nan")
    if d != d:
        return {"text": "—", "blocking": False, "value": None, "on_click": click}
    return {"text": _cg.cell_text(sl, tp, sp),
            "blocking": (cap is not None and d > float(cap)),
            "value": float(d) if d != float("inf") else 9e9, "on_click": click}


def _stages(ds, name: str, order=None) -> list:
    """A stratégia stádium-pöttyeinek SZÍNNEVEI, a stádiumok sorrendjében.

    A motor a `ds.strategy_cells[név]`-be írja (`{stádium: (glifa, szín-név)}`) —
    ugyanaz a forrás, amiből a `classic` tábla körei jönnek, tehát a két nézet
    nem mondhat mást. `order`: a stádiumok kanonikus sorrendje (a stratégia
    `columns()`-ából); enélkül a dict beszúrási sorrendje dönt."""
    cells = (getattr(ds, "strategy_cells", None) or {}).get(name) or {}
    keys = list(order) if order else list(cells)
    return [(cells.get(k) or ("", "muted"))[1] for k in keys]


def _open_position(positions, symbol: str, name: str, owner_of=None,
                   risk_of=None) -> dict:
    """A stratégia NYITOTT pozíciója ezen a páron: élő P&L + R.

    Per-ticket adatból dolgozik (`open_positions_detailed`), nem a szimbólumra
    aggregáltból: az utóbbiban NINCS stratégia, és az 1. körben pont ezért maradt
    a „Nyitott" oszlop némán üres.

    Az R a belépéskori kockázatokra vetítve: `Σ P&L / Σ kockázat`. Ha egyetlen
    pozícióhoz sincs rögzített kockázat, az R None (nem 0 — az azt állítaná, hogy
    nullán áll)."""
    pnl, risk, n = 0.0, 0.0, 0
    for p in positions or []:
        if not isinstance(p, dict) or p.get("symbol") != symbol:
            continue
        owner = p.get("strategy")
        if owner is None and owner_of is not None:
            try:
                owner = owner_of(p.get("ticket"), p.get("magic"))
            except Exception:
                owner = None
        if owner != name:
            continue
        n += 1
        pnl += float(p.get("profit") or 0.0)
        if risk_of is not None:
            try:
                r = risk_of(p.get("ticket"))
            except Exception:
                r = None
            if r:
                risk += float(r)
    if not n:
        return {"money": None, "r": None, "count": 0}
    return {"money": pnl, "r": (pnl / risk if risk else None), "count": n}


def _daily(ds, name: str) -> dict:
    """A mai LEZÁRT P&L erre a stratégiára (`core/pnl_split.py` bontásából)."""
    b = (getattr(ds, "daily_by_strategy", None) or {}).get(name)
    if not b:
        return {"money": None, "r": None}
    return {"money": b.get("pnl", 0.0),
            "r": (b.get("r") if b.get("r_count") else None)}


def _sum_money_r(parts) -> dict:
    """Az instrumentum-szintű összesítő: a blokkok összege.

    Az R-eket NEM adjuk össze vakon — csak azokat, amelyek léteznek; ha egyik
    blokkban sincs R, az összesítőben sem lesz."""
    money = [p.get("money") for p in parts if p.get("money") is not None]
    rs = [p.get("r") for p in parts if p.get("r") is not None]
    return {"money": (sum(money) if money else None),
            "r": (sum(rs) if rs else None)}


def row_data(symbol: str, ds, strategy_names, cfg: dict = None,
             params: dict = None, pair_cfg: dict = None, *,
             positions=None, owner_of=None, risk_of=None, quality_of=None,
             opt_of=None, live_of=None, stage_order_of=None,
             opt_enabled_of=None, opt_state_of=None, enabled_of=None,
             on_toggle=None, on_opt=None, on_stages=None,
             on_symbol=None, on_align=None, on_spread=None,
             on_market=None, on_momentum=None, on_cost=None,
             on_volatility=None, open_charts=None, market_states=None) -> dict:
    """Egy instrumentum sorának adata a `live_row.LiveRow` számára.

    `ds`          — `live_trader.PairDashboardState` (duck-typed).
    `params`      — a pár futásidejű paraméterei (a spread-küszöbhöz).
    `quality_of(symbol, strategy) -> (szöveg, szín) | None`
    `opt_of(symbol, strategy) -> str`      — dátum vagy folyamat-%
    `live_of(symbol, strategy) -> bool`    — fut-e a stratégia
    `opt_enabled_of(symbol, strategy) -> bool` — optimalizálható-e MOST
                  (alap: „nem kereskedik" — a futás felülírná a paraméterfájlt)
    `enabled_of(symbol, strategy) -> bool` — engedélyezett-e a stratégia EZEN a
                  páron (`pairs.<sym>.strategies`). Alap: True.

    MIÉRT KELL az `enabled_of`. A sor MINDEN instrumentumon UGYANAZT a stratégia-
    listát kapja (`available_strategies`), különben a tábla oszlopai nem állnának
    egy vonalban. A motor viszont a pár SAJÁT listájából dolgozik. E nélkül a
    jelölés nélkül egy nem engedélyezett stratégia blokkja pontosan úgy néz ki,
    mint egy engedélyezetté — Play gombbal együtt —, és az indítás néma no-op
    volna. A blokk ezért NEM tűnik el (az oszlopok maradnak), csak a Play/Stop
    válik tétlenné; az OPT viszont MARAD, mert egy még nem engedélyezett
    stratégiát épp optimalizálni akarsz, mielőtt bekapcsolod.

    A megnyitó visszahívások (`on_*`) a `classic` nézet kattintásait hozzák át:
    a jelzés-cella a stratégia paramétereit, az instrumentum NEVE az instrumentum
    beállításait, az `Együtt` a TF-együttállást, a `Spread` a spread-küszöböt."""
    ctx = _g.ctx_from_state(ds, params or {}, pair_cfg or {})

    # A K.Össz.-hez a MÉRÉST nézzük: minden kaput blokkolónak véve megkapjuk,
    # hány kapu áll blokkoló állapotban (lásd a modul fejlécét).
    #
    # ⚠ DE CSAK AZ ENGEDÉLYEZETTEKET. A Beállításokban kikapcsolt kapunak nincs
    # oszlopa ÉS nem is szól bele a kereskedésbe (`gate_layout` mester-kapcsoló)
    # — ha mégis beleszámolna a jelvénybe, a sor „⛔1"-et mutatna olyasmiért,
    # aminek se látható nyoma, se tényleges hatása nincs. A felhasználó pedig
    # jogosan kérdezné, hogy akkor MIÉRT nem kereskedik.
    #
    # A kikapcsoltakat kifejezetten `EFFECT_NONE`-ra kell állítani, nem elhagyni
    # a szótárból: az `evaluate` a hiányzó kulcsra a kapu ALAPÉRTELMEZETT
    # hatásával számol, nem semmissel.
    from core import gate_layout as _gl
    _on = set(_gl.enabled_gates(cfg or {}))
    measure_effects = {k: (_g.EFFECT_BLOCK if k in _on else _g.EFFECT_NONE)
                       for k in _g.KEYS}
    _measured = _g.evaluate(ctx, measure_effects)
    badge = _g.badge(_measured)
    blocking_count = len(_g.blocking(_measured))   # a rendezéshez (a `⛔n` száma)

    strategies = []
    for name in strategy_names or []:
        states = _g.evaluate(ctx, _g.effects_for(cfg or {}, symbol, name))
        q = quality_of(symbol, name) if quality_of else None
        enabled = bool(enabled_of(symbol, name)) if enabled_of else True
        # Ami nincs engedélyezve a páron, az nem is FUTHAT — ugyanaz a metszet,
        # amit a motor képez (`_active = _enabled & _intent`). Itt is elvégezzük,
        # hogy egyetlen hívó se felejthesse el (a `live_of` önmagában a szándékot
        # is visszaadhatná).
        live = bool(live_of(symbol, name)) if live_of else False
        live = live and enabled
        # ⚠ KÖTÉS-MÓD a jelzés-cella elé: „V" = valódi kötést nyit, „J" = csak
        # jelez. A kettő ránézésre EGYFORMA volt — ugyanaz a pötty-sor, ugyanaz
        # a zöld Play —, pedig az egyik pénzt mozgat, a másik nem. A `mode_of`
        # ugyanazt a forrást olvassa, amit a motor.
        try:
            from core import trade_mode as _tmx
            _mode = _tmx.mode_of(cfg or {}, symbol, name)
        except Exception:
            _mode = ""
        strategies.append({
            "name": name,
            "enabled": enabled,
            "mode": _mode,
            # ⚠ Van-e NYITOTT chart az MT5-on, ami a jelzest megkapja? „Csak
            # jelzes" modban ez dont: chart nelkul a jelzes SEHOL nem jelenik
            # meg. A hivo adja be (egyszer, kororkent) — parkent lekerdezni
            # mappa-listazast jelentene minden sorra.
            "chart_open": (symbol in (open_charts or set())),
            "stages": _stages(ds, name,
                              stage_order_of(name) if stage_order_of else None),
            "frame": _g.frame_state(states),
            "position": _open_position(positions, symbol, name, owner_of, risk_of),
            "daily": _daily(ds, name),
            "quality": (q[0] if q else None),
            "live": live,
            "opt": (opt_of(symbol, name) if opt_of else None),
            # A KERESKEDŐ stratégiát nem optimalizáljuk: a futás végén felülíródna
            # a paraméterfájlja, és egy nyíló belépő a RÉGI paraméterekkel menne.
            "opt_enabled": (bool(opt_enabled_of(symbol, name))
                            if opt_enabled_of else not live),
            # `""` | `"running"` | `"queued"` — az OPT vezérlő ebből MORPHOL
            # (OPT → STOP → SOR), mint a Play/Stop.
            "opt_state": (opt_state_of(symbol, name) if opt_state_of else ""),
            "on_toggle": (lambda n=name: on_toggle(symbol, n)) if on_toggle else None,
            "on_opt": (lambda n=name: on_opt(symbol, n)) if on_opt else None,
            "on_stages": (lambda n=name: on_stages(symbol, n)) if on_stages else None,
        })

    # ⚠ NYITVA VAN-E A PIAC. A hívó adja be (körönként EGYSZER, minden párra) —
    # páronként lekérdezve MT5-hívás lenne minden sorra. Hiányzó bejegyzés =
    # „ismeretlen": nem állítjuk se nyitottnak, se zártnak.
    _ms = (market_states or {}).get(symbol) or {}

    return {
        "symbol": symbol,
        "session": {"state": _ms.get("state", "unknown"),
                    "age_sec": _ms.get("age_sec"),
                    "tip": _ms.get("tip", "")},
        "bid": getattr(ds, "bid", None),
        "ask": getattr(ds, "ask", None),
        "change_pct": getattr(ds, "change_pct", None),
        "digits": getattr(ds, "digits", 5),
        "on_symbol": (lambda: on_symbol(symbol)) if on_symbol else None,
        "gates": {
            "spread": _spread_cell(ctx),
            "on_spread": (lambda: on_spread(symbol)) if on_spread else None,
            "align": {"signs": ctx.get("tf_align_signs") or [],
                      "on_click": (lambda: on_align(symbol)) if on_align else None},
            "market": {"text": getattr(ds, "market_state_label", "") or "—",
                       "on_click": (lambda: on_market(symbol)) if on_market else None},
            "momentum": _momentum_cell(ctx, on_momentum, symbol),
            "cost": _cost_cell(ctx, on_cost, symbol),
            "volatility": _volatility_cell(ctx, on_volatility, symbol),
            "badge": badge,
            "blocking_count": blocking_count,
        },
        "strategies": strategies,
        "total": {
            "position": _sum_money_r([s["position"] for s in strategies]),
            "daily": _sum_money_r([s["daily"] for s in strategies]),
        },
    }


# ---------------------------------------------------------------------------
# Szűrés és rendezés — TISZTA függvények a kész sor-adaton
# ---------------------------------------------------------------------------
# A `classic` tábla a widgetek újracsomagolásával szűr/rendez; a 2.0 az ADATOT
# rendezi, és a tábla azt rajzolja ki. Így a viselkedés tkinter nélkül mérhető,
# és a rendezés nem tud „elcsúszni" a megjelenítéstől.

# A minőség rangsora — szövegként rendezve „Gyenge" < „Jó" lenne, ami hazugság.
_QUALITY_RANK = {"Jó": 0, "Közepes": 1, "Gyenge": 2, "Rossz": 3}


def _num(v):
    """Rendezhető alak: `(rang, érték)`. A hiányzó adat MINDIG a végére kerül,
    növekvő és csökkenő sorrendben is — különben a „nincs adat" sorok a lista
    elejére ugranának, és úgy tűnne, ők a legjobbak."""
    if v is None:
        return (1, 0.0)
    try:
        return (0, float(v))
    except (TypeError, ValueError):
        return (1, 0.0)


def sort_value(row: dict, key: str):
    """Egy sor rendezési értéke a megadott oszlop-kulcsra.

    A kulcs vagy egyszerű (`symbol`, `bid`, `spread`, `total_daily`), vagy
    stratégiához kötött: `"<stratégia>|position"`, `"…|daily"`, `"…|quality"`,
    `"…|opt"`. Utóbbi azért kell, mert ugyanaz az oszlop stratégiánként külön
    létezik — a „Pozíció" fejlécre kattintva AZ a stratégia szerint rendezünk,
    amelyik blokkjában kattintottál."""
    g = row.get("gates") or {}
    if key == "symbol":
        return (0, str(row.get("symbol") or ""))
    if key in ("bid", "ask", "change"):
        return _num(row.get({"change": "change_pct"}.get(key, key)))
    if key == "spread":
        return _num((g.get("spread") or {}).get("value"))
    if key == "badge":
        return _num(g.get("blocking_count"))
    if key == "market":
        return (0, str((g.get("market") or {}).get("text") or ""))
    if key in ("total_pos", "total_daily"):
        t = (row.get("total") or {}).get(
            "position" if key == "total_pos" else "daily") or {}
        return _num(t.get("money"))
    if "|" in key:
        name, field = key.split("|", 1)
        st = next((s for s in (row.get("strategies") or [])
                   if s.get("name") == name), None)
        if st is None:
            return (1, 0.0)
        if field in ("position", "daily"):
            return _num((st.get(field) or {}).get("money"))
        if field == "quality":
            return (0, _QUALITY_RANK.get(st.get("quality"), 9))
        if field == "stages":
            # A jelzés-oszlop: a BLOKKOLT sorok előre (ott van teendő), utána a
            # csökkentett, végül a szabadon futók.
            return (0, {"blocked": 0, "reduced": 1}.get(st.get("frame") or "", 2))
        return (0, str(st.get(field) or ""))
    return (1, 0.0)


def sort_rows(rows, key: str = None, reverse: bool = False) -> list:
    """A sorok rendezve. `key=None` → az EREDETI (config szerinti) sorrend.

    A rendezés STABIL, és másodlagos kulcsként mindig a szimbólum: azonos
    értékeknél így nem cserélgetik egymást a sorok frissítésenként (az ugráló
    tábla olvashatatlan)."""
    rows = list(rows or [])
    if not key:
        return rows
    # A hiányzó adatot KÜLÖN kezeljük, nem a rendezési kulcs rangjával: a
    # `reverse=True` a rangot is megfordítaná, és a „nincs adat" sorok a lista
    # ELEJÉRE ugranának — mintha ők lennének a legjobbak.
    have = [r for r in rows if sort_value(r, key)[0] == 0]
    missing = [r for r in rows if sort_value(r, key)[0] != 0]
    have.sort(key=lambda r: (sort_value(r, key)[1],
                             str(r.get("symbol") or "")), reverse=reverse)
    missing.sort(key=lambda r: str(r.get("symbol") or ""))
    return have + missing


def filter_rows(rows, search: str = "", hide_stopped: bool = False) -> list:
    """Keresés a szimbólum nevében + a STOPPED sorok elrejtése.

    „Stopped" = a soron EGYETLEN stratégia sem fut. Több stratégiánál ez a
    helyes olvasat: ha bármelyik él, az instrumentum dolgozik."""
    out = []
    s = (search or "").strip().upper()
    for r in rows or []:
        if s and s not in str(r.get("symbol") or "").upper():
            continue
        if hide_stopped and not any(x.get("live")
                                    for x in (r.get("strategies") or [])):
            continue
        out.append(r)
    return out


def build_rows(symbols, ds_map, strategies_of, **kw) -> list:
    """Több sor egyszerre. `strategies_of(symbol) -> [név, …]`.

    A stratégia-LISTÁNAK minden sorban azonosnak kell lennie, különben a tábla
    oszlopai nem állnának egy vonalban — a hívó felelőssége, hogy így töltse."""
    out = []
    for sym in symbols or []:
        ds = (ds_map or {}).get(sym)
        if ds is None:
            continue
        out.append(row_data(sym, ds, strategies_of(sym), **kw))
    return out
