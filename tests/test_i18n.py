"""Nyelvi katalogus — core/i18n.py + lang/*.json.

A forditas legveszelyesebb hibaja a NEMA: egy hianyzo kulcs ures gombfelirat,
egy elirt helykitolto pedig egy nyers `{symbol}` a kepernyon — mindketto csak
akkor derul ki, ha valaki EPP azon a nyelven hasznalja a programot. Ezek a
tesztek ezt hozzak elore.

⚠ EZ A TESZT NEM IR SEMMIT. A katalogusokat es a configot csak olvassa.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import i18n

ROOT = Path(__file__).resolve().parents[1]
LANG = ROOT / "lang"

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def raw(code):
    """A nyers fajl — a `_comment` kulcsokkal egyutt."""
    with open(LANG / f"{code}.json", encoding="utf-8") as f:
        return json.load(f)


def keys(code):
    return {k for k, v in raw(code).items()
            if isinstance(v, str) and not k.startswith("_")}


def placeholders(s):
    return set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", s))


# ══ 1. A fajlok letezese es alakja ═════════════════════════════════════════
check("van lang/ mappa", LANG.is_dir())
for code in i18n.LANGUAGES:
    check(f"van katalogus: {code}.json", (LANG / f"{code}.json").exists())

base_keys = keys(i18n.BASE_LANG)
check("az alapnyelvi katalogus nem ures", len(base_keys) > 0, f"{len(base_keys)} kulcs")

# ⚠ Nyelvenkent UGYANAZ a kulcskeszlet. Uj kulcs = MINDEN katalogusba, egyszerre.
# Kulonben egy uj funkcio magyarul jelenik meg az angol feluleten, es senki nem
# szol rola — a visszaeses ugyanis szandekosan nema a felhasznalo fele.
for code in i18n.LANGUAGES:
    if code == i18n.BASE_LANG:
        continue
    k = keys(code)
    check(f"{code}: nincs hianyzo kulcs", not (base_keys - k),
          ", ".join(sorted(base_keys - k)[:5]))
    check(f"{code}: nincs arva (alapnyelvben nem letezo) kulcs", not (k - base_keys),
          ", ".join(sorted(k - base_keys)[:5]))

# ══ 2. Kulcs-konvencio es ertekek ══════════════════════════════════════════
# A terulet-nev is tartalmazhat alahuzast (`trade_mode.live`): a kulcsok a
# MODUL nevet tukrozik, es az konnyebben megtalalhatova teszi oket.
_KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
bad_keys = sorted(k for k in base_keys if not _KEY_RE.match(k))
check("minden kulcs a konvenciot koveti (<terulet>.<elem>, kisbetu)",
      not bad_keys, ", ".join(bad_keys[:5]))

# ⚠ A `number.*` kivetel: az ezres elvalaszto magyarul NEM TORO SZOKOZ, tehat
# szandekosan „ures" a `.strip()` szemeben. Ha ezt nem vennenk ki, a helyes
# ertek buktatna a tesztet — es a javitas az lenne, hogy elrontjuk.
for code in i18n.LANGUAGES:
    empty = sorted(k for k, v in raw(code).items()
                   if not k.startswith("_") and isinstance(v, str)
                   and not v.strip() and not k.startswith("number."))
    check(f"{code}: nincs ures szoveg", not empty, ", ".join(empty[:5]))
check("a magyar ezres elvalaszto NEM TORO szokoz",
      raw("hu")["number.group"] == " ",
      repr(raw("hu")["number.group"]))

# ⚠ A HELYKITOLTOK NYELVENKENT AZONOSAK. Egy elgepelt `{trade}` a `{trades}`
# helyett nem hibauzenet, hanem egy nyers kapcsos zarojel a kepernyon.
for code in i18n.LANGUAGES:
    if code == i18n.BASE_LANG:
        continue
    other = raw(code)
    diff = [k for k in base_keys & keys(code)
            if placeholders(raw(i18n.BASE_LANG)[k]) != placeholders(other[k])]
    check(f"{code}: a helykitoltok egyeznek az alapnyelvvel", not diff,
          ", ".join(sorted(diff)[:5]))

# ══ 3. A `t()` viselkedese ═════════════════════════════════════════════════
i18n.set_language("hu")
check("t() az alapnyelven a magyar szoveget adja",
      i18n.t("quality.good") == raw("hu")["quality.good"])

i18n.set_language("en")
check("t() a valasztott nyelven forditva ad",
      i18n.t("quality.good") == raw("en")["quality.good"])

# ⚠ A visszaeses NEM kivetel: a felulet nem allhat meg egy hianyzo forditas
# miatt. A hianyt a naplo es a scanner mondja meg, nem egy osszeomlas.
check("ismeretlen kulcs -> maga a kulcs (nem kivetel, nem ures)",
      i18n.t("nincs.ilyen.kulcs") == "nincs.ilyen.kulcs")
check("a hianyzo kulcs bekerul a missing_keys listaba",
      "nincs.ilyen.kulcs" in i18n.missing_keys())

check("helykitolto behelyettesites",
      i18n.t("quality.why.few_trades", trades=7) == raw("en")["quality.why.few_trades"]
      .format(trades=7))
check("hianyzo helykitolto eseten a nyers szoveg jon (nincs kivetel)",
      i18n.t("quality.why.few_trades") == raw("en")["quality.why.few_trades"])

i18n.set_language("nincs_ilyen")
check("ismeretlen nyelv -> alapnyelv", i18n.language() == i18n.BASE_LANG)
i18n.set_language("hu")

check("has() igazat mond a letezo kulcsra", i18n.has("theme.light"))
check("has() hamisat a nem letezore", not i18n.has("theme.nincs_ilyen"))

# ══ 4. Kod -> cimke leképezesek (Fazis 1) ══════════════════════════════════
# ⚠ Ez a teszt lelke: minden AZONOSITO-nak lennie kell felirata MINDEN nyelven.
# A kod-kulcs ott van a JSON-ban is, ezert egy uj allapot bevezetese, aminek
# elfelejtettek szoveget adni, itt bukik el — nem a felhasznalo kepernyojen.
from core import quality as _q
from core import mt_deploy as _md
from dashboard import theme as _th

check("minden minosites-kodnak van felirata",
      all(i18n.has(f"quality.{c}") for c in _q.GRADES), str(_q.GRADES))
check("a minosites rangsora minden kodot ismer",
      all(_q.grade_rank(c) < 4 for c in _q.GRADES))
check("minden temanak van felirata",
      all(i18n.has(k) for k in _th.THEME_LABEL_KEYS.values()),
      str(list(_th.THEMES)))
check("minden telepites-allapotnak van felirata",
      all(i18n.has(f"deploy.state.{c}") for c in _md.STATES), str(_md.STATES))

from dashboard import trade_list as _tl
check("minden kotes-oszlopnak van felirata",
      all(i18n.has(f"trades.col.{c}") for c in _tl.COLS), str(_tl.COLS))
check("minden kotes-oszlopnak van fajtaja (rendezes/formazas)",
      all(c in _tl.KINDS for c in _tl.COLS))


# ══ 5. A `_t` NEV NEM LEHET LOKALIS VALTOZO ════════════════════════════════
# ⚠ EZ MAR ELSULT. Az `instrument_dialog._build` egy ciklusvaltozot hivott
# `_t`-nek (`for _c, (_t, _w) in ...`), amitol a Python az EGESZ metodusban
# lokalisnak vette a nevet — es a metodus ELSO forditas-hivasa
# `UnboundLocalError`-ral allt meg. A hiba nem ott van, ahol a valtozo: barhol
# a fuggvenyben elhelyezve elviszi az egesz fuggvenyt, es csak futaskor latszik.
import ast

ROOT_PY = [p for p in ROOT.rglob("*.py")
           if not any(d in p.parts for d in {".venv", "__pycache__", "build",
                                             "tananyag", "tests"})]
shadow = []
for p in ROOT_PY:
    try:
        src = p.read_text(encoding="utf-8")
        if "core.i18n import t as _t" not in src:
            continue
        tree = ast.parse(src)
    except Exception:
        continue
    for n in ast.walk(tree):
        if ((isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
             and n.id == "_t") or (isinstance(n, ast.arg) and n.arg == "_t")):
            shadow.append(f"{p.relative_to(ROOT)}:{n.lineno}")
check("a forditot hasznalo modulokban nincs `_t` nevu valtozo", not shadow,
      ", ".join(shadow[:5]))


# ══ 6. A LEIRAS-FAJLOK nyelvvalasztasa ═════════════════════════════════════
# ⚠ A leirasok NEM a katalogusban vannak (tobb ezer szo Markdown), hanem
# `<nev>.<nyelv>.md` fajlokban. A visszaeses itt FORDITVA nema-ellenes: hianyzo
# forditasnal a MAGYAR eredeti latszik, es a `doc_note` kiirja, hogy
# forditatlant olvasol. Egy ures „Leiras" ful azt sugallna, hogy nincs is
# dokumentacio.
import tempfile

with tempfile.TemporaryDirectory() as _d:
    _dir = Path(_d)
    (_dir / "van.md").write_text("HU", encoding="utf-8")
    (_dir / "van.en.md").write_text("EN", encoding="utf-8")
    (_dir / "csak_hu.md").write_text("HU", encoding="utf-8")

    i18n.set_language("hu")
    check("magyarul mindig az alapnyelvi fajl",
          i18n.doc_path(_dir, "van").name == "van.md")
    check("...es nincs megjegyzes", i18n.doc_note(_dir, "van") == "")

    i18n.set_language("en")
    check("angolul a forditas, ha van",
          i18n.doc_path(_dir, "van").name == "van.en.md")
    check("...es ilyenkor sincs megjegyzes", i18n.doc_note(_dir, "van") == "")
    check("forditas hijan a MAGYAR eredeti (nem ures lap)",
          i18n.doc_path(_dir, "csak_hu").name == "csak_hu.md")
    check("...de a megjegyzes SZOL rola",
          "English" in i18n.doc_note(_dir, "csak_hu"))
    i18n.set_language("hu")

# A valodi leirasok: minden kapunak es strategianak, aminek van magyar doksija,
# feloldodik-e az utvonala mindket nyelven (a fajl letezese nem kovetelmeny —
# azt a scanner jelenti).
from core import gates as _gt
for _k in _gt.KEYS:
    i18n.set_language("en")
    _p = _gt.doc_path(_k)
    i18n.set_language("hu")
    check(f"kapu-leiras utvonala felold: {_k}", _p.name.startswith(_k))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
