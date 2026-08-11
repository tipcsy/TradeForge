"""A vezerlo-gomb AZT a sort vezerelje, amelyikre kattintottak.

Bejelentes (2026-08-11, elesben): "amikor a Stop-ra kattintok, nem azt zarja le,
ahova kattintottam, hanem a HAROMMAL FELETTIT".

Gyoker: a vaszon-tabla a sorokat REKESZKENT cimzi — `(sor_index, oszlop)`. A
novekmenyes frissites (`refresh`) rendezeskor ugyanabba a rekeszbe MAS
instrumentum adatat irja: az `_apply` a szoveget/szint atirja, a `_clicks`
szotarban viszont a REGI sorra zart lambda maradt.

⚠ Sulyosbito reszlet: a `Cell.visual()` SZANDEKOSAN nem tartalmazza a
visszahivast (csak alkulcs/szoveg/szin). Ha ket par vezerloje ugyanugy nez ki, a
frissites `continue`-val kihagyja a cellat — az elavult kotes igy AKKOR IS
tulelne, ha egyebkent a visual-valtozasra kotnenk ujra. Ezert kell a kotest
FELTETEL NELKUL frissiteni.

Ez a hiba NEMA es VESZELYES: a felhasznalo a helyes sorra kattint, a program a
megerositest is kiirja, es kozben MASIK par kereskedese all le.
"""
import copy
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
    from dashboard import canvas_table as ct
    from dashboard import live_row as lr
    from dashboard import theme as _theme

    root = tk.Tk(); root.withdraw()
    _theme._FONTS.clear()
    fonts = _theme.fonts()

    fired = []

    def rows_for(symbols):
        """Sorok a megadott SORRENDBEN. A vezerlo-visszahivas a SOR ADATABAN el
        (`st["on_toggle"]` / `st["on_opt"]`), ezert oda kotjuk a szimbolumot —
        pontosan ugy, ahogy a dashboard is teszi."""
        base = lr.demo_row()
        proto = base["strategies"][0]
        out = []
        for sym in symbols:
            r = copy.deepcopy(base)
            r["symbol"] = sym
            st = copy.deepcopy(proto)
            st["name"] = "wpr_sma"
            st["enabled"] = True
            st["opt_enabled"] = True
            st["on_toggle"] = (lambda s=sym: fired.append(("run", s)))
            st["on_opt"] = (lambda s=sym: fired.append(("opt", s)))
            r["strategies"] = [st]
            out.append(r)
        return out

    SYMS = ["AAA", "BBB", "CCC", "DDD", "EEE"]

    tbl = ct.CanvasTable(root, fonts, rows=rows_for(SYMS), collapsed={})
    root.update_idletasks()

    ctrl_keys = sorted({k[1] for k in tbl.clickable() if len(k) == 3})
    check("van vezerlo-cella a tablan", bool(ctrl_keys), str(ctrl_keys))
    CKEY = ctrl_keys[0] if ctrl_keys else None
    subs = sorted({k[2] for k in tbl.clickable() if len(k) == 3 and k[1] == CKEY})
    check("a vezerlonek van alkulcsa (run/stop)", bool(subs), str(subs))

    def visible_symbols():
        return [d["symbol"] for d in tbl._visible()]

    # ── 1. ALAPHELYZET: a kattintas a SAJAT sorat vezerelje ───────────────────
    vis = visible_symbols()
    ok_base = True
    for i, sym in enumerate(vis):
        for sub in subs:
            fired.clear()
            tbl.fire(i, CKEY, sub)
            if fired and fired[0][1] != sym:
                ok_base = False
    check("alaphelyzet: minden sor a SAJAT parjat vezerli", ok_base, str(vis))

    # ── 2. A HIBA MAGVA: ATRENDEZES utan is a lathato sor vezereljen ─────────
    # Ugyanaz az 5 par, MEGFORDITOTT sorrendben — pontosan az a helyzet, amit a
    # rendezes (vagy egy uj/eltuno par) elidez.
    tbl.refresh(rows_for(list(reversed(SYMS))))
    root.update_idletasks()
    vis2 = visible_symbols()
    check("atrendezes utan mas a sorrend (a teszt ertelmes)", vis2 != vis, str(vis2))

    bad = []
    for i, sym in enumerate(vis2):
        for sub in subs:
            fired.clear()
            tbl.fire(i, CKEY, sub)
            if not fired:
                bad.append(f"{i}:{sub}=nem sult el")
            elif fired[0][1] != sym:
                bad.append(f"sor{i} ({sym}) -> {fired[0][1]} !")
    check("ATRENDEZES utan: a gomb a LATHATO parjat vezerli", not bad,
          "; ".join(bad[:4]))

    # ── 3. Egy par ELTUNIK (szures) — a maradek se csuszhat el ───────────────
    tbl.refresh(rows_for(["CCC", "AAA", "EEE"]))
    root.update_idletasks()
    vis3 = visible_symbols()
    bad3 = []
    for i, sym in enumerate(vis3):
        for sub in subs:
            fired.clear()
            tbl.fire(i, CKEY, sub)
            if not fired or fired[0][1] != sym:
                bad3.append(f"sor{i} ({sym}) -> {fired[0][1] if fired else 'semmi'}")
    check("szures utan: a gomb tovabbra is a LATHATO parjat vezerli", not bad3,
          "; ".join(bad3[:4]))

    # ── 4. Az ATLATSZO cella-kattintasok (on_click) is kovessek a sort ───────
    plain = sorted({k[1] for k in tbl.clickable() if len(k) == 2})
    if plain:
        tbl.refresh(rows_for(["EEE", "CCC", "AAA"]))
        root.update_idletasks()
        v4 = visible_symbols()
        # a cella-kattintas nem ad vissza szimbolumot, de a KOTES letezese szamit
        ok4 = all(tbl.fire(i, plain[0]) for i in range(len(v4)))
        check("cella-kattintas: minden lathato sorban el van kotve", ok4, str(v4))
    else:
        check("cella-kattintas: nincs ilyen a tablan (kihagyva)", True)

    root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
