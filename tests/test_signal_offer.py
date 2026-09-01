"""A jelzés IGEN/NEM gombja — ahol egy chatüzenetből valódi pozíció lesz.

⚠ EZ A LEGKÉNYESEBB DARAB AZ EGÉSZ TELEGRAM-FUNKCIÓBAN. Minden más üzenetet
küld; ez KÖT. Ezért a teszt nem azt méri, hogy működik-e, hanem hogy MIKOR NEM
csinál semmit:

  1. **Alapból ki.** A `notify.answer_trading` nélkül ajánlat nem is születik.
  2. **Az ajánlat lejár** — jel-gyertya/2, de legalább egy perc. Egy fél órája
     küldött gomb más árra és más helyzetre vonatkozna.
  3. **Egyszer használható.** A kétszer megnyomott „Igen" EGY pozíciót nyit.
  4. **A kapuk nem kerülhetők meg** (nyitott pozíció, slot, napi limit) — és a
     végrehajtás ugyanazon az úton megy, mint a motor saját belépője.
  5. **A megcsúszott ár külön kérdés**: 0,25 R fölött az „Igen" NEM köt.

⚠ MT5 NÉLKÜL fut: a `live_trader` MT5-hívásait és a nyilvántartását cseréljük.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import signal_offer as so

# ── 1. ALAPBÓL KI ────────────────────────────────────────────────────────
# ⚠ Aki csak értesítést akar, ne kapjon véletlenül távirányítót a számlájához.
check("⚠ a válaszos kötés ALAPBÓL ki van kapcsolva", not so.enabled({}))
check("...üres notify blokknál is", not so.enabled({"notify": {}}))
check("...és kifejezetten be kell kapcsolni",
      so.enabled({"notify": {"answer_trading": True}}))
import json
_pelda = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
check("⚠ a config-példában is KI van kapcsolva",
      _pelda["notify"]["answer_trading"] is False)

# ── 2. ÉLETTARTAM: jel-gyertya / 2, de legalább egy perc ─────────────────
_ido = [1000.0]
R = so.Registry(ora=lambda: _ido[0])
for _gyertya, _var, _mit in ((900, 450, "M15 → 7,5 perc"),
                             (3600, 1800, "H1 → 30 perc"),
                             (60, 60, "M1 → 1 perc (a fele túl kevés lenne)"),
                             (0, 60, "ismeretlen → 1 perc")):
    check(f"élettartam: {_mit}", R.elettartam(_gyertya) == _var,
          f"{R.elettartam(_gyertya)} mp")


def ajanlat(gyertya=900, entry=100.0, sl_pts=100.0, tp_pts=200.0, irany="BUY"):
    return R.keszit(jel_gyertya_mp=gyertya, symbol="Ger40", strategy="wpr_sma",
                    direction=irany, lot=0.1, entry=entry, sl_points=sl_pts,
                    tp_points=tp_pts, point_size=0.01, magic=123,
                    risk_ccy=10.0, pv1_point=1.0)


o = ajanlat()
check("a friss ajánlat elérhető", o.elerheto(_ido[0]))
_ido[0] += 449
check("...a lejárat előtt is", o.elerheto(_ido[0]))
_ido[0] += 2
check("⚠ a LEJÁRT ajánlat nem elérhető", not o.elerheto(_ido[0]))
# ⚠ A lejárt ajánlatot MEGTARTJUK egy ideig: a késve megnyomott gomb így azt
# kapja, hogy „lejárt", nem azt, hogy „ismeretlen".
check("...de még megtalálható (a gomb tudjon róla szólni)",
      R.get(o.id) is not None)

# ── 3. EGYSZER HASZNÁLHATÓ ───────────────────────────────────────────────
# ⚠ A kétszer megnyomott „Igen" EGY pozíciót nyisson.
_ido[0] = 1000.0
o2 = ajanlat()
check("az első lezárás megkapja az ajánlatot",
      R.lezar(o2.id, so.ELFOGADVA) is not None)
check("⚠ a MÁSODIK már nem (nem nyílik két pozíció)",
      R.lezar(o2.id, so.ELFOGADVA) is None)
check("...és a nyitottak közt sem szerepel",
      o2.id not in [x.id for x in R.nyitott()])

# ── 4. A GEOMETRIA MARAD, A SZINT CSÚSZIK ────────────────────────────────
# ⚠ Ha az eredeti ABSZOLÚT SL/TP szintet vinnénk át egy megcsúszott belépőre, a
# kockázat CSENDBEN megváltozna: ugyanaz a lot más R-t jelentene.
o3 = ajanlat(entry=100.0, sl_pts=100.0, tp_pts=200.0)      # 1 pont = 0,01
_sl, _tp = o3.celok(100.0)
check("terv szerinti áron a stop a helyén",
      abs(_sl - 99.0) < 1e-9 and abs(_tp - 102.0) < 1e-9, f"{_sl} / {_tp}")
_sl2, _tp2 = o3.celok(100.5)                               # 0,5-tel feljebb
check("⚠ megcsúszott belépőnél a TÁVOLSÁG marad",
      abs((100.5 - _sl2) - 1.0) < 1e-9 and abs((_tp2 - 100.5) - 2.0) < 1e-9,
      f"{_sl2} / {_tp2}")
_o_sell = ajanlat(irany="SELL", entry=100.0)
_sl3, _tp3 = _o_sell.celok(100.0)
check("SELL: tükrözve", _sl3 > 100.0 > _tp3, f"{_sl3} / {_tp3}")

# ── 4b. AZ ÁR OLVASHATÓ LEGYEN ───────────────────────────────────────────
# ⚠ ÉLESBEN LÁTTAM: `%.5g`-vel egy Ger40-jelzés így nézett ki — „belépő 23457 ·
# SL 23456 · TP 23459". A három szint ránézésre EGYFORMA, és épp a stop
# TÁVOLSÁGA tűnt el, amiből meg lehetne ítélni a kötést. A pont-méret
# megmondja, hány tizedes érdekes.
for _pont, _ar, _var in ((0.01, 23456.7, "23456.70"),
                         (0.00001, 1.091234, "1.09123"),
                         (0.1, 64123.44, "64123.4"),
                         (1.0, 1234.5, "1234")):
    _o = ajanlat()
    _o.point_size = _pont
    check(f"ár-formátum {_pont}: {_var}", _o.fmt(_ar) == _var, _o.fmt(_ar))
_o = ajanlat()
_o.point_size = 0.0
check("⚠ hiányzó pont-méretnél sem dob (visszaesés)", bool(_o.fmt(123.456)))
# A stop TÁVOLSÁGA látszódjon: a belépő és az SL szövege NE legyen azonos.
_o = ajanlat(entry=23456.7, sl_pts=100.0)
_o.point_size = 0.01
check("⚠ a belépő és a stop SZÖVEGE különbözik (a távolság látszik)",
      _o.fmt(_o.entry) != _o.fmt(_o.celok(_o.entry)[0]),
      f"{_o.fmt(_o.entry)} vs {_o.fmt(_o.celok(_o.entry)[0])}")

# ── 5. AZ ELMOZDULÁS R-BEN ───────────────────────────────────────────────
check("terv szerinti áron nincs elmozdulás", o3.sodrodas_r(100.0) == 0.0)
check("negyed stop = 0,25 R", abs(o3.sodrodas_r(100.25) - 0.25) < 1e-9)
check("⚠ a küszöb 0,25 R", so.SODRODAS_R == 0.25)
check("⚠ az elmozdulás IRÁNYTÓL független (a kedvező is más kötés)",
      abs(o3.sodrodas_r(99.6) - o3.sodrodas_r(100.4)) < 1e-9)

# ── 6. A VÉGREHAJTÁS: egy út, két hívó ───────────────────────────────────
# ⚠ Ha a gomb saját utat járna, a fedezet-ellenőrzés, a slot-elszámolás, a
# belépéskori kockázat rögzítése és a napló-írás kimaradhatna belőle — némán,
# és pont a pénzt mozgató ágon.
_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("⚠ a kézi belépő ugyanazt a `_execute_entry`-t hívja",
      _src.count("_execute_entry(") >= 3,
      f"{_src.count('_execute_entry(')} előfordulás (1 def + 2 hívó)")
check("⚠ ...és zár védi a kettős nyitástól",
      "_MANUAL_LOCK" in _src and "with _MANUAL_LOCK" in _src)
check("⚠ az ajánlatot a MEGBÍZÁS ELŐTT fogyasztjuk el",
      _src.index("REGISTRY.lezar(o.id") < _src.index("ticket = _execute_entry("))

# ── 7. A KAPUK (MT5 nélkül, cserélt nyilvántartással) ────────────────────
from trading import live_trader as lt

_eredeti = {"pos": lt.strategy_positions, "slot": lt._run_slot_mgr,
            "cfg": lt._run_cfg, "exec": lt._execute_entry,
            "mt5": lt.mt5, "reg": so.REGISTRY}


class _FakeMt5:
    class _Tick:
        def __init__(self, ar):
            self.ask = self.bid = ar

    def __init__(self, ar=100.0):
        self.ar = ar

    def symbol_info_tick(self, _s):
        return self._Tick(self.ar)


class _Slot:
    def __init__(self, ok=True):
        self.ok = ok

    def can_open_risk(self, _r):
        return self.ok

    def add(self, *a, **kw):
        pass


try:
    so.REGISTRY = R
    lt.mt5 = _FakeMt5()
    lt._run_cfg = {"notify": {"answer_trading": True}, "trading": {}}
    lt._run_slot_mgr = _Slot()
    lt.strategy_positions = lambda s, n, positions=None: []
    _nyitott = []
    lt._execute_entry = lambda *a, **kw: (_nyitott.append(a) or 4242)

    # Kikapcsolva → semmi.
    lt._run_cfg = {"notify": {}, "trading": {}}
    o4 = ajanlat()
    _st, _sz, _u = lt.manual_entry(o4.id)
    check("⚠ kikapcsolt válaszos kötésnél NEM köt", _st == "kikapcsolva" and not _nyitott)
    lt._run_cfg = {"notify": {"answer_trading": True}, "trading": {}}

    # Lejárt ajánlat → semmi.
    _ido[0] += 10_000
    _st, _sz, _u = lt.manual_entry(o4.id)
    check("⚠ LEJÁRT ajánlatnál NEM köt", _st == "lejart" and not _nyitott)
    _ido[0] = 1000.0

    # Már van nyitott pozíció → semmi.
    o5 = ajanlat()
    lt.strategy_positions = lambda s, n, positions=None: [object()]
    _st, _sz, _u = lt.manual_entry(o5.id)
    check("⚠ NYITOTT pozíciónál NEM köt (egy páron egy pozíció)",
          _st == "mar_nyitva" and not _nyitott, _sz[:50])
    lt.strategy_positions = lambda s, n, positions=None: []

    # Nincs slot → semmi.
    lt._run_slot_mgr = _Slot(ok=False)
    _st, _sz, _u = lt.manual_entry(o5.id)
    check("⚠ SLOT nélkül NEM köt", _st == "nincs_slot" and not _nyitott)
    lt._run_slot_mgr = _Slot()

    # Megcsúszott ár → NEM köt, hanem újra kérdez, és az ajánlat NYITVA marad.
    lt.mt5 = _FakeMt5(ar=100.5)                 # 0,5 = 0,5 R elmozdulás
    _st, _sz, _u = lt.manual_entry(o5.id)
    check("⚠ 0,25 R fölötti elmozdulásnál NEM köt", _st == "sodrodas" and not _nyitott)
    check("...hanem ÚJRA KÉRDEZ", _u is True)
    check("...és megmondja, MENNYIT mozdult", "0.50" in _sz, _sz[:70])
    check("⚠ ...az ajánlat pedig NYITVA marad (dönthetsz)",
          R.get(o5.id).state == so.NYITOTT)

    # „Mégis" → most már köt, a MOSTANI árra igazított geometriával.
    _st, _sz, _u = lt.manual_entry(o5.id, drift_confirmed=True)
    check("a „Mégis” megköti", _st == "ok" and len(_nyitott) == 1, _st)
    _hivas = _nyitott[0]
    check("⚠ ...a MOSTANI áron (nem a terv árán)", abs(_hivas[10] - 100.5) < 1e-9,
          str(_hivas[10]))
    check("⚠ ...és a stop TÁVOLSÁGA a tervé", abs(_hivas[10] - _hivas[4] - 1.0) < 1e-9,
          f"belépő {_hivas[10]} / SL {_hivas[4]}")

    # ⚠ A MÁSODSZOR megnyomott gomb már nem nyit újat.
    _st, _sz, _u = lt.manual_entry(o5.id, drift_confirmed=True)
    check("⚠ ugyanaz az ajánlat MÁSODSZOR már nem köt",
          _st == "lejart" and len(_nyitott) == 1)

    # A megbízás elbukása → NEM hallgatunk.
    lt.mt5 = _FakeMt5(ar=100.0)
    lt._execute_entry = lambda *a, **kw: None
    o6 = ajanlat()
    _st, _sz, _u = lt.manual_entry(o6.id)
    check("⚠ ha a megbízás nem megy át, azt KIMONDJA", _st == "hiba", _sz[:60])
    check("...és megmondja, hogy NEM nyílt pozíció",
          "NEM" in _sz or "No position" in _sz)
finally:
    lt.strategy_positions = _eredeti["pos"]
    lt._run_slot_mgr = _eredeti["slot"]
    lt._run_cfg = _eredeti["cfg"]
    lt._execute_entry = _eredeti["exec"]
    lt.mt5 = _eredeti["mt5"]
    so.REGISTRY = _eredeti["reg"]

# ── 8. A GOMBOK ÚTJA ─────────────────────────────────────────────────────
from core import telegram_cmd as tgc
from core import console_cmd as cc

_ctx = cc.Context(cfg={"pairs": {}}, save_config=lambda: True,
                  positions=list, close_position=lambda t: True,
                  account=dict, dashboard={}, instrument_state={},
                  strategies_of=lambda s: [])
b = tgc.Bot(token="T", chat_ids=("1",), ctx=_ctx)


def _gomb(adat):
    return {"update_id": 1, "callback_query": {
        "id": "cb", "data": adat,
        "message": {"message_id": 5, "chat": {"id": "1"}}}}


_hivott = []
_eredeti_me = lt.manual_entry
try:
    lt.manual_entry = lambda oid, drift_confirmed=False: (
        _hivott.append((oid, drift_confirmed))
        or (("sodrodas", "elment az ár", True) if not drift_confirmed
            else ("ok", "megkötve", False)))
    _k = b.feldolgoz(_gomb("a:XYZ"))
    check("⚠ az „Igen” gomb NEM erősíti meg magától az elmozdulást",
          _hivott[-1] == ("XYZ", False))
    check("...és elmozdulásnál ÚJ gombot ad", len(_k[0].buttons) == 2,
          str([x[1] for x in _k[0].buttons]))
    check("⚠ ...a „Mégis” gomb külön adattal megy",
          any(a.startswith("m:") for _f, a in _k[0].buttons))
    _k2 = b.feldolgoz(_gomb("m:XYZ"))
    check("a „Mégis” megerősítve hívja", _hivott[-1] == ("XYZ", True))
    check("...és az üzenetet ÁTÍRJA (nincs mit kétszer megnyomni)",
          _k2[0].edit_message_id == 5 and not _k2[0].buttons)
finally:
    lt.manual_entry = _eredeti_me

# Az elvetés ne hívja a végrehajtást.
_hivott.clear()
_eredeti_me = lt.manual_entry
try:
    lt.manual_entry = lambda *a, **kw: (_hivott.append(a) or ("ok", "x", False))
    _k = b.feldolgoz(_gomb("x:ABC"))
    check("⚠ az elvetés NEM hívja a végrehajtást", not _hivott)
    check("...és meg is mondja",
          "nem csinálom" in _k[0].text or "not doing" in _k[0].text)
finally:
    lt.manual_entry = _eredeti_me

# ── 9. Katalógus ─────────────────────────────────────────────────────────
_hu = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
_en = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
_k = [k for k in _hu if k.startswith("tg.offer.")]
check("vannak `tg.offer.*` kulcsok", len(_k) >= 8, f"{len(_k)}")
check("⚠ mind le van fordítva angolra", not [k for k in _k if k not in _en])
# ⚠ Minden elutasítás MEGMONDJA AZ OKOT — nem csak annyit, hogy „nem sikerült".
for _kulcs in ("tg.offer.already_open", "tg.offer.no_slot",
               "tg.offer.daily_limit", "tg.offer.failed"):
    check(f"{_kulcs}: megmondja az okot", len(_hu[_kulcs]) > 30)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
