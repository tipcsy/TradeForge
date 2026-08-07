"""Az oszlop-terkep (dashboard/canvas_columns.py) — a vaszon-tabla alapja.

Amit oriz: a vaszon-tabla oszlopai PIXELRE azonosak a mai widget-tablaeval, es a
sorrend is ugyanaz. A renderelo csereje nem valtoztathat a latvanyon.

Miert ez a legfontosabb allitas: a widget-tablaban az oszlop-igazitas ALKU (a
fejlec es minden sor kulon pack-lancot epit, es ezeknek veletlenul egyezniuk
kell). Vasznon aritmetika: mindenki UGYANABBOL a listabol rajzol.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(e).__name__}: {e})")

if TK_OK:
    from dashboard import canvas_columns as cc
    from dashboard import live_row as lr
    from dashboard import theme as _theme

    root = tk.Tk(); root.withdraw()
    _theme._FONTS.clear()
    fonts = _theme.fonts()
    STRATS = ["wpr_sma", "ml_ai"]

    # ── Sorrend: PONTOSAN a build_header sorrendje ────────────────────────
    keys = cc.column_keys(STRATS, {})
    check("a fix oszlopok elol allnak, a megszokott sorrendben",
          keys[:4] == ["symbol", "bid", "ask", "change"], str(keys[:4]))
    check("a kapu-blokk: Spread · Egyutt · Piac · Lendulet · Koltseg, majd K.Ossz.",
          keys[4:10] == ["spread", "align", "market", "momentum", "cost", "badge"],
          str(keys[4:10]))
    check("a strategia-oszlopok kulcsa '<nev>|<mezo>' (a rendezes blokkra hat)",
          keys[10:16] == ["wpr_sma|stages", "wpr_sma|position", "wpr_sma|daily",
                          "wpr_sma|quality", "wpr_sma|ctrl", "wpr_sma|opt"],
          str(keys[10:16]))
    check("a vegen az osszesito + a torles",
          keys[-3:] == ["total_pos", "total_daily", "close"], str(keys[-3:]))

    # ── Osszecsukas: ugyanaz a szabaly, mint a widget-tablaban ────────────
    kg = cc.column_keys(STRATS, {"gates": True})
    check("osszecsukott kapuknal CSAK a K.Ossz. marad a blokkbol",
          "spread" not in kg and "align" not in kg and "badge" in kg, str(kg[:6]))
    ks = cc.column_keys(STRATS, {"strategies": {"ml_ai"}})
    check("osszecsukott strategianal a jelzes MELLETT a Vezerles is marad",
          "ml_ai|stages" in ks and "ml_ai|ctrl" in ks
          and "ml_ai|position" not in ks, str([k for k in ks if k.startswith("ml_ai")]))
    check("...a masik strategia blokkja teljes marad",
          len([k for k in ks if k.startswith("wpr_sma|")]) == 6)
    # A kapu-oszlopok KÖRE és SORRENDJE a configból jon (`dashboard.gate_order`).
    # Az AUTOMATIKUS elrejtes (v2.9.0 elott: ha egy paron sincs mert ertek, az
    # oszlop eltunik) MEGSZUNT — ket oka is lehetett annak, hogy valami nem
    # latszik, es nehez volt kitalalni, melyik.
    from core import gate_layout as gl
    kh = cc.column_keys(STRATS, {"gate_columns": ["spread", "align"]})
    check("a kikapcsolt kapu oszlopa KIMARAD",
          "market" not in kh and "momentum" not in kh and "cost" not in kh
          and "spread" in kh and "align" in kh, str(kh[:8]))
    ko = cc.column_keys(STRATS, {"gate_columns": ["cost", "align", "spread"]})
    check("...es a SORREND a listat koveti",
          ko[4:7] == ["cost", "align", "spread"], str(ko[4:7]))
    check("a K.Ossz. a kapu-oszlopok UTAN marad", ko[7] == "badge", str(ko[7]))
    check("ures lista -> csak a K.Ossz.",
          cc.column_keys(STRATS, {"gate_columns": []})[4] == "badge")
    check("hianyzo config -> MINDEN kapu, a REGISTRY sorrendjeben",
          gl.enabled_columns(None) == ["spread", "align", "market", "momentum", "cost"],
          str(gl.enabled_columns(None)))

    # ── A SZELESSEGEK a meglevo live_row.widths()-bol jonnek ──────────────
    for coll in ({}, {"gates": True}, {"strategies": True},
                 {"pnl_mode": "both"}, {"hide_market": True}):
        w = lr.widths(fonts, STRATS, coll)
        cols = cc.layout(fonts, STRATS, coll)
        bad = [(k, wd) for k, _x, wd in cols if wd != w[cc.base_key(k)]]
        check(f"a szelessegek pixelre egyeznek a widget-tablaeval  ({coll or 'alap'})",
              not bad, str(bad[:3]))

    # ── Az x-eltolasok HEZAGTARTOAK es novekvok ───────────────────────────
    cols = cc.layout(fonts, STRATS, {})
    xs = [x for _k, x, _w in cols]
    check("az x-eltolasok szigoruan novekvok", xs == sorted(set(xs)) and len(xs) == len(set(xs)))
    gaps = [cols[i + 1][1] - (cols[i][1] + cols[i][2]) for i in range(len(cols) - 1)]
    check("minden oszlop kozott PONTOSAN egy hezag van",
          set(gaps) == {cc.GAP}, str(sorted(set(gaps))))
    check("a teljes szelesseg az utolso oszlop vege",
          cc.total_width(cols) == cols[-1][1] + cols[-1][2])

    # ── A KERESES visszaadja a helyet (a kattintas-kezeles ezt hasznalja) ─
    check("x_of megtalalja a letezo oszlopot",
          cc.x_of(cols, "spread") == (cols[4][1], cols[4][2]))
    check("...es None-t ad a nem latszora",
          cc.x_of(cc.layout(fonts, STRATS, {"gates": True}), "spread") is None)

    # ── A stratégia-szam SKALAZODASA (ezert keszult az egesz) ─────────────
    many = [f"strat{i}" for i in range(10)]
    c10 = cc.layout(fonts, many, {})
    check("10 strategiaval is felepul az oszlop-terkep",
          len([k for k, _x, _w in c10 if k.startswith("strat0|")]) == 6,
          f"oszlop={len(c10)}, szelesseg={cc.total_width(c10)}px")

    # ── A `Piac` oszlop a VALODI kategoria-cimkekhez igazodik ────────────
    # Eles proban az „Id.Medve" vege levagodott: a mintaszoveg egy bedrotozott
    # „Sz.Bika" volt (7 betu), a leghosszabb cimke viszont az „Erdektelen" (10).
    from core import market_strategy as _ms
    w = lr.widths(fonts, STRATS, {})
    longest = max(_ms.display_labels(), key=fonts["small"].measure)
    check("a Piac oszlopba MINDEN kategoria-cimke kifer",
          w["market"] >= fonts["small"].measure(longest) + 2 * lr.PAD,
          f"oszlop={w['market']}px, leghosszabb={longest!r}="
          f"{fonts['small'].measure(longest)}px")
    for lbl in _ms.display_labels():
        if fonts["small"].measure(lbl) + 2 * lr.PAD > w["market"]:
            check(f"...{lbl!r} kifer", False)
            break
    else:
        check("...egyenkent is ellenorizve mind", True,
              f"{len(_ms.display_labels())} cimke")

    root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
