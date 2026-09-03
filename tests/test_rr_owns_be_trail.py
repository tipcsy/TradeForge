"""A BE + trailing a KOCKAZATCSOKKENTESE, nem a strategiae (v1.96.0).

A FELISMERES: a `PRESET_OFF` kommentje szerint „nincs kockazatcsokkentes" — de a
`_manage_position` az off-agban is `_update_stops`-ot hivott, azaz MINDIG futott a
breakeven es a trailing. Az `off` sosem jelentett semmit; a „legkisebb"
kockazatcsokkentes volt. Kozben a harom parametere a strategia parameter-ablakaban
ult (kozos „Vegrehajtas" kategoria), MINDEN preseten — holott:

  • Fibo / Harmados preseten SEMMIT nem csinalt (a `_manage_position` oda sem er),
  • Felezo/Pajzs + runner=keep/BE eseten sem,
  • risky-nel csak a TAVOLSAG szamit (a BE es az aktivalas azonnali).

Vagyis egy szerkesztheto beallitas, ami a legtobb preseten HATASTALAN — ugyanaz a
hibafajta, mint a `max_open_slots` a strategia-parameterek kozt.

AMIT ITT ORZUNK, harom szinten:
  1. a HATAR: a kockazatcsokkentes nem lat strategia-parametert (nincs `params`),
  2. a FORRAS: a BE/trailing az rr-specbol jon, nem a strategia dictjebol,
  3. a MATRIX: melyik preseten melyik parameter hat egyaltalan.
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import risk_reduction as rr
from core import rr_state as rrs
from core import execution_params as ep
from trading import backtest as bt


# ══ 1. A HATAR: a kockazatcsokkentes nem lat strategia-parametert ═════════
sig = inspect.signature(bt._manage_position)
check("a _manage_position-nek NINCS `params` parametere (szerkezeti hatar)",
      "params" not in sig.parameters, str(list(sig.parameters)))
check("a _update_stops `rr`-t kap, nem `params`-ot",
      "rr" in inspect.signature(bt._update_stops).parameters,
      str(list(inspect.signature(bt._update_stops).parameters)))

# A kulcsok tenyleg atkerultek.
for k in rr.BE_TRAIL_KEYS:
    check(f"a(z) {k} a kockazatcsokkento alapertekek kozt van",
          k in rr.default_config())
    check(f"...es MAR NINCS a kozos vegrehajtasi configban", k not in ep.DEFAULTS)


# ══ 2. A FORRAS: az rr-spec dont, nem a strategia params ═════════════════
class T:
    """Minimalis Trade a stop-frissiteshez (BUY, 100 -> TP 110, SL 90)."""
    def __init__(self):
        self.legs = [(100.0, 1.0)]
        self.direction = "BUY"
        self.open_price = 100.0
        self.tp = 110.0
        self.sl = 90.0
        self.risk_free = False
        self.entry_atr = 1.0


# be=0.5 -> a BE trigger 100 + (110-100)*0.5 = 105. FIGYELEM: a BE utan a
# TRAILING is fut ugyanebben a hivasban (ez a helyes viselkedes), ezert a vegso
# stop a belepo FOLOTT all — az invarians az, hogy kockazatmentes lett.
t = T()
bt._update_stops(t, high=105.0, low=99.0,
                 rr={"breakeven_pct": 0.5, "trail_activation_atr": 0.5,
                     "trail_distance_atr": 0.4},
                 point_size=0.01, risky=False)
check("a BE az rr-spec ertekevel sul el", t.risk_free and t.sl >= t.open_price,
      f"sl={t.sl} rf={t.risk_free}")

# ugyanaz a bar, DE be=0.9 -> a trigger 109, tehat MEG NEM sul el
t2 = T()
bt._update_stops(t2, high=105.0, low=99.0, rr={"breakeven_pct": 0.9},
                 point_size=0.01, risky=False)
check("...es egy masik rr-ertek MAS eredmenyt ad (tenyleg onnan olvas)",
      not t2.risk_free and t2.sl == 90.0, f"sl={t2.sl} rf={t2.risk_free}")

# be=0 -> a BE ki van kapcsolva
t3 = T()
bt._update_stops(t3, high=109.9, low=99.0, rr={"breakeven_pct": 0.0},
                 point_size=0.01, risky=False)
check("breakeven_pct=0 -> nincs BE (kikapcsolhato)", not t3.risk_free)

# A TRAILING TAVOLSAGA is az rr-bol jon: azonos baron ket kulonbozo tavolsag
# ket kulonbozo stopot ad (105 - 0.4 = 104.6 vs 105 - 2.0 = 103.0).
def _trail_sl(dist):
    x = T()
    bt._update_stops(x, high=105.0, low=99.0,
                     rr={"breakeven_pct": 0.5, "trail_activation_atr": 0.0,
                         "trail_distance_atr": dist},
                     point_size=0.01, risky=False)
    return round(x.sl, 6)

check("a trailing TAVOLSAGA is az rr-specbol jon",
      _trail_sl(0.4) == 104.6 and _trail_sl(2.0) == 103.0,
      f"{_trail_sl(0.4)} / {_trail_sl(2.0)}")


# ══ 3. PRESET_NONE: tenyleg SEMMI ════════════════════════════════════════
# Az `off` mindig BE-zett; aki tenyleg semmit akar, annak eddig NEM volt modja.
t4 = T()
bt._manage_position(t4, high=109.0, low=99.0, point_size=0.01,
                    min_lot=0.01, lot_step=0.01,
                    rr={**rr.default_config(), "preset": rr.PRESET_NONE})
check("`none` preset: a stop MARAD, ahol volt", t4.sl == 90.0 and not t4.risk_free,
      f"sl={t4.sl}")

t5 = T()
bt._manage_position(t5, high=109.0, low=99.0, point_size=0.01,
                    min_lot=0.01, lot_step=0.01,
                    rr={**rr.default_config(), "preset": rr.PRESET_OFF})
check("`off` preset: kockazatmentesit (ez a KULONBSEG a ketto kozt)",
      t5.risk_free and t5.sl >= t5.open_price, f"sl={t5.sl}")

check("a `none` benne van a presetekben es a korben",
      rr.PRESET_NONE in rr.PRESETS and rr.PRESET_NONE in rrs.CYCLE)
check("az `off` felirata mar IGAZAT mond (nem 'Ki')",
      rrs.NAME[rr.PRESET_OFF] == "BE + trailing", rrs.NAME[rr.PRESET_OFF])
check("...a `none` az, ami 'Ki'", "Ki" in rrs.NAME[rr.PRESET_NONE],
      rrs.NAME[rr.PRESET_NONE])
check("az `off` KULCSA valtozatlan (a mentett allapot nem serul)",
      rr.PRESET_OFF == "off")


# ══ 4. A MATRIX: melyik preseten melyik parameter hat ════════════════════
M = rr.be_trail_active
check("off -> mind a harom", M(rr.PRESET_OFF) == set(rr.BE_TRAIL_KEYS))
check("risky -> csak a tavolsag (a BE es az aktivalas azonnali)",
      M(rr.PRESET_RISKY) == {"trail_distance_atr"}, str(M(rr.PRESET_RISKY)))
check("halving + runner=trailing -> a ket trail-kulcs",
      M(rr.PRESET_HALVING, rr.RUNNER_TRAILING)
      == {"trail_activation_atr", "trail_distance_atr"})
check("halving + runner=keep -> EGYIK SEM",
      M(rr.PRESET_HALVING, rr.RUNNER_KEEP) == set())
check("shield + runner=breakeven -> EGYIK SEM",
      M(rr.PRESET_SHIELD, rr.RUNNER_BREAKEVEN) == set())
check("fibo -> EGYIK SEM (ez volt a panasz)", M(rr.PRESET_FIBO) == set())
check("thirds -> EGYIK SEM", M(rr.PRESET_THIRDS) == set())
check("none -> EGYIK SEM", M(rr.PRESET_NONE) == set())


# ══ 5. A per-par tarolas hordozza a harom kulcsot ════════════════════════
check("a rr_state kalibracios kulcsai kozt ott a harom",
      all(k in rrs._CALIB_KEYS for k in rr.BE_TRAIL_KEYS))

# A migracios olvaso letezik es ures dictet ad, ha nincs mit vinni.
check("az execution_params tudja, mi kolt at (migraciohoz)",
      set(ep.MIGRATED_KEYS) == set(rr.BE_TRAIL_KEYS))
check("a load_execution_params MAR NEM adja vissza oket",
      not (set(ep.load_execution_params("NINCS_ILYEN_PAR", {}))
           & set(rr.BE_TRAIL_KEYS)))


# ══ 6. NEMA VISELKEDES-VALTOZAS ELLEN: az `rr=None` ut is a PAR ertekeit kapja ══
# Ez a koltozes legveszelyesebb mellekhatasa lett volna: a BE/trailing korabban a
# `params`-ban utazott (per-szimbolum execution-overlay-jel), most az rr-ben lakik.
# Az `rr=None` hivok (optimalizalo, run_backtest) tehat a MODUL alapertekere
# estek volna vissza a par hangolt erteke helyett — es a hangolas mas vilagban
# tortent volna, mint az el.
rrs.load()
_cal = rrs.get_calibration("Ger40")
if _cal:
    spec = bt._rr_spec(None, False, "Ger40")
    check("az rr=None ut a PAR sajat BE/trail erteket kapja",
          all(abs(spec[k] - _cal[k]) < 1e-9 for k in rr.BE_TRAIL_KEYS if k in _cal),
          f"spec={[round(spec[k],3) for k in rr.BE_TRAIL_KEYS]} "
          f"par={[round(_cal.get(k, -1),3) for k in rr.BE_TRAIL_KEYS]}")
    check("...es NEM a modul alapertekere esik vissza (kulonben nema valtozas)",
          any(abs(spec[k] - rr.default_config()[k]) > 1e-9
              for k in rr.BE_TRAIL_KEYS if k in _cal),
          "a par ertekei veletlenul epp az alapertekek?")
else:
    print("KIHAGYVA: nincs migralt Ger40-kalibracio (friss telepites)")

# Ismeretlen par -> alapertek, kivetel nelkul.
_spec_unknown = bt._rr_spec(None, False, "NINCS_ILYEN_PAR")
check("ismeretlen parnal az alapertek (nem szall el)",
      _spec_unknown["breakeven_pct"] == rr.default_config()["breakeven_pct"])


# ══ 7. A strategia-configokban NINCS nyoma ═══════════════════════════════
import json
for name in ("wpr_sma", "ml_ai"):
    raw = json.loads((ROOT / "strategies" / "config" / f"{name}.json")
                     .read_text(encoding="utf-8"))
    flat = set()
    for sec in ("indicators", "sltp", "position_mgmt"):
        flat |= set(raw.get(sec) or {})
    pm = set((raw.get("param_meta") or {}).get("params") or {})
    opt = set(raw.get("optimizer") or {})
    leak = (flat | pm | opt) & set(rr.BE_TRAIL_KEYS)
    check(f"{name}: nincs BE/trailing kulcs a strategia-configban", not leak,
          str(leak))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
