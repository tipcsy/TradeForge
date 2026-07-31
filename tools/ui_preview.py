"""
Képernyőkép-alapú UI-ellenőrzés — fejlesztői eszköz a dashboard-munkához.

MIÉRT VAN. A dashboard 1. körében ez a módszer **négy valódi hibát** fogott meg,
mielőtt a felhasználóhoz ért volna (lásd Obsidian: „Dashboard fejlesztés"). Akkor
viszont session-lokális szkriptként élt, és elveszett — ugyanaz a hiba, amit a
tesztek repóba költöztetése (v1.71.1) már egyszer orvosolt. Ezért most itt van.

MIT AD:

  • `capture(build, path)` — felépít egy ablakot, megvárja a tényleges elrendezést,
    és PNG-t ment róla. **Igazolja, hogy a SAJÁT ablakunkat kaptuk el** (lásd lent).
  • `inspect(build)` — képernyőkép NÉLKÜL adja vissza a widget-fa mért geometriáját,
    így a levágás/magasság-eltérés automatikusan is ellenőrizhető (a tesztekben ez
    fut, mert nem igényel képernyőt).
  • `truncated()` / `height_groups()` — a két konkrét hibafajta, ami az 1. körben
    ténylegesen előfordult.

A CSAPDA, AMIT KÜLÖN KEZELÜNK. Egyszer a böngésző ablaka került a képre a sajátunk
helyett — és egy HIBÁS elrendezést jónak hihettem volna. A `-topmost` önmagában nem
elég bizonyíték, ezért a `capture` egy SZENTINEL pixelt rajzol a bal felső sarokba,
és a mentett képen ellenőrzi. Ha nem egyezik, kivételt dob: inkább ne legyen kép,
mint hamis kép.

Futtatás önmagában (bemutató + önteszt):

    python tools/ui_preview.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# A Windows-konzol cp1250: a nyíl/blokk-glifák különben UnicodeEncodeError-t
# dobnának, és a HIBA HELYETT kódolási hibát látnánk (ugyanaz a fogás, mint a
# tests/run_all.py-ban).
try:
    from core import applog
    applog.harden_console()
except Exception:
    pass

# A szentinel: egy 6x6 pixeles folt a bal felső sarokban, szokatlan színnel.
# Ha a grab MÁS ablakot kap el, ez a szín ott nem lesz — így a hamis kép kiderül.
SENTINEL = "#ff00d4"
SENTINEL_RGB = (255, 0, 212)
SENTINEL_PX = 6


class CaptureError(RuntimeError):
    """A képernyőkép nem a saját ablakunkról készült (vagy nem készíthető)."""


def _make_dpi_aware():
    """DPI-tudatosság bekapcsolása (Windows) — a képernyőkép ELŐFELTÉTELE.

    A tkinter `winfo_rootx/rooty/width/height` LOGIKAI pixelt ad, az `ImageGrab`
    viszont FIZIKAI képernyő-koordinátákkal dolgozik. 150%-os skálázásnál a kettő
    1,5× eltér, tehát a grab MÁS területet vágna ki — és pont olyan képet kapnánk,
    ami hihetőnek látszik, de nem a mi ablakunk. (A szentinel ezt elkapja, de jobb,
    ha elő sem áll.) Idempotens; nem-Windowson némán kihagyva."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v2
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()        # régebbi Windows
    except Exception:
        pass


def _build_root(build, size, bg="#1e1e2e"):
    """Ablak + a hívó tartalma. Visszaad: (root, content_frame)."""
    _make_dpi_aware()
    root = tk.Tk()
    root.configure(bg=bg)
    root.geometry(f"{size[0]}x{size[1]}+40+40")
    root.overrideredirect(True)          # nincs címsor → a kép csak a tartalom
    root.attributes("-topmost", True)    # KÖTELEZŐ: különben mást kapunk el
    # A szentinel a bal felső sarokban, a tartalom FÖLÖTT (place-szel, hogy ne
    # tolja el az elrendezést).
    content = tk.Frame(root, bg=bg)
    content.pack(fill="both", expand=True)
    build(content)
    mark = tk.Frame(root, bg=SENTINEL, width=SENTINEL_PX, height=SENTINEL_PX)
    mark.place(x=0, y=0)
    return root, content


def _settle(root, settle_ms: int):
    """A tényleges elrendezés kikényszerítése. Enélkül a `winfo_width()` még 1,
    és minden mérés hazudna."""
    root.update_idletasks()
    root.update()
    root.after(settle_ms, root.quit)
    root.mainloop()
    root.update_idletasks()


def capture(build, path, size=(1400, 220), settle_ms=140, bg="#1e1e2e") -> Path:
    """A `build(parent)` által felépített felület PNG-be mentve.

    `build` egy függvény, ami egy tkinter-keretet kap és feltölti. Nem kell hozzá
    futó dashboard vagy MT5 — kitalált adattal is renderelhető egy sor-widget.

    Kivételt dob (`CaptureError`), ha a mentett képen nincs meg a szentinel: ilyenkor
    NEM a mi ablakunk került a képre, és a kép megtévesztő lenne."""
    try:
        from PIL import ImageGrab
    except ImportError as e:                       # pragma: no cover
        raise CaptureError(f"Pillow kell a képernyőképhez: {e}") from e

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    root, _ = _build_root(build, size, bg)
    try:
        _settle(root, settle_ms)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        px = img.convert("RGB").getpixel((SENTINEL_PX // 2, SENTINEL_PX // 2))
        if px != SENTINEL_RGB:
            raise CaptureError(
                f"A képernyőkép NEM a saját ablakunkról készült (a szentinel "
                f"{SENTINEL_RGB} helyett {px} lett). Takarhatja egy másik ablak, "
                f"vagy a képernyő zárolva van — a kép megtévesztő lenne.")
        img.save(path)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return path


# ---------------------------------------------------------------------------
# Képernyőkép NÉLKÜLI vizsgálat — ez fut a tesztekben
# ---------------------------------------------------------------------------

def _walk(w, depth=0):
    yield w, depth
    for c in w.winfo_children():
        yield from _walk(c, depth + 1)


def inspect(build, size=(1400, 220), settle_ms=60) -> list:
    """A widget-fa MÉRT geometriája, kép készítése nélkül.

    Visszaad: `[{cls, text, x, y, w, h, req_w, req_h, depth}, …]`. A `req_*` a
    widget által KÉRT méret; ha ez nagyobb a kapottnál, a tartalom levágódik —
    némán, ami a legrosszabb fajta hiba (az 1. körben egy 10 kapus sor négynek
    látszott, mert a cella szó nélkül levágta a szegmenseket)."""
    root, content = _build_root(build, size)
    out = []
    try:
        _settle(root, settle_ms)
        for w, depth in _walk(content):
            try:
                out.append({
                    "cls": w.winfo_class(),
                    "text": (w.cget("text") if "text" in w.keys() else ""),
                    "x": w.winfo_x(), "y": w.winfo_y(),
                    "w": w.winfo_width(), "h": w.winfo_height(),
                    "req_w": w.winfo_reqwidth(), "req_h": w.winfo_reqheight(),
                    "depth": depth,
                })
            except Exception:
                continue
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return out


def truncated(nodes, tol: int = 0) -> list:
    """Azok a widgetek, amelyek NEM férnek ki (a kért méret > a kapott).

    Csak a MEGJELENÍTETT (w>1, h>1) elemeket nézi: a még nem elrendezett widget
    mérete 1, abból nem következik levágás.

    `tol`: hány pixel eltérés még elfogadható (a betű-kerekítés miatt 1-2 pixel
    normális lehet)."""
    out = []
    for n in nodes or []:
        if n["w"] <= 1 or n["h"] <= 1:
            continue
        if n["req_w"] - n["w"] > tol or n["req_h"] - n["h"] > tol:
            out.append(n)
    return out


def height_groups(nodes, cls=None) -> dict:
    """`{magasság: [elem, …]}` — a sor-magasságok eltérésének kimutatására.

    Az 1. körben a `Button` magasabb volt a `Label`-nél (`bd`/`highlightthickness`/
    `padx`/`pady` nélkül), amitől a stratégia-sor magasabb lett az instrumentum-
    sornál, és a tábla „ugrált". Egy csoport = jó; több = ugrálás."""
    out: dict = {}
    for n in nodes or []:
        if n["h"] <= 1:
            continue
        if cls and n["cls"] != cls:
            continue
        out.setdefault(n["h"], []).append(n)
    return out


def text_width(text: str, font) -> int:
    """Egy szöveg TÉNYLEGES pixel-szélessége az adott betűvel.

    Karakterszámból becsülni HIBA: a blokk-glifák (`▮▨▯`) és a `⛔` szélesebbek,
    mint a `0` — az 1. körben pont ez csordult túl, és a cella némán levágta a
    tartalmat. Mindig mérj."""
    return font.measure(text)


# ---------------------------------------------------------------------------
# Bemutató + önteszt
# ---------------------------------------------------------------------------

def _demo(parent):
    """Két sor: az egyik kifér, a másik SZÁNDÉKOSAN nem — hogy látszódjon, hogy az
    eszköz tényleg észreveszi a levágást."""
    from tkinter import font as tkfont
    mono = tkfont.Font(family="Consolas", size=11)
    ok = tk.Frame(parent, bg="#1e1e2e")
    ok.pack(fill="x", padx=10, pady=(14, 4))
    tk.Label(ok, text="kifér:", bg="#1e1e2e", fg="#a6adc8", font=mono,
             width=10, anchor="w").pack(side="left")
    tk.Label(ok, text="⛔1  ●●●  250/1312", bg="#313244", fg="#cdd6f4",
             font=mono, width=24, anchor="w").pack(side="left")

    bad = tk.Frame(parent, bg="#1e1e2e")
    bad.pack(fill="x", padx=10, pady=4)
    tk.Label(bad, text="levágva:", bg="#1e1e2e", fg="#a6adc8", font=mono,
             width=10, anchor="w").pack(side="left")
    cell = tk.Frame(bad, width=60, height=22, bg="#313244")
    cell.pack(side="left")
    cell.pack_propagate(False)          # fix méret → a tartalom nem fér ki
    tk.Label(cell, text="⛔1  ●●●  250/1312", bg="#313244", fg="#f38ba8",
             font=mono, anchor="w").pack(fill="both", expand=True)


def main() -> int:
    out = ROOT / "data" / "ui_preview" / "demo.png"
    nodes = inspect(_demo, size=(700, 120))
    trunc = truncated(nodes)
    print(f"widgetek: {len(nodes)}  |  levágott: {len(trunc)}")
    for t in trunc:
        print(f"   {t['cls']:<8} kért {t['req_w']}x{t['req_h']} → kapott "
              f"{t['w']}x{t['h']}   {t['text']!r}")
    if not trunc:
        print("HIBA: a bemutató SZÁNDÉKOSAN tartalmaz levágást, "
              "de az eszköz nem vette észre.")
        return 1
    try:
        p = capture(_demo, out, size=(700, 120))
        print(f"kép: {p}")
    except CaptureError as e:
        print(f"kép KIHAGYVA: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
