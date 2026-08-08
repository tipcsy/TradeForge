# Volatilitás — „elég mozgékony-e most ez a piac?"

Az oszlop egyetlen számot mutat: a **mostani ATR a kalibrált mércéhez képest**.

```
0.51×   →  az ATR a mérce fele            (⛔ a sáv alatt)
1.00×   →  pont annyi, amennyire hangolva lett
1.37×   →  élénkebb a szokásosnál
```

## ⚠ Ez az oszlop MUTAT, nem dönt

Minden más kapu (Spread, Együtt, Piac, Lendület, Költség) itt, a kapu-ablakban
kap hatást. **Ez nem.** A volatilitás-szűrés a stratégia belépő-hookjában
(`bt_entry`) történik — ott, ahol a backtest, a viz és az él **közös** kapuja
van. Ha itt is lehetne hatást állítani, az vagy duplán szűrne, vagy `none`-ra
állítva azt ígérné, hogy kikapcsoltad a szűrést, holott a stratégia tovább szűr.

A szűrő számai a **stratégia paraméterei** (`atr_min_pct`, `atr_max_pct`), a
Piac-szűrő kategóriában.

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
