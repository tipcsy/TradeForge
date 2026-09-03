"""
HOL LAKNAK A KAPUK — egy helyen kimondva.

Ugyanaz a szerep, mint a `strategy/paths.py`-é a stratégiáknál: EGY forrás arra a
kérdésre, hol keresse a program a kapu-tartalmat. A stratégiáknál ez a modul
azért kellett, mert HÁROM fájl számolta ki ugyanazt `__file__`-relatívan, és egy
elmozdítás mindhármat eltörte volna — némán, alapértékekre esve. A kapuknál most
csak EGY ilyen hely van (a leírás útvonala), de ugyanaz a hiba készül elő, ha ott
marad: a `.tfg` csomagolás (#3) épp azt fogja elmozdítani.
"""

from __future__ import annotations

from pathlib import Path

# A projekt gyökere (ez a fájl a `gates/` csomagban van).
ROOT = Path(__file__).resolve().parents[1]

# A TARTALOM csomagja — az egyes kapuk mérése és leírása.
PACKAGE = "gates"
DIR = ROOT / PACKAGE


def docs_dir() -> Path:
    """A kapu-leírások mappája: `gates/docs/`."""
    return DIR / "docs"
