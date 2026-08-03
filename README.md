# TradeForge

[![Licenc: GPL v3](https://img.shields.io/badge/Licenc-GPLv3-blue.svg)](LICENSE)

MetaTrader 5-höz kapcsolódó, Python-alapú kereskedési keretrendszer: élő motor,
tkinter dashboard, backtest, Optuna-alapú paraméter-optimalizálás és MT5-chart
vizualizáció — több instrumentumra és több stratégiára egyszerre.

> ⚠️ **Kockázati figyelmeztetés.** A program valós megbízásokat küldhet ki az MT5
> terminálon keresztül. Előbb **demo számlán** használd (`broker.is_demo: true`),
> és csak akkor válts élesre, ha megértetted, mit csinál. A szerzők nem vállalnak
> felelősséget a kereskedési veszteségekért.

---

## Tartalom

- [Előfeltételek](#előfeltételek)
- [Telepítés](#telepítés)
- [Konfiguráció](#konfiguráció)
- [Az MT5 terminál előkészítése](#az-mt5-terminál-előkészítése)
- [Futtatás](#futtatás)
- [Használati útmutató](#használati-útmutató)
- [MT5 indikátorok telepítése](#mt5-indikátorok-telepítése)
- [Frissítés Gitből](#frissítés-gitből)
- [Projektstruktúra](#projektstruktúra)
- [Tesztek](#tesztek)
- [Hibakeresés](#hibakeresés)
- [További dokumentáció](#további-dokumentáció)
- [Licenc](#licenc)

---

## Előfeltételek

| Előfeltétel | Megjegyzés |
|---|---|
| **Windows** | A `MetaTrader5` Python-csomag csak Windowson érhető el |
| **Python 3.10+** | A `tkinter` a hivatalos telepítővel együtt jön — külön nem kell |
| **MetaTrader 5 terminál** | Bármelyik bróker; a program a futó terminálhoz csatlakozik |
| **Git** (opcionális) | A kód letöltéséhez / frissítéséhez — <https://git-scm.com/download/win> |

> A program **nem** kötődik konkrét mappához: oda telepíted, ahová szeretnéd.
> Az alábbi parancsokban a `<projekt-mappa>` a saját választott könyvtárad.

---

## Telepítés

### 1. Kód letöltése

```bash
git clone https://github.com/tipcsy/TradeForge.git
```

Ez létrehoz egy `TradeForge` mappát az aktuális könyvtárban. Ha más nevet
szeretnél, add meg a végén (`git clone <url> <mappanév>`). Git nélkül a GitHubról
ZIP-ként is letölthető és kicsomagolható bárhová.

Ezután lépj a projekt mappájába — **minden további parancsot innen futtass**:

```bash
cd TradeForge
```

### 2. Virtuális környezet (ajánlott)

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

> PowerShellben/CMD-ben a fenti sor aktivál; Git Bashben: `source .venv/Scripts/activate`.

> A `.venv` a `.gitignore`-ban van, tehát nem kerül fel a repóra. Virtuális
> környezet nélkül is működik, ilyenkor a csomagok a rendszer-Pythonba kerülnek.

### 3. Csomagok telepítése

```bash
python -m pip install MetaTrader5 numpy pandas optuna pyarrow fastparquet
```

| Csomag | Mire kell |
|---|---|
| `MetaTrader5` | kommunikáció az MT5 terminállal (Windows-only) |
| `numpy`, `pandas` | számítások, idősorok |
| `optuna` | paraméter-optimalizálás |
| `pyarrow`, `fastparquet` | a historikus adatok Parquet-formátuma |

Opcionális csomagok, csak bizonyos funkciókhoz:

```bash
python -m pip install scikit-learn lightgbm pillow
```

| Csomag | Mihez |
|---|---|
| `scikit-learn`, `lightgbm` | az `ml_ai` stratégia tanítása/futtatása |
| `pillow` | felület-képernyőkép a `tools/ui_preview.py`-ban |

> **Miért `python -m pip` és nem `pip`?** Windowson a `pip` gyakran nincs a
> PATH-ban, a `python -m pip` viszont mindig a futtatott Python csomagkezelőjét
> hívja — így nem telepít véletlenül másik Python-környezetbe.

---

## Konfiguráció

A `config.json` **nincs a repóban** (jelszót tartalmaz, `.gitignore`-olt). Hozd
létre a mintából:

```bash
cp config.example.json config.json
```

Majd szerkeszd a `config.json`-t:

```json
"broker": {
  "name": "YourBroker",
  "server": "YourBroker-Demo",
  "login": 0,
  "password": "",
  "is_demo": true,
  "magic": 20260627
},
"mt5": {
  "path": "C:\\Path\\To\\MetaTrader5\\terminal64.exe",
  "portable": true
}
```

- **`broker`** — a saját MT5 belépési adataid. Kezdéshez `is_demo: true`.
- **`mt5.path`** — a `terminal64.exe` teljes útvonala a **saját gépeden**.
  Ha csak egy MT5 fut a gépen, elhagyható (a csomag megtalálja); több telepített
  terminál esetén **kötelező**, különben rossz terminálhoz csatlakozhat.
  A JSON-ban a fordított perjelet duplázni kell: `C:\\...\\terminal64.exe`.
- **`pairs`** — az instrumentumok. A minta kettőt tartalmaz (`EURUSD`, `GER40`);
  a többit a felületről is felveheted (a bróker adataival automatikusan kitölti).
  Egy pár be-/kikapcsolása: `"enabled": true|false`.

A többi mező jelentését a `config.example.json` `_comment` kulcsai írják le.

> **Soha ne commitold a saját `config.json`-odat.** A `.gitignore` kizárja a
> `config.json`-t és a `config*másolata*.json` / `config*copy*.json` mintákat is.

---

## Az MT5 terminál előkészítése

1. Indítsd el a **MetaTrader 5** terminált, és jelentkezz be a számlára.
2. Eszközök → Beállítások → Expert Advisors: **algoritmikus kereskedés engedélyezve**.
3. Hagyd a terminált **nyitva** — a Python háttérben ehhez csatlakozik.
4. A kereskedni kívánt instrumentumok legyenek láthatók a **Piac-figyelőben**.

---

## Futtatás

Minden parancs a projekt gyökeréből fut (ahol a `main.py` van):

| Parancs | Mit csinál |
|---|---|
| `python main.py download` | historikus adatok letöltése MT5-ből (`data/`) |
| `python main.py dashboard` | csak a felület, demo adatokkal — **MT5 nélkül is** |
| `python main.py live` | élő motor + dashboard |
| `python main.py backtest` | backtest az alapértelmezett paraméterekkel |
| `python main.py optimize` | paraméter-optimalizálás minden aktív párra |
| `python main.py optimize EURUSD GBPJPY` | optimalizálás csak a megadott párokra |

Argumentum nélkül (`python main.py`) kiírja ezt a listát.

**Első indításnál ajánlott sorrend:**

```bash
python main.py dashboard
```

(hogy lásd a felületet, még MT5 nélkül), majd

```bash
python main.py download
```

és végül

```bash
python main.py live
```

---

## Használati útmutató

### A dashboard fülei

| Fül | Mit mutat |
|---|---|
| **Live Dashboard** | instrumentumonként egy sor: BID/ASK, változás%, spread, pozíció, napi P&L, stratégia-cellák, optimalizálás-státusz és a vezérlőgombok |
| **Pozíciók** | a nyitott pozíciók részletei (stratégia, kiszállási terv, BE/trailing állapot, kézi vezérlés) |
| **Lezárt** | a lezárt kötések — köztük a mai nap |
| **Portfólió Backtest** | több instrumentum együttes visszatesztelése: kezdő tőke, időszak, kockázatcsökkentés, equity-görbe és eredménytáblázat |

### Vezérlés a Live Dashboardon

- **▶ / ■** — egy pár (illetve stratégia) indítása / leállítása. Az állapot a
  `config.json`-ba mentődik, tehát **újraindítás után is megmarad**.
  Nyitott pozíció melletti Stop esetén a pár *kivezetés* (CLOSING) állapotba kerül:
  új belépő nincs, de a meglévő pozíciót továbbra is menedzseli a motor.
- **Opt** — optimalizálás indítása az adott párra/stratégiára. Az `ml_ai`
  stratégiánál ez a gomb **tanítást** jelent, nem paraméter-keresést.
  A megszakadt optimalizálást a program induláskor felajánlja/folytatja.
- **BT** — backtest-ablak az adott párra: paraméter-szerkesztés, feltáró
  kapcsolók, előző/eredeti futás összevetése.
- **Instrumentum nevére kattintva** — paraméter-ablak: minősítés és metrikák, az
  optimalizálási találatok rangsor szerinti betöltése (▲/▼), óránkénti
  kereskedési kapcsoló, kézi paraméter-mentés.
- **Egyéb cellák kattinthatók**: a kapu-cellák a kapu-hatást (block / reduce /
  none), az „Együtt" cella a per-pár idősík-együttállást állítja.

### Tipikus munkamenet

1. `python main.py download` — előzmény letöltése (új instrumentumnál a program
   automatikusan is letölti a hiányzó előzményt).
2. **Opt** az adott páron → az optimalizált paraméterek a
   `data/optimized_params/<SYMBOL>.json`-ba kerülnek.
3. **BT** vagy Portfólió Backtest → a paraméterkészlet ellenőrzése.
4. `python main.py live` → **▶** a kiválasztott párokon.

> **Csak jelzés mód.** Páronként és stratégiánként beállítható, hogy a rendszer
> mindent kiszámoljon és naplózzon, de **megbízást ne küldjön ki**. Új stratégia
> élesítése előtt ez a legbiztonságosabb üzemmód.

### Naplók, kimenetek

| Hely | Tartalom |
|---|---|
| `data/tradeforge.log` | forgó futásnapló |
| `data/optimized_params/` | páronkénti optimalizált paraméterek + trials CSV |
| `data/execution_params/` | per-szimbólum végrehajtási beállítások |
| `data/backtest_results/` | backtest-kimenetek |
| `data/mt5_backtest/` | MT5-be visszajátszható backtest-CSV-k |

A `data/` mappa a `.gitignore`-ban van — a saját adataid nem kerülnek fel a repóra.

---

## MT5 indikátorok telepítése

A program a chart-vizualizációt fájlon keresztül adja át az MT5-nek (a Python nem
rajzol a chartra). A `.mq5` fájlokat a **saját MT5 adatmappádba** kell másolni:
az MT5-ben **Fájl → Adatmappa megnyitása**, majd az `MQL5` alkönyvtárba.

| Fájl | Hová | Mit csinál |
|---|---|---|
| `mt5/TradeForgeViz.mq5` | `MQL5\Indicators\` | élő jelzés-vizualizáció (belépők, SL/TP, riasztás-jelölők); ez rakja fel a másik kettőt is |
| `mt5/TradeForgeBands.mq5` | `MQL5\Indicators\` | állapot-sávok külön al-ablakban (M15 jelzési ablak, SMA-irány, piac-állapot, no-trade óra) |
| `mt5/TradeForgeWPR.mq5` | `MQL5\Indicators\` | Williams %R a stratégia matekjával, állítható szintekkel |
| `tools/BacktestTradesViewer.mq5` | `MQL5\Indicators\` | backtest-kötések kirajzolása |
| `tools/BacktestPnLViewer.mq5` | `MQL5\Indicators\` | ugyanaz + kötésenkénti P&L és R, összesítő panel |
| `tools/BacktestReplayer.mq5` | `MQL5\Experts\` | a backtest visszajátszása a Strategy Testerben |

Másolás után a **MetaEditorban fordítsd le** mindet (F7). A charton (**M1**) elég a
`TradeForgeViz`-t elhelyezni — a sávokat és a WPR-t az teszi fel a stratégia
paramétereivel. A vizualizáció páronként és stratégiánként a felületről kapcsolható be.

Részletek a backtest-visszajátszásról: [`tools/MT5_BACKTEST_README.md`](tools/MT5_BACKTEST_README.md).

---

## Frissítés Gitből

A projekt mappájából:

```bash
git pull
```

Ha a `git pull` a helyi módosítások miatt hibázik:

```bash
git status
```

```bash
git stash
```

```bash
git pull
```

```bash
git stash pop
```

| Parancs | Mit csinál |
|---|---|
| `git status` | mi módosult helyben |
| `git pull` | a legfrissebb verzió letöltése |
| `git log --oneline -10` | az utolsó 10 változás |
| `git stash` / `git stash pop` | helyi módosítások félretétele / visszahúzása |

> A `config.json` és a `data/` gitignore-olt, ezért a `git pull` **nem írja felül**
> a beállításaidat és az adataidat.

---

## Projektstruktúra

```
.
├── main.py                  ← belépési pont (download / dashboard / live / backtest / optimize)
├── version.py               ← alkalmazásnév és verzió (egy helyen)
├── config.example.json      ← config-minta (a valódi config.json gitignore-olt)
├── core/                    ← MT5-kapcsolat, indikátorok, kockázat, kapuk, végrehajtás
├── trading/                 ← élő motor és backtest
├── strategy/                ← stratégiák (wpr_sma, ml_ai) + saját configjaik és doksijuk
├── ml/                      ← Optuna-optimalizáló
├── dashboard/               ← tkinter felület
├── mt5/                     ← MQL5 indikátorok (vizualizáció)
├── tools/                   ← adatletöltő és karbantartó szkriptek, MQL5 backtest-eszközök
├── tests/                   ← tesztek (nincs pytest-függés)
├── build/                   ← PyInstaller EXE-build
└── data/                    ← adatok, naplók, eredmények (gitignore-olt, futáskor jön létre)
```

---

## Tesztek

```bash
python tests/run_all.py
```

Egy teszt önmagában is futtatható (`python tests/test_gates.py`), és részhalmaz is
szűrhető névtöredékkel (`python tests/run_all.py package`).

---

## Hibakeresés

| Hiba / tünet | Megoldás |
|---|---|
| `ModuleNotFoundError: MetaTrader5` | `python -m pip install MetaTrader5` (Windows kell hozzá) |
| `ModuleNotFoundError: optuna` / `pyarrow` | `python -m pip install optuna pyarrow fastparquet` |
| `pip` parancs nem található | Használd: `python -m pip install ...` |
| `FileNotFoundError: config.json` | Másold a `config.example.json`-t `config.json` néven, és a parancsot a projekt gyökeréből futtasd |
| MT5-kapcsolat sikertelen | Fut és be van jelentkezve a terminál? Jó az `mt5.path` a **saját** gépeden? Engedélyezett az algoritmikus kereskedés? |
| Nincs historikus adat | Előbb `python main.py download` |
| Nem látszik egy instrumentum | Add hozzá a Piac-figyelőhöz az MT5-ben, és `"enabled": true` a `config.json`-ban |
| Nincs vizualizáció a charton | Le van fordítva a `TradeForgeViz.mq5`, rajta van az **M1** charton, és be van kapcsolva a párnál? |

---

## További dokumentáció

- [`strategy/docs/wpr_sma.md`](strategy/docs/wpr_sma.md) — a WPR + SMA trendkövető stratégia
- [`strategy/docs/ml_ai.md`](strategy/docs/ml_ai.md) — a gépi tanulásos stratégia (jelenleg **nem** javasolt élesben)
- [`tools/MT5_BACKTEST_README.md`](tools/MT5_BACKTEST_README.md) — backtest visszajátszása MT5-ben
- [`build/README.md`](build/README.md) — EXE-build (PyInstaller)
- [`.claude/skills/new-strategy/SKILL.md`](.claude/skills/new-strategy/SKILL.md) — új stratégia bevezetésének checklistje

---

## Licenc

**GNU General Public License v3.0** — a teljes szöveg: [`LICENSE`](LICENSE).

```
TradeForge — MetaTrader 5 kereskedési keretrendszer
Copyright (C) 2026 tipcsy

Ez a program szabad szoftver: terjesztheted és/vagy módosíthatod a Free
Software Foundation által kiadott GNU General Public License 3. (vagy
bármely későbbi) változatának feltételei szerint.

A programot abban a reményben adjuk közre, hogy hasznos lesz, de MINDENFÉLE
GARANCIA NÉLKÜL; még az ELADHATÓSÁGRA vagy egy ADOTT CÉLRA VALÓ ALKALMASSÁGRA
vonatkozó garancia nélkül is. Részletekért lásd a GNU General Public
License-t.

A programmal együtt meg kellett kapnod a GNU General Public License egy
példányát; ha nem, lásd <https://www.gnu.org/licenses/>.
```

Röviden, mit jelent ez a gyakorlatban:

- **Szabadon** használhatod, tanulmányozhatod, módosíthatod és továbbadhatod.
- Ha **továbbadod** — akár módosítva, akár nem —, a **forráskódot is** át kell
  adnod, **ugyanezen** GPL-3.0 licenc alatt.
- Zárt forrású termékbe **nem** építhető be.
- **Nincs garancia.** Ezt a fenti kockázati figyelmeztetéssel együtt olvasd: a
  program valós pénzzel kereskedhet, és a felelősség a felhasználóé.
