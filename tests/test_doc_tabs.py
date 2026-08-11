"""A LEIRAS mint FUL — nem kulon ablak (user keres, 2026-08-07).

    Kapu-ablak         Beallitas · Leiras
    Strategia-ablak    Parameter · Leiras
    ⚙ Beallitasok      Json · Kapuk · Strategiak

Mindharom UGYANAZT a vazat hasznalja (`dashboard/tab_shell.py`), es a leiras a
szokasos `.md` fajlbol jon — a lemezrol, tehat szerkesztes utan azonnal friss.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. A leirasok LETEZNEK es a helyukon vannak ═══════════════════════════
for k in g.KEYS:
    p = g.doc_path(k)
    check(f"a(z) {k!r} kapunak van leirasa", p.exists(), str(p.name))
    check(f"...es erdemi ({k!r})", len(g.doc_text(k)) > 300,
          f"{len(g.doc_text(k))} karakter")

check("hianyzo leirasnal az ELVART utvonalat irja ki (nem ures lap)",
      "nincs leírás" in g.doc_text("nincs_ilyen")
      and "docs" in g.doc_text("nincs_ilyen"))

from strategy import get_strategy_by_name
for nm in ("wpr_sma", "ml_ai"):
    st = get_strategy_by_name(nm)
    check(f"a(z) {nm!r} strategianak van leirasa", st.doc_path().exists(),
          str(st.doc_path().name))

# ══ 2. A vaz — es hogy a lapok NEM semmisulnek meg valtaskor ══════════════
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK_OK = True
except Exception as e:
    TK_OK = False
    print(f"KIHAGYVA (Tk resz): {type(e).__name__}: {e}")

if TK_OK:
    from dashboard import theme as _th
    from dashboard.tab_shell import TabShell
    from dashboard import md_view

    root = tk.Tk(); root.withdraw()
    _th._FONTS.clear(); _th.fonts()
    try:
        seen = []
        sh = TabShell(root, ("A", "B", "C"), on_show=seen.append)
        check("az elso lap latszik indulaskor", sh.current == "A")
        check("...es az `on_show` lefutott ra", seen == ["A"], str(seen))
        sh.show("B"); sh.show("C"); sh.show("A"); sh.show("B")
        check("a lapvaltas oda-vissza megy", sh.current == "B")
        check("az `on_show` laponkent EGYSZER fut (lusta feltoltes)",
              seen == ["A", "B", "C"], str(seen))

        # ⚠ …DE van lap, aminek a tartalma KOZBEN elavul: futo optimalizalas
        # alatt frissulo eredmeny-CSV, a par allapota, vagy a masik lapon atirt
        # parameterek. Ott a "laponkent egyszer" azt jelentene, hogy a felulet
        # MAGABIZTOSAN elavult adatot mutat — a felhasznalo visszakattint
        # "megnezni, hogy all", es ugyanazt latja, mint tiz perce.
        seen2 = []
        sh2 = TabShell(root, ("A", "B"), on_show=seen2.append,
                       notify_every_show=True)
        sh2.show("B"); sh2.show("A"); sh2.show("B")
        check("notify_every_show -> MINDEN megjelenitesnel ertesit",
              seen2 == ["A", "B", "A", "B"], str(seen2))
        check("...es az alapertelmezes valtozatlan maradt (lusta)",
              seen == ["A", "B", "C"], str(seen))
        check("a lapok NEM semmisulnek meg (csak kicsomagolodnak)",
              all(sh.page(n).winfo_exists() for n in ("A", "B", "C")))

        # A beagyazott markdown-renderelo: EGY keretbe rajzol, nem uj ablakba
        _before = len(root.winfo_children())
        _holder = md_view.render(sh.page("C"), g.doc_text("cost"),
                                 source=str(g.doc_path("cost")))
        check("a leiras BEAGYAZVA jelenik meg (nem nyit uj Toplevelt)",
              len([w for w in root.winfo_children()
                   if isinstance(w, tk.Toplevel)]) == 0)
        _txt = [w for w in _holder.winfo_children()
                for c in ([w] + list(w.winfo_children()))
                if isinstance(c, tk.Text)]
        check("...es tenylegesen szoveget rajzolt",
              bool(_txt) or any(isinstance(c, tk.Text)
                                for w in _holder.winfo_children()
                                for c in w.winfo_children()))
    finally:
        root.destroy()

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
