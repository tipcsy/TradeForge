"""Kapu-tabla: „allapot (elesben)" es „backtest" KET KULON kerdes.

A felhasznalo keresе: „Nev | Allapot | Backtest — es a leiras-oszlop torolheto,
mert semmivel sem mond tobbet a kivalasztott szovegnel."

⚠ MIERT KELL A KET OSZLOP KULON. Epp ezzel merheto meg, mennyit visz el egy
kapu: kipipalod, futtatsz, kiveszed, futtatsz — a kulonbseg a kapue. Egyetlen
kozos `exec_gates` kapcsoloval (mind vagy semmi) ez a kerdes fel sem tehető
volt; a `tools/gate_ab.py` is csak azert szuletett, mert a feluleten nem ment.

⚠ ES A LEGFONTOSABB INVARIANS: a backtest az ELES hatasbol indul, es legfeljebb
KIVESZ belole — SOHA nem tesz hozza. Egy kapu, ami elesben nem szol bele, a
merésben sem szolhat: kulonben a backtest olyan vilagot modellezne, ami nem
letezik, es a kapott parameterek elesben mast csinalnanak.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from core import gates as g

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


SYM, STRAT = "TEST", "wpr_sma"


def _cfg():
    return {"pairs": {SYM: {"gates": {g.SPREAD: {STRAT: g.EFFECT_BLOCK},
                                      g.TF_ALIGN: {STRAT: g.EFFECT_BLOCK}}}}}


# ── 1. ALAPERTELMEZES: modellezze ─────────────────────────────────────────
c = _cfg()
check("alapbol MINDEN dontő kaput modellez a backtest",
      g.backtest_enabled(c, SYM, STRAT, g.SPREAD)
      and g.backtest_enabled(c, SYM, STRAT, g.TF_ALIGN))
check("az eles es a backtest hatas kezdetben AZONOS",
      g.effects_for(c, SYM, STRAT) == g.effects_for(c, SYM, STRAT, for_backtest=True))

# ⚠ A CSAK KIJELZES kapu SOHA nem modellezheto: a `decide` atugorja, a valodi
# szures a strategia bt_entry-jeben van. Egy bejelolheto pipa azt igerne, hogy hat.
check("a CSAK KIJELZES kapu sosem modellezheto",
      not g.backtest_enabled(c, SYM, STRAT, g.VOLATILITY))


# ── 2. A PIPA KIVESZI a merésbol — de az ELES hatast NEM erinti ───────────
g.set_backtest(c, SYM, STRAT, g.SPREAD, False)
check("kipipalva: a backtest MAR NEM modellezi",
      g.effects_for(c, SYM, STRAT, for_backtest=True)[g.SPREAD] == g.EFFECT_NONE)
# ⚠ EZ A LENYEG: az eles viselkedes valtozatlan. Ha a pipa az elest is atallitana,
# egy meres kozben csendben MAS kereskedes menne.
check("...de az ELES hatas valtozatlan",
      g.effects_for(c, SYM, STRAT)[g.SPREAD] == g.EFFECT_BLOCK)
check("a tobbi kapu erintetlen",
      g.effects_for(c, SYM, STRAT, for_backtest=True)[g.TF_ALIGN] == g.EFFECT_BLOCK)


# ── 3. CONFIG-HAZIREND: csak az ELTERES kerul a fajlba ────────────────────
check("a kipipalas bekerul a configba",
      c["pairs"][SYM].get("gates_backtest") == {STRAT: {g.SPREAD: False}},
      str(c["pairs"][SYM].get("gates_backtest")))
g.set_backtest(c, SYM, STRAT, g.SPREAD, True)
# ⚠ Az alapertelmezessel egyezo ertek KIKERUL: kulonben egy kesobbi
# alapertek-valtozas neman hatastalan maradna az igy „beallitott" kulcsokra.
check("visszapipalva a bejegyzes KIKERUL (nem marad ott `true`)",
      "gates_backtest" not in c["pairs"][SYM], str(c["pairs"][SYM]))
check("...es a hatas ujra az eles", g.effects_for(c, SYM, STRAT, for_backtest=True)
      [g.SPREAD] == g.EFFECT_BLOCK)


# ── 4. AZ INVARIANS: a backtest nem TEHET HOZZA ──────────────────────────
# Egy elesben KI-re allitott kapu a merésben sem elhet — akkor sem, ha valaki a
# tarba `true`-t irna.
c2 = {"pairs": {SYM: {"gates": {g.SPREAD: {STRAT: g.EFFECT_NONE}},
                      "gates_backtest": {STRAT: {g.SPREAD: True}}}}}
check("elesben KI -> a backtestben is KI (a pipa nem elesitheti)",
      g.effects_for(c2, SYM, STRAT, for_backtest=True)[g.SPREAD] == g.EFFECT_NONE)

_bt = g.effects_for(c, SYM, STRAT, for_backtest=True)
_live = g.effects_for(c, SYM, STRAT)
check("a backtest hatasa MINDIG az eles reszhalmaza",
      all(_bt[k] == _live[k] or _bt[k] == g.EFFECT_NONE for k in g.KEYS))


# ── 5. A BACKTEST TENYLEG ezt hasznalja ──────────────────────────────────
import inspect as _i
_bt_src = _i.getsource(__import__("trading.backtest", fromlist=["x"]))
check("a run_pair `for_backtest=True`-vel kerdezi a kapukat",
      "for_backtest=True" in _bt_src, "")
check("...es a portfolio-ag is",
      _bt_src.count("for_backtest=True") >= 3,
      f"{_bt_src.count('for_backtest=True')} helyen")


# ── 6. A FELULET: harom oszlop, es a letiltas ────────────────────────────
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception:
    TK = False

if TK:
    from strategy.settings import load_config
    from strategy import get_strategy_by_name
    from dashboard import instrument_dialog as idlg, theme
    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    f = theme.fonts()
    cfg = load_config("config.json")
    live = copy.deepcopy(cfg)
    sym = next(s for s in cfg["pairs"] if not s.startswith("_"))
    d = idlg.InstrumentParamsDialog(root, sym, cfg,
                                    get_strategy_by_name("wpr_sma"),
                                    f["header"], f["small"], lambda: None,
                                    root_cfg=live)
    root.update_idletasks()
    check("minden kapunak van backtest-pipaja",
          set(d._gate_bt_vars) == set(g.KEYS), str(sorted(d._gate_bt_vars)))

    # ⚠ A pipa csak ott jelenthet valamit, ahol a kapu ELESBEN dont. Ahol a
    # hatas „ki", ott LETILTVA — egy bepipalva marado jelolo azt igerne, hogy a
    # meres szamol vele.
    _bad = []
    for k in g.KEYS:
        eff = g.effect_for(live, sym, "wpr_sma", k)
        usable = eff != g.EFFECT_NONE and not g.is_display_only(k)
        state = str(d._gate_bt_cb[k].cget("state"))
        if usable and state == "disabled":
            _bad.append(f"{k}: hatas={eff} de letiltva")
        if not usable and state != "disabled":
            _bad.append(f"{k}: hatas={eff} de engedve")
    check("a pipa CSAK ott engedve, ahol a kapu elesben dont", not _bad,
          "; ".join(_bad))

    # A megszunt harmadik oszlop: csak akkor szol, ha van MIT mondania.
    _texts = {k: d._gate_src_lbl[k].cget("text") for k in g.KEYS}
    check("a sor-vegi megjegyzes NEM ismetli meg a legordulot",
          all("Akadályozza" not in t for t in _texts.values()), str(_texts))
    # ⚠ Egy dolgot viszont MEGTART: a globalis kikapcsolast. A legordulo olyankor
    # „ki"-t mutat — mintha a felhasznalo allitotta volna ugy.
    from core import gate_layout as gl
    _off = [k for k in g.KEYS if not gl.is_enabled(live, k)]
    check("a globalisan kikapcsoltnal KIIRJA az okot",
          all("Beállításokban" in _texts[k] for k in _off) if _off else True,
          str({k: _texts[k] for k in _off}))

    root.destroy()
else:
    check("nincs tkinter (a felulet-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
