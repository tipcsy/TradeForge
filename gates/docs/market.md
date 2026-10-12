# Piac-állapot kapu

Egy **piac-osztályozó** besorolja az aktuális piacot (ma: `regime` — ADX/DI/ATR
alapján, 8 kategória), és a kapu akkor „bukik", ha a besorolás a **kedvezőtlen**
listában van.

## Kategóriák

```
Sz.Bika  Sz.Medve      tiszta trend
Id.Bika  Id.Medve      ideges trend
Oldalazás              nincs irány
Érdektelen             halott piac
Bizonyt.  Átmenet      nem eldönthető
```

## Beállítások

- **Piac-osztályozó** — `gates.market.classifier` (alap: *Regime*). MINDEN
  instrumentumon fut, így a `Piac` oszlop mindenhol mutatja az állapotot.
- **Kedvezőtlen besorolások** — alap: *Érdektelen* + *Bizonytalan*.
- **Piac-sáv a charton** — `gates.market.viz`, csak rajz.

Mindhárom páronként felülírható a szokásos `pairs.<SYM>.gates.market` blokkban
(a kapu-ablak oda ment), mint bármely más kapu mérési beállítása.

> ⚠ **2026-10-12 előtt az instrumentum kapcsolta be** (`pairs.<SYM>.market_strategy`,
> „Piac-előszűrő"). Nélküle a kapu NÉMÁN átengedett mindent, hiába volt
> `block`-ra állítva — az instrumentum beleszólt a kapu működésébe. A régi
> kulcsokat a program már nem olvassa (a config-ellenőrző jelzi, ha még ott vannak).

## Sávos hatás (v3.28.0)

A **Hatás** fülön besorolásonként külön hatást adhatsz: `+ Sáv` felvesz egy
kategóriát, a `Törlés` kiveszi. Itt nincs mit sorba rendezni — a piac-állapot
nem skála, hanem kategória:

| besorolás | mi történik |
|---|---|
| Érdektelen | akadályozza a beszállást |
| Oldalazó | kockázatcsökkentés (fele méret) |

Ami nincs felsorolva, azt a kapu átengedi. A lista öröklődik: globális →
instrumentum → instrumentum+stratégia.

> **Sáv nélkül semmi nem változik**: a „kedvezőtlen" halmaz (`adverse`) dönt,
> ahogy eddig.
