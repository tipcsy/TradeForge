"""NAPI FELADATOK — core/daily_jobs.py: a STRATÉGIA deklarálja, a keret futtatja.

⚠ A HIBA, AMIÉRT EZ A MODUL VAN (2026-09-22). A Csilla-sáv forward-tesztje egy
hétig „naponta, kézzel" kellett volna fusson — egyszer sem futott. A modul a
motorból indítja.

⚠ ÉS A MÁSODIK HIBA, UGYANAZNAP. Az első változat a keretbe drótozta a feladat
nevét, a `main.py` importálta a szkriptjét. A felhasználó kérdése — „mi van,
ha letörlöm a csilla stratégiát?" — mutatta meg: a feladat minden este
elbukott volna. Ezért a feladat a STRATÉGIÁÉ (`Strategy.daily_jobs()`), a
keret a registry-n át kérdezi. Ez a teszt azt méri, hogy
  1. a beállított idő ELŐTT nem indul, UTÁNA egyszer igen, és ugyanazon a napon
     másodszor NEM (akkor sem, ha az első futás elbukott);
  2. a kézi indítás ugyanazt az utat járja, és futó feladat mellett NEM indít
     másodikat;
  3. a befejezést learatja (kód, idő), és a program újraindulását (nincs Popen,
     de „fut") kimondja — nem marad örökre „fut";
  4. a config csak az eltérést rögzíti: kikapcsolt feladat nem indul, a
     felületnek viszont kikapcsoltként látszik;
  5. a feladat FORRÁSA a stratégia: ha a forrás eltűnik (törölt stratégia), a
     feladat is — nincs időzítés, a parancs „ismeretlen"-t mond; a valódi
     `csilla` stratégia deklarálja a `csilla_forward`-ot, és a `.tfs` csomagoló
     viszi a modulját;
  6. a `jobs` parancs a keret sorait + a stratégia saját sorait adja, és a
     `jobs run` ugyanazt az utat hívja, mint a gomb.

⚠ AZ ÁLLAPOTFÁJL IDEIGLENES MAPPÁBAN VAN — a teszt a valódi `data/` alá SOHA
nem ír (lásd `tests-must-never-write-real-config`). Az alprocessz HAMIS: egy
Popen-utánzat, ami kérésre „fejeződik be".

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
dj._BASE = tmp
dj.reset_for_test()
FakePopen.inditasok.clear()
dj.subprocess.Popen = FakePopen          # a `tick` alapértelmezett indítója

# A HAMIS forrás: egy "stratégia" egy feladattal
_futott = []
PROBA = dict(name="proba", time="22:30", label="Próba-feladat", owner="proba_strat",
             run=lambda argv: (_futott.append(list(argv)), 0)[1],
             status_lines=lambda: ["saját sor 1", "saját sor 2"])
dj.PROVIDERS = [lambda: [PROBA]]

cfg = {}
d = "2026-09-22"

# ══ 1. IDŐZÍTÉS ═══════════════════════════════════════════════════════════
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 22:29"))
check("az idő ELŐTT nem indul", ind == [] and not FakePopen.inditasok)
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 22:30"))
check("az időpontban indul", ind == ["proba"] and len(FakePopen.inditasok) == 1)
check("a parancs a main.py `job <név>` alparancsa (EXE-ben is ez az út)",
      FakePopen.inditasok[0][0] == sys.executable
      and FakePopen.inditasok[0][1].endswith("main.py")
      and FakePopen.inditasok[0][-2:] == ["job", "proba"],
      " ".join(FakePopen.inditasok[0][-3:]))
_log = tmp / "data" / "daily_jobs" / "proba.log"
check("a napló-fájl a keret mappájában, az indítás beírva",
      _log.exists() and "indítás (daily)" in _log.read_text(encoding="utf-8"))
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
      "kilépési kód 3" in _log.read_text(encoding="utf-8"))
ind = dj.tick(cfg, now=datetime.fromisoformat(f"{d} 23:30"))
check("bukott futás után ugyanazon a napon NEM próbálja újra", ind == [])
ind = dj.tick(cfg, now=datetime.fromisoformat("2026-09-23 22:31"))
check("másnap újra indul", ind == ["proba"] and len(FakePopen.inditasok) == 2)
p, _fh, _t0 = dj._popen["proba"]
p.finish(rc=0)
dj.reap()
check("sikeres befejezés: ok, kód 0", dj.status(cfg, "proba")["status"] == dj.OK)

dj._popen["proba"] = (FakePopen(["x"]), open(_log, "a", encoding="utf-8"), 0.0)
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

# ══ 5. A FORRÁS A STRATÉGIA ═══════════════════════════════════════════════
check("a feladat futtatása a processzben a stratégia `run`-ját hívja",
      dj.run_in_process("proba", ["--x"]) == 0 and _futott == [["--x"]], str(_futott))
check("ismeretlen név a processzben: kilépési kód 2 (nem elszállás)",
      dj.run_in_process("nincs", []) == 2)
dj.PROVIDERS = [lambda: []]              # = a stratégiát letörölték
dj.reset_for_test()
FakePopen.inditasok.clear()
ind = dj.tick(cfg, now=datetime.fromisoformat("2026-09-25 23:00"))
check("TÖRÖLT stratégia: a feladat eltűnik — nincs időzített indítás",
      ind == [] and not FakePopen.inditasok and dj.jobs() == {})
check("…az állapota olvasható marad, de `known=False`",
      dj.status(cfg, "proba")["known"] is False and dj.status(cfg, "proba")["last_rc"] == 0)
ok, mi = dj.start("proba", popen=FakePopen)
check("…és kézzel sem indítható (ismeretlen)", not ok and mi == "unknown_job")
dj.PROVIDERS = [lambda: [PROBA], lambda: [dict(PROBA, owner="masik")]]
check("kétszer deklarált név: az első marad, a második kimarad (nem néma felülírás)",
      dj.jobs()["proba"]["owner"] == "proba_strat")
dj.PROVIDERS = [lambda: [dict(name="rossz", time="10:00")]]
check("hiányos feladat-leírás (nincs `run`) kimarad", dj.jobs() == {})

# a VALÓDI stratégiák: a csilla deklarálja a forwardot, a csomagoló viszi a modult
dj.PROVIDERS = [dj._strategy_jobs]
_valodi = dj.jobs()
check("a valódi registry-ből a csilla deklarálja a `csilla_forward`-ot",
      "csilla_forward" in _valodi and _valodi["csilla_forward"]["owner"] == "csilla",
      ", ".join(sorted(_valodi)))
from strategy.pack import helper_modules
check("a `.tfs` csomagoló a csilla_forward-ot segédmodulként viszi",
      "csilla_forward" in helper_modules("csilla"), str(helper_modules("csilla")))
from strategy.base import Strategy
from strategy import get_strategy_by_name
check("a szerződés hookja alapból üres lista (régi stratégia nem tud róla)",
      get_strategy_by_name("wpr_sma").daily_jobs() == []
      and "daily_jobs" in vars(Strategy))

# ══ 6. A `jobs` PARANCS ═══════════════════════════════════════════════════
from core import console_cmd as cc
dj.PROVIDERS = [lambda: [PROBA]]
dj.reset_for_test()


class _Ctx:
    cfg = {}


sorok = cc.job_lines({}, "proba")
check("a keret sora + a stratégia saját sorai együtt",
      len(sorok) >= 4 and "Próba-feladat" in sorok[0]
      and sorok[-2:] == ["saját sor 1", "saját sor 2"], " | ".join(sorok))
check("ismeretlen feladat a parancsban: kimondva",
      any("ismeretlen" in s or "unknown" in s for s in cc.job_lines({}, "nincs")))
FakePopen.inditasok.clear()
res = cc.cmd_jobs(_Ctx(), ["run", "proba"])
check("`jobs run <név>` indít (egy indítási út a gombbal)",
      res.ok and len(FakePopen.inditasok) == 1
      and FakePopen.inditasok[0][-2:] == ["job", "proba"], " | ".join(res.lines))
res = cc.cmd_jobs(_Ctx(), ["run", "proba"])
check("`jobs run` másodszor: „már fut”, nem indít másodikat",
      not res.ok and len(FakePopen.inditasok) == 1, " | ".join(res.lines))
check("`jobs run` név nélkül: használat, nem elszállás", not cc.cmd_jobs(_Ctx(), ["run"]).ok)
check("`jobs` (argumentum nélkül) az állást adja, ok", cc.cmd_jobs(_Ctx(), []).ok)
dj.PROVIDERS = [lambda: []]
check("`jobs` feladat nélkül: kimondja, hogy nincs (nem üres kimenet)",
      bool(cc.cmd_jobs(_Ctx(), []).lines) and cc.cmd_jobs(_Ctx(), []).ok)
check("a `jobs` a parancs-táblában és a súgóban van; a `forward` NINCS",
      cc.COMMANDS.get("jobs") is cc.cmd_jobs and "forward" not in cc.COMMANDS
      and any(h[0].startswith("jobs") for h in cc._HELP))

# ══ ÖSSZESÍTÉS ════════════════════════════════════════════════════════════
jo = sum(results)
print(f"\n{jo}/{len(results)} teszt PASS")
sys.exit(0 if jo == len(results) else 1)
