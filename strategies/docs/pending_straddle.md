# Függő megbízás (WPR straddle)

**Modul:** `strategies/pending_straddle.py` · **Config:** `strategies/config/pending_straddle.json`
**Jel-idősík:** `signal_tf_min` — alap **M5** (1/5/15/30/60); a betöltést mindig az M1 figyeli · **Magic-eltolás:** +4

---

## A szabály

1. **Trigger** — WPR(14) a **jel-idősíkon** (`signal_tf_min`, alap M5). A jel
   akkor szól, ha az árfolyam egy **extrém zónából indulva** áttöri a középső
   szintet:
   * a felső extrémből (WPR ≥ −20) **lefelé** töri a −50-et, **vagy**
   * az alsó extrémből (WPR ≤ −80) **felfelé** töri a −50-et.
2. **Straddle** — a triggerkor **két** megbízás kerül ki a jel-gyertya
   záróárától `straddle_spread_mult × spread` távolságra: egy BUY fölé, egy
   SELL alá.
3. **OCO** — amelyik elindul, a másik azonnal törlődik.
4. **Lejárat** — ha `straddle_ttl_bars` M1 gyertyán belül egyik sem indul el,
   mindkettő törlődik.

### Két idősík, két szerep

| | idősík | miért |
|---|---|---|
| **trigger** (WPR, straddle kihelyezése) | `signal_tf_min` (alap M5) | a döntés üteme |
| **betöltés** (a szintek érintése) | **mindig M1** | egy valódi stop-megbízás intrabar töltődne be — a durvább figyelés csak rontaná a modellt |

A lejárat (`straddle_ttl_bars`) **M1 gyertyában** számol, tehát az idősík
váltásakor a szetup élettartama változatlan marad — így az M1/M5/M15
összehasonlítás azonos időablakot mér.

⚠ A `signal_tf_min` **nincs az optimalizáló tengelyei közt**: az idősík
szerkezeti döntés, nem hangolási paraméter. Ha hangolnánk, minden trial más
stratégiát mérne, és a „legjobb" idősík a keresési zaj függvénye lenne.
Idősík-váltás után **újraoptimalizálás** kell.

### A WPR itt nem irányt ad, hanem időzítést

A −50 áttörése azt mondja, hogy *„most mozdul"* — hogy **merre**, azt a straddle
dönti el. Ez szándékos: a projekt korábbi mérései szerint (`Időzítés, nem
belépőjel`, `Indikátor-lista átvizsgálva`, 23 szabály × 5 pár × 2 irány) az
indikátorok az irányról nem mondanak semmit, a volatilitásról viszont igen.

---

## ⚠ Amit ez a modul NEM tud — olvasd el, mielőtt az eredményt értelmezed

**A TradeForge-ban nincs függő megbízás.** A `core/mt5_connector.py` kizárólag
`TRADE_ACTION_DEAL`-t (piaci kötés) küld, a backtest pedig fixen az M1 gyertya
**zárásán** nyit (`trading/backtest.py`: `open_price = _bar_c`). Sem `BUY_STOP`,
sem OCO, sem lejárat nincs a keretben.

Ez a modul ezért **virtuális straddle**: a két szintet a stratégia tartja
nyilván, és amelyiket az M1 gyertya **először megérinti**, arra ad jelet — a
tényleges belépő viszont az adott M1 gyertya **zárásán** történik, nem a
szinten.

| | virtuális straddle (ez a modul) | valódi függő megbízás |
|---|---|---|
| betöltési ár | az M1 gyertya zárása | pontosan a függő szint |
| live ↔ backtest | **bitre azonos** (ugyanaz a hook) | keret-fejlesztést igényel |
| megvalósítás | 1 stratégia-modul | connector + live OCO/lejárat + intrabar betöltés-modell |

### ⚠ …de a különbség MÉRVE nulla

2026-09-07, 6 pár, 19 371 betöltés. A szinten való betöltés **előnye** az M1
záráshoz képest, R-ben:

| pár | átlag | medián | pozitív |
|---|---:|---:|---:|
| Ger40 | −0,009 | +0,002 | 50,8% |
| UsaTec | −0,032 | −0,011 | 48,5% |
| GOLD | **+0,015** | +0,007 | 50,9% |
| EURUSD | −0,018 | −0,019 | 37,6% |
| UsaInd | −0,005 | +0,004 | 51,6% |
| UK100 | **+0,020** | +0,011 | 53,9% |

Az M1 zárás tehát a függő szint **torzítatlan** közelítése: a szórása nagyobb, a
várható értéke ugyanaz. Pontosan ez az, amit egy hatékony piactól várni lehet
(`A piac hatékonyabb lett`).

> **Következmény:** a valódi függő megbízás keret-szintű megépítése az alábbi
> eredményt **nem fordítaná meg**. A mostani szám nem „ideiglenes", hanem az
> ítélet.

A `max_chase_spread` (ha az M1 zárás ennyi spreadnél messzebb van a szinttől, a
belépő kimarad) ezért alapból **ki van kapcsolva** (0): nem vesz meg
hitelességet, viszont a betöltések 3–44%-át eldobná.

---

## A spread a lépték

A szintek **és alapból az SL is** spreadben mérődik, nem ATR-ben. Ez szándékos:
az `Instrumentum költség-sorrend` lelet szerint a költség R-ben 22×-es szórást
mutat instrumentumonként (UsaTec 0,032 R … EURHUF 0,707 R) — spread-léptékű
stoppal ez a szórás eltűnik, tehát a párok mérése összehasonlíthatóvá válik.

A spread a gyertya **saját** spread-oszlopából jön:

| forrás | oszlop | egység |
|---|---|---|
| parquet (backtest) | `close_spread`, tartalék `avg_spread` | ár |
| MT5 `copy_rates` (élő/viz) | `spread` — a `live_trader.get_candles` már árra váltotta | ár |

**Ha egyik sincs, a stratégia nem jelez** — és ezt egyszer **kiírja a naplóba**
(`pending_straddle (M1): a gyertyákon NINCS spread-oszlop …`). Egy néma nulla
pontosan úgy nézne ki, mint egy nyugodt piac; a projekt legdrágább
hibaosztálya épp ez.

---

## SL / TP

| `sl_mode` | SL | mikor |
|---|---|---|
| `straddle` (alap) | `sl_spread_mult × spread` | a straddle természetes léptéke |
| `atr` | `sl_atr_mult × ATR(M15)` | a kódbázis szokásos stopja |

A klasszikus *„az ellenoldali láb a stop"* straddle-beállítás:
`sl_spread_mult = 2 × straddle_spread_mult` (alapértékekkel 4,0).

A TP mindkét módban `tp_rr_ratio × SL`.

> ⚠ **Szűk stop = a spread eszi meg az élt.** Egy 4 spreades stopnál a belépés
> egyetlen spreadje az R **25%-a**. A `Csak-WPR M1 belépő: nincs él` lelet
> pontosan ezen bukott el. Ezért az `sl_spread_mult` tartománya tág (2…20), és
> ez a **második** mérendő tengely (az első a `straddle_spread_mult`).

> ⚠ **`min_lot` túlkockázat.** Szűk stop mellett a `calc_lot` nagy lotot ad. A
> súlyozott slot-keret ezt kezeli, de érdemes a Pozíciók fülön ellenőrizni,
> mekkora kockázat kerül ténylegesen a piacra.

---

## Ami NEM ezé a moduléé

| kérés | hova tartozik |
|---|---|
| „az SL-t BE+spreadre mozgatom" | **kockázatcsökkentés** — `core/risk_reduction.py` + `core/rr_state.py` (per pár). A breakeven ott már **költség-tudatos**: a puffernek a jutalékot és a swapot is fedeznie kell. |
| mekkora legyen a lot | `core/risk_manager.py` (számla × kockázat / slotok) |
| spread-kapu, TF-együttállás, piac-állapot, volatilitás | a közös végrehajtási config + `core/gates.py` |

A stratégia csak az SL/TP **távolságot** adja (`sl_tp_points`) — a lotot és a
stop későbbi mozgatását nem. Lásd `strategy/base.py`.

---

## Jelölő-oszlop (dashboard)

Három kör, balról jobbra:

| kör | jelentés | szín |
|---|---|---|
| **WPR extrém zóna** | a WPR járt az extrémben → fel van fegyverezve | sárga / szürke |
| **Függő pár kint** | a straddle ki van helyezve, még él | cián / szürke |
| **Betöltés** | ezen az M1 gyertyán töltődött be | zöld (BUY) / piros (SELL) / szürke |

## Chart-rajz (MT5)

* A függő szintek **szaggatott** vonallal (zöld = BUY oldal, piros = SELL oldal),
  pontosan addig, ameddig a megbízás kint volt.
* A betöltések a szokásos belépő-jelölővel (függőleges irány-vonal + Entry/TP/SL).
* WPR(14) al-ablak a négy szinttel.
* A rajz **csak az M1 charton** jelenik meg (`TfOnly(1)`) — minden döntés ott
  születik, más idősíkon félrevezető lenne.

---

## Modellezési döntések

**`[DÖNTÉS]` Egy gyertyán belül mindkét szint sérül.** Hogy melyik jött előbb,
az OHLC-ből nem derül ki (ahhoz tick kellene). A **pesszimista** utat vesszük,
ugyanazzal a konvencióval, mint a motor intrabar SL/TP-sorrendje: emelkedő
gyertyánál (close ≥ open) az utat az aljáról indítjuk → a **SELL** töltődött be,
és utána ellene ment a piac. Ez a whipsaw — nem szépítjük el.

**`[DÖNTÉS]` Egy szetuphoz egy straddle.** A trigger után a `zone` (extrém-emlék)
nullázódik, tehát a következő kihelyezéshez az árnak **újra meg kell járnia egy
extrémet**. E nélkül a −50 körüli oda-vissza pattogás gyertyánként új straddle-t
tenne ki.

**Felfegyverez → tüzel, nem „szomszédos gyertya".** A `zone` a felfegyverzés
(bármikor a múltban járhattunk az extrémben), a −50 keresztezése a tüzelés. Az
`M1 belépő állapotgép` lelet szerint a szomszédos-gyertyás minta a fokozatos
átütést kihagyja (a BUY gyakorlatilag sosem tüzelt).

**Mély warmup (M1: 1440 gyertya).** A `zone` tetszőlegesen régi lehet. Sekély
warmuppal a motor „nem látná" a felfegyverzést, a viz viszont igen — pontosan az
`M15 warmup-mélység eltérés` lelet.

---

## Első mérés — ALAP (hangolatlan) paraméterekkel

`sl_spread_mult = 6`, `straddle_spread_mult = 2`, `tp_rr_ratio = 2`, ~2,5 hónap,
`exec_gates=True`:

| pár | kötés | P&L | WR% | átlag R |
|---|---:|---:|---:|---:|
| Ger40 | 1789 | −804 $ | 29,0 | −0,1394 |
| UsaTec | 2455 | −993 $ | 28,2 | −0,1559 |
| GOLD | 2650 | −764 $ | 30,8 | −0,1195 |
| EURUSD | 994 | −175 $ | 36,7 | −0,2616 |
| UsaInd | 2535 | −369 $ | 32,0 | −0,1645 |
| UK100 | 2314 | −281 $ | 39,4 | −0,1624 |

### Az eredmény = a költség

Az `sl_spread_mult` végigsöprése megmutatja, hogy a veszteség **arányosan
zsugorodik** a stop tágításával — pontosan úgy, ahogy a `−1 / sl_spread_mult`
költség-képlet előírja:

| `sl_spread_mult` | várható (−1/mult) | Ger40 | UsaTec | EURUSD |
|---:|---:|---:|---:|---:|
| 3 | −0,333 | −0,306 | −0,329 | −0,448 |
| 4 | −0,250 | −0,205 | −0,231 | −0,380 |
| 6 | −0,167 | −0,139 | −0,156 | −0,262 |
| 9 | −0,111 | −0,101 | −0,088 | −0,197 |
| 14 | −0,071 | −0,085 | −0,090 | −0,122 |
| 20 | −0,050 | −0,047 | −0,028 | −0,128 |

A maradék (mért − várható) Ger40-en és UsaTec-en végig **±0,03 R-en belül** van,
EURUSD-n tartósan **negatív**. Nincs konzisztens él — az eredmény gyakorlatilag
*azonos* a költséggel, ugyanaz a kép, mint a `Várható érték = mínusz a költség`
leletben.

### Kill-teszt: a WPR-trigger nem ad semmit

A WPR-triggert **véletlen időzítésre** cserélve (minden 30. M1 gyertyán
kihelyezünk egy straddle-t, minden más változatlan), `sl_spread_mult = 6`:

| pár | WPR-trigger | véletlen időzítés |
|---|---:|---:|
| Ger40 | −0,1394 | **−0,1134** |
| UsaTec | −0,1559 | **−0,1496** |
| EURUSD | −0,2616 | −0,3015 |

A véletlen időzítés **három párból kettőn jobb**. A −20/−80 → −50 áttörés tehát a
belépés időzítéséhez nem ad mérhető információt — ugyanaz a kimenetel, mint a
`CLB: nincs él` esetben.

> ⚠ Ezek **hangolatlan** paraméterek (`Hangolatlan párok szennyezik a mérést`).
> Az optimalizáló találhat jobb kombinációt — de a fenti két teszt azt mutatja,
> hogy az eredményt a **költség-arány** vezérli, nem a WPR szintjei; ez az, amit
> egy paraméter-keresés nem tud megjavítani, csak elfedni.

---

---

## Az idősík nem segít (M1 vs M5 vs M15)

Ugyanaz a kód, csak a `signal_tf_min` más. Alap paraméterek, ugyanaz az ablak:

| pár | M1 kötés | M1 átlag R | M5 kötés | M5 átlag R | M15 kötés | M15 átlag R |
|---|---:|---:|---:|---:|---:|---:|
| Ger40 | 1789 | −0,1394 | 428 | −0,1399 | 167 | −0,1060 |
| UsaTec | 2455 | −0,1559 | 632 | −0,1623 | 202 | −0,1535 |
| GOLD | 2650 | −0,1195 | 611 | −0,1193 | 210 | −0,0920 |
| EURUSD | 994 | −0,2616 | 466 | −0,2832 | 178 | −0,2211 |
| UsaInd | 2535 | −0,1645 | 569 | −0,1210 | 193 | −0,2619 |
| UK100 | 2314 | −0,1624 | 533 | −0,1368 | 175 | −0,1860 |
| **összesen** | **12 737** | **−0,167** | **3 239** | **−0,160** | **1 125** | **−0,170** |

A kötésszám a várt arányban esik (1 : 3,9 : 11,3 ≈ az idősíkok aránya), a
**kötésenkénti eredmény viszont gyakorlatilag azonos**. Az abszolút P&L azért
kisebb M5-ön, mert kevesebb a kötés — nem mert jobb a kötés.

### M5-ön a kill-teszt is bukik — most már 3/3-on

`sl_spread_mult = 6`, a WPR-triggert véletlen időzítésre cserélve:

| pár | M5 WPR-trigger | véletlen időzítés |
|---|---:|---:|
| Ger40 | −0,1399 | **−0,0960** |
| UsaTec | −0,1623 | **−0,1368** |
| EURUSD | −0,2832 | **−0,2600** |

M1-en még csak 2/3 volt, M5-ön **mindhárom páron jobb a véletlen**. A
költség-görbe is ugyanúgy áll M5-ön (mult 3 → −0,37, 6 → −0,14, 14 → −0,08),
tehát a veszteség nem az idősík rossz megválasztása: a kötésenkénti várható
érték minden idősíkon a költség.

---

## Bevezetés / mérés — ajánlott sorrend

1. **Kapcsold be egy páron** (az instrumentum nevére kattintva, a stratégia
   pipálásával). Alapból minden regisztrált stratégia elérhető.
2. **Nézd meg a charton** (viz), hogy a szintek és a betöltések ott vannak-e,
   ahol vársz. Ha nincs jelölő, nézd meg a naplót a spread-oszlop hiányáról.
3. **Optimalizálás** (Opt gomb) — az első két tengely a `straddle_spread_mult`
   és az `sl_spread_mult`.
4. **Holdout** — a `Holdout protokoll` szerint. ⚠ Az `Optuna átlép az OOS-határon`
   lelet miatt a walk-forward számok felfújtak; a végső ítélet a külön tartott
   szeleté.
5. A **valódi** függő megbízás keret-fejlesztése a fenti mérés szerint **nem
   indokolt**: a szint-betöltés előnye nulla.
