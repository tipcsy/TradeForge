# Költség/kockázat kapu

Nem a spread **nagyságát** méri, hanem azt, hogy mennyire rontja el az üzletet.

## Amit a spread elront — és amit nem

A spread **NEM változtatja meg a kifizetést**: ha a TP üt, `tp`-t nyersz, ha az
SL, `sl`-t veszítesz. A nyereség/veszteség aránya — és így a nullszaldó
win-rate, `1/(1+RR)` — változatlan.

Amit elront, az a megteendő **TÁVOLSÁG**, mert a stop a bróker másik oldalán
teljesül:

```
táv_nyeréshez / táv_vesztéshez = (TP + spread) / (SL − spread)
```

EURCHF-en a kifizetés marad 2:1, a megteendő út aránya viszont **3,4:1** —
vagyis 2:1-ért kell 3,4:1 esélyű utat megtenni. Ez a rés a költség.

## Mérés (2026-08-07)

Véletlen belépés várható értéke kötésenként, R-ben, 12 000 M15 gyertyán:

```
GOLD    +0,029R      UsaTec  −0,075R      EURUSD  −0,127R
EURJPY  −0,196R      EURCHF  −0,201R      EURGBP  −0,201R
```

EURCHF-en tehát **minden kötés −0,20R-rel indul**, mielőtt bármilyen jel-minőség
szóba kerülne.

## Miért kell, ha már van spread-kapu

A spread-kapu relatív padlója (`min_spread_mult × normál_spread`) konstrukció
szerint nagyobb a pár normál spreadjénél — tehát a pár a saját szokásos
spreadjén SOHA nem akad fenn rajta:

```
pár      spread   ATR-tag   padló   tényleges határ   blokkol?
EURCHF       15       6,2    23,1              23,1        nem
EURGBP       14       5,7    21,6              21,6        nem
```

Az ATR-tag rég blokkolna, a padló átengedi.

## Miért kapu, és miért nem mozdítja el az SL-t

**Mérve:** a stop szélesítése nem menti meg a drága instrumentumot. EURCHF-en a
`sl_atr_mult` 1,5 → 3,0 a spread/SL arányt 31%-ról 15%-ra viszi, de a véletlen
belépés éle közben zuhan — a 2× szélesebb TP elérhetetlenné válik. Nincs olyan
geometria, ami kifizetné a spreadet.

**Szerkezeti ok:** ha egy kapu elmozdíthatná az SL-t, az „1 R" elveszítené a
jelentését. A rendszer R-alapú elszámolásra épül — a belépéskori kockázat
rögzül, a P&L-cellák R-ben is mutatnak, a kockázatcsökkentő presetek R-ben
gondolkodnak. Egy némán átírt stop minden korábbi R-számot hazuggá tenne
visszamenőleg.

> Ez az EGYETLEN kapu, ami a belépő-TERV után dől el — kell hozzá a stratégia
> által szánt SL.

## Sávos hatás (v3.28.0)

A kapu hatása nem csak egyetlen igen/nem lehet. A **Hatás** fülön létrát
állíthatsz: `+ Sáv` felvesz egy határt, a `Törlés` kiveszi.

| szint | mi történik |
|---|---|
| 80% | kockázatcsökkentés (fele méret) |
| 100% | akadályozza a beszállást |

**A szint a kapu SAJÁT küszöbének százaléka**: 100% pontosan az a pont, ahol ez a
kapu enélkül is bukna. Ezért hordozható, és ezért öröklődik — globális →
instrumentum → instrumentum+stratégia, ahol nincs beállítva, ott örököl.

> **Sáv nélkül semmi nem változik.** A létra hiánya is létra: egyetlen implicit
> sáv a kapu saját küszöbén, a fent beállított hatással. Amíg nem veszel fel
> sávot, a kapu bitre úgy viselkedik, ahogy eddig.
