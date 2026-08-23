"""Nyitva van-e a piac EZEN az instrumentumon? — a tick korából.

⚠ A KÉRDÉS (a felhasználótól, 2026-08-23): „Ha egy adott instrumentum »zárva«
van vagy a bróker épp zárva van, azt látjuk valahol?" Nem: a programnak eddig
nem volt ilyen fogalma. Egy zárt piacú pár pontosan úgy néz ki, mint egy nyitott,
amelyik épp nem talál belépőt — és a leggyakoribb néma kérdés (*miért nem csinál
semmit ez a pár?*) megválaszolatlan marad.

⚠ AMI NEM MŰKÖDIK — mérve (2026-08-23, vasárnap, zárt piac):
  • a `symbol_info().trade_mode` MIND a 10 páron `FULL`. Az JOGOSULTSÁG
    (kereskedhető-e egyáltalán), nem session-állapot. Aki erre épít, zárt piacon
    is „nyitva"-t kap.
  • a Python MT5-modul (5.0.5735) NEM adja a menetrendet: nincs benne
    `symbol_info_session_quote/trade`, csak `symbol_info` és `symbol_info_tick`.
    A hivatalos nyitvatartás tehát nem lekérdezhető.

⚠ AMI MŰKÖDIK: a TICK KORA. Ugyanabban a mérésben 9 pár utolsó tickje ~36 órás
volt (pénteki zárás), a BTCUSD-é friss (kripto, hétvégén is megy).

A küszöb MÉRT, nem tippelt. A meglévő M1 előzményen (60 000 gyertya páronként) a
gyertyák közti szünet 99,9%-ban 1–2 perc; 5 percnél hosszabb szünet az esetek
0,01–0,08%-ában fordul elő — és azok maguk a zárások. 5 perc néma csend nyitott
piacon tehát már rendellenes.

⚠ ÉS A CSAPDA, amibe a projekt már beleszaladt: a tick időbélyege SZERVER
időben van. Naivan `time.time() - tick.time`-ot számolva a BTCUSD tickje „a
jövőben" van −120 perccel — az a bróker +2 órás eltolása. Ezért a PERZISZTÁLT
eltolást használjuk (`mt5_connector._load_offset`, egész órára kvantálva,
DST-védetten), nem egy friss mérést: zárt hétvégén ugyanis a friss mérés maga is
egy elavult tickből jönne, és pont akkor csúszna el, amikor számít.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

OPEN = "open"
CLOSED = "closed"
UNKNOWN = "unknown"

# ⚠ 5 perc — az M1 előzményből mérve (lásd a modul fejlécét). Nem „kerek szám":
# a nyitott session gyertya-szünetei 99,9%-ban 1–2 percesek.
MAX_AGE_SEC = 300

LABEL = {OPEN: "", CLOSED: "zárva", UNKNOWN: "?"}


def _server_now() -> "float | None":
    """A BRÓKER faliórája epoch-ként — a perzisztált eltolásból.

    `None`, ha még sosem mértünk eltolást (ilyenkor nem TALÁLGATUNK: a hívó
    `UNKNOWN`-t kap, nem egy kitalált „zárva")."""
    from datetime import datetime, timezone
    try:
        from core.mt5_connector import _load_offset
        off = _load_offset()
    except Exception:
        off = None
    if off is None:
        return None
    return datetime.now(timezone.utc).timestamp() + float(off)


def info_of(symbol: str, max_age_sec: int = MAX_AGE_SEC) -> dict:
    """`{state, age_sec, tick_time}` egy instrumentumra.

    `age_sec` a bróker órája szerinti kor (negatív nem lehet — az óra-eltolás
    apró pontatlanságát 0-ra vágjuk, hogy a felületen ne villogjon „-3 mp").
    """
    out = {"state": UNKNOWN, "age_sec": None, "tick_time": None}
    now = _server_now()
    if now is None:
        return out
    try:
        import MetaTrader5 as mt5
        from core.mt5_connector import MT5_LOCK
        with MT5_LOCK:
            t = mt5.symbol_info_tick(symbol)
    except Exception as ex:
        log.debug("tick-lekérdezés hiba (%s): %s", symbol, ex)
        return out
    if not t or not getattr(t, "time", 0):
        return out
    age = max(0.0, now - float(t.time))
    out["tick_time"] = float(t.time)
    out["age_sec"] = age
    out["state"] = CLOSED if age > max_age_sec else OPEN
    return out


def from_tick(tick_time, max_age_sec: int = MAX_AGE_SEC) -> dict:
    """Ugyanaz, mint az `info_of`, de egy MÁR LEKÉRDEZETT tick idejéből.

    ⚠ Ezt használja a felület: az ár-frissítő háttérszál úgyis lekéri a ticket,
    tehát a piac-állapot NEM kerül egyetlen extra MT5-hívásba sem. Ugyanez a fő
    szálon körönként 10-30 hívás volna — pont az a terhelés, amit a
    fagyás-watchdog jelez."""
    out = {"state": UNKNOWN, "age_sec": None, "tick_time": None}
    now = _server_now()
    if now is None or not tick_time:
        return out
    age = max(0.0, now - float(tick_time))
    out["tick_time"] = float(tick_time)
    out["age_sec"] = age
    out["state"] = CLOSED if age > max_age_sec else OPEN
    return out


def state_of(symbol: str, max_age_sec: int = MAX_AGE_SEC) -> str:
    return info_of(symbol, max_age_sec)["state"]


def states_of(symbols, max_age_sec: int = MAX_AGE_SEC) -> dict:
    """`{szimbólum: info}` — a felület KÖRÖNKÉNT EGYSZER kérdezi le, nem soronként."""
    return {s: info_of(s, max_age_sec) for s in (symbols or [])}


def summary(states: dict) -> str:
    """Rövid összegzés a fejlécbe: `""` (minden nyitva) vagy `"Piac: 9/10 zárva"`.

    ⚠ Nyitott piacon ÜRES — nincs mit mondani. A jelzés akkor érték, amikor
    eltér a megszokottól; egy állandó „minden nyitva" felirat zaj volna."""
    vals = [v.get("state") for v in (states or {}).values()]
    n = len(vals)
    closed = sum(1 for v in vals if v == CLOSED)
    unknown = sum(1 for v in vals if v == UNKNOWN)
    if not n or (not closed and not unknown):
        return ""
    if closed == n:
        return "Piac: MINDEN instrumentum zárva"
    parts = []
    if closed:
        parts.append(f"{closed}/{n} zárva")
    if unknown:
        parts.append(f"{unknown} ismeretlen")
    return "Piac: " + ", ".join(parts)


def tip_of(info: dict) -> str:
    """Buborék-szöveg a cellához: MIÉRT halvány az ár."""
    st = (info or {}).get("state")
    if st == OPEN:
        return ""
    if st == UNKNOWN:
        return ("A piac állapota ismeretlen (nincs tick vagy szerver-eltolás). "
                "Az ár lehet elavult.")
    age = (info or {}).get("age_sec") or 0.0
    when = ""
    t = (info or {}).get("tick_time")
    if t:
        from datetime import datetime
        when = datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
    h, m = int(age // 3600), int((age % 3600) // 60)
    span = f"{h} óra {m} perce" if h else f"{m} perce"
    return (f"A piac ZÁRVA — az utolsó árajánlat {span}"
            + (f" ({when}, bróker-idő)." if when else ".")
            + " Amíg zárva van, nem születhet belépő.")
