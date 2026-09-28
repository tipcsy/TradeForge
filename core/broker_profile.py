"""BRÓKER-PROFILOK — melyik bróker, melyik számla, milyen óra, milyen szimbólumnevek.

⚠ 0029 „Több bróker egyszerre", 2. lépés (2026-09-28). A program eddig egyetlen
brókert ismert (a config `broker` + `mt5` blokkja). A profil ezt általánosítja:

    "brokers": [
      {"id": "activtrades", "tag": "At", "name": "ActivTrades",
       "server": "...", "login": 123, "password": "...", "is_demo": true,
       "magic": 20260627, "mt5": {"path": "...", "portable": true},
       "server_zone": "Europe/Berlin",
       "symbols": {}},                                  # kanonikus -> bróker
      {"id": "roboforex", "tag": "Rob", ..., "server_zone": "America/New_York+7",
       "symbols": {"GOLD": "XAUUSD"}}
    ],
    "active_broker": "activtrades"

⚠ VISSZAFELÉ KOMPATIBILIS: ha nincs `brokers` lista, a mai `broker` + `mt5`
blokkból EGY profil épül — ugyanazokkal az értékekkel. A mai config tehát
változatlanul működik, és semmit nem kell átírni.

⚠ LEGFELJEBB 5 BRÓKER (Tibi döntése, 2026-09-28): „a 2-3-4 még reális, 5
már sok, annál több ne lehessen". A `validate` ezt hibának jelzi.

⚠ A SZIMBÓLUM-ALIAS. A programon belül MINDEN a kanonikus névvel megy (a
`pairs` kulcsa: `GOLD`); csak az MT5 felé forduló réteg (`core/broker_adapter`)
fordít a bróker saját nevére (`XAUUSD`). Így a hangolt paraméterek, kapuk,
naplók nem vesznek el bróker-váltáskor.

TISZTA modul: se MT5, se fájl — a hívó adja a configot.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from core import broker_time as BT

MAX_BROKERS = 5


@dataclass(frozen=True)
class BrokerProfile:
    id: str
    tag: str
    name: str = ""
    server: str = ""
    login: int = 0
    password: str = field(default="", repr=False)
    is_demo: bool = False
    magic: int = 0
    mt5: dict = field(default_factory=dict, compare=False, hash=False)
    server_zone: BT.ServerZone = BT.CANONICAL
    symbols: dict = field(default_factory=dict, compare=False, hash=False)
    # Az OTTHONI bróker (a lista első eleme; régi config: az egyetlen) adatai a
    # régi helyükön maradnak — lásd core/broker_paths.py.
    home: bool = True
    # A felügyelő újraindítja-e a leállt motort (core/engine_supervisor).
    # Alapból NEM: egy kereskedő motor magától ne induljon, csak ha kérted.
    autostart: bool = False

    # ── szimbólum-fordítás ────────────────────────────────────────────────
    def to_broker(self, sym):
        """Kanonikus név → a bróker neve (nincs alias → ugyanaz)."""
        return self.symbols.get(sym, sym) if isinstance(sym, str) else sym

    def to_canonical(self, sym):
        """A bróker neve → kanonikus név (nincs alias → ugyanaz)."""
        if not isinstance(sym, str) or not self.symbols:
            return sym
        return self._vissza().get(sym, sym)

    def _vissza(self) -> dict:
        return {v: k for k, v in self.symbols.items()}

    @property
    def is_identity(self) -> bool:
        """Semmit nem kell fordítani: kanonikus óra ÉS nincs alias.
        (A mai ActivTrades-config ilyen → az adapter mindent érintetlenül ad át.)"""
        return self.server_zone.is_canonical and not self.symbols


def _alap_tag(nev: str, azon: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", nev or azon) or "Br"
    return s[:3]


def _profil(d: dict, mt5_cfg: dict | None = None, home: bool = True) -> BrokerProfile:
    nev = str(d.get("name", "") or "")
    azon = str(d.get("id") or re.sub(r"[^a-z0-9]", "", nev.lower()) or "broker")
    return BrokerProfile(
        id=azon,
        tag=str(d.get("tag") or _alap_tag(nev, azon)),
        name=nev or azon,
        server=str(d.get("server", "") or ""),
        login=int(d.get("login", 0) or 0),
        password=str(d.get("password", "") or ""),
        is_demo=bool(d.get("is_demo", False)),
        magic=int(d.get("magic", 0) or 0),
        mt5=dict(d.get("mt5") if isinstance(d.get("mt5"), dict) else (mt5_cfg or {})),
        server_zone=BT.parse(d.get("server_zone")),
        symbols={str(k): str(v) for k, v in (d.get("symbols") or {}).items()
                 if str(k) != str(v)},
        home=home,
        autostart=bool(d.get("autostart", False)),
    )


def profiles(cfg: dict | None) -> list[BrokerProfile]:
    """Az összes profil. `brokers` lista nélkül a régi `broker` + `mt5` blokk."""
    cfg = cfg or {}
    lista = cfg.get("brokers")
    if isinstance(lista, list) and lista:
        dl = [d for d in lista if isinstance(d, dict)]
        return [_profil(d, home=(i == 0)) for i, d in enumerate(dl)]
    return [_profil(cfg.get("broker") or {}, cfg.get("mt5") or {})]


_override: str | None = None


def set_override(broker_id: str | None) -> None:
    """A `--broker <id>` futásidejű választása (0029, 4. lépés).

    ⚠ NEM a configba: ha a motor egy mentésnél kiírná az `active_broker`-t, a
    következő indításkor a FELÜLET motorja is erre a brókerre állna át."""
    global _override
    _override = broker_id or None


def active(cfg: dict | None) -> BrokerProfile:
    """Az aktív profil: a `--broker` felülírás, az `active_broker`, különben az
    első. Ismeretlen `--broker` azonosítóra ValueError — csendben NEM esünk
    vissza az otthoni brókerre (egy második motor azzal az otthoni számlán
    kereskedne)."""
    ps = profiles(cfg)
    if _override:
        for p in ps:
            if p.id == _override:
                return p
        raise ValueError(f"ismeretlen bróker: {_override!r} "
                         f"(a profilok: {', '.join(p.id for p in ps)})")
    want = (cfg or {}).get("active_broker")
    for p in ps:
        if want and p.id == want:
            return p
    return ps[0]


def validate(cfg: dict | None) -> list[str]:
    """A profil-lista hibái (üres = rendben). A zóna-hibát is itt fogjuk meg:
    egy elgépelt zóna NÉMÁN elcsúsztatná az összes órát."""
    hibak = []
    lista = (cfg or {}).get("brokers")
    nyers = lista if isinstance(lista, list) and lista else None
    if nyers is not None and len(nyers) > MAX_BROKERS:
        hibak.append(f"legfeljebb {MAX_BROKERS} bróker lehet, a configban {len(nyers)} van")
    ps = []
    for d in (nyers or [None]):
        try:
            ps.append(_profil(d) if d is not None else profiles(cfg)[0])
        except ValueError as e:
            hibak.append(str(e))
    for mezo in ("id", "tag"):
        ertekek = [getattr(p, mezo) for p in ps]
        dup = sorted({v for v in ertekek if ertekek.count(v) > 1})
        if dup:
            hibak.append(f"ismétlődő bróker-{mezo}: {', '.join(dup)}")
    szamlak = [(p.server, p.login) for p in ps if p.login]
    if len(szamlak) != len(set(szamlak)):
        hibak.append("ugyanaz a számla (szerver + login) kétszer szerepel")
    for p in ps:
        celok = list(p.symbols.values())
        dup = sorted({v for v in celok if celok.count(v) > 1})
        if dup:
            hibak.append(f"{p.id}: több kanonikus név ugyanarra a bróker-szimbólumra: "
                         f"{', '.join(dup)}")
    want = (cfg or {}).get("active_broker")
    if want and want not in [p.id for p in ps]:
        hibak.append(f"az active_broker ('{want}') nincs a profilok között")
    return hibak


# ── BRÓKER-FÜGGŐ INSTRUMENTUM-ÉRTÉKEK (0029, 3. lépés) ──────────────────────
# Ugyanaz az instrumentum két brókernél más kontraktus: más pont-méret, pip-
# érték, lot-korlát, jutalék, swap, spread. Ezek a `pairs.<sym>.brokers.<id>`
# blokkba kerülnek; az ALAP (a `pairs.<sym>` saját kulcsai) az OTTHONI brókeré.
#
# ⚠ A MENTÉS A VESZÉLY. Betöltéskor (nem-otthoni brókernél) a bróker értékei
# a pár alapkulcsaira kerülnek — így a motor, a backteszt és a méretezés
# változtatás nélkül a jó számokkal dolgozik. Ha viszont egy mentés ezt a
# futásidejű dictet írná ki, a MÁSIK bróker számai az otthoni helyére kerülnének
# (a config.json-t tesztek már kétszer letarolták — ez ugyanaz a hibaosztály).
# Ezért a felülírás EMLÉKSZIK az eredetire (`_broker_overlay`), és az egyetlen
# config-író (`strategy.settings.write_config_file`) kiírás előtt VISSZAÁLLÍTJA;
# ha a felhasználó futás közben módosított egy ilyen értéket, az a bróker SAJÁT
# blokkjába kerül.

BROKER_PAIR_KEYS = ("point_size", "pv1_point", "min_lot", "lot_step", "max_lot",
                    "commission_per_lot", "swap_long_per_lot", "swap_short_per_lot",
                    "swap_3x_weekday", "backtest_spread_points")
# ⚠ A KERESKEDÉSI SZÁNDÉK IS BRÓKERENKÉNT (4. lépés). A `run_state` (Play/Stop)
# és a vele szinkronban tartott `enabled` a pár alatt él. Közösen egy második
# bróker motorja ugyanazokat a párokat indítaná, és a Play/Stop-ja az OTTHONI
# szándékot írná át. Nem-otthoni brókernél ezért a saját blokkjából jönnek, és
# ha ott nincsenek: LEÁLLÍTVA — egy új bróker motorja magától semmit nem indít.
BROKER_INTENT_DEFAULTS = {"run_state": {}, "enabled": False}
OVERLAY_KEY = "_broker_overlay"


def overlay_pairs(cfg: dict, profile: BrokerProfile) -> dict:
    """A nem-otthoni bróker értékei (instrumentum + szándék) a pár alapkulcsaira
    (helyben). Otthoni brókernél NEM csinál semmit. Visszaad: a cfg.

    A betöltött értékről PILLANATKÉP készül: a mentés ehhez hasonlít, így a
    helyben módosított (pl. `run_state[...] = "live"`) érték is a bróker
    blokkjába kerül."""
    if profile is None or profile.home or not isinstance(cfg, dict):
        return cfg
    applied, orig, hianyzott = {}, {}, {}
    for sym, pc in (cfg.get("pairs") or {}).items():
        if not isinstance(pc, dict):
            continue
        blokk = (pc.get("brokers") or {}).get(profile.id)
        blokk = blokk if isinstance(blokk, dict) else {}
        ertekek = {k: blokk[k] for k in BROKER_PAIR_KEYS if k in blokk}
        for k, alap in BROKER_INTENT_DEFAULTS.items():
            ertekek[k] = blokk.get(k, alap)
        for k, v in ertekek.items():
            if k in pc:
                orig.setdefault(sym, {})[k] = pc[k]
            else:
                hianyzott.setdefault(sym, []).append(k)
            pc[k] = copy.deepcopy(v)
            applied.setdefault(sym, {})[k] = copy.deepcopy(v)
    if applied:
        cfg[OVERLAY_KEY] = {"id": profile.id, "applied": applied, "orig": orig,
                            "missing": hianyzott}
    return cfg


def restore_for_save(data: dict) -> dict:
    """Kiírás előtt (helyben): az otthoni értékek vissza, a futás közbeni
    módosítás a bróker SAJÁT blokkjába. A rejtett kulcs eltűnik."""
    if not isinstance(data, dict):
        return data
    ov = data.pop(OVERLAY_KEY, None)
    if not isinstance(ov, dict):
        return data
    pid = ov.get("id")
    pairs = data.get("pairs") or {}
    for sym, kulcsok in (ov.get("applied") or {}).items():
        pc = pairs.get(sym)
        if not isinstance(pc, dict):
            continue
        for k, betoltott in kulcsok.items():
            if k in pc and pc[k] != betoltott:          # futás közben módosult
                pc.setdefault("brokers", {}).setdefault(pid, {})[k] = pc[k]
            if k in (ov.get("orig") or {}).get(sym, {}):
                pc[k] = ov["orig"][sym][k]
            elif k in (ov.get("missing") or {}).get(sym, []):
                pc.pop(k, None)
    return data


def write_target(pair_cfg: dict, profile: BrokerProfile) -> dict:
    """Hova írjon egy bróker-függő értéket egy eszköz (pl. refresh_costs):
    otthoni brókernél a pár maga, különben a `brokers.<id>` blokkja."""
    if profile is None or profile.home:
        return pair_cfg
    return pair_cfg.setdefault("brokers", {}).setdefault(profile.id, {})
