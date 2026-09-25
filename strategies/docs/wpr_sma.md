# wpr_sma — WPR + SMA trendkövető

Két idősíkot használ: a **magasabb** (M15) adja az irányt és a „jó zónát", a
**alacsonyabb** (M1) az időzítést.

## Az alapötlet

- Az **SMA** mondja meg a trend irányát: a záróár az SMA fölött = vételi oldal,
  alatta = eladási oldal. **A stratégia trendkövető** — nem fade-el, nem
  mean-reversion.
- A **Williams %R (WPR)** a belépő időzítése: a trend irányába akkor lép be, amikor
  az ellenkező szélsőségből visszafordul (vagyis egy visszahúzás után).

## Az állapotgép

Nem elég egy gyertya: a belépő **két fázisban** dől el.

1. **Felfegyverzés** — a magasabb idősík (M15) zárt gyertyáján a WPR belép a
   szélsőségbe, és az SMA-irány megengedi. Ettől kezdve az ablak **NYITVA** van.
2. **Tüzelés** — az alacsonyabb idősíkon (M1) a WPR **átüti** a trigger-szintet a
   trend irányába.

> **Miért fázisokban.** A korábbi, szomszédos-gyertyás M1-belépő a **fokozatos
> átütést kihagyta** (a BUY gyakorlatilag sosem tüzelt). Ezért lett belőle
> ugyanolyan felfegyverez → tüzel állapotgép, mint az M15-en. (v1.25.0)

## Amit érdemes tudni

- Az M15 ablak **mély bemelegítést** igényel: a „jó zónát" akár egy RÉGI szélsőség
  élesíti, ezért a jelzés-állapot visszajátszása mélyebb, mint az indikátor-warmup
  (`signal_warmup_bars`).
- A **szürke (no-trade) óra** opcionálisan **reseteli** az M15 ablakot
  (`no_trade_resets_signal`, alapból **KI**).
- Az SL-módszer alapból **`swing20`** (az elmúlt 20 gyertya szélsőértéke), nem ATR.

## Fő paraméterek

| paraméter | mit szabályoz |
|---|---|
| `sma_period` | a trend-irány simítása a magasabb idősíkon |
| `wpr_period` | a WPR ablaka (magasabb idősík) |
| `wpr_m1_period` | a WPR ablaka az időzítő idősíkon |
| `wpr_entry` | a szélsőség, ami FELFEGYVEREZ |
| `wpr_trigger` | az átütési szint, ami TÜZEL |
| `tp_rr_ratio` | a TP a stop-távolság szorzójaként |

> **⚠ A Volatilitás-kapu használata fontos.** A régi „Piac-szűrő"
> (`atr_min_pct`/`atr_max_pct`/`atr_baseline_bars` + `atr_avg_ref`) pontosan a
> **Volatilitás-kapu** küszöbe volt, ezért v3.103.0-ban kikerült a stratégiából:
> az instrumentumé lett, és a kapu ablakában állítható. A 14 hangolt készlet
> ezzel a szűrővel **együtt** lett kalibrálva, ezért wpr_sma-ra a kapu alapból
> **akadályozza a beszállást**. `Ki`-re állítva a stratégia más szabályokkal fut,
> mint amire hangolva lett. Az optimalizáló a küszöböket már nem hangolja.

> A `tp_rr_ratio` keresési tartománya **0,5–3,0** — szándékosan lefelé is nyitott,
> a „gyors beszálló / gyors kiszálló" elv miatt.

## Ismert korlátok

- A volatilitás-kapu felső küszöbe (`atr_max_pct`) volt a **délutáni belépők
  hiányzásának gyökere** — ha kevés kötést látsz egy sávban, a `Volatilitás`
  oszlopot érdemes először megnézni.
- A trailing **ATR-szorzóval** működik (`trail_activation_atr` /
  `trail_distance_atr`); a régi, abszolút pontos értékek instrumentumonként
  összemérhetetlenek voltak.
