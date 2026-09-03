"""A fordítás állapota egy parancsban.

    python tools/i18n_scan.py            # összesítő + a katalógusok egészsége
    python tools/i18n_scan.py --files    # fájlonkénti hátralék (Fázis 2 mérce)
    python tools/i18n_scan.py --list dashboard/gui.py   # a konkrét szövegek

Három kérdésre válaszol:

  1. **Egészséges-e a katalógus?** hiányzó / árva kulcs, eltérő helykitöltő.
  2. **Mennyi van hátra?** hány magyar szövegliterál van még a kódban, fájlonként
     — ez a haladás mérőszáma az átvezetés alatt.
  3. **Mi maradt ki?** kulcsok, amikre a kód sehol nem hivatkozik (`t("…")`).

⚠ MIÉRT KELL EZ KÜLÖN A TESZT MELLÉ. A teszt IGEN/NEM választ ad — egy hiányzó
kulcsnál elbukik. A hátralék viszont nem hiba, hanem MENNYISÉG: az átvezetés
közben végig nagy, és épp az a kérdés, csökken-e. Egy elbukó teszt erre nem
alkalmas: hetekig piros lenne, és megszoknánk.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import i18n  # noqa: E402

HU_CHARS = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
# A naplót és a kutató-szkripteket nem fordítjuk: a napló a fejlesztőé (és a
# hibajelentésé), a `tools/` egy része pedig egyszeri mérés.
SKIP_DIRS = {".venv", "__pycache__", ".git", "tananyag", "tests", "build", "lang"}
LOG_FUNCS = {"debug", "info", "warning", "error", "exception", "critical"}


def _py_files():
    for p in sorted(ROOT.rglob("*.py")):
        if not any(d in p.parts for d in SKIP_DIRS):
            yield p


def _hu(s: str) -> bool:
    return any(c in HU_CHARS for c in s)


def _untranslated(path: Path):
    """A fájlban maradt magyar szövegliterálok — docstring, komment és
    naplóhívás NÉLKÜL. (A komment nem is literál, tehát az AST-ben nincs benne.)"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            skip.add(id(node.body[0].value))
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else "")
            if name in LOG_FUNCS:
                for a in list(node.args) + [k.value for k in node.keywords]:
                    for sub in ast.walk(a):
                        skip.add(id(sub))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip):
            s = node.value.strip()
            if _hu(s) and len(s) > 2:
                out.append((node.lineno, s))
    return out


def _used_keys():
    """Amire a kód hivatkozik: konkrét kulcsok és kulcs-ELŐTAGOK.

    ⚠ AZ ELŐTAG NEM KÉNYELEM. A kód-kulcsos leképezések épp azért léteznek, hogy
    a kulcs futásidőben álljon össze: `_t(f"quality.{code}")`. Egy csak literált
    kereső scanner ezeket MIND „nem hivatkozott"-nak mondaná — a jelentés fele
    hamis riasztás lenne, és pontosan ettől szokik le róla az ember."""
    keys, prefixes = set(), set()
    # `_t("kulcs")` (a projekt alias-szokása), ritkán `t("kulcs")`.
    pat = re.compile(r'(?<![A-Za-z0-9])_?t\(\s*f?["\']([a-z0-9][a-z0-9._]*)'
                     r'(\{[^"\']*)?["\']')
    # ⚠ A `LabelMap("elotag", KODOK)` EGY sorban hivatkozik egy egesz csoportra.
    # Enelkul a jelentes fele hamis riasztas lenne (a kod->felirat tablak mind
    # „nem hivatkozott"-kent latszanak) — es epp ettol szokik le rola az ember.
    lm = re.compile(r'LabelMap\(\s*["\']([a-z0-9][a-z0-9._]*)["\']')
    # bármely pontozott, kisbetűs szöveg-literál (a miértet lásd lent)
    lit = re.compile(r'["\']([a-z0-9_]+(?:\.[a-z0-9_]+)+)["\']')
    for p in _py_files():
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for key, dyn in pat.findall(src):
            (prefixes if dyn else keys).add(key)
        prefixes.update(m + "." for m in lm.findall(src))
        # ⚠ A kulcs nem mindig `_t(...)`-ben all: a kod->kulcs TABLAK (pl.
        # `live_row._HEADER_KEYS`, `theme.THEME_LABEL_KEYS`) sima szotar-ertekkent
        # tartjak, es a feltételes agak masodik fele (`_t(A if x else B)`) is
        # kimaradna. Ezert MINDEN pontozott, kisbetus literalt hivatkozasnak
        # veszunk — a hamis riasztas itt rosszabb, mint a hamis „hasznalt".
        keys.update(lit.findall(src))
    return keys, prefixes


def _placeholders(s: str):
    return set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", s))


def main(argv):
    files_mode = "--files" in argv
    list_target = ""
    if "--list" in argv:
        i = argv.index("--list")
        list_target = argv[i + 1] if i + 1 < len(argv) else ""

    if list_target:
        p = ROOT / list_target
        if not p.exists():
            print(f"nincs ilyen fájl: {list_target}")
            return 1
        rows = _untranslated(p)
        print(f"{list_target} — {len(rows)} lefordítatlan szöveg\n")
        for ln, s in rows:
            print(f"  {ln:>5} | {s[:100]}")
        return 0

    # ── 1. A katalógusok egészsége ────────────────────────────────────────
    base = i18n.catalog(i18n.BASE_LANG)
    print(f"Alapnyelv: {i18n.BASE_LANG} — {len(base)} kulcs\n")
    print("KATALÓGUSOK")
    for code, native in i18n.LANGUAGES.items():
        if code == i18n.BASE_LANG:
            print(f"  {code} ({native}): alapnyelv")
            continue
        cat = i18n.catalog(code)
        missing = sorted(set(base) - set(cat))
        orphan = sorted(set(cat) - set(base))
        badph = sorted(k for k in set(base) & set(cat)
                       if _placeholders(base[k]) != _placeholders(cat[k]))
        pct = 100.0 * (len(base) - len(missing)) / max(1, len(base))
        print(f"  {code} ({native}): {pct:.0f}% kész  ·  hiányzik {len(missing)}"
              f"  ·  árva {len(orphan)}  ·  helykitöltő-eltérés {len(badph)}")
        for k in missing[:10]:
            print(f"      hiányzik: {k}")
        for k in orphan[:10]:
            print(f"      ÁRVA (az alapnyelvben nincs): {k}")
        for k in badph[:10]:
            print(f"      HELYKITÖLTŐ eltér: {k}")

    # ── 2. Nem hivatkozott kulcsok ────────────────────────────────────────
    used, prefixes = _used_keys()
    unused = sorted(k for k in base
                    if k not in used and not any(k.startswith(pf) for pf in prefixes))
    print(f"\nNEM HIVATKOZOTT kulcs: {len(unused)}")
    for k in unused[:15]:
        print(f"  {k}")
    if len(unused) > 15:
        print(f"  … és még {len(unused) - 15}")

    # ── 3. A LEÍRÁS-fájlok (nem a katalógusban élnek) ─────────────────────
    # ⚠ Külön szakasz, mert a leírások NEM kulcsok: több ezer szó Markdown,
    # `<név>.<nyelv>.md` fájlokban. A hiányuk nem hiba (a felület a magyar
    # eredetit mutatja), de MENNYISÉG — és a katalógus 100%-a mellett is
    # maradhat lefordítatlan doksi.
    print("\nLEÍRÁSOK (.md)")
    # ⚠ A lista a REGISZTRÁLT kapukhoz igazodik — különben a jelentés olyasmit
    # kérne számon, amit senki nem olvas a programban. (A `core/docs/` maradt
    # fejlesztői jegyzeteknek, pl. `tick_storage.md`; a KAPUK leírásai v3.29.1
    # óta a kapuval együtt, a `gates/docs/`-ban élnek.)
    from core import gates as _gates
    for label, folder, only in (
            ("kapuk", ROOT / "gates" / "docs", set(_gates.KEYS)),
            ("stratégiák", ROOT / "strategies" / "docs", None)):
        base = sorted(p for p in folder.glob("*.md")
                      if p.name.count(".") == 1
                      and (only is None or p.stem in only))
        for code in i18n.LANGUAGES:
            if code == i18n.BASE_LANG:
                continue
            have = [p for p in base
                    if (folder / f"{p.stem}.{code}.md").exists()]
            miss = [p.stem for p in base if p not in have]
            print(f"  {label} / {code}: {len(have)}/{len(base)}"
                  + (f"  ·  hiányzik: {', '.join(miss)}" if miss else ""))

    # ── 4. Hátralék ───────────────────────────────────────────────────────
    rows = []
    total = 0
    for p in _py_files():
        n = len(_untranslated(p))
        total += n
        if n:
            rows.append((n, str(p.relative_to(ROOT)).replace("\\", "/")))
    rows.sort(reverse=True)
    print(f"\nHÁTRALÉK: {total} magyar szövegliterál {len(rows)} fájlban")
    if files_mode:
        for n, rel in rows:
            print(f"  {n:>5}  {rel}")
    else:
        for n, rel in rows[:12]:
            print(f"  {n:>5}  {rel}")
        if len(rows) > 12:
            print(f"  … (--files a teljes listához)")
    return 0


if __name__ == "__main__":
    try:
        from core import applog
        applog.harden_console()
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
