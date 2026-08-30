"""Nyelvvalaszto a Megjelenes ablakban — a Fazis 5 szerzodese.

Amit orzunk:
  1. a legordulo a nyelvek SAJAT nevet mutatja (sosem forditva),
  2. a mentes a KODOT irja a configba (nem a feliratot),
  3. a valtas UJRAINDITAST ker — es ezt ki is mondja,
  4. a nyelv menet kozben NEM vált at (kevert felulet helyett egynyelvu).

⚠ EZ A TESZT NEM IR A VALODI CONFIGBA: a mentes-agat egy hamis `self`-fel
futtatjuk, aminek a `_save_main_config`-ja csak jelzi, hogy meghivtak.
"""
import inspect
import json
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from core import i18n
from dashboard import gui

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def texts(w, out=None):
    out = [] if out is None else out
    try:
        t = w.cget("text")
        if t:
            out.append(str(t))
    except Exception:
        pass
    for c in w.winfo_children():
        texts(c, out)
    return out


# ── 1. A NYELVEK NEVE NEM FORDITHATO ──────────────────────────────────────
# ⚠ Aki veletlenul egy szamara olvashatatlan nyelvre kapcsolt, a sajat nyelvet
# csak a SAJAT neven ismeri fel. Ezert a `LANGUAGES` a kodban el.
_hu_cat = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
check("a nyelvek neve NINCS a katalogusban",
      not [n for n in i18n.LANGUAGES.values()
           if n in _hu_cat.values()], str(list(i18n.LANGUAGES.values())))
check("minden nyelvnek EGYEDI a neve (a visszafejtes egyertelmu)",
      len(set(i18n.LANGUAGES.values())) == len(i18n.LANGUAGES))
check("van magyar es angol", {"hu", "en"} <= set(i18n.LANGUAGES))

# ── 2. A FORRAS szerzodese ────────────────────────────────────────────────
_src = inspect.getsource(gui.DashboardWindow._show_appearance)
# ⚠ Szokoz-turo: a mentes-blokk oszlopba igazitott (`dash["language"]    = ...`).
import re as _re
check("a mentes a KODOT irja a configba",
      bool(_re.search(r'dash\["language"\]\s*=\s*_lang_code\(\)', _src)))
check("a legordulo a sajat neveket kinalja",
      "_i18n.LANGUAGES.values()" in _src)
check("valtaskor UJRAINDITAST ker", "gui.restart.language" in _src
      and "gui.saved_restart" in _src)
# ⚠ A menet kozbeni valtas KEVERT feluletet adna: a mar megepult widgetek
# felirata nem valtozna, az ezutan nyiloke igen.
# ⚠ A HIVAST tiltjuk, nem a SZOT: a forrasban ott a magyarazat is, hogy miert
# nem hivjuk. Egy naiv szo-kereses a sajat kommentunkon bukna el.
check("menet kozben NEM allitja at a nyelvet",
      not _re.search(r"^\s*[\w.]*set_language\(", _src, _re.M),
      "a felulet fele magyar, fele angol lenne")

# ── 3. AZ ABLAK mindket nyelven ───────────────────────────────────────────
cfg = {"dashboard": {}}
saved = {"n": 0}


class _Fake:
    root = None
    cfg = cfg
    _small_font = ("Segoe UI", 9)
    _header_font = ("Segoe UI", 10, "bold")

    def _save_main_config(self):
        saved["n"] += 1
        return True


_root = tk.Tk()
_root.withdraw()
_Fake.root = _root
_orig = i18n.language()

for _lang in ("hu", "en"):
    i18n.set_language(_lang)
    gui.DashboardWindow._show_appearance(_Fake())
    _top = [w for w in _root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    _txt = texts(_top)
    check(f"[{_lang}] a nyelv sajat neven latszik",
          i18n.LANGUAGES[_lang] in _txt, str(_txt[:4]))
    check(f"[{_lang}] a lefordítatlanrol SZOL a megjegyzes",
          any("magyarul" in t or "Hungarian" in t for t in _txt))
    _top.destroy()

# ── 3b. A MENTES tenyleg KODOT ir ────────────────────────────────────────
# ⚠ Ez a teszt lelke. A legordulo a nyelv SAJAT nevet mutatja („Magyar"), a
# configba viszont a KODNAK („hu") kell kerulnie — kulonben egy masik nyelvu
# gepen a mentett ertek ismeretlen lenne, es a program csendben alapnyelvre
# esne vissza. A gombot TENYLEG megnyomjuk, nem a forrast olvassuk.
def _buttons(w, out=None):
    out = [] if out is None else out
    if isinstance(w, tk.Button):
        out.append(w)
    for c in w.winfo_children():
        _buttons(c, out)
    return out


i18n.set_language("hu")
gui.DashboardWindow._show_appearance(_Fake())
_top = [w for w in _root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
_save_btn = next((b for b in _buttons(_top)
                  if b.cget("text") == i18n.t("btn.save")), None)
check("van Mentes gomb", _save_btn is not None)
if _save_btn is not None:
    _save_btn.invoke()
    check("a mentes lefutott", saved["n"] == 1, str(saved))
    check("a configba a KOD kerult, nem a felirat",
          cfg["dashboard"].get("language") in i18n.LANGUAGES,
          repr(cfg["dashboard"].get("language")))
    check("...es a tema is kodkent",
          cfg["dashboard"].get("theme") not in i18n.LANGUAGES.values(),
          repr(cfg["dashboard"].get("theme")))
_top.destroy()

i18n.set_language(_orig)
_root.destroy()

# ── 4. A KATALOGUS kulcsai ────────────────────────────────────────────────
for _k in ("lang.label", "gui.saved", "gui.saved_restart",
           "gui.restart.language", "gui.restart.theme", "gui.language_note"):
    check(f"van kulcs: {_k}", i18n.has(_k))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
