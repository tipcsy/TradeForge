"""KARMESTER fül — a felület nem tud semmit, csak megjelenít és tovabbad.

⚠ MIERT FONTOS EZ. A ful gombjai VALODI valtozast csinalnak (kotes-mod!), es a
kesertes nagy, hogy a felulet „gyorsan" maga irja at az allapotot. Akkor viszont
a karmester NEGYEDIK irasi ut lenne, es a kozos retegben elesben megtanult
szabalyok (ujraervenyesites, megerosites, visszaut rogzitese) ra nem
vonatkoznanak. Ez a teszt azt orzi, hogy a ful vegig a `conductor/` + a kozos
parancs-reteg utjan megy.

⚠ A widget-szintu resz CSAK ott fut, ahol van tkinter (a CI Windowson). A
forras-szintu orok mindenhol — es epp a REGRESSZIO az, ha valaki „egyszerubb"
utat nyit a felulet fele.
"""
import csv
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.WARNING)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. FORRAS-SZINTU OROK ═══════════════════════════════════════════════
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_tab = (ROOT / "dashboard" / "conductor_tab.py").read_text(encoding="utf-8")

check("a Karmester ful be van epitve a notebookba",
      "self._notebook.add(cond_frame" in _gui and "ConductorTab(" in _gui)
# ⚠ A KOZOS parancs-reteg kornyezetet kapja — ugyanazt, amit a konzol hasznal.
check("...es a KOZOS parancs-kornyezetet kapja seamkent",
      "ctx_provider=self._cmd_ctx" in _gui, "")
check("...valamint egy visszahivast a tabla frissitesehez",
      "on_changed=self._apply_filter_sort" in _gui)

# ⚠ KET FRISSITES, KET KOLTSEG. A dashboard kore 30 mp-enkent fut; a hazirendek
# ujraszamolasa (cellankent fajlokkal) itt merheto lassulast okozna a FELULET
# szalan — a projekt ezt egyszer mar megmerte (7,64 -> 0,31 mp/kor).
_ciklus = _gui.split("if hasattr(self, \"_conductor_tab\")")[1].split("\n\n")[0]
check("a periodikus kor az OLCSO frissitest hivja",
      "_conductor_tab.refresh()" in _ciklus and "reload()" not in _ciklus, "")
check("...es vedve van", "A Karmester fül frissítése elbukott" in _gui)

# ⚠ A FELESLEGES UJRARAJZOLAS NEM „CSAK" PAZARLAS: a ful villogna, a gorgetes
# visszaugrana olvasas kozben, es egy epp megnyomott gomb kicsuszhatna az ujjad
# alol. Ezert a ket allapotfajl MODOSULASI IDEJE a rajzolas kapuja — ugyanaz a
# minta, mint a Jelzesek fulon a trades.csv-nel.
check("a ful csak VALTOZASKOR rajzol ujra",
      "self._mtime" in _tab and "_allapot_ideje" in _tab)
# ⚠ A masodperc-felbontasu mtime miatt a SAJAT hatasunk ugyanabba a
# masodpercbe eshet — a dontes utan ezert kenyszeritett ujrarajzolas kell.
check("...de a sajat dontes utan KENYSZERITETTEN",
      _tab.count("refresh(force=True)") >= 2, str(_tab.count("refresh(force=True)")))

_refresh = _tab.split("def refresh(")[1].split("\n    def ")[0]
_reload = _tab.split("def reload(")[1].split("\n    def ")[0]
check("a `refresh` nem futtat hazirendet",
      "policies" not in _refresh and "findings" not in _refresh, _refresh[:70])
check("...a `reload` viszont igen",
      "health as _h" in _reload and "lifecycle as _lc" in _reload)
check("...es a postaladat is beolvasztja", "_ib.sync(" in _reload)

# ⚠ A DONTES A KOZOS UTON MEGY — a ful nem ir sajat maga.
check("az elfogadas a `conductor.actions`-on megy",
      "_act.apply(" in _tab and "set_trade_mode" not in _tab)
check("a visszavonas is", "_act.undo(" in _tab)
check("az elvetes/halasztas a parancs-retegen",
      '_cc.dispatch(ctx, f"{mit} {azon}")' in _tab)
# ⚠ A ful NEM ir kozvetlenul allapotot.
check("⚠ a ful NEM ir kozvetlenul a run_state/trade_mode-ba",
      "_rs.set_state" not in _tab and "_tm.set_mode" not in _tab
      and "set_state(" not in _tab)

# ⚠ MEGERSITES-MINTA: ha a kozos reteg rakerdez, a ful megkerdezi.
_futtat = _tab.split("def _futtat(")[1].split("\n    def ")[0]
check("a ful kezeli a `confirm` kort",
      "res.confirm" in _futtat and "askyesno" in _futtat and "fn(ctx, True)" in _futtat)

# ⚠ NEM TESZUNK KI GOMBOT, AMI NEM MUKODIK: az optimalizalas ma csak az OPT
# gombbal indithato — egy halott „Elfogad" arra tanitana, hogy a ful gombjai
# megbizhatatlanok.
check("a nem vegrehajthato javaslatra NINCS Elfogad gomb",
      "if vegrehajthato:" in _tab and "cond.tab.advice_only" in _tab)
# ⚠ A VISSZAVONAS csak arra, ami tenyleg megtortent ES van hozza visszaut.
check("a Visszavon gomb csak vegrehajtott, visszavonhato tetelre jelenik meg",
      '_tetel.get("state") == _ib.ACCEPTED' in _tab and '_tetel.get("undo")' in _tab)
# ⚠ A BIZONYITEK a kartyan: indok nelkul nincs dontes.
check("a kartya kiirja a bizonyitekot",
      '"live_trades", "live_pf"' in _tab and 'e.get("evidence")' in _tab)
# ⚠ Az arnyek-figyelmeztetes allando.
check("a ful KIMONDJA, hogy a javaslatok maguktol nem hajtodnak vegre",
      "cond.tab.shadow" in _tab)
import json as _json
_HU = _json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
check("...es a szoveg ezt mondja",
      "nem hajtódnak végre" in _HU.get("cond.tab.shadow", ""),
      _HU.get("cond.tab.shadow", "")[:60])
check("a fokoknak van feliratuk mindket nyelven",
      all(_HU.get(f"cond.stage.{s}") for s in ("live", "paper", "untuned", "stopped")))


# ══ 2. WIDGET-SZINTU (csak ahol van tkinter) ════════════════════════════
try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as ex:
    print(f"KIHAGYVA: nincs hasznalhato tkinter ({type(ex).__name__}: {ex})")
    _root = None

if _root is not None:
    from conductor import paths as cp
    from conductor import telemetry as tl
    from conductor import inbox as ib
    from conductor import journal as jr
    from core import console_cmd as cc
    from core import trade_mode as tm

    TMP = Path(tempfile.mkdtemp(prefix="tf_tab_"))
    cp.DIR = TMP / "conductor"
    _CSV = TMP / "trades.csv"
    cp.trades_csv = lambda: _CSV
    tl.FLUSH_SEC = 0.0
    import core.params_store as ps
    ps.PARAMS_DIR = TMP / "params"
    (ps.PARAMS_DIR / "csilla").mkdir(parents=True, exist_ok=True)
    NOW = dt.datetime.now(dt.timezone.utc)
    with open(_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "event", "strategy", "symbol",
                                          "direction", "lot", "price", "sl", "tp",
                                          "ticket", "magic", "pnl_usd"])
        w.writeheader()
        for i in range(60):
            w.writerow({"time": (NOW - dt.timedelta(days=i % 40)).isoformat(),
                        "event": "close", "strategy": "csilla", "symbol": "GOLD",
                        "ticket": i, "pnl_usd": 10.0 if i % 5 == 0 else -4.0})
    (ps.PARAMS_DIR / "csilla" / "GOLD.json").write_text(json.dumps({
        "params": {"x": 1}, "optimized_at": NOW.isoformat(),
        "test_summary": {"trades": 200, "profit_factor": 1.6, "win_rate": 0.5,
                         "max_drawdown": 0.1}}), encoding="utf-8")

    cfg = {"optimizer": {"test_start_date": "2026-01-01"},
           "pairs": {"GOLD": {"enabled": True, "strategies": ["csilla"],
                              "run_state": {"csilla": "live"}}}}
    ctx = cc.Context(cfg=cfg, save_config=lambda: True, positions=list,
                     close_position=lambda t: False, account=dict, dashboard={},
                     instrument_state={}, strategies_of=lambda s: ["csilla"])
    ib.reset_for_test()
    jr.reset_for_test()

    from dashboard.conductor_tab import ConductorTab
    _valtozott = []
    frame = tk.Frame(_root)
    tab = ConductorTab(frame, ctx_provider=lambda: ctx,
                       on_changed=lambda: _valtozott.append(1))
    try:
        tab.reload()
        check("az atvizsgalas feltolti a postaladat", len(ib.items(ib.PENDING)) == 1,
              str(len(ib.items(ib.PENDING))))
        check("...es a matrixot", len(tab._cellak) == 1, str(len(tab._cellak)))
        check("a cella foka `live`", tab._cellak[0]["fok"] == "live")

        _id = ib.items(ib.PENDING)[0]["id"]
        check("a mod elotte `live`", tm.mode_of(cfg, "GOLD", "csilla") == "live")
        tab._accept(_id)
        check("az Elfogad VEGREHAJT a kozos retegen",
              tm.mode_of(cfg, "GOLD", "csilla") == "signal")
        check("...a tetel `accepted` lett", ib.get(_id)["state"] == ib.ACCEPTED)
        check("...es a hivo ertesult rola (a tabla frissuljon)", bool(_valtozott))

        # OLCSO frissites: ne szalljon el, es ne nyuljon semmihez.
        tab.refresh()
        check("az olcso frissites lefut", tm.mode_of(cfg, "GOLD", "csilla") == "signal")

        # Elvetes: a masodik javaslat (ha keletkezik) elvetheto.
        tab.reload()
        _nyitott = ib.items(ib.PENDING)
        if _nyitott:
            tab._dontes(_nyitott[0]["id"], "reject")
            check("az Elvet gomb a parancs-retegen megy",
                  ib.get(_nyitott[0]["id"])["state"] == ib.REJECTED)
        else:
            check("elfogadas utan nincs uj javaslat (helyes)", True)
    finally:
        _root.destroy()


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
