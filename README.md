# TradeForge

[![tests](https://github.com/tipcsy/TradeForge/actions/workflows/tests.yml/badge.svg)](https://github.com/tipcsy/TradeForge/actions/workflows/tests.yml)
[![Licenc: GPL v3](https://img.shields.io/badge/Licenc-GPLv3-blue.svg)](LICENSE)

MetaTrader 5-höz kapcsolódó, Python-alapú kereskedési keretrendszer: élő motor,
tkinter dashboard, backtest, Optuna-alapú paraméter-optimalizálás és MT5-chart
vizualizáció — több instrumentumra és több stratégiára egyszerre.

> ⚠️ **Kockázati figyelmeztetés.** A program valós megbízásokat küldhet ki az MT5
> terminálon keresztül. Előbb **demo számlán** használd (`broker.is_demo: true`),
> és csak akkor válts élesre, ha megértetted, mit csinál. A szerzők nem vállalnak
> felelősséget a kereskedési veszteségekért.

> ⚠️ **Risk warning.** This program can send **real orders** through the MT5
> terminal. Use it on a **demo account** first (`broker.is_demo: true`), and only
> switch to live once you understand what it does. The authors accept no
> liability for trading losses.

🇬🇧 **English description:** scroll to the bottom of this page — [English version](#english).

---

## Tartalom

- [Licencelés és regisztráció](#licencelés-és-regisztráció)
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
- [Dolgozzunk együtt!](#dolgozzunk-együtt)
- [További dokumentáció](#további-dokumentáció)
- [Licenc](#licenc)
- [English version](#english)

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
python -m pip install -r requirements.txt
```

Ez mindent feltesz — az alap- és az opcionális csomagokat is. Ha csak a
minimumot szeretnéd:

```bash
python -m pip install MetaTrader5 numpy pandas optuna pyarrow fastparquet cryptography
```

| Csomag | Mire kell |
|---|---|
| `MetaTrader5` | kommunikáció az MT5 terminállal (Windows-only) |
| `numpy`, `pandas` | számítások, idősorok |
| `optuna` | paraméter-optimalizálás |
| `pyarrow`, `fastparquet` | a historikus adatok Parquet-formátuma |
| `cryptography` | a licencszerver válaszának aláírás-ellenőrzése |

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

## Licencelés és regisztráció

A TradeForge **ingyenesen használható, de regisztrációhoz kötött.** A regisztráció
egy e-mail cím és egy jelszó — nincs bankkártya, nincs megerősítő levél, nincs
próbaidő-számláló.

> A regisztráció **csak az élő kereskedéshez** kell. A backtest, az optimalizálás
> és az adatletöltés licenc nélkül is fut: azok nem nyúlnak a brókerszámlához.

### A regisztráció lépésről lépésre

1. **Nyisd meg a portált:** <https://licence.tipcsy.hu>
2. **Regisztráció** — e-mail cím + jelszó. Ennyi; a fiók azonnal használható.
3. **Indítsd el a programot:** `python main.py live`. Az első élő indításkor a
   TradeForge feldob egy belépő-ablakot — ugyanaz az e-mail cím és jelszó, amivel
   a portálra regisztráltál.
4. **Kész.** A program elmenti a belépőt (tokent), és **többé nem kérdez**. A
   jelszó **sehol nem tárolódik**: a belépéskor tokenre váltjuk, és ott véget ér.

Ha elfelejtetted a jelszavad, a portál belépő képernyőjén van **„Elfelejtettem a
jelszavam"** — a visszaállító link 30 percig él, és egyszer használható.

### Mi történik minden induláskor

A program a mentett tokennel és az **MT5-ből olvasott brókerszámla-számmal**
megkérdezi a szervert, hogy futhat-e:

1. a számlaszám **már be van kötve** a licencedhez → indul;
2. nincs bekötve, de **van szabad számla-slot** → beköti és indul;
3. nincs szabad slot → nem indul, és megmondja, hány slotod van használatban.

Egy licenchez tehát több brókerszámla tartozhat — a slotok számát a portálon
látod. A tokenek gépenként külön élnek (a címke a **gép neve**), és a portálról
bármikor visszavonhatók: a visszavont gép a következő indításnál újra belépést kér.

### Ha a licencszerver nem érhető el

Ilyenkor a program a **legutóbbi, sikeres ellenőrzés** alapján még elindul, egy
**72 órás türelmi időn** belül. Ez nem hátsó ajtó: a szerver a válaszát Ed25519
aláírással látja el, a TradeForge-ba a publikus kulcs van beépítve, tehát egy
kézzel átírt gyorsítótár érvénytelen.

A türelmi idő **látszik a felületen** is: a fejlécben, a licenc e-mail mellett
(*„nincs licencszerver: még 51 óra"*) — sárgán, 12 óra alatt pirosan. Ugyanitt
jelenik meg a közelgő lejárat is (*„licenc lejár: 12 nap"*), 30 nap alatt.

### Beállítás a `config.json`-ban

Alapból nincs vele dolgod; a minta már tartalmazza:

```json
"licence": {
  "api_url": "https://licence.tipcsy.hu/api/v1"
}
```

> A licenc **nem ugyanaz, mint a forráskód licence.** A program **GPL-3.0** alatt
> áll (lásd lent a [Licenc](#licenc) szakaszt) — a regisztráció a *szolgáltatás*
> (licencszerver, számla-slotok) használatához kell, nem a kód olvasásához vagy
> módosításához.

---

## Futtatás

Minden parancs a projekt gyökeréből fut (ahol a `main.py` van):

| Parancs | Mit csinál |
|---|---|
| `python main.py download` | historikus adatok letöltése MT5-ből (`data/`) |
| `python main.py dashboard` | csak a felület, demo adatokkal — **MT5 nélkül is** |
| `python main.py live` | élő motor + dashboard |
| `python main.py console` | élő motor **felület nélkül** + parancssor (gyenge gép, VM, SSH) |
| `python main.py console --tui` | ugyanaz, **élő táblázattal** (a `rich` csomag kell hozzá) |
| `python main.py backtest` | backtest az alapértelmezett paraméterekkel |
| `python main.py optimize` | optimalizálás minden aktív párra, páronként a saját stratégiáival |
| `python main.py optimize EURUSD GBPJPY` | optimalizálás csak a megadott párokra |
| `python main.py optimize Ger40 --strategy ml_ai` | egy pár, egy stratégia (tanítható stratégiánál = tanítás) |
| `python main.py optimize -s wpr_sma,ml_ai` | minden pár, csak a felsorolt stratégiák |

### Felület nélküli futás (`console`)

Ugyanaz a motor, csak dashboard helyett egy parancssorral (`help` felsorolja a
parancsokat: `pairs`, `pos`, `close`, `play`, `stop`, `balance`, `state`).

Két dolgot érdemes tudni:

* **Egy számlán egy motor.** A program `data/live_<számlaszám>.lock` fájllal
  zárja ki, hogy két példány kereskedjen ugyanazon a számlán — a licenc ezt
  **nem** akadályozná meg, mert az a számlához szól, nem a géphez. Más számlán
  párhuzamosan futhat.
* **A licenc-belépés nem itt történik.** A konzolos mód szándékosan nem nyit
  belépő-ablakot (SSH-n nem is látszana): jelentkezz be egyszer a grafikus
  felületen, és másold a `data/licence_token.json`-t a másik gépre.

### Telegram-értesítés

A motor szólni tud a kötésekről, a pozíció-eseményekről és a bajról. A
`config.json` → `notify` blokk kapcsolja be (a `config.example.json`
dokumentálja); alapból **ki van kapcsolva**.

| esemény | mikor megy |
|---|---|
| kötés nyílt / lezárult, stop mozdult, kockázatmentesítés | ha a pár+stratégia **kötés-értesítése** be van kapcsolva (alap: BE) |
| jelzés (csak jelzés módban) | ha a **jelzés-értesítés** be van kapcsolva (alap: **KI** — abból sok van) |
| a motor nem halad · MT5 elveszett · napi veszteséglimit · lejáró licenc | **mindig**, naponta legfeljebb egyszer |
| indulás, ütemezett életjel | a `heartbeat_times` szerint (üres lista = nincs) |
| **napi zárás-összefoglaló** | a `daily_summary_time` szerint (üres = nincs) |

**Csendes órák** (`quiet_hours`, **helyi** idő szerint): a jelzések elvesznek —
alvás közben úgysem lépnél be —, a kötések viszont reggel **összesítve**
megjönnek. A kritikus hiba a csendet is átüti.

A **napi zárás** ugyanazt tartalmazza, amit a `/today` parancs: nyitások,
zárások, nettó eredmény, a **legjobb és a legrosszabb** kötés, hány jelzés volt
kötés nélkül, és mi maradt nyitva. ⚠ Egy nettó szám elrejtené, hogy egyetlen
nagy vesztes vitte-e el a napot, vagy sok apró. Ha az időpont a csendes órába
esik, az összefoglaló reggel jön meg.

⚠ **Az értesítés sosem állítja meg a kereskedést.** Az események egy sorba
kerülnek, és külön szál küldi őket; ha a Telegram elérhetetlen, a motor köre
zavartalanul megy tovább.

**Melyik párról szóljon:** az instrumentum nevére kattintva, a stratégia-
táblázatban két új sor — *Telegram: kötés* és *Telegram: jelzés* —, ugyanott,
ahol a vizualizáció és a kötés-mód. A „minden instrumentumra" pipa ezekre is
érvényes.

⚠ A `token` birtokosa **olvassa a botodnak küldött üzeneteket** — a
`config.json` `.gitignore`-olt, oda kerülhet, de máshova ne másold.

**Parancsok a botnak** (a válasz a beállított nyelven jön):

| parancs | mit ad |
|---|---|
| `/help` | a parancsok listája |
| `/balance` | egyenleg és a mai eredmény |
| `/pos` | nyitott pozíciók |
| `/today` | a mai kötések, eredmény, és hány jelzés volt |
| `/state` | mely stratégiák futnak melyik páron + a motor állapota |
| `/heart` | életjel — minden rendben van-e |
| `/play <pár>` · `/stop <pár>` | stratégia indítása/leállítása |

#### Jelzésre kötés gombbal (`answer_trading`)

⚠ **Alapból ki van kapcsolva**, mert ezzel egy chatüzenetből valódi pozíció
lesz. Bekapcsolva a **`signal` módú** pár+stratégia jelzéséhez a bot IGEN/NEM
gombot küld, és az IGEN megnyitja a pozíciót.

A biztosítékok:

* **csak `signal` módú** pár+stratégia kap gombot (a `live` módúaknál a motor
  amúgy is köt);
* az ajánlat **a jel-gyertya feléig él** (M15 → 7,5 perc, H1 → 30 perc,
  M1 → 1 perc), utána a gomb megmondja, hogy elkésett;
* **egyszer használható** — a kétszer megnyomott IGEN egy pozíciót nyit;
* a **kapuk nem kerülhetők meg**: nyitott pozíció, slot, napi veszteséglimit,
  fedezet — ugyanaz a végrehajtási út, mint a motor saját belépőjénél, és
  minden elutasítás megmondja az okát;
* ha az ár a terv óta **0,25 R-nél többet mozdult**, az IGEN **nem köt**:
  megmondja, mennyit mozdult, és újra rákérdez. A megerősítés után a
  **stop/célár távolsága marad**, csak a szint csúszik a mostani árhoz.

A **parancs-menüt** a program állítja be minden induláskor (`setMyCommands`),
a kódban lévő listából és a `/help` leírásaiból — a @BotFather-ben nem kell
kézzel karbantartani, és így nem is tud elavulni. Magyar és angol Telegram-
felülethez külön menü megy ki.

⚠ A bot **kizárólag** a configban felsorolt `chat_ids`-tól fogad parancsot;
minden más üzenetre **némán** hallgat. A `/stop` nyitott pozíciónál
**gombbal kérdez rá** (a gomb 10 perc után lejár), és a megerősítésig semmi nem
történik. Pozíciót zárni és a motort leállítani távolról **nem lehet** — a
parancslista szándékosan engedélyező, nem tiltó.

**Beüzemelés:** hozz létre egy botot a @BotFather `/newbot` parancsával, a
tokent írd a `config.json`-ba, majd:

```bash
python main.py notify-test
```

Ez ellenőrzi a tokent, **megkeresi a `chat_id`-dat** (abból, aki már írt a
botnak), felajánlja a mentést, és küld egy próbaüzenetet. ⚠ Előbb nyisd meg a
botodat Telegramban és nyomj **Startot** — a bot nem tud írni annak, aki nem
kezdeményezett vele beszélgetést.

**Két nézet, egy parancskészlet.** A `--tui` egy magától frissülő táblázatot ad
(instrumentumok, futó stratégiák, nyitott pozíciók, a motor életjele) a
terminál saját képernyő-pufferében; billentyűleütésre a kép megáll, és
ugyanazok a parancsok mennek, mint a parancssoros módban. Ami nem fér ki a
képernyőre, azt levágja — és kiírja, mennyi maradt le. A `rich` **nem kötelező**: nélküle a parancssor
változatlanul működik, a program pedig megmondja, mit kell telepíteni.
Mérve: a táblázatos nézet +6,6 MB memória (a tkinter-felület importjainak a
negyede).

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

### A felület nyelve

**⚙ Beállítás → Nyelv** fül — magyar vagy angol. A választás a
`config.json`-ba (`dashboard.language`) kerül, és a **program következő
indításakor** lép életbe, ugyanúgy, mint a téma színei: a tkinter a feliratot a
widget megépítésekor kapja meg, futás közbeni váltásnál a felület fele magyar,
fele angol lenne.

A nyelvek a **saját nevükön** szerepelnek a listában (Magyar / English) — így
akkor is megtalálod a sajátodat, ha véletlenül egy olvashatatlan nyelvre
kapcsoltál.

A **téma** és a **betűtípus** ugyanennek az ablaknak a
**Megjelenés** fülén állítható. (2026-08-31 előtt mindkettő egy külön
`🎨 Megjelenés` gomb alatt volt az eszközsávon — az a gomb megszűnt.)

> Ami még nincs lefordítva, az **magyarul** jelenik meg, nem üresen. A napló, a
> `tools/` szkriptek kimenete és a config-ellenőrző szándékosan magyar marad.
> Új nyelvhez nem kell kódot írni: egy `lang/<kód>.json` és a leírásoknál egy
> `<név>.<kód>.md` elég. Az állapotot a `python tools/i18n_scan.py` mondja meg.

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

### Miért nem 116/116 a CI-ben?

13 teszt a saját `config.json`-odból, a `data/` mappádból vagy egy valódi képernyőből
dolgozik — historikus parquet, optimalizált paraméterek, mentett készletek, illetve
Tk-geometria. Az előbbi kettő a `.gitignore`-ban
van: az egyik brókeradatot tartalmaz, a másik több száz megabájt. Egy friss klónon
tehát nincs mit mérniük, és — a projekt szabálya szerint, miszerint a néma átmenés
rosszabb a bukásnál — hangosan buknak.

A CI ezért a `--no-live-data` kapcsolóval fut:

```bash
python tests/run_all.py --no-live-data
```

A kihagyott fájlok és az indokuk: [`tests/requires_live_data.txt`](tests/requires_live_data.txt).
A futtató `SKIP` sorként kiírja mindet, tehát a naplóból pontosan látszik, mi maradt
ki. **A fejlesztői gépen ezek a tesztek is futnak és átmennek** — a lista nem
mentesítés, hanem a hiányzó bemenet könyvelése.

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
| Élő indításkor belépést kér | Ez a licenc-belépés — a portál-fiókod (<https://licence.tipcsy.hu>). Gépenként egyszer kérdezi |
| „A licenced LEJÁRT" / „Elfogytak a számla-slotok" | A licencedet és a számla-slotokat a portálon kezeled |
| „nincs licencszerver: még … óra" a fejlécben | A szerver nem érhető el, a program a türelmi időből fut. Nézd meg a hálózatot — 72 óra után az élő kereskedés megáll |

---

## Dolgozzunk együtt!

Van egy beszállási ötleted — egy indikátor-kombináció, egy gyertyaminta, egy
napszak-szabály —, és tudni szeretnéd, **hogy valóban ér-e valamit?**

**Írj egy e-mailt a <tipcsy@gmail.com> címre, és dolgozzunk együtt:** te hozod az
ötletet, én lemérem a motorral — több instrumentumon, éveken át, valós költséggel
(spread, swap), mintán belül **és** mintán kívül. A visszajelzés az lesz, amit a
számok mondanak, akkor is, ha az a válasz, hogy nincs benne él.

Ha lehet, ennyit írj meg a levélben:

- **mikor lépnél be** (a feltétel, minél pontosabban);
- **mikor szállnál ki** (stop, célár, idő);
- **melyik instrumentumon és idősíkon** gondolod;
- ha van: chart-kép vagy egy-két konkrét példa a mintára.

> Nem kell kódot írnod, és nem kell programozónak lenned hozzá. Az sem baj, ha az
> ötlet még csak fél mondat — a mérhető szabállyá formálás a közös munka része.

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

> A fenti [Licencelés és regisztráció](#licencelés-és-regisztráció) ettől külön
> kérdés: a GPL a **forráskódra** vonatkozik, a regisztráció pedig a
> **licencszolgáltatás** (élő kereskedés, számla-slotok) használatához kell. A
> regisztráció ingyenes.

---

<a id="english"></a>

# TradeForge — English

A Python trading framework for MetaTrader 5: live engine, tkinter dashboard,
backtesting, Optuna-based parameter optimisation and MT5 chart visualisation —
across multiple instruments and multiple strategies at once.

> ⚠ **Risk warning.** This program can send **real orders** through the MT5
> terminal. Use it on a **demo account** first (`broker.is_demo: true`), and only
> switch to live once you understand what it does. The authors accept no
> liability for trading losses.

---

## Contents

- [Licensing and registration](#licensing-and-registration)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Preparing the MT5 terminal](#preparing-the-mt5-terminal)
- [Running](#running)
- [User guide](#user-guide)
- [Installing the MT5 indicators](#installing-the-mt5-indicators)
- [Updating from Git](#updating-from-git)
- [Project layout](#project-layout)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Let's work together!](#lets-work-together)
- [Further documentation](#further-documentation)
- [Source licence](#source-licence)

---

## Licensing and registration

TradeForge is **free to use, but it requires registration.** Registration means
an e-mail address and a password — no credit card, no confirmation e-mail, no
trial countdown.

> Registration is needed **for live trading only**. Backtesting, optimisation and
> data download run without a licence: they never touch your broker account.

### Registration, step by step

1. **Open the portal:** <https://licence.tipcsy.hu>
2. **Register** — e-mail address + password. That is all; the account works
   immediately.
3. **Start the program:** `python main.py live`. On the first live start
   TradeForge shows a login window — the same e-mail and password you registered
   with.
4. **Done.** The program stores a login token and **never asks again**. Your
   password is **stored nowhere**: it is exchanged for a token at login and
   discarded there.

If you forget your password, the portal's login screen has **"Forgot my
password"** — the reset link is valid for 30 minutes and can be used once.

### What happens on every start

Using the stored token and the **broker account number read from MT5**, the
program asks the server whether it may run:

1. the account number is **already bound** to your licence → it starts;
2. not bound, but a **free account slot** exists → it binds it and starts;
3. no free slot → it does not start, and tells you how many slots are in use.

So one licence can cover several broker accounts — the portal shows your slots.
Tokens are per machine (the label is the **machine name**) and can be revoked
from the portal at any time: a revoked machine asks for login again on next start.

### If the licence server is unreachable

The program still starts from the **last successful check**, within a **72-hour
grace period**. This is not a back door: the server signs its answer with
Ed25519 and the public key is built into TradeForge, so a hand-edited cache is
invalid.

The grace period is **visible in the UI**: in the header, next to the licence
e-mail (*"no licence server: 51 hours left"*) — amber, and red below 12 hours.
An approaching expiry appears in the same place (*"licence expires: 12 days"*)
within 30 days.

### The setting in `config.json`

Nothing to do by default; the sample already contains:

```json
"licence": {
  "api_url": "https://licence.tipcsy.hu/api/v1"
}
```

> The licence **is not the same thing as the source licence.** The program is
> **GPL-3.0** (see [Source licence](#source-licence) below) — registration is for
> using the *service* (licence server, account slots), not for reading or
> modifying the code.

---

## Requirements

| Requirement | Note |
|---|---|
| **Windows** | The `MetaTrader5` Python package is Windows-only |
| **Python 3.10+** | `tkinter` ships with the official installer — nothing extra to install |
| **MetaTrader 5 terminal** | Any broker; the program connects to the running terminal |
| **Git** (optional) | To download / update the code — <https://git-scm.com/download/win> |

> The program is **not** tied to a specific folder: install it wherever you like.
> In the commands below, `<project-folder>` is the directory you chose.

---

## Installation

### 1. Get the code

```bash
git clone https://github.com/tipcsy/TradeForge.git
```

This creates a `TradeForge` folder in the current directory. For a different
name, append it (`git clone <url> <folder>`). Without Git you can also download
the ZIP from GitHub and extract it anywhere.

Then enter the project folder — **run every further command from here**:

```bash
cd TradeForge
```

### 2. Virtual environment (recommended)

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

> The line above activates it in PowerShell/CMD; in Git Bash: `source .venv/Scripts/activate`.

> `.venv` is in `.gitignore`, so it never reaches the repository. It also works
> without a virtual environment — the packages then go into the system Python.

### 3. Install the packages

```bash
python -m pip install -r requirements.txt
```

This installs everything — required and optional alike. For the bare minimum:

```bash
python -m pip install MetaTrader5 numpy pandas optuna pyarrow fastparquet cryptography
```

| Package | What it is for |
|---|---|
| `MetaTrader5` | talking to the MT5 terminal (Windows-only) |
| `numpy`, `pandas` | maths, time series |
| `optuna` | parameter optimisation |
| `pyarrow`, `fastparquet` | Parquet format for the historical data |
| `cryptography` | verifying the licence server's signature |

Optional packages, for specific features only:

```bash
python -m pip install scikit-learn lightgbm pillow
```

| Package | For what |
|---|---|
| `scikit-learn`, `lightgbm` | training/running the `ml_ai` strategy |
| `pillow` | UI screenshot in `tools/ui_preview.py` |

> **Why `python -m pip` and not `pip`?** On Windows `pip` is often not on PATH,
> whereas `python -m pip` always calls the package manager of the Python you are
> running — so it cannot accidentally install into another environment.

---

## Configuration

`config.json` is **not in the repository** (it holds a password, it is
`.gitignore`d). Create it from the sample:

```bash
cp config.example.json config.json
```

Then edit `config.json`:

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

- **`broker`** — your own MT5 credentials. Start with `is_demo: true`.
- **`mt5.path`** — the full path to `terminal64.exe` on **your** machine. If only
  one MT5 is installed it can be omitted (the package finds it); with several
  installed terminals it is **mandatory**, otherwise it may connect to the wrong
  one. In JSON the backslashes must be doubled: `C:\\...\\terminal64.exe`.
- **`pairs`** — the instruments. The sample has two (`EURUSD`, `GER40`); you can
  add the rest from the UI as well (it fills in the broker's data automatically).
  Enable or disable a pair with `"enabled": true|false`.

The meaning of the other fields is described by the `_comment` keys of
`config.example.json`.

> **Never commit your own `config.json`.** `.gitignore` excludes `config.json`
> and the `config*copy*.json` / `config*másolata*.json` patterns too.

---

## Preparing the MT5 terminal

1. Start the **MetaTrader 5** terminal and log in to the account.
2. Tools → Options → Expert Advisors: **algorithmic trading enabled**.
3. Leave the terminal **open** — Python connects to it in the background.
4. The instruments you want to trade must be visible in **Market Watch**.

---

## Running

Every command runs from the project root (where `main.py` is):

| Command | What it does |
|---|---|
| `python main.py download` | download history from MT5 (into `data/`) |
| `python main.py dashboard` | UI only, with demo data — **works without MT5** |
| `python main.py live` | live engine + dashboard |
| `python main.py console` | live engine **without a UI** + a command prompt (weak machine, VM, SSH) |
| `python main.py console --tui` | the same, with a **live table** (needs the `rich` package) |
| `python main.py backtest` | backtest with the default parameters |
| `python main.py optimize` | optimise every active pair, each with its own strategies |
| `python main.py optimize EURUSD GBPJPY` | optimise the given pairs only |
| `python main.py optimize Ger40 --strategy ml_ai` | one pair, one strategy (for a trainable strategy this means training) |
| `python main.py optimize -s wpr_sma,ml_ai` | every pair, only the listed strategies |

### Running without a UI (`console`)

The same engine, with a command prompt instead of the dashboard (`help` lists
the commands: `pairs`, `pos`, `close`, `play`, `stop`, `balance`, `state`).

Two things worth knowing:

* **One engine per account.** A `data/live_<account>.lock` file prevents two
  instances from trading the same account — the licence would **not** stop
  that, because it is bound to the account, not to the machine. A different
  account may run in parallel.
* **Licence sign-in does not happen here.** Console mode deliberately does not
  open a sign-in window (it would not show over SSH): sign in once in the GUI
  and copy `data/licence_token.json` to the other machine.

### Telegram notifications

The engine can tell you about trades, position events and trouble. The
`config.json` → `notify` block turns it on (documented in
`config.example.json`); it is **off by default**.

| event | when it is sent |
|---|---|
| trade opened / closed, stop moved, risk removed | if the pair+strategy **trade notification** is on (default: ON) |
| signal (in signal-only mode) | if the **signal notification** is on (default: **OFF** — there are many) |
| engine not advancing · MT5 lost · daily loss limit · licence expiring | **always**, at most once a day |
| startup, scheduled heartbeat | per `heartbeat_times` (empty list = none) |
| **daily close summary** | per `daily_summary_time` (empty = none) |

**Quiet hours** (`quiet_hours`, in **local** time): signals are dropped — you
would not enter while asleep — but trades arrive **summarised** in the morning.
A critical error breaks through the quiet hours.

The **daily close** contains exactly what `/today` shows: opens, closes, net
result, the **best and worst** trade, how many signals produced no trade, and
what is still open. ⚠ A single net number would hide whether one big loser took
the day or many small ones. If the time falls inside quiet hours, the summary
arrives in the morning.

⚠ **Notification never stops trading.** Events go into a queue and a separate
thread sends them; if Telegram is unreachable, the engine cycle carries on.

**Which pair should speak:** click the instrument name — the strategy table
has two new rows, *Telegram: trades* and *Telegram: signals*, right where the
visualisation and trade-mode switches are. The "apply to every instrument"
checkbox covers them too.

⚠ Whoever holds the `token` **can read the messages sent to your bot** —
`config.json` is git-ignored so it belongs there, but do not copy it elsewhere.

**Commands** (replies come in the configured language):

| command | what it gives |
|---|---|
| `/help` | the command list |
| `/balance` | balance and today's result |
| `/pos` | open positions |
| `/today` | today's trades, result, and how many signals there were |
| `/state` | which strategies run on which pair + engine status |
| `/heart` | heartbeat — is everything OK |
| `/play <pair>` · `/stop <pair>` | start/stop a strategy |

#### Trading a signal from a button (`answer_trading`)

⚠ **Off by default**, because this turns a chat message into a real position.
When on, the bot sends a YES/NO button for signals of **`signal`-mode**
pair+strategy combinations, and YES opens the position.

The safeguards:

* only **`signal`-mode** pair+strategy gets a button (in `live` mode the engine
  trades anyway);
* the offer lives for **half a signal bar** (M15 → 7.5 min, H1 → 30 min,
  M1 → 1 min); after that the button says you are late;
* **single use** — pressing YES twice opens one position;
* the **gates cannot be bypassed**: open position, slot, daily loss limit,
  margin — the same execution path as the engine's own entry, and every refusal
  states its reason;
* if the price moved **more than 0.25 R** since the plan, YES does **not**
  trade: it tells you how far it moved and asks again. After confirming, the
  **stop/target distance is kept** and only the level slides to the current price.

The **command menu** is published by the program on every start
(`setMyCommands`), built from the command list in the code and the `/help`
descriptions — no manual upkeep in @BotFather, and it cannot go stale. Separate
menus are published for Hungarian and English Telegram interfaces.

⚠ The bot accepts commands **only** from the `chat_ids` listed in the config;
every other message is met with **silence**. With an open position `/stop` asks
with a **button** (which expires after 10 minutes), and nothing happens until
you confirm. Closing a position or stopping the engine remotely is **not
possible** — the command list is deliberately an allowlist, not a blocklist.

**Setup:** create a bot with @BotFather's `/newbot`, put the token into
`config.json`, then:

```bash
python main.py notify-test
```

This validates the token, **finds your `chat_id`** (from whoever has already
written to the bot), offers to save it, and sends a test message. ⚠ Open your
bot in Telegram and press **Start** first — a bot cannot message someone who
has not started a conversation with it.

**Two views, one command set.** `--tui` gives a self-refreshing table
(instruments, running strategies, open positions, the engine's heartbeat) in the
terminal's own screen buffer; any key pauses the view and the same commands work
as in the plain prompt. Anything that does not fit on screen is trimmed — and it
tells you how much was left out. `rich`
is **not required**: without it the prompt works unchanged and the program tells
you what to install. Measured: the table view costs +6.6 MB of memory (a quarter
of what the tkinter UI's imports cost).

With no argument (`python main.py`) it prints this list.

**Recommended order on the first run:**

```bash
python main.py dashboard
```

(to see the UI, still without MT5), then

```bash
python main.py download
```

and finally

```bash
python main.py live
```

---

## User guide

### Dashboard tabs

| Tab | What it shows |
|---|---|
| **Live Dashboard** | one row per instrument: BID/ASK, change %, spread, position, daily P&L, strategy cells, optimisation status and the control buttons |
| **Positions** | details of the open positions (strategy, exit plan, BE/trailing state, manual control) |
| **Closed** | the closed trades — including today's |
| **Portfolio Backtest** | joint backtest of several instruments: starting capital, period, risk reduction, equity curve and result table |

### Controls on the Live Dashboard

- **▶ / ■** — start / stop a pair (or a strategy). The state is saved into
  `config.json`, so it **survives a restart**. Stopping while a position is open
  puts the pair into *closing* (CLOSING) state: no new entries, but the engine
  keeps managing the existing position.
- **Opt** — start optimisation for that pair/strategy. For the `ml_ai` strategy
  this button means **training**, not a parameter search. An interrupted
  optimisation is offered/resumed at start-up.
- **BT** — backtest window for that pair: parameter editing, exploratory
  switches, comparison of the previous/original run.
- **Clicking the instrument name** — parameter window: rating and metrics,
  loading the optimisation results by rank (▲/▼), hourly trading switch, manual
  parameter save.
- **Other cells are clickable too**: the gate cells set the gate effect (block /
  reduce / none), and the "Together" cell sets the per-pair timeframe alignment.

### A typical session

1. `python main.py download` — download history (for a new instrument the program
   also downloads the missing history automatically).
2. **Opt** on the pair → the optimised parameters land in
   `data/optimized_params/<SYMBOL>.json`.
3. **BT** or Portfolio Backtest → check the parameter set.
4. `python main.py live` → **▶** on the selected pairs.

> **Signal-only mode.** Per pair and per strategy you can make the system compute
> and log everything but **send no orders**. This is the safest mode before
> taking a new strategy live.

### The interface language

**⚙ Settings → Language** tab — Hungarian or English. The choice is written to
`config.json` (`dashboard.language`) and takes effect **the next time the program
starts**, just like the theme colours: tkinter gives a widget its label when the
widget is built, so switching mid-run would leave half the interface Hungarian
and half English.

The languages appear under their **own names** in the list (Magyar / English) —
so you can find yours even if you switched to one you cannot read by accident.

The **theme** and the **font** are on the **Appearance** tab of the same
window. (Before 2026-08-31 both lived under a separate `🎨 Appearance` button
on the toolbar — that button is gone.)

> Whatever is not translated yet appears **in Hungarian**, not empty. The log,
> the output of the `tools/` scripts and the config checker deliberately stay
> Hungarian. A new language needs no code: a `lang/<code>.json` and, for the
> descriptions, a `<name>.<code>.md` is enough. `python tools/i18n_scan.py` tells
> you where it stands.

### Logs and outputs

| Location | Content |
|---|---|
| `data/tradeforge.log` | rotating run log |
| `data/optimized_params/` | per-pair optimised parameters + trials CSV |
| `data/execution_params/` | per-symbol execution settings |
| `data/backtest_results/` | backtest outputs |
| `data/mt5_backtest/` | backtest CSVs replayable in MT5 |

The `data/` folder is in `.gitignore` — your own data never reaches the repository.

---

## Installing the MT5 indicators

The program hands the chart visualisation to MT5 through a file (Python does not
draw on the chart). The `.mq5` files must be copied into **your own MT5 data
folder**: in MT5 choose **File → Open Data Folder**, then the `MQL5` subdirectory.

| File | Where | What it does |
|---|---|---|
| `mt5/TradeForgeViz.mq5` | `MQL5\Indicators\` | live signal visualisation (entries, SL/TP, alert markers); it also puts the other two on the chart |
| `mt5/TradeForgeBands.mq5` | `MQL5\Indicators\` | state bands in a separate sub-window (M15 signal window, SMA direction, market state, no-trade hour) |
| `mt5/TradeForgeWPR.mq5` | `MQL5\Indicators\` | Williams %R with the strategy's own maths, adjustable levels |
| `tools/BacktestTradesViewer.mq5` | `MQL5\Indicators\` | draws the backtest trades |
| `tools/BacktestPnLViewer.mq5` | `MQL5\Indicators\` | the same plus per-trade P&L and R, with a summary panel |
| `tools/BacktestReplayer.mq5` | `MQL5\Experts\` | replays the backtest in the Strategy Tester |

After copying, **compile them all in MetaEditor** (F7). On the (**M1**) chart it
is enough to attach `TradeForgeViz` — it adds the bands and the WPR with the
strategy's parameters. The visualisation can be switched on per pair and per
strategy from the UI.

Details on backtest replay: [`tools/MT5_BACKTEST_README.md`](tools/MT5_BACKTEST_README.md).

---

## Updating from Git

From the project folder:

```bash
git pull
```

If `git pull` fails because of local modifications:

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

| Command | What it does |
|---|---|
| `git status` | what changed locally |
| `git pull` | download the latest version |
| `git log --oneline -10` | the last 10 changes |
| `git stash` / `git stash pop` | set local changes aside / bring them back |

> `config.json` and `data/` are gitignored, so `git pull` **does not overwrite**
> your settings and your data.

---

## Project layout

```
.
├── main.py                  ← entry point (download / dashboard / live / backtest / optimize)
├── version.py               ← application name and version (in one place)
├── config.example.json      ← config sample (the real config.json is gitignored)
├── core/                    ← MT5 connection, indicators, risk, gates, execution
├── trading/                 ← live engine and backtest
├── strategy/                ← strategies (wpr_sma, ml_ai) + their own configs and docs
├── ml/                      ← Optuna optimiser
├── dashboard/               ← tkinter UI
├── mt5/                     ← MQL5 indicators (visualisation)
├── tools/                   ← data download and maintenance scripts, MQL5 backtest tools
├── tests/                   ← tests (no pytest dependency)
├── build/                   ← PyInstaller EXE build
└── data/                    ← data, logs, results (gitignored, created at runtime)
```

---

## Tests

```bash
python tests/run_all.py
```

A single test can be run on its own (`python tests/test_gates.py`), and a subset
can be filtered by a name fragment (`python tests/run_all.py package`).

### Why is CI not 116/116?

13 tests work from your own `config.json`, your `data/` folder or a real screen —
historical parquet, optimised parameters, saved sets, or Tk geometry. The first
two are in `.gitignore`: one contains broker data, the other is hundreds of
megabytes. On a fresh clone they have nothing to measure, and — following this
project's rule that a silent pass is worse than a failure — they fail loudly.

CI therefore runs with the `--no-live-data` switch:

```bash
python tests/run_all.py --no-live-data
```

The skipped files and the reason for each:
[`tests/requires_live_data.txt`](tests/requires_live_data.txt). The runner prints
every one of them as a `SKIP` line, so the log shows exactly what was left out.
**On the developer machine these tests run and pass** — the list is bookkeeping
for a missing input, not an exemption.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: MetaTrader5` | `python -m pip install MetaTrader5` (needs Windows) |
| `ModuleNotFoundError: optuna` / `pyarrow` | `python -m pip install optuna pyarrow fastparquet` |
| `pip` command not found | Use `python -m pip install ...` |
| `FileNotFoundError: config.json` | Copy `config.example.json` to `config.json`, and run the command from the project root |
| MT5 connection fails | Is the terminal running and logged in? Is `mt5.path` correct on **your** machine? Is algorithmic trading enabled? |
| No historical data | Run `python main.py download` first |
| An instrument is missing | Add it to Market Watch in MT5, and set `"enabled": true` in `config.json` |
| No visualisation on the chart | Is `TradeForgeViz.mq5` compiled, attached to the **M1** chart, and switched on for that pair? |
| Live start asks for a login | This is the licence login — the portal account (<https://licence.tipcsy.hu>). It is asked once per machine |
| "The licence has EXPIRED" / "no free account slots" | Manage your licence and your account slots on the portal |
| "No licence server: … hours left" in the header | The server is unreachable; the program runs from the grace period. Check the network — after 72 hours live trading stops |

---

## Let's work together!

Do you have an entry idea — an indicator combination, a candle pattern, a
time-of-day rule — and want to know **whether it is actually worth anything?**

**Write an e-mail to <tipcsy@gmail.com> and let's work on it together:** you bring
the idea, I measure it with the engine — across several instruments, over years,
with real costs (spread, swap), in-sample **and** out-of-sample. The feedback will
be whatever the numbers say, even when the answer is that there is no edge in it.

If you can, put this much in the mail:

- **when you would enter** (the condition, as precisely as possible);
- **when you would exit** (stop, target, time);
- **which instrument and timeframe** you have in mind;
- if you have one: a chart image or a couple of concrete examples of the pattern.

> You do not need to write code and you do not need to be a programmer. It is
> fine if the idea is still half a sentence — turning it into a measurable rule
> is part of the joint work.

---

## Further documentation

- [`strategy/docs/wpr_sma.md`](strategy/docs/wpr_sma.md) — the WPR + SMA trend-following strategy (Hungarian)
- [`strategy/docs/ml_ai.md`](strategy/docs/ml_ai.md) — the machine-learning strategy (currently **not** recommended live) (Hungarian)
- [`tools/MT5_BACKTEST_README.md`](tools/MT5_BACKTEST_README.md) — replaying a backtest in MT5 (Hungarian)
- [`build/README.md`](build/README.md) — EXE build (PyInstaller) (Hungarian)
- [`.claude/skills/new-strategy/SKILL.md`](.claude/skills/new-strategy/SKILL.md) — checklist for introducing a new strategy (Hungarian)

---

## Source licence

**GNU General Public License v3.0** — full text: [`LICENSE`](LICENSE).

```
TradeForge — MetaTrader 5 trading framework
Copyright (C) 2026 tipcsy

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.
```

In practice this means:

- You may **freely** use, study, modify and pass it on.
- If you **pass it on** — modified or not — you must hand over the **source code**
  as well, under the **same** GPL-3.0 licence.
- It **cannot** be built into a closed-source product.
- **No warranty.** Read this together with the risk warning above: the program can
  trade with real money, and the responsibility is the user's.

> The **registration** described under
> [Licensing and registration](#licensing-and-registration) is a separate matter:
> the GPL covers the source code, while registration covers the use of the licence
> service (live trading, account slots). Registration is free.
