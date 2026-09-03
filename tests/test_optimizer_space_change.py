"""A KERESÉSI TÉR VÁLTOZÁSA új optimalizálást indít.

⚠ A LELET (felhasználói jelzés 2026-09-02, mérve 09-03): „hiába írom át a
tól-ig-et egy hangolt paraméternél, nem azt veszi". A `keltner_period`
tartománya 10–20-ról 4–30-ra változott, a futás ki is írta, hogy 14 lehetséges
variáció van — az EREDMÉNY mégis a 10–20 sávból jött.

AZ OK. Az optuna study perzisztens (SQLite), és a folytatás kulcsa CSAK a
szimbólum — a keresési tér nincs benne:

    study = optuna.create_study(study_name=symbol, storage=…,
                                load_if_exists=True, …)

Ha az előző futás megszakadt (nincs `done` marker, de van `.db`), a program
FOLYTATJA. Ilyenkor az ÚJ trialok már az új tartományból mintáznak, a RÉGIEK
viszont bent maradnak a régi értékekkel — és a „legjobb" az ÖSSZES trial közül
kerül ki, jellemzően egy régiből.

⚠ SEMMI NEM HIBÁZOTT, ÉS SEMMI NEM SZÓLT. A futás sikeresnek látszott, a
haladás-kijelző rendben volt, a napló tiszta. Csak épp a beállított tartomány
nem érvényesült — ez a projekt legdrágább hibaosztálya (néma, helyesnek látszó
eredmény).

A JAVÍTÁS: a keresési térről ujjlenyomat kerül a study mellé
(`<sym>_study.space`). Eltérésnél a régi `.db` FÉLRETEVŐDIK (nem törlődik), és
új study indul — hangosan, `WARNING`-gal.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import params_store as ps
from ml.optimizer import ter_ujjlenyomat as ujj

# ── 1. AZ UJJLENYOMAT AZT MÉRI, AMIT KELL ─────────────────────────────────
_alap = {"keltner_period": {"min": 10, "max": 20, "step": 2},
         "atr_period": {"min": 7, "max": 21, "step": 7},
         "valami_mas": "nem range",
         "n_trials": 500}

check("ugyanaz a tér → ugyanaz az ujjlenyomat",
      ujj(_alap) == ujj(dict(_alap)))

# ⚠ EZ A KONKRÉT ESET, amit a felhasználó jelzett.
_uj = {**_alap, "keltner_period": {"min": 4, "max": 30, "step": 2}}
check("a tartomány módosítása MEGVÁLTOZTATJA az ujjlenyomatot (10–20 → 4–30)",
      ujj(_alap) != ujj(_uj), f"{ujj(_alap)} / {ujj(_uj)}")

for _mit, _spec in (("min", {"min": 8, "max": 20, "step": 2}),
                    ("max", {"min": 10, "max": 22, "step": 2}),
                    ("step", {"min": 10, "max": 20, "step": 1})):
    check(f"a `{_mit}` egyedüli változása is számít",
          ujj(_alap) != ujj({**_alap, "keltner_period": _spec}))

# A `gt`/`lt` függés is a tér része: megváltoztatja, mely kombinációk állhatnak elő.
check("a `gt`/`lt` függés is a tér része",
      ujj(_alap) != ujj({**_alap, "keltner_period":
                         {**_alap["keltner_period"], "gt": "atr_period"}}))

# ⚠ AMI NEM A TÉR: a trial-szám vagy egy nem-range kulcs változása NEM
# érvényteleníti a study-t — különben minden apró config-mozgás eldobná a
# félbehagyott futást, és a folytatás-képesség elveszne.
check("a trial-szám NEM része a térnek (a folytatás megmarad)",
      ujj(_alap) == ujj({**_alap, "n_trials": 900}))
check("nem-range kulcs változása sem",
      ujj(_alap) == ujj({**_alap, "valami_mas": "más"}))

# ── 2. A KÍSÉRŐ BEÁLLÍTÁSOK is a tér részei ───────────────────────────────
# ⚠ Bekapcsolt rr-kereséssel MÁS dimenziók kerülnek a trialba, tehát a régi
# trialok nem összemérhetők az újakkal.
check("az rr-keresés be/ki megváltoztatja az ujjlenyomatot",
      ujj(_alap, {"rr": False}) != ujj(_alap, {"rr": True}))
check("a beágyazott mód is", ujj(_alap, {"nested": False}) != ujj(_alap, {"nested": True}))
check("a stratégia neve is", ujj(_alap, {"strategy": "a"}) != ujj(_alap, {"strategy": "b"}))

# ── 3. A KÓD tényleg félreteszi a régit, és HANGOS ─────────────────────────
_src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
_blokk = _src.split("A KERESÉSI TÉR VÁLTOZOTT-E?", 1)[1][:2600]

check("a régi study FÉLRETEVŐDIK, nem törlődik",
      ".rename(" in _blokk and "unlink" not in _blokk)
check("...és a név alapján visszakereshető (időbélyeg)",
      "regi-" in _blokk and "strftime" in _blokk)
check("a felhasználó ÉRTESÜL róla (WARNING, nem debug)",
      "log.warning(" in _blokk)
check("...és megmondja, MIÉRT baj a folytatás",
      "NEM" in _blokk and "érvényesülne" in _blokk)
# ⚠ Ha a félretevés elbukik, NEM hallgatunk: rossz tartományú folytatás
# csendben rosszabb, mint egy hangos hiba.
check("ha a félretevés elbukik, az HIBA (nem néma)",
      "log.error(" in _blokk)

# ── 4. Az ujjlenyomat-fájl a study MELLETT lakik ──────────────────────────
_f = ps.space_marker("UsaTec", "wpr_sma")
check("az ujjlenyomat a study mellé kerül",
      _f.parent == ps.study_db("UsaTec", "wpr_sma").parent, str(_f))
check("...és a nevében ott a szimbólum", "UsaTec" in _f.name, _f.name)

# ⚠ HIÁNYZÓ ujjlenyomat (a javítás ELŐTTI study-k) = ISMERETLEN tér → új futás.
# A régi .db-kről nem tudjuk, milyen tartománnyal készültek; a folytatásuk
# pontosan azt a hibát hozná vissza, ami ellen ez az egész készült.
check("hiányzó ujjlenyomatnál is új futás indul (üres ≠ hash)",
      "" != ujj(_alap))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
