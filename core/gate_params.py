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
from core.i18n import t as _t

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
    némán a motorig.

    ⚠ A FELIRAT ÉS A SÚGÓ NINCS ITT: a nyelvi katalógusban élnek
    (`gp.<kapu>.<kulcs>.label` / `.help`), és a `label`/`help` tulajdonság a
    HÍVÁSKOR oldja fel őket. Egy modul-betöltéskor kiszámolt szöveg befagyna a
    betöltéskori nyelvbe — ez a modul pedig import-időben épül fel.

    A `gate` mezőt a `_SPECS` definíciója után egy ciklus tölti ki (a spec a
    saját kapuja nélkül nem tudná, melyik kulcsot kérdezze)."""

    __slots__ = ("key", "gate", "kind", "default", "choices", "lo", "hi")

    def __init__(self, key, kind, default, choices=None, lo=None, hi=None):
        self.key = key
        self.gate = ""
        self.kind = kind
        self.default = default
        self.choices = choices if callable(choices) else tuple(choices or ())
        self.lo = lo
        self.hi = hi

    @property
    def label(self) -> str:
        return _t(f"gp.{self.gate}.{self.key}.label")

    @property
    def help(self) -> str:
        """Üres, ha nincs súgó — nem a nyers kulcs (a felület csak akkor
        rajzol halvány sort, ha van mit mondania)."""
        k = f"gp.{self.gate}.{self.key}.help"
        txt = _t(k)
        return "" if txt == k else txt

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
        ParamSpec("max_spread_atr_ratio", FLOAT, 0.20, lo=0.0, hi=5.0),
        ParamSpec("min_spread_mult", FLOAT, 1.5, lo=0.0, hi=50.0),
        ParamSpec("atr_period", INT, 14, lo=2, hi=500),
    ),
    _g.TF_ALIGN: (
        ParamSpec("enabled", BOOL, True),
        ParamSpec("timeframes", MULTI, [1, 5, 15], choices=_TF_CHOICES),
        ParamSpec("sma_period", INT, 50, lo=2, hi=1000),
        ParamSpec("viz", BOOL, False),
    ),
    _g.MARKET: (
        ParamSpec("market_strategy", CHOICE, "", choices=_market_choices),
        ParamSpec("adverse", MULTI, list(_g.MARKET_ADVERSE_DEFAULT),
                  choices=_adverse_choices),
        ParamSpec("market_viz", BOOL, False),
    ),
    _g.COST: (
        ParamSpec("max_rr_distortion", FLOAT, 0.25, lo=0.0, hi=10.0),
    ),
    _g.MOMENTUM: (
        ParamSpec("basis", CHOICE, "sma",
                  choices=lambda: [("sma", _t("gp.basis.sma")),
                                   ("tf", _t("gp.basis.tf"))]),
        ParamSpec("idle_threshold", FLOAT, 0.35, lo=0.0, hi=20.0),
        ParamSpec("timeframe", CHOICE, 15, choices=_TF_CHOICES),
        ParamSpec("sma_fast", INT, 8, lo=2, hi=1000),
        ParamSpec("sma_mid", INT, 32, lo=2, hi=2000),
        ParamSpec("sma_slow", INT, 100, lo=2, hi=5000),
        ParamSpec("timeframes", MULTI, [1, 5, 15], choices=_TF_CHOICES),
        ParamSpec("tf_sma", INT, 50, lo=2, hi=1000),
        ParamSpec("vol_window", INT, 14, lo=2, hi=500),
    ),
}



# ⚠ A spec a SAJÁT KAPUJÁT is ismeri: a felirata és a súgója a katalógusban
# `gp.<kapu>.<kulcs>.label` alatt él, és a kulcs-nevek kapuk közt ismétlődnek
# (`timeframes` a tf_align-ban ÉS a lendületben). A kapu nélkül a kettő
# összeakadna — némán, egymás szövegét mutatva.
for _gate_key, _gate_specs in _SPECS.items():
    for _spec in _gate_specs:
        _spec.gate = _gate_key

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
                                                _t("gp.err.unknown", label=spec.label))
    if spec.kind == MULTI:
        vals = {v for v, _ in choices_of(spec)}
        picked = [v for v in (raw or []) if v in vals]
        return picked, None
    txt = str(raw).strip().replace(",", ".")     # magyar tizedesvessző is jó
    if not txt:
        return spec.default, _t("gp.err.empty", label=spec.label)
    try:
        val = int(txt) if spec.kind == INT else float(txt)
    except ValueError:
        return spec.default, _t("gp.err.nan", label=spec.label, value=repr(raw))
    if spec.lo is not None and val < spec.lo:
        return spec.default, _t("gp.err.too_low", label=spec.label, value=val,
                                limit=spec.lo)
    if spec.hi is not None and val > spec.hi:
        return spec.default, _t("gp.err.too_high", label=spec.label, value=val,
                                limit=spec.hi)
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
            out.append(_t("gp.err.tf_count", n=len(tfs)))
    if key == _g.MOMENTUM:
        out += extra_errors_momentum(values)
        if str(values.get("basis")) == "tf" and not values.get("timeframes"):
            out.append(_t("gp.err.tf_basis"))
    return out


# ── A MÉRT állapot emberi kiírása ───────────────────────────────────────────
# A `ctx` ugyanaz, amit a `gates.evaluate` kap (`gates.ctx_from_state`), tehát a
# számok GARANTÁLTAN azok, amikkel a kapu dönt — nem külön számolt „kb. ugyanaz”.


def _pts_txt(v) -> str:
    """„{n} pont" — az egyetlen hely, ahol a pont-mértékegység szövegbe kerül."""
    if v is None:
        return "—"
    return _t("gp.val.points", n=f"{float(v):,.0f}".replace(",", " "))


def measured_rows(key: str, ctx: dict) -> list:
    """`[(címke, érték_szöveg), …]` — a kapu ablakának felső, csak-olvasható
    blokkja: „mi a helyzet MOST ezen az instrumentumon”."""
    ctx = ctx or {}
    if key == _g.SPREAD:
        cur = ctx.get("spread_points")
        cap = ctx.get("max_spread_points")
        atr = ctx.get("atr_price")
        pt = ctx.get("point_size")
        rows = [(_t("gp.row.spread_now"),
                 _pts_txt(cur)),
                (_t("gp.row.spread_cap"),
                 _pts_txt(cap) if cap not in (None, 0)
                 and cap != float("inf") else "—")]
        if atr:
            rows.append((_t("gp.row.atr_main"),
                         f"{atr:.5f}"
                         + (f"  ({_pts_txt(atr / pt)})" if pt else "")))
        norm = ctx.get("normal_spread_points")
        if norm:
            rows.append((_t("gp.row.spread_normal"), _pts_txt(float(norm))))
        return rows
    if key == _g.TF_ALIGN:
        signs = ctx.get("tf_align_signs") or []
        labels = ctx.get("tf_align_labels") or []
        arrows = {1: "↑", -1: "↓", 0: "·"}
        txt = "  ".join(f"{labels[i] if i < len(labels) else '?'} "
                        f"{arrows.get(int(s), '·')}" for i, s in enumerate(signs))
        d = ctx.get("tf_align_dir")
        return [(_t("gp.row.tf_dirs"), txt or "—"),
                (_t("gp.row.tf_align"), d or _t("gp.val.no_align"))]
    if key == _g.MARKET:
        return [(_t("gp.row.classifier"),
                 ctx.get("market_name") or _t("gp.val.none_sel")),
                (_t("gp.row.classification"), ctx.get("market_label") or "—")]
    if key == _g.COST:
        from core import cost_gate as _cg
        sl, tp = ctx.get("plan_sl_points"), ctx.get("plan_tp_points")
        sp = ctx.get("spread_points")
        cap = ctx.get("cost_max_distortion")
        rows = [(_t("gp.row.planned_sl"), _pts_txt(sl) if sl else "—"),
                (_t("gp.row.spread_now"), _pts_txt(sp))]
        if sl and tp:
            rows.append((_t("gp.row.payout_ratio"),
                         f"{float(tp) / float(sl):.1f}:1"))
            rows.append((_t("gp.row.path_ratio"), _cg.cell_text(sl, tp, sp)))
        if cap is not None:
            rows.append((_t("gp.row.limit"), f"{float(cap) * 100:+.0f}%"))
        return rows
    if key == _g.VOLATILITY:
        from core import vol_baseline as _vb
        atr = ctx.get("atr_price")
        base = ctx.get("atr_baseline")
        prm = ctx.get("vol_params") or {}
        pt = ctx.get("point_size")

        def _pts(v):
            return _pts_txt(v / pt) if (v and pt) else "—"

        rows = [(_t("gp.row.atr_now"), _pts(atr)),
                (_t("gp.row.baseline"), _pts(base))]
        if atr and base:
            st = _vb.status(float(atr), prm, float(base))
            rows.append((_t("gp.row.ratio"), f"{st['ratio']:.2f}×"))
            rows.append((_t("gp.row.band"),
                         f"{_pts(st['lo'])} … {_pts(st['hi'])}"
                         if (st["lo"] or st["hi"]) else _t("gp.val.no_limit")))
            rows.append((_t("gp.row.state"),
                         _t("gp.val.ok") if st["ok"] else f"⛔ {st['why']}"))
        nb = _vb.baseline_bars(prm)
        rows.append((_t("gp.row.baseline_kind"),
                     _t("gp.val.rolling", bars=nb, days=nb // 96) if nb > 0
                     else _t("gp.val.frozen")))
        return rows
    if key == _g.MOMENTUM:
        from core import momentum as _m
        val = ctx.get("momentum")
        thr = ctx.get("momentum_idle_threshold")
        v = val if val is not None else float("nan")
        rows = [(_t("gp.row.momentum_now"), _m.cell_text(val))]
        d = _m.direction(v)
        rows.append((_t("gp.row.direction"),
                     {"BUY": _t("gp.val.up"),
                      "SELL": _t("gp.val.down")}.get(d, "—")))
        if thr is not None:
            rows.append((_t("gp.row.idle_threshold"), f"{float(thr):.2f}"))
            rows.append((_t("gp.row.state"), momentum_state_text(v, thr)))
            # ⚠ A szótár KIÍRVA: a mért érték önmagában nem árulja el, hogy
            # mihez képest sok vagy kevés, és melyik szó milyen állapotot jelöl.
            # (Enélkül a felhasználó olyan állapotra vár, ami nem is létezik.)
            rows.append((_t("gp.row.states"), momentum_states()))
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

def momentum_states() -> str:
    """A kapu KÉT állapotának szótára — az aktív nyelven.

    ⚠ Függvény, nem konstans: egy modul-szintű `_t(...)` a betöltéskori
    nyelvbe fagyna."""
    return _t("gp.mom.states")


def momentum_state_text(value, threshold) -> str:
    """Az állapot a MÉRÉSSEL EGYÜTT — a puszta szó nem mondja meg, mihez képest."""
    import math as _math
    from core import momentum as _m
    if value is None or _math.isnan(float(value)):
        return _t("gp.mom.no_data")
    mag, thr = abs(float(value)), float(threshold)
    if _m.is_idle(value, {"idle_threshold": thr}):
        return _t("gp.mom.idle", value=f"{mag:.2f}", threshold=f"{thr:.2f}")
    return _t("gp.mom.running", value=f"{mag:.2f}", threshold=f"{thr:.2f}")


def extra_errors_momentum(values: dict) -> list:
    """A három SMA-nak NÖVEKVŐ sorrendben kell lennie, különben a „fordulat”
    előjele értelmetlen (a gyors-mínusz-lassú megfordulna)."""
    f, m, s = (values.get("sma_fast"), values.get("sma_mid"),
               values.get("sma_slow"))
    if None in (f, m, s):
        return []
    if not (f < m < s):
        return [_t("gp.err.sma_order", fast=f, mid=m, slow=s)]
    return []
