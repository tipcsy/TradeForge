# Volatilitás — „elég mozgékony-e most ez a piac?"

Az oszlop egyetlen számot mutat: a **mostani ATR a kalibrált mércéhez képest**.

```
0.51×   →  az ATR a mérce fele            (⛔ a sáv alatt)
1.00×   →  pont annyi, amennyire hangolva lett
1.37×   →  élénkebb a szokásosnál
```

## Valódi kapu — a hatása állítható (v3.27.0)

Ez a kapu sokáig **csak mutatott**: a szűrés a stratégia belépő-hookjában
(`bt_entry`) futott, feltétel nélkül, és a kapu-ablakban nem lehetett hozzányúlni.
Ez félrevezető volt — egy kapu, ami nem dönt, nem kapu.

Mostantól itt, a kapu-ablakban kap hatást, mint a többi:

| hatás | mit tesz |
|---|---|
| **Akadályozza a beszállást** (alap) | a sávon kívüli ATR-nél nincs belépő — ez a v3.27.0 előtti viselkedés |
| **Kockázatcsökkentés** | belép, de fele mérettel |
| **Ki** | a kapu **tényleg** nem szűr — a stratégia sem |

> **A küszöbök továbbra is a stratégia paraméterei** (`atr_min_pct`,
> `atr_max_pct`), nem a kapu configjában laknak. Ezért ez az egyetlen
> **paraméter-vezérelt** kapu: az optimalizáló és a söprés ugyanezeket a
> számokat söpri, és emiatt az `exec_gates=False` („ne modellezd a végrehajtási
> kapukat") ezt a kaput **nem** kapcsolja ki — különben a söprés olyan
> paramétert mérne, aminek nincs hatása.

> **⚠ A Beállításokban kikapcsolt oszlop most már a szűrést is leveszi.**
> v3.27.0 előtt a `gate_order`-ből kivenni pusztán megjelenítési döntés volt. Ha
> korábban azért vetted ki, mert „úgyis csak mutat", kapcsold vissza — a
> program a naplóban is szól róla (`volatility_gate_off`).

## Miért lett külön oszlopa

2026-08-08-ig ez volt az **egyetlen blokkoló ok, ami sehol nem látszott**. A
BTCUSD hetekig némán nem kereskedett:

| | |
|---|---|
| mérce (`atr_avg_ref`) | 272,75 |
| friss ATR-medián | **140,19** |
| arány | **0,51×** |
| engedett sáv | 245,5 … 872,8 |
| a gyertyák hány %-a fér bele | **6,0%** |

30 nap alatt 26 belépő-jel keletkezett, és **mind a 26 elbukott ezen a szűrőn**.
A charton egyetlen jelölő sem jelent meg, élesben egyetlen kötés sem született —
és semmi nem árulta el, miért. A többi páron ugyanez nem látszott (Ger40 1,00× ·
GOLD 0,97× · UsaTec 1,34×): a BTC volt az egyetlen, ahol a volatilitási rezsim
elmozdult.

## A mérce kétféle lehet

| `atr_baseline_bars` | mérce | mikor |
|---|---|---|
| **0** (alap) | az optimalizáláskor mentett `atr_avg_ref` — **befagyasztott** | a backtest reprodukálható, több letöltött előzmény nem billenti el |
| **> 0** | gördülő ablak N M15 gyertyára (96 = 1 nap) | követi a rezsimváltást |

A befagyasztott mérce hátránya pont a fenti eset: ha az instrumentum
volatilitása tartósan elmozdul, a szűrő **jelentése** vele csúszik, és a pár
némán leáll. A gördülő mérce ezt követi, és ugyanúgy reprodukálható (bárokban
van definiálva, nem a letöltött előzmény hosszában).

> **Az alapértelmezés nem véletlen.** Megmérve (7 pár, 2026-07-01…08-07): a
> gördülő mércével a BTCUSD 0 helyett 5–8 kötést ad, de azok veszteségesek
> (−11…−19$), és a portfólió eredménye zajszinten változik (+1053$ →
> +1050…+1103$). Nincs mérési alapja az átkapcsolásnak — a mechanizmus
> rendelkezésre áll, páronként.

## Mit tegyél, ha ⛔-t látsz

1. **Nézd meg az arányt.** 0,9× alatt „túl csendes", a plafon fölött „túl
   kaotikus" — a kapu-ablak `Beállítás` lapja kiírja, melyik.
2. **Ha tartósan a sáv alatt van**, az instrumentum kikerült abból a
   volatilitási rezsimből, amire hangolva lett. Két út: gördülő mérce
   (`atr_baseline_bars`), vagy a `atr_min_pct` újragondolása.
3. **Újraoptimalizálás önmagában nem elég**: az `atr_avg_ref` a teljes
   előzményből számol, tehát ugyanaz a szám jönne ki újra.
