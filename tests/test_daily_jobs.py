"""NAPI FELADATOK — core/daily_jobs.py: egyszer egy napon, alprocesszben, nem némán.

⚠ A HIBA, AMIÉRT EZ A MODUL VAN (2026-09-22). A Csilla-sáv forward-tesztje egy
hétig „naponta, kézzel" kellett volna fusson — egyszer sem futott. A modul a
motorból indítja; ez a teszt azt méri, hogy
  1. a beállított idő ELŐTT nem indul, UTÁNA egyszer igen, és ugyanazon a napon
     másodszor NEM (akkor sem, ha az első futás elbukott);
  2. a kézi indítás ugyanazt az utat járja, és futó feladat mellett NEM indít
     másodikat;
  3. a befejezést learatja (kód, idő), és a program újraindulását (nincs Popen,
     de „fut") kimondja — nem marad örökre „fut";
  4. a config csak az eltérést rögzíti: kikapcsolt feladat nem indul, a
     felületnek viszont kikapcsoltként látszik;
  5. a `forward` konzol-parancs a status-fájlból ír, és a hiányt kimondja.

⚠ AZ ÁLLAPOTFÁJL IDEIGLENES MAPPÁBAN VAN — a teszt a valódi `data/` alá SOHA
nem ír (lásd `tests-must-never-write-real-config`). Az alprocessz HAMIS: egy
Popen-utánzat, ami azonnal vagy kérésre „fejeződik be".

Futtatás:  python tests/test_daily_jobs.py
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import applog
applog.harden_console()

from core import daily_jobs as dj

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class FakePopen:
    """Popen-utánzat: `rc=None` amíg a teszt le nem zárja (`finish`)."""
    inditasok = []

    def __init__(self, args, stdout=None, stderr=None):
        self.args, self.pid, self._rc = args, 4242 + len(FakePopen.inditasok), None
        FakePopen.inditasok.append(list(args))

    def poll(self):
        return self._rc

    def finish(self, rc=0):
        self._rc = rc


tmp = Path(tempfile.mkdtemp(prefix="tf_daily_jobs_"))
dj.STATE_FILE = tmp / "daily_jobs.json"
dj.JOBS = {"proba": dict(argv=["forward", "--all"], time="22:30", log="x/proba.log")}
# a napló a BASE_DIR alá menne — a tesztben ideiglenes helyre
dj._BASE = tmp
dj.reset_for_test()
FakePopen.inditasok.clear()
dj.subprocess.Popen = FakePopen          # a `tick` alapértelmezett indítója

cfg = {}
d = "2026-09-22"

# ══ 1. IDŐZÍTÉS ═══════════════════════════════════════════════════════════
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 22:29"))
check("az idő ELŐTT nem indul", ind == [] and not FakePopen.inditasok)
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 22:30"))
check("az időpontban indul", ind == ["proba"] and len(FakePopen.inditasok) == 1)
check("a parancs a main.py alparancsa (EXE-ben is ez az út)",
      FakePopen.inditasok[0][0] == sys.executable
      and FakePopen.inditasok[0][1].endswith("main.py")
      and FakePopen.inditasok[0][-2:] == ["forward", "--all"],
      " ".join(FakePopen.inditasok[0][-3:]))
check("a napló-fájl megnyílt és az indítás beíródott",
      (tmp / "x" / "proba.log").exists() and "indítás (daily)" in
      (tmp / "x" / "proba.log").read_text(encoding="utf-8"))
st = dj.status(cfg, "proba")
check("az állapot: fut, a nap beírva", st["status"] == dj.RUNNING and st["last_date"] == d)
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 23:10"))
check("ugyanazon a napon MÁSODSZOR nem indul (fut)", ind == [] and len(FakePopen.inditasok) == 1)

# ══ 2. KÉZI INDÍTÁS FUTÓ MELLETT ═════════════════════════════════════════
ok, mi = dj.start("proba", trigger="manual", popen=FakePopen)
check("futó feladat mellett a kézi indítás elutasítva", not ok and mi == "already_running", mi)
ok, mi = dj.start("nincs", popen=FakePopen)
check("ismeretlen feladat: kimondva", not ok and mi == "unknown_job")

# ══ 3. LEARATÁS ═══════════════════════════════════════════════════════════
p, _fh, _t0 = dj._popen["proba"]
p.finish(rc=3)
n = dj.reap()
st = dj.status(cfg, "proba")
check("a bukott befejezés learatva: failed, kód 3",
      n == 1 and st["status"] == dj.FAILED and st["last_rc"] == 3 and st["last_end"],
      f"{st['status']} rc={st['last_rc']}")
check("a napló-fájlba a vége is beíródott",
      "kilépési kód 3" in (tmp / "x" / "proba.log").read_text(encoding="utf-8"))
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 23:30"))
check("bukott futás után ugyanazon a napon NEM próbálja újra", ind == [])
ind = dj.tick(cfg, now=datetime.fromisoformat("2026-09-23 22:31"))
check("másnap újra indul", ind == ["proba"] and len(FakePopen.inditasok) == 2)
p, _fh, _t0 = dj._popen["proba"]
p.finish(rc=0)
dj.reap()
check("sikeres befejezés: ok, kód 0", dj.status(cfg, "proba")["status"] == dj.OK)

# az állapot fájlból is visszajön (újraindulás), és a „fut, de nincs Popen" kimondva
dj._popen["proba"] = (FakePopen(["x"]), open(tmp / "x" / "proba.log", "a", encoding="utf-8"), 0.0)
dj._load()["proba"]["status"] = dj.RUNNING
dj._save()
dj.reset_for_test()                      # = a program újraindult
st = dj.status(cfg, "proba")
check('újraindulás után a „fut” Popen nélkül → lost (nem marad örökre fut)',
      st["status"] == dj.LOST, st["status"])
check("az állapot fájlból jött vissza (last_rc megmaradt)", st.get("last_rc") == 0)

# ══ 4. CONFIG: CSAK AZ ELTÉRÉS ════════════════════════════════════════════
c = dj.job_cfg({}, "proba")
check("alap: bekapcsolva, a feladat saját idején", c == {"enabled": True, "time": "22:30"})
c = dj.job_cfg({"daily_jobs": {"proba": {"time": "07:15"}}}, "proba")
check("csak az idő eltér → az marad, az enabled alap", c == {"enabled": True, "time": "07:15"})
cfg_ki = {"daily_jobs": {"proba": {"enabled": False}}}
dj.reset_for_test()
FakePopen.inditasok.clear()
ind = dj.tick(cfg_ki, now=datetime.fromisoformat("2026-09-24 23:00"))
check("kikapcsolt feladat nem indul", ind == [] and not FakePopen.inditasok)
check("…de a felületnek KIKAPCSOLTKÉNT látszik, nem tűnik el",
      dj.status(cfg_ki, "proba")["enabled"] is False)

# ══ 5. A `forward` PARANCS A STATUS-FÁJLBÓL ÍR ═══════════════════════════
from core import console_cmd as cc
dj.JOBS = {"csilla_forward": dict(argv=["forward", "--all"], time="22:30",
                                  log="data/forward/csilla_forward.log")}
dj.reset_for_test()
# a status-fájl a `daily_jobs.base()` alatt — az már a tmp-re mutat
try:
    sorok = cc.forward_lines({})
    check("status-fájl nélkül: a hiány KIMONDVA (nem „0 kötés”)",
          any("állapot-fájl nincs" in s or "no status file" in s for s in sorok),
          " | ".join(sorok))
    check("a fejsor + a feladat állapota (még nem futott)",
          len(sorok) >= 2 and ("még nem futott" in sorok[1] or "never ran" in sorok[1]),
          sorok[1] if len(sorok) > 1 else "")
    (tmp / "data" / "forward").mkdir(parents=True)
    (tmp / "data" / "forward" / "csilla_status.json").write_text(
        '{"started":"2026-09-15","signals":24,"closed":6,"open":1,"skipped":17,'
        '"primary":{"n":1,"r_mean":-1.0,"t":0.0,"win":0.0},"to_kill":59,"verdict":"running"}',
        encoding="utf-8")
    sorok = cc.forward_lines({})
    check("a status-fájlból: napló-sor + elsődleges + ítélet",
          any("24" in s and "6" in s for s in sorok) and any("n=1" in s for s in sorok)
          and any("59" in s for s in sorok), " | ".join(sorok))
    # a parancs-réteg: `forward run` a daily_jobs.start-ot hívja (hamis Popen-nel)
    dj.subprocess.Popen = FakePopen
    FakePopen.inditasok.clear()

    class _Ctx:
        cfg = {}
    res = cc.cmd_forward(_Ctx(), ["run"])
    check("`forward run` indít (egy indítási út a gombbal)",
          res.ok and len(FakePopen.inditasok) == 1
          and FakePopen.inditasok[0][-2:] == ["forward", "--all"], " | ".join(res.lines))
    res = cc.cmd_forward(_Ctx(), ["run"])
    check("`forward run` másodszor: „már fut”, nem indít másodikat",
          not res.ok and len(FakePopen.inditasok) == 1, " | ".join(res.lines))
    check("`forward` (argumentum nélkül) az állást adja, ok",
          cc.cmd_forward(_Ctx(), []).ok)
    check("a `forward` a parancs-táblában és a súgóban van",
          cc.COMMANDS.get("forward") is cc.cmd_forward
          and any(h[0].startswith("forward") for h in cc._HELP))
finally:
    pass

# ══ ÖSSZESÍTÉS ════════════════════════════════════════════════════════════
jo = sum(results)
print(f"\n{jo}/{len(results)} teszt PASS")
sys.exit(0 if jo == len(results) else 1)
