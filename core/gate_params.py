"""
A belépő-kapuk SAJÁT paraméterei — deklaratívan, egy helyen.

MIÉRT KELL. A `core/gates.py` a kapuk *hatását* mondja meg (blokkol / kockázat-
csökkentés / ki), a *számaikat* viszont eddig nem ismerte senki egységesen: a
spread küszöbei a `core/execution_params.py`-ban laktak és csak a stratégia
paraméter-ablakának „Végrehajtás" kategóriájában lehetett hozzájuk férni (a
`Spread` cellára kattintva a teljes wpr_sma-paraméterlista nyílt — pont az, amit
nem kerestél), a TF-együttállásé egy kézzel írt külön ablakban, a piac-előszűrőé
pedig az instrumentum-ablakban.

Ez a modul TISZTA (se tkinter, se MT5, se fájl): csak leírja, hogy egy kapunak
milyen számai vannak, mi az alapértékük, hogyan kell beolvasni és ellenőrizni
őket, és hogy a MÉRT állapotából mit érdemes kiírni. A tárolás gazdája marad a
mai modul (`execution_params`, `tf_align`, `gates`) — ez a réteg csak közös
nyelvet ad, hogy EGY ablak mindegyiket ki tudja szolgálni
(`dashboard/gate_dialog.py`).
"""

from __future__ import annotations

from core import gates as _g

# ── Egy paraméter FAJTÁJA (a szerkesztő ebből tudja, mit rajzoljon) ──────────
FLOAT = "float"
INT = "int"
BOOL = "bool"
CHOICE = "choice"     # egy érték egy zárt listából
MULTI = "multi"       # részhalmaz egy zárt listából (jelölőnégyzetek)


class ParamSpec:
    """Egy szerkeszthető kapu-paraméter leírása.

    `choices`: `[(érték, címke), …]` a CHOICE/MULTI fajtákhoz. LEHET hívható is
    (nulla argumentummal): a piac-osztályozók listája futásidőben derül ki a
    registerből, és modul-betöltéskor még nem szabad importálni.
    `lo`/`hi`: megengedett tartomány (None = nincs korlát) — a szerkesztő ezt
    kényszeríti ki, hogy egy elgépelt 20-as ATR-hányad (2000%) ne jusson el
    némán a motorig."""

    __slots__ = ("key", "label", "kind", "default", "help", "choices", "lo", "hi")

    def __init__(self, key, label, kind, default, help="", choices=None,
                 lo=None, hi=None):
        self.key = key
        self.label = label
        self.kind = kind
        self.default = default
        self.help = help
        self.choices = choices if callable(choices) else tuple(choices or ())
        self.lo = lo
        self.hi = hi

    def __repr__(self):                       # a teszt-hibaüzenetekhez
        return f"ParamSpec({self.key!r}, {self.kind})"


_TF_CHOICES = [(1, "M1"), (5, "M5"), (15, "M15"), (30, "M30"),
               (60, "H1"), (240, "H4")]


def _market_choices():
    """A piac-osztályozók + a „nincs" tétel. Lusta import: a `market_strategy`
    a `regime`-et húzza be, és ez a modul enélkül is használható."""
    try:
        from core import market_strategy as _ms
        names = _ms.registered_market_names()
        labels = _ms.NAME_HU
    except Exception:
        names, labels = [], {}
    return [("", "Nincs")] + [(n, labels.get(n, n)) for n in names]


def _adverse_choices():
    """Mely piac-kategóriák jelölhetők „kedvezőtlennek" (a piac-kapu bukása)."""
    try:
        from core import market_strategy as _ms
        from core import regime as _r
        order = (_r.CLEAN_BULL, _r.CLEAN_BEAR, _r.VOLATILE_BULL, _r.VOLATILE_BEAR,
                 _r.RANGING, _r.DEAD, _r.UNCERTAIN, _r.TRANSITION)
        return [(c, _ms.display(c)[0]) for c in order]
    except Exception:
        return []


# ── Kapunként a szerkeszthető számok ────────────────────────────────────────
# A sorrend a felületen látszó sorrend. A `help` a mező alatti halvány sor: a
# képlet, amiből az érték hat — enélkül egy 0.20-as „arány" semmit nem mond.

_SPECS = {
    _g.SPREAD: (
        ParamSpec("max_spread_atr_ratio", "Spread ATR-hányada", FLOAT, 0.20,
                  "A megengedett spread az ATR ekkora része. "
                  "határ = max(padló, (ATR / point) × ez)", lo=0.0, hi=5.0),
        ParamSpec("min_spread_mult", "Padló: a normál spread szorzója", FLOAT, 1.5,
                  "Az ALSÓ küszöb az instrumentum saját tipikus spreadjének "
                  "ennyiszerese — így minden páron ugyanazt jelenti.",
                  lo=0.0, hi=50.0),
        ParamSpec("atr_period", "ATR-ablak (gyertya)", INT, 14,
                  "A volatilitás mércéje a fő időkereten.", lo=2, hi=500),
    ),
    _g.TF_ALIGN: (
        ParamSpec("enabled", "Bekapcsolva — figyeli az együttállást", BOOL, True,
                  "Ez tölti az „Együtt” oszlopot és ad bemenetet a kapunak."),
        ParamSpec("timeframes", "Figyelt idősíkok (2–6)", MULTI, [1, 5, 15],
                  "Minden kiválasztott idősíkon az SMA-hoz mért irány számít.",
                  choices=_TF_CHOICES),
        ParamSpec("sma_period", "SMA-periódus", INT, 50,
                  "Az irányt a záróár és ennek az SMA-nak a viszonya adja.",
                  lo=2, hi=1000),
        ParamSpec("viz", "SMA-vonalak a charton (viz)", BOOL, False,
                  "Csak rajz — a figyelés ettől függetlenül működik."),
    ),
    _g.MARKET: (
        ParamSpec("market_strategy", "Piac-osztályozó", CHOICE, "",
                  "Ez tölti a „Piac” oszlopot. „Nincs” → a kapu néma.",
                  choices=_market_choices),
        ParamSpec("adverse", "KEDVEZŐTLEN besorolások (ezeken bukik a kapu)",
                  MULTI, list(_g.MARKET_ADVERSE_DEFAULT),
                  "A kapu csak akkor szól bele, ha a hatása nem „Ki”.",
                  choices=_adverse_choices),
        ParamSpec("market_viz", "Piac-sáv a charton (viz)", BOOL, False,
                  "Csak rajz."),
    ),
    _g.COST: (
        ParamSpec("max_rr_distortion", "Megengedett tavolsag-hatrany", FLOAT, 0.25,
                  "A KIFIZETES aranya nem valtozik a spreadtol — a megteendo "
                  "UT igen. 0,25 = a 2:1-es kifizetesert legfeljebb 2,5:1 eselyu "
                  "utat vallalunk. Merve: EURCHF +70%, EURGBP +72%, EURJPY +31%, "
                  "EURUSD +21%, GOLD +5%, UsaTec +4%.", lo=0.0, hi=10.0),
    ),
    _g.MOMENTUM: (
        ParamSpec("basis", "Mérési alap", CHOICE, "sma",
                  "„Egy idősík, 3 SMA”: a gyors/közép/lassú átlag távolsága — ez a "
                  "legszorosabb fordulatszámmérő. „Három idősík”: idősíkonként a "
                  "záróár SMA-tól vett távolsága, átlagolva.",
                  choices=lambda: [("sma", "Egy idősík, 3 SMA"),
                                   ("tf", "Három idősík, egy SMA")]),
        ParamSpec("idle_threshold", "Alapjárat-küszöb", FLOAT, 0.35,
                  "Ez alatt „áll a piac”. Egysége: átlagos gyertya-elmozdulás — "
                  "0,35 azt jelenti, hogy az átlagok egy átlagos gyertya "
                  "harmadánál közelebb vannak egymáshoz.", lo=0.0, hi=20.0),
        ParamSpec("timeframe", "Idősík (az „egy idősík” alaphoz)", CHOICE, 15,
                  "Ezen fut a három SMA.", choices=_TF_CHOICES),
        ParamSpec("sma_fast", "Gyors SMA", INT, 8, "", lo=2, hi=1000),
        ParamSpec("sma_mid", "Közepes SMA", INT, 32, "", lo=2, hi=2000),
        ParamSpec("sma_slow", "Lassú SMA", INT, 100,
                  "A három SMA-ból két „fordulat” adódik (gyors↔közép, "
                  "közép↔lassú), az átlaguk a mutató.", lo=2, hi=5000),
        ParamSpec("timeframes", "Idősíkok (a „három idősík” alaphoz)", MULTI,
                  [1, 5, 15], "Idősíkonként egy fordulat, átlagolva.",
                  choices=_TF_CHOICES),
        ParamSpec("tf_sma", "SMA-periódus (a „három idősík” alaphoz)", INT, 50,
                  "Minden kiválasztott idősíkon ugyanez.", lo=2, hi=1000),
        ParamSpec("vol_window", "Normáló ablak (gyertya)", INT, 14,
                  "Ennyi gyertya átlagos abszolút záróár-elmozdulása a mérce — "
                  "ettől jelent ugyanazt a szám GOLD-on és EURUSD-n.",
                  lo=2, hi=500),
    ),
}


def specs_for(key: str) -> tuple:
    """Egy kapu szerkeszthető paraméterei (üres, ha a kapunak nincs saját száma)."""
    return _SPECS.get(key, ())


def choices_of(spec: ParamSpec) -> list:
    """A `choices` feloldva. Lehet hívható (lusta) is — a piac-osztályozók
    listája futásidőben derül ki a registerből."""
    c = spec.choices
    return list(c()) if callable(c) else list(c)


# ── Ellenőrzés / értelmezés ─────────────────────────────────────────────────

def parse(spec: ParamSpec, raw):
    """`(érték, hibaüzenet)` — a hiba `None`, ha rendben.

    A szerkesztő NYERS szöveget ad (Entry), a jelölőnégyzetek bool-t, a
    többválasztós mezők listát. A tartomány-ellenőrzés itt van, nem a felületen:
    így teszttel is bizonyítható, hogy egy elgépelt érték nem jut a motorig."""
    if spec.kind == BOOL:
        return bool(raw), None
    if spec.kind == CHOICE:
        vals = [v for v, _ in choices_of(spec)]
        return (raw, None) if raw in vals else (spec.default,
                                                f"{spec.label}: ismeretlen érték")
    if spec.kind == MULTI:
        vals = {v for v, _ in choices_of(spec)}
        picked = [v for v in (raw or []) if v in vals]
        return picked, None
    txt = str(raw).strip().replace(",", ".")     # magyar tizedesvessző is jó
    if not txt:
        return spec.default, f"{spec.label}: üres"
    try:
        val = int(txt) if spec.kind == INT else float(txt)
    except ValueError:
        return spec.default, f"{spec.label}: nem szám ({raw!r})"
    if spec.lo is not None and val < spec.lo:
        return spec.default, f"{spec.label}: {val} < {spec.lo} (alsó határ)"
    if spec.hi is not None and val > spec.hi:
        return spec.default, f"{spec.label}: {val} > {spec.hi} (felső határ)"
    return val, None


def parse_all(key: str, raw_by_key: dict) -> tuple:
    """`(értékek, hibák)` egy kapu teljes űrlapjára. Hiba esetén a hívó NE mentsen:
    a részleges mentés a legrosszabb — a fele beállítás elmenne, a másik fele nem."""
    values, errors = {}, []
    for spec in specs_for(key):
        if spec.key not in (raw_by_key or {}):
            continue
        val, err = parse(spec, raw_by_key[spec.key])
        if err:
            errors.append(err)
        else:
            values[spec.key] = val
    return values, errors


def extra_errors(key: str, values: dict) -> list:
    """Kapu-specifikus, MEZŐK KÖZTI szabályok (amit egy mező önmagában nem lát)."""
    out = []
    if key == _g.TF_ALIGN:
        tfs = values.get("timeframes")
        if tfs is not None and not (2 <= len(tfs) <= 6):
            out.append("Idősíkok: 2 és 6 között válassz "
                       f"(most {len(tfs)}) — egyetlen idősík nem „együttállás”.")
    if key == _g.MOMENTUM:
        out += extra_errors_momentum(values)
        if str(values.get("basis")) == "tf" and not values.get("timeframes"):
            out.append("A „három idősík” alaphoz legalább egy idősík kell.")
    return out


# ── A MÉRT állapot emberi kiírása ───────────────────────────────────────────
# A `ctx` ugyanaz, amit a `gates.evaluate` kap (`gates.ctx_from_state`), tehát a
# számok GARANTÁLTAN azok, amikkel a kapu dönt — nem külön számolt „kb. ugyanaz”.

def measured_rows(key: str, ctx: dict) -> list:
    """`[(címke, érték_szöveg), …]` — a kapu ablakának felső, csak-olvasható
    blokkja: „mi a helyzet MOST ezen az instrumentumon”."""
    ctx = ctx or {}
    if key == _g.SPREAD:
        cur = ctx.get("spread_points")
        cap = ctx.get("max_spread_points")
        atr = ctx.get("atr_price")
        pt = ctx.get("point_size")
        rows = [("Jelenlegi spread", f"{cur:.0f} pont" if cur is not None else "—"),
                ("Számított határ",
                 f"{cap:.0f} pont" if cap not in (None, 0) and cap != float("inf")
                 else "—")]
        if atr:
            rows.append(("ATR (fő időkeret)",
                         f"{atr:.5f}" + (f"  ({atr / pt:.0f} pont)" if pt else "")))
        norm = ctx.get("normal_spread_points")
        if norm:
            rows.append(("Instrumentum normál spreadje", f"{float(norm):.0f} pont"))
        return rows
    if key == _g.TF_ALIGN:
        signs = ctx.get("tf_align_signs") or []
        labels = ctx.get("tf_align_labels") or []
        arrows = {1: "↑", -1: "↓", 0: "·"}
        txt = "  ".join(f"{labels[i] if i < len(labels) else '?'} "
                        f"{arrows.get(int(s), '·')}" for i, s in enumerate(signs))
        d = ctx.get("tf_align_dir")
        return [("Idősík-irányok", txt or "—"),
                ("Együttállás", d or "nincs")]
    if key == _g.MARKET:
        return [("Osztályozó", ctx.get("market_name") or "nincs kiválasztva"),
                ("Jelenlegi besorolás", ctx.get("market_label") or "—")]
    if key == _g.COST:
        from core import cost_gate as _cg
        sl, tp = ctx.get("plan_sl_points"), ctx.get("plan_tp_points")
        sp = ctx.get("spread_points")
        cap = ctx.get("cost_max_distortion")
        rows = [("Tervezett SL", f"{sl:.0f} pont" if sl else "—"),
                ("Jelenlegi spread", f"{sp:.0f} pont" if sp is not None else "—")]
        if sl and tp:
            rows.append(("Kifizetes aranya", f"{float(tp) / float(sl):.1f}:1"))
            rows.append(("Megteendo ut aranya", _cg.cell_text(sl, tp, sp)))
        if cap is not None:
            rows.append(("Határ", f"{float(cap) * 100:+.0f}%"))
        return rows
    if key == _g.MOMENTUM:
        from core import momentum as _m
        val = ctx.get("momentum")
        thr = ctx.get("momentum_idle_threshold")
        v = val if val is not None else float("nan")
        rows = [("Fordulat most", _m.cell_text(val))]
        d = _m.direction(v)
        rows.append(("Irány", {"BUY": "felfelé", "SELL": "lefelé"}.get(d, "—")))
        if thr is not None:
            rows.append(("Alapjárat-küszöb", f"{float(thr):.2f}"))
            rows.append(("Állapot", momentum_state_text(v, thr)))
            # ⚠ A szótár KIÍRVA: a mért érték önmagában nem árulja el, hogy
            # mihez képest sok vagy kevés, és melyik szó milyen állapotot jelöl.
            # (Enélkül a felhasználó olyan állapotra vár, ami nem is létezik.)
            rows.append(("Lehetséges állapotok", MOMENTUM_STATES))
        return rows
    return []


# ---------------------------------------------------------------------------
# A Lendület-kapu ÁLLAPOT-SZÓTÁRA
# ---------------------------------------------------------------------------
# A kapunak PONTOSAN két állapota van: a küszöb alatt („alapjárat”) vagy fölötte.
# A korábbi „pörög” szó többet ígért ennél — azt sugallta, hogy a piac kimondottan
# élénk, holott a mérés csak annyit mond, hogy nem áll. A semleges „fut” pont ezt
# fedi le. Harmadik állapot az adathiány: a kapu ilyenkor NEM szűr (fail-open,
# mint a spread-kapu), ezért nem szabad „fut”-ként mutatni.

MOMENTUM_STATES = "alapjárat (küszöb alatt) · fut (küszöb fölött)"


def momentum_state_text(value, threshold) -> str:
    """Az állapot a MÉRÉSSEL EGYÜTT — a puszta szó nem mondja meg, mihez képest."""
    import math as _math
    from core import momentum as _m
    if value is None or _math.isnan(float(value)):
        return "nincs adat (a kapu átenged)"
    mag, thr = abs(float(value)), float(threshold)
    if _m.is_idle(value, {"idle_threshold": thr}):
        return f"ALAPJÁRAT — {mag:.2f} < {thr:.2f} (a kapu bukik)"
    return f"fut — {mag:.2f} ≥ {thr:.2f}"


def extra_errors_momentum(values: dict) -> list:
    """A három SMA-nak NÖVEKVŐ sorrendben kell lennie, különben a „fordulat”
    előjele értelmetlen (a gyors-mínusz-lassú megfordulna)."""
    f, m, s = (values.get("sma_fast"), values.get("sma_mid"),
               values.get("sma_slow"))
    if None in (f, m, s):
        return []
    if not (f < m < s):
        return [f"SMA-k: gyors < közepes < lassú kell legyen (most {f}/{m}/{s})."]
    return []
