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
- A `threshold = 1.01` a „soha ne tüzelj" jelölő. Egy irány ezt kapja, ha a
  kalibráció nem talál elfogadható küszöböt — a felületen ez **némán** annyit
  jelent, hogy az a pár/irány soha nem köt. (A v2.13.0 utáni állapotot lásd
  alább.)
- Az AUC ~0,5 azt jelenti, hogy **a jellemzőkben nincs jel** — ezen sem küszöb, sem
  újratanítás nem segít. Vagy más jellemzők kellenek, vagy más célváltozó.

## JAVÍTVA (v2.13.0): a küszöb ahhoz a modellhez tartozik, amelyik kiszolgálja

A küszöb és az AUC mostantól a **teljes train-re vett fold-on kívüli**
valószínűségekből jön (`oof_proba`), **tisztító sávval**: a címke `lookahead`
gyertyát néz előre, tehát a szomszédos sorok kimenete átfed — a fold köré vágott
sáv nélkül a tanító rész a teszt-rész jövőjét is látná.

A mentett modell továbbra is a teljes train-en tanul (a friss adat számít), de a
küszöb már arra az eloszlásra vonatkozik, amit élesben látni fog.

Új védelem: **AUC-padló** (`optimizer.training.min_model_auc`, alap 0,52). Ha a
modell nem tud megkülönböztetni, bármely küszöb „jó" találati aránya kizárólag a
keresés mellékterméke — a `min_calibration_signals` a mintaszám felől véd, ez a
jelforrás felől.

### Mit hozott (2026-08-08, újratanítás 11 páron)

Az őszinte kalibráció **22 irányból 17-et magától kikapcsolt**. Friss OOS-on
(2026-05-01 … 08-07):

| | kötés | P&L |
|---|---|---|
| ml_ai, régi kalibráció | 340 | **−827$** |
| ml_ai, őszinte kalibráció | 164 | **−208$** |
| `wpr_sma` ugyanott | 1314 | **+2394$** |

> A javítás **nem teremt élt** — nem is teremthet. Azt szünteti meg, hogy a
> stratégia zajra élesedjen: a kár a negyedére esett, de az előjel nem fordult.

## v2.15.0: a küszöb VÁRHATÓ ÉRTÉKRE kalibrál

A régi pontszám (`wr² × lefedettség^0,15`) a **találati arányt** hajszolta, ezért
mindig a legszűkebb, legmagasabb-arányú farkat választotta — az aktív irányok
rendre 42–100 jelen álltak, épp a minimumon. Csakhogy nem a találati arány fizet:

> **E[R] = wr × (RR+1) − 1** — RR 2-nél a nullszaldó 33,3%.

Egy 35%-os, sok jelet adó küszöb (+0,05R × 500 kötés) többet ér, mint egy 50%-os,
ami húszszor ritkábban szól. A mintaszám a **Wilson-alsókorláttal** épül be
(10/20 → 0,299; 500/1000 → 0,469), a pontszám pedig a konzervatív várható érték
× darabszám. Így a `min_signals` már csak durva padló, nem a fő védelem.

`optimizer.training.calibration_z` (alap **1,28** = 80% egyoldali). Ez
kockázatvállalási döntés, nem statisztikai közlés: 95%-on (z=1,96) 8 irányból 2
maradt 108 jellel, 80%-on 3 irány 1815 jellel.

### OOS-menet (2026-05-01 … 08-07)

| lépés | kötés | P&L |
|---|---|---|
| kiindulás (régi kalibráció, régi címke) | 340 | −827$ |
| fold-on kívüli kalibráció (v2.13.0) | 164 | −208$ |
| őszinte címke + idő-jellemzők (v2.14.0) | 14 | +0$ |
| várható-érték kalibráció (v2.15.0) | 21 | **+6$** |

> ⚠ **21 kötés három hónap alatt.** A veszteség forrása megszűnt; nyereségesség
> NINCS bizonyítva. Ehhez lényegesen több kötés kell — vagy több páron kell
> érvényes küszöböt találni, vagy erősebb jellemzők kellenek.
