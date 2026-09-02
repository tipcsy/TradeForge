"""HATÓKÖR-ELEMZŐ: melyik név dobna `NameError`-t futáskor?

⚠ MIÉRT KELLETT. Az első változat (2026-09-02) csak azt nézte, hogy egy név
MEGKÖTŐDIK-E VALAHOL a modulban — a hatókört szándékosan nem követte, „nincs
téves riasztás" indokkal. Aznap ugyanez a vak folt engedett át egy VALÓDI
hibát: a `trading/live_trader.py` `process_pair` függvénye a `cfg` nevet
olvasta, ami ott sehol nem kötődik meg (a modulban `_run_cfg` a neve). A sor
`NameError`-t dobott, amit a körülötte lévő `except` `log.debug`-ra némított —
így a Telegram IGEN/NEM gombja a v3.12.0 óta EGYSZER SEM működött, miközben a
kód, a teszt és a felület is azt állította, hogy van ilyen funkció.

A modul-szintű `_run_cfg` létezése miatt a régi őr elégedett volt: a `cfg`-t
viszont sosem látta megkötve — de mivel egy MÁSIK függvény paramétere `cfg`,
a „bárhol megkötődik" szabály átengedte.

── MIT CSINÁL ─────────────────────────────────────────────────────────────
Felépíti a hatókör-láncot (modul → függvény → beágyazott függvény →
comprehension), és minden OLVASOTT névre megnézi, elérhető-e:

  * a saját hatókörében megkötött nevek,
  * a KÖRÜLÖLELŐ FÜGGVÉNY-hatókörök nevei (closure),
  * a modul-szintű nevek,
  * a beépítettek.

── MIT NEM CSINÁL, ÉS MIÉRT ───────────────────────────────────────────────
Nem sorrend-érzékeny: a függvényen belül lejjebb megkötött név a feljebbi
olvasásnál is „ismertnek" számít. Egy `if`-ág mögötti értékadás után a nevet
használni teljesen szabályos minta, és a sorrend követése ITT csak téves
riasztást hozna. A cél nem a teljes linter, hanem az, hogy a BIZTOSAN hiányzó
nevek — mint a fenti `cfg` — kiessenek.

Az osztály-törzsben megkötött nevek a modul-szintűek közé kerülnek. Ez
megengedőbb a valóságnál (a metódusok nem látják az osztály-törzs neveit), de
inkább hagyjunk ki egy ritka hibát, mint hogy az őr zajossá váljon és
kikapcsolják.
"""
from __future__ import annotations

import ast
import builtins

BUILTIN = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__builtins__", "__package__",
    "__spec__", "__loader__", "__debug__", "__class__",
}


def _cel_nevek(cel: ast.AST) -> set:
    """Egy értékadás/ciklus CÉLJÁBAN megkötött nevek (tuple-kicsomagolással)."""
    ki = set()
    for n in ast.walk(cel):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            ki.add(n.id)
    return ki


class _Hatokor:
    """Egy hatókör: a benne megkötött nevek + a szülője."""

    def __init__(self, szulo=None, fuggveny=False):
        self.szulo = szulo
        self.fuggveny = fuggveny      # closure-ként látszik-e a gyerekeknek
        self.nevek: set = set()

    def lathato(self, nev: str) -> bool:
        if nev in self.nevek:
            return True
        # ⚠ CSAK a FÜGGVÉNY-hatókörök látszanak kifelé. Az osztály-törzs nem
        # closure: egy metódus nem éri el az osztály-törzs lokálisait.
        sz = self.szulo
        while sz is not None:
            if sz.szulo is None or sz.fuggveny:      # modul vagy függvény
                if nev in sz.nevek:
                    return True
            sz = sz.szulo
        return False


class _Elemzo(ast.NodeVisitor):
    """Két menet: előbb a hatókör nevei, aztán az olvasások ellenőrzése."""

    def __init__(self):
        self.hibak: list = []

    # ── 1. menet: mit köt meg EZ a hatókör (a gyerek-hatókörökbe nem lépve) ──
    @staticmethod
    def _kotesek(csomopontok, sajat_fej=None) -> set:
        ki = set()
        if sajat_fej is not None:
            ki |= sajat_fej

        def kezel(n) -> bool:
            """Megkötések ebből a csomópontból. `False` → ne menjünk beljebb.

            ⚠ AZ ELSŐ VÁLTOZATOM CSAK A GYEREKEKET nézte, magát a csomópontot
            nem — így a MODUL-SZINTŰ `from pathlib import Path` kimaradt, és az
            őr a fél kódbázisra riasztott. Egy őr, ami mindenre kiabál,
            ugyanolyan használhatatlan, mint amelyik semmire."""
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                ki.add(n.name)           # a NEVE ide kötődik, a törzse nem
                return False
            if isinstance(n, ast.Lambda):
                return False
            if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp,
                              ast.GeneratorExp)):
                # ⚠ A comprehension SAJÁT hatókör, de a `:=` a KÖRÜLÖLELŐBE köt.
                for w in ast.walk(n):
                    if isinstance(w, ast.NamedExpr):
                        ki.update(_cel_nevek(w.target))
                return False
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    ki.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                ki.update(n.names)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                ki.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx,
                                                        (ast.Store, ast.Del)):
                ki.add(n.id)
            return True

        def bejar(n):
            if not kezel(n):
                return
            for gy in ast.iter_child_nodes(n):
                bejar(gy)

        for cs in csomopontok:
            bejar(cs)
        return ki

    @staticmethod
    def _arg_nevek(args: ast.arguments) -> set:
        ki = {a.arg for a in list(args.posonlyargs) + list(args.args)
              + list(args.kwonlyargs)}
        if args.vararg:
            ki.add(args.vararg.arg)
        if args.kwarg:
            ki.add(args.kwarg.arg)
        return ki

    # ── 2. menet: az olvasások ────────────────────────────────────────────
    def fut(self, fa: ast.Module, ut: str) -> list:
        self.ut = ut
        modul = _Hatokor()
        modul.nevek = self._kotesek(fa.body)
        self._torzs(fa.body, modul)
        return self.hibak

    def _torzs(self, csomopontok, hk: _Hatokor) -> None:
        for cs in csomopontok:
            self._csomopont(cs, hk)

    def _csomopont(self, n: ast.AST, hk: _Hatokor) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # A dekorátorok és az alapértelmezések a KÜLSŐ hatókörben futnak.
            for d in n.decorator_list:
                self._csomopont(d, hk)
            for d in list(n.args.defaults) + [x for x in n.args.kw_defaults if x]:
                self._csomopont(d, hk)
            uj = _Hatokor(hk, fuggveny=True)
            uj.nevek = self._kotesek(n.body, self._arg_nevek(n.args))
            self._torzs(n.body, uj)
            return
        if isinstance(n, ast.Lambda):
            for d in list(n.args.defaults) + [x for x in n.args.kw_defaults if x]:
                self._csomopont(d, hk)
            uj = _Hatokor(hk, fuggveny=True)
            uj.nevek = self._kotesek([n.body], self._arg_nevek(n.args))
            self._csomopont(n.body, uj)
            return
        if isinstance(n, ast.ClassDef):
            for d in n.decorator_list:
                self._csomopont(d, hk)
            for b in list(n.bases) + [k.value for k in n.keywords]:
                self._csomopont(b, hk)
            uj = _Hatokor(hk, fuggveny=False)
            uj.nevek = self._kotesek(n.body)
            # ⚠ MEGENGEDŐEN: az osztály-törzs nevei a MODUL-szintre is
            # felkerülnek. Lásd a modul fejlécét.
            gyoker = hk
            while gyoker.szulo is not None:
                gyoker = gyoker.szulo
            gyoker.nevek |= uj.nevek
            self._torzs(n.body, uj)
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp,
                          ast.GeneratorExp)):
            uj = _Hatokor(hk, fuggveny=True)
            for g in n.generators:
                uj.nevek |= _cel_nevek(g.target)
            # Az ELSŐ iterálandó a KÜLSŐ hatókörben értékelődik ki.
            if n.generators:
                self._csomopont(n.generators[0].iter, hk)
                for g in n.generators[1:]:
                    self._csomopont(g.iter, uj)
                for g in n.generators:
                    for f in g.ifs:
                        self._csomopont(f, uj)
            reszek = ([n.key, n.value] if isinstance(n, ast.DictComp)
                      else [n.elt])
            for r in reszek:
                self._csomopont(r, uj)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in BUILTIN and not hk.lathato(n.id):
                self.hibak.append((n.lineno, n.id))
            return
        for gy in ast.iter_child_nodes(n):
            self._csomopont(gy, hk)


def hianyzo_nevek(forras: str, ut: str = "") -> list:
    """`(sor, név)` párok, amelyekre a modul `NameError`-t dobna.

    A találatok sor szerint rendezve, névenként az ELSŐ előfordulással."""
    fa = ast.parse(forras)
    nyers = _Elemzo().fut(fa, ut)
    latott, ki = set(), []
    for sor, nev in sorted(nyers):
        if nev in latott:
            continue
        latott.add(nev)
        ki.append((sor, nev))
    return ki
