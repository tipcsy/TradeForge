# Lendület — a piac „fordulatszáma"

Folytonos, **előjeles**, normált mutató: az előjel az irány, a nagyság az, hogy
mennyire pörög a piac. A metafora pontos — rálépsz a gázra, a mutató kileng,
majd visszaáll alapjáratra. A gyors átlag ilyenkor elszakad a lassútól.

## Két mérési alap

- **Egy idősík, 3 SMA** (8/32/100) — két „fordulat" adódik (gyors↔közép,
  közép↔lassú), az átlaguk a mutató. Ez a legszorosabb fordulatszámmérő.
- **Három idősík** (alap M1/M5/M15) — idősíkonként (záróár − SMA), átlagolva.

Mindkettő UGYANAZZAL a mércével oszt: az utolsó `vol_window` gyertya átlagos
abszolút záróár-elmozdulása. Ettől jelent **0,35 ugyanazt** GOLD-on és EURUSD-n,
és ettől hordozható a küszöb a két alap között.

## Az állapot-szótár

A mutatónak **pontosan két állapota** van, plusz az adathiány — nincs több
fokozat, tehát nem érdemes „élénkülő” vagy „lassuló” kiírásra várni:

| állapot | mikor | mit tesz a kapu |
|---|---|---|
| **alapjárat** | \|fordulat\| < küszöb | bukik (a beállított hatás szerint) |
| **fut** | \|fordulat\| ≥ küszöb | átenged |
| nincs adat | még nincs elég gyertya | átenged (fail-open) |

A „fut” szándékosan semleges: azt jelenti, hogy **a piac nem áll** — nem azt,
hogy kimondottan élénk. A mértéket a szám adja meg, nem a szó.

## Mit figyeljen (stratégiánként)

- **Alapjárat** — a piac áll (|fordulat| < küszöb) → ne kössünk bele.
- **Irány-szűrő** — a fordulat SZEMBEN megy a jellel → ne kössünk ellene.
- **Mindkettő**.

## Mérés (2026-08-07, 5 pár, ~20 000 M15 gyertya)

`wpr_sma`:

```
kapu KI          1625 kötés   4342 $   PF 1,56   maxDD 42,5%
alapjárat 0,35   1563         4394     PF 1,59   maxDD 40,3%
alapjárat 0,75   1472         4165     PF 1,60   maxDD 33,9%
IRÁNY-szűrő      1559         3876     PF 1,52   maxDD 42,3%
```

**Az alapjárat-szűrő nem profit-termelő, hanem drawdown-csökkentő.** A +1,2%
(0,35-nél) 1625 kötésen zaj; a valódi hozadék 0,5–0,75 között ~20% relatív
DD-csökkenés ~4% profit áráért.

> ⚠ **Az IRÁNY-szűrő `wpr_sma`-n KÁROS** (−10,7% profit, rosszabb PF, és a
> drawdownt sem csökkenti). Valószínű ok: a `wpr_sma` belépője mean-reversion
> jellegű, az irány-szűrő pedig trend-követő logikát erőltet rá — ráadásul a
> TF-együttállás már csinál valami hasonlót, hangoltan.

`ml_ai`-on fordítva: ott az alapjárat-szűrő csak árt, az irány-szűrő viszont
valódi minőség-szűrő — de a kötések felét eldobja, és a profit is feleződik.
