"""A config.json mentese: ATOMIKUS es BESZEDES (P3, v2.0.0).

KET lelet egy helyen (`dashboard/gui.py`), a 2026-08-05-i atvizsgalasbol es a
javitas kozben:

  1. **Nema hiba.** A `_save_main_config` egy `except Exception: pass`-szal
     nyelte el a mentesi hibat. Zarolt/irhatatlan fajlnal a Play/Stop, a slot- es
     a limit-allitas UGY NEZETT KI, mintha megtortent volna (a futasideju cfg-ben
     meg is tortent) — es csak UJRAINDITASKOR derult volna ki, hogy semmi nem
     perzisztalt. A kereskedes-SZANDEK a legrosszabb hely erre.

  2. **Nem atomikus iras.** Az `open(..., "w")` ELOBB csonkolja a fajlt, es csak
     utana ir. A projekt MINDEN mas allapotfajlja (`params_store`, `adopted`,
     `build_state`, `execution_params`, `mt5_visual`) temp->replace-szel ir; a
     legertekesebb fajl — ami a broker-belepot, a parokat es a szandekot tartja —
     volt az egyetlen kivetel.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []
import json as _json
_HU_CAT = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))


def _says(key, *words):
    """A kulcs magyar szovege tartalmazza-e mindet? (i18n utan a felirat mar
    nem a forrasban van — a teszt a KATALOGUST kerdezi.)"""
    txt = _HU_CAT.get(key, "")
    return all(w in txt for w in words)




def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy.settings import write_config_file, save_main_config, main_config_view

TMP = Path(tempfile.mkdtemp())

# ══ 1. Sikeres iras ═══════════════════════════════════════════════════════

p = TMP / "config.json"
err = write_config_file({"a": 1, "ekezet": "árvíztűrő"}, p)
check("sikeres iras -> ures hibauzenet", err == "", repr(err))
check("a fajl letrejott", p.exists())
_d = json.loads(p.read_text(encoding="utf-8"))
check("a tartalom visszaolvashato", _d == {"a": 1, "ekezet": "árvíztűrő"}, str(_d))
check("UTF-8, nem escape-elt (a config kezzel is szerkesztheto)",
      "árvíztűrő" in p.read_text(encoding="utf-8"))
check("behuzott (olvashato) JSON", "\n  " in p.read_text(encoding="utf-8"))

# ══ 2. ATOMICITAS: a regi tartalom tullel egy elszallo szerializalast ═════

_before = p.read_text(encoding="utf-8")


class _NemSzerializalhato:
    pass


err = write_config_file({"a": _NemSzerializalhato()}, p)
check("szerializalhatatlan ertek -> HIBAUZENET (nem kivetel)", bool(err), repr(err))
check("...es a REGI tartalom ERINTETLEN (nem csonkolt fajl)",
      p.read_text(encoding="utf-8") == _before)
check("nem maradt felkesz .tmp fajl",
      not (TMP / "config.json.tmp").exists(),
      str(sorted(x.name for x in TMP.iterdir())))

# ══ 3. Irhatatlan cel -> beszedes hiba, nem nema nyeles ═══════════════════

err = write_config_file({"a": 1}, TMP / "nincs_ilyen_konyvtar" / "config.json")
check("irhatatlan ut -> hibauzenet", bool(err), repr(err))
check("a hibauzenet a FAJLNEVET is tartalmazza", "config.json" in err, err)

# ══ 4. save_main_config: a strategia-szekciok kiszurve ════════════════════

CFG = {"trading": {"max_open_slots": 4},
       "indicators": {"csak_a_strategiae": 1},      # STRATEGY_SECTIONS
       "sltp": {"szinten": 2},
       "optimizer": {"max_trials": 10, "wpr_sma_tartomany": [1, 2]}}
p2 = TMP / "main.json"
err = save_main_config(CFG, p2)
check("save_main_config sikeres", err == "", repr(err))
_w = json.loads(p2.read_text(encoding="utf-8"))
check("a strategia-szekciok NEM kerultek a fajlba",
      "indicators" not in _w and "sltp" not in _w, str(sorted(_w)))
check("a vaz-szekciok bent maradtak", _w.get("trading") == {"max_open_slots": 4})
check("az optimizer MOTOR-kulcsa bent, a strategia-tere nem",
      _w.get("optimizer") == {"max_trials": 10}, str(_w.get("optimizer")))
check("save_main_config == main_config_view + write (nincs ketto igazsag)",
      _w == main_config_view(CFG))

# A ket fuggveny SZETVALASZTASA szandekos: aki mar kesz vaz-dictet tart (a ⚙
# szerkeszto), az a nyers irot hivja — kulonben a nezet-szures ketszer futna.
p3 = TMP / "raw.json"
write_config_file({"indicators": {"marad": 1}}, p3)
check("write_config_file NEM szur (kesz dictet ir, ahogy kapta)",
      json.loads(p3.read_text(encoding="utf-8")) == {"indicators": {"marad": 1}})

# ══ 5. A GUI hivasi helyei ════════════════════════════════════════════════

gsrc = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")

check("gui.py: NINCS tobbe nyers open(config.json, 'w')",
      'open(ROOT / "config.json", "w"' not in gsrc)
_sm = gsrc.split("def _save_main_config")[1].split("\n    def ")[0]
check("_save_main_config: a kozos atomikus irot hivja",
      "save_main_config as _save" in _sm and "_save(self.cfg" in _sm)
# A DOKSIT levagjuk: az szandekosan IDEZI a regi, nema mintat („`except
# Exception: pass` állt itt"). A naiv substring-kereses ezt hibanak venne — a
# TORZS-et kell nezni.
_sm_body = _sm.split('"""')[2] if _sm.count('"""') >= 2 else _sm
check("_save_main_config: a TORZSBEN nincs tobbe nema 'except Exception: pass'",
      "except Exception:" not in _sm_body and "pass" not in _sm_body,
      _sm_body.strip()[:160])
check("_save_main_config: hibanal az ALLAPOTSORBA ir",
      "_set_status" in _sm and "gui.ctrl.not_saved" in _sm
      and _says("gui.ctrl.not_saved", "NEM mentődött el"))
check("_save_main_config: bool-t ad vissza (a hivo tud rola)",
      "-> bool:" in _sm and "return False" in _sm and "return True" in _sm)

# A ket SZANDEK-hordozo hivo ne nyomja el a hibauzenetet a sajat
# „elindítva"/„leállítva" szovegevel — kulonben a figyelmeztetes felvillanna es
# eltunne, ami rosszabb, mint ha ott sem lenne.
_start = gsrc.split("def _start_strategy")[1].split("\n    def ")[0]
check("_start_strategy: figyeli a mentes eredmenyet",
      "_saved = self._save_main_config()" in _start)
check("_start_strategy: sikertelen mentesnel MAS uzenetet ad",
      "if _saved:" in _start and "gui.ctrl.started_unsaved" in _start
      and _says("gui.ctrl.started_unsaved", "nem folytatódik"))
_stop = gsrc.split("def _stop_strategy")[1].split("\n    def ")[0]
check("_stop_strategy: figyeli a mentes eredmenyet",
      "_saved = self._save_main_config()" in _stop)
check("_stop_strategy: sikertelen mentesnel MAS uzenetet ad",
      "if _saved else" in _stop and "gui.ctrl.stopped_unsaved" in _stop
      and _says("gui.ctrl.stopped_unsaved", "visszaindulna"))

# A ⚙ szerkeszto is atomikusan ir (es a nyers irot hasznalja: a `new` mar vaz)
# v2.9.0: a ⚙ ablak HAROM bal oldali fulre bomlott (Json / Kapuk / Strategiak);
# a mentes-ag a "Json" lap ala kerult, de UGYANAZ a kozos iro.
_set = gsrc.split("def _show_settings")[1]
check("a ⚙ mentes a kozos (nyers) irot hasznalja",
      "write_config_file as _write" in _set and "_write(new," in _set)
check("a ⚙ mentes a hibat a sajat cimkejere teszi",
      "lbl_err.config(text=_err)" in _set)

# ══ 6. ISMETELT KULCS: a json.load nemán az UTOLSOT tartja meg ═══════════
#
# A `config.example.json`-ban KET `gates` szekcio volt (v2.1.0-ig): az elso
# teljes egeszeben halott, mert a masodik felulirta. A JSON ezt megengedi, a
# betoltes nem szol — a fajlt olvasva viszont az ELSOT hiszed ervenyesnek. Ezt
# egy kezi atnezes talalta meg, nem a program; azota a betoltes elkapja.

from strategy.settings import duplicate_keys

check("egyszeru dupla kulcs -> jelezzuk",
      duplicate_keys('{"a": 1, "b": 2, "a": 3}') == ["a"],
      str(duplicate_keys('{"a": 1, "b": 2, "a": 3}')))
check("tiszta JSON -> ures lista", duplicate_keys('{"a": 1, "b": 2}') == [])
check("FESZKELT objektumban is fog", duplicate_keys('{"x": {"g": 1, "g": 2}}') == ["g"])
check("tobb kulonbozo dupla -> mind, rendezve",
      duplicate_keys('{"b": 1, "b": 2, "a": 3, "a": 4}') == ["a", "b"])
check("ugyanaz a kulcsnev MAS objektumokban NEM dupla",
      duplicate_keys('{"x": {"g": 1}, "y": {"g": 2}}') == [])
check("a dupla kulcs nem valtoztat az EREDMENYEN (az utolso nyer)",
      json.loads('{"a": 1, "a": 3}') == {"a": 3})

# A ket leszallitott config LEGYEN tiszta.
for _f in ("config.json", "config.example.json"):
    _p = ROOT / _f
    if _p.exists():
        _d = duplicate_keys(_p.read_text(encoding="utf-8"))
        check(f"{_f}: NINCS ismetelt kulcs", _d == [], str(_d))

# A `load_config` szol rola (nem gatol).
_ssrc = (ROOT / "strategy" / "settings.py").read_text(encoding="utf-8")
_lc = _ssrc.split("def load_config")[1]
check("load_config: ellenorzi az ismetelt kulcsokat", "duplicate_keys(text)" in _lc)
check("load_config: csak FIGYELMEZTET, nem gatol",
      "log.warning" in _lc and "raise" not in _lc)

# ══ 7. Vegpontok: a repo config.json-ja ertelmes marad ════════════════════

real = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
check("az eles config.json ervenyes JSON es van benne pairs",
      isinstance(real.get("pairs"), dict) and len(real["pairs"]) > 1)
check("nem maradt .tmp a repo gyokereben",
      not (ROOT / "config.json.tmp").exists())

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
