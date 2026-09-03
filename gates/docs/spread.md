# Spread-kapu

A bróker **pillanatnyi spreadjét** a piac mozgékonyságához (ATR) méri. Túl tág
spread — csendes vagy kaotikus piac, hír — esetén kimarad a belépő.

## A képlet

```
határ = max(padló, (ATR / point) × max_spread_atr_ratio)
ok    = jelenlegi_spread ≤ határ
```

A cellában a `250/1312` alak: **jelenlegi / határ**, pontban.

## A három szám

- **Spread ATR-hányada** (`max_spread_atr_ratio`, alap 0,20) — a megengedett
  spread az ATR ekkora része.
- **Padló** (`min_spread_mult`, alap 1,5) — az alsó küszöb az instrumentum
  SAJÁT tipikus spreadjének ennyiszerese.
- **ATR-ablak** (`atr_period`, alap 14) — a volatilitás mércéje.

Mindhárom **stratégia-független**, instrumentumonként:
`data/execution_params/<SYMBOL>.json`.

## Miért relatív a padló

Korábban fix 2,0 „pip" volt — csakhogy a „pip" instrumentumonként mást jelent.
Mérve, mennyit blokkolt a kapu a valós előzményen:

```
GOLD    padló 200 pont, tipikus spread  45  ->  0,1%   gyakorlatilag süket
EURJPY  padló 200 pont, tipikus spread  25  ->  0,8%   gyakorlatilag süket
UK100   padló 200 pont, tipikus spread 139  -> 30,2%   szűrt
```

Ugyanaz a szám az egyik páron mindent átengedett, a másikon a kötések harmadát
vágta. A padló azóta az instrumentum saját normál spreadjéhez mér.

> ⚠ **Amit ez a kapu NEM fog meg.** A padló konstrukció szerint mindig nagyobb a
> pár normál spreadjénél, tehát egy pár a SAJÁT szokásos spreadjén sosem akad
> fenn rajta. Ez a kapu a *kitáguló* spreadet fogja, a *krónikusan drága*
> instrumentumot nem — arra a **Költség/kockázat** kapu való.

## Sávos hatás (v3.28.0)

A kapu hatása nem csak egyetlen igen/nem lehet. A **Hatás** fülön létrát
állíthatsz: `+ Sáv` felvesz egy határt, a `Törlés` kiveszi.

| szint | mi történik |
|---|---|
| 80% | kockázatcsökkentés (fele méret) |
| 100% | akadályozza a beszállást |

**A szint a kapu SAJÁT küszöbének százaléka**: 100% pontosan az a pont, ahol ez a
kapu enélkül is bukna. Ezért hordozható, és ezért öröklődik — globális →
instrumentum → instrumentum+stratégia, ahol nincs beállítva, ott örököl.

> **Sáv nélkül semmi nem változik.** A létra hiánya is létra: egyetlen implicit
> sáv a kapu saját küszöbén, a fent beállított hatással. Amíg nem veszel fel
> sávot, a kapu bitre úgy viselkedik, ahogy eddig.
