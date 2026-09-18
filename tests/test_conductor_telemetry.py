"""KARMESTER F0 — belépő-telemetria: a „miért nem kötött?" válasza.

⚠ A LELET. A rendszer meg tudja mondani, MI történt (kötések, P&L, napló), de
nem tudja megmondani, MI NEM. Egy nem kötő cella pontosan úgy néz ki, mint
amelyik épp nem talál belépőt — pedig lehet, hogy a spread-kapu zárt egész nap,
vagy elfogytak a slotok, vagy a napi limit áll fenn. A karmester ENÉLKÜL vakon
döntene, ezért ez az F0 fázis első darabja.

⚠ A TESZT SOHA NEM NYÚL A VALÓDI `data/` MAPPÁHOZ. A `conductor.paths.DIR`-t
ideiglenes könyvtárba irányítjuk — a projektben már háromszor megtörtént, hogy
egy teszt a felhasználó állapotát írta felül.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.WARNING)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from conductor import paths as cp
from conductor import telemetry as tl

cp.DIR = Path(tempfile.mkdtemp(prefix="tf_cond_"))
tl.FLUSH_SEC = 0.0            # a tesztben minden rögzítés után írjon
NAP = "2026-09-18"


# ══ 1. ROGZITES ES OSSZESITES ════════════════════════════════════════════
tl.reset_for_test()
tl.record("EURUSD", "wpr_sma", "BUY", tl.GATE, gates_blocked=["spread"],
          bar_ts=1000, day=NAP)
tl.record("EURUSD", "wpr_sma", "SELL", tl.NO_SLOT, bar_ts=1060, day=NAP)
tl.record("EURUSD", "wpr_sma", "BUY", tl.ENTERED, bar_ts=1120, day=NAP)
c = tl.cell("EURUSD", "wpr_sma", NAP)
check("minden jel szamit", c["signals"] == 3, str(c["signals"]))
check("a kotes kulon is szamit", c["entries"] == 1, str(c["entries"]))
check("a kimenetek bontasa megvan",
      c["outcomes"] == {"gate": 1, "no_slot": 1, "entered": 1}, str(c["outcomes"]))
check("a KAPU is nevesitve van", c["gates_blocked"] == {"spread": 1},
      str(c["gates_blocked"]))
check("az utolso esemeny reszletei megvannak",
      (c["last"] or {}).get("outcome") == "entered"
      and (c["last"] or {}).get("direction") == "BUY", str(c["last"]))

# ⚠ A „miert nem" a KOTESEKET nem tartalmazza: a kerdes az, ami MEGAKADALYOZTA.
_why = tl.why_not("EURUSD", "wpr_sma", NAP)
check("a why_not csak az AKADALYOKAT adja",
      dict(_why) == {"gate": 1, "no_slot": 1}, str(_why))
check("...a leggyakoribb elol", _why == sorted(_why, key=lambda x: (-x[1], x[0])))


# ══ 2. ISMETLODES-VEDELEM ════════════════════════════════════════════════
# ⚠ ELESBEN MAR ELSULT: a „csak jelzes" riasztasbol EGYETLEN szetupra 60 uzenet
# ment ki (GOLD BUY, 18:00-18:04, percenkent egy), amig az alert-ID a JEL-
# gyertyara nem kerult. A motor percenkent fut; egy H1-es strategia jele 60
# korön at „jel" marad. Ha a telemetria ezt nem kezelne, egy H1-es strategia
# 60x-os sullyal latszana egy M1-eshez kepest.
tl.reset_for_test()
_elso = tl.record("Ger40", "bollinger", "BUY", tl.GATE, bar_ts=7200, day=NAP)
_ismet = [tl.record("Ger40", "bollinger", "BUY", tl.GATE, bar_ts=7200, day=NAP)
          for _ in range(59)]
check("az elso jel szamit", _elso)
check("...a tobbi 59 kor NEM", not any(_ismet))
check("a cella egyetlen jelet lat",
      tl.cell("Ger40", "bollinger", NAP)["signals"] == 1)
# A KOVETKEZO gyertya viszont uj jel.
tl.record("Ger40", "bollinger", "BUY", tl.GATE, bar_ts=10800, day=NAP)
check("a KOVETKEZO jel-gyertya viszont uj jel",
      tl.cell("Ger40", "bollinger", NAP)["signals"] == 2)
# Jel-gyertya nelkul (kezi belepo) nincs dedup — ott az ember dont, egyszer.
tl.record("Ger40", "bollinger", "BUY", tl.ENTERED, day=NAP)
tl.record("Ger40", "bollinger", "BUY", tl.ENTERED, day=NAP)
check("bar_ts nelkul minden rogzites szamit",
      tl.cell("Ger40", "bollinger", NAP)["entries"] == 2)


# ══ 3. LEMEZ: atomikus iras, es a memoria+fajl EGYUTT az igazsag ═════════
tl.reset_for_test()
tl.record("GOLD", "csilla", "SELL", tl.DAILY_LIMIT, bar_ts=1, day=NAP)
check("a napi fajl megszuletett", cp.telemetry_file(NAP).exists(),
      cp.telemetry_file(NAP).name)
check("...es nem maradt utana .tmp",
      not list(cp.telemetry_dir().glob("*.tmp")))
import json as _json
_fajl = _json.loads(cp.telemetry_file(NAP).read_text(encoding="utf-8"))
check("a fajl verziozott es nap-cimkezett",
      _fajl.get("version") and _fajl.get("day") == NAP, str(_fajl.get("day")))

# ⚠ A ki nem irt resz is latszik: a felhasznalo epp az IMENT kimaradt belepot
# keresi a jelentesben, nem az egy perccel ezelottit.
tl.FLUSH_SEC = 9999.0
tl.record("GOLD", "csilla", "SELL", tl.NO_ATR, bar_ts=2, day=NAP)
check("a meg ki nem irt meres is benne van a lekerdezesben",
      tl.cell("GOLD", "csilla", NAP)["signals"] == 2)
tl.FLUSH_SEC = 0.0
tl.flush()

# Ujraolvasas TISZTA memoriaval: a lemezrol is ugyanaz jon.
tl.reset_for_test()
check("ujrainditas utan a lemezrol olvas",
      tl.cell("GOLD", "csilla", NAP)["signals"] == 2,
      str(tl.cell("GOLD", "csilla", NAP)))


# ══ 4. A NAP: a BROKERE, es a hivo adja be ═══════════════════════════════
# ⚠ A projektben KET „ma" el, mindketto szandekosan: a „Lezart" ful a broker
# napjat hasznalja (server_today), a napi osszesito a HELYI napot. A telemetria
# a PIAC napjahoz tartozik — de a modul MT5-mentes marad, ezert kivulrol kapja.
tl.set_day_provider(lambda: "2026-01-02")
check("a bekotott nap-forras dont", tl.day_key() == "2026-01-02", tl.day_key())
tl.set_day_provider(lambda: 1 / 0)          # elszallo forras
check("az elszallo nap-forras NEM viszi el a merest (UTC-re esik vissza)",
      len(tl.day_key()) == 10 and tl.day_key()[4] == "-", tl.day_key())
tl.set_day_provider(None)

# Nap-valtas: a regi nap NEM keveredik az ujba.
tl.reset_for_test()
tl.record("UsaInd", "wpr_sma", "BUY", tl.ENTERED, bar_ts=5, day="2026-09-17")
tl.record("UsaInd", "wpr_sma", "BUY", tl.ENTERED, bar_ts=5, day="2026-09-18")
check("a nap-valtas kulon fajlba megy",
      cp.telemetry_file("2026-09-17").exists()
      and cp.telemetry_file("2026-09-18").exists())
check("...es a ket nap kulon szamol",
      tl.cell("UsaInd", "wpr_sma", "2026-09-17")["entries"] == 1
      and tl.cell("UsaInd", "wpr_sma", "2026-09-18")["entries"] == 1)
check("⚠ ...az ismetlodes-vedelem NEM nyeli el a nap elso jelet",
      tl.cell("UsaInd", "wpr_sma", "2026-09-18")["signals"] == 1)


# ══ 5. A MERES SOHA NEM ALLITHATJA MEG A KERESKEDEST ═════════════════════
check("ismeretlen kimenet: nem dob, de nem is szamolja",
      tl.record("X", "y", "BUY", "nincsilyen", day=NAP) is False)
_elotte = dict(tl.cell("GOLD", "csilla", NAP))
_rossz_dir = cp.DIR
cp.DIR = Path("/dev/null/nemletezik")       # irhatatlan
try:
    check("irhatatlan mappa: a rogzites NEM dob", 
          tl.record("GOLD", "csilla", "BUY", tl.NO_SLOT, bar_ts=99, day=NAP) is True)
    check("...es a flush sem", tl.flush() is False)
finally:
    cp.DIR = _rossz_dir
check("a helyreallt mappaba kiirja a kozben gyult merest", tl.flush())


# ══ 6. TAKARITAS ════════════════════════════════════════════════════════
tl.set_day_provider(lambda: "2026-09-18")
for _regi in ("2026-01-01", "2026-05-05"):
    cp.telemetry_file(_regi).write_text("{}", encoding="utf-8")
_n = tl.prune(keep_days=30)
check("a regi napok kitakarodnak", _n == 2, str(_n))
check("...a mai megmarad", cp.telemetry_file("2026-09-18").exists())
check("keep_days=0 -> nincs takaritas", tl.prune(keep_days=0) == 0)
tl.set_day_provider(None)


# ══ 7. A MOTOR BEKOTESE — forras-szintu orzes ═══════════════════════════
# ⚠ MIERT FORRAS-SZINTU: a `trading/live_trader.py` MT5-ot importal, tehat itt
# nem tolthető be. A REGRESSZIO viszont pont az, ha egy dontesi ag kimarad a
# meresbol — akkor a jelentes NEMAN hianyos lesz.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
for _ag, _kod in (("kapu/limit/slot lanc", "_tlm.record(symbol, strategy.name, signal, _why"),
                  ("korrelacio",           "_tlm.CORRELATION"),
                  ("nincs SL/TP terv",     "_tlm.NO_PLAN"),
                  ("csak jelzes",          "_tlm.SIGNAL_ONLY"),
                  ("vegrehajtas",          "_tlm.ENTERED if _ticket else _tlm.EXEC_FAILED"),
                  ("kezi (Telegram) belepo", "_tlm.ENTERED if ticket else _tlm.EXEC_FAILED")):
    check(f"a motor meri: {_ag}", _kod in _lt, "")

# ⚠ ELOBB A KOD, A SZOVEG ABBOL. Korabban a lanc kozvetlenul a FORDITOTT mondatot
# adta; a telemetrianak ugyanazt a precedenciat kellett volna masodszor is
# leirnia, es a ket lanc az elso uj oknal elcsuszott volna.
_lanc = _lt.split("_why = (_tlm.CLOSING")[1].split("_block = (")[0]
check("a kihagyas oka KODKENT dol el (egy lanc)",
      "_tlm.NO_SLOT if not slot_mgr.can_open()" in _lanc
      and "_t(" not in _lanc, _lanc[:80])
check("...es a mondat a KODBOL keszul",
      "_t(\"block.no_slot\") if _why == _tlm.NO_SLOT" in _lt)

# A JEL-GYERTYA ideje EGY helyen: az alert-ID es a telemetria ugyanazt lassa.
check("a jel-gyertya ideje kozos segedbol jon", "def _signal_bar_ts(" in _lt)
check("...es az alert-ID is azt hasznalja",
      '_aid = f"{symbol}|{strategy.name}|{signal}|{_bar_ts}"' in _lt)
# ⚠ A JEL-GYERTYA IDEJENEK szamitasa (`df_lo.index[-2]`) EGY helyen legyen. A
# `signal_bar_seconds` maga TOBB helyen hivodik (a viz-idosik korlatja is
# hasznalja) — az nem duplikacio, mert nem idobelyeget szamol.
check("...es a jel-gyertya IDEJE csak egy helyen szamolodik",
      _lt.count("df_lo.index[-2].timestamp()") == 1,
      str(_lt.count("df_lo.index[-2].timestamp()")))

# A meres nem allithatja meg a motort: a bekotesek vedve vannak.
check("az induló bekotes vedve van",
      "_tlm.set_day_provider(mt5_connector.server_today)" in _lt
      and "karmester-telemetria: az indítás kimaradt" in _lt)
check("a leallaskori kiiras is vedve van",
      "karmester-telemetria: a záró kiírás kimaradt" in _lt)


# ══ 8. A KODOK STABILAK, A FELIRAT CSAK KIJELZES ════════════════════════
# ⚠ Ugyanaz a szabaly fogta meg a core/quality.py minositeseit: ott a magyar szo
# volt a rangsor kulcsa is, es angolra forditva a tabla NEMAN rossz sorrendet
# mutatott. Egy naplofajlnal ez rosszabb: a tegnapi fajlt mar nem lehet
# visszaforditani.
_HU = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
_EN = _json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
check("minden kimenetnek van magyar felirata",
      all(_HU.get(f"conductor.outcome.{o}") for o in tl.OUTCOMES),
      str([o for o in tl.OUTCOMES if not _HU.get(f"conductor.outcome.{o}")]))
check("...es angol is",
      all(_EN.get(f"conductor.outcome.{o}") for o in tl.OUTCOMES))
check("a kodok ASCII azonositok (nem forditott mondatok)",
      all(o.isascii() and o.islower() for o in tl.OUTCOMES))
check("a LabelMap az AKTIV nyelvbol szolgal ki (nem fagy be)",
      type(tl.LABELS).__name__ == "LabelMap")


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
