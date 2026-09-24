# Piacok — hol tart a világ tőzsdéinek napja?

Hat piac nyitva tartását követi (Európa/Frankfurt, London, Amerika, Ázsia/Hongkong,
Japán, Ausztrália), és hat állapotot különböztet meg. Azért kapu, és nem csak
kijelzés, mert ugyanaz az öröklés és ugyanaz a három hatás vonatkozik rá, mint a
többire — de **alapból egyik állapot sem tilt**. Lásd lent, hogy miért.

## Az állapotok (élesség szerint, a legélesebb nyer)

| állapot | mikor | szín az oszlopban |
|---|---|---|
| **Nyitás** | a nyitás perce | piros |
| **Nyitás után** | a nyitás utáni `utan_perc` perc | piros |
| **Nyitás előtt** | a nyitás előtti `elott_perc` perc | sárga |
| **Zárás előtt** | a zárás előtti `zaras_elott_perc` perc | sárga |
| **Nyitva** | a kereskedési nap többi része | zöld |
| **Zárva** | hétvége, ünnep utáni éjszaka, nyitvatartáson kívül | szürke |

Ha egyszerre több figyelt piac ad állapotot, a **legélesebb** nyer, és a sor azt is
megmondja, melyik piac okozza.

## Miért nem kell „ÉS / VAGY" szabály-motor

A tervezéskor felmerült egy szabály-rendszer ÉS/VAGY kapcsolatokkal. Kiderült,
hogy nem kell: a **„mindegyik figyelt piac zárva"** = ÉS, a **„bármelyik piac
nyitás utáni ablakában"** = VAGY — és mindkettő EGYETLEN állapot a párhoz rendelt
piac-halmazon. A sablon tehát a `markets` lista maga.

## ⚠ Ahhoz, hogy az állapotonkénti hatás ÉLJEN, a kapu ne legyen „Ki"

A sávok (állapot → hatás) **csak akkor szólnak bele**, ha a kapu hatása ezen a
páron/stratégián nem `none`. Ez nem ennek a kapunak a szabálya, hanem a keret
általános szabálya: „egy kikapcsolt kapunak nincs sávja" — különben egy örökölt
sáv némán visszakapcsolhatna egy szándékosan kikapcsolt kaput.

Vagyis a sorrend: **1.** a kapu hatását vedd `block`-ra, **2.** a sávokban mondd
meg, MELYIK állapot mit tegyen (amelyik állapothoz nincs sáv, az átenged). A
kapu hatása itt főkapcsolóként működik, a részleteket a sávok döntik el.

## Beállítások

| kulcs | jelentés | alap |
|---|---|---|
| `markets` | mely piacokat figyeli ez a pár | mind a hat |
| `elott_perc` | a „nyitás előtt" ablak hossza | 10 |
| `utan_perc` | a „nyitás után" ablak hossza | 10 |
| `zaras_elott_perc` | a „zárás előtt" ablak hossza | 10 |
| `adverse` | mely állapotok BUKTATJÁK a kaput | üres |

Öröklés: `pairs.<SYM>.sessions` → `sessions` → beépített alapérték.

## ⚠ Az idő: mérve, nem tippelve

A gyertyák időbélyege **szerver-időben** van, és a szerver órája **Europe/Berlin**
helyi idő (nyári időszámítással együtt). Ez nem feltételezés: a Ger40 M1-gyertyák
átlagos tartománya télen és nyáron is a **09h indexnél** a legnagyobb (= frankfurti
nyitás), az amerikai púp pedig 15–16h-nál — valódi UTC-ben ezek két külön órára
esnének. Ha ezt valaki „igazi UTC"-nek veszi, a kapu **nyáron két órát téved**, és
épp a nyitási tüskét hagyja ki, amiért készült.

## ⚠ Ünnepnapokat nem ismer

Tőzsdei naptár nélkül karácsonykor is „nyitva"-t mond. A tényleges tick-aktivitást
a `core.market_state` méri instrumentumra — ez a modul a NAPTÁRT tudja, nem a
forgalmat.

## Miért nem blokkol alapból

A projekt saját mérései ellentmondanak egymásnak:

- **Mellette:** 186 471 kötésen a napszak-hatás majdnem teljesen költség-szerkezet,
  és a 22:00-s óra az egyetlen, ahol a BRUTTÓ él is erősen negatív (−0,179 R).
  De a mechanizmus a költség — azt a spread- és a költség-kapu KÖZVETLENÜL méri,
  ez csak proxy.
- **Ellene:** a gyertya-alakzat vizsgálatban a 15:30–16:00 szerver-idejű ablak
  (= 09:30 New York, a nyitóharang) jött ki a LEGJOBB napszaknak.

Ezért a kapu MUTAT. Mielőtt bármelyik állapot `block`-ra kerül, **meg kell mérni**,
mit tesz.

## Amit hozzátesz

A spread-kapu **reaktív**: akkor lát, amikor a spread már kinyílt. Ez **előre tud**
— tíz perccel a londoni nyitás előtt már tudja, hogy jön.
