"""Csoportositott dashboard-sorok: felepules es a KAPU-CSIK helyessege.

Ez a teszt nem a szepseget meri (azt kepernyokep dontotte el), hanem azt, hogy a
sorok FELEPULNEK es a csik a VART allapotot mutatja — kulonben egy jovobeli
valtoztatas nemán elronthatna a jelzest.

Ha nincs megjelenites (fejnelkuli kornyezet), a tkinter-reszt KIHAGYJA: a
tesztkeszlet ne bukjon attol, hogy nincs kepernyo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import gates as G
from dashboard.grouped_layout import (GATE_SEGMENTS_MAX, INSTRUMENT_COLUMNS,
                                      STRATEGY_COLUMNS, ready_badge, should_expand)

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def ctx(spread=100, cap=200, gated=True, dirn="BUY", market="regime_adx"):
    return {"spread_points": spread, "max_spread_points": cap,
            "tf_align_gated": gated, "tf_align_signs": [1, 1, 1],
            "tf_align_labels": ["M1", "M5", "M15"], "tf_align_dir": dirn,
            "market_name": market, "market_label": "trendelo"}


# ══ 1. Oszlop-szetvalasztas ══════════════════════════════════════════════
ikeys = [c.key for c in INSTRUMENT_COLUMNS]
skeys = [c.key for c in STRATEGY_COLUMNS]
check("az instrumentum-oszlopok kozt NINCS strategia-fuggo",
      not ({"quality", "gates", "mode", "opt"} & set(ikeys)), str(ikeys))
check("a strategia-oszlopok kozt OTT a Minoseg (ez volt a panasz)",
      "quality" in skeys)
check("...es a kapuk is (a config mar per strategia)", "gates" in skeys)
check("a napi P&L MINDKET szinten szerepel (osszevont + bontott)",
      "daily" in ikeys and "daily" in skeys)
check("az ar ('elo bizonyitek') az INSTRUMENTUM sorban van",
      {"bid", "ask", "change"} <= set(ikeys))

# ══ 2. Keszultseg-jeloles ════════════════════════════════════════════════
check("2-bol 1 kesz -> ●○", ready_badge(1, 2) == "●○", ready_badge(1, 2))
check("mind kesz -> ●●", ready_badge(2, 2) == "●●")
check("egyik sem -> ○○", ready_badge(0, 2) == "○○")
check("nincs strategia -> gondolatjel", ready_badge(0, 0) == "—")


class DS:
    pos_count = 0


# ══ 3. Automatikus kinyitas ══════════════════════════════════════════════
clean = {"wpr_sma": G.evaluate(ctx()), "ml_ai": G.evaluate(ctx())}
blocked = {"wpr_sma": G.evaluate(ctx()), "ml_ai": G.evaluate(ctx(spread=999))}
check("minden tiszta, nincs pozicio -> CSUKVA marad",
      should_expand(DS(), clean, G.is_blocked) is False)
check("blokkolo kapu -> MAGATOL kinyilik",
      should_expand(DS(), blocked, G.is_blocked) is True)


class DSPos:
    pos_count = 1


check("nyitott pozicio -> MAGATOL kinyilik (akkor is, ha minden tiszta)",
      should_expand(DSPos(), clean, G.is_blocked) is True)

# ══ 4. A csik a VART allapotot mutatja ═══════════════════════════════════
# Ezek a kepernyokepen ellenorzott esetek, szamszerusitve — hogy egy kesobbi
# valtoztatas ne tudja nemán elrontani.
cases = [
    ("minden atenged",            ctx(),                  "▮▮▮", "✓"),
    ("SPREAD blokkol (1. szegmens)", ctx(spread=999),     "▨▮▮", "⛔1"),
    ("TF-EGYUTTALLAS blokkol (2.)",  ctx(dirn=None),      "▮▨▮", "⛔1"),
    ("piac KIKAPCSOLVA (3. halvany)", ctx(market=None),   "▮▮▯", "✓"),
    ("ketto blokkol",             ctx(spread=999, dirn=None), "▨▨▮", "⛔2"),
]
for name, c, want_strip, want_badge in cases:
    stt = G.evaluate(c)
    got_s, got_b = G.strip(stt), G.badge(stt)
    check(f"csik: {name}", got_s == want_strip and got_b == want_badge,
          f"{got_s} {got_b}")

# ══ 5. A widgetek FELEPULNEK (ha van megjelenites) ═══════════════════════
try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as e:
    print(f"SKIP  tkinter-resz: nincs megjelenites ({type(e).__name__})")
else:
    from dashboard import theme as _theme
    from dashboard.grouped_rows import InstrumentRow, StrategyRow
    from dashboard.grouped_layout import instrument_indent
    F = _theme.fonts()
    mono, small = F["mono"], F["small"]
    body = tk.Frame(_root)
    ok = True
    try:
        ir = InstrumentRow(body, "GOLD", 0, mono, small)
        ir.frame.pack()
        ir.update(DSPos(), "LIVE", True, (1, 2))
        sr = StrategyRow(body, "GOLD", "wpr_sma", 1, mono, small,
                         instrument_indent(mono))
        sr.frame.pack()
        sr.update(mode_label="KÖT", states=G.evaluate(ctx()), quality=("jó", "green"),
                  pos_text="1 poz.", daily=14.6, opt_status="", live=True)
        # Ujraszinezes MASIK allapottal: a szegmens-labelek ujrafelhasznalodnak
        sr.update(mode_label="jelez", states=G.evaluate(ctx(spread=999)),
                  quality=("rossz", "red"), pos_text="—", daily=-2.2,
                  opt_status="40%", live=False)
        _root.update_idletasks()
    except Exception as e:
        ok = False
        import traceback
        traceback.print_exc()
    check("a sorok felepulnek es ketszer is frissithetok", ok)
    # A szegmensek szama = a kapuk szama (nem duplazodik ujrarajzolaskor)
    check("ujrarajzolas NEM duplazza a szegmenseket",
          len(sr._gate_segs) == len(G.REGISTRY), str(len(sr._gate_segs)))
    _root.destroy()

# ══ 6. SKALAZODAS: sok kapu -> osszevont szamlalo ════════════════════════
# A merés megfogta, hogy a szegmenses csik 6 folott NEM fer ki (80px cella vs
# 10 kapu 165px), es NEMAN levagta a tobbletet: a 10 kapus sor NEGYNEK latszott.
def many(n, blk=0, off=0):
    out = []
    for i in range(n):
        stt = G.BLOCKING if i < blk else G.OFF if i < blk + off else G.PASS
        out.append({"key": f"g{i}", "label": f"kapu{i}",
                    "effect": G.EFFECT_BLOCK, "state": stt, "detail": ""})
    return out


c = G.counts(many(10, blk=2, off=3))
check("szamlalas: 2 blokkol / 3 ki / 5 atenged",
      (c[G.BLOCKING], c[G.OFF], c[G.PASS]) == (2, 3, 5), str(c))
comp = G.compact(many(10, blk=2, off=3))
check("osszevont alak: harom csoport", len(comp) == 3, str(comp))
check("...a blokkolo AZ ELSO (az a lenyeges)", comp[0][1] == G.BLOCKING, str(comp[0]))
check("ures kategoria kimarad (nincs '⛔0' zaj)",
      all("0" not in t for t, _ in G.compact(many(5))), str(G.compact(many(5))))
check("minden kikapcsolva -> egyetlen csoport", len(G.compact(many(4, off=4))) == 1)
check("ures allapot -> gondolatjel", G.compact([]) == [("—", G.OFF)])

# A hatarertek: 6-ig szegmens, 7-tol osszevont
check("a hatar 6 kapu", GATE_SEGMENTS_MAX == 6)

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
