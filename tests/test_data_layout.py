"""A `data/` MAPPA ELRENDEZÉSE (2026-10-08) — őr-teszt + a költöztető eszköz.

⚠ MIT ŐRZÜNK:
  1. Egy bróker-feed vagy számla-állapot útvonalat (`data/m1`, `data/ticks`,
     `data/sl_moves`…) építő modul a `core/broker_paths`-on át is vezeti — kü-
     lönben a régi, gyökérbeli helyre írna/olvasna, ami a költöztetés óta
     NEM LÉTEZIK (vagy rosszabb: egy elhagyott, elavult másolatot talál).
  2. A `tools/migrate_data_layout.py` helyesen sorol be, ütközésnél NEM mozgat
     semmit, és a `--undo` pontosan visszaállít. ⚠ CSAK ideiglenes mappán.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from core import broker_paths as BP                                      # noqa: E402
import tools.migrate_data_layout as M                                    # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ── 1. őr: közvetlen feed/számla útvonal csak broker_paths-szal ──────────────
print("== A bróker-útvonalak a broker_paths-on át mennek ==")
MINTA = re.compile(r'(ROOT|_BASE\)?|BASE_DIR|parents\[1\])\s*/\s*"data"\s*/\s*'
                   r'"(m1|m5|m15|m30|h1|h4|d1|ticks|bars_manifest|signal_journal|'
                   r'sl_moves|forward|conductor|engine_status\.json|server_offset\.json|'
                   r'adopted_positions\.json|position_meta\.json|signal_delivery\.csv)"')
rossz = []
for p in sorted(ROOT.rglob("*.py")):
    rel = p.relative_to(ROOT).as_posix()
    if rel.startswith(("tananyag/", "build/", ".venv/", "venv/", "scratchpad/")) \
            or "__pycache__" in rel or rel == "tests/test_data_layout.py":
        continue
    try:
        s = p.read_text(encoding="utf-8")
    except Exception:
        continue
    if MINTA.search(s) and "broker_paths" not in s:
        rossz.append(rel)
check("minden feed/szamla-utvonalat epito modul hasznalja a broker_paths-t",
      not rossz, ", ".join(rossz))

# ── 2. a költöztető eszköz, IDEIGLENES mappán ────────────────────────────────
print("\n== A koltozteto eszkoz (ideiglenes mappan) ==")
TMP = Path(tempfile.mkdtemp(prefix="layout_"))
D = TMP / "data"
for n in ("m1/GOLD.parquet", "ticks/GOLD/2026-01.parquet", "sl_moves/GOLD.csv",
          "conductor/inbox.json", "optimized_params/GOLD.json", "outcomes/GOLD.parquet",
          "_backup_x/a.txt", "regi_v1/h.parquet"):
    f = D / n
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
for n in ("engine_status.json", "risk_mode.json", "search_GOLD.parquet",
          "swing_vol.parquet", ".GOLD.history.lock", "risk_mode.json.mentes-1",
          "tradeforge.log", "tradeforge.log.1", "valami_uj.bin"):
    (D / n).write_text("x", encoding="utf-8")
(TMP / "trades.csv").write_text("x", encoding="utf-8")

_regi = (M.DATA, M.BP.TRADES)
M.DATA, M.BP.TRADES = D, TMP / "trades.csv"
try:
    lepesek, ismeretlen = M.plan("at")
    cel = {s.name: (d.relative_to(D).as_posix(), c) for s, d, c in lepesek}
    check("feed: m1 -> brokers/at/m1", cel.get("m1") == ("brokers/at/m1", "feed"), str(cel.get("m1")))
    check("feed: ticks", cel.get("ticks", ("",))[0] == "brokers/at/ticks")
    check("feed: a letolto szimbolum-zarja", cel.get(".GOLD.history.lock", ("",))[0]
          == "brokers/at/.GOLD.history.lock")
    check("szamla: sl_moves, conductor, engine_status",
          all(cel.get(n, ("",))[0] == f"accounts/at/{n}"
              for n in ("sl_moves", "conductor", "engine_status.json")))
    check("szamla: a GYOKERBELI trades.csv is", cel.get("trades.csv", ("",))[0]
          == "accounts/at/trades.csv")
    check("kutatas: outcomes, search_*, swing_*",
          all(cel.get(n, ("",))[0] == f"research/at/{n}"
              for n in ("outcomes", "search_GOLD.parquet", "swing_vol.parquet")))
    check("archiv: _backup_*, regi_v1, *.mentes-*",
          all(cel.get(n, ("",))[0] == f"_archive/{n}"
              for n in ("_backup_x", "regi_v1", "risk_mode.json.mentes-1")))
    check("kozos: optimized_params, risk_mode.json, naplok a HELYUKON",
          not ({"optimized_params", "risk_mode.json", "tradeforge.log",
                "tradeforge.log.1"} & set(cel)))
    check("ismeretlen elem NEM mozdul, de listazva",
          [p.name for p in ismeretlen] == ["valami_uj.bin"], str(ismeretlen))

    # ütközés: a cél már létezik → semmi nem mozdulhat
    (D / "brokers" / "at" / "m1").mkdir(parents=True)
    (D / "brokers" / "at" / "m1" / "X.parquet").write_text("y", encoding="utf-8")
    check("utkozes eszlelve (nem ures celmappa)",
          D / "brokers" / "at" / "m1" in M._utkozesek(M.plan("at")[0]))
    (D / "brokers" / "at" / "m1" / "X.parquet").unlink()
    check("az URES celmappa nem utkozes", not M._utkozesek(M.plan("at")[0]))

    manifest = M.apply(M.plan("at")[0])
    check("vegrehajtas: az m1 atkerult",
          (D / "brokers" / "at" / "m1" / "GOLD.parquet").exists() and not (D / "m1").exists())
    check("vegrehajtas: a trades.csv atkerult",
          (D / "accounts" / "at" / "trades.csv").exists() and not (TMP / "trades.csv").exists())
    check("vegrehajtas: a kozos a helyen", (D / "optimized_params" / "GOLD.json").exists())
    mf = json.loads(manifest.read_text(encoding="utf-8"))
    check("manifeszt: minden lepes benne", len(mf["moves"]) == len(lepesek), str(len(mf["moves"])))
    check("ujrafuttatas: nincs mit koltoztetni (idempotens terv)",
          not [x for x in M.plan("at")[0]], str(M.plan("at")[0]))

    check("undo: rendben", M.undo(manifest) == 0)
    check("undo: minden a regi helyen",
          (D / "m1" / "GOLD.parquet").exists() and (TMP / "trades.csv").exists()
          and (D / "_backup_x" / "a.txt").exists() and (D / "outcomes" / "GOLD.parquet").exists())
finally:
    M.DATA, M.BP.TRADES = _regi

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
