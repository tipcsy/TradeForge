"""A nem ENGEDELYEZETT strategia MONDJA MEG, miert nem indithato.

⚠ A LELET (2026-08-14). A felhasznalo ketszer jelezte, hogy a bollingert nem
tudja elinditani UsaInd-en. A ket kapu KULONBOZO:

  1. nincs mentett parameterkeszlet   -> JAVITVA v2.47.0 (a strategia sajat
                                         alapertekeivel indul)
  2. a strategia nincs BEKAPCSOLVA a paron (`pairs.<sym>.strategies`)
                                      -> ez maradt, es ez a helyes viselkedes:
                                         a motor sosem futtatna, tehat a `▶`
                                         hazugsag volna

A BAJ NEM A KAPU VOLT, HANEM A NEMASAGA. A sor jelzest ES minosite:st is mutatott
(UsaInd/bollinger: „Jó", 157 kotes, +674$), tehat KESZNEK latszott — a Vezerles
cellaban viszont csak egy halvany `–` allt, ami a szemnek „nincs itt semmi", nem
„ez ki van kapcsolva". Az OK csak KATTINTASRA jelent meg az allapotsorban; aki
nem kattintott ra, elakadt.

⚠ ES A KATTINTAS MEGMARAD. A halvany vezerlo tovabbra is fog: a buborek nem
helyettesiti az allapotsor uzenetet, csak elorehozza.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from dashboard import canvas_cells as cc, live_row as lr

BB = "bollinger_squeeze_breakout"


def _row(enabled):
    return {"symbol": "UsaInd", "bid": 1.0, "ask": 2.0, "digits": 2,
            "strategies": [{"name": BB, "enabled": enabled, "live": False,
                            "mode": "live", "stages": ["muted", "muted"],
                            "quality": "Jó", "on_toggle": lambda: None}]}


# ── 1. A VEZERLO ALLAPOTA ────────────────────────────────────────────────
_off = cc.cells_for(_row(False), collapsed={})[f"{BB}|ctrl"]
_on = cc.cells_for(_row(True), collapsed={})[f"{BB}|ctrl"]
check("engedelyezve: Play, AKTIV", _on.parts[0][1] == "▶" and _on.parts[0][4])
check("nem engedelyezve: HALVANY, tetlen",
      _off.parts[0][1] == "–" and not _off.parts[0][4], str(_off.parts[0][:2]))

# ⚠ A KOTES AKKOR IS MEGVAN: a halvany vezerlo kattinthato, es a hivo kiirja az
# okot az allapotsorba. Egy nema, nem reagalo gomb rosszabb a halvanynal.
check("a halvany vezerlo IS kattinthato", _off.parts[0][3] is not None)


# ── 2. A BUBOREK: az ok KATTINTAS NELKUL ─────────────────────────────────
check("a letiltott vezerlonek VAN buborekja", bool(_off.tip), _off.tip)
check("...ami megmondja, hogy nincs BEKAPCSOLVA",
      "nincs bekapcsolva" in _off.tip and "motor" in _off.tip, _off.tip)
# ⚠ A buborek nem elég ahhoz, hogy KIMONDJA a bajt — meg kell mondania a
# TEENDOT is. Enelkul ugyanott vagyunk: tudom, hogy nem megy, de nem tudom, hol
# kapcsolom be.
check("...ES megmondja, HOL kapcsolod be",
      "kattints" in _off.tip.lower() and "instrumentum" in _off.tip.lower(),
      _off.tip)
check("a strategia NEVE benne van", BB in _off.tip)

# ⚠ AMI MUKODIK, ARRA NINCS BUBOREK. Egy mindenhol felugro sugo ugyanolyan zaj,
# mint egy mindig latszo „nincs hiba" felirat: elveszi a helyet, es megtanitja a
# szemet, hogy ne nezzen oda.
check("a MUKODO vezerlon NINCS buborek", not _on.tip, _on.tip)


# ── 3. A VASZON-TABLA megjeleniti ────────────────────────────────────────
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception:
    TK = False

if TK:
    from dashboard import theme as th, canvas_table as ct
    root = tk.Tk(); root.withdraw()
    th._FONTS.clear()
    fonts = th.fonts()

    t = ct.CanvasTable(root, fonts, rows=[_row(False)])
    t.frame.pack()
    root.update_idletasks()

    _ks = [k for k in t.clickable() if len(k) == 3 and k[1] == f"{BB}|ctrl"]
    check("a tablan a halvany vezerlo kattinthato marad", bool(_ks), str(_ks))
    # ⚠ ES MEGSINCS KEZ-KURZORA: a buborek elmondja, miert tetlen, de a kurzor
    # nem igerheti, hogy kattintasra TENNI fog valamit. A ket dolog ugyanazt az
    # `<Enter>` esemenyt hallgatja — ezert kell a kulon nyilvantartas.
    check("...de NINCS kez-kurzora", f"c0_{BB}|ctrl_run" not in t._hand_tags,
          str(sorted(t._hand_tags))[:80])

    class _Ev:
        x_root = y_root = 100

    t._tip_show(_Ev(), "proba szoveg")
    root.update_idletasks()
    check("a buborek-ablak MEGJELENIK", bool(t._tipwin.winfo_ismapped()))
    check("...a kapott szoveggel", t._tiplbl.cget("text") == "proba szoveg")
    # ⚠ EGYETLEN ablakot hasznalunk ujra: a tabla tobb szaz cellat rajzol, es
    # annyi Toplevel letrehozasa merhetoen akadna.
    _w1 = t._tipwin
    t._tip_hide(); root.update_idletasks()
    check("...es elrejtheto", not t._tipwin.winfo_ismapped())
    t._tip_show(_Ev(), "masodik")
    check("ujra mutatva UGYANAZ az ablak (nem szemetel)", t._tipwin is _w1)
    t._tip_hide()

    root.destroy()
else:
    check("nincs tkinter (a tabla-tesztek kihagyva)", True)


# ── 4. A KAPU MAGA valtozatlan ───────────────────────────────────────────
# A javitas NEM az, hogy bekapcsoljuk a strategiat mindenhol: az nemán mas
# kereskedest jelentene. A kapu marad, csak mostantol beszel.
import inspect
from dashboard import gui as _gui
_src = inspect.getsource(_gui.DashboardWindow._start_strategy)
if _src:
    check("a Play tovabbra is megtagadja a nem engedelyezettet",
          "if not self._strategy_enabled(symbol, name):" in _src)
    check("...es megmondja, hol lehet bekapcsolni",
          "beállításainál" in _src, "")
else:
    check("ures forras (kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
