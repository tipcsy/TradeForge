# Kutatási mérőműszer

**Ez NEM a motor.** Kísérleti kód, ami a hosszú (tickből épített) mintán mér
hipotéziseket, mielőtt bármiből stratégia-modul lenne. A `strategy/` csomagba
csak az kerülhet, ami itt átment a rostán.

Miért külön: a `trading/backtest.py` egy KONKRÉT stratégia végigfuttatására való,
ez pedig százas nagyságrendű variáns gyors szűrésére. A végrehajtási konvenciók
ugyanazok (bid gyertya, ask = bid + spread, belépő a gyertya zárásán, BUY ask-on
nyit / bid-en zár), és a kapuk a rendszer SAJÁT moduljaiból jönnek
(`core.regime`, `core.spread_gate`, `core.momentum`, `core.cost_gate`) — így ami
itt mérhető, az átvihető élesbe.

---

## ⚠ Az elfogadási protokoll — ezt előre kell rögzíteni

Egy jelölt csak akkor mehet tovább, ha **mindhárom** teljesül:

1. **t ≥ 2** az összevont mintán,
2. **az évek legalább 60%-ában pozitív**,
3. **legalább 3 instrumentumon pozitív**.

**Miért.** 2026-08-27-én a `donchian48 + kapuk` a 2 éves mintán +0,100 R/kötést
adott (t = +2,04) — a 14 évesen **−0,038 (t = −2,94)**, és 14-ből 11 évben
negatív. Csak az utolsó három évben volt pozitív: pontosan abban az ablakban,
amin felfedeztem. Egy háromévnyi szerencsés szakasz teljes élnek látszik.

A 2. feltétel (évenkénti konzisztencia) ölte volna meg ezt a jelöltet a
felfedezés napján. A t-statisztika nem.

---

## Fájlok

| fájl | mit ad |
|---|---|
| `lab.py` | adatbetöltés, újramintavétel, indikátorok, **szimulátor** (SL/TP/BE/trailing, EOD) |
| `gates_lab.py` | a rendszer kapui bar-onként kiszámolva (gyorsítótárazva) |
| `exp_struct.py` | szerkezeti jellemzők (swing-pontok, trendvonal-R², harmados pozíció) |
| `rules.py`, `rules_long.py` | belépő-szabály katalógus (~24 variáns) |
| `run_gates.py` | kapu-maszkok + idő-alapú kimenet-mérés |
| `mae_mfe.py` | **„mennyire lőttünk mellé"** — MAE/MFE, idő pluszban/mínuszban, megmenthető vesztesek |
| `shield.py` | kockázatcsökkentés (BE, trailing) hatása |
| `build_pyramid.py` | **pozícióépítés** a `core/position_build.py` szabályaival |
| `sizing.py` | **feltételes méretezés** — kvintilis-elemzés + súlyozott eredmény |

Futtatás a projekt gyökeréből:

```bash
python tools/research/mae_mfe.py
python tools/research/sizing.py
```

---

## Eddigi eredmények (2026-08-28, 5 instrumentum, 2013–2026)

**A belépő majdnem nem hordoz irányt.** MFE/MAE = **1,036**; a kötések 50,6%-ánál
ment többet a jó irányba; az idő 49,3%-a telt pluszban.

**A kimenet-kezelés viszont számít** — és ezt sokáig nem mértem:

| lépés | R/kötés | hozzáadás |
|---|---|---|
| kiindulás (célárral) | −0,019 | — |
| **célár elhagyása** (BE + hagyd futni) | +0,012 | **+0,031** |
| + pozícióépítés (fix R-rács) | +0,020 | +0,008 |
| + feltételes méretezés (walk-forward) | ~+0,016…0,025 | +0,013 |

**A kockázatcsökkentés átrajzol, de nem mozgat.** BE 0,3R-nél a kötések 51,6%-a
nullán zár, a vesztes-arány 59,9% → 30,7% — és a várható érték nem változik
(−0,0326 → −0,0322). Ez az opcionális megállítás tétele, megmérve.

**A méretezés iránya fordított az intuícióhoz képest.** A nagyobb pozíció a
CSENDES piacnak jár: a lendület/ADX/R² szerint *fordítva* méretezve +0,015, míg
„egyenesen" méretezve negatív. Magyarázat: a kitörés akkor ér valamit, ha
meglepetés — ha a piac már pörög, a mozgás nagy része megtörtént.

**A szűk keresztmetszet a swap:** −0,028…−0,044 R/kötés, **nagyobb, mint az
egész mért él**. Nélküle a rendszer +0,064 (t = 2,85) lenne.

Végállapot: **+0,02 R/kötés, t < 1, 95% CI [−0,024 … +0,063]**.
