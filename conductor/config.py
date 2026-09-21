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
    "lifecycle": {
        # PAPÍR → ÉLŐ: ennyi jel kell a „csak jelzés" módban…
        "paper_min_signals": 30,
        # …ennyi OLYAN napon, amikor a motor futott (lásd `telemetry.window`).
        "paper_min_days": 10,
        # ÉLŐ → PAPÍR: ennyi valódi kötés alatt nem minősítünk vissza — a kis
        # mintából hozott visszaminősítés zajra reagálna (core/quality.py mérése).
        "demote_min_trades": 50,
        # …és csak ez alatti profit factornál.
        "demote_pf": 1.0,
        # A mentett készlet ennyi nap után avult (az `overview` 60 napnál szól).
        "stale_params_days": 60,
        # Az ELSZÁRADÁS küszöbeit az egészségőr adja (`health.dried_up_*`) — ott
        # van egy helyen, hogy a lelet és a döntés ne mondhasson mást.
    },
    "inbox": {
        # A javaslat ennyi nap után magától kiesik. ⚠ Ez a MÁSODIK védvonal: az
        # elsődleges az, hogy az elfogadás pillanatában újra ellenőrizzük,
        # igaz-e még (lásd `conductor/actions.py`).
        "expire_days": 7,
        # ⚠ AZ ELVETÉSNEK MEG KELL MARADNIA. Ha az elvetett javaslat másnap
        # újraszületne, az elvetés semmit nem jelentene — a postaláda pedig arra
        # tanítana, hogy hagyd figyelmen kívül.
        "reject_cooldown_days": 14,
        # Az elhalasztás („most nem") ennyi napra teszi félre.
        "defer_days": 3,
        # A LEZÁRT tételek takarítása (a TÖRTÉNET a krónikában van).
        "keep_days": 30,
    },
    "optqueue": {
        # ⚠ ALAPBÓL EGY. Az optimalizálás órákig tartó, CPU-nehéz munka, és az
        # ÉLŐ MOTOR MELLETT fut: hat párhuzamos futás elvenné a gépet a
        # kereskedés elől. (Az `optimizer.max_parallel_optimizers` a felület
        # saját sora — ez a karmesteré.)
        "max_parallel": 1,
        # Ennyi óra után egy „fut" tételt elveszettnek nyilvánítunk, ha a motor
        # újraindult közben (nincs meg a processz-fogantyú). Egy örökké „fut"
        # sor rosszabb, mint egy bevallott hiány.
        "stale_hours": 12,
        # A LEZÁRT tételek megtartása.
        "keep_days": 14,
    },
    "autonomy": {
        # ── A BUROK (F3/b) ───────────────────────────────────────────────
        # ⚠ EZ AZ, AMI L4-EN IS A HELYÉN MARAD. Az autonómia-fok azt mondja
        # meg, kell-e emberi pipa; a burok azt, MEDDIG mehet el a gép. A
        # kettő nem ugyanaz: egy elszálló visszacsatolási hurkot nem a fok
        # állít meg, hanem a kvóta.
        #
        # Hány GÉPI változtatás lehet EGY NAP, összesen. ⚠ Nem cellánként:
        # egy rossz nap hat cellán hat változás — az már nem finomhangolás,
        # hanem átrendezés, és arról tudnod kell.
        "max_changes_per_day": 6,
        # Egy CELLÁN ennyi óráig nem nyúlunk újra. ⚠ A mérésnek idő kell:
        # egy visszaminősítés után a papír-bizonyíték napokban gyűlik, nem
        # órákban. Enélkül a karmester oda-vissza kapcsolgatna.
        "cooldown_hours_per_cell": 72,
        # ⚠ NYITOTT POZÍCIÓ MELLETT NEM VÁLTOZTATUNK. A mód-váltás a BELÉPŐKRE
        # hat, a nyitott pozíciót a motor végigkezeli — de egy futó ügylet
        # közben átírni a cella szabályait olyan döntés, amit ember hozzon.
        "no_change_while_position_open": True,
        # Ennyi órán át KIEMELTEN mutatjuk a gépi lépést, hogy vissza tudd
        # vonni. ⚠ A visszavonás ezután is lehetséges (amíg a postaláda tétele
        # megvan) — ez az ABLAK arról szól, mit teszünk a szemed elé.
        "undo_window_hours": 24,
        # ⚠ A VISSZA NEM VONHATÓ akciók külön kapcsolón — L4 SEM oldja fel
        # magától. Ma nincs ilyen akció a készletben; a kapcsoló azért van itt,
        # hogy amikor lesz, ne kelljen új fogalmat bevezetni hozzá.
        "allow_irreversible": False,
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


def lifecycle(cfg: dict) -> dict:
    """Az életciklus-létra küszöbei."""
    return _blokk(cfg, "lifecycle")


def inbox(cfg: dict) -> dict:
    """A javaslat-postaláda küszöbei."""
    return _blokk(cfg, "inbox")


def optqueue(cfg: dict) -> dict:
    """A fej nélküli optimalizálás-sor küszöbei."""
    return _blokk(cfg, "optqueue")


def journal(cfg: dict) -> dict:
    return _blokk(cfg, "journal")


def autonomy(cfg: dict) -> dict:
    """A BUROK: kvóta, türelmi idő, pozíció-szabály, visszavonási ablak.

    ⚠ A FOKOT NEM ITT OLVASSUK. A `conductor.autonomy.default` és az
    `overrides` a `conductor/autonomy.py`-é (ott van a feloldás sorrendje); ez
    a szótár csak a KORLÁTOKAT adja. Ugyanabban a config-blokkban laknak, mert
    együtt kell olvasni őket — de a fok egy LÉTRA, a korlát egy SZÁM, és a
    kettőt külön kell tudni elrontani."""
    return _blokk(cfg, "autonomy")
