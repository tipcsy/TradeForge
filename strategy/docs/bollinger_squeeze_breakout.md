# Bollinger Squeeze & Breakout

Belépési jel, amely a Bollinger-sávok összeszűkülését (**squeeze**) és az azt
követő **kitörést** fogja meg. A csendes szakasz után a volatilitás jellemzően
irányt vesz — a stratégia ezt az átmenetet várja.

## Mikor long?

1. **Squeeze aktív** — a BB a Keltner-csatornán BELÜL van **ÉS** a BandWidth az
   elmúlt `bw_lookback` gyertya alsó `bw_percentile` százalékában
2. **A squeeze feloldódik** (az előző gyertyán még állt, ezen már nem)
3. **Trend** *(alapból KI — lásd „Az IRÁNY-VÉTÓ a kapuké")*:
   `ema_fast > ema_slow` és az ár az `ema_fast` fölött
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

## Az IDŐSÍK — a legfontosabb egyetlen beállítás

`signal_tf_min` (15 | 30 | 60 | 120 | 240 perc), alapértelmezés **60**.

A **letöltött** adat M15 marad; a stratégia ebből mintázza fel a jel-gyertyát
(ugyanaz a resample, amit az `ml_ai` és a `tf_align` is használ). Nem kell tehát
új adatforrás, és a váltás egyetlen szám átírása.

A tananyag szerint M15-ön a squeeze gyakran csak 1–2 gyertyáig tart, tehát
„nincs ideje feltöltődni" — a kitörés utána nem hordoz energiát. Megmérve
(7 pár, **három külön** 6 hónapos időszak, hangolatlan paraméterekkel):

| idősík | 2025-02…08 | 2025-08…2026-02 | 2026-02…08 |
|---|---|---|---|
| M15 | 28,6% · **−133$** | 23,0% · **−691$** | 25,1% · **−487$** |
| M30 | 43,6% · +1470$ | 36,9% · +486$ | 44,6% · +2096$ |
| **M60** | **57,9% · +1709$** | **54,1% · +1438$** | **52,0% · +1737$** |
| M240 | 67,9% · +1148$ | 53,5% · +758$ | 65,6% · +1804$ |

**M15 mind a három időszakban veszteséges; M60 mind a háromban nyereséges.** A
találati arány monoton nő az idősíkkal, a kötésszám monoton csökken — a 60 perc
ott van, ahol még van elég kötés (7 páron ~300 / 6 hónap), de a zaj már kezelhető.

> ⚠ Ezek **hangolatlan** alapértékek — épp ezért érdemesek figyelemre: nincs mit
> túlilleszteni rajtuk. De egyetlen paraméter sincs optimalizálva, és a
> `bw_lookback`/`ema_slow` az új idősíkon mást jelent. **Idősík-váltás után
> újraoptimalizálás kell.**

⚠ A warmup a letöltött **M15**-ben értendő, az indikátorok viszont a jel-idősíkon
élnek — a gyertyaszám ezért felszorzódik (H1 → 4×). Enélkül a leghosszabb ablak
végig NaN maradna, és a stratégia némán egyetlen jelet sem adna.

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

> Ezért az alapértelmezés `require_trend_alignment: false`.

### …de a kapu SEM segít — megmérve

Kézenfekvő volt, hogy az `Együtt (tf_align)` kapu vegye át a vétó szerepét. Egy
gond viszont van vele: alapból **M1/M5/M15**-öt néz, ami egy **H1-en döntő**
stratégiának zajt mér, nem kontextust. Ezért a kapu mostantól **stratégiánként
paraméterezhető** (`tf_align.per_strategy`) — és így is megmértük.

7 pár, három külön 6 hónapos időszak, M60-as bollinger, hangolatlan paraméterek:

| kapu | kötés (3 időszak) | találat | **össz P&L** |
|---|---|---|---|
| **KI (nincs vétó)** | 290 / 318 / 319 | 57,9 / 54,1 / 52,0% | **+4884$** |
| Együtt M1/M5/M15 | 251 / 273 / 254 | 55,0 / 52,4 / 49,6% | +3733$ |
| Együtt M15/H1/H4 | 142 / 146 / 149 | — | +1995$ |
| Együtt H1/H4/D1 | 93 / 114 / 109 | 53,8 / 45,6 / 54,1% | **+1483$** |

**Minden kapu-beállítás ront**, és a „helyesebb" magasabb idősíkok rontanak a
legtöbbet. A kapu harmadára vágja a kötésszámot, a találati arányt pedig nem
javítja.

> **Hipotézis** (nem bizonyított): a squeeze-kitörés **volatilitás-tágulási**
> kereskedés, nem trendkövetés. A legjobb kitörések gyakran épp egy oldalazásból
> fordulnak ki, tehát a pillanatnyi trenddel SZEMBEN indulnak — egy trend-vétó
> pont ezeket vágja le.

Ezért az `Együtt` kapu hatása a bollingeren **`none`** marad. A szerkezet készen
áll: ha egy stratégiának mégis kell, `tf_align.per_strategy.<stratégia>` alatt
kaphat saját idősíkokat és `sma_period`-ot, a pár közös beállítása fölé rétegezve.

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

A döntés a **jel-idősíké** (`signal_tf_min`, alapból H1) — a kitörő gyertya adja
a jelet, ahogy a fenti szabályok mondják. Az **M1 pusztán kézbesíti**: a jelzés
után az első M1 gyertyán tüzel, egyszer. Egy feloldási ablakból **egy** belépő
születik (a kitörés további gyertyái nem tüzelnek újra).

## Korábbi mérés (M15-ös idősíkon — MEGHALADVA, lásd fent)

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
