"""
PIAC-KAPU — a piac BESOROLÁSA alapján enged vagy nem.

⚠ EZ A KAPU EDDIG MODUL NÉLKÜL LÉTEZETT. A `REGISTRY`-ben ott volt, doksija
(`gates/docs/market.md`) is volt, a felületen is látszott — de a MÉRÉSE a
`live_trader` egyik függvényének közepén, kézzel beírva élt. Vagyis a
`gates/` csomag, aminek épp az lett volna a dolga, hogy „egy kapu egy darabban
mozdítható legyen", ezt az egy kaput nem tartalmazta.

⚠ AMI ITT NINCS, ÉS MIÉRT: maga az OSZTÁLYOZÓ (`core/market_strategy.py`,
`core/regime.py`). Az nem kapu, hanem egy önálló, cserélhető seam („milyen a
piac most?"), amit ez a kapu csak FOGYASZT — a besorolás készen érkezik a
kijelzés-állapotban (`ctx.ds.market_state`). Ha az osztályozó idekerülne, a
`gates/` mappa megint két különböző dolgot tartalmazna.

A „kedvezőtlen" halmaz KERESKEDÉSI döntés, ezért configból jön
(`gates.market.adverse`, ill. `pairs.<SYM>.gates.market.adverse`) — a kapu csak
összeveti vele a besorolást.
"""

from __future__ import annotations

# A kapu bejelentkezése a keretnek (ugyanaz a szótár, amit egy `.tfg`-vel
# telepített kapu is ad). A beépített kapuknál a `core/gates.REGISTRY` az
# elsődleges — ez itt a dokumentáció és a szimmetria kedvéért van.
GATE = {"key": "market", "default_effect": "none", "phase": "signal"}


def failed(category: str, adverse) -> bool:
    """Bukik-e a kapu ezzel a besorolással?

    Üres besorolás → NEM bukik (fail-open): ha az osztályozó nem tudott
    dönteni, a kapu nem tilthat le egy belépőt egy hiányzó adat miatt."""
    cat = str(category or "")
    return bool(cat) and cat in set(adverse or ())


def measure(ctx) -> tuple:
    """`(bukott_e, szint)` — a szint maga a BESOROLÁS (a sávos létrának).

    ⚠ A szintet akkor is visszaadjuk, ha nincs sáv-létra: a kijelzés a
    besorolást a kapu-cellában mutatja, és ez a viselkedés v3.28.0 óta így van.
    """
    from core import gates as _g

    if ctx.signal == "NONE":
        return False, None
    cat = getattr(ctx.ds, "market_state", "") or ""
    return failed(cat, _g.market_adverse(ctx.cfg or {}, ctx.symbol)), cat
