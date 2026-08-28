"""A tick-letolto: NAPI batch, folytathatosag, konstans memoria.

A felhasznalo tapasztalata (2026-08-27) harom kovetelmenyt adott, es ez a teszt
mindharmat orzi:

  1. NAPI szeletek - az MT5-on at a letoltes drága; egy honap egyben None-t ad,
     es megszakadaskor az egesz honap karba vesz.
  2. FOLYTATHATOSAG - a broker bezar, a kapcsolat megszakad: a kovetkezo futas
     onnan folytassa, ahol abbahagyta. A napi fajl MAGA az allapot.
  3. NE EGYE MEG A MEMORIAT - egyszerre egy nap legyen bent; a havi osszevonas
     streameljen.

MT5 nelkul fut: a halozati reteget (`fetch_day`) kicsereljuk.
"""
import io
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from tools import download_ticks as D

# ⚠ SOHA ne a valodi data/ticks-be irjunk.
TMP = Path(tempfile.mkdtemp(prefix="tf_ticks_"))
D.TICK_DIR = TMP
D.POLITE_SLEEP = 0.0
check_("a teszt a sajat temp-konyvtaraba ir", str(D.TICK_DIR).startswith(str(TMP)))


# ── to_frame: szures, dedup, rendezes, EGESZ ar ─────────────────────────────
dt = np.dtype([("time_msc", "i8"), ("bid", "f8"), ("ask", "f8")])
raw = np.array([(3000, 1.16551, 1.16561),
                (1000, 1.16549, 1.16559),
                (2000, 0.0, 0.0),            # bid <= 0 -> KIESIK
                (1000, 1.16550, 1.16560),    # UGYANAZ az ms -> MEGMARAD
                (4000, 1.16500, 1.16400)],   # ask < bid -> a sor MARAD, ask_pt=0
               dtype=dt)
f = D.to_frame(raw, 1e-5)
# ⚠ A dedup TILOS. Tobb VALODI tick osztozhat egy ezredmasodpercen; ha eldobjuk,
# a volumen csokken es a high/low LEVAGODIK. Merve (Ger40, 581 ezer bar):
# -3,6% tick, a barok 68,9%-an kevesebb, high -0,022 / low +0,0145 pont.
check_("to_frame: a bid<=0 sor kiesik", len(f) == 4, str(len(f)))
check_("to_frame: az AZONOS ms-u tickek MINDEGYIKE megmarad",
       list(f.time_msc) == [1000, 1000, 3000, 4000], str(list(f.time_msc)))
check_("to_frame: az ervenytelen ask sora MARAD (a volumenbe szamit)",
       int(f.time_msc.iloc[-1]) == 4000)
check_("...de ask_pt = 0 (a spreadbe nem szamit)",
       int(f.ask_pt.iloc[-1]) == 0, str(f.ask_pt.iloc[-1]))
check_("to_frame: az ar EGESZ pont (nincs kerekitesi vesztes)",
       int(f.ask_pt.iloc[2]) == 116561, str(f.ask_pt.iloc[2]))


# ── atomikus iras: felkesz fajl sosem marad ─────────────────────────────────
p = TMP / "X" / "proba.parquet"
D._write_atomic(f, p)
check_("atomikus iras: a fajl a helyen van", p.exists())
check_("...es nincs .tmp maradek", not list(p.parent.glob("*.tmp")))
back = pd.read_parquet(p)
check_("...a visszaolvasott tartalom egyezik",
       list(back.time_msc) == [1000, 1000, 3000, 4000])


# ── FOLYTATHATOSAG: a napi fajl az allapot ─────────────────────────────────
SYM = "TESZT"
hivott = []


def fake_fetch(sym, d, point, cfg):
    """A halozati reteg helyett: minden hetkoznapra 3 tick."""
    hivott.append(d.date())
    base = int(d.timestamp() * 1000)
    return pd.DataFrame({"time_msc": [base, base + 1, base + 2],
                         "bid_pt": [1, 2, 3], "ask_pt": [2, 3, 4]}).astype("int64")


D.fetch_day = fake_fetch


class _Info:
    point = 1e-5


D.mt5 = type("m", (), {"symbol_select": staticmethod(lambda s, b: True),
                       "symbol_info": staticmethod(lambda s: _Info())})()
D.mt5_connector = type("c", (), {"MT5_LOCK": __import__("threading").RLock()})()

start = datetime(2024, 3, 4, tzinfo=timezone.utc)     # hetfo
end = datetime(2024, 3, 11, tzinfo=timezone.utc)      # a kovetkezo hetfo
st1 = D.download_symbol(SYM, start, end, {})
check_("elso futas: 5 hetkoznap toltodott le", st1["uj"] == 5, str(st1))
check_("...a hetvege URES fajlt kapott (nem kerdezzuk ujra)", st1["ures"] == 2,
       str(st1["ures"]))
check_("...a halozatot csak hetkoznapra hivtuk", len(hivott) == 5, str(len(hivott)))

hivott.clear()
st2 = D.download_symbol(SYM, start, end, {})
check_("MASODIK futas: 0 uj letoltes (folytathatosag)", st2["uj"] == 0, str(st2))
check_("...mind a 7 nap meglevonek szamit", st2["meglevo"] == 7, str(st2["meglevo"]))
check_("...es a halozatot MEG EGYSZER SEM hivtuk", not hivott, str(hivott))

# megszakadas kozepen: egy nap fajlja hianyzik -> csak azt tolti ujra
D.day_file(SYM, datetime(2024, 3, 6, tzinfo=timezone.utc)).unlink()
hivott.clear()
st3 = D.download_symbol(SYM, start, end, {})
check_("hianyzo nap -> CSAK azt tolti ujra", st3["uj"] == 1 and len(hivott) == 1,
       f"{st3['uj']} / {hivott}")

# halozati hiba -> NINCS fajl, hogy legkozelebb ujraprobalja
D.fetch_day = lambda sym, d, point, cfg: None
D.day_file(SYM, datetime(2024, 3, 7, tzinfo=timezone.utc)).unlink()
st4 = D.download_symbol(SYM, start, end, {})
check_("halozati hiba -> nem ir fajlt (ujraprobalhato)",
       st4["hiba"] == 1 and not D.day_file(
           SYM, datetime(2024, 3, 7, tzinfo=timezone.utc)).exists(), str(st4))
D.fetch_day = fake_fetch
D.download_symbol(SYM, start, end, {})        # potoljuk


# ── HAVI OSSZEVONAS: streamel, a folyo honapot nem bantja ──────────────────
n = D.consolidate(SYM)
mf = D.month_file(SYM, 2024, 3)
check_("a lezart honap osszevonva", n == 1 and mf.exists(), f"{n}")
m = pd.read_parquet(mf)
check_("...a havi fajl 5 hetkoznap x 3 tick = 15 sor", len(m) == 15, str(len(m)))
check_("...ido szerint novekvo", list(m.time_msc) == sorted(m.time_msc))
check_("...a napi fajlok eltakaritva", not list(D.day_dir(SYM).glob("2024-03-*")))
check_("ismetelt osszevonas nem csinal semmit", D.consolidate(SYM) == 0)

# a FOLYO honapot nem vonja ossze (meg johet bele nap)
now = datetime.now(timezone.utc)
cur = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
D.download_symbol(SYM, cur, cur + timedelta(days=3), {})
D.consolidate(SYM)
check_("a FOLYO honapot nem vonja ossze",
       not D.month_file(SYM, cur.year, cur.month).exists())
check_("...a napi fajljai megmaradnak", bool(list(D.day_dir(SYM).glob(f"{cur:%Y-%m}-*"))))


# ── OSSZEVONAS UTAN: ne toltse ujra a mar osszevont honapot ────────────────
# (A fustproba ezt VALODI hibakent fogta: az osszevonas torli a napi fajlokat,
#  es a letolto csak azokat nezte -> a marciust megegyszer lehuzta, majd arva
#  napi fajlok maradtak, mert a havi mar megvolt.)
hivott.clear()
st5 = D.download_symbol(SYM, start, end, {})
check_("osszevonas UTAN sem tolti ujra a honapot",
       st5["uj"] == 0 and not hivott, f"{st5['uj']} / {hivott}")
check_("...mind a 7 nap meglevonek szamit (a havi fajl a jel)",
       st5["meglevo"] == 7, str(st5["meglevo"]))

# arva napi fajlok egy mar osszevont honapbol -> a consolidate takaritja
arva = D.day_file(SYM, datetime(2024, 3, 5, tzinfo=timezone.utc))
D._write_atomic(pd.DataFrame({"time_msc": [1], "bid_pt": [1], "ask_pt": [2]}
                             ).astype("int64"), arva)
check_("arva napi fajl letezik a teszt elott", arva.exists())
D.consolidate(SYM)
check_("a consolidate eltakaritja az arva napi fajlt", not arva.exists())
check_("...a havi fajlt viszont nem bantja", D.month_file(SYM, 2024, 3).exists())


# ── a szerzodes, amit nem szabad elrontani ─────────────────────────────────
src = io.open(ROOT / "tools" / "download_ticks.py", encoding="utf-8").read()
check_("egy hivas = EGY nap (nem honap)", "d + timedelta(days=1)" in src)
check_("a havi osszevonas ParquetWriter-rel streamel",
       "ParquetWriter" in src and "write_table(tbl)" in src)
check_("Ctrl+C-re tisztan all le", "signal.signal(signal.SIGINT" in src)
check_("kapcsolat-vesztesnel ujracsatlakozik", "ensure_connected" in src)
check_("a mar osszevont honap is \"megvan\" jel", "kesz_honapok" in src)
check_("NINCS deduplikalas (a high/low levagodna)",
       "drop_duplicates" not in src)

import shutil
shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
