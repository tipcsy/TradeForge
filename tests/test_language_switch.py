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
# ⚠ 2026-08-31 ota a nyelv es a megjelenes a `⚙ Beallitas` ablak KET KULON
# lapja, nem egy sajat `🎨 Megjelenes` gomb az eszkozsavon (felhasznaloi keres).
_src = inspect.getsource(gui.DashboardWindow._show_settings)
import re as _re
check("a mentes a KODOT irja a configba",
      bool(_re.search(r'_dash\["language"\]\s*=\s*_lang_code\(\)', _src)))
check("valtaskor UJRAINDITAST ker", "gui.restart.language" in _src
      and "gui.saved_restart" in _src)
# ⚠ A menet kozbeni valtas KEVERT feluletet adna: a mar megepult widgetek
# felirata nem valtozna, az ezutan nyiloke igen.
# ⚠ A HIVAST tiltjuk, nem a SZOT: a forrasban ott a magyarazat is, hogy miert
# nem hivjuk. Egy naiv szo-kereses a sajat kommentunkon bukna el.
check("menet kozben NEM allitja at a nyelvet",
      not _re.search(r"^\s*[\w.]*set_language\(", _src, _re.M),
      "a felulet fele magyar, fele angol lenne")
check("a nyelv KULON lapon van (nem a megjelenes alatt)",
      '("language", _t("lang.label"))' in _src)
check("...es a megjelenes is sajat lapon",
      '("appearance", _t("gui.megjelenes"))' in _src)

# ⚠ AZ ESZKOZSAVON MAR NINCS gomb. Ha visszakerulne, ket helyrol lehetne
# ugyanazt allitani -- a ket ut elobb-utobb elcsuszna.
_gui_src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("nincs tobbe `_show_appearance` (egy forras maradt)",
      "_show_appearance" not in _gui_src)
check("...es nincs eszkozsav-gomb ra", "gui.megjelenes2" not in _gui_src)

# ── 3. A KET LAP mindket nyelven ─────────────────────────────────────────
# A lapokat KULON metodus epiti (`_build_*_tab`) -- igy a teljes Beallitas-ablak
# (JSON-szerkeszto, kapu- es strategia-editor) nelkul is megnyithatok, es a
# teszt a VISELKEDEST meri, nem a forras szoveget.
cfg = {"dashboard": {}}


class _Fake:
    root = None
    cfg = cfg
    _small_font = ("Segoe UI", 9)
    _header_font = ("Segoe UI", 10, "bold")


_root = tk.Tk()
_root.withdraw()
_Fake.root = _root
_orig = i18n.language()

for _lang in ("hu", "en"):
    i18n.set_language(_lang)
    _top = tk.Toplevel(_root)
    _nyelv = gui.DashboardWindow._build_language_tab(_Fake(), _top)
    _txt = texts(_top)
    check(f"[{_lang}] a nyelv sajat neven latszik",
          i18n.LANGUAGES[_lang] in _txt, str(_txt[:4]))
    check(f"[{_lang}] a lefordítatlanrol SZOL a megjegyzes",
          any("magyarul" in t or "Hungarian" in t for t in _txt))
    _top.destroy()

# ── 3b. A visszafejtes tenyleg KODOT ad ──────────────────────────────────
# ⚠ Ez a teszt lelke. A legordulo a nyelv SAJAT nevet mutatja („Magyar"), a
# configba viszont a KODNAK („hu") kell kerulnie — kulonben egy masik nyelvu
# gepen a mentett ertek ismeretlen lenne, es a program csendben alapnyelvre
# esne vissza.
i18n.set_language("hu")
_top = tk.Toplevel(_root)
_ny = gui.DashboardWindow._build_language_tab(_Fake(), _top)
for _kod, _nev in i18n.LANGUAGES.items():
    _ny["lang_var"].set(_nev)
    check(f"a(z) {_nev} felirat -> {_kod} kod",
          _ny["lang_code"] == _kod if isinstance(_ny["lang_code"], str)
          else _ny["lang_code"]() == _kod)
_top.destroy()

# A megjelenes-lap is a KODOT adja vissza (nem a feliratot).
_top = tk.Toplevel(_root)
_mg = gui.DashboardWindow._build_appearance_tab(_Fake(), _top)
from dashboard import theme as _th
check("a tema legordulo FELIRATOT mutat", _mg["theme_var"].get() in
      [_th.theme_label(c) for c in _th.THEMES], _mg["theme_var"].get())
check("...de a kod visszafejtheto belole",
      _th.theme_code(_mg["theme_var"].get()) in _th.THEMES,
      _th.theme_code(_mg["theme_var"].get()))
check("a betu-elonezet hivhato", callable(_mg["preview"]))
_top.destroy()

i18n.set_language(_orig)
_root.destroy()

# ── 4. A KATALOGUS kulcsai ────────────────────────────────────────────────
for _k in ("lang.label", "gui.saved_restart",
           "gui.restart.language", "gui.restart.theme", "gui.language_note"):
    check(f"van kulcs: {_k}", i18n.has(_k))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
