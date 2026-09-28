"""ÁLLAPOTFÁJLOK ÚJRATÖLTÉSE — két processz, egy állapot (0029, 4b/3 S3a).

⚠ A LELET (2026-09-28): hat állapot-modul (`rr_state`, `risky_mode`,
`build_state`, `correlation`, `adopted`, `position_meta`) betöltéskor a
memóriájába olvassa a fájlját, és utána NEM nézi meg újra. Amíg a motor és a
felület egy processz volt, ez mindegy volt. Külön processzben két irányban is
elcsúszott volna:
  • a felületen átállított runner / preset / építés-mód NEM jut el a motorhoz;
  • a motor által írt pozíció-adatot (belépéskori kockázat, örökbefogadás) a
    felület NEM látja.

A MEGOLDÁS: egy központi újratöltő. A regisztrált modulok fájljának lenyomatát
(módosítási idő + méret) nézi, és ahol változott, meghívja a modul SAJÁT
`load()`-ját. A motor a kör elején hívja (a config-újratöltés mellett), a
felület a távoli pumpájában. Egy `stat` mikroszekundumos.

⚠ Csak a MÁR BETÖLTÖTT modulokat nézi (`sys.modules`) — nem húz be semmit, amit
a processz nem használ. A saját írás utáni újratöltés ártalmatlan (ugyanaz a
tartalom). Az ÍRÁS egy processzé marad: külön processzben futó motornál a
felület a motoron át módosít (S3b), így egy fájlt nem ír két processz.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

MODULES = ("core.rr_state", "core.risky_mode", "core.build_state",
           "core.correlation", "core.adopted", "core.position_meta")

_utolso: dict = {}


def _utvonal(mod) -> Path | None:
    fn = getattr(mod, "_path", None)
    try:
        return Path(fn()) if callable(fn) else Path(getattr(mod, "PATH"))
    except Exception:
        return None


def _lenyomat(p: Path):
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def refresh_all(modules=MODULES) -> list:
    """Egy kör. Visszaad: az újratöltött modulok nevei."""
    kesz = []
    for nev in modules:
        mod = sys.modules.get(nev)
        if mod is None:
            continue
        p = _utvonal(mod)
        if p is None:
            continue
        most = _lenyomat(p)
        kulcs = (nev, str(p))
        if kulcs in _utolso and _utolso[kulcs] == most:
            continue
        elso = kulcs not in _utolso
        _utolso[kulcs] = most
        if elso or most is None:
            # Első megfigyelés: a modul a saját betöltését már elvégezte; csak
            # megjegyezzük. Eltűnt fájl: a memória marad (nem nullázunk).
            continue
        try:
            mod.load()
            kesz.append(nev)
        except Exception as ex:
            log.warning("állapot-újratöltés hiba (%s): %s", nev, ex)
    return kesz
