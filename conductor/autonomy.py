"""AUTONÓMIA-LÉTRA ÉS KIKAPCSOLÓ — meddig mehet el a karmester magától.

⚠ A LELET (2026-09-21). A `paths.off_switch()` docstringje azt állította, hogy
„a szál minden ciklus elején megnézi" — közben az egész kódbázisban EGYETLEN
hivatkozás volt rá: a saját definíciója. A kapcsoló, amit a terv a karmester
első számú feltételének nevez, nem létezett. Ez a modul az, ami mögé áll.

⚠ MIÉRT NEM ELÉG EGY `bool`. „Kikapcsolható" és „önálló" nem két állapot, hanem
egy LÉTRA két vége. A köztes fokok azok, amiken a rendszer élni fog: mérni már
mérjen, de ne javasoljon; javasoljon, de ne hajtson végre. Egy kapcsoló ezt nem
tudja kifejezni, és aki csak kapcsolót kap, az vagy vakon bízik, vagy kikapcsol.

── A LÉTRA ────────────────────────────────────────────────────────────────
  L-1  KIKAPCSOLT   nem figyel, nem ír, nem riportol — el sem indul
  L0   MEGFIGYELŐ   csak mér és naplóz; nincs javaslat, nincs értesítés
  L1   TANÁCSADÓ    javasol, MINDENT ember hagy jóvá
  L2   SEGÍTETT     a visszafordítható, kockázatCSÖKKENTŐ lépések gépiek
  L3   KORLÁTOZOTT  a teljes akciókészlet gépi — kvótán és hatókörön belül
  L4   TELJES       nincs emberi jóváhagyási lépés (a burok marad)

⚠ MA AZ L2–L4 UGYANAZT TESZI, MINT AZ L1. A gépi végrehajtás az F3/b tartalma;
amíg nincs meg, a magasabb fok BEÁLLÍTHATÓ, de nem hazudunk önállóságot: a
`level_text()` kiírja, hogy a fok a végrehajtásig tanácsadóként viselkedik. Egy
„L3" felirat, ami mögött semmi nincs, pontosan az a néma hiba, ami ezt a modult
kikényszerítette.

── A FELOLDÁS SORRENDJE ───────────────────────────────────────────────────
  1. KILL-SWITCH FÁJL (`data/conductor/off`) → L-1, MINDENHOL, azonnal.
  2. CELLA:          conductor.autonomy.overrides["<SYM>.<stratégia>"]
  3. INSTRUMENTUM:   conductor.autonomy.overrides["<SYM>"]
  4. ALAPÉRTÉK:      conductor.autonomy.default

A legszűkebb találat nyer. ⚠ A kill-switch fájl azért van FELÜL, mert az az
egyetlen út, ami akkor is járható, amikor a config nem írható vagy a felület nem
válaszol: egy `touch data/conductor/off` SSH-n is megy.

⚠ KIKAPCSOLÁSKOR A BEÁLLÍTOTT ÁLLAPOTOK MARADNAK. A visszaállítás maga is
cselekvés, kikapcsolt állapotban pedig nem cselekszünk. A visszagörgetés külön,
tudatos parancs (`undo`), nem a kikapcsolás mellékhatása.

⚠ TISZTA MODUL: a config dict + EGY fájl létezésének kérdezése. Se MT5, se
pandas, se felület.
"""

from __future__ import annotations

import logging

from conductor import paths as _paths

log = logging.getLogger(__name__)

# ── A FOKOK (stabil SZÁMOK — a felirat fordítás, a szám azonosító) ───────
OFF       = -1
OBSERVER  = 0
ADVISOR   = 1
ASSISTED  = 2
LIMITED   = 3
FULL      = 4

SZINTEK = (OFF, OBSERVER, ADVISOR, ASSISTED, LIMITED, FULL)

# ⚠ A FELIRAT KULCSA SZÓ, NEM SZÁM. A `-1` a nyelvi katalógus kulcs-konvenciójába
# sem fér bele (`<terület>.<elem>`, kisbetű) — de a valódi ok mélyebb: a projekt
# szabálya, hogy AZONOSÍTÓNAK stabil kód való, és a szám itt a config felé néz,
# nem a szöveg felé. A kettő így külön romolhat el: ha egyszer átszámozzuk a
# létrát, a feliratok nem csúsznak el némán.
KOD = {OFF: "off", OBSERVER: "observer", ADVISOR: "advisor",
       ASSISTED: "assisted", LIMITED: "limited", FULL: "full"}


def kod(szint: int) -> str:
    """A fok stabil kódja (a felirat ebből fordul)."""
    return KOD.get(szint, "off")

# ⚠ AZ ALAPÉRTÉK MA L1, NEM L3. A terv végállapota L3 — de az önállóságot
# akkor adjuk meg, amikor (a) van gépi végrehajtás, és (b) az árnyék-mód
# bizonyítékából látod, hogy a létra jól kalibrált. Egy L3-as alapérték gépi
# végrehajtás nélkül csak felirat volna; egy L3-as alapérték MÉRÉS nélkül pedig
# vakrepülés. A config `default: 3` már ma is beállítható.
DEFAULT = ADVISOR

# ── KÉPESSÉGEK: melyik fok mit enged (stabil kódok) ──────────────────────
MEASURE = "measure"    # telemetria, egészség-leletek, krónika
PROPOSE = "propose"    # életciklus-javaslatok (árnyék-mód)
INBOX   = "inbox"      # a javaslatok postaládába gyűjtése
REPORT  = "report"     # napi riport, értesítés
EXECUTE = "execute"    # az elfogadott döntés végrehajtása (opt-sor hajtása)
AUTO    = "auto"       # GÉPI végrehajtás emberi jóváhagyás NÉLKÜL (F3/b)

MIN_SZINT = {
    MEASURE: OBSERVER,
    PROPOSE: ADVISOR,
    INBOX:   ADVISOR,
    REPORT:  ADVISOR,
    EXECUTE: ADVISOR,      # amit TE fogadtál el, azt L1-en is végrehajtjuk
    AUTO:    ASSISTED,     # ⚠ ma még senki nem kéri — az F3/b kapcsolja be
}


def _szam(nyers) -> "int | None":
    """Egy fok olvasása. `None` = nincs / értelmezhetetlen bejegyzés.

    ⚠ TÍPUSHŰEN. A `-1` igaz-értéke `True`, a `0`-é `False` — egy `x or alap`
    tehát a MEGFIGYELŐ fokot (0) némán az alapértékre cserélné, vagyis a
    lefokozás kapcsolna fel valamit. Ez a projekt visszatérő hibája."""
    if nyers is None or isinstance(nyers, bool):
        # ⚠ A `True`/`False` NEM fok. Aki `true`-t ír, az valószínűleg
        # kapcsolónak hiszi — ne találgassunk helyette.
        if isinstance(nyers, bool):
            log.warning("conductor.autonomy: a fok nem be/ki kapcsoló (%r) — "
                        "figyelmen kívül hagyva", nyers)
        return None
    try:
        v = int(str(nyers).strip())
    except (TypeError, ValueError):
        log.warning("conductor.autonomy: értelmezhetetlen fok (%r) — "
                    "figyelmen kívül hagyva", nyers)
        return None
    if v not in SZINTEK:
        log.warning("conductor.autonomy: ismeretlen fok (%r) — a létra -1…4 "
                    "között van, figyelmen kívül hagyva", nyers)
        return None
    return v


def _blokk(cfg: dict) -> dict:
    b = (cfg or {}).get("conductor")
    a = b.get("autonomy") if isinstance(b, dict) else None
    return a if isinstance(a, dict) else {}


def _overrides(cfg: dict) -> dict:
    o = _blokk(cfg).get("overrides")
    return o if isinstance(o, dict) else {}


# ---------------------------------------------------------------------------
# KILL SWITCH — a fájl
# ---------------------------------------------------------------------------

def off_by_file() -> bool:
    """Létezik-e a kikapcsoló fájl? ⚠ SOHA NEM DOB: egy olvashatatlan lemez
    miatt nem mondjuk azt, hogy be van kapcsolva."""
    try:
        return _paths.off_switch().exists()
    except Exception:
        log.warning("conductor.autonomy: a kikapcsoló fájl nem ellenőrizhető — "
                    "BIZTONSÁGBÓL kikapcsoltnak vesszük", exc_info=True)
        return True


def set_off_file(be: bool) -> bool:
    """A kikapcsoló fájl létrehozása / törlése. Visszaad: sikerült-e.

    ⚠ A KIKAPCSOLÁSNAK MINDIG SIKERÜLNIE KELL. Ha a fájlt nem tudjuk
    létrehozni, az `False` — és a hívónak KI KELL MONDANIA, hogy a karmester
    NEM állt le. Egy „kikapcsolva" felirat egy futó karmester felett a
    lehető legrosszabb hazugság."""
    ut = _paths.off_switch()
    try:
        if be:
            if not _paths.ensure():
                return False
            ut.write_text("off\n", encoding="utf-8")
        else:
            ut.unlink(missing_ok=True)
        return True
    except Exception as ex:
        log.warning("conductor.autonomy: a kikapcsoló fájl nem írható (%s): %s",
                    ut, ex)
        return False


# ---------------------------------------------------------------------------
# A FOK FELOLDÁSA
# ---------------------------------------------------------------------------

def default_level(cfg: dict) -> int:
    """A config alapértéke (a kikapcsoló fájl NÉLKÜL)."""
    v = _szam(_blokk(cfg).get("default"))
    return DEFAULT if v is None else v


def level(cfg: dict, symbol: str = None, strategy: str = None) -> int:
    """A HATÁLYOS fok. `symbol`/`strategy` nélkül az alapérték."""
    if off_by_file():
        return OFF
    ov = _overrides(cfg)
    if symbol and strategy:
        v = _szam(ov.get(f"{symbol}.{strategy}"))
        if v is not None:
            return v
    if symbol:
        v = _szam(ov.get(symbol))
        if v is not None:
            return v
    return default_level(cfg)


def forras(cfg: dict, symbol: str = None, strategy: str = None) -> str:
    """HONNAN jön a fok: `off_file` · `cell` · `symbol` · `default`."""
    if off_by_file():
        return "off_file"
    ov = _overrides(cfg)
    if symbol and strategy and _szam(ov.get(f"{symbol}.{strategy}")) is not None:
        return "cell"
    if symbol and _szam(ov.get(symbol)) is not None:
        return "symbol"
    return "default"


def enged(cfg: dict, kepesseg: str, symbol: str = None,
          strategy: str = None) -> bool:
    """Szabad-e EZT? (`MEASURE` · `PROPOSE` · `INBOX` · `REPORT` · `EXECUTE` ·
    `AUTO`)

    ⚠ ISMERETLEN KÉPESSÉGRE NEM. A kétely a nem-cselekvés felé billen: egy
    elgépelt képesség-név ne nyisson kaput."""
    also = MIN_SZINT.get(kepesseg)
    if also is None:
        log.warning("conductor.autonomy: ismeretlen képesség (%r) — tiltva",
                    kepesseg)
        return False
    return level(cfg, symbol, strategy) >= also


def barmi_aktiv(cfg: dict) -> bool:
    """Van-e EGYÁLTALÁN dolga a karmesternek?

    ⚠ MIÉRT NEM ELÉG AZ ALAPÉRTÉK. `default: -1` mellett is lehet egyetlen
    cella L2-n („a GOLD-ot figyeld, a többit ne") — a szálnak olyankor futnia
    kell. Viszont ha MINDEN fok -1, egy fájlolvasás sem indokolt."""
    if off_by_file():
        return False
    szintek = [default_level(cfg)]
    szintek += [v for v in (_szam(x) for x in _overrides(cfg).values())
                if v is not None]
    return max(szintek) >= OBSERVER


def cells_with(cfg: dict, kepesseg: str, cellak) -> list:
    """A `cellak` (`(symbol, strategy)` párok) közül azok, amikre szabad."""
    return [(s, n) for s, n in (cellak or []) if enged(cfg, kepesseg, s, n)]


# ---------------------------------------------------------------------------
# ÍRÁS — a configot a HÍVÓ menti
# ---------------------------------------------------------------------------

def set_default(cfg: dict, szint: int) -> bool:
    """Az alapérték átírása. Visszaad: VÁLTOZOTT-e."""
    if szint not in SZINTEK:
        return False
    b = cfg.setdefault("conductor", {})
    if not isinstance(b, dict):
        return False
    a = b.get("autonomy")
    if not isinstance(a, dict):
        a = {}
        b["autonomy"] = a
    if _szam(a.get("default")) == szint:
        return False
    a["default"] = int(szint)
    return True


def set_override(cfg: dict, symbol: str, strategy: str,
                 szint: "int | None") -> bool:
    """Hatókör-felülírás. `szint=None` → törlés (essen vissza a tágabb szintre).

    A kulcs `<SYM>` vagy `<SYM>.<stratégia>` — a szűkebb nyer."""
    if szint is not None and szint not in SZINTEK:
        return False
    kulcs = f"{symbol}.{strategy}" if strategy else str(symbol or "")
    if not kulcs:
        return False
    b = cfg.setdefault("conductor", {})
    if not isinstance(b, dict):
        return False
    a = b.get("autonomy")
    if not isinstance(a, dict):
        a = {}
        b["autonomy"] = a
    o = a.get("overrides")
    if not isinstance(o, dict):
        o = {}
    regi = _szam(o.get(kulcs))
    if regi == szint and (kulcs in o) == (szint is not None):
        return False
    if szint is None:
        o.pop(kulcs, None)
    else:
        o[kulcs] = int(szint)
    # ⚠ Az üres táblát kitakarítjuk — egy `"overrides": {}` azt sugallná, hogy
    # van itt valami beállítás.
    if o:
        a["overrides"] = o
    else:
        a.pop("overrides", None)
    return True
