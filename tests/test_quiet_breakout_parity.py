"""QUIET_BREAKOUT — a stratégia-modul PARITÁSA a kutató-laborral (2026-10-02).

⚠ NEM ÜRES PARITÁS (`vacuous-parity-tests`): mindkét kar VALÓS adaton fut, a
belépők száma > 0 kötelező, és a két kart NEM ugyanaz a kód adja — a labor a
`tools/research/swing_weekly.py` + `swing_vol.py` saját implementációja, a modul a
`strategies/quiet_breakout_rules.py`.

Amit őrzünk:
  1. regisztráció, interfész, config, docs, magic, i18n kulcsok;
  2. a modul belépői == a labor belépői (időpont + stop-táv) UGYANAZON a kereten;
  3. a motor-út (`bt_indicators`) a jelet a belépő M15 ZÁRÁSA utáni első M1-sorra
     teszi, és a natív M15-soron ott a stop-táv;
  4. a `run_pair` végigfut, és van kötés — a jelzett időpontokban.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import broker_paths as _BP                      # noqa: E402
sys.path.insert(0, str(ROOT / "tools" / "research"))

from core import applog  # noqa: E402
applog.harden_console()

NAME = "quiet_breakout"
SYM = "UsaTec"
T0, T1 = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-07-01", tz="UTC")
_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------
print("== Regisztracio es interfesz ==")
from strategy import registered_strategy_names, get_strategy_by_name    # noqa: E402
from strategy.base import Strategy                                       # noqa: E402

check("auto-felderites megtalalja", NAME in registered_strategy_names())
s = get_strategy_by_name(NAME)
check("a Strategy leszarmazottja", isinstance(s, Strategy))
check("NINCS absztrakt metodus hianyban", not getattr(type(s), "__abstractmethods__", None))
check("docs (hu) letezik, >200 karakter", s.doc_path().exists()
      and len(s.doc_path().read_text(encoding="utf-8")) > 200)
check("docs (en) letezik", (ROOT / "strategies" / "docs" / f"{NAME}.en.md").exists())
raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
from strategy.settings import config_for_strategy                        # noqa: E402
cfg = config_for_strategy(raw, NAME)
base = s.base_params(cfg)
for k in ("pivot_k", "atr_len", "vol_max", "min_align", "sl_min_atr", "sl_max_atr",
          "tp_rr_ratio"):
    check(f"a(z) {k!r} a base_params-ban", k in base)
mags = {get_strategy_by_name(n).magic(cfg) for n in registered_strategy_names()}
check("a magic egyedi", len(mags) == len(registered_strategy_names()))
for lang in ("hu", "en"):
    d = json.loads((ROOT / "lang" / f"{lang}.json").read_text(encoding="utf-8"))
    for k in ("stage.qb_align", "stage.qb_quiet", "stage.qb_entry",
              "param_cat.structure", "param_cat.filters"):
        check(f"{lang}: {k}", k in d)

# ---------------------------------------------------------------------------
print("\n== A modul belepoi == a labor belepoi ==")
import lab                                                               # noqa: E402
from swing_weekly import run_sym                                         # noqa: E402
from swing_vol import vol_ratio                                          # noqa: E402
from strategies import quiet_breakout_rules as rules                     # noqa: E402

ref = run_sym(SYM, start=T0, end=T1)
ref = ref[ref.side == 1].copy()
ref["egy4"] = ref.m1_ok + ref.m5_ok + ref.h1_ok + ref.h4_ok
v = vol_ratio(SYM, start=str((T0 - pd.Timedelta(days=60)).date()), end=str(T1.date()))
ref["vol"] = v.reindex(ref.time).to_numpy()
ref = ref[(ref.vol <= 0.78) & (ref.egy4 >= 2)]

m1 = lab.load_m1(SYM)
m1 = m1[(m1.index >= T0 - pd.Timedelta(days=120)) & (m1.index < T1)]
tab = rules.entry_table(m1, base)
loc = (tab.index + pd.Timedelta(minutes=15)).tz_convert("UTC")  # fal-óra: nincs átváltás
lm = loc.hour * 60 + loc.minute
sp = lab.resample(m1, 15)["avg_spread"].reindex(tab.index).to_numpy()
mine = tab[tab["sig"].to_numpy() & (lm >= 600) & (lm < 1260) & np.isfinite(sp)
           & (tab.index >= T0)]
a, b = set(mine.index), set(ref.time)
check("a labor ad belepot (nem ures)", len(b) > 10, f"n={len(b)}")
check("a modul belepoi == a labor belepoi", a == b,
      f"modul {len(a)}, labor {len(b)}, csak modul {len(a - b)}, csak labor {len(b - a)}")
com = sorted(a & b)
if com:
    r = ref.set_index("time").loc[com]
    risk_ref = (lab.resample(m1, 15)["avg_spread"].reindex(com) / r["cost"]).to_numpy()
    dif = np.nanmax(np.abs(mine.loc[com, "sl_dist"].to_numpy() - risk_ref))
    check("a stop-tav bitre egyezik", dif < 1e-9, f"max elteres {dif}")

# ---------------------------------------------------------------------------
print("\n== Motor-ut (bt_indicators) ==")
m15 = pd.read_parquet(_BP.bars_file("m15", SYM))
m15 = m15[(m15.index >= T0 - pd.Timedelta(days=120)) & (m15.index < T1)]
m1e = pd.read_parquet(_BP.bars_file("m1", SYM))
m1e = m1e[~m1e.index.duplicated(keep="last")].sort_index()
m1e = m1e[(m1e.index >= T0 - pd.Timedelta(days=120)) & (m1e.index < T1)]
hi, lo = s.bt_indicators(m15, m1e, {**base, "point_size": 0.01})
sig_t = lo.index[lo["qb_sig"].to_numpy()]
exp_t = rules.entry_table(m1e, base)
exp_t = exp_t.index[exp_t["sig"].to_numpy()] + pd.Timedelta(minutes=15)
check("van M1-jelzes", len(sig_t) > 10, f"n={len(sig_t)}")
check("a jel a belepo M15 zarasanak M1-soran", set(sig_t) <= set(exp_t)
      and len(set(exp_t) - set(sig_t)) <= 2,
      f"jel {len(sig_t)}, vart {len(exp_t)}")
_ok = hi["qb_sl_dist"].reindex(sig_t - pd.Timedelta(minutes=15))
check("a nativ M15-soron ott a stop-tav", _ok.notna().mean() > 0.95,
      f"{_ok.notna().mean():.3f}")

# ---------------------------------------------------------------------------
print("\n== run_pair ==")
from core.execution_params import load_execution_params                 # noqa: E402
from trading.backtest import run_pair                                    # noqa: E402

params = {**base, **(load_execution_params(SYM, cfg) or {})}
res = run_pair(SYM, m15, m1e, params, cfg["pairs"][SYM], cfg["trading"], 10_000.0,
               strategy=s, cfg=cfg, test_start=str(T0.date()), test_end=str(T1.date()))
opens = {pd.Timestamp(t.open_time) for t in res.closed}
check("a run_pair kotest ad", len(res.closed) > 5, f"n={len(res.closed)}")
check("minden kotes egy jelzett idopontban nyilt",
      all(any(abs((o - x).total_seconds()) <= 120 for x in sig_t) for o in opens),
      f"kotes {len(opens)}")
check("csak long", all(t.direction == "BUY" for t in res.closed))

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("BUKOTT:", _fail)
    sys.exit(1)
