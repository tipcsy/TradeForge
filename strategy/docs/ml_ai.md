# ml_ai — gépi tanulás (LightGBM / RandomForest)

Nem szabály-alapú: egy **betanított modell** dönt. Az „Opt" gomb ennél a
stratégiánál **tanítást** jelent, nem paraméter-keresést.

## Hogyan működik

1. **Jellemzők** (`ml_features.compute_smc`) — SMC-szerű szerkezeti mérőszámok
   (egyensúly-hiányok, korábbi csúcsok/aljak távolsága, stb.), **pontban**
   normalizálva.
2. **Címkézés** (`ml_train.label_outcomes`) — a belépő a gyertya záróján, a kimenet
   a következő ~32 gyertyán; azonos gyertyán belül **SL-elsőbbség**.
3. **Küszöb-kalibráció** — külön szeleten, hogy a döntési határ ne a tanító adatra
   illeszkedjen.

Az SL-módszer **`atr`** (nem `swing20`): a modell címkéje ATR-alapú stopra épül.

> Ez egy valós hibából jött: a közös végrehajtási út `swing20`-at használt
> alapértékként, ami a **wpr_sma sajátja**. Így a motor 1,4–1,5× szűkebb stoppal
> kötött, mint amire a predikció vonatkozott — **a predikció más kereskedésre
> szólt, mint amit a motor végrehajtott**. (v1.66.3)

## ⚠️ Jelenlegi állapot: NEM javasolt élesben

A mérések szerint a modellek **nem hordoznak használható jelet**:

| mérőszám | érték | mit jelent |
|---|---|---|
| AUC | 0,483–0,576 | **0,5 = véletlen** |
| küszöb-lefedettség | 0,1–4% | a magas tanítási találati arány néhány tucat mintára esik |
| OOS profit-faktor | 0,25–1,46 | mintán kívül összeomlik |

A tanítási pipeline **módszertanilag rendben van** (nincs look-ahead a
címkézésben, az időrendi vágás helyes, a küszöb külön szeleten kalibrálódik).
**A jellemzők nem hordoznak jelet erre a címkére** — nem a tanítás rossz.

Ezért minden páron **„csak jelzés"** módban fut: mindent kiszámol, riaszt és
naplóz, de **megbízás nem megy ki**. Így tovább mérhető, pénz nélkül.

## Modell-verziózás

A mentett csomag bélyege: `meta.feature_unit = "point"`.

A `compute_smc` a jellemzőket a pár **pont-méretével** normalizálja. Amikor a
projekt pipről pontra váltott, ez indexeken **100×-os skálaugrást** jelentett a
bemenetben — a pip-skálán tanított modellek némán értelmetlen predikciókat adtak
volna. Ezért a betöltés **ellenőrzi a bélyeget**, és elavultnál **kihagyja** a
modellt beszédes üzenettel.

> Konverzióval nem javítható: **újratanítás kell.**

## Ha újratanítod

- Az „Opt" gomb indítja (per pár).
- A tanítás a **teljes előzményt** használja (`optimizer.training.lookback_years`),
  nem a `train_start_date`-et — több adat, jobb modell.
- Az AUC-t érdemes megnézni utána: ha ~0,5 marad, a modell **nem javult**, csak a
  zaj rendeződött át. A PF ingadozása önmagában nem bizonyíték.

## ⚠ Mérés 2026-08-08: a modellek MEMORIZÁLNAK, nem tanulnak

A tanítási határnál kettévágva ugyanaz a kód, ugyanaz a spread:

| | kötés | találat | PF | P&L |
|---|---|---|---|---|
| BTCUSD **in-sample** | 874 | **70,4%** | 8,04 | +15 524$ |
| BTCUSD **OOS** | 130 | **26,2%** | 0,78 | −80$ |
| EURUSD **in-sample** | 476 | **72,7%** | 10,51 | +2 769$ |
| EURUSD **OOS** | 45 | **22,2%** | 0,57 | −31$ |

A mentett modellek AUC-ja **a tanítóadaton 0,87–0,92, friss adaton 0,48–0,56**
(a BTCUSD long 0,482 — *rosszabb*, mint az érmefeldobás). Vagyis az in-sample
eredmény nem részleges tudás, hanem **színtiszta felidézés**: valódi
megkülönböztető erő gyakorlatilag nincs.

### Miért ekkora a szakadék — a szerkezeti ok

A `_train_direction` **kétszer** tanít:

1. A modell a train első 80%-án tanul, a küszöb a maradék 20%-on kalibrálódik
   (ezt a modell NEM látta) → a küszöb tisztességes.
2. Utána a modell **újratanul a teljes train-en**, a kalibrációs farokkal együtt.

A mentett csomagba a **második modell** kerül, de az **elsőhöz** kalibrált
küszöbbel. A küszöb így más eloszlásra vonatkozik, mint amire alkalmazzuk: a
végső modell a saját tanítóadatán már közel tökéletes, tehát a 0,81-es küszöb
ott a *tényleges nyerőket* válogatja ki. Friss adaton — AUC 0,5 mellett —
ugyanaz a küszöb már csak érmét dob.

### Amit ebből tudni kell

- **Az ml_ai backtestje csak a tanítási ablakon KÍVÜL értelmes.** A Backtest-ablak
  ezt mostantól kiírja (`core/training_overlap.py`).
- A `threshold = 1.01` a „soha ne tüzelj" jelölő. Jelenleg **4 páron mindkét irány
  1.01** (Ger40, UK100, UsaInd, Euro50 → ott soha nem köt), és **3 pár csak long**
  (EURUSD, UsaTec, GOLD). Ez a `min 40 kalibrációs jel` védelem műve.
- Az AUC ~0,5 azt jelenti, hogy **a jellemzőkben nincs jel** — ezen sem küszöb, sem
  újratanítás nem segít. Vagy más jellemzők kellenek, vagy más célváltozó.
