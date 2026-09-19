"""A KARMESTER KÜSZÖBEI — egy helyen, configból felülírhatóan.

⚠ MIÉRT KÜLÖN MODUL. A küszöb, ami a kódban szétszórva él, két bajt okoz:
(1) nem lehet hangolni anélkül, hogy kódot írnál; (2) egy jelentés nem tudja
megmondani, MIHEZ képest mondja, amit mond. A karmester minden döntése
számonkérhető kell legyen — ehhez a számnak NEVE és HELYE kell.

A config-blokk (`config.json` → `conductor`) minden kulcsa opcionális: ami
hiányzik, az alábbi alapértékre esik vissza. Az alapértékek NEM ízlés kérdése,
ahol mérés van mögöttük — a forrást a konstans mellé írjuk.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ⚠ MÉRT KÜSZÖB (core/quality.py, 2026-08-23): 50 valódi kötésnél a bootstrap
# 95%-os sávja 1,82-ig ér — egy „Jó" (PF ≥ 1,4) még lehet véletlen, de már csak
# ~3% eséllyel. Ez a bizonyíték-szorzó félértéke is (lásd `metrics.confidence`).
DEFAULTS = {
    "telemetry": {
        "keep_days": 90,
    },
    "health": {
        # Hány naponta írja ki a krónika ugyanazt a fennálló leletet. 1 = naponta
        # egyszer. ⚠ Enélkül egy tartós lelet minden körben új sort írna, és a
        # krónika olvashatatlanná válna — a valódi események elvesznének benne.
        "repeat_days": 1,
        # ELSZÁRADÁS: az élő aktivitás a vártnak ennyi töredéke alatt lelet.
        # 0,25 = „a negyedét sem hozza". ⚠ Nem szigorúbb, mert a mentett mérés
        # más időszakra szól: egy csendesebb hónap önmagában nem baj.
        "dried_up_ratio": 0.25,
        # ...de csak ennyi ÉLŐ nap után, különben egy frissen indított cella
        # azonnal „elszáradtnak" látszana.
        "dried_up_min_days": 14,
        # KAPU-FAL: egy kapu a jelek ennyi részét blokkolta ÉS egy kötés sem lett.
        "gate_wall_ratio": 0.8,
        # ...legalább ennyi jelnél (kevesebből ez zaj).
        "gate_wall_min_signals": 3,
        # NÉMA SOROZAT: ennyi OLYAN nap után lelet, amikor a motor futott
        # (a fájlban más celláknak volt jele), de ennek a cellának egy sem.
        "silent_days": 5,
    },
    "journal": {
        "keep_days": 365,
        # A krónika visszaolvasásakor legfeljebb ennyi sort nézünk (a duplikátum-
        # szűréshez és a `read`-hez). A napi takarítás mellett bőven elég.
        "max_scan_lines": 20000,
    },
}


def _blokk(cfg: dict, nev: str) -> dict:
    """Az alapértékek + a config felülírásai, TÍPUS-HŰEN.

    ⚠ MIÉRT ITT DŐL EL A TÍPUS, ÉS MIÉRT NEM A HÍVÓNÁL. A kézenfekvő
    `int(k.get("repeat_days") or 1)` minta NÉMÁN ELNYELI A SZÁNDÉKOS NULLÁT: a
    `0` hamis, tehát az `or` az alapértelmezést adja vissza. Vagyis a
    „kapcsold ki" (`repeat_days: 0`, `keep_days: 0`) beállítás pont az
    ELLENKEZŐJÉT csinálta volna, mint amit a felhasználó kért — és semmi nem
    szólt volna. Mivel a szótár MINDIG teljes (az alapértékekből indul), a hívó
    egyszerűen indexelhet, és ez a hiba nem tud megismétlődni."""
    d = dict(DEFAULTS.get(nev) or {})
    hato = ((cfg or {}).get("conductor") or {}).get(nev)
    if isinstance(hato, dict):
        for k, v in hato.items():
            # ⚠ A `_comment*` kulcsok DOKUMENTÁCIÓK a configban (a projekt
            # konvenciója), nem beállítások — ezek sosem lesznek küszöbök.
            if str(k).startswith("_") or k not in d:
                continue
            try:
                d[k] = type(d[k])(v)
            except (TypeError, ValueError):
                # ⚠ NEM néma: egy elgépelt érték csendben az alapértékkel futna,
                # és a felhasználó azt hinné, hogy az ő száma érvényes.
                log.warning("conductor.config: a(z) conductor.%s.%s értéke nem "
                            "értelmezhető (%r) — marad az alapérték (%r)",
                            nev, k, v, d[k])
    return d


def health(cfg: dict) -> dict:
    """Az egészségőr küszöbei."""
    return _blokk(cfg, "health")


def telemetry(cfg: dict) -> dict:
    return _blokk(cfg, "telemetry")


def journal(cfg: dict) -> dict:
    return _blokk(cfg, "journal")
