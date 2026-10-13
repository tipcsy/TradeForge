"""A Kockázatkezelés ablak (2026-10-13, 2. lépés) + az optimalizáló a stratégia
felülírásába ír.

⚠ Ideiglenes risk_mode.json — a valódihoz nem nyúl; a config dict kézi.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import rr_state as R, risk_reduction as RR             # noqa: E402
from dashboard import risk_window as RW                          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


_vp, _vs, _vr = R.PATH, dict(R._state), R._sync_risky
R.PATH = Path(tempfile.mkdtemp()) / "risk_mode.json"
R._sync_risky = lambda s, p: None
R._state.clear()
try:
    R.set_preset("Ger40", RR.PRESET_OFF)
    R._set("Ger40", breakeven_r=1.0)
    check("összefoglaló: a pár alapja", RW.summary("Ger40") .startswith(R.NAME[RR.PRESET_OFF])
          and "BE 1R" in RW.summary("Ger40"), RW.summary("Ger40"))

    # ── stratégia felülírása a szerkesztő mentés-tervén át ───────────────────
    elotte = {k: RW.INHERIT for k in RW.FIELD_KEYS}
    utana = dict(elotte, preset=RR.PRESET_SHIELD, runner=RR.RUNNER_EXIT,
                 exit_indicator="wpr")
    lepes = RW.plan_changes("Ger40", "csilla", elotte, utana)
    check("a terv csak a megváltozott mezőket írja",
          {k for _op, k, _v in lepes} == {"preset", "runner", "exit_indicator"}, lepes)
    RW.apply_changes("Ger40", "csilla", lepes)
    check("a felülírás a csillára íródott",
          R.spec_for("Ger40", "csilla")["preset"] == RR.PRESET_SHIELD
          and R.get_exit_config("Ger40", "csilla")["indicator"] == "wpr")
    check("...a pár alapja érintetlen", R.spec_for("Ger40")["preset"] == RR.PRESET_OFF)
    check("a felülírt mezők listája", RW.overridden("Ger40", "csilla")
          == {"preset", "runner", "exit_indicator"}, RW.overridden("Ger40", "csilla"))
    check("összefoglaló a csillán: Pajzs · Kiszállási jel",
          R.NAME[RR.PRESET_SHIELD] in RW.summary("Ger40", "csilla")
          and R.RUNNER_NAME[RR.RUNNER_EXIT] in RW.summary("Ger40", "csilla"),
          RW.summary("Ger40", "csilla"))

    # vissza örököltre (a runner marad saját)
    elotte2 = {k: (RW.values("Ger40", "csilla")[k] if k in RW.overridden("Ger40", "csilla")
                   else RW.INHERIT) for k in RW.FIELD_KEYS}
    utana2 = dict(elotte2, preset=RW.INHERIT, exit_indicator=RW.INHERIT)
    RW.apply_changes("Ger40", "csilla", RW.plan_changes("Ger40", "csilla", elotte2, utana2))
    check("„Örökölt” → a felülírás törlődik (a preset a páré)",
          R.spec_for("Ger40", "csilla")["preset"] == RR.PRESET_OFF
          and "preset" not in R.override_of("Ger40", "csilla"))
    check("...a többi saját mező megmarad", R.override_of("Ger40", "csilla").get("runner")
          == RR.RUNNER_EXIT, R.override_of("Ger40", "csilla"))

    # a pár alapja: csak a változás íródik
    v = RW.values("Ger40")
    RW.apply_changes("Ger40", None, RW.plan_changes("Ger40", None, v,
                                                    dict(v, breakeven_r=2.0)))
    check("a pár alapjának módosítása", R.spec_for("Ger40")["breakeven_r"] == 2.0)
    check("...és a csilla örökli (nem írta felül)",
          R.spec_for("Ger40", "csilla")["breakeven_r"] == 2.0)

    # ── idő-kilépés stratégián ───────────────────────────────────────────────
    RW.apply_changes("Ger40", "wpr_sma", [("set", "eod_close", "21:30")])
    check("napvégi zárás csak a wpr_smán",
          R.get_time_exit("Ger40", "wpr_sma")["eod_close"] == "21:30"
          and R.get_time_exit("Ger40")["eod_close"] == "")

    # ── relevancia ────────────────────────────────────────────────────────
    rel = RW.relevant({"preset": RR.PRESET_SHIELD, "runner_stop": RR.RUNNER_EXIT})
    check("Pajzs + jel: a részleges zárás és a jel-indikátor hat",
          {"trigger_R", "shield_fraction", "exit_indicator", "runner"} <= rel)
    check("...a Felező hányada NEM", "halving_fraction" not in rel)

    # ── az optimalizáló a stratégia felülírásába ír ───────────────────────
    from ml import optimizer as OPT
    OPT.apply_optimized_rr("Ger40", {"preset": RR.PRESET_HALVING, "runner_stop": RR.RUNNER_TRAILING,
                                     "trigger_R": 1.5}, strategy="wpr_sma")
    check("optimalizáló: a wpr_sma felülírásába írt",
          R.spec_for("Ger40", "wpr_sma")["preset"] == RR.PRESET_HALVING
          and R.spec_for("Ger40", "wpr_sma")["trigger_R"] == 1.5)
    check("...a pár alapja és a csilla érintetlen",
          R.spec_for("Ger40")["preset"] == RR.PRESET_OFF
          and R.spec_for("Ger40", "csilla")["preset"] == RR.PRESET_OFF)
    _osrc = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
    check("a háttér-optimalizáló a hangolt stratégiával hív",
          "apply_optimized_rr(symbol, _rr, strategy=sname)" in _osrc)

    # ── az ablak felépül (ha van Tk) ──────────────────────────────────────
    try:
        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        TK = True
    except Exception as e:                                       # noqa: BLE001
        TK = False
        print(f"KIHAGYVA: nincs tkinter ({e})")
    if TK:
        cfg = {"available_strategies": ["wpr_sma", "csilla"],
               "pairs": {"Ger40": {"strategies": ["wpr_sma", "csilla"]},
                         "GOLD": {"strategies": ["wpr_sma"]}}}
        w = RW.RiskWindow(root, cfg)
        check("a mátrix felépül", w.top.winfo_exists() and len(w._body.winfo_children()) > 6)
        ed = RW.RiskEditor(w.top, "Ger40", "csilla")
        check("stratégia-szerkesztő: a felül nem írt mező „Örökölt”",
              ed._before["preset"] is RW.INHERIT and ed._before["runner"] == RR.RUNNER_EXIT)
        _m, sv, opts = ed._vars["preset"]
        sv.set(next(c for vv, c in opts if vv == RR.PRESET_FIBO))
        ed._save()
        check("szerkesztőből mentve", R.spec_for("Ger40", "csilla")["preset"] == RR.PRESET_FIBO)
        eb = RW.RiskEditor(w.top, "GOLD", None)
        check("alap-szerkesztő: nincs „Örökölt” tétel",
              all(v is not RW.INHERIT for v, _c in eb._vars["preset"][2]))
        eb.top.destroy()
        w.top.destroy()
        root.destroy()
finally:
    R.PATH, R._sync_risky = _vp, _vr
    R._state.clear()
    R._state.update(_vs)

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
