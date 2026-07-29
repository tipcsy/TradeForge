"""#19 (gyertya-visszaszamlalo), #15 (halott kulcsok), #16 (halott fuggveny), #17."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ #19  seconds_to_candle_close ═══════════════════════════════════════════
from trading.live_trader import seconds_to_candle_close as sc

# A REGI keplet, referenciakent
from datetime import datetime, timezone


def regi(tf):
    now = datetime.now(timezone.utc)
    return tf * 60 - ((now.minute % tf) * 60 + now.second)


for tf in (1, 5, 15, 30, 60):
    uj, r = sc(tf), regi(tf)
    check(f"M{tf}: az uj egyezik a regivel (nem volt hibas)", abs(uj - r) <= 1,
          f"uj={uj} regi={r}")

# H4 (240 perc): a regi keplet SOSEM vont le orat -> mindig > 3 ora maradek
h4_uj, h4_regi = sc(240), regi(240)
check("H4: az uj ertek a [0, 14400] tartomanyban van", 0 < h4_uj <= 240 * 60, str(h4_uj))
check("H4: a REGI keplet hibas volt (a perc-maradek miatt > 3 ora)",
      h4_regi > 180 * 60, f"regi={h4_regi} ({h4_regi/3600:.1f} ora)")

# Determinisztikus ellenorzes: a hatarok a tf-racsra esnek
import time as _t


def at(ts, tf, off=0.0):
    """A fuggveny keplete adott idopontra (a fuggveny most()-ot hasznal, ezert
    ugyanazt a kepletet ellenorizzuk kozvetlenul)."""
    period = tf * 60
    return int(period - ((ts + off) % period))


check("epoch-alap: 04:00:00 UTC-kor a H4 gyertya EPP most nyilt -> 4 ora van hatra",
      at(datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc).timestamp(), 240) == 240 * 60)
check("epoch-alap: 05:30:00 UTC -> 2.5 ora van hatra a H4-bol",
      at(datetime(2026, 7, 27, 5, 30, tzinfo=timezone.utc).timestamp(), 240) == 150 * 60)
# GMT+3 brokernel 05:30 UTC = 08:30 szerver-ido -> a 08:00-s H4 gyertyabol 3.5 ora
check("szerver-eltolas eltolja a H4 racsot (GMT+3: 05:30 UTC = 08:30 szerver -> 3.5 ora)",
      at(datetime(2026, 7, 27, 5, 30, tzinfo=timezone.utc).timestamp(), 240, 3 * 3600)
      == 210 * 60)
check("M15-nel az eltolas (egesz ora) NEM valtoztat",
      at(1780000000, 15) == at(1780000000, 15, 3 * 3600))

# ══ #15  halott config-kulcsok ════════════════════════════════════════════
DEAD = ("global_session_start_utc", "global_session_end_utc", "min_lot_breach_action")
for f in ("config.json", "config.example.json"):
    # A `config.json` GITIGNORE-olt (broker-jelszot tartalmaz) -> friss klonon nincs.
    # Ilyenkor KIHAGYJUK, nem bukunk: a `config.example.json` a repoban van, azt
    # mindig ellenorizzuk. Igy a teszt fejlesztoi gepen TOBBET ellenoriz, de sehol
    # sem ad hamis riasztast.
    path = ROOT / f
    if not path.exists():
        print(f"SKIP  {f}: nincs a munkamasolatban (gitignore) — kihagyva")
        continue
    d = json.loads(path.read_text(encoding="utf-8"))
    left = [k for k in DEAD if k in d.get("trading", {})]
    check(f"{f}: nincs benne halott kulcs", not left, str(left))

# ══ #16  halott fuggveny eltavolitva ══════════════════════════════════════
from core import mt5_connector as mc
check("modify_position_sl (0 hivoval) eltavolitva",
      not hasattr(mc, "modify_position_sl"))
check("a hasznalt modify_position_sltp megvan", hasattr(mc, "modify_position_sltp"))
check("live_trader.modify_sl (a trailing utja) megvan",
      hasattr(sys.modules["trading.live_trader"], "modify_sl"))

# A kereszthivatkozas mindket oldalon ott van (a jovobeli valtoztatas ne csusszon szet)
src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("IKERPAR-figyelmeztetes mindket BE-agon", src.count("IKERPÁR") == 2,
      f"{src.count('IKERPÁR')} elofordulas")

# ══ #17  arva-kereso ══════════════════════════════════════════════════════
sys.argv = ["cleanup_orphans.py"]
import tools.cleanup_orphans as co
import tempfile

# A keresot SZINTETIKUS fajlokon merjuk, nem a repo pillanatnyi allapotan — igy a
# teszt a takaritas utan is ervenyes marad (korabban megkovetelte, hogy LEGYENEK
# arvak, ezert a `--delete` lefuttatasa "elrontotta" volna).
_tmp = Path(tempfile.mkdtemp())
for sub, names in (("models", ["Ger40.pkl", "DJ30.pkl"]),
                   ("optimized_params", ["Ger40.json", "DJ30_study.done"]),
                   ("sl_moves", ["Ger40.csv", "GER40.csv", "NAS100.csv"])):
    d = _tmp / sub; d.mkdir(parents=True)
    for n in names: (d / n).write_text("x", encoding="utf-8")
_orig_data = co.DATA
co.DATA = _tmp
orph = co.scan({"Ger40"})            # CSAK a Ger40 van "configban"
names = {p.name for p, _ in orph}
co.DATA = _orig_data

check("az arva-kereso megtalalja a nem-konfiguralt szimbolumokat",
      {"DJ30.pkl", "DJ30_study.done", "NAS100.csv"} <= names, str(sorted(names)))
check("a config-beli szimbolum fajljai NEM arvak",
      not {"Ger40.pkl", "Ger40.json", "Ger40.csv"} & names)
# KIS-NAGYBETU: Windows/macOS alatt a `GER40.csv` es a `Ger40.csv` UGYANAZ a fajl,
# tehat a mas irasmod NEM arva, hanem az ELO naplo — torolni adatvesztes lenne.
# (Ez egyszer meg is tortent: a Ger40 SL-naploja tunt el, majd lett visszaallitva.)
_ci = not co._case_sensitive_fs()
if _ci:
    check("kis-nagybetu-ERZEKETLEN FS: a GER40.csv NEM arva (a Ger40 elo naploja)",
          "GER40.csv" not in names)
else:
    check("kis-nagybetu-ERZEKENY FS: a GER40.csv arvakent van jelolve",
          any(p.name == "GER40.csv" and "kis-nagybetu" in w for p, w in orph))
check("a `_study.done` utotag levagasa mukodik (a szimbolum DJ30)",
      any(p.name == "DJ30_study.done" and "DJ30" in w for p, w in orph))
check("a dry-run NEM torol (a fajlok megvannak)",
      all(p.exists() for p, _ in orph))

# ══ applog.harden_console publikus (a tools is hasznalja) ═════════════════
from core import applog
check("applog.harden_console publikus", callable(getattr(applog, "harden_console", None)))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
