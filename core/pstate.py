"""A futásidejű POZÍCIÓ-REKORD alakja — EGY gazdával (v3.57.0).

A `trading.live_trader.position_state` egy `{ticket: {...}}` szótár, amit a MOTOR
és a FELÜLET is ír. Ez a modul azt mondja meg, **mi van benne** — és mivel tiszta
(nincs MT5, nincs tkinter, csak számok és szótárak), egy sorban tesztelhető.

⚠ A LELET (2026-09-08). A rekordot **öt helyen** hoztuk létre, két modulban, és
mindenhol `setdefault`-tal — vagyis **aki előbb ér oda, az nyer**, a többi már
nem javít rajta. Az öt alak nem is egyezett:

    live_trader:2201  (no-trade ág)   6 kulcs, original_sl = pos.sl
    live_trader:2422  (process_pair)  6 kulcs, original_sl = pos.sl
    live_trader:3553  (csomag-stop)   {}  ← ÜRES szótár
    gui:5796          (kézi BE)       5 kulcs, entry_atr nélkül
    gui:5849          _DEFAULT_PSTATE 5 kulcs, original_sl = 0.0  ← !!

És volt elérhető út, ahol a FELÜLET nyer: a `process_pair` csak `LIVE`/`CLOSING`
páron fut, tehát egy STOPPED páron nyitva maradt (vagy örökbefogadott) pozíciónál
a Pozíciók fül trailing-kapcsolója hozza létre a rekordot — `original_sl = 0.0`-val.
A motor `setdefault`-ja utána MÁR TALÁL bejegyzést, tehát a valódi stopot soha nem
írja bele: az a pozíció élete végéig hibás 1 R-rel fut.

⚠ ÉS A GYÖKÉR: a `0.0` KÉT dolgot jelentett egyszerre — „nincs stop" és „nem
tudjuk". Itt a kettő szétválik: az ISMERETLEN az `None`, és a `normalise_sl` a
0/negatív/None értéket mind `None`-ra képezi. Amit nem tudunk, azt nem
találjuk ki (lásd `risk_reduction.breakeven_trigger`: inkább nincs breakeven,
mint hamis küszöb).

⚠ A JAVÍTÁS LÉNYEGE nem az egységes alak, hanem hogy az ISMERETLEN EREDETI STOP
KÉSŐBB PÓTOLHATÓ. Az `ensure()` nem csak létrehoz: ha a rekord már megvan, de az
`original_sl` ismeretlen, és a hívó tud egy érvényes stopot, **beírja**. Így
mindegy, ki ér oda előbb — a felület kapcsolója nem tudja megmérgezni a motor
kockázat-számítását.
"""
from __future__ import annotations

# A rekord TELJES alakja. Ami itt nincs, az futásidejű JELÖLŐ (`rr_reduced`,
# `runner_mode`, `rr_thirds1`, `be_hirdetve`, `sf_mode`…): azoknál a HIÁNY maga a
# jelentés („még nem történt meg"), és `.get()`-tel olvasódnak.
DEFAULTS: dict = {
    # Az EREDETI (nyitáskori) stop ÁRA — ebből lesz az 1 R. `None` = NEM TUDHATÓ.
    "original_sl":      None,
    # A Pozíciók fül kézi kapcsolója.
    "trailing_enabled": True,
    # Megtörtént-e a breakeven (a slot felszabadítás és a trailing padlója).
    "be_done":          False,
    # Kézi követés-távolság PONTBAN (None = az optimalizált ATR-szorzó).
    "trail_points":     None,
    # Húzott-e már a trailing (a kijelzés jelöli).
    "trail_moved":      False,
    # A BELÉPÉSKORI ATR — a trailing ezzel skálázódik (0.0 = még ismeretlen).
    "entry_atr":        0.0,
    # A legutóbb LÁTOTT stop (a stop-mozgás felismeréséhez). None = még nem láttuk.
    "last_sl":          None,
}

FIELDS = tuple(DEFAULTS)

_UNSET = object()


def normalise_sl(sl) -> "float | None":
    """A stop ÁRA, vagy `None`, ha nincs / nem tudható.

    ⚠ Az MT5 a stop NÉLKÜLI pozíciónak `sl = 0.0`-t ad, nem `None`-t. A `0.0`
    ÁRKÉNT értelmetlen, kivonásban viszont működik — ebből lett a „nyitóárral
    egyenlő 1 R", ami csendben soha el nem sülő küszöböt adott.
    """
    try:
        v = float(sl)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def new(original_sl=None, be_done: bool = False) -> dict:
    """Egy ÚJ, teljes pozíció-rekord. Az `original_sl` 0/None → ismeretlen."""
    rec = dict(DEFAULTS)
    rec["original_sl"] = normalise_sl(original_sl)
    rec["be_done"] = bool(be_done)
    return rec


def ensure(store: dict, ticket: int, *, original_sl=_UNSET,
           be_done: bool = False) -> dict:
    """A ticket rekordja — létrehozva VAGY kiegészítve. Ez az EGYETLEN belépő.

    Három dolgot csinál, ebben a sorrendben:

      1. ha még nincs rekord, teljes alakot hoz létre (`be_done` csak ITT számít,
         mint eddig a `setdefault`-nál — meglévő rekord jelölését nem írja át);
      2. ha van, a HIÁNYZÓ mezőket feltölti az alapértékkel (régi, csonka
         rekordok — pl. a csomag-stop üres szótára — így válnak teljessé);
      3. ⚠ ha az `original_sl` ISMERETLEN, de a hívó tud egy érvényeset, BEÍRJA.
         Ez a lelet javítása: a felület által létrehozott rekord így nem zárja ki
         örökre a motor valódi stop-adatát.

    Az ismert `original_sl`-t SOHA nem írja felül: a stop menet közben elmozdul
    (BE, trailing, kézi húzás), és az 1 R a NYITÁSKORI kockázat.
    """
    rec = store.get(ticket)
    if rec is None:
        rec = new(be_done=be_done)
        store[ticket] = rec
    else:
        for k, v in DEFAULTS.items():
            rec.setdefault(k, v)
    if original_sl is not _UNSET and rec.get("original_sl") is None:
        rec["original_sl"] = normalise_sl(original_sl)
    return rec


def original_sl(rec: "dict | None", current_sl=None) -> "float | None":
    """Az EREDETI stop ára — a rekordból, különben a MOSTANIBÓL, különben `None`.

    A mostani stop csak KÖZELÍTÉS (a BE/trailing már elmozdíthatta), de jobb, mint
    a semmi: a régi kód is így esett vissza. Az a fontos, hogy a motor és a
    felület UGYANAZT a közelítést használja — különben a sor más R-t mutatna,
    mint amivel a motor dolgozik.
    """
    # ⚠ A TÁROLT értéket is normalizáljuk, nem csak a tartalékot. Az `ensure()`
    # már íráskor `None`-ra képezi a 0-t, DE a memóriában maradhat RÉGI rekord (a
    # motor újraindítás nélkül is fut hetekig), és egy `{"original_sl": 0.0}`
    # bejegyzésen enélkül visszajönne a hiba, amit ez a modul javít:
    # `abs(nyitóár − 0) = nyitóár`, azaz egy magával az árral egyenlő „1 R".
    osl = normalise_sl(rec.get("original_sl")) if rec else None
    if osl is None:
        osl = normalise_sl(current_sl)
    return osl


def one_r_price(price_open: float, rec: "dict | None", current_sl=None) -> float:
    """1 R ÁRBAN (a nyitáskori stop-távolság), vagy **0.0**, ha nem tudható.

    A `0.0` a hívóknál KIHAGYÁST jelent, nem nulla kockázatot:
      * `risk_reduction.breakeven_trigger` → `None` (nincs BE) + naplósor,
      * a Felező/Pajzs 1R-triggere → `if one_r > 0`,
      * a Harmados szintjei → `if _risk > 0`,
      * a pozícióépítés R-létrája → nincs R-alapú szint.
    """
    osl = original_sl(rec, current_sl)
    if osl is None:
        return 0.0
    return abs(float(price_open) - float(osl))
