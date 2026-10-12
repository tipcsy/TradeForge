"""HOL VAN EGY BRÓKER ADATA — feed brókerenként, állapot számlánként.

⚠ 0029 „Több bróker egyszerre", 3. lépés (2026-09-28). Három csoport:

  • BRÓKER-FEED — a bróker árfolyamaiból: gyertyák (`m1`, `m15`…), tickek,
    a bars_manifest, a mért szerver-eltolás, a jelzés-napló, a forward-napló.
    Két bróker ára, spreadje, órája ELTÉR → nem keveredhet egy fájlban.
  • SZÁMLA — ticket szerint kulcsolt állapot: `trades.csv`, átvett pozíciók,
    pozíció-meta, SL-lépések, jelzés-kézbesítés, motor-állapot, karmester.
    A ticket a SZÁMLÁHOZ tartozik.
  • KÖZÖS — beállítások és hangolás (risk_mode, execution_params,
    optimized_params, modellek…). Tibi döntése: a paraméterek KÖZÖSEK.

⚠ MINDEN BRÓKER — AZ OTTHONI IS — A SAJÁT MAPPÁJÁBAN (2026-10-08):
        data/brokers/<id>/m1/…         (feed)
        data/accounts/<id>/…           (számla; a trades.csv is ide)
    Korábban az otthoni bróker a régi helyén maradt (`data/m1`, gyökér
    `trades.csv`) — ettől a `data/` mappában egy bróker szétszórva, a másik
    rendezetten ült, és nem látszott, mi kié. Az átköltöztetés eszköze:
    `tools/migrate_data_layout.py` (manifeszttel, visszavonható).

⚠ ÁTHELYEZŐ, NEM ÚJ ÁLLANDÓ. A modulok megtartják a „logikai" útvonal-
állandójukat (`adopted.PATH = data/adopted_positions.json`,
`live_trader.TRADES_CSV`…), és HASZNÁLATKOR ezen mennek át:
`broker_paths.account(PATH)` / `broker_paths.feed(path)`. Minden `data/`-n
KÍVÜLI útvonal (a tesztek ideiglenes fájljai) változatlanul jön vissza — a
tesztek állandó-cseréje így továbbra is működik.

Melyik a profil? Sorrendben:
  1. explicit `profile` argumentum (a felület több brókert is mutathat);
  2. az adapterben beállított AKTÍV (a `main.load_cfg` és a `connect` állítja);
  3. a `TRADEFORGE_BROKER` környezeti változó (kutató-eszközök, tesztek:
     `TRADEFORGE_BROKER=roboforex python tools/research/x.py`);
  4. a config.json aktív profilja (`active_broker`, különben a lista ELSŐ,
     otthoni eleme) — a sima kutató-futás és az optimalizáló-alprocesszek ide
     esnek, ugyanúgy, mint korábban az „otthoni" ágba.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:                                             # EXE-ben az adat az .exe mellett van
    from version import BASE_DIR as _BASE
    _BASE = Path(_BASE)
except Exception:                                # pragma: no cover
    _BASE = ROOT
DATA = _BASE / "data"
TRADES = _BASE / "trades.csv"                  # LOGIKAI útvonal (→ accounts/<id>/)
CONFIG = _BASE / "config.json"
ENV = "TRADEFORGE_BROKER"
# ⚠ A modulok vegyesen a `__file__`-ra és a `version.BASE_DIR`-re építik a
# `data/` útvonalat (a kettő EXE-ben ELTÉR). Mindkét gyökeret felismerjük —
# különben egy bróker EXE-ben csendben a régi, gyökérbeli fájlokba írna.
_GYOKEREK = tuple(dict.fromkeys([_BASE.resolve(), ROOT.resolve()]))

# Mi NEM brókerfüggő a `data/` alatt — ezeket sosem helyezzük át, akkor sem, ha
# valaki véletlenül feed()/account()-on át kéri (pl. a kutatási kimenetek).
_SAJAT_GYOKER = ("brokers", "accounts", "research", "_archive")

_cfg_cache: dict = {"mtime": None, "cfg": None}


def _config() -> dict:
    """A config.json NYERSEN (stratégia-merge nélkül), mtime szerint cache-elve.
    Hiányzó/hibás fájl → üres dict (→ az alap-profil)."""
    try:
        mt = CONFIG.stat().st_mtime
    except OSError:
        return {}
    if _cfg_cache["mtime"] != mt:
        try:
            _cfg_cache["cfg"] = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            _cfg_cache["cfg"] = {}
        _cfg_cache["mtime"] = mt
    return _cfg_cache["cfg"] or {}


def _env_profile():
    azon = os.environ.get(ENV, "").strip()
    if not azon:
        return None
    from core import broker_profile
    # ⚠ A környezeti változó KIFEJEZETT adat-választás (kutatás, tesztek) — egy
    # kikapcsolt (`"active": false`) bróker adata is elérhető vele: a kikapcsolás
    # a motort és a felületet érinti, a letöltött adat attól még ott van.
    for p in broker_profile.all_profiles(_config()):
        if p.id == azon:
            return p
    # ⚠ NEM esünk vissza csendben az otthonira: egy elgépelt név az otthoni
    # bróker adatán futtatná a „roboforexes" kutatást.
    raise ValueError(f"{ENV}={azon!r}: ismeretlen bróker (a profilok: "
                     f"{', '.join(p.id for p in broker_profile.all_profiles(_config()))})")


def _aktiv(profile=None):
    if profile is not None:
        return profile
    from core import broker_adapter
    p = broker_adapter.current()
    if p is not None:
        return p
    p = _env_profile()
    if p is not None:
        return p
    from core import broker_profile
    return broker_profile.active(_config())


def active_id(profile=None) -> str:
    """Az aktív bróker azonosítója (a mappanév)."""
    return _aktiv(profile).id


def is_home(profile=None) -> bool:
    return bool(getattr(_aktiv(profile), "home", True))


def _athelyez(path, gyoker: Path, profile=None) -> Path:
    # ⚠ A profilt CSAK akkor kérdezzük, ha tényleg áthelyezünk: profil nélkül
    # az a config.json beolvasása — egy data/-n kívüli (teszt-)útvonalnál ez
    # fölösleges költség a forró úton (lab tick_van: 20 ms → 40 ms).
    path = Path(path)
    r = path.resolve()
    for g in _GYOKEREK:
        if r == g / "trades.csv":
            return gyoker / _aktiv(profile).id / "trades.csv"
        try:
            rel = r.relative_to(g / "data")
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in _SAJAT_GYOKER:
            return path                          # már áthelyezett: nem duplázunk
        return gyoker / _aktiv(profile).id / rel
    return path                                  # data/-n kívül: nem a miénk


def feed(path, profile=None) -> Path:
    """Bróker-feed útvonal (a `data/…` alatti) → a bróker saját mappája."""
    return _athelyez(path, DATA / "brokers", profile)


def account(path, profile=None) -> Path:
    """Számla-állapot útvonal (a `data/…` alatti, vagy a `trades.csv`) → a
    számla saját mappája."""
    return _athelyez(path, DATA / "accounts", profile)


def feed_dir(kind: str, profile=None) -> Path:
    """Pl. `feed_dir("m1")` → `data/brokers/<id>/m1`."""
    return feed(DATA / kind, profile)


def bars_file(kind: str, symbol: str, profile=None) -> Path:
    """A gyertya-fájl: `data/brokers/<id>/<kind>/<symbol>.parquet`."""
    return feed_dir(kind, profile) / f"{symbol}.parquet"


def research_dir(profile=None) -> Path:
    """A kutatási kimenetek és gyorsítótárak helye: `data/research/<id>/`.

    ⚠ BRÓKERENKÉNT KÜLÖN: a gyorsítótárak (outcomes, flow, event_time…) a
    gyertyákból készülnek — egy közös mappában a roboforexes futás csendben az
    ActivTrades-gyorsítótárat olvasná vissza."""
    d = DATA / "research" / _aktiv(profile).id
    # a kimenetet író szkriptek eddig a mindig létező `data/`-ba írtak
    d.mkdir(parents=True, exist_ok=True)
    return d
