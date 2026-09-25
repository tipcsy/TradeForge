"""
KIMENT-E A JELZÉS? — a Jelzések fül Telegram-oszlopa és helyi ideje (v3.108.0).

MIERT (2026-09-25): a fül „Kiküldött jelzések" cimmel harom jelzest mutatott
20:31-20:32-kor, a Telegramra egyik sem erkezett. Az ok a csendes ora volt
(22:00-07:00 HELYI ido) — szandekos, de a ful (1) UTC-ben irta az idot, ezert a
22:31-es jelzes „20:31-es nappalinak" latszott, (2) semmit nem mutatott arrol,
hogy kiment-e.

Amit orzunk:
  1. a DONTES rogzitodik (sent / quiet / muted / off / dropped), a jovahagyo
     ajanlat „sent"-je felulirja a pár-nemitast;
  2. a naplo KULON fajl (a trades.csv auditnyomat nem irjuk at), es a teszt a
     valodi data/-ba NEM ir;
  3. a ful HELYI idot mutat, a „Ma" a helyi nap, es a Telegram-oszlop a
     naplobol jon.
"""

import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.applog as _applog
_applog.harden_console()

from core import notify as nt                       # noqa: E402
from core import signal_delivery as sd              # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


_tmp = pathlib.Path(tempfile.mkdtemp(prefix="sigdel_"))
sd.PATH = _tmp / "signal_delivery.csv"
_VALODI = ROOT / "data" / "signal_delivery.csv"
_valodi_elotte = _VALODI.stat().st_mtime if _VALODI.exists() else None

# ══ 1. A dontes rogzitese ══════════════════════════════════════════════════
print("== 1. dontes ==")
ROW = {"time": "2026-09-25T20:31:25+00:00", "event": "signal", "symbol": "Jp225",
       "strategy": "wpr_sma", "direction": "BUY", "lot": 0.05, "price": 66622.0,
       "sl": 66585.0, "tp": 66696.0}
_o_aktiv, _o_cfg = nt._aktiv, nt._cfg_json


def _allapot(row):
    return sd.load().get(sd.key(row["time"], row["symbol"], row["strategy"]))


try:
    nt._aktiv = None
    nt.trade_event(ROW)
    check("nincs beallitva -> off", _allapot(ROW) == sd.OFF, _allapot(ROW))

    # csendes ora: a mostani pillanatot lefedo ablak
    most = datetime.now()
    tol = (most - timedelta(minutes=5)).strftime("%H:%M")
    ig = (most + timedelta(minutes=5)).strftime("%H:%M")
    cfg = nt.Config(enabled=True, token="T", chat_ids=("7",),
                    quiet_from=tol, quiet_to=ig)
    nt._aktiv = nt.Notifier(cfg)
    nt._cfg_json = {"pairs": {"Jp225": {"strategy_notify_signal": {"wpr_sma": True}}}}
    r2 = {**ROW, "time": "2026-09-25T20:32:00+00:00"}
    nt.trade_event(r2)
    check("csendes ora -> quiet", _allapot(r2) == sd.QUIET, _allapot(r2))

    nt._aktiv = nt.Notifier(nt.Config(enabled=True, token="T", chat_ids=("7",)))
    r3 = {**ROW, "time": "2026-09-25T20:33:00+00:00"}
    nt.trade_event(r3)
    check("kimehet -> sent (sorba kerult)", _allapot(r3) == sd.SENT, _allapot(r3))

    nt._cfg_json = {"pairs": {"Jp225": {"strategy_notify_signal": {"wpr_sma": False}}}}
    r4 = {**ROW, "time": "2026-09-25T20:34:00+00:00"}
    nt.trade_event(r4)
    check("a par/strategia nemitva -> muted", _allapot(r4) == sd.MUTED, _allapot(r4))
    r5 = {**ROW, "time": "2026-09-25T20:35:00+00:00", "offered": True}
    nt.trade_event(r5)
    check("nemitva, DE a jovahagyo ajanlat kiment -> sent",
          _allapot(r5) == sd.SENT, _allapot(r5))

    nt._cfg_json = {"pairs": {"Jp225": {"strategy_notify_signal": {"wpr_sma": True}}}}
    _n = nt.Notifier(nt.Config(enabled=True, token="T", chat_ids=("7",)))
    _n.push = lambda ev: False
    nt._aktiv = _n
    r6 = {**ROW, "time": "2026-09-25T20:36:00+00:00"}
    nt.trade_event(r6)
    check("tele a sor -> dropped", _allapot(r6) == sd.DROPPED, _allapot(r6))

    r7 = {**ROW, "time": "2026-09-25T20:37:00+00:00", "event": "open"}
    nt._aktiv = None
    nt.trade_event(r7)
    check("KOTES-nyitasnal nincs kezbesites-rekord (csak jelzesnel)",
          _allapot(r7) is None)
finally:
    nt._aktiv, nt._cfg_json = _o_aktiv, _o_cfg

check("ismeretlen allapot nem kerul be", (sd.record("x", "Y", "z", "nem-ilyen"),
                                          sd.key("x", "Y", "z") not in sd.load())[1])
check("a VALODI data/signal_delivery.csv-t a teszt nem irta",
      (_VALODI.stat().st_mtime if _VALODI.exists() else None) == _valodi_elotte)
check("a szuro indoklasai konstansok (a lekepezes ezekre epul)",
      "return False, OK_CSEND_JELZES" in (ROOT / "core" / "notify.py")
      .read_text(encoding="utf-8"))

# ══ 2. A ful: helyi ido, helyi nap, Telegram-oszlop ════════════════════════
print("== 2. Jelzesek ful ==")
from dashboard import signals_tab as st                 # noqa: E402

h = st._helyi("2026-09-25T20:31:25+00:00")
_elvart = datetime(2026, 9, 25, 20, 31, 25, tzinfo=timezone.utc).astimezone()
check("_helyi: az UTC-idot HELYI idore valtja",
      h is not None and h.strftime("%H:%M") == _elvart.strftime("%H:%M"),
      h and h.strftime("%H:%M"))
check("_helyi: ertelmezhetetlen -> None", st._helyi("nem ido") is None)

import pandas as pd                                     # noqa: E402
_csv = _tmp / "trades.csv"
pd.DataFrame([ROW, {**ROW, "time": "2026-09-24T09:00:00+00:00", "symbol": "Ger40"}]
             ).to_csv(_csv, index=False)


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


class _Lbl:
    def config(self, **kw):
        pass


tab = st.SignalsTab.__new__(st.SignalsTab)
tab._csv = _csv
tab._range_var = _Var("custom")
_nap = h.date().isoformat()
tab._from_var, tab._to_var = _Var(_nap), _Var(_nap)
tab._lbl_hiba = _Lbl()
sd.record(ROW["time"], ROW["symbol"], ROW["strategy"], sd.QUIET)
sorok = tab._olvas()
check("a helyi napra szur (a 09-24-i sor kimarad)",
      [r["symbol"] for r in sorok] == ["Jp225"], [r["symbol"] for r in sorok])
check("a sor megkapja a kezbesites-allapotot a naplobol",
      sorok and sorok[0].get("_kezbesites") == sd.QUIET,
      sorok and sorok[0].get("_kezbesites"))
_src = (ROOT / "dashboard" / "signals_tab.py").read_text(encoding="utf-8")
check("a ful a HELYI idot irja ki (nem a nyers UTC-t)",
      '_h.strftime("%Y-%m-%d %H:%M")' in _src)
check("a Telegram-oszlop a fejlecben", 'signals.col.telegram' in _src)

import json                                             # noqa: E402
for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    kell = ["signals.col.telegram"] + [f"signals.delivery.{s}" for s in sd.STATUSES]
    check(f"{lang}: minden allapotnak van felirata", all(k in d for k in kell),
          [k for k in kell if k not in d])
    check(f"{lang}: a cim nem allitja, hogy MIND kiment",
          "Kiküldött" not in d["signals.title"] and "Sent" not in d["signals.title"])

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("Bukott:", ", ".join(_fail))
sys.exit(0 if all(_results) else 1)
