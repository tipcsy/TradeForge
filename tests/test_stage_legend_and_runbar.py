"""A karikak MAGYARAZATA, es az Inditas gomb LATHATOSAGA.

⚠ 1. A KARIKAK. A soron stadiumonkent egy kor mutatja, hol tart a belepo
szetupja — de SEHOL nem volt kiirva, MELYIK kor mit jelent. A jelolo a napi
hasznalat legfontosabb eleme; a jelrendszert a felhasznalonak kellett
kikovetkeztetnie a viselkedesbol.

A lista a STRATEGIA SAJAT deklaraciojabol epul (`columns()[0].stages`), nem
bedrotozott szovegbol. Ez nem stilus: a wpr_sma-nak es a bollingernek HAROM
stadiuma van, az ml_ai-nak KETTO — egy „harom karika" felirat maris hazudna, es
egy uj strategia neman rossz magyarazatot kapna.

⚠ 2. AZ INDITAS GOMB. Merve (Ger40, wpr_sma): a Parameter lap tartalma 3112 px,
az ablak a kepernyo 88%-an 1520 px — a Futtatas szakasz 1495 px-nel KEZDODIK,
tehat a benne ulo gomb pont az also el ala esett. Nagyobb ablak ezt NEM oldja
meg: nincs az a kepernyo, amin egy 3000 px-es lap elfer. A gomb ezert oda kerult,
ahol ennek az ablaknak MINDEN cselekvese van (Mentes · Megse) — es vele a futas
ALLAPOTA is, mert a visszajelzes ugyanugy nem lehet a lap aljara rejtve.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception as e:
    TK = False
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({e})")

from strategy import get_strategy_by_name

# ── 0. A STADIUMOK (Tk nelkul is merheto) ────────────────────────────────
_counts = {}
for _n in ("wpr_sma", "bollinger_squeeze_breakout", "ml_ai"):
    _counts[_n] = len(get_strategy_by_name(_n).columns()[0].stages)
check("a strategiak NEM egyforma szamu stadiumot deklaralnak",
      len(set(_counts.values())) > 1, str(_counts))
check("a wpr_sma-nak es a bollingernek 3",
      _counts["wpr_sma"] == 3 == _counts["bollinger_squeeze_breakout"])
check("az ml_ai-nak KETTO (ezert nem lehet bedrotozni a harmat)",
      _counts["ml_ai"] == 2, str(_counts["ml_ai"]))

if TK:
    from strategy.settings import load_config
    from dashboard import instrument_dialog as idlg, theme

    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    fonts = theme.fonts()
    cfg = load_config("config.json")

    def _texts(widget):
        out = []

        def walk(w):
            for c in w.winfo_children():
                try:
                    if "text" in c.keys():
                        t = str(c.cget("text"))
                        if t:
                            out.append(t)
                except tk.TclError:
                    pass
                walk(c)
        walk(widget)
        return out

    # ── 1. A LEGENDA minden strategian ───────────────────────────────────
    for name in ("wpr_sma", "bollinger_squeeze_breakout", "ml_ai"):
        st = get_strategy_by_name(name)
        d = idlg.InstrumentParamsDialog(root, "Ger40", cfg, st, fonts["header"],
                                        fonts["small"], lambda: None,
                                        root_cfg=copy.deepcopy(cfg))
        root.update_idletasks()
        blob = " ".join(_texts(d._shell.page("Áttekintés")))
        check(f"[{name}] van karika-magyarazat", "Mit jelentenek a karikák" in blob)
        # ⚠ A DARABSZAM a strategiaebol jon, nem bedrotozva.
        _n = len(st.columns()[0].stages)
        check(f"[{name}] a HELYES darabszamot mondja ({_n})",
              f"A soron {_n} kör" in blob, blob[blob.find("A soron"):][:40])
        # Minden stadium-cimke szerepel, SORSZAMOZVA (a soron balrol jobbra).
        _miss = [lab for _k, lab in st.columns()[0].stages if lab not in blob]
        check(f"[{name}] minden stadium neve kiirva", not _miss, str(_miss))
        check(f"[{name}] sorszamozva (a kor HELYE a soron)",
              all(f"{i}." in blob for i in range(1, _n + 1)))
        # ⚠ A SZINEK jelentese is kell: egy piros kor NEM hiba, hanem kesz
        # SELL-szetup. Enelkul a magyarazat felkesz.
        check(f"[{name}] a SZINEK jelentese is ott van",
              "zöld = BUY" in blob and "piros = SELL" in blob
              and "NEM hiba" in blob)

        # ⚠ A KOROK AZ ELO ALLAPOTOT MUTATJAK, nem disz-zoldet. Egy statikus
        # pelda-kor mellett a magyarazat elolvashato, de nem hasznalhato: a
        # kerdes nem az, hogy „mit jelentene, ha zold volna", hanem hogy MOST
        # melyik feltetel all.
        from dashboard import live_row as _lr
        _keys = [k for k, _ in st.columns()[0].stages]
        check(f"[{name}] provider NELKUL halvany (nem hazudunk zoldet)",
              all(d._legend_dots[k].cget("fg") == _lr._stage_color("muted")
                  for k in _keys),
              str({k: d._legend_dots[k].cget("fg") for k in _keys}))
        _fake = {"green": 0, "red": 1, "muted": 2}
        _want = {k: ["green", "red", "muted"][i % 3] for i, k in enumerate(_keys)}
        d.stage_cells_of = lambda sym, nm, _w=_want: {k: ("●", v) for k, v in _w.items()}
        d._refresh_legend_dots()
        root.update_idletasks()
        # ⚠ UGYANAZ A SZIN-FUGGVENY, mint a soron: ket kepletbol elobb-utobb ket
        # kulonbozo kep lenne, es itt epp az volna a baj, ha a magyarazat mast
        # mutatna, mint amit magyaraz.
        check(f"[{name}] elo allapotbol szinez (a sorral EGYEZO fuggvennyel)",
              all(d._legend_dots[k].cget("fg") == _lr._stage_color(v)
                  for k, v in _want.items()),
              str({k: d._legend_dots[k].cget("fg") for k in _keys}))
        d.popup.destroy()

    # ── 2. AZ INDITAS GOMB a ROGZITETT gombsorban ────────────────────────
    d = idlg.InstrumentParamsDialog(root, "Ger40", cfg,
                                    get_strategy_by_name("wpr_sma"),
                                    fonts["header"], fonts["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    d._shell.show("Paraméter")
    top = d.popup
    top.deiconify(); top.update(); top.update_idletasks()

    # ⚠ A LENYEG: a gomb az ABLAKON BELUL van. A lap tartalma tobb ezer px —
    # a szakaszban ulo gomb a kepernyo ala esett.
    _btn = d._plan_btn
    _win_bottom = top.winfo_rooty() + top.winfo_height()
    check("az Indítás gomb LATSZIK", bool(_btn.winfo_ismapped()))
    check("...es az ablakon BELUL van",
          top.winfo_rooty() < _btn.winfo_rooty() < _win_bottom,
          f"gomb y={_btn.winfo_rooty()} ablak={top.winfo_rooty()}..{_win_bottom}")
    # NEM a gorgetheto lapon ul (kulonben megint elcsuszhatna)
    check("...a ROGZITETT sávban, nem a görgethető lapon",
          str(d._body) not in str(_btn), f"{_btn}")

    # ⚠ ES A TERV IS OTT VAN MELLETTE: a reszletes magyarazat a lap kozepen
    # marad, de vakon nyomni ne kelljen.
    check("a gomb mellett ott a RÖVID terv",
          bool(d._plan_short.cget("text")), d._plan_short.cget("text")[:60])
    check("...ami megmondja, MI fog futni",
          any(w in d._plan_short.cget("text")
              for w in ("EGYETLEN futás", "VÉGIGPRÓBÁLÁS", "RÁCS",
                        "OPTIMALIZÁLÁS")), d._plan_short.cget("text"))

    # A futas ALLAPOTA is a rogzitett savban (a visszajelzes nem rejtozhet el).
    check("a futás-állapot is a rögzített sávban",
          str(d._body) not in str(d._run_status), str(d._run_status))

    # A terv-szakaszban NINCS masodik inditogomb (egy cselekves — egy hely).
    _sec = " | ".join(_texts(d._sections["futtatas"].body))
    check("a szakaszban NINCS második Indítás gomb", "Indítás" not in _sec,
          _sec[:120])
    check("...de a MAGYARAZAT ott maradt", "Mi fog történni" in _sec)

    top.withdraw()
    root.destroy()
else:
    check("nincs tkinter (a felulet-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
