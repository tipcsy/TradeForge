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

- **Piac-osztályozó** — `pairs.<SYM>.market_strategy`. „Nincs" → a kapu néma.
- **Kedvezőtlen besorolások** — alap: *Érdektelen* + *Bizonytalan*.
- **Piac-sáv a charton** — csak rajz.

> ⚠ **Két dolog kell hozzá.** A hatás beállítása önmagában kevés: a páron KI IS
> KELL VÁLASZTANI egy osztályozót, különben a kapunak nincs mit mérnie, és sosem
> tüzel. A config-ellenőrző szól, ha ez az állapot előáll.

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
