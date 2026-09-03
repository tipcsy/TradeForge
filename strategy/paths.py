"""
HOL LAKNAK A STRATÉGIÁK — egy helyen kimondva.

⚠ MIÉRT KELL EGY KÜLÖN MODUL EGY ÚTVONALÉRT. A szétválasztás előtt három
független helyen szerepelt ugyanaz a feltevés, mindhárom `__file__`-relatívan:

    strategy/settings.py       Path(__file__).parent / "config" / f"{name}.json"
    strategy/base.py           Path(__file__).parent / "docs"
    strategy/bollinger_...py   Path(__file__).parent / "config" / f"{name}.json"

Amíg minden egy mappában volt, ez működött — és pontosan ezért volt veszélyes: a
`config/` elmozdítása HÁROM fájlt tört volna el, egymástól függetlenül, és a
hiba nem kivétel lett volna, hanem egy néma „nincs config, megyek az
alapértékkel". Most egy forrás van; ha a stratégiák egyszer (a `.tfs` csomagolás
miatt) megint máshová kerülnek, EZT az egy fájlt kell átírni.

⚠ NEM a `strategy/__init__.py`-ban van, mert az importálja a `base`-t, a `base`
pedig innen kér útvonalat — körkörös import lenne. Egy levél-modul nem tud
kört csinálni.
"""

from __future__ import annotations

from pathlib import Path

# A projekt gyökere (ez a fájl a `strategy/` csomagban van).
ROOT = Path(__file__).resolve().parents[1]

# A TARTALOM csomagja — a konkrét stratégiák. A név importnévként is ez.
PACKAGE = "strategies"
DIR = ROOT / PACKAGE


def config_file(name: str) -> Path:
    """Egy stratégia saját config-fájlja: `strategies/config/<név>.json`."""
    return DIR / "config" / f"{name}.json"


def docs_dir() -> Path:
    """A stratégia-leírások mappája: `strategies/docs/`."""
    return DIR / "docs"
