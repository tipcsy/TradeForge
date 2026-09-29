"""
Historikus M15 és M1 adatok letöltése MT5-ből minden engedélyezett párhoz.

Stratégia (a Trading-with-ai projektből átvéve):
  - Alap TF (M15, M1): tick -> resample, havi bontásban.
    Ez adja a maximális visszatekintési időszakot (2-3 év) és az avg_spread mezőt.
  - Ha a fájl már létezik: csak a hiányzó (gap) adatokat tölti le és fűzi hozzá.

Futtatás: python tools/download_history.py
"""

import json
import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.broker_adapter import mt5          # noqa: E402  (szimbólum-alias + bróker-idő)

# Importáljuk a globális MT5 lockot — ha elérhető (GUI-ból hívva); egyébként dummy
try:
    from core.mt5_connector import MT5_LOCK as _MT5_LOCK
except Exception:
    import threading as _threading
    _MT5_LOCK = _threading.Lock()  # standalone futásnál saját lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import mt5_connector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M15": mt5.TIMEFRAME_M15,
    # ⚠ H1: NATÍV gyertyából (nincs a RESAMPLE-ben → nincs tick-út). Eddig
    # hiányzott innen, és a H1 minden letöltése 'H1' KeyError-ral elbukott
    # (2026-09-23 óta minden indításkor, minden páron).
    "H1":  mt5.TIMEFRAME_H1,
}

RESAMPLE = {
    "M1":  "1min",
    "M15": "15min",
}

# ⚠ A HELYI M1-BŐL ÉPÍTETT IDŐSÍKOK (2026-09-29): a H1-et (és a többi M1-nél
# nagyobbat) NEM kérjük a terminálból — minden terminál-hívás a motor és a
# felület hívásaival osztozik (egy GerMid50 H1 lekérés 5,6 mp-re megakasztotta
# a felületet). Az M1 fájl úgyis megvan; ugyanabból az adatból épül, mint az
# M15, és egy teljes újraépítés tört másodperc.
DERIVED = {
    "M5":  "5min",
    "M30": "30min",
    "H1":  "1h",
    "H4":  "4h",
}


# ---------------------------------------------------------------------------
# Segédfüggvények (tick -> bar konverzió)
# ---------------------------------------------------------------------------

def _next_month(dt: datetime) -> datetime:
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1,
                          hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(month=dt.month + 1, day=1,
                      hour=0, minute=0, second=0, microsecond=0)


def _ticks_to_bars(ticks_raw, freq: str) -> pd.DataFrame:
    """MT5 tick tömb -> OHLCV DataFrame (UTC index, avg_spread mezővel)."""
    df = pd.DataFrame(ticks_raw)
    if df.empty:
        return pd.DataFrame()

    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("dt").sort_index()

    has_bid  = "bid"  in df.columns
    has_ask  = "ask"  in df.columns
    has_last = "last" in df.columns

    # FONTOS: a gyertyák BID árból épülnek — az MT5 chart és a Strategy Tester is
    # BID-et rajzol (ask-gyertya nincs; az ASK csak a végrehajtásnál jelenik meg:
    # BUY belép ask-on, SELL kilép ask-on). Így az indikátoraink és a trigger-
    # ellenőrzéseink UGYANAZON a soron dolgoznak, mint az MT5 → a backtest és az
    # MT5-replay összevethető. Az `avg_spread` (ask−bid) mellé megy, ebből áll elő
    # az ask-sorozat a motorban (ask = bid + spread).
    if has_bid and has_ask:
        df["mid"] = df["bid"]                      # BID a bar-alap (nem közép!)
        valid = (df["bid"] > 0) & (df["ask"] > 0) & (df["ask"] > df["bid"])
        df["spread"] = float("nan")
        df.loc[valid, "spread"] = df.loc[valid, "ask"] - df.loc[valid, "bid"]
    elif has_bid:
        df["mid"] = df["bid"]
    elif has_last:
        df["mid"] = df["last"]                     # tőzsdei (last) szimbólum
    else:
        return pd.DataFrame()

    df = df[df["mid"] > 0].dropna(subset=["mid"])
    if df.empty:
        return pd.DataFrame()

    ohlcv = df["mid"].resample(freq).ohlc()
    ohlcv["volume"] = df["mid"].resample(freq).count()
    ohlcv = ohlcv.dropna(subset=["open"])
    ohlcv = ohlcv[ohlcv["volume"] > 0]

    if "spread" in df.columns:
        # avg_spread: a baron BELÜLI átlag — az intrabar SL/TP-trigger becsléséhez.
        ohlcv["avg_spread"] = df["spread"].resample(freq).mean()
        # close_spread: az UTOLSÓ tick spreadje a baron — a BELÉPŐHÖZ ez a pontos,
        # mert a jelzés (és így a belépő) a gyertya ZÁRÁSÁN keletkezik.
        ohlcv["close_spread"] = df["spread"].resample(freq).last()

    return ohlcv


# ⚠ NAPI DARABOK, EGY LETÖLTÉS TÖBB IDŐSÍKRA (2026-09-29, demó-próba).
# Az új instrumentum teljes előzménye eddig HAVI darabokban kérte a tickeket
# (egy hónap = több millió tick), a kérés alatt fogta a processz MT5-zárját, és
# minden idősíkhoz ÚJRA letöltötte ugyanazokat (M15, aztán M1). Élesben ez
# 5+ percre megállította a motort ÉS a felületet (NZDJPY felvétele, mérve: a
# jelzés-napló 316 mp-ig nem frissült). Most:
#   • napi darabok, köztük rövid szünet — a terminál közben a motort is
#     kiszolgálja, és az MT5-zár egyszerre csak rövid ideig foglalt;
#   • a tickek EGYSZER jönnek le, és ugyanabból épül minden kért idősík;
#   • a pontos spread-oszlopok (avg_spread, close_spread) megmaradnak — a
#     natív gyertya spreadje ~3× optimista, a backtest költségmodellje ebből él.
_NAPI_SZUNET = 0.02


def _download_ticks_multi(symbol: str, tf_strs, start: datetime,
                          end: datetime) -> dict:
    """Bars több idősíkra, EGY tick-letöltésből, NAPI bontásban.
    Visszatér: {idősík: OHLCV DataFrame} (üres DataFrame, ahol nincs adat)."""
    tf_strs = [t for t in tf_strs if t in RESAMPLE]
    if not tf_strs:
        # ⚠ NINCS tick-építésű idősík → NINCS tick-letöltés. A v3.120.0 itt
        # 730 napi tick-kérést indított a H1-hez a semmiért (egy gyertya sem
        # épült belőle), és a terminál szerver-szinkronja 100+ mp-re megfagyasztotta
        # a motort és a felületet — páronként ismételve (demó-próba, 20:55).
        return {}
    frames = {t: [] for t in tf_strs}
    cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
    allapot = {"ho": cur.strftime("%Y-%m"), "tick": 0, "t0": time.time()}

    def _havi_sor():
        # EGY sor / hónap (a GUI sorosan olvassa a stdout-ot)
        print(f"      {allapot['ho']} ... {allapot['tick']:>8,} tick -> "
              + ", ".join(tf_strs)
              + f"  ({time.time() - allapot['t0']:.1f}s)", flush=True)

    while cur < end:
        nap_vege = min(cur + timedelta(days=1), end)
        if cur.strftime("%Y-%m") != allapot["ho"]:
            _havi_sor()
            allapot.update(ho=cur.strftime("%Y-%m"), tick=0, t0=time.time())
        with _MT5_LOCK:
            ticks_raw = mt5.copy_ticks_range(symbol, cur, nap_vege, mt5.COPY_TICKS_ALL)
        if ticks_raw is not None and len(ticks_raw) > 0:
            allapot["tick"] += len(ticks_raw)
            for t in tf_strs:
                ohlcv = _ticks_to_bars(ticks_raw, RESAMPLE[t])
                if not ohlcv.empty:
                    frames[t].append(ohlcv)
        cur = nap_vege
        time.sleep(_NAPI_SZUNET)
    _havi_sor()

    out = {}
    for t in tf_strs:
        if frames[t]:
            c = pd.concat(frames[t])
            out[t] = c[~c.index.duplicated(keep="last")].sort_index()
        else:
            out[t] = pd.DataFrame()
    return out


def _download_via_ticks(symbol: str, tf_str: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Bars egy idősíkra (a több-idősíkos, napi darabolású letöltő egy esete)."""
    return _download_ticks_multi(symbol, [tf_str], start, end).get(tf_str, pd.DataFrame())


# ---------------------------------------------------------------------------
# Gap feltöltés meglévő parquet-hez
# ---------------------------------------------------------------------------

def _fill_gap(out_file: Path, symbol: str, tf_str: str, end: datetime) -> bool:
    """
    Meglévő parquet fájlba hozzáírja az utolsó bar óta hiányzó adatokat.
    Visszatér: True ha sikeres, False ha nem volt mit tölteni.
    """
    existing = pd.read_parquet(out_file)
    last_dt = existing.index[-1]

    # Timezone-aware -> naive UTC összehasonlításhoz
    if last_dt.tzinfo is not None:
        last_dt_naive = last_dt.replace(tzinfo=None)
    else:
        last_dt_naive = last_dt

    gap_h = (end.replace(tzinfo=None) - last_dt_naive).total_seconds() / 3600
    if gap_h < 1:
        log.info("%s %s — naprakész, kihagyva.", symbol, tf_str)
        return True

    log.info("%s %s — gap %.0fh -> frissítés (natív bar)...", symbol, tf_str, gap_h)
    from_dt = last_dt.replace(tzinfo=timezone.utc) if last_dt.tzinfo is None else last_dt
    from_dt = from_dt + pd.Timedelta(minutes=1)

    tf_mt5 = TF_MAP[tf_str]
    with _MT5_LOCK:
        new_raw = mt5.copy_rates_range(symbol, tf_mt5,
                                       from_dt.replace(tzinfo=None),
                                       end.replace(tzinfo=None))
    if new_raw is None or len(new_raw) == 0:
        log.warning("%s %s — gap feltöltés: nincs adat (%s)", symbol, tf_str, mt5.last_error())
        return False

    df_new = pd.DataFrame(new_raw)
    df_new["time"] = pd.to_datetime(df_new["time"], unit="s", utc=True)
    df_new = df_new.set_index("time")
    df_new = df_new[["open", "high", "low", "close", "tick_volume"]].rename(
        columns={"tick_volume": "volume"}
    )

    # Timezone egységesítés: mindkettő UTC-aware legyen
    if existing.index.tzinfo is None:
        existing.index = existing.index.tz_localize("UTC")
    if df_new.index.tzinfo is None:
        df_new.index = df_new.index.tz_localize("UTC")

    combined = pd.concat([existing, df_new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.to_parquet(out_file)
    log.info("%s %s — +%d bar hozzáadva -> összesen %d", symbol, tf_str, len(df_new), len(combined))
    return True


# ---------------------------------------------------------------------------
# Egy pár letöltése
# ---------------------------------------------------------------------------

_NATIV_SZUNET = 0.05


def _native_bars(symbol: str, tf_str: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Natív gyertyák NAPI darabokban, a jelentől VISSZAFELÉ, rövid szünetekkel.

    ⚠ MÉRVE (2026-09-29, CADJPY, a terminál gyorsítótárában NEM volt): 2 év M1
    napi darabokban ~30 mp alatt jött le a szerverről, és közben egy második
    kliens 0,25 mp-enkénti ár-lekérdezése SOSEM várt 0,29 mp-nél többet — a
    terminál végig kiszolgálta a motort és a felületet. (A TICK-előzmény nem
    ilyen: az AUDJPY napi darabokban is 10 percre megállította — ezért az
    alapból KI.)

    ⚠ A terminál csak a „Max. gyertya a charton" (terminal_info().maxbars,
    alapból 100 000) legutóbbi gyertyáját adja: 2 év M1 (~740 ezer) EGY
    kérésben `Invalid params` → a GBPJPY M1 üres maradt (demó-próba,
    2026-09-29). Visszafelé haladva ott állunk meg, ahol a terminál már nem ad
    adatot — a kapott szakasz FOLYTONOS (a régi hónapokból jövő 1-1 gyertya
    lyukas előzményt adna)."""
    tf_mt5 = TF_MAP[tf_str]
    darabok = []
    veg = end
    ures = 0                           # egymás utáni üres napok (hétvége, ünnep)
    ho, t0 = veg.strftime("%Y-%m"), time.time()
    while veg > start:
        # az aktuális nap eleje (az első kérés csak a mai részt kéri)
        eleje = max(start, (veg - timedelta(microseconds=1)).replace(
            hour=0, minute=0, second=0, microsecond=0))
        with _MT5_LOCK:
            raw = mt5.copy_rates_range(symbol, tf_mt5, eleje.replace(tzinfo=None),
                                       veg.replace(tzinfo=None))
        if raw is None or len(raw) == 0:
            ures += 1
            if ures >= 10:             # innen visszafelé a terminál nem ad adatot
                break
        else:
            ures = 0
            darabok.append(pd.DataFrame(raw))
        if eleje.strftime("%Y-%m") != ho:
            # EGY sor / hónap (a szülő soronként olvassa)
            print(f"      {ho} ... {tf_str}  ({time.time() - t0:.1f}s)", flush=True)
            ho, t0 = eleje.strftime("%Y-%m"), time.time()
        veg = eleje
        time.sleep(_NATIV_SZUNET)
    if not darabok:
        return pd.DataFrame()
    df = pd.concat(darabok[::-1])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if df.index[0] - start > timedelta(days=7):
        log.warning("%s %s — natív gyertya CSAK %s-tól (a terminál 'Max. gyertya a "
                    "charton' korlátja); a teljes előzményhez: MT5 Eszközök → "
                    "Beállítások → Chartok → Korlátlan, vagy --ticks.",
                    symbol, tf_str, str(df.index[0])[:10])
    return df[["open", "high", "low", "close", "tick_volume"]].rename(
        columns={"tick_volume": "volume"})


def download_pair(symbol: str, tf_str: str, start: datetime, overwrite: bool, end: datetime,
                  ticks: bool = True) -> bool:
    from core import broker_paths                 # 0029: az aktív bróker mappája
    out_dir = broker_paths.feed(ROOT / "data" / tf_str.lower())
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{symbol}.parquet"

    if not mt5.symbol_select(symbol, True):
        log.warning("%s — nem érhető el ezen a brókerszerveren, kihagyva.", symbol)
        return False

    # Ha létezik és nem overwrite: gap feltöltés
    if out_file.exists() and not overwrite:
        return _fill_gap(out_file, symbol, tf_str, end)

    # Teljes letöltés tick -> resample módszerrel — CSAK tick-építésű idősíkra;
    # a többi (H1) közvetlenül natív gyertyából.
    # `ticks=False`: az ensure_history új instrumentuma — lásd ott (a terminál
    # tick-szinkronja a motort is megállítja)
    if tf_str in RESAMPLE and ticks:
        log.info("%s %s — tick letöltés (%s -> %s)...", symbol, tf_str,
                 start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        ohlcv = _download_via_ticks(symbol, tf_str, start, end)
    else:
        ohlcv = pd.DataFrame()

    if ohlcv.empty:
        # natív gyertya (tick nélkül kérve, vagy nincs tick adat, pl. kripto CFD)
        log.info("%s %s — natív gyertya letöltés...", symbol, tf_str)
        ohlcv = _native_bars(symbol, tf_str, start, end)
        if not ohlcv.empty:
            log.info("%s %s — natív bar fallback: %d gyertya [%s → %s]",
                     symbol, tf_str, len(ohlcv),
                     str(ohlcv.index[0])[:10], str(ohlcv.index[-1])[:10])

    if ohlcv.empty:
        log.warning("%s %s — nincs letölthető adat (tick és natív bar is üres).", symbol, tf_str)
        return False

    ohlcv.to_parquet(out_file)
    log.info("%s %s — %d gyertya mentve -> %s  [%s -> %s]",
             symbol, tf_str, len(ohlcv), out_file.name,
             str(ohlcv.index[0])[:10], str(ohlcv.index[-1])[:10])
    return True


# ---------------------------------------------------------------------------
# Egy instrumentum előzményeinek biztosítása (GUI + CLI közös útja)
# ---------------------------------------------------------------------------

# Per-szimbólum zár: a GUI-ban két út is kérhet letöltést UGYANARRA a párra
# (új instrumentum auto-letöltése + Opt/Backtest) — ugyanazt a parquet-et írnák
# egyszerre. A zár sorba állítja őket (a második már a kész fájlt találja).
#
# FONTOS: az új instrumentum letöltése KÜLÖN PROCESSZBEN fut (a GUI ne fagyjon a
# GIL-től), a Backtest/Opt út viszont a GUI processzében hív ensure_history-t —
# ezért a zárnak PROCESSZEK KÖZÖTT is érvényesnek kell lennie. Egy in-process
# threading.Lock (gyors, ugyanazon processz szálai közt) + egy fájl-alapú zár
# (processzek közti) párosa adja ezt.
_HISTORY_LOCKS: dict = {}
_HISTORY_LOCKS_GUARD = threading.Lock()


def _thread_lock(symbol: str) -> threading.Lock:
    with _HISTORY_LOCKS_GUARD:
        return _HISTORY_LOCKS.setdefault(symbol, threading.Lock())


try:                                    # Windows
    import msvcrt

    def _flock_acquire(fh):
        while True:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.2)         # foglalt — várunk a másik processzre

    def _flock_release(fh):
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
except ImportError:                     # POSIX
    import fcntl

    def _flock_acquire(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _flock_release(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


from contextlib import contextmanager
from core.i18n import t as _t


@contextmanager
def _history_lock(symbol: str):
    """Per-szimbólum zár, ami PROCESSZEK KÖZÖTT is soroba állít (lásd fent)."""
    with _thread_lock(symbol):
        lock_dir = ROOT / "data"
        lock_dir.mkdir(parents=True, exist_ok=True)
        fh = open(lock_dir / f".{symbol}.history.lock", "w")
        try:
            _flock_acquire(fh)
            yield
        finally:
            try:
                _flock_release(fh)
            finally:
                fh.close()


def _derive_from_m1(m1_file: Path, out_file: Path, symbol: str, tf_str: str) -> bool:
    """`tf_str` (M15, H1, H4, ...) a helyi M1 fájlból — terminál-hívás NÉLKÜL.
    Mindig teljes újraépítés (tört másodperc), így nincs külön gap-fill út."""
    m1 = pd.read_parquet(m1_file)
    if m1.empty:
        return False
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    for col, how in (("volume", "sum"), ("tick_volume", "sum"),
                     ("avg_spread", "mean"), ("close_spread", "last"),
                     ("spread", "mean")):
        if col in m1.columns:
            agg[col] = how
    bars = (m1[list(agg)].resample(RESAMPLE.get(tf_str) or DERIVED[tf_str],
                                   label="left", closed="left")
            .agg(agg).dropna(subset=["open"]))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(out_file)
    log.info("%s %s — %d gyertya az M1-ből -> %s", symbol, tf_str, len(bars),
             out_file.name)
    return True


def ensure_history(symbol: str, cfg: dict, tf_labels=("M15", "M1"),
                   status=None, ticks: bool = False) -> tuple[bool, str]:
    """Gondoskodik róla, hogy `symbol`-nak legyen letöltött előzmény-adata.

    Meglévő parquet → gap feltöltés; hiányzó → TELJES letöltés a config
    `data.history_start_date`-jétől. EGY hely, amit a GUI (új instrumentum
    felvétele, Opt, Backtest) és a CLI is hív — így nem csúszhat szét, MIKOR
    töltünk le adatot.

    Szimbólumonként SOROSÍTVA fut (lásd `_history_lock`).

    `status`: opcionális callback(str) a haladás visszajelzéséhez (GUI-sor).
    Visszaad: (van-e MOST már adat minden kért TF-hez, rövid üzenet).
    """
    with _history_lock(symbol):
        return _ensure_history(symbol, cfg, tf_labels, status, ticks)


def _ensure_history(symbol, cfg, tf_labels, status, ticks=False) -> tuple[bool, str]:
    def _say(msg):
        if status is not None:
            try:
                status(msg)
            except Exception:
                pass

    def _pq(tf):
        from core import broker_paths
        return broker_paths.feed(ROOT / "data" / tf.lower() / f"{symbol}.parquet")

    end_dt  = datetime.now(timezone.utc)
    missing = [tf for tf in tf_labels if not _pq(tf).exists()]

    # MINDENKI ugyanazt a connect()-et használja → egységes terminál (config
    # mt5.path) + fiók-ellenőrzés. (A connect() maga foglalja a MT5_LOCK-ot,
    # ezért NEM tesszük külön lock-blokkba — az deadlock lenne.)
    if not mt5_connector.connect(cfg):
        if missing:
            return False, (f"MT5 offline — {symbol}: nincs letöltött adat "
                           f"({', '.join(missing)}).")
        return True, "MT5 offline — a meglévő adatokkal."

    hs = datetime.strptime(
        (cfg.get("data") or {}).get("history_start_date", "2024-10-01"),
        "%Y-%m-%d",
    ).replace(tzinfo=timezone.utc)

    # ⚠ ÚJ INSTRUMENTUM: NATÍV GYERTYA, NEM TICK (demó-próba, 2026-09-29).
    # A terminál egyszerre EGY kérést szolgál ki: egy még nem látott szimbólum
    # tick-előzményét előbb a szerverről szinkronizálja (Ger40: 110 mp az első
    # hónap), és addig a motor ÉS a felület MT5-hívásai is állnak — a külön
    # processz ezen nem segít (AUDJPY felvétele: a motor 3+ percig állt). A
    # natív gyertya másodpercek; a pontos (tickből számolt) spread-oszlopot
    # kifejezett kérésre (`ticks=True`, CLI `--ticks`) lehet pótolni.
    uj_tick = ([tf for tf in tf_labels if not _pq(tf).exists() and tf in RESAMPLE]
               if ticks else [])
    if uj_tick:
        _say(f"Letöltés {', '.join(uj_tick)}...")
        try:
            if mt5.symbol_select(symbol, True):
                log.info("%s %s — tick letöltés (%s -> %s)...", symbol,
                         ",".join(uj_tick), hs.strftime("%Y-%m-%d"),
                         end_dt.strftime("%Y-%m-%d"))
                for tf, df in _download_ticks_multi(symbol, uj_tick, hs, end_dt).items():
                    if not df.empty:
                        pq = _pq(tf)
                        pq.parent.mkdir(parents=True, exist_ok=True)
                        df.to_parquet(pq)
                        log.info("%s %s — %d gyertya mentve -> %s", symbol, tf,
                                 len(df), pq.name)
            else:
                log.warning("%s — nem érhető el ezen a brókerszerveren.", symbol)
        except Exception as ex:
            log.warning("%s — tick-letöltés hiba: %s", symbol, ex)

    # az M1 (ha kell) a származtatott idősíkok ELŐTT — azok ebből épülnek
    sorrend = sorted(tf_labels, key=lambda t: t != "M1")
    for tf in sorrend:
        pq = _pq(tf)
        try:
            # ÚJ M15 is az M1-ből (egy letöltés, ugyanabból az adatból); a
            # meglévő (tickből épült) M15 marad, és a szokott módon pótlódik
            uj_m15 = tf == "M15" and not pq.exists() and not ticks
            if (tf in DERIVED or uj_m15) and _pq("M1").exists():
                _say(f"{tf} az M1-ből...")
                _derive_from_m1(_pq("M1"), pq, symbol, tf)
            elif pq.exists():
                if tf in uj_tick:
                    continue                      # most töltöttük le teljesen
                _say(f"Gap-fill {tf}...")
                _fill_gap(pq, symbol, tf, end_dt)
            else:
                _say(f"Letöltés {tf}...")
                download_pair(symbol, tf, hs, overwrite=False, end=end_dt,
                              ticks=ticks)
        except Exception as ex:
            log.warning("%s %s — előzmény-letöltés hiba: %s", symbol, tf, ex)

    failed = [tf for tf in tf_labels if not _pq(tf).exists()]
    if failed:
        return False, (f"{symbol}: nem sikerült az előzmény-letöltés "
                       f"({', '.join(failed)}) — nem érhető el ezen a "
                       f"brókerszerveren?")
    return True, f"{symbol}: adat kész."


def ensure_history_subprocess(symbol: str, tf_labels=("M15", "M1"),
                              broker_id: str | None = None, on_line=None,
                              timeout: float | None = None) -> tuple[bool, str]:
    """Az `ensure_history` KÜLÖN PROCESSZBEN — a MOTOR és a felület processzéből.

    ⚠ MIÉRT (demó-próba, 2026-09-29): a motor az új instrumentum előzményét a
    SAJÁT processzében töltötte (`ensure_history` szálon): a tick-letöltés fogta
    az MT5-zárat, a tick→gyertya építés a Python GIL-t — a motor ÉS a (közös
    processzű) felület 5+ percre megfagyott. Külön processzben saját GIL-je van,
    és a napi darabolás miatt a terminál is kiszolgálja közben a motort.

    `broker_id`: a bróker-profil (több brókernél a jó terminál / adatmappa).
    `on_line(sor)`: a gyerek stdout-sorai (haladás). Visszaad: (siker, utolsó sor)."""
    import os
    import subprocess
    cmd = [sys.executable, "-u", str(Path(__file__).resolve()),
           "--symbol", symbol, "--tfs", ",".join(tf_labels)]
    if broker_id:
        cmd += ["--broker", str(broker_id)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    kw = dict(cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
              text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
              stdin=subprocess.DEVNULL)
    if os.name == "nt":
        kw["creationflags"] = 0x08000000           # CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(cmd, **kw)
    except Exception as ex:
        return False, str(ex)
    utolso = ""
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        utolso = line
        if on_line is not None:
            try:
                on_line(line)
            except Exception:
                pass
    try:
        kod = proc.wait(timeout=timeout)
    except Exception:
        proc.kill()
        return False, utolso or "időtúllépés"
    return kod == 0, utolso


# ---------------------------------------------------------------------------
# Belépési pont
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=_t("cli.download_history.historikus_m15_m1_adat_letolte"))
    parser.add_argument(
        "--symbol",
        help=_t("cli.download_history.egyetlen_szimbolum_letoltese_a"))
    parser.add_argument(
        "--tfs", default="M15,M1",
        help=_t("cli.download_history.vesszovel_elvalasztott_idokere"))
    parser.add_argument(
        "--broker", default=None,
        help="0029: a bróker-profil azonosítója (több brókernél a jó terminál)")
    parser.add_argument(
        "--ticks", action="store_true",
        help="új szimbólumnál a teljes TICK-előzmény (pontos spread) — lassú, és "
             "a terminál szinkronja alatt a futó motort is megállítja")
    args = parser.parse_args()

    from strategy.settings import load_config
    if args.broker:
        # a betöltés ELŐTT — a load_config már a bróker értékeit rakja a párokra
        from core import broker_profile
        broker_profile.set_override(args.broker)
    cfg = load_config(ROOT / "config.json")

    # ── Egy-szimbólumos mód (GUI külön processz) ─────────────────────────────
    # A haladást stdout-ra írjuk (a szülő GUI sorosan olvassa és a sor-státuszba
    # + a naplóba teszi). A connect()-et az ensure_history maga intézi.
    if args.symbol:
        tf_labels = tuple(t.strip() for t in args.tfs.split(",") if t.strip()) \
                    or ("M15", "M1")

        def _st(msg):
            print(f"[státusz] {msg}", flush=True)

        ok, msg = ensure_history(args.symbol, cfg, tf_labels, status=_st,
                                 ticks=args.ticks)
        try:
            mt5_connector.disconnect()
        except Exception:
            pass
        # ⚠ az eredmény az UTOLSÓ sor — a szülő ezt teszi a hibaüzenetbe (előtte
        # a „MT5 kapcsolat lezárva." került oda, az ok helyett)
        print(msg, flush=True)
        sys.exit(0 if ok else 1)

    if not mt5_connector.connect(cfg):
        sys.exit(1)

    start_dt = datetime.strptime(
        cfg["data"]["history_start_date"], "%Y-%m-%d"
    ).replace(tzinfo=timezone.utc)
    end_dt   = datetime.now(timezone.utc)
    overwrite = cfg["data"].get("overwrite_existing", False)

    pairs = {s: p for s, p in cfg["pairs"].items()
             if isinstance(p, dict) and p.get("enabled", False)}
    log.info("%d aktív pár letöltése indul...", len(pairs))

    ok = err = 0
    for symbol in pairs:
        for tf in ("M15", "M1"):
            if download_pair(symbol, tf, start_dt, overwrite, end_dt):
                ok += 1
            else:
                err += 1

    mt5_connector.disconnect()
    log.info("Kész. Sikeres: %d | Hibás: %d", ok, err)


if __name__ == "__main__":
    main()
