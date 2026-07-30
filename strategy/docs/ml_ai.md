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
