"""HOL VAN EGY BRÓKER ADATA — feed brókerenként, állapot számlánként.

⚠ 0029 „Több bróker egyszerre", 3. lépés (2026-09-28). Három csoport:

  • BRÓKER-FEED — a bróker árfolyamaiból: gyertyák (`data/m1`, `m15`…), tickek,
    a bars_manifest, a mért szerver-eltolás, a jelzés-napló. Két bróker ára,
    spreadje, órája ELTÉR → nem keveredhet egy fájlban.
  • SZÁMLA — ticket szerint kulcsolt állapot: `trades.csv`, átvett pozíciók,
    pozíció-meta, SL-lépések, jelzés-kézbesítés. A ticket a SZÁMLÁHOZ tartozik.
  • KÖZÖS — beállítások és hangolás (risk_mode, execution_params,
    optimized_params, modellek…). Tibi döntése: a paraméterek KÖZÖSEK.

⚠ NINCS ADAT-KÖLTÖZTETÉS. Az ELSŐ (otthoni) bróker — ma az egyetlen, az
ActivTrades — adatai PONTOSAN OTT MARADNAK, ahol eddig: az élő program futás
közben írja őket, a kutató-eszközök tucatjai közvetlenül a `data/m1`-et
olvassák, és így a mai működés bitre változatlan. Csak az új brókerek kapnak
saját mappát:
        data/brokers/<id>/m1/…         (feed)
        data/accounts/<id>/…           (számla; a trades.csv is ide)

⚠ ÁTHELYEZŐ, NEM ÚJ ÁLLANDÓ. A modulok megtartják a saját útvonal-állandójukat
(`adopted.PATH`, `live_trader.TRADES_CSV`…), és HASZNÁLATKOR ezen mennek át:
`broker_paths.account(PATH)` / `broker_paths.feed(path)`. Az otthoni brókernél
és minden `data/`-n KÍVÜLI útvonalnál (a tesztek ideiglenes fájljai) a bemenet
változatlanul jön vissza — a tesztek állandó-cseréje így továbbra is működik.

Melyik a profil? Alapból az adapterben beállított AKTÍV (a `main.load_cfg` és a
`connect` állítja); egy explicit `profile` felülírja (a felület több brókert
is mutathat).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:                                             # EXE-ben az adat az .exe mellett van
    from version import BASE_DIR as _BASE
    _BASE = Path(_BASE)
except Exception:                                # pragma: no cover
    _BASE = ROOT
DATA = _BASE / "data"
TRADES = _BASE / "trades.csv"                  # az otthoni bróker helye (örökség)
# ⚠ A modulok vegyesen a `__file__`-ra és a `version.BASE_DIR`-re építik a
# `data/` útvonalat (a kettő EXE-ben ELTÉR). Mindkét gyökeret felismerjük —
# különben egy második bróker EXE-ben csendben az otthoni fájlokba írna.
_GYOKEREK = tuple(dict.fromkeys([_BASE.resolve(), ROOT.resolve()]))


def _aktiv(profile=None):
    if profile is not None:
        return profile
    from core import broker_adapter
    return broker_adapter.current()


def is_home(profile=None) -> bool:
    p = _aktiv(profile)
    return p is None or bool(getattr(p, "home", True))


def _athelyez(path, gyoker: Path, profile=None) -> Path:
    path = Path(path)
    if is_home(profile):
        return path
    p = _aktiv(profile)
    r = path.resolve()
    for g in _GYOKEREK:
        if r == g / "trades.csv":
            return gyoker / p.id / "trades.csv"
        try:
            rel = r.relative_to(g / "data")
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in ("brokers", "accounts"):
            return path                          # már áthelyezett: nem duplázunk
        return gyoker / p.id / rel
    return path                                  # data/-n kívül: nem a miénk


def feed(path, profile=None) -> Path:
    """Bróker-feed útvonal (a `data/…` alatti) → a bróker saját mappája."""
    return _athelyez(path, DATA / "brokers", profile)


def account(path, profile=None) -> Path:
    """Számla-állapot útvonal (a `data/…` alatti, vagy a `trades.csv`) → a
    számla saját mappája."""
    return _athelyez(path, DATA / "accounts", profile)


def feed_dir(kind: str, profile=None) -> Path:
    """Pl. `feed_dir("m1")` → `data/m1` (otthon) vagy `data/brokers/<id>/m1`."""
    return feed(DATA / kind, profile)


def bars_file(kind: str, symbol: str, profile=None) -> Path:
    """A gyertya-fájl: `data/<kind>/<symbol>.parquet`, a bróker mappájában."""
    return feed_dir(kind, profile) / f"{symbol}.parquet"
