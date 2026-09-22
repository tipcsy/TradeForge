---
name: new-strategy
description: Checklist és buktatók egy ÚJ kereskedési stratégia bevezetéséhez a TradeForge kódbázisba (strategies/ csomag). Használd, amikor új stratégiát adnál a motorhoz / dashboardhoz — "új stratégia", "add strategy", "introduce a strategy", "stratégia bevezetése", stratégia-modul, param_space, bt_entry.
---

# Új stratégia bevezetése (TradeForge)

A dashboard "váza" (megjelenítés, optimalizálás, futtatás, MT5, portfólió-backtest)
**stratégia-független**. Egy stratégia a `strategies/` csomagban él, és a `strategy/` KERETEN át csatlakozik, a
`Strategy` interfészen ([strategy/base.py](../../strategy/base.py)) keresztül. Ez a
skill a bevezetés lépéseit ÉS a nehezen tanult buktatókat foglalja össze — kövesd
végig, mielőtt "kész"-nek jelölsz egy új stratégiát.

> [!warning] KERET vs. TARTALOM (v3.29.0)
> Két csomag van, és a különbség kötelező:
>
> * **`strategy/`** — a KERET: `base` (az interfész), `visual` (rajz-primitívek),
>   `settings` (config-betöltés), `signal_journal`, `paths`, és a registry.
> * **`strategies/`** — a TARTALOM: a konkrét stratégiák + `config/` + `docs/`.
>
> Az irány EGYIRÁNYÚ: a stratégiád támaszkodhat a keretre, a keret viszont soha
> nem importálhat a `strategies/`-ből. Ezt teszt őrzi
> (`tests/test_strategy_layout.py`) — ha egy segédfüggvényed több stratégiának
> is kellene, az NEM a másik stratégiából importálandó, hanem a `core/`-ba való.
> (Pontosan ez történt a `resample_ohlc`-kal: az `ml_ai`-ban lakott, miközben
> három másik hívó importálta onnan.)
>
> Az útvonalakat a `strategy.paths` adja — ne számolj `__file__`-relatívan.

## 1. A stratégia-modul (`strategies/<name>.py`)

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
`bt_new_state`, `bt_on_high_close`, `bt_on_low_close`, `sl_tp_points`, `bt_entry`.

### ⚠ PONTOS ALÁÍRÁSOK ÉS ADATFORMÁK — ezt olvasd el, mielőtt kódot írsz

Egy korábbi vázlat (`bollinger_squeeze`) egy KITALÁLT interfészre íródott, mert ez a
lap csak a metódusNEVEKET sorolta fel. A 8 kötelezőből 6 hiányzott belőle, és olyat
használt, ami nem létezik. **Nincs `EntryPlan` osztály.** A hiteles forrás mindig
[strategy/base.py](../../strategy/base.py); ez itt a kivonat:

```python
timeframes()                     -> list[Timeframe]   # Timeframe(label, minutes)
columns()                        -> list[Column]      # MarkerColumn / StrategyColumn / CountdownColumn
warmup_bars(params, tf_label)    -> int
signal_warmup_bars(params, tf)   -> int                # mély, ha a jel állapotgép
compute_display(md)              -> dict[str, Cell]    # Cell(text, color_name)
new_signal_state(symbol)         -> Any
on_bar_close(state, md)          -> tuple[Any, str]    # str: "BUY" | "SELL" | "NONE"
base_params(cfg)                 -> dict
param_space(cfg, base, method, max_trials) -> list[dict]

bt_indicators(df_hi, df_lo, params) -> (df_hi2, df_lo2)   # OSZLOPOKKAL bővített másolat
bt_warmup(params, tf_label)      -> int
bt_new_state(symbol)             -> Any
bt_on_high_close(state, hi_row, params)              -> state   # hi_row: pandas Series
bt_on_low_close(state, prev_lo_row, lo_row, params)  -> str     # "BUY"|"SELL"|"NONE"
sl_tp_points(hi_row, params, point_size) -> (sl_points, tp_points) | None   # ⚠ PONTBAN
bt_entry(hi_row, params, point_size)     -> (sl_points, tp_points) | None   # + előszűrő
visual_objects(md)               -> list   # `strategy.visual` OBJEKTUMOK, nem dictek
```

> ⚠ **A cellák kulcsa a STÁDIUM, nem az OSZLOP** — és a `live_cells` sem
> kivétel. Jelölő-oszlopnál két külön névtér van, és összekeverni őket
> **néma** hiba:
>
> ```python
> def columns(self):                 # az OSZLOP kulcsa: "marks"
>     return [MarkerColumn("marks", self.name, stages=_STAGES)]
>
> def compute_display(self, md):     # a CELLÁK kulcsa: a stádiumok
>     return {"squeeze": Cell(...), "release": Cell(...), "entry": Cell(...)}
>     # ❌ NEM: {"marks": {...}} — egy szinttel mélyebben
> ```
>
> A motor `{k: (c.text, c.color) for k, c in cells.items()}`-szel bontja szét,
> tehát egy burkolótól a `c` szótár lesz és a `c.text` elszáll — a sor pedig
> ÖRÖKRE üres marad, ami pontosan úgy néz ki, mint egy stratégia, ami épp nem
> jelez. **Két stratégia is bedőlt neki** (`bollinger_squeeze`,
> `candle_level_break`); a `tests/test_strategy_cell_contract.py` óta a
> teszt-készlet elkapja.

**`MarketData` (`md`) mezői:** `symbol`, `params`, **`bars`**, `no_trade_hours`,
`show_signals`, `entry_gate`, és (újabban) `lot_of` (lot-számoló a jelölő
címkéjéhez), `exec_gates`, `on_entry_record` (a belépő-rekord gyűjtője → a
perzisztens `strategy.signal_journal`; a `visual_objects`-ban HÍVD MEG minden
belépőre), `gate_effects`, `gate_bands`. A hiteles lista mindig
[strategy/base.py](../../strategy/base.py) — a régi mezőkre épülő stratégia
változatlanul működik, az újak opcionálisak.

**A `params` szótárba a motor INJEKTÁLJA** a `symbol`-t és a `point_size`-t
(`run_pair` és a live_trader is: `{**params, "symbol": …, "point_size": …}`) —
per-pár viselkedéshez (pl. napszak-sáv páronként, gyorsítótár-kulcs) ezt
használd, ne találgasd a pár nevét.

**A params-értékek legyenek HASHELHETŐK** (szám, string, tuple). Az optimalizáló
a paraméter-készleteket halmazba teszi (dedup) — egy `dict`-értékű paraméter
(pl. egy per-pár szótár) `TypeError: unhashable`-lel bukik a
`test_strategy_param_space`-ben. Ha mégis kell összetett érték, a `base_params`
alakítsa tuple-lé — de per-pár beállításnak általában NEM a stratégia-paraméter a helye.

> ⚠ **`md.bars` egy SZÓTÁR**, nem DataFrame: `{"M15": df, "M1": df}` — a
> `timeframes()` címkéivel kulcsolva. `md.params` a **dict**, amiből dolgozol
> (nincs `self.cfg` dataclass: a paraméterek a `strategies/config/<name>.json`-ból
> jönnek, és a hívó adja át).

**A `bt_*` hookok EGY SORT kapnak** (pandas Series), nem DataFrame-et és nem indexet —
a motor előre kiszámolt oszlopokon fut, szoros ciklusban. Ami több sort igényel
(rolling, percentilis), azt a `bt_indicators`-ban kell OSZLOPPÁ tenni.

**Az SL/TP PONTBAN megy** (nem árban, nem pipben): a `point_size` a hívótól jön.

**A warmup GYERTYÁBAN megy, a motor a keret ELEJÉRŐL vágja** (`m15.iloc[bt_warmup:]`
— az indikátorok a TELJES kereten számolódnak, a szimuláció a vágás után indul).
Ha a szabályod NAPBAN gondolkodik (pl. „egy szint 365 napig él”), a bar-szám
instrumentum-függő: 96 M15/nap a 24 órás piacokon, ~56 egy index-CFD-n. Ha a
keret RÖVIDEBB a warmupnál, a motor üres keretet kap és **0 kötéssel, némán**
fut le — a `csilla` első paritás-tesztje pont ezen bukott. A backtest/teszt
keretének hosszabbnak kell lennie a warmupnál.

Opcionális, de gyakran kell: `signal_warmup_bars`, `live_cells`, `visual_lookback_bars`
+ `visual_objects` (MT5-viz), `grade`, `magic`, `constraints_ok`.

Minta a bevált stratégiákból: [strategies/wpr_sma.py](../../strategies/wpr_sma.py) (klasszikus),
[strategies/ml_ai.py](../../strategies/ml_ai.py) (tanítható — `fit`, saját
segédmodulokkal), [strategies/trend_pullback.py](../../strategies/trend_pullback.py)
(a jel egy vektorizált OSZLOP a `bt_indicators`-ban, az állapotgép csak a felfutó
élt nézi — a legegyszerűbb, paritás-barát minta),
[strategies/csilla.py](../../strategies/csilla.py) (a szabály KÜLÖN segédmodulban,
amit a kutató-labor is hív → paritás-teszttel; gyorsítótárazott mély kontextus;
per-pár napszak-sáv).

### Hova kerüljön a stratégia SAJÁT logikája — és a `.tfs` csomag

A `.tfs` csomagoló ([strategy/pack.py](../../strategy/pack.py)) a stratégia
modulját, a **`strategies.<x>`-ből importált saját segédmoduljait** (transzitíven,
AST-ből: `from strategies import x` / `from strategies.x import …`), a
`config/<név>.json`-t és a `docs/<név>.md` + `.en.md` leírást viszi magával.
**A `core/`-t NEM.** Tehát:

* ami a stratégia SAJÁT szabálya (még ha a kutató-labor is használja), az
  `strategies/<név>_<valami>.py` segédmodul legyen (mint `ml_features`,
  `csilla_rules`) — így a csomag hordozza;
* a `core/`-ba csak az való, amit a KERET nyújt minden stratégiának
  (`resample_ohlc`, kapuk, kockázatkezelés). Egy `core/`-ra épített stratégia
  máshol telepítve importhibával esik szét;
* egy másik STRATÉGIÁT importálni tilos (`test_strategy_layout`), és a
  csomagoló szándékosan ki is hagyja.

Csomagolás: `strategy.pack.build("<név>")` → `<név>-<verzió>.tfs`; telepítés
`strategy.pack.install(path)` (zip-slip, fájl-fehérlista, sha256 — kétlépcsős).
Ellenőrizd a manifest `helpers` listáját: ha a segédmodulod nincs benne, az
import-alak nem az, amit a csomagoló felismer.

### A stratégia-szerződés (`api` + ujjlenyomat, v3.30.0)

A `Strategy.api` (alap: `STRATEGY_API`) mondja meg, melyik szerződésre íródott
a stratégia; a program betöltéskor összeveti a sajátjával, és eltérésnél
megnevezi, melyik oldalt kell frissíteni. A `tests/test_strategy_contract.py`
az interfész UJJLENYOMATÁT is őrzi: ha egy hook aláírása változik, a teszt
bukik, és dönteni kell — törő (`STRATEGY_API + 1`) vagy sem (ujjlenyomat
frissítése). Új hook alapértelmezett megvalósítással NEM törő. Új stratégia
írásakor ehhez nem kell nyúlni; ha a KERETEN változtatsz közben, igen.

### Napi feladatok — a `daily_jobs()` hook (v3.87.1)

**Mi ez.** Ha a stratégiának van olyan munkája, amit **naponta egyszer, a
kereskedéstől függetlenül** el kell végezni — forward-napló frissítése, egy
saját állapotfájl újraszámolása, egy modell heti/napi újratanítás-előkészítése
—, azt **a stratégia deklarálja**, és **a keret futtatja**: naponta egyszer a
beállított helyi idő után, **alprocesszben** (`main.py job <név>`), állapottal
(`data/daily_jobs.json`), naplóval (`data/daily_jobs/<név>.log`), gombbal a
Karmester fülön („Napi feladatok"), `jobs [run <név>]` paranccsal (konzol +
Telegram) és egy szakasszal az esti riportban. A config csak az eltérést
rögzíti: `daily_jobs.<név>.enabled` / `.time`.

**Miért így, és nem a keretbe drótozva.** A `csilla` forward-tesztje (2026-09-22)
először a keretbe került: a `core/daily_jobs.py` ismerte a nevét, a `main.py`
importálta a szkriptjét. A felhasználó kérdése — „mi van, ha letörlöm a csilla
stratégiát?" — mutatta meg a hibát: a feladat minden este elbukott volna, a
felületen egy halott doboz maradt volna. **A stratégia hordozható (`.tfs`): ami
hozzá tartozik, azt ő deklarálja, és vele együtt tűnik el.** Ugyanaz a szabály,
mint a segédmoduloknál: a keret a `strategies/`-ből nem importál, nevet nem
ismer — a registry-n át, dinamikusan kérdez (`tests/test_strategy_layout.py`
őrzi: a `main.py` sem importálhat a tartalomból, a `core/daily_jobs.py` kódjában
nem lehet stratégia-név).

**Hogyan.** A hook a `Strategy`-n opcionális (alap: `[]`), tehát egy stratégia,
aminek nincs ilyen munkája, nem is tud róla. Ha van:

```python
# strategies/<név>.py
def daily_jobs(self) -> list:
    from strategies import <név>_forward as _fw     # ← ITT importáld: a .tfs így viszi
    return [_fw.job_spec()]

# strategies/<név>_forward.py  (a stratégia SAJÁT segédmodulja)
def job_spec() -> dict:
    from core.i18n import t as _t
    return dict(
        name="<név>_forward",          # kisbetű/szám/aláhúzás; config-kulcs és fájlnév is
        time="22:30",                  # alap indítás, helyi idő (a config felülírhatja)
        label=_t("<név>.forward.head"),  # a felületen megjelenő cím
        run=lambda argv: main(argv or ["--all"]),   # az alprocesszben fut, kilépési kódot ad
        status_lines=status_lines,     # az állás sorai — a futás által ÍRT fájlból, újraszámolás nélkül
    )
```

Szabályok, amiken már elbukott valami:
* **`run` az alprocesszben fut** — ne a motor szálán csinálj perces munkát; a
  kimenete a naplóba megy (`print` jó), a kilépési kód (0 = rendben) a
  felületen látszik.
* **`status_lines` NE számoljon újra**: a `run` írjon egy kis állapotfájlt (pl.
  `data/<név>/status.json`), a `status_lines` azt olvassa. A „nincs fájl" ≠ „0
  eredmény" — mondd ki külön (`forward.no_status` minta).
* **Egy feladat egyszer egy napon**, akkor is, ha elbukott — másnap újra. Ha a
  feladatnak MT5 kell (gyertya-pótlás), az EXE-s gépen a terminál fusson.
* **A `.tfs` manifestje szabványos alakban viszi** (`daily_jobs: [{name, time,
  label}]` — adat, nem kód), és a telepítő a megerősítés ELŐTT kiírja: aki
  telepít, tudja, mi fog naponta futni. A csomagoló ellenőrzi a deklarációt
  (érvényes név, egyediség, hívható `run`, `HH:MM`) — hibás feladattal nem
  csomagol (`strategy.pack.declared_jobs`).
* Nyelvi kulcsok: a feladat szövegei (`<név>.forward.*`) egyelőre a keret
  katalógusába (`lang/hu.json` + `en.json`) kerülnek, mint a `stage.<x>_*`
  kulcsok — ismert engedmény; hiányuknál a kulcs jelenik meg, nem hiba.

Minta: `strategies/csilla.py` (`daily_jobs`) + `strategies/csilla_forward.py`
(`job_spec`, `status_lines`, `write_status`); teszt: `tests/test_daily_jobs.py`
(a hamis forrás + a valódi registry), `tests/test_strategy_pack.py` 1b.

## 2. Regisztráció — AUTOMATIKUS (nincs teendő)

A `strategy/__init__.py` **auto-felderíti** a `strategies/` csomag moduljait, és a `Strategy`
interfészt implementáló osztályt a `.name` attribútuma alapján magától regisztrálja.
**Új stratégia = csak egy új modul a `strategies/`-ben** — a vázat (`__init__.py`) NEM kell
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
  ⚠ **Ettől függetlenül a `tests/test_strategy_availability.py` megköveteli, hogy
  MINDEN regisztrált stratégia szerepeljen** a `config.json` ÉS a
  `config.example.json` térképében — az új modul után mindkettőbe vedd fel
  (`"<név>": true/false`), különben a teszt bukik.
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
- **Stratégia-config fájl**: `strategies/config/<name>.json` — `indicators`, `sltp`,
  `position_mgmt`, `quality`, az optimalizáló-tér (`optimizer`: a tartományok
  KÖZVETLENÜL alatta, nem `ranges` alkulcsban) + `constraints`, és **`param_meta`**
  (a Paraméterek ablak: `categories` + `params.<kulcs>.{recompute: signal|exec,
  category, comment}`). A váz-config ezt betöltéskor beolvasztja
  (`apply_strategy_config`), mentéskor kiszűri (`main_config_view`) — a config.json
  nem szennyeződik stratégia-szekciókkal. Saját szekció (pl. egy saját szűrő küszöbe) is
  lehet, a `base_params` olvassa ki — de ELŐBB nézd meg, nincs-e rá keret-funkció
  (órák, kapuk, kockázatcsökkentés: lásd a „mi NEM a stratégiáé” táblát). ⚠ A JSON-ban a magyar idézőjel `„…”` legyen
  (a `"` lezárja a stringet — egyszer már elsült).
- **Paraméter-NEVEK**: kövesd a meglévő konvenciót — `sl_atr_mult`, `tp_rr_ratio`,
  `atr_ref_period` stb. (lásd `trend_pullback.json`). A keret több helyen NÉV
  szerint ismeri fel őket (a `config_check` `tp_preset_conflict`-je a
  `tp_rr_ratio`-t nézi, a Paraméterek ablak kategóriái, a migrációk). Egy saját
  név (`stop_atr`) működik, de láthatatlan ezeknek az őröknek.
- **Kategorikus paraméter** (pl. „melyik időkeret szintjeit": `level_kinds =
  "D1+W1"`): stringként mehet a configba és a params-ba (hashelhető, a
  Paraméterek ablak szerkeszthetően mutatja), de az optimalizáló rácsa CSAK
  numerikus tartományt ismer — az ilyet ne tedd az `optimizer` szekcióba, a
  mért/alap értéket viszont írd a `_comment`-be és a `param_meta` megjegyzésbe.
- **Leírás**: `strategies/docs/<name>.md` (magyar, KÖTELEZŐ — teszt őrzi:
  `s.doc_path().exists()`, > 200 karakter) és `<name>.en.md` (angol, a csomag
  viszi). A Paraméterek ablak és a `.tfs` innen olvassa.
- **i18n**: a stádium-feliratokat `_t("stage.<rövidnév>_…")` kulccsal add
  (`from core.i18n import t as _t`), és a kulcsokat vedd fel a `lang/hu.json` ÉS
  `lang/en.json` fájlba (ábécérendben tartva). Hiányzó kulcsnál a felirat maga a
  kulcs lesz — a `tests/test_i18n.py` és a saját teszted fogja meg.
  A `param_meta.categories` minden ÚJ kategóriájához is kell felirat:
  `param_cat.<kategória>` mindkét nyelvi fájlban (`tests/test_param_categories.py`
  őrzi — a `csilla` `levels`/`entry_m1` kategóriája ezen bukott először).

### ⚠ MI NEM A STRATÉGIÁÉ — a legfontosabb szabály

> **A stratégia egy BESZÁLLÁSI JELZŐ (+ előszűrő).** Ha egy paraméter arról szól,
> mi történik a **belépés UTÁN**, akkor **nem a stratégiáé**.

| tartozik | hova | példa |
|---|---|---|
| méretezés | kockázatkezelés (`core/risk_manager.py`, `trading.*`) | `account_risk_pct`, `max_open_slots` |
| kimenet-menedzsment | **kockázatcsökkentés** (`core/risk_reduction.py` + `core/rr_state.py`) | `breakeven_pct`, `trail_*`, részleges zárás, runner-stop, Fibo/Harmados, exit-jel, cost-cut |
| végrehajtási kapuk | keretrendszer (`core/execution_params.py`, `spread_gate`, `gates`) | `atr_period`, `max_spread_atr_ratio`, TF-együttállás |
| **napszak / kereskedési órák** | keretrendszer, STRATÉGIA-hatókörű (`core/params_store.trade_hours` → `data/optimized_params/<strat>/<PÁR>_hours.json`, a dashboard óra-választója; a motor `allowed_hours`-a és a backtest is ezt használja) | „csak 8–11 között” — NEM egy saját `session_hours` paraméter (a `csilla` első változata ezt tette: olvashatatlan tuple a Paraméterek ablakban, és a keret funkciójának duplikátuma) |

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
- **A kilépést a PÁR rr-specje adja, és az LAPOS szótár:** `run_pair(..., rr=spec)` a
  `core.rr_state.spec_for` alakját várja — `{**risk_reduction.default_config(),
  "preset": …, "breakeven_r": …, "trail_activation_atr": …, …}` EGY szinten. Egy
  beágyazott `{"preset", "cfg"}` alak némán az alapértékeket adja (BE a célár
  felénél = távoli célárnál soha). A `breakeven_r` (> 0) R-alapú BE-t ad, amit a
  hosszú célár nem kapcsol ki; a trailing viszont `entry_atr`-szorzó (a
  VÉGREHAJTÁSI `atr_period` ATR-je a belépő M15-gyertyáján), nem R — egy
  R-ben definiált kutató-kilépés csak KÖZELÍTŐLEG vihető át, és a motorban
  NINCS idő-kilépés (max tartás), csak `cost_cut` (ha még veszteséges).
  Paritást tehát a BELÉPŐKRE bizonyíts; a kilépés-eltérést mérd és írd le.
- **A paritás-teszt ne legyen üres** (`vacuous-parity-tests`): a kutató-labor és a
  motor-út (`bt_indicators` → jel-oszlop) UGYANAZON az adaton, belépő-szám > 0
  kötelező, időpont + irány + SL egyezés — ÉS egy `run_pair`, ami kötést ad. A
  `csilla` első futása 3 valódi hibát fogott (ablak-szél, üres keret a warmup
  miatt, rossz rr-alak) — egy 0-vs-0 összevetés mind a hármat elnyelte volna.
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

## 5b. Élesítés a dashboardon — amin a `csilla` bevezetése elakadt (2026-09-15)

- **A futó TradeForge ZÁROLJA a `config.json`-t** (Windows: `WinError 5` a
  temp→replace-nél), és a saját memóriabeli cfg-jét írja vissza a következő
  Play/Stop-nál — egy kézi szerkesztés tehát vagy nem ment el, vagy némán
  felülíródik. Sorrend: **leállítás → szerkesztés (`strategy.settings.
  write_config_file`) → indítás.** Előtte mentsd le a configot (nincs
  verziókövetve).
- **Kód-változás után újraindítás kell**: a stratégia-modulok indításkor
  töltődnek; a viz-/jelzés-logika módosítása a futó példányban nem látszik.
- **Csak-jelzés mód** (`core.trade_mode.set_mode` → `pairs.<sym>.strategy_mode
  [<strat>] = "signal"`) + `run_state` `live` (`core.run_state.set_state`) + a
  pár `strategies` listája — ez a három együtt kell egy papírkereskedéshez. A
  napló induláskor kiírja: „🔔 CSAK JELZÉS mód (NEM köt): …" — ellenőrizd.
- **Az `untuned_pair` config-lelet VÁRHATÓ** egy olyan stratégiánál, amelynek
  az alapértékei MAGA a mért szabály (nincs és nem is kell optimalizált
  készlet) — nem hiba, de a napló minden indításkor szólni fog.
- **A viz élő charton legyen SZŰK.** A teljes ablakon áthúzott szint-/sáv-
  vonalak (amik egy egyhetes labor-nézőben hasznosak) élő charton szemét — a
  felhasználó azonnal szólt. Csak azt rajzold, amit a döntés használ, és ott,
  ahol történik (a törésnél egy rövid szakasz, nem az élő szint). A TradeForgeViz
  **nem töröl** objektumot: viz-logika módosítása után `python tools/viz_clear.py
  <SYM>` minden érintett páron, különben a régi rajz ott marad.
- **Két mérőhely, két szám.** A keretben futó stratégia eredménye ELTÉR a
  kutató-labor számától akkor is, ha a belépők bitre azonosak: a motor kapui
  (TF-együttállás, spread, volatilitás), a több slot, és az ATR-alapú kilépés
  mást ad, mint a labor R-alapú, egy-pozíciós, idő-korlátos szimulációja.
  Dokumentáld mindkettőt, és NE hangold egyiket a másikhoz — a labor a rögzített
  szabály, a keret az „élesben így menne" kérdés.
- **Ha egy pár-szintű beállítást a stratégia-paraméterek közé tennél** (napszak,
  órák, per-pár küszöb), állj meg: a Paraméterek ablak MINDEN paramétert mutat,
  és a keretnek szinte biztosan van rá funkciója (órák: `params_store.
  trade_hours`; kapuk: `gates/`; kilépés: `risk_reduction`).

## 6. Ellenőrzés (mielőtt "kész")

1. `python -m py_compile strategies/<name>.py` és a modul importja hibátlan.
2. `available_strategy_names(cfg)` / a per-pár választó felkínálja; oszlop megjelenik
   (újraindítás után). A `config.json` + `config.example.json`
   `available_strategies` térképében szerepel.
2b. A stratégia-tesztek zöldek: `test_strategy_cell_contract`, `test_strategy_contract`,
   `test_strategy_param_space`, `test_strategy_layout`, `test_strategy_availability`,
   `test_i18n`, `test_strategy_pack` — és a saját `tests/test_<name>*.py` (minta:
   `tests/test_bollinger_squeeze.py`, `tests/test_csilla_parity.py`).
2c. `strategy.pack.build("<név>")` lefut, és a manifest `helpers` listája
   tartalmazza a segédmoduljaidat.
2d. Ha van napi feladatod: a manifest `daily_jobs` listája tartalmazza (név,
   idő, cím); `python main.py job` felsorolja; `jobs` parancs az állását adja;
   a Karmester fülön megjelenik a doboza; `python main.py job <név>` kód 0-val
   fut le; `test_daily_jobs` + `test_strategy_pack` zöld.
3. Optimalizálás lefut (Opt gomb; tanítható stratégiánál = tanítás), 0 érvénytelen trial
   a constraints-tól; done-marker + "Utolsó opt" dátum megjelenik.
4. Backtest ↔ live paritás: ugyanaz a `bt_entry`-terv élőben és backtestben.
5. Egy portfólió-backtest a stratégiával; a P&L/R értelmes.
6. Élesítés: `available_strategies` + a pár `strategies` listája + `strategy_mode`
   (`signal` a papírteszthez) + `run_state`; a kapu-listák (`tf_align.gate`), a
   stratégia-hatókörű órák, és a pár rr-specje beállítva; a napló induláskor
   megnevezi a stratégiát a csak-jelzés listában; a chart nem szemetes.
