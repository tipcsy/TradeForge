"""Látszik-e, hogy egy instrumentum piaca ZÁRVA van.

⚠ A KÉRDÉS (a felhasználótól, 2026-08-23): „Ha egy adott instrumentum »zárva«
van vagy a bróker épp zárva van, azt látjuk valahol?" Nem láttuk: a programnak
nem volt ilyen fogalma. Egy zárt piacú pár pontosan úgy nézett ki, mint egy
nyitott, amelyik épp nem talál belépőt — és a leggyakoribb néma kérdés (*miért
nem csinál semmit ez a pár?*) megválaszolatlan maradt.

⚠ A MÉRÉS, ami eldöntötte, MIRE lehet építeni (2026-08-23, vasárnap):
  • `symbol_info().trade_mode` MIND a 10 páron `FULL` — az JOGOSULTSÁG, nem
    session-állapot; zárt piacon is „nyitva"-t adna;
  • a Python MT5-modul (5.0.5735) nem adja a menetrendet (nincs
    `symbol_info_session_quote`), tehát a nyitvatartás nem kérdezhető le;
  • a TICK KORA viszont egyértelmű: 9 pár utolsó tickje ~36 órás volt, a
    BTCUSD-é friss (kripto, hétvégén is megy).

⚠ ÉS A CSAPDA: a tick időbélyege SZERVER időben van. Naiv
`time.time() - tick.time` mellett a BTCUSD tickje „a jövőben" van 120 perccel —
az a bróker +2 órás eltolása. Ezért a PERZISZTÁLT eltolást használjuk; zárt
hétvégén egy friss eltolás-mérés maga is egy elavult tickből jönne.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import market_state as ms

# ── 1. A DÖNTÉS: kor → állapot ──────────────────────────────────────────
_real_now = ms._server_now
NOW = 1_800_000_000.0
ms._server_now = lambda: NOW
try:
    check("friss tick → NYITVA", ms.from_tick(NOW - 10)["state"] == ms.OPEN)
    check("4 perces tick → még NYITVA", ms.from_tick(NOW - 240)["state"] == ms.OPEN)
    # ⚠ A KÜSZÖB MÉRT: az M1 előzményen a gyertya-szünetek 99,9%-a 1–2 perc, és
    # az 5 percnél hosszabb szünetek (0,01–0,08%) MAGUK a zárások.
    check("a küszöb 5 perc (mérve, nem tippelve)", ms.MAX_AGE_SEC == 300,
          str(ms.MAX_AGE_SEC))
    check("6 perces tick → ZÁRVA", ms.from_tick(NOW - 360)["state"] == ms.CLOSED)
    check("36 órás tick → ZÁRVA", ms.from_tick(NOW - 36 * 3600)["state"] == ms.CLOSED)
    # ⚠ Az óra-eltolás apró pontatlansága ne villogtasson „-3 mp"-et.
    check("a jövőbeli tick kora 0, nem negatív",
          ms.from_tick(NOW + 30)["age_sec"] == 0.0,
          str(ms.from_tick(NOW + 30)["age_sec"]))
    check("tick nélkül ISMERETLEN (nem 'zárva')",
          ms.from_tick(0)["state"] == ms.UNKNOWN)
finally:
    ms._server_now = _real_now

# ⚠ SZERVER-ELTOLÁS NÉLKÜL NEM TALÁLGATUNK. Enélkül minden pár „zárva" volna
# egy +2 órás brókeren — vagy fordítva, egy órákig halott pár „nyitva".
ms._server_now = lambda: None
try:
    check("eltolás nélkül ISMERETLEN, nem kitalált állapot",
          ms.from_tick(time.time())["state"] == ms.UNKNOWN)
finally:
    ms._server_now = _real_now
_src = (ROOT / "core" / "market_state.py").read_text(encoding="utf-8")
check("a PERZISZTÁLT eltolást használja (nem friss mérést)",
      "_load_offset" in _src and "server_offset_sec" not in _src)


# ── 2. AZ ÖSSZEGZÉS csak akkor beszél, ha van mit mondani ───────────────
_open = {"state": ms.OPEN}
_closed = {"state": ms.CLOSED}
check("minden nyitva → ÜRES (nincs mit mondani)",
      ms.summary({"A": _open, "B": _open}) == "",
      ms.summary({"A": _open, "B": _open}))
check("vegyes → darabszám", ms.summary({"A": _open, "B": _closed}) == "Piac: 1/2 zárva",
      ms.summary({"A": _open, "B": _closed}))
check("mind zárva → kimondja", "MINDEN" in ms.summary({"A": _closed, "B": _closed}))
check("ismeretlen is látszik",
      "ismeretlen" in ms.summary({"A": _open, "B": {"state": ms.UNKNOWN}}))
check("üres bemenet → üres", ms.summary({}) == "")

# A buborék MEGMONDJA, mióta és meddig.
ms._server_now = lambda: NOW
try:
    # ⚠ RÖVID, szándékosan. A felhasználó kérése: „ennyi elég: ZÁRVA — Bróker
    # idő: 8-22: 0:59 óta. További szöveg felesleges." Aki a szürke árra
    # rámutat, azt EGY dolog érdekli: mióta áll.
    _tip = ms.tip_of(ms.from_tick(NOW - 36 * 3600))
    check("a buborék kimondja: ZÁRVA", _tip.startswith("ZÁRVA"), _tip)
    check("...és megadja, MIKOR ÓTA (bróker idő)",
          "bróker idő" in _tip and "óta" in _tip, _tip)
    check("...és NEM magyaráz tovább", len(_tip) <= 45, f"{len(_tip)} karakter")
    check("nyitott piacon NINCS buborék", ms.tip_of(ms.from_tick(NOW - 5)) == "")
finally:
    ms._server_now = _real_now


# ── 3. A FELÜLET: halvány ár + buborék ─────────────────────────────────
from dashboard.canvas_cells import cells_for
from dashboard.theme import FG_GRAY_DIM, FG_WHITE

_row = {"symbol": "Ger40", "bid": 25443.91, "ask": 25446.0, "change_pct": 0.03,
        "digits": 2, "gates": {}, "strategies": [], "total": {}}


def _cells(state, tip="valamiért zárva"):
    d = dict(_row, session={"state": state, "age_sec": 9999, "tip": tip})
    return cells_for(d, {})


_c = _cells(ms.CLOSED)
check("zárt piacon az ÁR halvány", _c["bid"].fg == FG_GRAY_DIM, _c["bid"].fg)
check("...az ask is", _c["ask"].fg == FG_GRAY_DIM)
check("...és a változás% is", _c["change"].fg == FG_GRAY_DIM)
check("...a buborék megmondja, miért", bool(_c["bid"].tip) and bool(_c["symbol"].tip))
# ⚠ Az ÁR MEGMARAD (nem töröljük): az utolsó ismert ár információ — csak nem él.
check("az ár SZÖVEGE megmarad (az utolsó ismert ár is információ)",
      "25443" in _c["bid"].text, _c["bid"].text)

_o = _cells(ms.OPEN, tip="")
check("nyitott piacon az ár FEHÉR", _o["bid"].fg == FG_WHITE, _o["bid"].fg)
check("...és nincs buborék", not _o["bid"].tip)
check("...a változás% a saját színét kapja (zöld/piros)",
      _o["change"].fg not in (FG_GRAY_DIM,), _o["change"].fg)
# Hiányzó `session` (régi hívó) → NEM zárva, hanem a régi viselkedés.
_n = cells_for(dict(_row), {})
check("session nélkül a RÉGI viselkedés (nem 'zárva')",
      _n["bid"].fg == FG_WHITE and not _n["bid"].tip, _n["bid"].fg)


# ── 4. A BEKÖTÉS: a HÁTTÉRSZÁL számol, nem a fő szál ──────────────────
# ⚠ Ez nem stílus: páronként a fő szálon lekérdezve körönként 10-30 MT5-hívás
# menne a UI-szálra — pont az a terhelés, amit a fagyás-watchdog jelez. Az
# ár-frissítő úgyis lekéri a ticket, tehát az állapot INGYEN van.
_g = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_i = _g.find("def _refresh_price")
_blk = _g[_i:_i + 2500]
check("az ár-frissítő (háttérszál) számolja az állapotot",
      "market_state" in _blk and "ds.session" in _blk)
check("...a MÁR lekért tickből (nincs extra MT5-hívás)", "from_tick" in _blk)
check("a sor-építés csak ÖSSZESZEDI", "_market = {s: (getattr(ds," in _g)
check("...és átadja a sor-adatnak", "market_states=_market," in _g)
_rs = (ROOT / "dashboard" / "row_source.py").read_text(encoding="utf-8")
check("a sor-adat továbbviszi", '"session"' in _rs and "market_states" in _rs)

# A fejléc-összegzés is a háttérszál adatából dolgozik.
check("van piac-összegző a felületen", "_refresh_market_badge" in _g)
_i2 = _g.find("def _refresh_market_badge")
check("...ami nyitott piacon ELTŰNIK", "pack_forget()" in _g[_i2:_i2 + 1200])

# ⚠ A dashboard-állapotnak VAN ilyen mezője (különben a háttérszál írása
# csendben elveszne egy elgépelt attribútumnévben).
from trading.live_trader import PairDashboardState
check("a dashboard-állapotnak van `session` mezője",
      "session" in PairDashboardState.__dataclass_fields__)


# ── 5. ÉLES MÉRÉS, ha van MT5-kapcsolat ───────────────────────────────
try:
    import logging
    logging.disable(logging.INFO)
    from strategy.settings import load_config
    from core import mt5_connector as _C
    cfg = load_config("config.json")
    _C.connect(cfg)
    _live = bool(_C.connection_info(cfg).get("connected"))
except Exception:
    _live = False

if _live:
    _syms = [s for s in cfg["pairs"] if not s.startswith("_")]
    _st = ms.states_of(_syms)
    logging.disable(logging.NOTSET)
    _n_open = sum(1 for v in _st.values() if v["state"] == ms.OPEN)
    _n_closed = sum(1 for v in _st.values() if v["state"] == ms.CLOSED)
    check("minden párra született állapot", len(_st) == len(_syms),
          f"{len(_st)}/{len(_syms)}")
    check("...és egyik sem maradt ISMERETLEN (van szerver-eltolás)",
          _n_open + _n_closed == len(_syms),
          f"nyitva={_n_open} zárva={_n_closed}")
    print(f"      (élesben MOST: {_n_open} nyitva, {_n_closed} zárva — "
          f"{ms.summary(_st) or 'minden nyitva'})")
    # ⚠ A kor SOSEM negatív — ez a szerver-eltolás helyes kezelésének a próbája:
    # eltolás nélkül a BTCUSD tickje „a jövőben" volna 2 órával.
    check("egyetlen kor sem negatív (a szerver-eltolás rendben)",
          all((v["age_sec"] or 0) >= 0 for v in _st.values()))
else:
    check("nincs MT5-kapcsolat (az éles mérés kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
