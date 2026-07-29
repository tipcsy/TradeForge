"""
Elárvult adatfájlok kiszűrése — modellek, optimalizált paraméterek, SL-naplók.

Egy instrumentum eltávolítása a configból NEM takarítja el a hozzá tartozó
fájlokat. Ezek utána is ott maradnak, és három módon zavarnak:

  • **Félrevezetnek.** Egy `DJ30.json` az `optimized_params` alatt azt sugallja,
    hogy a DJ30 be van állítva — pedig a configban nincs is.
  • **Kis-nagybetű.** A `sl_moves/GER40.csv` a `Ger40` átnevezése ELŐTTI korszakból
    való; a motor a `Ger40.csv`-t írja, a régi fájlt már senki nem olvassa.
  • **Helyet foglalnak** (a `.pkl` modellek MB-osak).

Az eszköz alapból CSAK FELSOROL. A `--delete` töröl — de előbb nézd át a listát:
ha egy instrumentumot csak IDEIGLENESEN vettél ki a configból, a hozzá tartozó
optimalizálás visszavételkor újra kellene.

Használat:
    python tools/cleanup_orphans.py            # csak felsorol
    python tools/cleanup_orphans.py --delete   # tenylegesen torol
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def configured_symbols() -> set:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return {s for s, v in (cfg.get("pairs") or {}).items() if isinstance(v, dict)}


def _case_sensitive_fs() -> bool:
    """Kis-nagybetű-ÉRZÉKENY-e a `data/` fájlrendszere? Windows/macOS: nem.
    Ténylegesen kipróbáljuk (a platform-név nem elég megbízható: hálózati és
    konténeres kötések máshogy viselkedhetnek)."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory(dir=str(DATA) if DATA.exists() else None) as d:
            probe = Path(d) / "CaseProbe.tmp"
            probe.write_text("x", encoding="ascii")
            return not (Path(d) / "caseprobe.tmp").exists()
    except Exception:
        return False        # bizonytalanság esetén NEM jelölünk (nem törlünk)


def scan(symbols: set) -> list:
    """[(fájl, indok)] — az elárvult fájlok. A szimbólum-nevet a fájlnév ELEJÉRŐL
    olvassuk ki (a `_study.done`, `_trials.csv`, `_hours.json` utótagokat levágva)."""
    SUFFIXES = ("_study.done", "_trials.csv", "_hours.json", "_study.db")
    out = []

    def sym_of(name: str) -> str:
        for suf in SUFFIXES:
            if name.endswith(suf):
                return name[: -len(suf)]
        return Path(name).stem

    # KIS-NAGYBETŰ. Windows/macOS alatt a fájlrendszer ÉRZÉKETLEN, tehát a
    # `GER40.csv` és a `Ger40.csv` UGYANAZ a fájl — a motor a config szerinti
    # alakkal nyitja meg, és a meglévő tartalomhoz fűz. Ilyenkor a más írásmód NEM
    # árva, hanem az ÉLŐ napló; törölni ADATVESZTÉS lenne. (Ez egyszer meg is
    # történt: a `sl_moves/GER40.csv` a Ger40 aktív SL-naplója volt.)
    # Csak KIS-NAGYBETŰ-ÉRZÉKENY fájlrendszeren van értelme külön kezelni.
    case_sensitive = _case_sensitive_fs()
    lower = {s.lower(): s for s in symbols}

    for sub in ("models", "optimized_params", "sl_moves"):
        base = DATA / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            s = sym_of(path.name)
            if s in symbols:
                continue
            if not case_sensitive and s.lower() in lower:
                continue          # a fájlrendszer szemében UGYANAZ a fájl → nem árva
            if s.lower() in lower:
                out.append((path, f"kis-nagybetu elteres: '{s}' helyett '{lower[s.lower()]}' az ervenyes"))
            else:
                out.append((path, f"'{s}' nincs a configban"))
    return out


def main() -> int:
    from core import applog
    applog.harden_console()   # cp1250 konzol: az ekezetek ne dobjanak kivetelt
    delete = "--delete" in sys.argv
    symbols = configured_symbols()
    orphans = scan(symbols)

    print(f"\nConfig-beli instrumentumok ({len(symbols)}): {', '.join(sorted(symbols))}")
    if not orphans:
        print("\nNincs elárvult fájl.")
        return 0

    total = sum(p.stat().st_size for p, _ in orphans if p.exists())
    print(f"\n{len(orphans)} elárvult fájl ({total / 1024:.0f} kB):\n")
    w = max(len(str(p.relative_to(ROOT))) for p, _ in orphans)
    for p, why in orphans:
        print(f"  {str(p.relative_to(ROOT)).ljust(w)}   {why}")

    if not delete:
        print("\nNEM töröltem semmit. Ha átnézted és mehet:")
        print("    python tools/cleanup_orphans.py --delete")
        return 0

    n = 0
    for p, _ in orphans:
        try:
            p.unlink()
            n += 1
        except OSError as e:
            print(f"  NEM sikerült: {p} — {e}")
    print(f"\n{n} fájl törölve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
