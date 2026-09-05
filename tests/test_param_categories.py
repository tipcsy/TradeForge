"""A PARAMETER-KATEGORIA AZONOSITO, NEM FELIRAT (0011).

⚠ MI VOLT A BAJ. A paraméter-ablak csoportositasa a MAGYAR SZORA hasonlitott:
a config `"category": "Indikátor – M15"`-ot tarolt, a kod pedig ezt kereste.
Harom kulon baj egyszerre:

  1. LEFORDITHATATLAN. Egy angol csapatnak a config semmit nem mond, es ha
     lefordítanank, a csoportositas SZETESNE — minden parameter az „Egyeb"
     agra kerulne, mert a kod a magyar szot keresi.
  2. KODOLAS-ERZEKENY. Mas karakterkodolasu gepen az ekezet vagy a gondolatjel
     („–", ami NEM kotojel) maskepp jon vissza -> nema rossz ag. A felhasznalo
     epp ezt emelte ki: „nem opcio, hanem megcsinalni valo feladat".
  3. MAR EL IS TORT. A configokban `"SL / TP"` ES `"SL/TP"` is szerepelt —
     ugyanaz a fogalom ket irasmoddal, KET kulon csoport a feluleten.

Mostantol a config AZONOSITOT tarol (`"category": "sltp"`), a feliratot az i18n
adja (`param_cat.sltp`). Uj nyelv = 1 JSON; a strategia-configok nem valtoznak.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog  # noqa: E402
applog.harden_console()

from strategy import settings as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ── 1. A REGI FELIRATOK azonositova ─────────────────────────────────────
check("a regi magyar felirat azonositova valik",
      S.category_id("Indikátor – M15") == "indicator_m15")
check("a hianyzo/ures kategoria -> 'other'",
      S.category_id(None) == S.CAT_OTHER and S.category_id("") == S.CAT_OTHER)

# ⚠ EZ VOLT A VALODI, MAR MEGTORTENT HIBA.
check("a 'SL / TP' es a 'SL/TP' UGYANARRA az azonositora kepzodik",
      S.category_id("SL / TP") == S.category_id("SL/TP") == "sltp",
      "korabban ez ket kulon csoport volt a feluleten")

# ⚠ ISMERETLEN AZONOSITO VALTOZATLANUL MEGY TOVABB — nem lesz belole 'other'.
# Egy `.tfs` csomag hozhat sajat kategoriat, es annak a CSOPORTOSITASA akkor is
# legyen helyes, ha a feliratat nem ismerjuk.
check("ismeretlen azonosito valtozatlanul megy tovabb",
      S.category_id("sajat_kategoria") == "sajat_kategoria")
check("...es NEM esik az 'other' agra",
      S.category_id("sajat_kategoria") != S.CAT_OTHER)


# ── 2. SORREND: a duplikatum kiesik ─────────────────────────────────────
_cfg = {"param_meta": {"categories": ["SL / TP", "SL/TP", "Egyéb"]}}
check("a ket irasmod EGY sorrend-elemme olvad",
      S.category_order(_cfg) == ["sltp", S.CAT_OTHER],
      str(S.category_order(_cfg)))
check("ures/hianyzo param_meta -> ures sorrend", S.category_order({}) == [])


# ── 3. FELIRAT: i18n -> config -> azonosito ─────────────────────────────
check("ismert azonosito feliratot kap az i18n-bol",
      S.category_label("sltp") == "SL / TP", S.category_label("sltp"))
check("ismeretlen azonosito ONMAGAT mutatja (lathato, nem nema)",
      S.category_label("nincs_ilyen_id") == "nincs_ilyen_id")
# A `.tfs` csomag sajat feliratot is hozhat.
_tfs = {"param_meta": {"category_labels": {"sajat": "Saját blokk"}}}
check("a config sajat felirata a tartalek",
      S.category_label("sajat", _tfs) == "Saját blokk")
check("...de az i18n ERTEKESEBB (a sajat felirat nem irja felul)",
      S.category_label("sltp", {"param_meta": {"category_labels":
                                               {"sltp": "NE EZ"}}}) == "SL / TP")


# ── 4. A MIGRALT CONFIGOK: csak azonositok ──────────────────────────────
# ⚠ EZ A LENYEG a felhasznalo kodolas-erve szempontjabol: ha a fajlban nincs
# ekezet es nincs gondolatjel, akkor nincs mit elrontania a karakterkodolasnak.
_hibas = []
for f in sorted((ROOT / "strategies" / "config").glob("*.json")):
    pm = json.loads(f.read_text(encoding="utf-8")).get("param_meta") or {}
    ertekek = list(pm.get("categories") or [])
    ertekek += [v.get("category") for v in (pm.get("params") or {}).values()
                if isinstance(v, dict) and v.get("category")]
    for e in ertekek:
        # ASCII, kisbetu, alulvonas — semmi, amit a kodolas elronthat.
        if not str(e).isascii() or str(e) != str(e).lower():
            _hibas.append(f"{f.name}:{e!r}")
check("EGYETLEN strategia-config sem tarol feliratot kategoriakent",
      not _hibas, "; ".join(_hibas[:4]))

# …es minden hasznalt azonositonak van feliratа mindket nyelven.
_hasznalt = set()
for f in (ROOT / "strategies" / "config").glob("*.json"):
    pm = json.loads(f.read_text(encoding="utf-8")).get("param_meta") or {}
    _hasznalt |= set(pm.get("categories") or [])
    _hasznalt |= {v.get("category") for v in (pm.get("params") or {}).values()
                  if isinstance(v, dict) and v.get("category")}
_hasznalt |= {S.CAT_EXEC, S.CAT_OTHER}
for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    _hiany = sorted(c for c in _hasznalt if f"param_cat.{c}" not in d)
    check(f"{lang}: minden hasznalt kategorianak van felirata", not _hiany, str(_hiany))


# ── 5. A FELULET VALTOZATLAN MARAD magyarul ─────────────────────────────
# ⚠ A migracio VISELKEDES-SEMLEGES: ugyanazok a csoportok, ugyanabban a
# sorrendben, ugyanazokkal a feliratokkal — csak mar nem a felirat AZ adat.
_VART = {
    "wpr_sma": ["Indikátor – M15", "Indikátor – M1", "SL / TP",
                "Kockázatkezelés", "Piac-szűrő", "Egyéb"],
    "trend_pullback": ["Belépő – M5", "Volatilitás – M30", "Trend – H1",
                       "SL / TP", "Egyéb"],
    "candle_level_break": ["Szint", "Belépő", "SL / TP", "Piac-szűrő", "Egyéb"],
}
for nev, vart in _VART.items():
    c = S.load_strategy_config(nev)
    kapott = [S.category_label(i, c) for i in S.category_order(c)]
    check(f"{nev}: a feliratok es a sorrend valtozatlanok", kapott == vart,
          str(kapott))

# Egy parameter kategoriaja is azonosito.
_c = S.load_strategy_config("wpr_sma")
check("a param_category azonositot ad", S.param_category(_c, "sma_period") == "indicator_m15",
      S.param_category(_c, "sma_period"))
check("ismeretlen parameter -> 'other'",
      S.param_category(_c, "nincs_ilyen_parameter") == S.CAT_OTHER)


# ── 6. A KOD NE HASONLITSON MAGYAR SZORA ────────────────────────────────
# ⚠ Ez a regresszio-or: a magyar literal konnyen visszakerul egy kesobbi
# szerkesztesnel, es akkor NEMAN esik szet a csoportositas.
# ⚠ A KOMMENT-SZURES NEM ELEG: a magyar szo DOCSTRINGBEN is elofordul (es ott
# a HELYE — ott magyaraz). A `#`-es szures a docstringet nem veszi ki, ezert a
# teszt hamisan bukott. AST-tal nezzuk: csak a VALODI kod-literalok szamitanak.
import ast as _ast   # noqa: E402

_dlg = (ROOT / "dashboard" / "instrument_dialog.py").read_text(encoding="utf-8")
_fa = _ast.parse(_dlg)
_doc_ids = set()
for _n in _ast.walk(_fa):
    _b = getattr(_n, "body", None)
    if isinstance(_n, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef,
                       _ast.ClassDef)) and _b:
        _e = _b[0]
        if (isinstance(_e, _ast.Expr) and isinstance(_e.value, _ast.Constant)
                and isinstance(_e.value.value, str)):
            _doc_ids.add(id(_e.value))
_literalok = {n.value for n in _ast.walk(_fa)
              if isinstance(n, _ast.Constant) and isinstance(n.value, str)
              and id(n) not in _doc_ids}
for _tiltott in ("Egyéb", "Végrehajtás"):
    check(f"a parameter-ablak KODJA nem hasonlit a(z) {_tiltott!r} literalra",
          _tiltott not in _literalok,
          "kommentben/docstringben szabad")
_kod = _dlg
check("...hanem az azonosito-konstansokat hasznalja",
      "_sset.CAT_OTHER" in _kod and "_sset.CAT_EXEC" in _kod)
check("...es a feliratot a megjelenitesnel oldja fel",
      "_sset.category_label(" in _kod)

# A `_LEGACY_CAT` map MEGMARAD: regi formatumu `.tfs` confignak is mukodnie kell.
check("a regi feliratok megfeleltetese megmaradt (regi .tfs csomagokhoz)",
      len(S._LEGACY_CAT) >= 19, str(len(S._LEGACY_CAT)))



# ── 7. UGYANEZ A KORRELACIO-MODOKRA ─────────────────────────────────────
# ⚠ Ezek MENTETT azonositok (`data/correlation_mode.json`), es korabban a
# MAGYAR FELIRAT volt maga az ertek (`INACTIVE = "Inaktív"`). A felirat
# barmilyen valtoztatasa — forditas VAGY kodolas-elteres — a mentett allapotot
# ervenytelenitette volna: a `load()` csak a MODES-ban levot fogadja el, tehat
# a regi mentes NEMAN visszaesik az alapertelmezesre.
from core import correlation as C   # noqa: E402

check("a korrelacio-modok azonositok (ascii, kisbetu)",
      all(m.isascii() and m == m.lower() for m in C.MODES), str(C.MODES))
check("...es van feliratuk", [C.mode_label(m) for m in C.MODES]
      == ["Inaktív", "Jelző", "Csak erősebb", "Fél méret"],
      str([C.mode_label(m) for m in C.MODES]))
check("ismeretlen mod ONMAGAT mutatja", C.mode_label("nincs_ilyen") == "nincs_ilyen")

# A REGI, magyar feliratu mentes tovabbra is beolvashato.
check("a regi magyar ertek azonositova valik betolteskor",
      C._LEGACY_MODE.get("Csak erősebb") == C.STRONGER)
check("...es a set_mode is elfogadja",
      (C.set_mode("Fél méret"), C.get_mode())[1] == C.HALF)
C.PATH.unlink(missing_ok=True)          # a teszt ne hagyjon maga utan allapotot

for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    _h = [m for m in C.MODES if f"corr_mode.{m}" not in d]
    check(f"{lang}: minden korrelacio-modnak van felirata", not _h, str(_h))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
