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

⚠ 2026-10-12: a config.json-ban MÁR CSAK a `brokers` lista van (a régi `broker`
+ `mt5` blokk kikerült — a belső motor is a listából olvas). Egy régi config
(lista nélkül) továbbra is beolvasható: a `broker` + `mt5` blokkból EGY profil
épül.

⚠ KÉT JELZŐ brókerenként (Tibi, 2026-10-12):
  • `"main": true`  — a FŐSZÁMLA (a felület saját motorja, ez áll a lista
    elején). Ha több van bejelölve, az ELSŐ találat számít; ha egy sincs, az
    első aktív bróker.
  • `"active": false` — a bróker KI VAN KAPCSOLVA: a program sehol nem látja
    (nem indul motorja, nincs oszlopa, órája, fül-sora). Hiányzik → aktív.
    Így egy bróker adatai törlés nélkül félretehetők.

⚠ FŐSZÁMLA ≠ ALAP-ÉRTÉKEK GAZDÁJA. A `pairs.<sym>` saját kulcsai (pont-méret,
jutalék, run_state, kötés-mód …) a lista ELSŐ elemének brókeréé (`base`) — a
főszámla átállítása ezen NEM változtat, különben egy másik bróker motorja az
első bróker Play/Stop-ját és ÉLES kötés-módját örökölné (lásd a 0031-es
AUDCHF-esetet lent).

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
    # Az OTTHONI bróker = a FŐSZÁMLA (`"main": true`; ha nincs, az első aktív) —
    # a felület saját motorja. Az adatai 2026-10-08 óta ugyanúgy a saját
    # mappájában vannak, mint a többié (core/broker_paths).
    home: bool = True
    # Az ALAP-ÉRTÉKEK gazdája: a `brokers` lista ELSŐ eleme (régi config: az
    # egyetlen). A `pairs.<sym>` saját kulcsai az övéi; a többi bróker a
    # `pairs.<sym>.brokers.<id>` blokkból kap felülírást (overlay_pairs).
    base: bool = True
    # A felügyelő újraindítja-e a leállt motort (core/engine_supervisor).
    # Alapból NEM: egy kereskedő motor magától ne induljon, csak ha kérted.
    autostart: bool = False
    # 0029/6a: a számla SAJÁT kockázati beállításai (a közös `trading` fölé) —
    # csak a BROKER_TRADING_KEYS; üres → a közös érvényes.
    trading: dict = field(default_factory=dict, compare=False, hash=False)

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


def _profil(d: dict, mt5_cfg: dict | None = None, home: bool = True,
            base: bool = True) -> BrokerProfile:
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
        base=base,
        autostart=bool(d.get("autostart", False)),
        trading={k: v for k, v in (d.get("trading") or {}).items()
                 if k in BROKER_TRADING_KEYS},
    )


def is_active(d: dict) -> bool:
    """Egy `brokers`-elem aktív-e (`"active": false` → ki van kapcsolva)."""
    return bool(d.get("active", True))


def _main_index(dl: list) -> int:
    """A főszámla indexe a nyers listában: az első `main: true` AKTÍV elem;
    ha nincs ilyen, az első aktív; ha egy sem aktív, a 0."""
    akt = [i for i, d in enumerate(dl) if is_active(d)]
    for i in akt:
        if bool(dl[i].get("main", False)):
            return i
    return akt[0] if akt else 0


def profiles(cfg: dict | None) -> list[BrokerProfile]:
    """Az AKTÍV profilok, a FŐSZÁMLA az első helyen (utána a lista sorrendje).

    A kikapcsolt (`"active": false`) bróker NINCS benne — a program sehol nem
    látja. Ha MINDEN bróker ki van kapcsolva, a főszámla (vagy az első) marad:
    bróker nélkül nincs mihez kapcsolódni (a `validate` ezt jelzi).
    `brokers` lista nélkül a régi `broker` + `mt5` blokk (egy profil)."""
    cfg = cfg or {}
    lista = cfg.get("brokers")
    if isinstance(lista, list) and lista:
        dl = [d for d in lista if isinstance(d, dict)]
        if not dl:
            return [_profil({})]
        fo = _main_index(dl)
        sorrend = [fo] + [i for i, d in enumerate(dl) if i != fo and is_active(d)]
        return [_profil(dl[i], home=(i == fo), base=(i == 0)) for i in sorrend]
    return [_profil(cfg.get("broker") or {}, cfg.get("mt5") or {})]


def all_profiles(cfg: dict | None) -> list[BrokerProfile]:
    """MINDEN profil, a kikapcsoltakkal együtt (a lista sorrendjében) — csak
    ott kell, ahol egy kikapcsolt bróker maradványát is el kell érni (pl. a
    program bezárásakor egy még futó motorja leállítása)."""
    cfg = cfg or {}
    lista = cfg.get("brokers")
    if isinstance(lista, list) and lista:
        dl = [d for d in lista if isinstance(d, dict)]
        if dl:
            fo = _main_index(dl)
            return [_profil(d, home=(i == fo), base=(i == 0)) for i, d in enumerate(dl)]
    return profiles(cfg)


def main(cfg: dict | None) -> BrokerProfile:
    """A főszámla (a felület saját motorja)."""
    return profiles(cfg)[0]


def magic_of(cfg: dict | None) -> int:
    """Az aktív bróker `magic` alapszáma (a stratégiák erre teszik az eltolásukat).

    ⚠ Eddig a régi `broker` blokkból jött — az a configból kikerült. Ismeretlen
    `--broker` esetén (ValueError) a főszámláé: a magic csak azonosít, a hibás
    választást a motor indulása úgyis megállítja."""
    try:
        return int(active(cfg).magic or 0)
    except ValueError:
        return int(main(cfg).magic or 0)


_override: str | None = None
_override_any: bool = False


def set_override(broker_id: str | None, allow_inactive: bool = False) -> None:
    """A `--broker <id>` futásidejű választása (0029, 4. lépés).

    ⚠ NEM a configba: ha a motor egy mentésnél kiírná az `active_broker`-t, a
    következő indításkor a FELÜLET motorja is erre a brókerre állna át.

    `allow_inactive=True`: egy KIKAPCSOLT (`"active": false`) bróker is választható
    — CSAK tesztnek és kutató-eszköznek, ami egy adott bróker ADATÁN akar futni
    (pl. a tesztek az ActivTrades-adatra rögzítve, akkor is, ha épp a RoboForex a
    főszámla). A motor (`--broker`) ezt NEM használja: kikapcsolt brókeren motor
    nem indulhat."""
    global _override, _override_any
    _override = broker_id or None
    _override_any = bool(allow_inactive and broker_id)


def active(cfg: dict | None) -> BrokerProfile:
    """Az aktív profil: a `--broker` felülírás, az `active_broker`, különben az
    első. Ismeretlen `--broker` azonosítóra ValueError — csendben NEM esünk
    vissza az otthoni brókerre (egy második motor azzal az otthoni számlán
    kereskedne)."""
    ps = all_profiles(cfg) if _override_any else profiles(cfg)
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
    for d in (nyers or []):
        if not isinstance(d, dict):
            continue
        tr = d.get("trading")
        if tr is None:
            continue
        if not isinstance(tr, dict):
            hibak.append(f"{d.get('id', '?')}: a 'trading' blokk nem objektum")
            continue
        ism = sorted(k for k in tr if k not in BROKER_TRADING_KEYS and not k.startswith("_"))
        if ism:
            hibak.append(f"{d.get('id', '?')}: a 'trading' blokkban nem számlánként "
                         f"állítható kulcs: {', '.join(ism)} (csak: "
                         f"{', '.join(BROKER_TRADING_KEYS)})")
        for k in BROKER_TRADING_KEYS:
            if k in tr:
                try:
                    if float(tr[k]) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    hibak.append(f"{d.get('id', '?')}: trading.{k} érvénytelen: {tr[k]!r}")
    if nyers is not None:
        dl = [d for d in nyers if isinstance(d, dict)]
        if dl and not any(is_active(d) for d in dl):
            hibak.append("minden bróker ki van kapcsolva (active: false) — "
                         "a főszámla/első bróker fut")
        fok = [str(d.get("id", "?")) for d in dl if bool(d.get("main", False))]
        if len(fok) > 1:
            hibak.append(f"több főszámla is be van jelölve ({', '.join(fok)}) — "
                         f"az első aktív számít")
    want = (cfg or {}).get("active_broker")
    if want and want not in [p.id for p in profiles(cfg)]:
        hibak.append(f"az active_broker ('{want}') nincs az aktív profilok között")
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
# ⚠ A KÖTÉS-MÓD IS (0031, 2026-09-30): nem-otthoni brókernél MINDEN stratégia
# alapból CSAK JELEZ (`{"*": "signal"}`, core/trade_mode.WILDCARD). Közösen a
# RoboForex motor az otthoni módot látta, és ahol az hiányzott, VALÓDI kötést
# próbált nyitni (AUDCHF SELL 0,09 lot — csak a terminál AutoTrading-tiltása
# állította meg). A valódi kötés egy új brókeren KIFEJEZETT választás.
BROKER_INTENT_DEFAULTS = {"run_state": {}, "enabled": False,
                          "strategy_mode": {"*": "signal"}}
OVERLAY_KEY = "_broker_overlay"


def overlay_pairs(cfg: dict, profile: BrokerProfile) -> dict:
    """A nem-alap bróker értékei (instrumentum + szándék) a pár alapkulcsaira
    (helyben). Az alap-értékek gazdájánál (`base`) NEM csinál semmit. Visszaad: a cfg.

    A betöltött értékről PILLANATKÉP készül: a mentés ehhez hasonlít, így a
    helyben módosított (pl. `run_state[...] = "live"`) érték is a bróker
    blokkjába kerül."""
    if profile is None or profile.base or not isinstance(cfg, dict):
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


# ── SZÁMLÁNKÉNTI KOCKÁZATI BEÁLLÍTÁSOK (0029, 6a) ──────────────────────────
# A slot-keret, a kockázat % és a napi limit MINDEN motorban a saját számlájára
# hat (saját egyenleg, saját P&L, saját slot-nyilvántartás) — de az ÉRTÉKEK
# eddig közösek voltak. Egy kisebb számlán kevesebb slot / kisebb limit kell.
# A bróker blokkjába írt `trading` ugyanúgy felülír, mint a pár-értékek, és a
# mentés ugyanúgy visszaállít: a futás közbeni módosítás (slot ▲▼, limit) a
# bróker SAJÁT blokkjába kerül, a közös `trading` érintetlen marad.
BROKER_TRADING_KEYS = ("max_open_slots", "account_risk_pct",
                       "daily_loss_limit_usd", "daily_loss_limit_pct")
TRADING_OVERLAY_KEY = "_broker_trading_overlay"


def overlay_trading(cfg: dict, profile: BrokerProfile) -> dict:
    """Az aktív számla saját `trading` értékei a közös fölé (helyben). Üres
    blokknál (pl. egy brókernél) nem csinál semmit. Visszaad: a cfg."""
    if profile is None or not profile.trading or not isinstance(cfg, dict):
        return cfg
    tr = cfg.setdefault("trading", {})
    orig, hianyzott = {}, []
    for k, v in profile.trading.items():
        if k in tr:
            orig[k] = tr[k]
        else:
            hianyzott.append(k)
        tr[k] = copy.deepcopy(v)
    cfg[TRADING_OVERLAY_KEY] = {"id": profile.id,
                                "applied": copy.deepcopy(profile.trading),
                                "orig": orig, "missing": hianyzott}
    return cfg


def effective_trading(cfg: dict, profile: BrokerProfile) -> dict:
    """Egy (akár NEM aktív) számla érvényes `trading` beállítása — a felület a
    többi bróker limitjéhez használja. A cfg-t nem módosítja."""
    alap = dict((cfg or {}).get("trading") or {})
    ov = (cfg or {}).get(TRADING_OVERLAY_KEY)
    if isinstance(ov, dict):          # az aktív felülírását előbb visszavesszük
        for k in (ov.get("applied") or {}):
            if k in (ov.get("orig") or {}):
                alap[k] = ov["orig"][k]
            else:
                alap.pop(k, None)
    alap.update(getattr(profile, "trading", None) or {})
    return alap


def _restore_trading(data: dict) -> None:
    ov = data.pop(TRADING_OVERLAY_KEY, None)
    if not isinstance(ov, dict):
        return
    pid = ov.get("id")
    tr = data.get("trading")
    if not isinstance(tr, dict):
        return
    # a bróker saját blokkja: a `brokers` listában, régi configban a `broker`
    lista = data.get("brokers")
    blokk = None
    if isinstance(lista, list):
        blokk = next((d for d in lista if isinstance(d, dict)
                      and str(d.get("id") or "") == str(pid)), None)
    if blokk is None and isinstance(data.get("broker"), dict):
        blokk = data["broker"]
    for k, betoltott in (ov.get("applied") or {}).items():
        if k in tr and tr[k] != betoltott and blokk is not None:   # futás közben módosult
            blokk.setdefault("trading", {})[k] = tr[k]
        if k in (ov.get("orig") or {}):
            tr[k] = ov["orig"][k]
        elif k in (ov.get("missing") or []):
            tr.pop(k, None)


def restore_for_save(data: dict) -> dict:
    """Kiírás előtt (helyben): az otthoni értékek vissza, a futás közbeni
    módosítás a bróker SAJÁT blokkjába. A rejtett kulcs eltűnik."""
    if not isinstance(data, dict):
        return data
    _restore_trading(data)
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
    # ⚠ FUTÁS KÖZBEN FELVETT PÁR (2026-10-13, BRENT). A fenti ciklus csak a
    # BETÖLTÉSKOR már létező párokat ismeri (`applied`) — egy új instrumentum
    # Play-állapota és kötés-módja így a pár ALAPKULCSAIBA került, ami a lista
    # első brókeréé. Újraindítás után a futó bróker motorja a párt LEÁLLÍTOTTNAK
    # látta volna (a saját blokkja üres), az alap-bróker pedig a más brókeren
    # nyomott Play-t örökölte volna — a bróker-szivárgás hibaosztálya. Ezért:
    #   • a SZÁNDÉK (run_state, strategy_mode) ÁTKERÜL a bróker blokkjába;
    #   • az `enabled` és az instrumentum-értékek (pont-méret, költség) oda is
    #     MÁSOLÓDNAK, az alapban is maradnak (más forrás nincs rájuk).
    for sym, pc in pairs.items():
        if sym in (ov.get("applied") or {}) or not isinstance(pc, dict):
            continue
        blokk = pc.setdefault("brokers", {}).setdefault(pid, {})
        for k in ("run_state", "strategy_mode"):
            if k in pc:
                blokk[k] = pc.pop(k)
        for k in ("enabled",) + BROKER_PAIR_KEYS:
            if k in pc and k not in blokk:
                blokk[k] = copy.deepcopy(pc[k])
    return data


def write_target(pair_cfg: dict, profile: BrokerProfile) -> dict:
    """Hova írjon egy bróker-függő értéket egy eszköz (pl. refresh_costs):
    az alap-értékek gazdájánál a pár maga, különben a `brokers.<id>` blokkja."""
    if profile is None or profile.base:
        return pair_cfg
    return pair_cfg.setdefault("brokers", {}).setdefault(profile.id, {})
