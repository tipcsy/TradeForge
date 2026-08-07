"""
Mely kapuk LÁTSZANAK, milyen SORRENDBEN — és melyik van teljesen kikapcsolva.

Eddig a kapu-oszlopok sorrendje és köre BE VOLT DRÓTOZVA
(`dashboard/canvas_columns.column_keys`), a láthatóságuk pedig automatikus volt:
ha egyetlen páron sem volt mért érték, az oszlop eltűnt. Ez két okot adott arra,
hogy valami ne látsszon — és nehéz volt kitalálni, melyik érvényes.

MOSTANTÓL EGY LISTA DÖNT. A `dashboard.gate_order` az ENGEDÉLYEZETT kapuk
kulcsai, a megjelenítés sorrendjében:

    "dashboard": { "gate_order": ["spread", "tf_align", "cost"] }

Ami NINCS a listában, az KI VAN KAPCSOLVA — és ez KÉT dolgot jelent együtt:

  1. az oszlopa nem látszik, ÉS
  2. a kapu EGYETLEN instrumentumon sem szól bele a kereskedésbe.

A kettő szándékosan nem választható szét. Ha csak elrejtenénk az oszlopot, a
kapu LÁTHATATLANUL blokkolhatna tovább — pontosan az a hibaosztály, ami ebben a
projektben többször visszaütött (némán aktív vagy némán tétlen funkció, aminek
a felületen semmi nyoma).

⚠ A kikapcsolás FELFÜGGESZT, nem TÖRÖL. A per-pár/per-stratégia hatások
(`pairs.<SYM>.gates.…`) érintetlenül a configban maradnak, és visszakapcsoláskor
újra élnek. A kapu beállító ablaka pedig kiírja, hogy „a Beállításokban
kikapcsolva" — nem hazudik „Ki"-t, ami azt sugallná, hogy te állítottad úgy.

A kulcs HIÁNYA = a mai viselkedés: minden kapu engedélyezett, a `REGISTRY`
sorrendjében.

TISZTA modul: se tkinter, se MT5, se fájl.
"""

from __future__ import annotations

from core import gates as _g

# A kapu KULCSA (config, `core/gates.py`) ↔ az OSZLOP kulcsa (a tábla modellje).
# A kettő egy helyen tér el: a `tf_align` oszlopa történelmi okból `align`.
_COLUMN_OF = {_g.TF_ALIGN: "align"}
_GATE_OF = {v: k for k, v in _COLUMN_OF.items()}


def column_key(gate_key: str) -> str:
    """A kapu OSZLOP-kulcsa (`tf_align` → `align`, egyébként önmaga)."""
    return _COLUMN_OF.get(gate_key, gate_key)


def gate_key(column_key_: str) -> str:
    """Az oszlop-kulcshoz tartozó KAPU-kulcs (`align` → `tf_align`)."""
    return _GATE_OF.get(column_key_, column_key_)


def _raw(cfg: dict):
    v = ((cfg or {}).get("dashboard") or {}).get("gate_order")
    return v if isinstance(v, (list, tuple)) else None


def enabled_gates(cfg: dict = None) -> list:
    """Az ENGEDÉLYEZETT kapuk kulcsai, MEGJELENÍTÉSI sorrendben.

    Hiányzó/érvénytelen config → minden kapu, a `REGISTRY` sorrendjében (a mai
    viselkedés). Az ismeretlen kulcsokat kiszűrjük, hogy egy elgépelés ne
    tüntessen el némán egy kaput."""
    raw = _raw(cfg)
    if raw is None:
        return list(_g.KEYS)
    seen, out = set(), []
    for k in raw:
        k = gate_key(str(k))
        if k in _g.KEYS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def disabled_gates(cfg: dict = None) -> list:
    """A KIKAPCSOLT kapuk, a `REGISTRY` sorrendjében (a beállító ablak bal listája)."""
    on = set(enabled_gates(cfg))
    return [k for k in _g.KEYS if k not in on]


def is_enabled(cfg: dict, key: str) -> bool:
    """Engedélyezve van-e ez a kapu EGYÁLTALÁN? (`False` → rejtett ÉS hatástalan)"""
    return gate_key(key) in enabled_gates(cfg)


def enabled_columns(cfg: dict = None) -> list:
    """Ugyanez OSZLOP-kulcsokkal — ezt fogyasztja a tábla oszlop-modellje."""
    return [column_key(k) for k in enabled_gates(cfg)]


def apply_order(cfg: dict, gate_keys) -> dict:
    """Az engedélyezett kapuk listájának BEÍRÁSA a configba (a `cfg`-t módosítja).

    A TELJES listát kiírjuk, akkor is, ha épp minden kapu engedélyezett. Ez
    tudatos: enélkül a fájlból nem derülne ki, MI a sorrend — csak az, hogy
    eltér-e valamitől. (Ugyanaz a döntés, mint az `available_strategies`-nél.)"""
    clean, seen = [], set()
    for k in (gate_keys or []):
        k = gate_key(str(k))
        if k in _g.KEYS and k not in seen:
            seen.add(k)
            clean.append(k)
    cfg.setdefault("dashboard", {})["gate_order"] = clean
    return cfg
