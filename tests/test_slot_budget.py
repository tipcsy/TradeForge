"""A slot mint KOCKAZATI KERET (nem darabszam).

LELET (2026-08-27). A `SlotManager` minden poziciot PONTOSAN 1 slotnak szamolt,
fuggetlenul a benne levo kockazattol. Kis szamlan a broker `min_lot`-ja nagyobb
lotot kenyszerit, mint amennyi a slot keretebe ferne: 981 EUR egyenlegen,
`account_risk_pct` 1% es 4 slot mellett egy slot kerete 2,45 EUR, egy UsaTec
pozicio viszont 12,36 EUR-t kockaztat (5,04 slot). NEGY ilyen pozicio
szabalyosnak LATSZOTT, es kozben 5% volt kockazatban 1% helyett.

Ez a teszt azt orzi, hogy a foglaltsag SULYOZOTT, a sulyt a MINDENKORI keretbol
szamoljuk (nem tarolt, elavulo erteket), es a tul nagy pozicio csak URES
kerettel nyithato.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results = []


def check_(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core.risk_manager import SlotManager, slot_weight, fits_budget

BAL = 981.32
TCFG = {"account_risk_pct": 0.01, "max_open_slots": 4}
PER_SLOT = BAL * 0.01 / 4                      # 2.4533 EUR

# ── slot_weight ─────────────────────────────────────────────────────────────
check_("a suly a kockazat / egy slot kerete",
       abs(slot_weight(PER_SLOT, BAL, TCFG) - 1.0) < 1e-9)
check_("UsaTec merte kockazata 5,04 slot",
       abs(slot_weight(12.36, BAL, TCFG) - 5.04) < 0.01,
       f"{slot_weight(12.36, BAL, TCFG):.3f}")
check_("fel merettel fel suly",
       abs(slot_weight(PER_SLOT / 2, BAL, TCFG) - 0.5) < 1e-9)
# Ismeretlen bemenet SOHA ne adjon 0-t: az korlatlan nyitast engedne.
check_("ismeretlen kockazat -> 1.0 (a regi viselkedes)",
       slot_weight(0.0, BAL, TCFG) == 1.0)
check_("nulla egyenleg -> 1.0", slot_weight(5.0, 0.0, TCFG) == 1.0)
check_("hianyos trading cfg -> 1.0", slot_weight(5.0, BAL, {}) == 1.0)

# ── fits_budget ─────────────────────────────────────────────────────────────
check_("ures keretbe belefer az 1.0", fits_budget(0.0, 1.0, 4))
check_("3.0 foglalt + 1.0 meg belefer", fits_budget(3.0, 1.0, 4))
check_("3.5 foglalt + 1.0 mar nem", not fits_budget(3.5, 1.0, 4))
check_("nulla kockazat mindig belefer (kockazatmentes lab)",
       fits_budget(4.0, 0.0, 4))
# A lebegopontos osszeadas ne buktassa a negyedik belepot.
check_("4 x 0.25 osszege nem buktatja az utolsot",
       fits_budget(0.25 * 3 + 1e-16, 0.25, 1.0))
# A `min_lot` miatt egymaga tullogo pozicio: csak URES kerettel.
check_("a kereten tullogo pozicio ures kerettel nyithato",
       fits_budget(0.0, 5.04, 4))
check_("...de barmi mas mellett nem", not fits_budget(0.5, 5.04, 4))

# ── SlotManager: sulyozott foglaltsag ───────────────────────────────────────
sm = SlotManager(4)
sm.set_budget(BAL, TCFG)
check_("keret beallitas utan a suly szamolhato",
       abs(sm.set_budget(BAL, TCFG) - PER_SLOT) < 1e-9)

sm.add(101, 12.36)                              # UsaTec
check_("egy UsaTec pozicio 5,04 slotot foglal",
       abs(sm.occupied() - 5.04) < 0.01, f"{sm.occupied():.3f}")
check_("...es ezzel NINCS tobb hely", not sm.can_open_risk(12.36))
check_("...egy pici pozicionak sem", not sm.can_open_risk(0.5))

# EZ a regresszio lenyege: negy ilyen pozicio korabban szabalyos volt.
sm2 = SlotManager(4)
sm2.set_budget(BAL, TCFG)
opened = 0
for t in range(4):
    if sm2.can_open_risk(12.36):
        sm2.add(1000 + t, 12.36)
        opened += 1
check_("4 UsaTec-meretu belepobol csak EGY nyilik meg", opened == 1, f"{opened}")
check_("...a lekotott kockazat 12,36 (nem 49,44)",
       abs(sm2.occupied_risk() - 12.36) < 0.01, f"{sm2.occupied_risk():.2f}")

# Kockazatmentes -> a TELJES sulyat felszabaditja.
sm2.set_risk_free(1000)
check_("a kockazatmentes pozicio felszabaditja a keretet",
       sm2.occupied() == 0 and sm2.can_open_risk(12.36))

# ⚠ A keret SZUKIT, nem TAGIT: a darabszam-korlat MEGMARAD. A UK100 merte
# (0,60 slot) sulyra hatot engedne a keret — de a `max_open_slots` negynel megall.
# Enelkul MINDEN korabbi backteszt eredmenye elmozdulna, nem csak a hibas eseteke.
sm3 = SlotManager(4)
sm3.set_budget(BAL, TCFG)
n = 0
while sm3.can_open_risk(1.47):
    sm3.add(2000 + n, 1.47)
    n += 1
    if n > 20:
        break
check_("UK100-meretu (0,60 slot) poziciobol a DARABSZAM-korlat 4-nel megall",
       n == 4, f"{n}")
check_("...a lekotott keret igy csak 2,4 slot (nincs tulnyitas)",
       abs(sm3.occupied() - 2.4) < 0.05, f"{sm3.occupied():.2f}")

# ── a suly NEM tarolt: a keret valtozasa atszamolja ─────────────────────────
sm4 = SlotManager(4)
sm4.set_budget(BAL, TCFG)
sm4.add(301, 4.90)                              # ~2 slot
w_before = sm4.weight_of(301)
sm4.set_budget(BAL, {"account_risk_pct": 0.02, "max_open_slots": 4})
w_after = sm4.weight_of(301)
check_("a kockazat-% duplazasa felezi a mar nyitott pozicio sulyat",
       abs(w_before / 2 - w_after) < 1e-9, f"{w_before:.3f} -> {w_after:.3f}")
sm4.set_budget(BAL * 2, TCFG)
check_("a duplazodo egyenleg is felezi a sulyt",
       abs(sm4.weight_of(301) - w_before / 2) < 1e-9)

# ── ismeretlen kockazat: a regi, darabszam-alapu viselkedes ─────────────────
sm5 = SlotManager(4)
sm5.set_budget(BAL, TCFG)
sm5.add(401)                                    # nincs megadott kockazat
check_("ismeretlen kockazatu pozicio 1 teljes slot", sm5.occupied() == 1.0)
check_("...es a remove a kockazatot is takaritja",
       (sm5.remove(401), sm5.occupied() == 0.0)[1])

# `ensure`: a meglevo bejegyzest nem irja felul
sm6 = SlotManager(4)
sm6.set_budget(BAL, TCFG)
sm6.add(501, 2.45)
sm6.set_risk_free(501)
check_("az ensure nem irja felul a kockazatmentes jelolest",
       (sm6.ensure(501, 12.36) is False) and sm6.is_risk_free(501))
check_("...uj ticketnel viszont felveszi a kockazattal",
       sm6.ensure(502, 4.90) and abs(sm6.weight_of(502) - 2.0) < 0.01)

# ── a FELULET ugyanazt a keretet szamolja, mint a motor ─────────────────────
# A cimke-szamolok tiszta fuggvenyek: stub objektummal hivhatok, tkinter ablak
# nelkul. Ha a ket oldal szethuz, a felhasznalo mast lat, mint amit a motor tesz.
from dashboard import gui as _gui


class _Stub:
    pass


_st = _Stub()
_st.cfg = {"trading": dict(TCFG)}
_st._balance = BAL
_st._occupied_risk = 12.36
check_("a felulet egy-slot kerete egyezik a motoreval",
       abs(_gui.DashboardWindow._per_slot_risk(_st) - PER_SLOT) < 1e-9)
check_("a kiirt terheles a szamla %-a",
       abs(_gui.DashboardWindow._risk_load_pct(_st) - 12.36 / BAL * 100) < 1e-9)
_st._occupied_risk = None
check_("ismeretlen lekotes -> 0% (nem hamis nulla-terheles allitas)",
       _gui.DashboardWindow._risk_load_pct(_st) == 0.0)
# A terheles a beallitott risk_pct FOLE mehet a min_lot miatt — ezt latni kell.
_st._occupied_risk = 12.36
check_("a min_lot miatti tullepes a beallitott 1% FOLOTT van",
       _gui.DashboardWindow._risk_load_pct(_st) > 1.0)
check_("a kockazat-allito metodus letezik",
       callable(getattr(_gui.DashboardWindow, "_change_risk_pct", None)))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
