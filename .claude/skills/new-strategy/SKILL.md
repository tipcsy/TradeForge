---
name: new-strategy
description: Checklist és buktatók egy ÚJ kereskedési stratégia bevezetéséhez a TradeForge kódbázisba (strategy/ csomag). Használd, amikor új stratégiát adnál a motorhoz / dashboardhoz — "új stratégia", "add strategy", "introduce a strategy", "stratégia bevezetése", stratégia-modul, param_space, bt_entry.
---

# Új stratégia bevezetése (TradeForge)

A dashboard "váza" (megjelenítés, optimalizálás, futtatás, MT5, portfólió-backtest)
**stratégia-független**. Egy stratégia a `strategy/` csomagon át csatlakozik, a
`Strategy` interfészen ([strategy/base.py](../../strategy/base.py)) keresztül. Ez a
skill a bevezetés lépéseit ÉS a nehezen tanult buktatókat foglalja össze — kövesd
végig, mielőtt "kész"-nek jelölsz egy új stratégiát.

## 1. A stratégia-modul (`strategy/<name>.py`)

Implementáld a `Strategy` interfészt. A **kötelező** (abstract) metódusok:

| Metódus | Feladat |
|---------|---------|
| `timeframes()` | mely időkeretek (adatletöltés + visszaszámlálók); konvenció: `[0]` = magasabb tf, `[1]` = alsó tf |
| `columns()` | a stratégia dashboard-oszlopai (marker/countdown is) |
| `warmup_bars(params, tf)` | indikátor-bemelegítés gyertyaszáma |
| `compute_display(md)` | a cellák MEGJELENÍTÉSHEZ (formálódó gyertyát is használhat) |
| `new_signal_state(symbol)` / `on_bar_close(state, md)` | **élő** jelzéslogika ZÁRT gyertyán → `(state, "BUY"/"SELL"/"NONE")` |
| `base_params(cfg)` / `param_space(cfg, base, method, max_trials)` | optimalizáláshoz |

**Backtest-hookok** (a `trading.backtest` motor ezeken kéri az indikátort, jelet és
pozíciótervet — szoros ciklusban, precomputed sorokon): `bt_indicators`, `bt_warmup`,
`bt_new_state`, `bt_on_high_close`, `bt_on_low_close`, `sl_tp_pips`, `bt_entry`.

Opcionális, de gyakran kell: `signal_warmup_bars`, `live_cells`, `visual_lookback_bars`
+ `visual_objects` (MT5-viz), `grade`, `magic`, `constraints_ok`.

Minta a bevált stratégiákból: [strategy/wpr_sma.py](../../strategy/wpr_sma.py) (klasszikus),
[strategy/ml_ai.py](../../strategy/ml_ai.py) (tanítható — `fit`).

## 2. Regisztráció — AUTOMATIKUS (nincs teendő)

A `strategy/__init__.py` **auto-felderíti** a `strategy/` csomag moduljait, és a `Strategy`
interfészt implementáló osztályt a `.name` attribútuma alapján magától regisztrálja.
**Új stratégia = csak egy új modul a `strategy/`-ben** — a vázat (`__init__.py`) NEM kell
szerkeszteni. A `name` osztály-attribútum legyen EGYEDI (ez a registry-kulcs). A be nem
tölthető modult a felderítés kihagyja (warning a logban).

## 3. Elérhetőség és konfiguráció

- **`available_strategies`** (config.json): a program által felkínált stratégiák
  ki-be kapcsolója — **térkép**: `{"wpr_sma": true, "ml_ai": false}`. A **⚙ Beállítás**
  ablak ezt írja, MINDIG a teljes készlettel (a kikapcsoltakat is), hogy a fájlból
  kiderüljön, mi LÉTEZIK. Oszlop-változás újraindítás után látszik. A régi LISTA alak
  (whitelist) is olvasható. Kihagyva = az összes regisztrált. **Egy új stratégia-modul,
  ami itt még nem szerepel, alapból ELÉRHETŐ** — nem tűnik el némán, kikapcsolni
  kifejezetten kell (`false`).
- **`strategy.name`** (config.json): az ALAPÉRTELMEZETT stratégia — ezt használja egy
  pár, ha nincs saját `pairs.<sym>.strategies` listája. Ha nincs az elérhetők között,
  az elsőre esik vissza.
- **`pairs.<sym>.strategies`**: a tényleges per-instrumentum engedélyezés (több is).

### ⚠ A KÉT LISTA nem ugyanaz — és a felület összemoshatja

`available_strategies` = **mit MUTAT** a felület · `pairs.<sym>.strategies` = **mit FUTTAT**
a motor. A 2.0 sor szándékosan az *available*-ből dolgozik (különben az oszlopok nem
állnának egy vonalban), a motor viszont metszetet képez:

```python
_active = _enabled & _intent      # a pár `strategies` listája ∩ a run_state szándék
```

**Minden felületi „fut-e?" kérdésnek EZT a képletet kell tükröznie**
(`gui.DashboardWindow._strategy_live`, `gui.OptimizerController._strategy_live`) — a
szándék önmagában nem elég, mert a `run_state` bejegyzés akkor is megmarad, ha közben
kikapcsoltad a stratégiát a páron. E nélkül a sor futónak mutat valamit, amivel a motor
soha nem fut (v1.98.0-ban javítva; őrzi: `tests/test_strategy_availability.py`). Egy új
stratégia bevezetésekor a `row_source.row_data` `enabled_of` seamje adja a különbséget
a sornak: a nem engedélyezett blokk **marad** (oszlop-egyvonal), csak a Play tétlenedik
— az OPT viszont használható, hisz épp optimalizálni akarod, mielőtt bekapcsolod.
- **Stratégia-config fájl**: `strategy/config/<name>.json` — `indicators`, `sltp`,
  `position_mgmt`, `quality`, és az optimalizáló-tér + `constraints`. A váz-config ezt
  betöltéskor beolvasztja (`apply_strategy_config`), mentéskor kiszűri
  (`main_config_view`) — a config.json nem szennyeződik stratégia-szekciókkal.

### ⚠ MI NEM A STRATÉGIÁÉ — a legfontosabb szabály

> **A stratégia egy BESZÁLLÁSI JELZŐ (+ előszűrő).** Ha egy paraméter arról szól,
> mi történik a **belépés UTÁN**, akkor **nem a stratégiáé**.

| tartozik | hova | példa |
|---|---|---|
| méretezés | kockázatkezelés (`core/risk_manager.py`, `trading.*`) | `account_risk_pct`, `max_open_slots` |
| kimenet-menedzsment | **kockázatcsökkentés** (`core/risk_reduction.py` + `core/rr_state.py`) | `breakeven_pct`, `trail_*`, részleges zárás, runner-stop, Fibo/Harmados, exit-jel, cost-cut |
| végrehajtási kapuk | keretrendszer (`core/execution_params.py`, `spread_gate`, `gates`) | `atr_period`, `max_spread_atr_ratio`, TF-együttállás |

A stratégia az SL/TP **távot** adja (`sl_tp_points` / `bt_entry`), a lotot és a
stop későbbi mozgatását **nem**.

**Miért szabály, és nem ajánlás.** Amíg a BE/trailing a stratégia paraméterei közt
élt: (a) minden stratégia configjában duplikálva volt; (b) egy páron futó két
stratégia MÁS értéket adhatott ugyanarra a pozíció-kezelésre; (c) a legtöbb
kockázatcsökkentő preseten **hatástalan** volt, mégis szerkeszthetőnek látszott
(Fibo/Harmados preseten soha nem futott). Ugyanez történt a `max_open_slots`-szal,
ami sokáig egy **elpazarolt optimalizálási tengely** volt. Lásd `strategy/base.py`.

## 4. Kritikus buktatók (ezeken bukott már el korábbi stratégia)

- **Live↔backtest paritás:** a belépés-szűrőt ÉS a méretezést a `bt_entry` adja — a
  **live_trader és a backtest UGYANEZT hívja**. Ha máshol szűrsz/méretezel, az élő
  eredmény eltér az optimalizálttól. A motor stratégia-független (nem ismer 'atr'-t).
- **M15 look-ahead / jövő-szivárgás:** a jel CSAK zárt gyertyákból számoljon. Az ml_ai
  portnál kiderült egy motor-szintű M15 look-ahead — ellenőrizd, hogy a magasabb tf
  aktuális sora ne tartalmazzon jövőbeli információt (train/test szeletelésnél is).
- **`signal_warmup_bars` mélység:** ha a jel állapotgépe a teljes előzménytől függ (egy
  régi extrém élesít egy "jó zónát"), a live/dashboard sekély warmupja ELTÉRHET a viz
  mély ablakától → kimaradó belépések. Add meg a mély `signal_warmup_bars`-t (a viz
  `visual_lookback_bars`-ával egyező ablakállapotért).
- **M1 belépő állapotgép:** ne "szomszédos gyertyás" átütést várj (a fokozatos áttörést
  kihagyja, a BUY ~sosem tüzel). Használj **felfegyverez → tüzel** mintát (mint az M15).
  Új stratégia után **ÚJRAOPTIMALIZÁLÁS** kell.
- **Költség-tudatos breakeven:** a BE-puffernek fedeznie kell a jutalék+swapot, különben
  nettó mínusz (kül. gold/risky). A backtest NEM modellez költséget — élőben ellenőrizd.
- **Deklaratív param-kényszerek:** a `constraints_ok`-ot vezéreld configból
  (`optimizer.constraints` + range gt/lt), hogy az optuna dinamikus tartománya 0
  elpazarolt trialt adjon. Biztonságos eval: [core/param_constraints.py](../../core/param_constraints.py).
- **Egyedi magic több stratégiánál:** a `magic(cfg)`-ban adj EGYEDI magicet (pl.
  `broker.magic + eltolás`), hogy a nyitott pozíciók broker-szinten szétválaszthatók
  legyenek a stratégiák között.
- **Restart-biztos állapot:** a Play/Stop és a megszakadt optimalizálás per-(symbol,
  strategy) perzisztál (run_state, unfinished_studies → auto-folytat). A study az optuna
  SQLite-ban van (folytatható); a "friss vs. folytatás" a done/stop marker.
- **Viz upsert:** a Python nem rajzol — fájlt ír, az MQL5 indikátor (TradeForgeViz)
  upsertel (nincs törlés). Új rajz-primitívnél MT5-recompile kell.

## 5. Kapcsolódó modulok (ha a stratégia használja)

- Kiszállási jel: [core/exit_signal.py](../../core/exit_signal.py) (RUNNER_EXIT — runner
  zárása indikátor-jelre).
- Pozícióépítés: [core/position_build.py](../../core/position_build.py) (piramidális add +
  átlagár-stop).
- Kockázatcsökkentés (Felező/Pajzs/Risky), piac-előszűrő (market_strategy) — per-pár.

## 6. Ellenőrzés (mielőtt "kész")

1. `python -m py_compile strategy/<name>.py` és a modul importja hibátlan.
2. `available_strategy_names(cfg)` / a per-pár választó felkínálja; oszlop megjelenik
   (újraindítás után).
3. Optimalizálás lefut (Opt gomb; tanítható stratégiánál = tanítás), 0 érvénytelen trial
   a constraints-tól; done-marker + "Utolsó opt" dátum megjelenik.
4. Backtest ↔ live paritás: ugyanaz a `bt_entry`-terv élőben és backtestben.
5. Egy portfólió-backtest a stratégiával; a P&L/R értelmes.
