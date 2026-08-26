"""A kísérlet-listában EGY paraméter-készlet = EGY sor.

⚠ A LELET (2026-08-25, a felhasználó): „a Kísérleteknél (pl. Ger40 wpr_sma)
folyamatosan belekerülnek tételek, de az ugyanaz az eredmény, csak sokszorosítva.
Ezt ne engedjük, használhatatlanná teszi a listát!"

AZ OK. Az optuna study adatbázisa PERZISZTENS (a folytathatóság miatt), a
TPE-mintavevő pedig szűk, diszkrét térben újra és újra ugyanazt a kombinációt
húzza. Mindegyik külön trial lett, külön sorral — és mivel a backtest
determinisztikus, MIND UGYANAZT az eredményt adta.

A KÉT VÁLASZTÁS, amit a felhasználó megfogalmazott, és amit itt egyszerre
teljesítünk:

  1. „újraszámolja és felülírja"  → a CSV-író deduplikál, a legjobb score-ú sort
     tartja meg. Ez a MÁR MEGLÉVŐ, elszennyezett listákat is kitakarítja.
  2. „azt nem futtatja le mégegyszer" → a kiértékelés előtt gyorsítótárból
     válaszolunk, tehát a DRÁGA rész (backtest az összes walk-forward ablakon)
     el sem indul, és a sor sem keletkezik újra.

⚠ A kettő KÜLÖN védelmi vonal, és mindkettő kell: a gyorsítótár csak a mostani
futásra és a study-ban meglévő trialokra lát, a CSV-szűrő viszont bármit kiszűr,
ami mégis kettőzve jutna el a fájlig.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import tempfile

import pandas as pd

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


import ml.optimizer as O

# ── 1. Az ujjlenyomat ───────────────────────────────────────────────────
a = {"score": 12.5, "trades": 40, "note": "", "wpr_period": 14, "sma_period": 200}
b = {"score": 99.9, "trades": 41, "note": "más", "wpr_period": 14, "sma_period": 200}
check("⚠ a MÉRÉS-oszlopok NEM számítanak bele az azonosságba",
      O._param_kulcs(a) == O._param_kulcs(b))

c = {"score": 12.5, "trades": 40, "note": "", "wpr_period": 15, "sma_period": 200}
check("...egy paraméter eltérése viszont IGEN",
      O._param_kulcs(a) != O._param_kulcs(c))

# ⚠ A 0,3 és a 0,30000000000000004 UGYANAZ a készlet. Kerekítés nélkül két külön
# sor lenne — és pont az ilyen „majdnem egyforma" sorok tennék olvashatatlanná
# a listát.
d = {"score": 1, "trades": 1, "note": "", "x": 0.1 + 0.2}
e = {"score": 1, "trades": 1, "note": "", "x": 0.3}
check("⚠ a lebegőpontos zaj nem csinál új készletet",
      O._param_kulcs(d) == O._param_kulcs(e),
      f"{0.1 + 0.2!r} vs 0.3")

# A rank sem: azt az író teszi rá, nem a keresés.
f = dict(a, rank=1)
check("a `rank` sem része az azonosságnak", O._param_kulcs(a) == O._param_kulcs(f))

# ── 2. A CSV-író deduplikál ─────────────────────────────────────────────
tmp = Path(tempfile.mkdtemp(prefix="tf_trials_"))
try:
    sorok = [
        {"score": 10.0, "trades": 30, "note": "", "wpr_period": 14, "sma_period": 200},
        {"score": 10.0, "trades": 30, "note": "", "wpr_period": 14, "sma_period": 200},
        {"score": 10.0, "trades": 30, "note": "", "wpr_period": 14, "sma_period": 200},
        {"score": 22.0, "trades": 50, "note": "", "wpr_period": 21, "sma_period": 200},
        {"score":  5.0, "trades": 12, "note": "", "wpr_period":  9, "sma_period": 100},
    ]
    ki = tmp / "x_trials.csv"
    n = O._write_trials_csv(sorok, ki)
    check("⚠ 5 sorból 3 EGYEDI marad", n == 3, str(n))

    df = pd.read_csv(ki, sep=";", decimal=",", encoding="utf-8-sig")
    check("a fájlban is 3 sor van", len(df) == 3, str(len(df)))
    check("a legjobb az 1. rank", df.iloc[0]["rank"] == 1 and df.iloc[0]["score"] == 22.0)
    check("a rangsor folytonos (1..N)", list(df["rank"]) == [1, 2, 3],
          str(list(df["rank"])))

    # ⚠ AZONOS készlet, ELTÉRŐ score: a JOBBAT tartjuk. Determinisztikus futásnál
    # ez nem fordul elő; ha mégis, az azt jelenti, hogy az ADAT változott két
    # futás között (új gyertyák) — ilyenkor a frissebb, jobb mérés a hasznos.
    sorok2 = [
        {"score":  7.0, "trades": 20, "note": "régi", "wpr_period": 14},
        {"score": 19.0, "trades": 25, "note": "friss", "wpr_period": 14},
    ]
    ki2 = tmp / "y_trials.csv"
    O._write_trials_csv(sorok2, ki2)
    df2 = pd.read_csv(ki2, sep=";", decimal=",", encoding="utf-8-sig")
    check("⚠ azonos készletnél a JOBB score marad", len(df2) == 1
          and df2.iloc[0]["score"] == 19.0,
          f"{len(df2)} sor, score={df2.iloc[0]['score']}")

    # ── ⚠ KÉT HIBA, amit egy VALÓDI takarítás közben követtem el ─────────
    #
    # 1. SZÖVEGES score → BETŰREND. A régebbi verzió pont-tizedessel írta a
    #    `score`-t, míg a többi oszlopot vesszővel; visszaolvasva a `score`
    #    `object` típus lett. A `sort_values` ilyenkor LEXIKOGRAFIKUSAN rendez:
    #    a „97.68" nagyobb, mint a „739.55" — és a lista élére a ROSSZ készlet
    #    kerül. Élesben megtörtént: a Ger40 rangsora elromlott (a másolatból
    #    állt helyre).
    sorok3 = [
        {"score": "97.68",  "trades": 5,  "note": "", "wpr_period": 9},
        {"score": "739.55", "trades": 10, "note": "", "wpr_period": 14},
        {"score": "512.30", "trades": 8,  "note": "", "wpr_period": 21},
    ]
    ki3 = tmp / "s_trials.csv"
    O._write_trials_csv(sorok3, ki3)
    df3 = pd.read_csv(ki3, sep=";", decimal=",", encoding="utf-8-sig")
    check("⚠ SZÖVEGES score esetén is SZÁM szerint rangsorol",
          float(str(df3.iloc[0]["score"]).replace(",", ".")) == 739.55,
          f"rank1={df3.iloc[0]['score']}")

    # 2. PARAMÉTER NÉLKÜLI sorok. Ha egy sornak nincs egyetlen paraméter-
    #    oszlopa sem (csak mérések), az ujjlenyomata ÜRES — és akkor MINDEGYIK
    #    sor egymás duplikátumának látszik. Három sorból egy maradt: néma
    #    adatvesztés. Ilyenkor a szűrés KIMARAD, és szólunk róla.
    sorok4 = [
        {"score": 739.55, "trades": 10, "note": ""},
        {"score": -999999.0, "trades": 0, "note": "nincs értékelhető trade"},
        {"score": 97.68, "trades": 5, "note": ""},
    ]
    ki4 = tmp / "p_trials.csv"
    n4 = O._write_trials_csv(sorok4, ki4)
    check("⚠ paraméter-oszlop NÉLKÜL egy sor sem vész el", n4 == 3, str(n4))

    # Üres bemenet nem hoz létre fájlt és nem hasal el.
    check("üres lista → 0, nincs kivétel",
          O._write_trials_csv([], tmp / "z.csv") == 0)
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

# ── 3. A KIÉRTÉKELÉS is kimarad (nem csak a sor) ────────────────────────
# ⚠ Ez a fontosabb fele: a sor elhagyása kozmetika, a backtest újrafuttatása
# viszont PERCEK. A forrásban ellenőrizzük, hogy a szűrő a kiértékelés ELŐTT áll.
_src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")

for _nev in ("_objective_flat", "_objective_nested"):
    _i = _src.find(f"def {_nev}(trial)")
    _blk = _src[_i:_i + 2000]
    _dup = _blk.find("_mar_ertekelt")
    _ert = _blk.find("_evaluate(") if _nev == "_objective_flat" else _blk.find("build_signal_series")
    check(f"⚠ '{_nev}': a szűrő a KIÉRTÉKELÉS ELŐTT van",
          0 < _dup < _ert, f"szűrő@{_dup} < kiértékelés@{_ert}")
    check(f"'{_nev}': ...és ilyenkor nem ír sort",
          "_duplikatum[0] += 1" in _blk and
          _blk[_dup:_blk.find("_progress_tick()", _dup)].count("_record_trial") == 0)

check("⚠ folytatáskor a study-ból feltöltjük a gyorsítótárat",
      'user_attrs.get("sig")' in _src)
check("⚠ ...és a trial VISZI is az ujjlenyomatát",
      'set_user_attr("sig"' in _src)
check("az ismétlődések SZÁMA a naplóba kerül",
      "ISMÉTLŐDŐ készletet húzott" in _src)

# ⚠ KÖZÖS építő: az ujjlenyomat a kiértékelés előtt és a sor mentésekor is
# ugyanabból jön. Két külön másolat előbb-utóbb elcsúszna, és a szűrő NÉMÁN
# elkezdene átengedni duplikátumokat.
check("⚠ a paraméter-oszlopokat KÖZÖS építő adja",
      _src.count("def _param_oszlopok(") == 1
      and _src.count("_param_oszlopok(") >= 3,
      f"{_src.count('_param_oszlopok(')} hivatkozás")

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
