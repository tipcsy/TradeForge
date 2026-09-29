"""ELOZMENY-LETOLTES: napi darabok, egy letoltes tobb idosikra, KULON processzben.

⚠ A LELET (2026-09-29, demo-proba, NORMAL modban): az NZDJPY felvetelekor a motor
a SAJAT processzeben toltotte a teljes elozmenyt — HAVI darabokban (egy honap =
tobb millio tick, a keres alatt a processz MT5-zarja foglalt), minden idosikhoz
UJRA (M15, aztan M1), a tick->gyertya epites a GIL-t fogta. A motor ES a kozos
processzu felulet 5+ percre megfagyott (a jelzes-naplo 316 mp-ig nem frissult).

MIT ORZUNK:
  1. napi darabok: napi PONTOSAN egy tick-keres, es abbol MINDEN kert idosik
     epul (nem toltjuk le ketszer); az ures napok (hetvege) nem akasztanak meg;
  2. uj szimbolum: EGY kozos letoltesbol mindket fajl letrejon;
  3. a kulon processzes seged a `--broker`-t atadja, a halado sorokat tovabbitja,
     a kilepesi kodbol dont;
  4. OR: a motor, a felulet es a backtest HELYBEN nem hivja az ensure_history-t.
⚠ Hamis MT5, ideiglenes mappa — a valodi data/-t es a terminalt nem erinti.
"""
import sys
import tempfile
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

import numpy as np                                                       # noqa: E402
import pandas as pd                                                      # noqa: E402

from tools import download_history as DH                                 # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def ticks(nap: dt.datetime, n=40):
    """Hamis tick-tomb egy napra: 2 percenkent egy tick (bid/ask)."""
    t0 = int(nap.replace(tzinfo=dt.timezone.utc).timestamp()) + 3600
    rec = [(t0 + i * 120, 1.10 + i * 1e-5, 1.10002 + i * 1e-5, 0.0, 0,
            (t0 + i * 120) * 1000, 6, 0.0) for i in range(n)]
    return np.array(rec, dtype=[("time", "<i8"), ("bid", "<f8"), ("ask", "<f8"),
                                ("last", "<f8"), ("volume", "<u8"), ("time_msc", "<i8"),
                                ("flags", "<u4"), ("volume_real", "<f8")])


class HamisMT5:
    COPY_TICKS_ALL = -1

    def __init__(self):
        self.kerdes = []
        self.gyertya = []

    def copy_ticks_range(self, sym, a, b, flags):
        self.kerdes.append((a, b))
        if a.weekday() >= 5:                      # hetvege: nincs adat
            return np.array([], dtype=ticks(a).dtype)
        return ticks(a)

    def copy_rates_range(self, sym, tf, a, b):
        self.gyertya.append((sym, tf, a, b))
        if a.weekday() >= 5:                      # hetvege: nincs gyertya
            return None
        t0 = int(dt.datetime(2026, 9, 22, 8, tzinfo=dt.timezone.utc).timestamp())
        rec = [(t0 + i * 60, 1.1, 1.2, 1.0, 1.1 + i * 1e-5, 5, 2, 0) for i in range(300)]
        return np.array(rec, dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"),
                                    ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<u8"),
                                    ("spread", "<i4"), ("real_volume", "<u8")])

    def symbol_select(self, s, e=True):
        return True

    def last_error(self):
        return (1, "Success")


print("== Napi darabok, egy letoltes tobb idosikra ==")
hamis = HamisMT5()
_regi_mt5 = DH.mt5
DH.mt5 = hamis
_regi_szunet = DH._NAPI_SZUNET
DH._NAPI_SZUNET = 0
try:
    kezd = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)          # kedd
    veg = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)
    out = DH._download_ticks_multi("NZDJPY", ["M15", "M1"], kezd, veg)
    check("napi PONTOSAN egy tick-keres (7 nap -> 7 keres)", len(hamis.kerdes) == 7,
          str(len(hamis.kerdes)))
    check("minden keres EGY napot fed (rovid MT5-zar)",
          all((b - a) <= dt.timedelta(days=1) for a, b in hamis.kerdes))
    check("mindket idosik ugyanabbol a letoltesbol", set(out) == {"M15", "M1"}
          and not out["M15"].empty and not out["M1"].empty)
    check("az M1 tobb gyertya, mint az M15", len(out["M1"]) > len(out["M15"]))
    check("a hetvegi ures napok nem akasztottak meg", len(out["M15"]) > 0)
    check("a pontos spread-oszlop megmaradt (a backtest koltsegmodellje)",
          "avg_spread" in out["M1"].columns, str(list(out["M1"].columns)))
    check("nincs duplikalt gyertya a napi hatarokon", out["M1"].index.is_unique)

    # ⚠ v3.120.0 regresszio (demo-proba, 2026-09-29): a H1 potlasa 730 napi
    # tick-kerest inditott a SEMMIERT (a H1 nem tickbol epul) — a terminal
    # szerver-szinkronja 110 mp-re megfagyasztotta a motort es a feluletet.
    hamis.kerdes.clear()
    check("tick-idosik nelkul EGYETLEN tick-keres sincs (H1)",
          DH._download_ticks_multi("Ger40", ["H1"], kezd, veg) == {}
          and not hamis.kerdes, f"{len(hamis.kerdes)} keres")
    check("a H1 a nativ gyertya-uton ismert (nincs KeyError)", "H1" in DH.TF_MAP)

    print("\n== Uj szimbolum: egy kozos letoltesbol mindket fajl ==")
    TMP = Path(tempfile.mkdtemp())
    _regi_root, _regi_conn = DH.ROOT, DH.mt5_connector.connect
    DH.ROOT = TMP
    DH.mt5_connector.connect = lambda cfg: True
    hamis.kerdes.clear()
    try:
        ok, msg = DH.ensure_history("NZDJPY", {"data": {"history_start_date": "2026-09-21"}},
                                    ("M15", "M1"), ticks=True)
        check("sikeres", ok, msg)
        check("mindket fajl letrejott (IDEIGLENES mappaban)",
              (TMP / "data" / "m15" / "NZDJPY.parquet").exists()
              and (TMP / "data" / "m1" / "NZDJPY.parquet").exists())
        napok = (dt.datetime.now(dt.timezone.utc).date() - dt.date(2026, 9, 21)).days + 1
        check("a tickek EGYSZER jottek le (nem idosikonkent ujra)",
              len(hamis.kerdes) <= napok + 1, f"{len(hamis.kerdes)} keres, {napok} nap")

        # ⚠ AUDJPY (demo-proba, 2026-09-29): a terminal EGY kerest szolgal ki; egy
        # uj szimbolum tick-szinkronja alatt a motor 3+ percig allt. Alapbol
        # tehat NATIV gyertya — tick-keres NELKUL.
        print("\n== Uj szimbolum alapbol: nativ gyertya, tick NELKUL ==")
        hamis.kerdes.clear()
        hamis.gyertya.clear()
        ok, msg = DH.ensure_history("AUDJPY", {"data": {"history_start_date": "2026-09-21"}},
                                    ("M15", "M1", "H1"))
        check("sikeres", ok, msg)
        check("EGYETLEN tick-keres sincs", not hamis.kerdes, f"{len(hamis.kerdes)} keres")
        # ⚠ MERVE (CADJPY): napi darabokban a terminal KOZBEN is kiszolgal
        # (a szonda max. 0,29 mp-et vart) -> csak az M1 jon a terminalbol
        check("CSAK az M1 jon a terminalbol (az M15 es a H1 abbol epul)",
              {tf for _, tf, _, _ in hamis.gyertya} == {DH.TF_MAP["M1"]},
              str({tf for _, tf, _, _ in hamis.gyertya}))
        check("a tomeges letoltes minden kerese legfeljebb EGY nap",
              all((b - a) <= dt.timedelta(days=1) for _, _, a, b in hamis.gyertya[:-1]))
        # ⚠ AUDUSD (2026-09-29): a szinkron elejen a legfrissebb napok uresek
        # voltak -> a fajl 4 nappal a jelen elott ert veget. A zaro potlas ezt hozza.
        check("a lemaradt friss veget a letolto AZONNAL potolja",
              hamis.gyertya[-1][2].date() == dt.date(2026, 9, 22)
              and hamis.gyertya[-1][3] - hamis.gyertya[-1][2] > dt.timedelta(days=1),
              str(hamis.gyertya[-1][2:]))
        check("a hetvegi ures napok NEM allitjak le (a teljes idoszak lejott)",
              min(a for _, _, a, _ in hamis.gyertya).date() <= dt.date(2026, 9, 21))
        check("az M15 is letrejott (az M1-bol)",
              (TMP / "data" / "m15" / "AUDJPY.parquet").exists())
        check("a H1 a helyi M1-bol (a terminalt NEM kerdeztuk)",
              DH.TF_MAP["H1"] not in {tf for _, tf, _, _ in hamis.gyertya}
              and (TMP / "data" / "h1" / "AUDJPY.parquet").exists())
        h1 = pd.read_parquet(TMP / "data" / "h1" / "AUDJPY.parquet")
        m1 = pd.read_parquet(TMP / "data" / "m1" / "AUDJPY.parquet")
        check("a H1 = az M1 orankenti osszevonasa (5 ora, 300 perc)",
              len(h1) == 5 and h1["close"].iloc[0] == m1["close"].iloc[59]
              and h1["open"].iloc[1] == m1["open"].iloc[60], str(len(h1)))
        check("...es a gyertya a nyitasi idejere cimkezve",
              h1.index[0] == m1.index[0] and (h1.index[1] - h1.index[0]) == pd.Timedelta("1h"))
    finally:
        DH.ROOT, DH.mt5_connector.connect = _regi_root, _regi_conn
finally:
    DH.mt5, DH._NAPI_SZUNET = _regi_mt5, _regi_szunet

print("\n== A kulon processzes seged ==")
import subprocess                                                        # noqa: E402
hivas = {}


class HamisProc:
    def __init__(self, cmd, **kw):
        hivas["cmd"] = cmd
        hivas["kw"] = kw
        self.stdout = iter(["[státusz] Letöltés M15, M1...\n", "      2026-09 ... 100 tick\n",
                            "NZDJPY: adat kész.\n"])

    def wait(self, timeout=None):
        return 0


_regi_popen = subprocess.Popen
subprocess.Popen = HamisProc
sorok = []
try:
    ok, utolso = DH.ensure_history_subprocess("NZDJPY", ("M15", "M1"), broker_id="rob",
                                              on_line=sorok.append)
finally:
    subprocess.Popen = _regi_popen
check("a --broker atadva a gyereknek", hivas["cmd"][-2:] == ["--broker", "rob"], str(hivas["cmd"]))
check("a gyerek a letolto szkript, a kert idosikokkal",
      "download_history.py" in hivas["cmd"][2] and "M15,M1" in hivas["cmd"])
check("bemenet nelkul (nem var semmire)", hivas["kw"].get("stdin") is not None)
check("a halado sorok tovabbitva", len(sorok) == 3 and sorok[-1] == "NZDJPY: adat kész.")
check("a kilepesi kodbol dont (0 -> siker)", ok is True and utolso == "NZDJPY: adat kész.")

print("\n== OR: a motor, a felulet, a backtest HELYBEN nem tolt ==")
for f in ("trading/live_trader.py", "dashboard/gui.py", "trading/backtest.py"):
    kod = [ln for ln in (ROOT / f).read_text(encoding="utf-8").splitlines()
           if ln.strip() and not ln.strip().startswith("#")]
    helyi = [ln.strip() for ln in kod if "ensure_history(" in ln
             and "ensure_history_subprocess" not in ln]
    check(f"{f}: nincs helyi ensure_history-hivas", not helyi, str(helyi[:2]))

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
