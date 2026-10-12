"""Tesztsegéd: a VALÓDI adaton futó tesztek rögzítése EGY brókerre.

⚠ MIÉRT (2026-10-12). A valódi gyertyákon futó tesztek (labor, paritás, szerver-
óra) eddig a config AKTÍV brókerének adatát olvasták. Amikor a RoboForex lett a
főszámla (és az ActivTrades ki lett kapcsolva), öt teszt egyszerre elbukott —
nem a kód miatt, hanem mert más bróker adatát kapták (más szerver-óra, más
gyertya-lefedettség, más pont-érték). A teszt eredménye nem függhet attól, hogy
a felhasználó épp melyik számlát jelölte főszámlának.

A rögzítés két helyen hat, és mindkettő kell:
  • `TRADEFORGE_BROKER` → a `core.broker_paths` ennek a brókernek a mappáját adja;
  • `broker_profile.set_override(..., allow_inactive=True)` → a `load_config` az
    ő pár-értékeit (pont-méret, költség) teszi a párokra — kikapcsolt brókernél is.

Ha a brókert a config nem ismeri (más gép, más beállítás), a rögzítés kimarad, és
a teszt a régi módon, az aktív brókeren fut.
"""
import os

ADAT_BROKER = "activtrades"


def pin(broker_id: str = ADAT_BROKER) -> bool:
    """Rögzíti a tesztet `broker_id` adatára. Visszaad: sikerült-e."""
    from core import broker_paths, broker_profile
    if broker_id not in {p.id for p in broker_profile.all_profiles(broker_paths._config())}:
        return False
    os.environ[broker_paths.ENV] = broker_id
    broker_profile.set_override(broker_id, allow_inactive=True)
    return True
