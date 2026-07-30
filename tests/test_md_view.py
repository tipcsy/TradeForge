"""Strategia-leiras `.md`-bol, formazva (tegnapi lista #7).

A feldolgozas TISZTA fuggveny (`parse`), ezert tesztelheto tkinter nelkul. A
legfontosabb allitas: a parser SEMMIT nem dob el — egy nema elnyeles itt azt
jelentene, hogy a doksi egy resze hianyzik, es ezt senki nem venne eszre.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from dashboard import md_view as mv

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def tags(md):
    return [t for t, _ in mv.parse(md)]


# ══ 1. Cimsorok ══════════════════════════════════════════════════════════
check("h1 / h2 / h3 felismerve",
      tags("# A\n## B\n### C") == [mv.H1, mv.H2, mv.H3], str(tags("# A\n## B\n### C")))
check("a cimsor SZOVEGE a # nelkul",
      mv.parse("## Cim itt")[0][1] == "Cim itt", str(mv.parse("## Cim itt")[0]))
check("a hosszabb # nyer (### nem lesz #)",
      mv.parse("### X")[0][0] == mv.H3)

# ══ 2. Soron beluli formazas ═════════════════════════════════════════════
_, val = mv.parse("sima **felkover** es `kod` vege")[0]
segs = val[1]
check("inline szeletek: szoveg + felkover + kod",
      [t for t, _ in segs] == [mv.TEXT, mv.BOLD, mv.TEXT, mv.CODE, mv.TEXT],
      str([t for t, _ in segs]))
check("a felkover SZOVEGE csillagok nelkul",
      [s for t, s in segs if t == mv.BOLD] == ["felkover"])
check("a kod SZOVEGE backtick nelkul",
      [s for t, s in segs if t == mv.CODE] == ["kod"])

# ══ 3. Listak ════════════════════════════════════════════════════════════
check("- * + es szamozott lista is lista",
      tags("- a\n* b\n+ c\n1. d") == [mv.LIST] * 4, str(tags("- a\n* b\n+ c\n1. d")))
check("a lista eleme is kap inline formazast",
      mv.parse("- **X** y")[0][1][1][0][0] == mv.BOLD)

# ══ 4. Kodblokk — SZO SZERINT ════════════════════════════════════════════
md = "elotte\n```\n# ez NEM cimsor\n- ez NEM lista\n```\nutana"
t = tags(md)
check("a kodblokk EGY elem", t.count(mv.CODE) == 1, str(t))
body = [v for tg, v in mv.parse(md) if tg == mv.CODE][0]
check("a kodblokkban a # NEM cimsor lett", "# ez NEM cimsor" in body, body[:40])
check("...es a - sem lista", "- ez NEM lista" in body)
check("lezaratlan kodblokk sem veszik el",
      "bent" in [v for tg, v in mv.parse("```\nbent") if tg == mv.CODE][0])

# ══ 5. Tablazat / idezet / vonal ═════════════════════════════════════════
tb = mv.parse("| a | b |\n|---|---|\n| 1 | 2 |")
check("a szeparator-sor KIMARAD", len([x for x in tb if x[0] == mv.TABLE]) == 2,
      str([x[0] for x in tb]))
check("a cellak listaban jonnek", tb[0][1] == ["a", "b"], str(tb[0][1]))
check("idezet felismerve", mv.parse("> figyelem")[0][0] == mv.QUOTE)
# Az idezet is kap inline formazast: az elso valtozat a nyers szoveget adta at,
# ezert a **felkover** CSILLAGOKKAL jelent meg a nezetben (kepernyokep fogta meg).
_q = mv.parse("> **fontos** dolog")[0][1]
check("az idezetben a felkover FORMAZODIK (nem csillagokkal latszik)",
      _q[0] == "inline" and _q[1][0][0] == mv.BOLD, str(_q))
check("...es a csillagok eltunnek a szovegbol",
      "**" not in mv.plain_text("> **fontos** dolog"))
check("vizszintes vonal felismerve", tags("---")[0] == mv.RULE)
check("rovid kotojel NEM vonal (lista lehet)", tags("- x")[0] == mv.LIST)

# ══ 5b. BEKEZDES-OSSZEFOLYATAS ═══════════════════════════════════════════
# A Markdown-ban a bekezdesen beluli sortores csak szokoz. Enelkul egy ket sorra
# tordelt **felkover** egyik felen sincs par -> NYERSEN, csillagokkal jelenik meg.
# A kepernyokep fogta meg (a wpr_sma doksi idezetében).
NL = chr(10)
for _lbl, _md in (("bekezdes", "sima **ket" + NL + "sorra** tordelve."),
                  ("idezet",   "> **egy" + NL + "> ketto** harom.")):
    _out = mv.plain_text(_md)
    check(f"{_lbl}: a sortordelt felkover OSSZEFOLYIK (nincs csillag)",
          "**" not in _out, _out)
_abc = "a" + NL + "b" + NL + "c"
check("a bekezdes EGY blokk lesz (nem soronkent kulon)",
      len([t for t, _ in mv.parse(_abc) if t == mv.TEXT]) == 1,
      str([t for t, _ in mv.parse(_abc)]))
check("ures sor ELVALASZTJA a bekezdeseket",
      len([t for t, v in mv.parse("a" + NL + NL + "b")
           if t == mv.TEXT and v]) == 2)
# Az UTOLSO bekezdes sem tunhet el (a ciklus vegi zaras nelkul eltunt volna —
# az ujrairas soran egyszer ki is maradt, es a parse() URES listat adott).
check("az UTOLSO bekezdes megvan (nincs elveszett puffer)",
      "vege" in mv.plain_text("cim" + NL + NL + "ez a vege"))
check("cimsor UTAN kezdodo bekezdes is megvan",
      "torzs" in mv.plain_text("# Cim" + NL + "torzs szoveg"))

# ══ 5c. BEAGYAZOTT JELOLES es TABLAZAT-CELLA ═════════════════════════════
# Mindkettot a kepernyokep fogta meg: a `**`kod`**` alakban a backtickek, a
# tablazat-cellaban pedig a ** jelentek meg NYERSEN.
_nested = mv.parse("Az **`atr`** modszer")[0][1][1]
check("beagyazott bold+kod: a backtickek ELTUNNEK",
      all("`" not in s for _t, s in _nested), str(_nested))
check("...es a tartalom megmarad",
      "atr" in "".join(s for _t, s in _nested))
_tcell = mv.parse("| AUC | **0,5 = veletlen** |")[0][1]
check("tablazat-cella: a ** ELTUNIK (a tartalom marad)",
      _tcell == ["AUC", "0,5 = veletlen"], str(_tcell))
# A KESZ doksikban semmilyen nyers jelolo nem maradhat.
from strategy import get_strategy_by_name as _gs
for _nm in ("wpr_sma", "ml_ai"):
    _pt = mv.plain_text(_gs(_nm).doc_text())
    check(f"{_nm} doksi: NINCS nyers ** a nezetben", "**" not in _pt)
    check(f"{_nm} doksi: NINCS nyers backtick a nezetben", "`" not in _pt)

# ══ 6. A LENYEG: semmi nem tunik el ══════════════════════════════════════
SRC = """# Cim

Bevezeto **kiemelt** szoveggel es `kod`-dal.

## Alcim
- elso pont
- masodik pont

| fej | ertek |
|---|---|
| a | 1 |

> Figyelmeztetes.

```
kodblokk sor
```
Zaro bekezdes.
"""
plain = mv.plain_text(SRC)
for word in ("Cim", "Bevezeto", "kiemelt", "kod", "Alcim", "elso", "masodik",
             "fej", "ertek", "Figyelmeztetes", "kodblokk", "Zaro"):
    if word not in plain:
        check(f"'{word}' MEGVAN a feldolgozas utan", False, plain[:120])
        break
else:
    check("MINDEN erdemi szo megvan a feldolgozas utan (semmi nem tunik el)", True)

# ══ 7. Robusztussag ══════════════════════════════════════════════════════
check("ures bemenet -> ures lista", mv.parse("") == [])
check("None -> nem robban", mv.parse(None) == [])
check("csak ures sorok -> nem robban", len(mv.parse("\n\n\n")) == 3)
check("ismeretlen szintaxis SZOVEGKENT megjelenik (nem tunik el)",
      "~~~valami~~~" in mv.plain_text("~~~valami~~~"))

# ══ 8. A strategia-seam ══════════════════════════════════════════════════
from strategy import get_strategy_by_name, registered_strategy_names
for nm in registered_strategy_names():
    st = get_strategy_by_name(nm)
    p = st.doc_path()
    check(f"{nm}: doc_path a strategy/docs ala mutat",
          p.parent.name == "docs" and p.name == f"{nm}.md", str(p.name))
    txt = st.doc_text()
    check(f"{nm}: doc_text SOSE ures (hianyzo fajlnal is beszedes)",
          bool(txt.strip()) and nm in txt)
    if not p.exists():
        check(f"{nm}: hianyzo doksinal az ELVART utvonal latszik", str(p) in txt)

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
