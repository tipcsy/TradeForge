# Trend-visszahúzódás (`trend_pullback`)

Belépési jel, amely **erős emelkedő trendben, élénk piacon** egy rövid
**visszaesésre** vásárol. A három feltétel három **különböző időkeretről** jön —
ez a lényege: a nagyobb keret adja a kontextust, a kicsi az időzítést.

Nem kitalált szabály: a `tools/research/` keresőrendszer találta 231 000
jelöltből, és mintán kívüli teszten igazolódott. A származása és a
korlátai alább.

## Mikor long?

Mindhárom feltétel egyszerre, és a belépő a **felfutó élen** (amikor az
együttállás igazzá *válik*, nem amíg igaz):

| # | időkeret | feltétel | mit jelent |
|---|---|---|---|
| 1 | **H1** | ár > Keltner(14; 2,0) **felső** sávja | erős emelkedő trend |
| 2 | **M30** | ATR(14) > az ATR 200-as átlaga | él a piac, van mozgás |
| 3 | **M5** | stoch(14) %K keresztezi **lefelé** a %D-t | rövid visszahúzódás |

Az 1–2 a *kontextus* (megmarad órákig), a 3 az *esemény* (egyetlen gyertya).
Ezért van értelme: nem a kitörést vesszük meg, hanem a trenden belüli
visszaesést.

**SL** = M15 ATR × `sl_atr_mult` · **TP** = SL × `tp_rr_ratio` (pontban).

## Mikor short?

**Soha.** A short irányt a kutatás külön mérte: a keresés mind a hat short
jelöltje **veszített** a valódi motoron. Ez nem hiányosság, hanem eredmény — ne
„szimmetrizáld".

## A felfutó él — miért nem elég, hogy „igaz az együttállás"

Az első mérésem minden gyertyát értékelt, amíg az együttállás állt, és
**+0,029 R**-t mutatott. A valódi motoron viszont **−0,022** lett. Az ok:

> az él az **időszakon** oszlott el, nem a **belépés pillanatában** volt.

Vagyis a minta jó *időszakot* jelölt ki (piac-időzítés), de a belépés
pillanatában nem volt előny. Egy állapot-jellegű feltétel több száz gyertyán át
igaz marad; a motor viszont egy pozíciót nyit rá. A javítás után (`felfutó él`)
a jel **átment** a motoron. Lásd `on_bar_close` / `bt_on_low_close`.

## Származás és igazolás

| lépés | mit tett | eredmény |
|---|---|---|
| keresés | 231 000 jelölt, **2017–2022** | a mintát itt választottuk |
| holdout | **2023–2026**, addig ÉRINTETLEN | R **+0,1225**/kötés, **t = +2,94** |
| valódi motor | `run_pair` slottal, kapukkal | **4/4 pozitív év** |
| sodródás-teszt | a swap költség-e vagy forrás | **költség** — nélküle jobb |
| napon belüli? | tartás-eloszlás | **medián 1,8–3,4 óra** |

### A 2017–2022-es „laposság" — megoldva

Első ránézésre a minta csak 2023 óta működött (+125 $ hat év alatt vs +955 $
négy év alatt), ami a Nasdaq-emelkedés gyanúját vetette fel. **Nem az volt.**

| szakasz | nettó R | **swap nélkül** | a swap ára R-ben |
|---|---|---|---|
| 2017–2022 | +0,0117 | **+0,2569** | **+0,2452** |
| 2023–2026 | +0,1416 | **+0,2214** | +0,0798 |

Swap nélkül a két korszak **azonos** — az él 2017 óta végig ott volt. Ami
változott, az a swap terhe R-ben: **0,449 → 0,047** (tízszeres csökkenés).
Mechanikus ok: a swap devizában ~állandó, a stop-távolság viszont az **árral**
skálázódik. A UsaTec 2017-ben ~5000 ponton állt, ma ~20000-en, ezért a
kötésenkénti kockázat 2,47 $-ról 21,78 $-ra nőtt.

## ⚠ Csak UsaTec-en igazolt

16 instrumentumon lemérve **egyedül ott ment át**. A kép viszont árnyalt:

| sym | nettó R | bruttó R | költség | értékelés |
|---|---|---|---|---|
| **UsaTec** | **+0,1821** | +0,2108 | 0,0288 | igazolt |
| UsaInd | +0,0986 | +0,1340 | 0,0354 | a jel működik, a költség elviszi |
| Usa500 | −0,0355 | +0,0304 | 0,0659 | ugyanaz, gyengébben |
| Ger40 | −0,0365 | +0,0133 | 0,0499 | ugyanaz, gyengébben |
| GOLD | −0,0447 | +0,0177 | 0,0624 | ugyanaz, gyengébben |
| UK100 · Euro50 · FX · BTC | negatív | **negatív** | — | a jel sem működik |

A bruttó öt páron pozitív, és a nettó sorrend a **költséget** követi. Más páron
tehát nem eleve reménytelen — de **csak saját méréssel** élesítsd.

## Mi NEM ezé a modulé

> A stratégia **beszállási jelző**. Ami a belépés UTÁN történik, az nem az övé.

A breakeven, a trailing és a cost-cut a **kockázatcsökkentésé**
(`core/risk_reduction.py`, per pár). Mérve, a UsaTec holdouton:

| beállítás | n | R/kötés | t | nettó$ |
|---|---|---|---|---|
| **`off` preset (BE + trailing), cost_cut ki** | 711 | **+0,1058** | **+2,75** | **+954,8** |
| ugyanaz + cost_cut 24 | 667 | +0,0836 | +2,24 | +764,9 |
| trailing ki + cost_cut 24 | 669 | +0,0937 | +2,06 | +861,9 |

**A pár jelenlegi beállítása a legjobb** — nincs mit átállítani. És egy
tanulság: a `cost_cut` **trailing nélkül** segít, **trailinggel** ront. Mindkettő
korán zár, együtt már túl sok. *Egy kilépési paraméter csak a többi ismeretében
értelmezhető.*

⚠ A kockázatcsökkentés **per PÁR** van tárolva. A UsaTec-en három stratégia fut,
és **osztoznak rajta** — a `trend_pullback`-re hangolt kilépés a Bollingert
27%-kal rontotta volna (+1148 $ → +833 $). Mielőtt itt bármit állítasz, mérd meg
a páron futó ÖSSZES stratégiára.

## Paraméterek

`strategies/config/trend_pullback.json`:

| kulcs | alap | mit állít |
|---|---|---|
| `stoch_period` · `stoch_d` | 14 · 3 | az M5 belépő |
| `atr_ref_period` | 200 | az M30 volatilitás-küszöb hossza |
| `keltner_period` · `keltner_mult` | 14 · 2,0 | a H1 trend-csatorna |
| `sl_atr_mult` · `tp_rr_ratio` | 1,5 · 2,0 | SL/TP az M15 ATR-ből |

Az **időkeretek** (M5 / M30 / H1) **nem paraméterek**: a keresés ezeken találta,
és a kombináció együtt érvényes.

### Az ATR definíciója — ne cseréld el

A modul az ATR-t a true range **egyszerű mozgóátlagaként** számolja, nem
Wilder-simítással — pedig az utóbbi a szabványosabb. Ez **szándékos**: a
validálás az egyszerű átlaggal készült, és a két definíció a jelek **0,3%-án**
eltér. A „jobb" változat egy *másik, nem tesztelt* stratégia lenne. Csere csak
újravalidálással.

## Amit még nem tudunk

Minden szám mintán kívüli **backtest**. A stratégia **még nem futott élő
piacon** — az egyetlen hátralévő teszt az idő. Kis mérettel érdemes kezdeni.

A `t = +2,94` biztató, de nem megcáfolhatatlan, és a nagyságrend
**~20–25 %/év** kötésenkénti 1 % kockázattal — nem napi 1 %.
