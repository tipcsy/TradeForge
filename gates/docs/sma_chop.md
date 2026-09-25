# SMA-oldalazás — átütötte-e az ár az SMA-t a közelmúltban?

Trendben az ár az SMA **egyik** oldalán halad. Ha a közelmúltban átment a másik
oldalra, a piac oldalaz: az SMA-irány ilyenkor zaj, és egy trendkövető belépő
véletlenszerű irányba lép be.

## A szabály

Az utolsó `lookback` **lezárt** gyertyában hányszor váltott oldalt a záróár az
SMA-hoz képest? Ha **többször**, mint `max_crosses`, akkor oldalazás van, és a
kapu **bukik**. Irányfüggetlen: BUY-t és SELL-t ugyanúgy szűr.

| paraméter | alap | jelentés |
|---|---|---|
| `timeframe` | M1 | ezen az idősíkon |
| `sma_period` | 50 | az SMA hossza |
| `lookback` | 20 | ennyi lezárt gyertyán számolunk |
| `max_crosses` | 0 | ennyi átütés még belefér — 0 = egy is blokkol |

Átütés = két **egymást követő** gyertya záróára az SMA **különböző** oldalán
van. A pontosan az SMA-n záró gyertya az előző oldalát örökli, így egy érintés
nem számít kétszer.

> A felhasználó emléke szerint „ezt már csináltuk egy indikátorral". A kódban és
> a jegyzetekben nem találtuk (2026-09-25). A legközelebbi meglévő a
> **Lendület**-kapu alapjárata, az viszont a gyors és a lassú SMA
> **távolságát** méri, nem az átütéseket.

## Mérve (2026-09-25) — ⚠ zajszintű hatás

14 wpr_sma pár, 2025-11-01 – 2026-09-24, él-paritású backtest (`run_pair`):

| változat | kötés | R/kötés |
|---|---|---|
| kapu nélkül | 6445 | −0,143 |
| SMA-oldalazás, **M1** / SMA50 / 20 / 0 | 2812 | −0,126 |
| SMA-oldalazás, **M15** / SMA50 / 20 / 0 | 3283 | −0,157 |

A kötések felét elveszi, a kötésenkénti eredmény pedig a mintanagysághoz képest
**nem változik érdemben** (±0,015 R). Ezért a kapu **alapból ki van kapcsolva**
(`none`).

## Hol dönt

Jelzés-fázisú kapu (a terv előtt). Élesben, egypáros és portfólió-backtestben és
a charton (viz) is ugyanazzal a méréssel.
