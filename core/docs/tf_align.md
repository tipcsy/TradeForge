# Idősík-együttállás („Együtt")

Idősíkonként megnézi, hogy az ár az SMA **fölött vagy alatt** van-e, és azt
kérdezi: mutat-e MIND egy irányba?

```
irány(idősík) = előjel(záróár − SMA(sma_period))
```

A cella pöttyei idősíkonként az irányt mutatják: **zöld** = fel, **piros** = le,
**halvány** = semleges.

## Beállítások

- **Bekapcsolva** — ez tölti az „Együtt" oszlopot és ad bemenetet a kapunak.
- **Figyelt idősíkok** (2–6, alap M1/M5/M15) — egyetlen idősík nem „együttállás".
- **SMA-periódus** (alap 50).
- **SMA-vonalak a charton** — csak rajz, a figyelés ettől függetlenül működik.

A mért állapot **instrumentum-tulajdonság**, a kapuzás viszont **stratégiánként**
állítható.

## Irány-tudatos

Ez a kapu nem egyszerűen „blokkol vagy nem": a **jel irányát** nézi. Egy BUY jelet
a lefelé mutató együttállás blokkol, egy SELL-t nem. Ezért a sor csak azt tudja
megmutatni, hogy van-e egyáltalán együttállás — a végleges döntés a motoré, ahol
a jel iránya is ismert.

> A kapu a `tf_align.gate` LISTÁBÓL is örökölhet (régi config-alak). Ha a hatás
> „örökölt", és nem ezen a páron állítottad be, az ablak kiírja, honnan jön.
