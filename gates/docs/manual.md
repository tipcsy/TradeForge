# Manuális előszűrő

A reggeli **kézi piac-áttekintés** eredménye, instrumentumonként. A táblán a
**Kapuk blokk előtt** áll („Kézi” oszlop); a cellára kattintva egy lenyílóból
választod ki a mai állapotot.

| Állapot | Mit csinál |
|---|---|
| **Nincs** | nincs beállítva semmi — nyugodtan kereskedhet |
| **Ne kereskedj!** | minden beszállás gátolva |
| **Óvatosan (fele pénz)** | beszáll, de fele kockázattal |
| **Szép chart ↑** | bika piac: a felfelé belépő mehet, a lefelé gátolva |
| **Szép chart ↓** | medve piac: a lefelé belépő mehet, a felfelé gátolva |
| **Szép chart ↕** | szép chart, mindkét irány mehet |

## Fontos

- **Új nap → minden „Nincs”.** A választás csak aznapra szól (a gép helyi dátuma).
- **Bekapcsolás:** `config.json` → `"manual_filter": {"enabled": true}`. Kikapcsolva
  se oszlop, se hatás.
- **Minden brókerre ugyanaz** (a piac-kép az instrumentumról szól, nem a számláról):
  `data/manual_filter.json`.
- A motorban **kapu**: stratégiánként kikapcsolható
  (`pairs.<SYM>.gates.manual.<stratégia>: "none"`).
- **Backtestben nincs hatása** — a reggeli kézi ítéletnek nincs múltja.
