"""A `data/` mappa átrendezése — egyszeri, VISSZAVONHATÓ költöztetés (2026-10-08).

Mit csinál:
  1. Az OTTHONI bróker (a config `brokers` listájának első eleme) adatai a
     saját mappájukba kerülnek, ugyanúgy, mint a többi brókeré:
        feed   → data/brokers/<id>/   (m1, m15, h1, ticks, bars_manifest,
                                       server_offset.json, signal_journal, forward…)
        számla → data/accounts/<id>/  (engine_*, conductor, sl_moves, trades.csv…)
  2. A kutatási kimenetek és gyorsítótárak → data/research/<id>/
  3. A régi mentések és biztonsági másolatok → data/_archive/
  A KÖZÖS beállítások (optimized_params, risk_mode.json, execution_params,
  models, naplók, licenc…) a helyükön maradnak.

Használat:
    python tools/migrate_data_layout.py               # CSAK terv (semmit nem mozgat)
    python tools/migrate_data_layout.py --apply       # végrehajtás
    python tools/migrate_data_layout.py --undo data/_archive/layout_migration_<…>.json

⚠ ALAPBÓL NEM ÍR. Előbb a tervet nézd át.
⚠ FUTÓ MOTOR / FELÜLET MELLETT NEM FUT: az élő motor futás közben írja az
  állapotfájlokat; egy félig átköltözött számla-állapot pozíciót veszíthet.
⚠ SEMMIT NEM TÖRÖL. Csak átnevez (ugyanazon a meghajtón azonnali, a 30 GB-os
  tick-tárnál is), és minden lépést manifesztbe ír → `--undo` visszaállítja.
⚠ ÜTKÖZÉSNÉL MEGÁLL, MIELŐTT BÁRMIT MOZGATNA: ha a cél már létezik (és nem
  üres mappa), a teljes költöztetés elmarad.
⚠ ISMERETLEN elemet nem mozgat: amit egyik szabály sem fed, a helyén marad, és
  a terv külön listázza — a szabálylistát kell bővíteni, nem találgatni.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
from core import broker_paths as BP                                      # noqa: E402
from core import broker_profile                                          # noqa: E402

DATA = BP.DATA

# ── A SZABÁLYOK (a `data/` gyökerének elemeire, fnmatch-mintával) ────────────
FEED = ["m1", "m5", "m15", "m30", "h1", "h4", "d1", "ticks", "bars_manifest",
        "server_offset.json", "signal_journal", "forward",
        "tick_probe.csv", "symbol_scan.csv"]
FEED_MINTA = [".*.history.lock"]           # a gyertya-letöltő szimbólum-zárjai
ACCOUNT = ["engine_status.json", "engine_inbox", "engine_outbox",
           "engine_console.log", "conductor", "adopted_positions.json",
           "position_meta.json", "signal_delivery.csv", "sl_moves"]
COMMON = ["optimized_params", "risk_mode.json", "risky_mode.json",
          "correlation_mode.json", "execution_params", "models",
          "daily_jobs", "daily_jobs.json", "daily_jobs.*.claim",
          "build_mode.json", "backtest_prefs.json", "backtest_results",
          "licence_cache.json", "licence_token.json", "live_*.lock",
          "tradeforge.log", "tradeforge.log.[0-9]*", "opt_error.log",
          "ui_watchdog.log", "ui_preview", "lab.log", "lab_elrendezes.json",
          "lab_sablonok", "packs", "mt5_backtest", "build_csv",
          "mt5_backtest_result", "Mt4_Manual_backtest_result",
          "brokers", "accounts", "research", "_archive"]
ARCHIVE = ["_backup*", "_bars_backup*", "*.mentes*", "*_MENTES*", "regi_v[0-9]*"]
RESEARCH = ["search_*.parquet", "search_*.csv", "swing_*.parquet", "candle_*",
            "*_h4_trades*.parquet", "holdout_*.parquet", "jeloltek_*.json",
            "quiet_breakout_engine_*.parquet", "istvan_tcb_*", "ict2022_*",
            "rotation_*", "triangle_*", "regime_change.csv",
            "indicator_screen.csv", "intraday_screen.csv", "flow_*.csv",
            "longrun_*.csv", "wpr_longrun.csv", "alap_h1h4.parquet",
            "gate_ab*", "nested_ab_*", "sl_oracle_*", "seq_*.parquet",
            "outcomes", "flow", "event_time", "daily_params", "candle_draw",
            "lab_piac_teszt"]


def _illik(nev: str, mintak) -> bool:
    return any(fnmatch.fnmatchcase(nev, m) for m in mintak)


def plan(home_id: str) -> tuple[list, list]:
    """[(forrás, cél, csoport)] és az ismeretlen elemek listája."""
    lepesek, ismeretlen = [], []
    for p in sorted(DATA.iterdir(), key=lambda x: x.name.lower()):
        n = p.name
        # A sorrend számít: az archív-minta előbb (pl. `tradeforge.log.mentes-…`),
        # a közös utána, hogy a `brokers`/`accounts` sose mozduljon.
        if _illik(n, ARCHIVE):
            lepesek.append((p, DATA / "_archive" / n, "archív"))
        elif _illik(n, COMMON):
            continue
        elif n in FEED or _illik(n, FEED_MINTA):
            lepesek.append((p, DATA / "brokers" / home_id / n, "feed"))
        elif n in ACCOUNT:
            lepesek.append((p, DATA / "accounts" / home_id / n, "számla"))
        elif _illik(n, RESEARCH):
            lepesek.append((p, DATA / "research" / home_id / n, "kutatás"))
        else:
            ismeretlen.append(p)
    trades = BP.TRADES
    if trades.exists():
        lepesek.append((trades, DATA / "accounts" / home_id / "trades.csv", "számla"))
    return lepesek, ismeretlen


def _utkozesek(lepesek) -> list:
    rossz = []
    for src, dst, _ in lepesek:
        if dst.exists() and not (dst.is_dir() and not any(dst.iterdir())):
            rossz.append(dst)
    return rossz


def _futo_processzek() -> list:
    """Élő motor-zár, illetve futó Python/TradeForge processz (önmagunk kivételével)."""
    talalat = []
    from core import live_lock
    for z in DATA.glob("live_*.lock"):
        try:
            pid = int(json.loads(z.read_text(encoding="utf-8")).get("pid") or 0)
        except Exception:
            continue
        if pid and pid != os.getpid() and live_lock._pid_alive(pid):
            talalat.append(f"{z.name}: él a motor (pid {pid})")
    if os.name == "nt":
        try:
            ki = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                text=True, timeout=20).stdout
        except Exception:
            ki = ""
        for sor in ki.splitlines():
            m = re.match(r'"([^"]+)","(\d+)"', sor)
            if not m:
                continue
            nev, pid = m.group(1).lower(), int(m.group(2))
            if pid == os.getpid() or pid == os.getppid():
                continue
            if nev.startswith("tradeforge") or nev in ("python.exe", "pythonw.exe"):
                talalat.append(f"{m.group(1)} (pid {pid})")
    return talalat


def _meret(p: Path) -> str:
    try:
        if p.is_file():
            b = p.stat().st_size
        else:
            b = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return "?"
    for e in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {e}"
        b /= 1024
    return f"{b:.1f} TB"


def apply(lepesek) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    (DATA / "_archive").mkdir(parents=True, exist_ok=True)
    manifest = DATA / "_archive" / f"layout_migration_{stamp}.json"
    kesz = []
    try:
        for src, dst, csoport in lepesek:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_dir() and not any(dst.iterdir()):
                dst.rmdir()                       # üres célmappa (pl. egy korábbi mkdir)
            os.rename(src, dst)
            kesz.append({"src": str(src), "dst": str(dst), "group": csoport})
    finally:
        # a manifeszt MINDIG kiíródik — egy félbeszakadt futás is visszavonható
        manifest.write_text(json.dumps({"created": stamp, "moves": kesz}, indent=1,
                                       ensure_ascii=False), encoding="utf-8")
    return manifest


def undo(manifest: Path) -> int:
    d = json.loads(manifest.read_text(encoding="utf-8"))
    lepesek = list(reversed(d.get("moves") or []))
    rossz = [m["src"] for m in lepesek if Path(m["src"]).exists()]
    if rossz:
        print("NEM vonom vissza — a régi helyen már van valami:")
        for r in rossz:
            print("   ", r)
        return 1
    for m in lepesek:
        Path(m["src"]).parent.mkdir(parents=True, exist_ok=True)
        os.rename(m["dst"], m["src"])
    print(f"{len(lepesek)} lépés visszavonva.")
    return 0


def main() -> int:
    applog.harden_console()
    args = sys.argv[1:]
    if args[:1] == ["--undo"]:
        if len(args) < 2:
            print("Használat: --undo <manifeszt.json>")
            return 2
        if _futo_processzek() and "--force" not in args:
            print("Fut a program — előbb állítsd le (vagy --force).")
            return 1
        return undo(Path(args[1]))

    cfg = BP._config()
    home = broker_profile.profiles(cfg)[0]
    lepesek, ismeretlen = plan(home.id)

    print(f"Otthoni bróker: {home.id}   (data: {DATA})\n")
    w = max([len(s.name) for s, _, _ in lepesek] + [10])
    for csoport in ("feed", "számla", "kutatás", "archív"):
        sorok = [(s, d) for s, d, c in lepesek if c == csoport]
        if not sorok:
            continue
        print(f"── {csoport} ({len(sorok)}) ──")
        for s, d in sorok:
            print(f"  {s.name.ljust(w)}  {_meret(s):>8}  →  {d.relative_to(BP._BASE)}")
        print()
    if ismeretlen:
        print(f"── ISMERETLEN, a helyén marad ({len(ismeretlen)}) ──")
        for p in ismeretlen:
            print(f"  {p.name}")
        print()

    utk = _utkozesek(lepesek)
    if utk:
        print("ÜTKÖZÉS — a cél már létezik, NEM mozgatok semmit:")
        for u in utk:
            print("   ", u)
        return 1

    if "--apply" not in args:
        print("NEM mozgattam semmit (terv). Végrehajtás:  python tools/migrate_data_layout.py --apply")
        return 0

    fut = _futo_processzek()
    if fut and "--force" not in args:
        print("Fut a program — előbb állítsd le a felületet ÉS a motort "
              "(python main.py engine-stop):")
        for f in fut:
            print("   ", f)
        return 1

    manifest = apply(lepesek)
    print(f"{len(lepesek)} elem átköltöztetve. Visszavonás:")
    print(f"    python tools/migrate_data_layout.py --undo {manifest.relative_to(BP._BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
