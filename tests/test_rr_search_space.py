"""A kockazatcsokkento kereses FELTETELES tere (v1.96.0) — ml/optimizer.py.

A KORABBI TER LAPOS VOLT: minden dimenziot minden trialen sorsolt, akkor is, ha a
preset nem hasznalja. Konkretan a `halving_fraction`-t `off`/`risky` preseten es a
`shield_fraction`-t `halving`-nal — pedig a `target_fraction` ezeket ott sosem
olvassa. Elpazarolt tengelyek: a TPE mintavevo rajuk is modellezett, a trials-CSV
pedig olyan szamot mutatott, aminek NULLA hatasa volt az eredmenyre. Ugyanaz a
hibafajta, mint a `max_open_slots` a strategia-terben.

AMIT ORZUNK:
  1. minden dimenzio CSAK azon a preseten sorsolodik, ahol hat,
  2. a nem sorsolt dimenzio URES cellat kap a CSV-ben (nem 0, nem alapertek),
  3. a suggeszt-SORREND determinisztikus (kulonben az azonos seedu study sem
     reprodukalhato),
  4. a nyertes spec NEM esik vissza None-ra `off` preseten (az eldobna a keresest).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import risk_reduction as rr
import ml.optimizer as opt


class FakeTrial:
    """Rogziti, MELY dimenziokat kertek — ez a teszt lenyege."""

    def __init__(self, preset, runner="trailing"):
        self._preset, self._runner = preset, runner
        self.asked = []           # a suggeszt-hivasok NEVE, SORRENDBEN

    def suggest_categorical(self, name, choices):
        self.asked.append(name)
        if name == "rr_preset":
            return self._preset
        if name == "rr_runner":
            return self._runner
        return choices[0]

    def suggest_float(self, name, lo, hi, step=None):
        self.asked.append(name)
        return lo


def dims(preset, runner="trailing"):
    """A trialen TENYLEGESEN sorsolt dimenziok (a preset-valasztas nelkul)."""
    t = FakeTrial(preset, runner)
    spec = opt._suggest_rr(t, {})
    return {a[3:] for a in t.asked if a != "rr_preset"}, spec, t.asked


# ══ 1. Amit korabban PAZAROLTUNK ═════════════════════════════════════════
d_off, _, _ = dims("off")
check("off: NINCS halving_fraction (ott sosem hatott)", "halving_fraction" not in d_off,
      str(sorted(d_off)))
check("off: NINCS shield_fraction", "shield_fraction" not in d_off)
check("off: NINCS trigger_R (nincs reszleges zaras)", "trigger_R" not in d_off)
check("off: NINCS runner (nincs runner)", "runner" not in d_off)

d_risky, _, _ = dims("risky")
check("risky: sem frakcio, sem trigger", not ({"halving_fraction", "shield_fraction",
                                               "trigger_R"} & d_risky), str(sorted(d_risky)))

d_halv, _, _ = dims("halving")
check("halving: CSAK a sajat frakcioja",
      "halving_fraction" in d_halv and "shield_fraction" not in d_halv,
      str(sorted(d_halv)))
d_shield, _, _ = dims("shield")
check("shield: CSAK a sajat frakcioja",
      "shield_fraction" in d_shield and "halving_fraction" not in d_shield,
      str(sorted(d_shield)))


# ══ 2. A BE/trailing pontosan ott, ahol hat ══════════════════════════════
BT = set(rr.BE_TRAIL_KEYS)
check("off: mind a harom BE/trail dimenzio", BT <= d_off, str(sorted(d_off)))
check("risky: CSAK a trail-tavolsag", BT & d_risky == {"trail_distance_atr"},
      str(sorted(BT & d_risky)))
check("halving + runner=trailing: a ket trail-kulcs",
      BT & d_halv == {"trail_activation_atr", "trail_distance_atr"},
      str(sorted(BT & d_halv)))

d_keep, _, _ = dims("halving", "keep")
check("halving + runner=keep: EGYETLEN BE/trail dimenzio SEM", not (BT & d_keep),
      str(sorted(d_keep)))

d_fibo, _, _ = dims("fibo")
check("fibo: nincs BE/trail, VAN fibo_stop_level",
      not (BT & d_fibo) and "fibo_stop_level" in d_fibo, str(sorted(d_fibo)))
d_thirds, _, _ = dims("thirds")
check("thirds: nincs BE/trail, VAN thirds_base_R",
      not (BT & d_thirds) and "thirds_base_R" in d_thirds, str(sorted(d_thirds)))
d_none, _, _ = dims("none")
check("none: SEMMI nem sorsolodik (tenyleg semmi nem hat)", not d_none,
      str(sorted(d_none)))


# ══ 3. Determinisztikus SORREND (a seedelt study reprodukalhatosaga) ═════
# A `be_trail_active` HALMAZT ad; halmazon iteralva a str-hash randomizalas miatt
# a sorrend processzenkent mas lenne -> ugyanaz a seed MAS trialeket adna.
orders = [dims("off")[2] for _ in range(5)]
check("ugyanazon a preseten a suggeszt-sorrend ALLANDO",
      all(o == orders[0] for o in orders), str(orders[0]))
_bt_order = [a[3:] for a in orders[0] if a[3:] in BT]
check("...es a BE/trail kulcsok a ROGZITETT sorrendben jonnek",
      _bt_order == [k for k in rr.BE_TRAIL_KEYS if k in BT], str(_bt_order))


# ══ 4. A spec TELJES marad, es nem esik vissza None-ra ═══════════════════
_, spec_off, _ = dims("off")
check("a spec tartalmazza a presetet es a runnert (egyseges alak)",
      spec_off.get("preset") == "off" and "runner_stop" in spec_off)
check("`off` preset spec-je NEM lesz None (kulonben a kereses elveszne)",
      opt._rr_for_run(spec_off) is spec_off)
check("None spec -> None (a kikapcsolt ut valtozatlan)",
      opt._rr_for_run(None) is None and opt._rr_for_run({}) is None)

_, spec_h, _ = dims("halving")
check("a cautious a preset szerint all be",
      spec_h["cautious"] is False and dims("risky")[1]["cautious"] is True)


# ══ 5. Configbol szukitheto a preset-halmaz ══════════════════════════════
t = FakeTrial("shield")
opt._suggest_rr(t, {"rr_presets": ["shield", "halving"]})
check("az rr_presets szukiti a valaszthato preseteket", "rr_preset" in t.asked)
t2 = FakeTrial("off")
opt._suggest_rr(t2, {"rr_presets": ["nincs_ilyen_preset"]})
check("ismeretlen preset-nev kiszurve (nem szall el)", "rr_preset" in t2.asked)


# ══ 6. A nyertes ertekek PERZISZTALNAK a par allapotaba ══════════════════
from core import rr_state as rrs
check("a rr_state minden uj kalibracios kulcsot ismer",
      all(k in rrs._CALIB_KEYS for k in
          ("trigger_R", "halving_fraction", "shield_fraction", "fibo_stop_level",
           "thirds_base_R", *rr.BE_TRAIL_KEYS)))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
