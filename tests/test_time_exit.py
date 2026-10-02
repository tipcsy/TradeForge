"""IDŐ-KILÉPÉS (napvégi zárás / max. tartás) — 2026-10-02.

Amit őrzünk:
  1. `risk_reduction.time_exit_due` — a tiszta döntés: napvégi zárás aznap,
     előtte nem, hétvégén átcsúszva az első gyertyán, max. tartás, kikapcsolva;
     a tzinfo-t NEM váltja át (a gyertya-index fal-óra, „UTC" címkével);
  2. `rr_state._norm` — az érvénytelen időpont nem kerül be (a valódi
     állapotfájlt a teszt NEM írja);
  3. `run_pair` valódi adaton: napvégi zárással egyetlen kötés sem marad nyitva
     az időpont után, a zárás `time` státuszú, kikapcsolva pedig a futás
     BITRE azonos azzal, mintha a funkció nem létezne (nincs `time` zárás).
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


from core import risk_reduction as rr                                     # noqa: E402

T = lambda s: pd.Timestamp(s)                                             # noqa: E731
eod = {"eod_close": "21:45", "max_hold_min": 0}
print("== time_exit_due ==")
check("alapból kikapcsolva", not rr.time_exit_active(rr.default_config()))
check("eod bekapcsolva aktív", rr.time_exit_active(eod))
check("eod előtt nincs zárás",
      rr.time_exit_due(T("2025-03-03 10:00"), T("2025-03-03 21:44"), eod) is None)
check("eod pontban zár",
      rr.time_exit_due(T("2025-03-03 10:00"), T("2025-03-03 21:45"), eod) == "eod")
check("eod után nyitott pozíció aznap nem zár",
      rr.time_exit_due(T("2025-03-03 21:50"), T("2025-03-03 23:00"), eod) is None)
check("eod után nyitott — másnap eod-kor zár",
      rr.time_exit_due(T("2025-03-03 21:50"), T("2025-03-04 21:45"), eod) == "eod")
check("hétvégén átcsúszva az első gyertyán zár",
      rr.time_exit_due(T("2025-03-07 15:00"), T("2025-03-10 00:01"), eod) == "eod")
check("a tzinfo NEM vált át (UTC-címkés fal-óra)",
      rr.time_exit_due(T("2025-07-01 10:00+00:00"), T("2025-07-01 21:45+00:00"), eod) == "eod"
      and rr.time_exit_due(T("2025-07-01 10:00+00:00"), T("2025-07-01 20:00+00:00"), eod) is None)
mh = {"eod_close": "", "max_hold_min": 480}
check("max tartás előtt nincs zárás",
      rr.time_exit_due(T("2025-03-03 10:00"), T("2025-03-03 17:59"), mh) is None)
check("max tartás után zár",
      rr.time_exit_due(T("2025-03-03 10:00"), T("2025-03-03 18:00"), mh) == "max_hold")
check("érvénytelen időpont = kikapcsolva",
      not rr.time_exit_active({"eod_close": "25:00", "max_hold_min": 0}))
check("parse_hhmm", rr.parse_hhmm("21:45") == 1305 and rr.parse_hhmm("") is None
      and rr.parse_hhmm("9:5") == 545 and rr.parse_hhmm("x") is None)

print("\n== rr_state normalizálás (fájlírás nélkül) ==")
from core import rr_state                                                 # noqa: E402
n = rr_state._norm({"preset": "off", "eod_close": "21:45", "max_hold_min": 480})
check("érvényes idő-kilépés tárolódik", n.get("eod_close") == "21:45"
      and n.get("max_hold_min") == 480.0)
n = rr_state._norm({"preset": "off", "eod_close": "99:99", "max_hold_min": -5})
check("érvénytelen idő-kilépés nem tárolódik", "eod_close" not in n
      and "max_hold_min" not in n)

print("\n== run_pair valódi adaton (UsaTec, quiet_breakout) ==")
from strategy import get_strategy_by_name                                # noqa: E402
from strategy.settings import config_for_strategy                        # noqa: E402
from core.execution_params import load_execution_params                  # noqa: E402
from trading.backtest import run_pair                                    # noqa: E402

SYM = "UsaTec"
raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
cfg = config_for_strategy(raw, "quiet_breakout")
st = get_strategy_by_name("quiet_breakout")
params = {**st.base_params(cfg), **(load_execution_params(SYM, cfg) or {})}
t0, t1 = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-07-01", tz="UTC")
m15 = pd.read_parquet(ROOT / "data" / "m15" / f"{SYM}.parquet")
m1 = pd.read_parquet(ROOT / "data" / "m1" / f"{SYM}.parquet")
m1 = m1[~m1.index.duplicated(keep="last")].sort_index()
m1 = m1[(m1.index >= t0 - pd.Timedelta(days=120)) & (m1.index < t1)]
m15 = m15[(m15.index >= t0 - pd.Timedelta(days=120)) & (m15.index < t1)]


def futas(spec):
    r = run_pair(SYM, m15, m1, params, cfg["pairs"][SYM], cfg["trading"], 10_000.0,
                 strategy=st, cfg=cfg, rr=spec, test_start=str(t0.date()),
                 test_end=str(t1.date()))
    return r.closed


ki = futas({**rr.default_config(), "preset": "none"})
be = futas({**rr.default_config(), "preset": "none", "eod_close": "21:45"})
check("van kötés mindkét futásban", len(ki) > 5 and len(be) > 5, f"{len(ki)} / {len(be)}")
check("kikapcsolva nincs `time` zárás", all(t.status != "time" for t in ki))
check("bekapcsolva van `time` zárás", any(t.status == "time" for t in be))
_idx = m1.index


def kesve(trades, due_of):
    """A kötések, amelyek az esedékesség UTÁNI első elérhető gyertyánál később
    zártak. ⚠ Hétvégén/szünetben a „következő gyertya" napokkal később jön —
    az a helyes viselkedés (zárt piacon nem lehet zárni)."""
    rossz = []
    for t in trades:
        d = due_of(pd.Timestamp(t.open_time))
        j = _idx.searchsorted(d - pd.Timedelta(minutes=1))     # a zárási idő >= d
        if j < len(_idx) and pd.Timestamp(t.close_time) > _idx[j]:
            rossz.append((t.open_time, t.close_time, t.status))
    return rossz


def kov_eod(o):
    e = o.normalize() + pd.Timedelta(hours=21, minutes=45)
    return e if o < e else e + pd.Timedelta(days=1)


_r = kesve(be, kov_eod)
check("egyetlen kötés sem marad nyitva a napvégi zárás után", not _r, str(_r[:3]))
_mh = futas({**rr.default_config(), "preset": "none", "max_hold_min": 120})
_r = kesve(_mh, lambda o: o + pd.Timedelta(minutes=120))
check("max. tartás: legkésőbb az esedékesség utáni első gyertyán zár",
      not _r and len(_mh) > 5, f"n={len(_mh)} rossz={_r[:3]}")
check("max. tartás: van `time` zárás", any(t.status == "time" for t in _mh))

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("BUKOTT:", _fail)
    sys.exit(1)
