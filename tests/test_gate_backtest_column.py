"""Kapu-tabla: „allapot (elesben)" es „backtest" KET KULON kerdes.

A felhasznalo keresе: „Nev | Allapot | Backtest — es a leiras-oszlop torolheto,
mert semmivel sem mond tobbet a kivalasztott szovegnel."

⚠ MIERT KELL A KET OSZLOP KULON. Epp ezzel merheto meg, mennyit visz el egy
kapu: kipipalod, futtatsz, kiveszed, futtatsz — a kulonbseg a kapue. Egyetlen
kozos `exec_gates` kapcsoloval (mind vagy semmi) ez a kerdes fel sem tehető
volt; a `tools/gate_ab.py` is csak azert szuletett, mert a feluleten nem ment.

⚠ A PIPA MINDKET IRANYBAN szabad. Egy korabbi valtozat tiltotta az elesben
kikapcsolt kapu bepipalasat („a backtest ne modellezzen nem letezo vilagot") —
de eppen ez a feltaro meres lenyege, es a tiltas elvette a legfontosabb
kerdest: MEGERI-e bekapcsolni. Amit a felulet cserebe VALLAL: az elteres soha
nem lehet nema — a sor vegen es a becsukott fejlecen is ki van irva.

Az EGYETLEN kivetel a CSAK KIJELZES kapu, es az nem hazirend, hanem TENY: a
`decide` atugorja, tehat a bepipalas semmit nem tenne.
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

# ⚠ v3.27.0: a Volatilitas is DONTO kapu lett (eddig CSAK KIJELZES volt), tehat
# alapbol modellezi a backtest — ahogy eddig is tette, csak akkor a strategia
# `bt_entry`-jen keresztul, lathatatlanul.
check("a Volatilitast alapbol modellezi a backtest",
      g.backtest_enabled(c, SYM, STRAT, g.VOLATILITY))


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


# ── 4. „MI LENNE, HA BEKAPCSOLNAM?" — a merés TOBBET is modellezhet ──────
# ⚠ Ez a felhasznalo kerése: „az egyes kapukat kell tudjuk allitani akkor is,
# ha azok ki vannak kapcsolva." Kulonben nem lehetne megmerni, MEGERI-e.
c2 = {"pairs": {SYM: {"gates": {g.SPREAD: {STRAT: g.EFFECT_NONE}},
                      "gates_backtest": {STRAT: {g.SPREAD: True}}}}}
check("elesben KI, de a merésre BE -> a backtest modellezi",
      g.effects_for(c2, SYM, STRAT, for_backtest=True)[g.SPREAD] != g.EFFECT_NONE)
# Milyen hatassal? A kapu sajat alapertelmezesevel; ha az is „nincs", akkor
# BLOKKOL — egy kapu bekapcsolasan azt szokas erteni, hogy akadalyoz.
check("...a kapu sajat alapertelmezett hatasaval",
      g.effects_for(c2, SYM, STRAT, for_backtest=True)[g.SPREAD] == g.EFFECT_BLOCK)
check("...az ELES hatas kozben valtozatlanul KI",
      g.effects_for(c2, SYM, STRAT)[g.SPREAD] == g.EFFECT_NONE)

# Egy kapu, aminek nincs sajat alapertelmezese sem (`none`), szinten blokkol.
c3 = {"pairs": {SYM: {"gates_backtest": {STRAT: {g.MOMENTUM: True}}}}}
check("a `none` alapertelmezesu kapu is BLOKKOL, ha a merésre bekapcsolod",
      g.effects_for(c3, SYM, STRAT, for_backtest=True)[g.MOMENTUM] == g.EFFECT_BLOCK)

# ⚠ AMIT CSEREBE VALLALUNK: az elteres NEM lehet nema.
check("az elteres LEKERDEZHETO", g.backtest_differs(c2, SYM, STRAT) == [g.SPREAD],
      str(g.backtest_differs(c2, SYM, STRAT)))
check("...mindket iranyban", set(g.backtest_differs(
      {"pairs": {SYM: {"gates": {g.SPREAD: {STRAT: g.EFFECT_BLOCK}},
                       "gates_backtest": {STRAT: {g.SPREAD: False,
                                                  g.MOMENTUM: True}}}}},
      SYM, STRAT)) == {g.SPREAD, g.MOMENTUM})
check("egyezéskor URES a lista", g.backtest_differs(_cfg(), SYM, STRAT) == [])

# A Volatilitas KIVEHETO a meresbol (a pipaval) — ez az A/B lenyege: mennyit
# visz el a volatilitas-szuro? Elesben viszont valtozatlanul blokkol.
c4 = {"pairs": {SYM: {"gates_backtest": {STRAT: {g.VOLATILITY: False}}}}}
check("a Volatilitas kivehető a merésbol",
      g.effects_for(c4, SYM, STRAT, for_backtest=True)[g.VOLATILITY] == g.EFFECT_NONE)
check("...de az ELES hatasa valtozatlan",
      g.effects_for(c4, SYM, STRAT)[g.VOLATILITY] == g.EFFECT_BLOCK)


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

    # ⚠ A pipa MINDEN kapun allithato — akkor is, ha elesben ki van kapcsolva.
    # v3.27.0 elott a Volatilitas kivetel volt (CSAK KIJELZES, a `decide`
    # atugorta); mostantol valodi kapu, tehat neki is elo pipaja van.
    _bad = [f"{k}: {str(d._gate_bt_cb[k].cget('state'))}"
            for k in g.KEYS if str(d._gate_bt_cb[k].cget("state")) != "normal"]
    check("a pipa MINDEN kapun allithato", not _bad, "; ".join(_bad))

    # A megszunt harmadik oszlop: csak akkor szol, ha van MIT mondania.
    _texts = {k: d._gate_src_lbl[k].cget("text") for k in g.KEYS}
    check("a sor-vegi megjegyzes NEM ismetli meg a legordulot",
          all("Akadályozza" not in t for t in _texts.values()), str(_texts))
    # ⚠ Egy dolgot viszont MEGTART: a globalis kikapcsolast. A legordulo olyankor
    # „ki"-t mutat — mintha a felhasznalo allitotta volna ugy.
    from core import gate_layout as gl
    _off = [k for k in g.KEYS if not gl.is_enabled(live, k)
            and not g.backtest_enabled(live, sym, "wpr_sma", k)]
    check("a globalisan kikapcsoltnal KIIRJA az okot",
          all("Beállításokban" in _texts[k] for k in _off) if _off else True,
          str({k: _texts[k] for k in _off}))

    # ⚠ AZ ELTERES NEM LEHET NEMA: ha egy elesben kikapcsolt kaput bepipalsz, a
    # sor vegen ki kell irnia — kulonben a meres hetekig mast modellezne.
    _k = next((k for k in g.KEYS
               if g.effect_for(live, sym, "wpr_sma", k) == g.EFFECT_NONE), None)
    if _k:
        d._gate_bt_vars[_k].set(True)
        d._on_gate_bt_change(_k)
        check("elteresnel a sor vege FIGYELMEZTET",
              "⚠" in d._gate_src_lbl[_k].cget("text"),
              d._gate_src_lbl[_k].cget("text"))
        check("...es a becsukott fejlec is",
              "eltér" in d._sections["kapuk"]._sum.cget("text"),
              d._sections["kapuk"]._sum.cget("text"))
        d._gate_bt_vars[_k].set(False); d._on_gate_bt_change(_k)
    else:
        check("nincs kikapcsolt kapu a teszt-paron (kihagyva)", True)

    root.destroy()
else:
    check("nincs tkinter (a felulet-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
