"""Manuális előszűrő (Tibi, 2026-10-12 — „Program működése" rajz).

Config-ban kapcsolható; a táblán a Kapuk ELŐTT saját oszlop; a cellán lenyíló
(Nincs / Ne kereskedj! / Óvatosan / Szép ↑ / Szép ↓ / Szép ↕); új nap → Nincs.
A motorban kapu: Ne kereskedj → gátol, Óvatosan → fele kockázat, Szép ↑/↓ → az
ellenkező irány gátolva.

⚠ A valódi data/manual_filter.json-t és a config.json-t NEM írja (ideiglenes útvonal).
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import manual_filter as MF                             # noqa: E402
from core import gates as G, gate_bands as GB, gate_layout as GL  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


_tmp = Path(tempfile.mkdtemp()) / "manual_filter.json"
_valodi = MF.PATH
MF.PATH = _tmp
try:
    # ── tároló + napi visszaállás ─────────────────────────────────────────
    check("üres: minden Nincs", MF.state_of("GOLD") == MF.NONE)
    MF.set_state("GOLD", MF.NO_TRADE, day="2026-10-12")
    MF.set_state("Ger40", MF.BULL, day="2026-10-12")
    check("aznap visszaolvasható", MF.state_of("GOLD", day="2026-10-12") == MF.NO_TRADE
          and MF.state_of("Ger40", day="2026-10-12") == MF.BULL)
    check("⚠ ÚJ NAP → minden Nincs (a tegnapi nem ragad be)",
          MF.state_of("GOLD", day="2026-10-13") == MF.NONE
          and MF.states(day="2026-10-13") == {})
    MF.set_state("EURUSD", MF.CAUTIOUS, day="2026-10-13")
    check("új napi beíráskor a tegnapiak kiürülnek",
          MF.states(day="2026-10-13") == {"EURUSD": MF.CAUTIOUS})
    MF.set_state("EURUSD", MF.NONE, day="2026-10-13")
    check("a Nincs törli a bejegyzést", MF.states(day="2026-10-13") == {})
    try:
        MF.set_state("X", "valami")
        ok = False
    except ValueError:
        ok = True
    check("ismeretlen állapot → hiba", ok)
    check("a valódi fájl érintetlen (ideiglenes útvonal)", MF.PATH != _valodi)
finally:
    MF.PATH = _valodi

# ── irányfüggő ítélet ─────────────────────────────────────────────────────
L = MF.level_of
check("Ne kereskedj → mindkét irány bukik",
      L(MF.NO_TRADE, "BUY") == L(MF.NO_TRADE, "SELL") == MF.LEVEL_NO_TRADE)
check("Óvatosan → csökkentés", L(MF.CAUTIOUS, "BUY") == MF.LEVEL_CAUTIOUS)
check("Szép ↑: BUY mehet, SELL ellenirány",
      L(MF.BULL, "BUY") == MF.LEVEL_OK and L(MF.BULL, "SELL") == MF.LEVEL_AGAINST)
check("Szép ↓: SELL mehet, BUY ellenirány",
      L(MF.BEAR, "SELL") == MF.LEVEL_OK and L(MF.BEAR, "BUY") == MF.LEVEL_AGAINST)
check("Szép ↕ és Nincs → mindkét irány mehet",
      L(MF.NICE, "BUY") == L(MF.NICE, "SELL") == L(MF.NONE, "SELL") == MF.LEVEL_OK)

# ── a kapu a keretben ─────────────────────────────────────────────────────
check("beépített kapu, alap-hatás block", G.MANUAL in G.BUILTIN_KEYS
      and G.default_effect_of(G.MANUAL) == G.EFFECT_BLOCK)
KI = {"pairs": {"GOLD": {}}}
BE = {"manual_filter": {"enabled": True}, "pairs": {"GOLD": {}}}
check("kikapcsolva (config nélkül) a hatás none — mester-kapcsoló",
      G.effect_with_source(KI, "GOLD", "wpr_sma", G.MANUAL)
      == (G.EFFECT_NONE, G.SRC_MASTER_OFF))
check("bekapcsolva block", G.effect_for(BE, "GOLD", "wpr_sma", G.MANUAL) == G.EFFECT_BLOCK)
check("NEM a Kapuk-sorrend része (sem be-, sem kikapcsoltként)",
      G.MANUAL not in GL.enabled_gates(BE) and G.MANUAL not in GL.disabled_gates(BE))
_lad = GB.ladder(BE, "GOLD", "wpr_sma", G.MANUAL)
check("a kapu saját alap-létrája", _lad == {"no_trade": "block", "cautious": "reduce",
                                          "against": "block"}, _lad)


def hatas(state, signal, cfg=BE):
    from gates import manual as M
    ctx = NS(signal=signal, ds=NS(manual_state=state))
    failed, lvl = M.measure(ctx)
    base = G.effect_for(cfg, "GOLD", "wpr_sma", G.MANUAL)
    eff = GB.effect_at(G.MANUAL, GB.ladder(cfg, "GOLD", "wpr_sma", G.MANUAL), base, lvl, failed)
    return G.decide({G.MANUAL: eff != G.EFFECT_NONE}, {G.MANUAL: eff})


d = hatas(MF.NO_TRADE, "BUY")
check("Ne kereskedj → a motor GÁTOL", d["blocked"] == [G.MANUAL], d)
d = hatas(MF.CAUTIOUS, "SELL")
check("Óvatosan → a motor FELEZ", d["reduced"] == [G.MANUAL] and d["risk_factor"] == 0.5, d)
check("Szép ↑ + SELL → gátol", hatas(MF.BULL, "SELL")["blocked"] == [G.MANUAL])
check("Szép ↑ + BUY → szabad", hatas(MF.BULL, "BUY")["blocked"] == []
      and hatas(MF.BULL, "BUY")["reduced"] == [])
check("Szép ↓ + BUY → gátol", hatas(MF.BEAR, "BUY")["blocked"] == [G.MANUAL])
check("Szép ↕ → szabad", hatas(MF.NICE, "SELL")["blocked"] == [])
_off = {**BE, "pairs": {"GOLD": {"gates": {"manual": {"wpr_sma": "none"}}}}}
check("stratégiánként kikapcsolható (none) → nem szól bele",
      hatas(MF.NO_TRADE, "BUY", _off)["blocked"] == [])
check("kikapcsolt előszűrő → nem szól bele", hatas(MF.NO_TRADE, "BUY", KI)["blocked"] == [])
from gates import manual as _M                                   # noqa: E402
check("nincs állapot (pl. backtest) → fail-open",
      _M.measure(NS(signal="BUY", ds=None)) == (False, None))

# ── tábla: oszlop a Kapuk ELŐTT, cella lenyílóval ───────────────────────
from dashboard import canvas_columns as CCol, canvas_cells as CC, canvas_table as CT  # noqa
k = CCol.column_keys([], {"show_manual": True, "gate_columns": ["spread"]})
check("kikapcsolva nincs oszlop", "manual" not in CCol.column_keys([], {"gate_columns": []}))
check("bekapcsolva az oszlop a változás UTÁN, a kapuk ELŐTT",
      k.index("manual") == k.index("change") + 1 and k.index("manual") < k.index("spread"), k)
check("...összecsukott kapuknál is látszik",
      "manual" in CCol.column_keys([], {"show_manual": True, "gates": True}))
check("saját fejléc-csoport", any(c == ["manual"] for _l, c, _x in
                                   CT.groups([], {"show_manual": True, "gate_columns": []})))
from dashboard import row_source as RS                           # noqa: E402
_h = []
_cell = RS._manual_cell(NS(manual_state=MF.BULL), lambda s: _h.append(s), "GOLD")
c = CC.cells_for({"symbol": "GOLD", "digits": 2, "manual": _cell}, {"show_manual": True})
check("a cella a rövid feliratot mutatja", c["manual"].text == MF.SHORT[MF.BULL])
c["manual"].on_click()
check("kattintás → a lenyíló hívása a szimbólummal", _h == ["GOLD"])
check("kikapcsolva nincs cella", "manual" not in CC.cells_for(
    {"symbol": "GOLD", "digits": 2, "manual": _cell}, {}))
check("a kijelzés-ctx hordozza az állapotot",
      G.ctx_from_state(NS(manual_state=MF.NO_TRADE), {}, {}).get("manual_state") == MF.NO_TRADE)

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
