"""
Config-KOHERENCIA: az önmagában érvényes, de ÖNELLENTMONDÓ beállítások jelzése.

A `core/config_freshness.py` testvére. Az MÉRI a configot a brókerhez (elévült-e egy
pillanatkép-érték); ez a modul a configot ÖNMAGÁHOZ méri: olyan beállításokat keres,
amik szintaktikailag rendben vannak, a program elfogadja őket, **mégsem azt csinálják,
amit a felhasználó gondol**.

MIÉRT KELL. A 2026-08-05-i átvizsgálás öt ilyet talált egy 11 párós configban — és
egyik sem okozott hibát, kivételt vagy naplóbejegyzést. Például az `UsaInd` `Piac`
kapuja `kockázatcsökkentés`-re volt állítva (a felület így is mutatta), de mivel a
páron nem volt kiválasztva piac-előszűrő, a kapunak **nem volt mit mérnie** — sosem
tüzelhetett. A beállítás létezett, látszott, és semmit nem csinált.

Ez a modul ugyanabba a családba tartozik, mint a `constraints`-ellenőrzés vagy a
kapu-forrás kijelzése: **a némán hatástalan beállítás rosszabb, mint a hiányzó.**

NEM ír és nem javít — csak MÉR és SZÓL, mint a `config_freshness`. A javítás mindig
felhasználói döntés (más-más a helyes válasz: bekapcsolni vagy kivenni).

TISZTA modul: se MT5, se tkinter, se fájl. Egy dictet kap, listát ad — így egy sorban
tesztelhető, és minden belépési pont (live, backtest, optimalizálás) ugyanazt látja.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Súlyosság. Kettő van, szándékosan:
#   WARN — a beállítás NEM azt csinálja, amit mutat (néma hatástalanság / árnyékolás)
#   INFO — érvényes, de érdemes tudni róla (alapértelmezés, aminek KÖVETKEZMÉNYE van)
WARN = "warn"
INFO = "info"


def _finding(level, code, msg, symbol=None) -> dict:
    return {"level": level, "code": code, "symbol": symbol, "message": msg}


# ---------------------------------------------------------------------------
# 1. Kapu, aminek nincs mit mérnie
# ---------------------------------------------------------------------------

def _check_gate_preconditions(cfg: dict, out: list) -> None:
    """Kapu BE van kapcsolva (`block`/`reduce`), de az ELŐFELTÉTELE hiányzik.

    A kapu hatása és a kapu MÉRHETŐSÉGE két külön dolog, és a felület csak az
    elsőt mutatja. Ha a mérés forrása hiányzik, a kapu némán átenged mindent."""
    from core import gates as _g
    from core import market_strategy as _ms
    from core import tf_align as _tfa
    from strategy import enabled_strategy_names

    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        for sname in enabled_strategy_names(cfg, sym) or []:
            # PIAC: a besorolás a per-pár kiválasztott osztályozóból jön. Nincs
            # osztályozó → `ds.market_state` üres marad → a kapu sosem bukik.
            if _g.active(_g.effects_for(cfg, sym, sname), _g.MARKET):
                if not _ms.market_name_of(pc):
                    out.append(_finding(
                        WARN, "market_gate_no_classifier",
                        f"{sym}/{sname}: a Piac-kapu be van kapcsolva "
                        f"({_g.effect_for(cfg, sym, sname, _g.MARKET)}), de a páron "
                        f"nincs piac-előszűrő kiválasztva (pairs.{sym}."
                        f"market_strategy) → a kapunak NINCS mit mérnie, sosem "
                        f"tüzel. Válassz osztályozót "
                        f"({', '.join(_ms.registered_market_names())}), vagy vedd "
                        f"a kapu hatását 'none'-ra.", sym))
            # IDŐSÍK-EGYÜTTÁLLÁS: ha a figyelő ki van kapcsolva, nincs előjel-adat.
            if _g.active(_g.effects_for(cfg, sym, sname), _g.TF_ALIGN):
                try:
                    _en = _tfa.config_for(cfg, sym)[0]
                except Exception:
                    _en = True
                if not _en:
                    out.append(_finding(
                        WARN, "tf_gate_disabled_watcher",
                        f"{sym}/{sname}: a TF-együttállás kapu be van kapcsolva, de "
                        f"maga a figyelő ki van kapcsolva (tf_align.enabled=false) "
                        f"→ a kapu sosem tüzel.", sym))


# ---------------------------------------------------------------------------
# 2. Stratégia-hivatkozás, ami nem fut
# ---------------------------------------------------------------------------

# Per-pár, stratégia-KULCSOS térképek: {config-kulcs: emberi név}
_STRATEGY_MAPS = {
    "run_state":       "kereskedés-szándék (Play/Stop)",
    "strategy_mode":   "kötés módja (valódi / csak jelzés)",
    "strategy_viz":    "vizualizáció látszik",
    "strategy_trades": "kötések látszanak",
}


def _check_stale_strategy_keys(cfg: dict, out: list) -> None:
    """A páron NEM ENGEDÉLYEZETT stratégiára mutató beállítások.

    Ezek nem hibák — szándékosan nem takarítjuk őket, mert ha újra bekapcsolod a
    stratégiát, a korábbi választásod érvényes marad. De egy `run_state: live`
    bejegyzés egy ki nem kapcsolt stratégián FÉLREVEZET: úgy néz ki, mintha futna.
    (Ez volt a 2026-08-05-i P0 gyökere a felület oldalán.)"""
    from strategy import enabled_strategy_names, registered_strategy_names
    reg = set(registered_strategy_names())

    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        enabled = set(enabled_strategy_names(cfg, sym) or [])
        for key, label in _STRATEGY_MAPS.items():
            per = pc.get(key)
            if not isinstance(per, dict):
                continue
            for n, v in per.items():
                if n in enabled or n not in reg:
                    continue
                # Csak a HATÁSSAL bíró (nem alapértelmezett) bejegyzés érdekes: egy
                # `stopped` / `false` bejegyzés nem ígér semmit.
                if key == "run_state" and v != "live":
                    continue
                out.append(_finding(
                    INFO, "stale_strategy_key",
                    f"{sym}: a(z) {n!r} nincs engedélyezve ezen a páron "
                    f"(pairs.{sym}.strategies), de van rá {key}={v!r} bejegyzés "
                    f"({label}) → a motor figyelmen kívül hagyja.", sym))


# ---------------------------------------------------------------------------
# 3. Költség-kulcsok hiánya
# ---------------------------------------------------------------------------

_COST_KEYS = ("commission_per_lot", "swap_long_per_lot", "swap_short_per_lot")


def _check_costs(cfg: dict, out: list) -> None:
    """Hiányzó költség-kulcs → a backteszt NULLA költséggel számol.

    Élesben ez nem látszik (a bróker úgyis levonja), a backteszt viszont csendben
    TÚLBECSÜLNE — pont annál a párnál, amit még csak most vezetsz be."""
    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        missing = [k for k in _COST_KEYS if pc.get(k) is None]
        if missing:
            out.append(_finding(
                WARN, "missing_costs",
                f"{sym}: hiányzó költség-kulcs ({', '.join(missing)}) → a backteszt "
                f"NULLA költséggel számolna ezen a páron. Töltsd fel: "
                f"`python tools/refresh_costs.py --write`.", sym))


# ---------------------------------------------------------------------------
# 3b. HIÁNYZÓ MÉRETEZÉSI KULCS — ez nem kényelmi kérdés, ez leállás
# ---------------------------------------------------------------------------

# A pár nélkülözhetetlen számai. Ezek nélkül a motor nem tud lotot számolni,
# tehát a pár nem kereskedhet.
_SIZING_KEYS = ("point_size", "pv1_point")


def missing_sizing_keys(pair_cfg: dict) -> list:
    """A pár hiányzó méretezési kulcsai. A MOTOR és az ellenőrzés is EZT
    hívja — így nem fordulhat elő, hogy a config-vizsgálat rendben találja,
    amit az indulás elutasít (vagy fordítva)."""
    if not isinstance(pair_cfg, dict):
        return list(_SIZING_KEYS)
    return [k for k in _SIZING_KEYS if not pair_cfg.get(k)]


def _check_sizing(cfg: dict, out: list) -> None:
    """Hiányzó `point_size`/`pv1_point` → a pár NEM tud kereskedni.

    Ez a lista legsúlyosabb lelete, és valós kárt okozott: 2026-08-08-án egy
    frissen felvett instrumentumnál hiányzott a `point_size`, a `pair_cfg[...]`
    KeyError-je pedig MEGÖLTE a teljes LiveTrader szálat — onnantól EGYETLEN pár
    sem kereskedett, és a viz-fájlok sem íródtak. A tünet (üres sávok a charton)
    hetekkel később derült ki. A motor azóta izolálja a hibás párt; ez az
    ellenőrzés pedig INDULÁS ELŐTT megmondja, hogy melyikről van szó."""
    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        missing = missing_sizing_keys(pc)
        if missing:
            out.append(_finding(
                WARN, "missing_sizing",
                f"{sym}: hiányzik a méretezéshez KÖTELEZŐ kulcs "
                f"({', '.join(missing)}) → ez a pár NEM fog kereskedni "
                f"(kimarad az indításnál). Töltsd fel: "
                f"`python tools/refresh_point_values.py --write`.", sym))


# ---------------------------------------------------------------------------
# 3c. A volatilitás-kapu KIKAPCSOLVA, miközben van beállított küszöb
# ---------------------------------------------------------------------------

def _check_volatility_gate_off(cfg: dict, out: list) -> None:
    """A Volatilitás oszlopot kivenni a `gate_order`-ből v3.27.0 óta KIKAPCSOLJA
    a szűrést is.

    ⚠ MIÉRT KELL ERRŐL SZÓLNI. v3.27.0 előtt ez az oszlop CSAK KIJELZÉS volt: a
    szűrés a stratégia `bt_entry`-jében futott, és a `gate_order` nem érintette.
    Aki tehát korábban a látvány miatt vette ki az oszlopot, az most — a lista
    változatlanul hagyásával — a SZŰRÉST is levette. Ez a fajta néma
    viselkedés-váltás pontosan az, amiért ez a modul létezik.

    A jelzés csak akkor szól, ha van MIT kikapcsolni: a mentett készletben van
    nem-nulla `atr_min_pct`/`atr_max_pct`. Nulla küszöbnél a kapu úgysem szűrne,
    tehát a kikapcsolás semmit nem változtat."""
    from core import gates as _g, gate_layout as _gl
    if _gl.is_enabled(cfg, _g.VOLATILITY):
        return
    syms = [s for s in (cfg.get("pairs") or {}) if isinstance(s, str)]
    if not syms:
        return
    out.append(_finding(
        WARN, "volatility_gate_off",
        f"A Volatilitás kapu a Beállításokban KI van kapcsolva "
        f"(dashboard.gate_order), ezért az `atr_min_pct`/`atr_max_pct` "
        f"küszöbök SEHOL nem szűrnek — sem élesben, sem a backtestben. "
        f"v3.27.0 előtt ez az oszlop csak kijelzés volt, és a kivétele nem "
        f"befolyásolta a szűrést. Ha szűrni akarsz, kapcsold vissza a kaput; "
        f"ha nem, a küszöböket is nullázd, hogy a kettő ne mondjon mást."))


# ---------------------------------------------------------------------------
# 4. Holt kulcs: a napi limit két forrása
# ---------------------------------------------------------------------------

def _check_daily_limit(cfg: dict, out: list) -> None:
    """`daily_loss_limit_usd` > 0 esetén a `_pct` SOSEM számít (lásd
    `backtest.daily_limit_usd`). A `_pct` ilyenkor holt kulcs — de ott áll a
    fájlban a saját magyarázatával, tehát könnyű azt hinni, hogy ő a mérvadó."""
    tc = cfg.get("trading") or {}
    usd = tc.get("daily_loss_limit_usd")
    pct = tc.get("daily_loss_limit_pct")
    try:
        usd = float(usd or 0)
    except (TypeError, ValueError):
        usd = 0.0
    if usd > 0 and pct is not None:
        out.append(_finding(
            INFO, "daily_limit_pct_dead",
            f"A napi limit a rögzített {usd:.0f}$ (daily_loss_limit_usd); a "
            f"daily_loss_limit_pct={pct} MELLETTE HOLT — csak akkor lépne életbe, "
            f"ha az usd 0/hiányzó lenne."))


# ---------------------------------------------------------------------------
# 5. Régi és új kapu-config együtt
# ---------------------------------------------------------------------------

def _check_gate_config_shadowing(cfg: dict, out: list) -> None:
    """A `gates` szekció ÁRNYÉKOLJA a régi `tf_align.gate` listát.

    A feloldás sorrendje: pár-gates → globális gates → LEGACY lista → beépített.
    Ha valaki felvesz egy globális `gates.tf_align` bejegyzést, a meglévő per-pár
    `tf_align.gate` listák NÉMÁN hatástalanná válnak. Ez ma nem áll fenn — de ha
    egyszer előáll, ez a jelzés spórolja meg a keresést."""
    glob = (cfg.get("gates") or {}).get("tf_align")
    if not isinstance(glob, dict):
        return
    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        ta = pc.get("tf_align")
        # Csak akkor árnyékol, ha a páron NINCS saját gates.tf_align felülírás.
        pair_g = (pc.get("gates") or {}).get("tf_align")
        if isinstance(ta, dict) and "gate" in ta and not isinstance(pair_g, dict):
            out.append(_finding(
                WARN, "legacy_tf_gate_shadowed",
                f"{sym}: a régi tf_align.gate={ta.get('gate')!r} lista HATÁSTALAN, "
                f"mert a globális `gates.tf_align` szekció megelőzi. Vidd át a "
                f"beállítást a `gates` szekcióba, vagy töröld a régi listát.", sym))


# ---------------------------------------------------------------------------
# 6. Több stratégia egy páron, házirend nélkül
# ---------------------------------------------------------------------------

def _check_same_symbol_policy(cfg: dict, out: list) -> None:
    """Két KÖTŐ stratégia egy páron `independent` házirenddel egymással SZEMBE is
    nyithat (hedge számlán). Ez lehet szándékos — de legyen kimondva.

    Csak akkor szólunk, ha tényleg előállhat: legalább két stratégia engedélyezve,
    és legalább kettő közülük VALÓDI kötés módban (a „csak jelzés" nem köt)."""
    from core import symbol_policy as _sp
    from core import trade_mode as _tm
    from strategy import enabled_strategy_names

    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        names = enabled_strategy_names(cfg, sym) or []
        trading = [n for n in names if not _tm.is_signal_only(cfg, sym, n)]
        if len(trading) < 2:
            continue
        if _sp.resolve(cfg, sym) != _sp.INDEPENDENT:
            continue
        out.append(_finding(
            INFO, "independent_multi_strategy",
            f"{sym}: {len(trading)} stratégia köt valódit ({', '.join(trading)}) "
            f"'{_sp.INDEPENDENT}' házirenddel → egyszerre nyithatnak EGYMÁSSAL "
            f"SZEMBE is. Szigorítás: trading.same_symbol_policy = "
            f"'{_sp.ONE_PER_SYMBOL}' vagy '{_sp.NO_OPPOSITE}'.", sym))


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 7. „Csak jelzés" mód kikapcsolt vizualizációval
# ---------------------------------------------------------------------------

def _check_invisible_signal_mode(cfg: dict, out: list) -> None:
    """A `signal` mód CÉLJA a megfigyelés — kikapcsolt rajzzal viszont vak.

    A „csak jelzés" azért van, hogy egy stratégiát élesben, pénz nélkül nézhess:
    mindent kiszámol, de nem küld megbízást. Ha közben a vizualizációja ÉS a
    kötés-rétege is ki van kapcsolva, a charton semmi nem látszik belőle — a
    beállítás így pontosan azt a célt nem szolgálja, amiért bekapcsoltad.

    A leletet STRATÉGIÁNKÉNT ÖSSZEVONJUK. Egy „csak jelzés" mód tipikusan az összes
    páron egyszerre áll be, tehát páronként külön sor tíz azonos üzenetet adna
    minden induláskor — az ilyen mindenütt-ott-ülő jelzés pontosan úgy válik
    láthatatlanná, mint amiről a `gates.badge` doksija is ír."""
    from core import trade_mode as _tm
    from core import viz_prefs as _vp
    from core import run_state as _rs
    from strategy import enabled_strategy_names

    by_strategy: dict = {}
    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        names = enabled_strategy_names(cfg, sym) or []
        live = set(_rs.live_strategies(cfg, sym, names) or [])
        for n in names:
            if not _tm.is_signal_only(cfg, sym, n):
                continue
            # Csak a ténylegesen FUTÓ stratégia érdekes: egy megállítottnál a
            # kikapcsolt rajz teljesen rendben van.
            if n not in live:
                continue
            if _vp.viz_on(cfg, sym, n) or _vp.trades_on(cfg, sym, n):
                continue
            by_strategy.setdefault(n, []).append(sym)

    for n, syms in by_strategy.items():
        out.append(_finding(
            INFO, "signal_mode_invisible",
            f"{n}: 'csak jelzés' módban FUT {len(syms)} páron ({', '.join(syms)}), "
            f"de sem a vizualizációja, sem a kötés-rétege nem látszik "
            f"(strategy_viz / strategy_trades) → nem látod, mit csinálna, pedig a "
            f"'csak jelzés' épp ezért van. Kapcsold be az instrumentum "
            f"beállításainál (kattints a pár nevére).",
            syms[0] if len(syms) == 1 else None))


_CHECKS = (
    _check_gate_preconditions,
    _check_stale_strategy_keys,
    _check_costs,
    _check_sizing,
    _check_volatility_gate_off,
    _check_daily_limit,
    _check_gate_config_shadowing,
    _check_same_symbol_policy,
    _check_invisible_signal_mode,
)


# ---------------------------------------------------------------------------
# A CÉLÁR és a KILÉPÉSI PRESET összhangja
# ---------------------------------------------------------------------------
# ⚠ MÉRVE (2026-08-23), és ez a legmeglepőbb kölcsönhatás, amit eddig találtunk:
# a kettő NEM független, és ELLENTÉTES irányba lejt. UsaInd, ugyanaz az ablak:
#
#     TP        BE+trailing        kockázatcsökkentés NÉLKÜL
#     1,5R          +870                    +1870
#     2,7R         +1991                    +1587
#     3,0R         +2080                    +1557
#
# TRAILINGGEL a HOSSZÚ célár a jó: a stop követi az árat, hagyja futni a
# nyertest, és közben véd. TRAILING NÉLKÜL a RÖVID: a távoli célárig gyakran nem
# ér el az ár, mielőtt visszafordul. A UK100-on ugyanez.
#
# ⚠ EZÉRT: ha valaki kikapcsolja a kockázatcsökkentést, a célárat is CSÖKKENTENIE
# kell — különben a távoli TP védelem nélkül marad, és a nyereség visszafolyik.
# A fordítottja is igaz: rövid célár mellett a trailing levágja a nyertest,
# mielőtt bármit hozna. Egy éles mérésben ez a tévedés 1121 dollárba került volna
# (a javaslat a MÁSIK konfigurációban mért görbéből jött).
TP_LONG = 2.0        # e fölött „hosszú" célár   — védelem nélkül kockázatos
TP_SHORT = 1.5       # e alatt „rövid"           — trailinggel levágja a nyertest


def tp_preset_conflict(preset: str, tp_rr) -> "str | None":
    """A célár és a kilépési preset ellentmondása — TISZTA függvény.

    `preset`: a `core.risk_reduction` preset neve; `"none"` = a stop MARAD.
    Visszaad: az ellentmondás szövege, vagy `None`, ha összhangban vannak."""
    try:
        tp = float(tp_rr)
    except (TypeError, ValueError):
        return None
    if tp <= 0:
        return None
    keeps_stop = str(preset or "").lower() == "none"
    if keeps_stop and tp >= TP_LONG:
        return (f"a célár {tp:.2f}R (hosszú), de a kockázatcsökkentés KI van "
                f"kapcsolva (a stop marad a helyén) — védelem nélkül a távoli "
                f"célárig gyakran nem ér el az ár. Mérve: trailing nélkül a "
                f"RÖVIDEBB célár (~1,5R) a jobb.")
    if (not keeps_stop) and tp <= TP_SHORT:
        return (f"a célár {tp:.2f}R (rövid), miközben a kilépési preset MOZGATJA "
                f"a stopot — a trailing így levágja a nyertest, mielőtt a célár "
                f"hozna. Mérve: trailinggel a HOSSZABB célár (~2,5–3R) a jobb.")
    return None


def _check_tp_vs_preset(cfg: dict, out: list, preset_of, tp_of) -> None:
    """A koherencia-ellenőrzés PÁRONKÉNT, a beadott állapot-olvasókkal."""
    from strategy import enabled_strategy_names
    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        try:
            preset = preset_of(sym)
        except Exception:
            continue
        for name in (enabled_strategy_names(cfg, sym) or []):
            try:
                tp = tp_of(sym, name)
            except Exception:
                continue
            msg = tp_preset_conflict(preset, tp)
            if msg:
                out.append(_finding(WARN, "tp_vs_preset",
                                    f"{sym}/{name}: {msg}", sym))


def check_with_state(cfg: dict, preset_of=None, tp_of=None) -> list:
    """`check()` + az ÁLLAPOT-FÜGGŐ ellenőrzések (mentett paraméterek, rr-preset).

    ⚠ Miért külön függvény. A `check()` szerződése az, hogy TISZTA: dictet kap,
    listát ad, se fájl, se MT5 — így egy sorban tesztelhető. A célár↔preset
    összhanghoz viszont két FÁJLBÓL jövő adat kell (`data/risk_mode.json` és a
    mentett paraméterkészlet). A szerződést nem törjük el: az olvasók
    BEADHATÓK (a teszt így tiszta marad), és csak az alapértelmezésük nyúl
    fájlhoz."""
    out = list(check(cfg))
    if preset_of is None:
        def preset_of(sym):
            from core import rr_state as _rs
            return _rs.get_preset(sym)
    if tp_of is None:
        def tp_of(sym, name):
            import json
            from core.params_store import params_file
            f = params_file(sym, name)
            if not f.exists():
                return None
            return (json.loads(f.read_text(encoding="utf-8")).get("params")
                    or {}).get("tp_rr_ratio")
    try:
        _check_tp_vs_preset(cfg or {}, out, preset_of, tp_of)
    except Exception as e:
        log.debug("célár↔preset ellenőrzés hiba: %s", e)
    return out


def check(cfg: dict) -> list:
    """Minden koherencia-ellenőrzés. `[{level, code, symbol, message}, …]`.

    Egy ellenőrzés hibája NEM buktathatja a többit (és főleg nem az indulást):
    a config-vizsgálat kényelmi funkció, nem kapu."""
    out: list = []
    for fn in _CHECKS:
        try:
            fn(cfg or {}, out)
        except Exception as e:            # pragma: no cover — védőháló
            log.debug("config-ellenőrzés hiba (%s): %s", fn.__name__, e)
    return out


def log_findings(cfg: dict, logger=None) -> list:
    """Az ellenőrzés lefuttatása + KIÍRÁSA a naplóba. Visszaad: a leletek.

    ⚠ A TELJES képet adja (`check_with_state`): az állapot-függő leletek — mint a
    célár↔kilépési preset ellentmondás — épp azok, amiket senki nem venne észre.

    Ezt hívják a belépési pontok. A `warn` szintűek `log.warning`-gal mennek (ezek
    némán hatástalan beállítások), az `info`-k `log.info`-val."""
    findings = check_with_state(cfg)
    lg = logger or log
    if not findings:
        return findings
    _w = [f for f in findings if f["level"] == WARN]
    lg.warning("Config-ellenőrzés: %d lelet (%d figyelmeztetés)",
               len(findings), len(_w))
    for f in findings:
        (lg.warning if f["level"] == WARN else lg.info)("  ⚙ %s", f["message"])
    return findings
