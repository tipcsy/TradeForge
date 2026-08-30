"""Kotes-lista: a futas kotesei TETELESEN.

Eddig a futas EGYETLEN sorban vegzodott („42 kotes, +1 234$, PF 1,31"), es ha a
szam nem tetszett, nem volt hova tovabbmenni.

⚠ MIT ALLIT EZ A TESZT, es miert epp azt:

1. A ZARAS OKA nem a `status` nyers atvetele. Egy `sl` zaras `risk_free=True`
   mellett NYERESEG is lehet — a stop mar a belepon (vagy azon tul) allt. E
   nelkul a lista onellentmondonak latszana: „Stop" +240$-ral.

2. Az `R` URES marad, ahol a kockazat nem ismert. A 0,0 azt hazudna, hogy
   megmertuk es nulla lett.

3. A HIANYZO ertek MINDIG a lista vegere rendezodik, akarmelyik iranyba
   rendezel — kulonben az R szerinti rendezes a nem mert koteseket egyszer
   legfelulre, egyszer legalulra dobna.

4. A kotes-listat a `on_run_done` tolti, NEM az `on_result`. Az utobbi a mentett
   minositest irja vissza, es CSAK azonos kockazatcsokkentesnel — kulonben egy
   feltaro futas szennyezne a nyilvantartott szamot. A lista viszont a MOST
   lefuttatott futas nezete: feltaro beallitasnal a legerdekesebb.
"""
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


import pandas as pd

from dashboard import trade_list as tl
from trading.backtest import BacktestResult, Trade


def _t(direction, status, pnl, risk=100.0, risk_free=False, day=1, legs=None):
    return Trade(symbol="TEST", direction=direction,
                 open_time=pd.Timestamp(f"2026-08-{day:02d} 10:00"),
                 open_price=100.0, sl=99.0, tp=103.0, lot=0.1, point_size=0.01,
                 pv1_point=1.0, sl_points=100.0,
                 close_time=pd.Timestamp(f"2026-08-{day:02d} 12:30"),
                 close_price=101.5, pnl_usd=pnl, status=status,
                 risk_free=risk_free, risk_usd=risk, legs=list(legs or []))


TRADES = [
    _t("BUY",  "tp",   +250.0, day=1),
    _t("SELL", "sl",   -100.0, day=2),
    # ⚠ A LENYEG: `sl` + `risk_free` -> NYERESEG. Enelkul „Stop" allna +80$-ral.
    _t("BUY",  "sl",    +80.0, risk_free=True, day=3),
    _t("SELL", "exit",  +40.0, day=4),
    _t("BUY",  "cut",   -35.0, day=5),
    # Ismeretlen kockazat -> az R nem szamolhato.
    _t("SELL", "tp",   +120.0, risk=0.0, day=6),
]
RES = BacktestResult(symbol="TEST", trades=list(TRADES))
rows = tl.rows_from(RES)

check("minden lezart kotes egy sor", len(rows) == 6, str(len(rows)))

# ── 1. A ZARAS OKA ────────────────────────────────────────────────────────
_oks = [r["reason"] for r in rows]
check("a `tp` -> Celar", tl.REASON[_oks[0]] == "Célár", str(_oks[0]))
check("a sima `sl` -> Stop", tl.REASON[_oks[1]] == "Stop")
# ⚠ EZ A KULONBSEGTETEL A LENYEG.
check("az `sl` + risk_free -> KULON ok", _oks[2] == "sl_free"
      and tl.REASON[_oks[2]] == "Stop (BE/trail)", str(_oks[2]))
check("...es tenyleg nyeresegkent latszik", rows[2]["_win"] is True)
check("az `exit` -> Kiszallasi jel", tl.REASON[_oks[3]] == "Kiszállási jel")
check("a `cut` -> Cost-cut", "Cost-cut" in tl.REASON[_oks[4]])

# ── 2. AZ R OSZLOP ────────────────────────────────────────────────────────
check("R = P&L / kockazat", abs(rows[0]["r"] - 2.5) < 1e-9, str(rows[0]["r"]))
# ⚠ NEM 0,0: az azt hazudna, hogy megmertuk.
check("ismeretlen kockazatnal az R URES", rows[5]["r"] is None, str(rows[5]["r"]))
check("...es a cellaja gondolatjel", tl.fmt("r", rows[5]["r"]) == "—")

# ── 3. FORMAZAS (magyar) ──────────────────────────────────────────────────
check("a P&L-ben tizedesVESSZO es elojel",
      tl.fmt("pnl", 1234.5) == "+1" + tl.NBSP + "234,50", tl.fmt("pnl", 1234.5))
check("az R elojeles, ket tizedes", tl.fmt("r", -1.5) == "-1,50", tl.fmt("r", -1.5))
check("az ido rovid alakban", tl.fmt("open", rows[0]["open"]) == "08-01 10:00",
      tl.fmt("open", rows[0]["open"]))

# ── 4. RENDEZES: a hianyzo MINDIG a vegen ────────────────────────────────
for desc in (False, True):
    _s = tl.sort_rows(rows, "r", desc)
    check(f"R szerint rendezve (desc={desc}) a HIANYZO a vegen",
          _s[-1]["r"] is None, str([r["r"] for r in _s]))
_asc = [r["r"] for r in tl.sort_rows(rows, "r", False) if r["r"] is not None]
check("...a tobbi viszont tenyleg rendezett",
      _asc == sorted(_asc), str(_asc))
_t_desc = [r["open"] for r in tl.sort_rows(rows, "open", True)]
check("ido szerint is rendez", _t_desc == sorted(_t_desc, reverse=True))

# ── 5. SZURES ─────────────────────────────────────────────────────────────
check("irany szerint", len(tl.apply_filters(rows, direction="BUY")) == 3)
check("nyero/veszto szerint",
      len(tl.apply_filters(rows, outcome="win")) == 4
      and len(tl.apply_filters(rows, outcome="loss")) == 2)
check("zaras oka szerint", len(tl.apply_filters(rows, reason="tp")) == 2)
# ⚠ A `sl` szuro NE hozza a `sl_free`-t: az mas kereskedesi esemeny.
check("a Stop szuro NEM hozza a BE/trail zarast",
      [r["reason"] for r in tl.apply_filters(rows, reason="sl")] == ["sl"])
check("a szurok egyutt is hatnak",
      len(tl.apply_filters(rows, direction="BUY", outcome="win")) == 2)

# ── 6. OSSZEGZES a SZURT halmazrol ───────────────────────────────────────
_all = tl.summary_line(rows)
check("az osszegzes kotesszamot, nyero-aranyt es P&L-t mond",
      "6 kötés" in _all and "4 nyerő" in _all and "+355" in _all, _all)
_loss = tl.summary_line(tl.apply_filters(rows, outcome="loss"))
check("...a SZURT halmazrol, nem az osszesrol",
      "2 kötés" in _loss and "-135" in _loss, _loss)
check("ures halmazra sem esik szet", "nincs" in tl.summary_line([]))

# ── 7. CSV ────────────────────────────────────────────────────────────────
csv = tl.to_csv(rows)
_lines = csv.strip().split("\n")
check("a CSV fejleces es teljes",
      _lines[0] == ";".join(tl.col_label(c) for c in tl.COLS)
      and len(_lines) == 7, f"{len(_lines)} sor")
# A magyar Excel `;` + tizedesVESSZO parost nyit meg kattintasra.
check("tizedesVESSZO a szamokban", ",50" in _lines[1] or ",0000" in _lines[1],
      _lines[1])
check("a zaras oka EMBERI nevvel megy ki", "Stop (BE/trail)" in csv)
check("a hianyzo R URES cella (nem 0)", _lines[6].endswith(";;Célár")
      or ";;" in _lines[6], _lines[6])

# ── 8. NYITVA MARADT koteseket NEM listazunk ─────────────────────────────
# Nincs zaro aruk, tehat se P&L-jük, se R-jük — a „—"-okkal teli sor csak zaj.
_open = BacktestResult(symbol="T", trades=[_t("BUY", "open", 0.0)])
check("a nyitott kotes NEM kerul a listaba", tl.rows_from(_open) == [])
check("None eredmenyre ures lista", tl.rows_from(None) == [])


# ── 9. A FELULET ─────────────────────────────────────────────────────────
try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    TK = True
except Exception:
    TK = False

if TK:
    import copy
    from strategy.settings import load_config
    from strategy import get_strategy_by_name
    from dashboard import instrument_dialog as idlg, theme

    root = tk.Tk(); root.withdraw()
    theme._FONTS.clear()
    fonts = theme.fonts()

    ctl = tl.build(root, {"small": fonts["small"]})
    root.update_idletasks()
    check("uresen is felepul (nem ugral az elrendezes)", ctl.rows() == [])
    ctl.set_rows(rows)
    check("a sorok bekerulnek", len(ctl.rows()) == 6)

    cfg = load_config("config.json")
    sym = next(s for s in cfg["pairs"] if not s.startswith("_"))
    d = idlg.InstrumentParamsDialog(root, sym, cfg,
                                    get_strategy_by_name("wpr_sma"),
                                    fonts["header"], fonts["small"], lambda: None,
                                    root_cfg=copy.deepcopy(cfg))
    root.update_idletasks()
    check("a Futtatas es az Eredmeny SZAKASZ (nem lap)",
          "futtatas" in d._sections and "eredmeny" in d._sections
          and "Futtatás" not in d._shell.names(), str(d._shell.names()))
    check("az Eredmeny szakasz fejlece elore szol, hogy meg nem futott",
          "nem futott" in d._sections["eredmeny"]._sum.cget("text"),
          d._sections["eredmeny"]._sum.cget("text"))

    # ⚠ A LISTAT az `on_run_done` tolti — a nyers eredmenybol, MINDIG.
    d._on_run_done(RES)
    root.update_idletasks()
    check("a futas utan megjelennek a kotesek", len(d._trades.rows()) == 6)
    check("...es a becsukott fejlec is osszegez",
          "6 kötés" in d._sections["eredmeny"]._sum.cget("text"),
          d._sections["eredmeny"]._sum.cget("text"))

    # A ket visszahivas KULONBOZO: az `on_run_done` a nyers eredmenyt kapja.
    import inspect
    _src = inspect.getsource(idlg.InstrumentParamsDialog._on_run_done)
    check("az on_run_done a NYERS eredmenybol dolgozik", "rows_from(result)" in _src)
    from dashboard import backtest_dialog as bd
    _dsrc = inspect.getsource(bd.BacktestDialog._done)
    check("...es a backtest MINDIG meghivja (nem az rr-egyezeshez kotve)",
          _dsrc.index("_on_run_done") < _dsrc.index("same_rr"), "sorrend")

    root.destroy()
else:
    check("nincs tkinter (a felulet-tesztek kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
