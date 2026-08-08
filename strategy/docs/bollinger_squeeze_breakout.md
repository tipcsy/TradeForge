# Bollinger Squeeze & Breakout

Belépési jel, amely a Bollinger-sávok összeszűkülését (**squeeze**) és az azt
követő **kitörést** fogja meg. A csendes szakasz után a volatilitás jellemzően
irányt vesz — a stratégia ezt az átmenetet várja.

## Mikor long?

1. **Squeeze aktív** — a BB a Keltner-csatornán BELÜL van **ÉS** a BandWidth az
   elmúlt `bw_lookback` gyertya alsó `bw_percentile` százalékában
2. **A squeeze feloldódik** (az előző gyertyán még állt, ezen már nem)
3. **Trend**: `ema_fast > ema_slow` és az ár az `ema_fast` fölött
4. **Kitörés**: záróár a felső BB fölött **ÉS** `%B ≥ pb_long_threshold`

## Mikor short?

A fenti tükörképe (alsó sáv, `%B ≤ pb_short_threshold`, fordított EMA-sorrend).

## A kettős squeeze-feltétel

A két feltétel **más kérdésre válaszol**, ezért kell mindkettő:

| | mit mér |
|---|---|
| BB a KC-n belül | a szórás lecsökkent az ATR-hez képest — *relatív* csend |
| BW az alsó percentilisben | a sáv szűk a SAJÁT előzményéhez képest — *történeti* csend |

Csak az elsővel trendes, de egyenletes piac is „squeeze"-nek látszana; csak a
másodikkal egy tartósan szűk instrumentum végig jelezne.

> A `bw_percentile` **gördülő** ablakból számol, nem a teljes mintából. Ez nem
> stílus kérdése: a teljes mintás percentilis a JÖVŐT is látná, és a backtest
> némán felfelé torzulna.

## Az IRÁNY-VÉTÓ a kapuké, nem a stratégiáé

A stratégia iránya abból jön, **melyik sávot törte át** az ár — a felsőt (long)
vagy az alsót (short). Az EMA-trendszűrő ezen felül egy **vétó**: „csak akkor
lépj be, ha a trend is egyetért". Ez nem jel, hanem szűrő — és a szűrés a
**kapuk** dolga (per pár és stratégia állítható, minden stratégián egyformán).

Megmérve (5 pár, 2026-02-01…08-07, hangolatlan paraméterekkel):

| EMA-szűrő | Együtt-kapu | kötés | találat | P&L |
|---|---|---|---|---|
| BE | KI | 399 | 27,1% | −342$ |
| BE | BE | 367 | 28,1% | −247$ |
| **KI** | KI | 766 | 28,7% | −142$ |
| **KI** | **BE** | 700 | **29,4%** | **−31$** |

Az EMA-szűrő **felezi a kötésszámot úgy, hogy a találati arányt nem javítja**
(27,1% vele, 28,7% nélküle) — vagyis nem válogat, csak vág. Az `Együtt` kapu
viszont mindkét esetben javít.

> Ezért az alapértelmezés `require_trend_alignment: false`, és az irány-vétót az
> **Együtt (tf_align) kapura** bízzuk. A paraméter megmarad — kutatásra és arra
> az esetre, ha optimalizálás után máshogy viselkedne —, de alapból nem szól bele.

⚠ A kapu bekapcsolása **nem automatikus**: a váz szabálya szerint egy kapu-hatás
alapból `none`, hogy egy frissítés soha ne kezdjen el némán másképp kereskedni.
A `Együtt` oszlopra kattintva, stratégiánként kell `block`-ra állítani.

## Paraméterek

`strategy/config/bollinger_squeeze_breakout.json`, a paraméter-ablakban
kategóriákra bontva.

| csoport | kulcsok |
|---|---|
| Bollinger | `bb_period`, `bb_std` |
| Összeszűkülés | `bw_lookback`, `bw_percentile` |
| Keltner | `kc_ema_period`, `kc_atr_period`, `kc_atr_mult` |
| Trend-szűrő | `ema_fast`, `ema_slow`, `require_trend_alignment` |
| Kitörés | `pb_long_threshold`, `pb_short_threshold`, `min_bars_since_squeeze`, `max_bars_after_squeeze` |
| SL/TP | `sl_atr_mult`, `tp_rr` |

⚠ A `kc_atr_period` a **csatorna alakja**, nem a végrehajtásé. A méretezés
ATR-periódusa (`atr_period`) a közös `core/execution_params.py`-ban van — ahogy
a BE/trailing és a spread-kapu is. A stratégia az SL/TP **távot** adja pontban;
a lotot és a stop későbbi mozgatását a keretrendszer intézi.

## Jelzés-architektúra

A döntés **mind az M15-é** — a kitörő M15 gyertya adja a jelet, ahogy a fenti
szabályok mondják. Az M1 pusztán kézbesíti: az M15 jelzése után az **első M1
gyertyán** tüzel, egyszer. Egy feloldási ablakból **egy** belépő születik (a
kitörés további gyertyái nem tüzelnek újra).

## Mérés (2026-08-08, ALAPÉRTELMEZETT paraméterekkel)

Backtest 2026-02-01 … 08-07, páronként 1000$:

| pár | kötés | találat | PF | P&L |
|---|---|---|---|---|
| Ger40 | 78 | 35,9% | 0,91 | −46$ |
| UsaTec | 63 | 28,6% | 0,56 | −159$ |
| GOLD | 100 | 22,0% | 0,82 | −84$ |
| EURUSD | 85 | 21,2% | 0,45 | −75$ |
| UsaInd | 73 | 30,1% | **1,20** | +21$ |

> ⚠ **Ez NEM a stratégia teljesítménye, hanem a kiindulási ponté.** A számok
> hangolatlan alapértékekkel készültek — az `Opt` gomb még nem futott le egyik
> páron sem. RR 2-nél a nullszaldó 33,3%: a Ger40 (35,9%) és az UsaInd már
> fölötte van, a többi nincs. A következő lépés a **páronkénti optimalizálás**,
> és csak az utána mért OOS-eredmény mond bármit.

## Továbbfejlesztési irány

Az M1 jelenleg csak kézbesít. Egy **M1-en finomított belépő** (a kitörés
elkapása az M15 zárása előtt) kevesebb csúszást adhat — de ez a stratégia
karakterét változtatja meg, ezért külön mérendő, nem alapból bevezetendő.
