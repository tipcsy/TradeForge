"""
Markdown-megjelenítő a stratégia-leírásokhoz.

A stratégia leírása `.md` fájlban él (`strategies/docs/<név>.md`), és a
paraméter-ablakból nyitható meg **formázva**. Nem teljes Markdown-motor: pontosan
annyit tud, amennyi egy stratégia-doksit olvashatóvá tesz — címsorok, félkövér,
listák, kódblokk, táblázat-sorok, idézet, vízszintes vonal.

**Miért nem külső könyvtár.** A projektnek eddig nincs Markdown-függősége, és egy
teljes renderelő (vagy egy beágyazott böngésző) aránytalan lenne egy olvasható
szöveghez. Ez ~100 sor, és nincs új csomag.

A FELDOLGOZÁS (`parse`) szándékosan **tiszta függvény**: `(tag, szöveg)` szeleteket
ad, tkinter nélkül. Így a formázás egy sorban tesztelhető, és a megjelenítő csak
tag-eket ragaszt — nem lehet benne elrejtett logika.
"""

from __future__ import annotations
from core.i18n import t as _t

import re

# Bekezdés-szintű tag-ek (a megjelenítő ezekhez rendel betűt/színt)
H1, H2, H3 = "h1", "h2", "h3"
TEXT = "text"
BOLD = "bold"
LIST = "list"
CODE = "code"
QUOTE = "quote"
RULE = "rule"
TABLE = "table"

_H = ((re.compile(r"^###\s+(.*)$"), H3),
      (re.compile(r"^##\s+(.*)$"), H2),
      (re.compile(r"^#\s+(.*)$"), H1))
_LIST = re.compile(r"^\s*([-*+]|\d+\.)\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> list:
    """Soron belüli formázás: `**félkövér**` és `` `kód` `` → szeletek.

    A maradékot érintetlenül hagyjuk — a `*dőlt*` és a linkek szándékosan
    kimaradnak: egy stratégia-doksiban nem hordoznak plusz jelentést, és minden
    további szabály újabb hibalehetőség."""
    out: list = []
    pos = 0
    # Egy közös menetben keressük mindkettőt, hogy a sorrend ne számítson.
    pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    for m in pattern.finditer(text):
        if m.start() > pos:
            out.append((TEXT, text[pos:m.start()]))
        if m.group(1) is not None:
            # BEÁGYAZOTT jelölés: a `**`kód`**` alakban a félkövér TARTALMA még
            # tartalmazhat backtick-et. Az első változat szó szerint kiírta a
            # backtickeket — a képernyőkép fogta meg. Egy szint elég: mélyebb
            # egymásba ágyazás egy stratégia-doksiban nem fordul elő.
            inner = m.group(1)
            if "`" in inner:
                for _tg, _s in _inline(inner):
                    out.append((CODE if _tg == CODE else BOLD, _s))
            else:
                out.append((BOLD, inner))
        else:
            out.append((CODE, m.group(2)))
        pos = m.end()
    if pos < len(text):
        out.append((TEXT, text[pos:]))
    return out or [(TEXT, "")]


def _cell(text: str) -> str:
    """Táblázat-cella FORMÁZÁS NÉLKÜLI szövege.

    A táblázat szándékosan egyszerű (monospace, igazított): a cellákban nincs
    félkövér/kód-kiemelés, mert az elrontaná a karakter-alapú igazítást. De a
    JELÖLŐKET el kell tüntetni — az első változat nyersen kiírta a `**`-ot, és a
    táblázat úgy nézett ki, mintha hibás lenne."""
    return "".join(s for _tg, s in _inline(text))


def parse(md: str) -> list:
    """Markdown → `[(tag, szöveg), …]` blokk-lista.

    Minden elem EGY megjelenítendő egység; a soron belüli formázást a
    `TEXT`/`BOLD`/`CODE` szeletek adják egy `("inline", [szeletek])` elemben.
    Ismeretlen szintaxis egyszerű szövegként jelenik meg — **nem tűnik el**, mert
    egy néma elnyelés itt azt jelentené, hogy a doksi egy része hiányzik."""
    out: list = []
    in_code = False
    code_buf: list = []
    # BEKEZDÉS-PUFFER: a Markdown-ban a bekezdésen belüli sortörés csak szóköz, a
    # sorokat tehát ÖSSZE KELL FOLYATNI, mielőtt a soron belüli formázás lefut.
    # Enélkül egy két sorra tördelt `**félkövér**` egyik felén sincs pár, és
    # NYERSEN, csillagokkal jelenik meg — a képernyőkép pontosan ezt fogta meg.
    para: list = []
    para_tag = TEXT

    def _flush():
        if para:
            out.append((para_tag, ("inline", _inline(" ".join(para)))))
            para.clear()

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        # ── Kódblokk: a ``` páros között MINDEN sor szó szerint megy át ────
        if stripped.startswith("```"):
            _flush()
            if in_code:
                out.append((CODE, "\n".join(code_buf)))
                code_buf = []
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(raw)
            continue

        # ── Üres sor: a bekezdés VÉGE ─────────────────────────────────────
        if not stripped:
            _flush()
            para_tag = TEXT
            out.append((TEXT, ""))
            continue

        # ── Idézet: BEKEZDÉS, több sora összefolyik ───────────────────────
        if stripped.startswith(">"):
            if para_tag != QUOTE:
                _flush()
                para_tag = QUOTE
            para.append(stripped[1:].strip())
            continue
        if para_tag == QUOTE:            # kilépés az idézetből
            _flush()
            para_tag = TEXT

        # ── Blokk-szintű elemek: mindegyik ZÁRJA a folyó bekezdést ────────
        if set(stripped) <= {"-", "*", "_"} and len(stripped) >= 3:
            _flush()
            out.append((RULE, ""))
            continue
        _hit = False
        for rx, tag in _H:
            m = rx.match(line)
            if m:
                _flush()
                out.append((tag, m.group(1).strip()))
                _hit = True
                break
        if _hit:
            continue
        if stripped.startswith("|"):
            _flush()
            # Táblázat: a szeparátor-sort (|---|---|) kihagyjuk, a többit
            # celláira bontva, egyszerű szövegként igazítva mutatjuk.
            cells = [_cell(c.strip()) for c in stripped.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} and c for c in cells):
                continue
            out.append((TABLE, cells))
            continue
        m = _LIST.match(line)
        if m:
            _flush()
            para_tag = LIST
            para.append(m.group(2))
            continue

        # ── Sima szöveg: a bekezdés-pufferbe (NEM külön blokk) ────────────
        # ⚠ Ha listaelem BEHÚZOTT folytatása, akkor a LISTAELEMHEZ tartozik, nem
        # új bekezdés. A bekezdéseknél már megvolt ez a felismerés (lásd fent), a
        # listáknál nem — így egy két sorra tördelt `**félkövér**` a listaelemen
        # NYERSEN, csillagokkal jelent meg. (A `1.01**` alakot a teszt fogta meg.)
        if para and para_tag == LIST and not raw[:1].strip():
            para.append(stripped)
            continue
        if not para:
            para_tag = TEXT
        para.append(stripped)

    # A CIKLUS VÉGI zárás nélkül az UTOLSÓ bekezdés eltűnne (a puffer benne
    # maradna). Ez az újraírás során egyszer ki is maradt — a teszt fogta meg,
    # `parse()` üres listát adott.
    _flush()
    if in_code and code_buf:          # lezáratlan kódblokk → ne veszítsük el
        out.append((CODE, "\n".join(code_buf)))
    return out


def plain_text(md: str) -> str:
    """A doksi FORMÁZÁS NÉLKÜLI szövege — kereséshez és teszthez.

    Azt őrzi, hogy a `parse()` semmit nem dob el: a visszaadott szöveg minden
    érdemi szót tartalmaz, ami a bemenetben volt."""
    parts: list = []
    for tag, val in parse(md):
        if tag == TABLE:
            parts.append(" ".join(val))
        elif isinstance(val, tuple) and val and val[0] == "inline":
            parts.append("".join(t for _tg, t in val[1]))
        else:
            parts.append(str(val))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Megjelenítő ablak
# ---------------------------------------------------------------------------

def render(parent, md: str, source: "str | None" = None):
    """A leírás BEÁGYAZVA — egy meglévő keretbe, nem külön ablakba.

    Ez a valódi megjelenítő; a `show()` már csak egy Toplevelt tesz köré. Azért
    így, mert a leírás a felhasználó kérésére a beállító form EGYIK LAPJA lett
    (Kapu: „Beállítás · Leírás", Stratégia: „Paraméter · Leírás") — külön
    ablakban nem lehet a paraméterek mellett olvasni, amit épp állítasz.

    Csak tag-eket ragaszt a `parse()` kimenetére — a formázási döntések ott
    vannak, egy helyen. A `source` (fájl-útvonal) a lábban látszik: enélkül nem
    lenne kideríthető, MELYIK fájlt kell szerkeszteni."""
    import tkinter as tk

    from dashboard import theme as _th

    F = _th.fonts()
    holder = tk.Frame(parent, bg=_th.BG)
    holder.pack(fill="both", expand=True)

    body = tk.Frame(holder, bg=_th.BG)
    body.pack(fill="both", expand=True, padx=10, pady=(10, 4))
    vsb = tk.Scrollbar(body)
    vsb.pack(side="right", fill="y")
    txt = tk.Text(body, bg=_th.BG, fg=_th.FG_WHITE, relief="flat", wrap="word",
                  yscrollcommand=vsb.set, padx=8, pady=6,
                  insertbackground=_th.FG_WHITE)
    txt.pack(side="left", fill="both", expand=True)
    vsb.config(command=txt.yview)

    txt.tag_configure(H1, font=F["title"], foreground=_th.FG_WHITE,
                      spacing1=10, spacing3=6)
    txt.tag_configure(H2, font=F["header"], foreground=_th.FG_BLUE,
                      spacing1=10, spacing3=4)
    txt.tag_configure(H3, font=F["small_bold"], foreground=_th.FG_CYAN,
                      spacing1=8, spacing3=2)
    txt.tag_configure(TEXT, font=F["small"], foreground=_th.FG_WHITE)
    txt.tag_configure(BOLD, font=F["small_bold"], foreground=_th.FG_WHITE)
    txt.tag_configure(CODE, font=F["mono"], foreground=_th.FG_GREEN,
                      background=_th.BG_HEADER)
    txt.tag_configure(LIST, font=F["small"], foreground=_th.FG_WHITE,
                      lmargin1=18, lmargin2=32)
    txt.tag_configure(QUOTE, font=F["small"], foreground=_th.FG_YELLOW,
                      lmargin1=14, lmargin2=14)
    txt.tag_configure(TABLE, font=F["mono"], foreground=_th.FG_GRAY)

    def _ins_inline(segments, base_tag):
        for tg, s2 in segments:
            txt.insert("end", s2, (base_tag if tg == TEXT else tg))
        txt.insert("end", "\n")

    for tag, val in parse(md):
        if tag == RULE:
            txt.insert("end", "─" * 70 + "\n", TABLE)
        elif tag == CODE:
            txt.insert("end", str(val) + "\n", CODE)
        elif tag == TABLE:
            txt.insert("end", "  ".join(f"{c:<18}" for c in val) + "\n", TABLE)
        elif tag == LIST:
            txt.insert("end", "  •  ", LIST)
            _ins_inline(val[1], LIST)
        elif isinstance(val, tuple) and val and val[0] == "inline":
            _ins_inline(val[1], TEXT)
        else:
            txt.insert("end", str(val) + "\n", tag)

    txt.config(state="disabled")      # olvasható, de nem szerkeszthető

    if source:
        tk.Label(holder, text=_t("docs.source", source=source), bg=_th.BG, fg=_th.FG_GRAY_DIM,
                 font=F["small"], anchor="w").pack(fill="x", padx=10, pady=(0, 6))
    return holder


def show(parent, title: str, md: str, source: "str | None" = None):
    """A leírás KÜLÖN ABLAKBAN (a `render` köré tett Toplevel)."""
    import tkinter as tk

    from dashboard import theme as _th

    popup = tk.Toplevel(parent)
    popup.title(title)
    popup.configure(bg=_th.BG)
    popup.geometry("760x620")
    tk.Button(popup, text=_t("btn.close"), bg=_th.BTN_DIS_BG, fg=_th.BTN_DIS_FG,
              relief="flat", font=_th.fonts()["small"],
              command=popup.destroy).pack(side="bottom", anchor="e",
                                          padx=10, pady=8)
    render(popup, md, source)
    return popup
