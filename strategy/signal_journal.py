"""Perzisztens BELÉPŐ-/JELZÉS-NAPLÓ a vizualizációhoz (per szimbólum + stratégia).

MIÉRT KELL. A chart belépő-jelölőit ma a `visual_objects()` **újraszámolja** a
betöltött adatablakból (M1 ~1 nap). A régebbi jelölők csak azért maradnak a
charton, mert az MQL indikátor **sosem töröl** (upsert) — tehát a megőrzésük
MELLÉKHATÁS, nem tulajdonság. MT5-újraindításnál, az indikátor újracsatolásánál
vagy egy hosszabb leállás után az egész előzmény eltűnik, és nincs mód
visszahozni: az ablakon kívüli jelzés sehol nem létezik.

A NAPLÓ NEM VÁLTJA LE AZ ÚJRASZÁMOLÁST. A viz továbbra is az aktuális ablakon
számol (ott marad a mai viz↔backtest paritás), a napló csak az **ablakon kívüli
múltat** tölti vissza. Két forrás, éles határral:

    [ ─────── napló (múlt) ─────── |ablak| ── újraszámolás (jelen) ── ]

⚠ MIÉRT ÍGY, ÉS NEM „a napló az egyetlen igazság": a naplót az ÉLŐ motor írja,
azokkal a paraméterekkel, amik AKKOR érvényesek voltak. Egy hangolás után a mai
újraszámolás **jogosan** más jelölőket adna ugyanarra a napra — a napló viszont
azt őrzi, amit a bot TÉNYLEGESEN látott. Mindkettő igaz, csak más kérdésre
válasz. Ezért minden rekord viszi a paraméter-**ujjlenyomatát** (`fp`): az
átfedő szakasz csak AZONOS ujjlenyomat mellett hasonlítható össze, és ott az
eltérés valódi lelet (pontosan az a néma osztály, ami a warmup-mélységnél és a
viz-sávnál is pénzbe került).

A REKORD abból áll, amiből a jelölő **újrarajzolható** — nem a kész rajzsorból.
Így a `visual.entry_marks()` ugyanabból a rekordból ugyanazt a sort állítja elő
a naplóból is, az újraszámolásból is; nem tud elcsúszni a kettő.

⚠ A BACKTEST NEM ÍR IDE (`live` kapcsoló, alap: ki). A backtest ablakonként
újrafuttatható, és ha írna, összekeveredne a valós élő előzménnyel — a napló
attól napló, hogy az van benne, ami megtörtént.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

DIR = Path(__file__).resolve().parents[1] / "data" / "signal_journal"

# Megtartás. A napló KIJELZÉST szolgál, nem auditot: a chart úgysem tud
# korlátlan objektumot kezelni, és a régi jelölő értéke gyorsan nullához tart.
# `0` = ne takaríts (mint az örökbefogadás-nyilvántartásnál).
KEEP_RECORDS = 800
KEEP_DAYS = 60

# ⚠ Amennyit a CHARTRA visszatöltünk — ez NEM ugyanaz, mint amennyit tárolunk.
# A viz-fájl minden körben TELJESEN újraíródik (`mt5_visual.write_lines`
# pillanatkép + az indikátor újraparzolja), és egy belépő ÖT rajz-objektum: 800
# jelölő 4000 sort jelentene 30 másodpercenként, minden szimbólumra. A tárolás
# olcsó (egy sor szöveg), a megjelenítés nem — ezért külön korlát.
SHOW_RECORDS = 200

_lock = threading.Lock()
# fájl → a MÁR NAPLÓZOTT időbélyegek. Enélkül minden viz-körben (30 mp) újra
# kellene olvasni a fájlt, hogy tudjuk, mi az új — a viz-szál pedig a GIL-t
# fogná. Lásd a kijelzés-út mély warmup tanulságát.
_seen: dict[str, set] = {}

_FIELDS = ("t", "d", "e", "sl", "tp", "lab", "fp", "skip")


def path_of(symbol: str, strategy: str) -> Path:
    """A napló fájlja. Szimbólum ÉS stratégia szerint külön — egy chartra több
    stratégia rajza kerülhet, és a takarítás/összehasonlítás is stratégiánként
    értelmes."""
    safe = "".join(c if (c.isalnum() or c in "._-") else "_"
                   for c in f"{symbol}__{strategy}")
    return DIR / f"{safe}.jsonl"


def fingerprint(params: dict) -> str:
    """A paraméter-készlet rövid ujjlenyomata.

    ⚠ MINDEN paraméter beleszámít, nem csak a jel-paraméterek: a jelölő SL/TP
    vonalai végrehajtási kulcsokból (`atr_period`, `sl_method`) is származnak,
    tehát azok változása is MÁS rajzot ad. Ha csak a jel-paramétereket vennénk,
    az összehasonlítás hamis egyezést mutatna.
    """
    try:
        blob = json.dumps({k: params[k] for k in sorted(params)},
                          sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        # A paraméterek elvileg JSON-barát skalárok; ha mégsem, az ujjlenyomat
        # NE dobjon — inkább legyen „ismeretlen", mint hogy a naplózás elvesszen.
        log.debug("ujjlenyomat: a paraméterek nem sorosíthatók", exc_info=True)
        return "?"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def _norm(r: dict) -> "dict | None":
    """Egy rekord ellenőrzése és szűkítése a tárolt mezőkre."""
    try:
        t = int(r["t"])
        d = str(r["d"]).upper()
        if d not in ("BUY", "SELL") or t <= 0:
            return None
        out = {"t": t, "d": d, "e": round(float(r["e"]), 8)}
        for k in ("sl", "tp"):
            if r.get(k) is not None:
                out[k] = round(float(r[k]), 8)
        if r.get("lab"):
            out["lab"] = str(r["lab"])[:64]
        if r.get("fp"):
            out["fp"] = str(r["fp"])[:16]
        # ⚠ A KIMARADT jelzés jelölése (`visual.mark_blocked`) — enélkül az
        # ablakon KÍVÜLI múlt megint úgy nézne ki, mintha minden jelzésből
        # kötés lett volna. A döntés a jelzés pillanatában VÉGLEGES (azt nézi,
        # nyitva volt-e akkor pozíció), tehát utólag nem kell frissíteni.
        if r.get("skip"):
            out["skip"] = 1
        return out
    except (KeyError, TypeError, ValueError):
        # Egy hibás rekord ne vigye el a többit — de a naplóban maradjon nyoma.
        log.debug("napló: hibás rekord kihagyva: %r", r)
        return None


def _read(p: Path) -> list:
    """A fájl beolvasása. Sérült SOR csak önmagát viszi el (a JSONL épp ezért
    jobb itt egyetlen nagy JSON-nál: egy félbeszakadt írás egy sort ront el,
    nem az egész előzményt)."""
    out = []
    if not p.exists():
        return out
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = _norm(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if r is not None:
                    out.append(r)
    except OSError as ex:
        log.warning("napló: a(z) %s nem olvasható (%s) — az ablakon KÍVÜLI "
                    "jelölők ezúttal kimaradnak a chartról", p.name, ex)
        return []
    out.sort(key=lambda r: r["t"])
    return out


def load(symbol: str, strategy: str, before_t: "int | None" = None,
         limit: int = KEEP_RECORDS) -> list:
    """A napló rekordjai időrendben.

    `before_t`: csak az ennél RÉGEBBI jelzések (ez a viz alap-használata — az
    ablakon belül az újraszámolás az igazság). `limit`: a legutolsó N rekord.
    """
    with _lock:
        rows = _read(path_of(symbol, strategy))
    if before_t is not None:
        rows = [r for r in rows if r["t"] < int(before_t)]
    return rows[-int(limit):] if limit and limit > 0 else rows


def append(symbol: str, strategy: str, records: list, fp: str = "") -> int:
    """ÚJ jelzések hozzáfűzése. Visszaadja, hány rekord került be ténylegesen.

    Idempotens: ugyanaz az időbélyeg csak egyszer kerül be. Ez lényeges, mert a
    viz-szál 30 másodpercenként ugyanazt az ablakot számolja újra — dedup nélkül
    a napló percek alatt megtelne ugyanannak a jelzésnek a másolataival.
    """
    if not records:
        return 0
    p = path_of(symbol, strategy)
    key = str(p)
    with _lock:
        seen = _seen.get(key)
        if seen is None:
            seen = {r["t"] for r in _read(p)}
            _seen[key] = seen
        fresh = []
        for r in records:
            n = _norm({**r, "fp": r.get("fp") or fp})
            if n is None or n["t"] in seen:
                continue
            seen.add(n["t"])
            fresh.append(n)
        if not fresh:
            return 0
        try:
            DIR.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                for n in fresh:
                    f.write(json.dumps({k: n[k] for k in _FIELDS if k in n},
                                       ensure_ascii=False) + "\n")
        except OSError as ex:
            # ⚠ NEM néma: ha az írás elbukik, a jelzés csak a MEMÓRIÁBAN van
            # (a `seen`-ben már benne), tehát a következő körben sem próbáljuk
            # újra — a chart előzménye csendben hiányos lenne.
            _seen.pop(key, None)          # a bejegyzés ne maradjon „elintézve"
            log.error("napló: a(z) %s nem írható (%s) — %d jelzés NEM kerül be "
                      "az előzménybe", p.name, ex, len(fresh))
            return 0
    return len(fresh)


def prune(symbol: str, strategy: str, keep_records: int = KEEP_RECORDS,
          keep_days: int = KEEP_DAYS, now_t: "int | None" = None) -> int:
    """Takarítás: a legutolsó `keep_records` rekord ÉS a `keep_days`-nél nem
    régebbiek maradnak. `0` bármelyik korlátnál = az a korlát nem érvényes.
    Visszaadja a törölt rekordok számát."""
    import time as _t
    p = path_of(symbol, strategy)
    with _lock:
        rows = _read(p)
        if not rows:
            return 0
        keep = rows
        if keep_days and keep_days > 0:
            cut = int(now_t if now_t is not None else _t.time()) - keep_days * 86400
            keep = [r for r in keep if r["t"] >= cut]
        if keep_records and keep_records > 0:
            keep = keep[-int(keep_records):]
        if len(keep) == len(rows):
            return 0
        # ⚠ WINDOWS: a `replace` MEGTAGADHATÓ (`WinError 5`), ha a célfájlt épp
        # nyitva tartja valaki — egy másik szál olvasása, egy víruskereső, vagy
        # egy megnyitott szerkesztő. Megtörtént 2026-08-25-én. Egyetlen
        # próbálkozásnál a takarítás kimarad, és a fájl a korlát fölé nő.
        import time as _t
        _hiba = None
        for _kiserlet in range(3):
            try:
                tmp = p.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for n in keep:
                        f.write(json.dumps({k: n[k] for k in _FIELDS if k in n},
                                           ensure_ascii=False) + "\n")
                tmp.replace(p)                 # atomikus csere
                _hiba = None
                break
            except OSError as ex:
                _hiba = ex
                _t.sleep(0.2)
        if _hiba is not None:
            # ⚠ `debug`, nem `warning`: a takarítás BEST-EFFORT, és a következő
            # körben úgyis újrapróbáljuk. Egy 30 másodpercenként ismétlődő
            # figyelmeztetés elfedné a valódi leleteket.
            log.debug("napló: a(z) %s most nem takarítható (%s) — a következő "
                      "körben újrapróbáljuk", p.name, _hiba)
            return 0
        _seen[str(p)] = {r["t"] for r in keep}
    return len(rows) - len(keep)


def compare(symbol: str, strategy: str, records: list, fp: str,
            price_tol: float = 0.0) -> dict:
    """A napló és az ÚJRASZÁMOLÁS összevetése az ÁTFEDŐ szakaszon.

    Ez a napló legfontosabb mellékterméke: ha az élő motor mást írt, mint amit a
    mai újraszámolás ugyanarra az időre ad, az **néma eltérés** — a projektben
    ez az osztály okozta a warmup-mélység és a viz-sáv leletét is.

    ⚠ CSAK AZONOS `fp` (paraméter-ujjlenyomat) mellett van értelme: hangolás után
    a különbség JOGOS, nem hiba. Az eltérő ujjlenyomatú rekordokat kihagyjuk.

    ⚠ `price_tol`: ENNÉL KISEBB ÁR-ELTÉRÉS NEM SZÁMÍT. Az SL/TP egy CSÚSZÓ
    ablakon számolt indikátorból (ATR, Bollinger) jön; ahogy az ablak arrébb
    lép, az érték a sokadik tizedesjegyen ingadozik. Mérve (EURCHF/BSB,
    2026-08-25): napló `sl=0.92402994`, újraszámolás `0.9240299443…` — a
    különbség a NYOLCADIK tizedesen, vagyis sokkal kisebb, mint egy ártick.
    Ilyet jelezni ZAJ, és a zajban elvész a valódi lelet: a hívó ezért a
    `point_size` felét adja át. `0` = pontos egyezés (a régi viselkedés).

    Visszaad: `{"osszevetve", "egyezik", "csak_naploban", "csak_szamolt",
    "elter"}` — az utolsó három időbélyeg-lista.
    """
    if not records:
        return {"osszevetve": 0, "egyezik": 0, "csak_naploban": [],
                "csak_szamolt": [], "elter": []}
    lo = min(int(r["t"]) for r in records)
    hi = max(int(r["t"]) for r in records)
    jr = {r["t"]: r for r in load(symbol, strategy, limit=0)
          if lo <= r["t"] <= hi and r.get("fp") == fp}
    cr = {}
    for r in records:
        n = _norm({**r, "fp": r.get("fp") or fp})
        if n is not None:
            cr[n["t"]] = n
    def _egyezik(a: dict, b: dict) -> bool:
        if a.get("d") != b.get("d"):
            return False                     # az IRÁNY sosem lehet „közel"
        for k in ("e", "sl", "tp"):
            x, y = a.get(k), b.get(k)
            if x is None or y is None:
                if x != y:
                    return False
                continue
            if abs(float(x) - float(y)) > price_tol:
                return False
        return True

    same, diff = 0, []
    for t in set(jr) & set(cr):
        if _egyezik(jr[t], cr[t]):
            same += 1
        else:
            diff.append(t)
    return {"osszevetve": len(set(jr) & set(cr)), "egyezik": same,
            "csak_naploban": sorted(set(jr) - set(cr)),
            "csak_szamolt": sorted(set(cr) - set(jr)),
            "elter": sorted(diff)}
