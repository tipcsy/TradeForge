# Gyertyaszint-törés (`candle_level_break`)

Egy **H4 fordulószinten** vár, és akkor lép be, amikor az ár a szint visszatesztje
után egy szűk **M15 konszolidációs sávból** kitör. A nagyobb keret adja a szintet,
a kicsi az időzítést.

> ⚠ **Ez a stratégia MÉRVE VAN, és nem talált élt.** Élesítés előtt olvasd el a
> *Mit mutatott a mérés* szakaszt — a modul működik és tesztelt, de nincs
> bizonyíték arra, hogy pénzt keresne.

## Mikor lép be?

Négy lépcső, sorrendben (LONG; SHORT tükrözve):

| # | időkeret | mi történik | mit jelent |
|---|---|---|---|
| 1 | **H4** | a swing-alj gyertyájának a **teteje** | ez a szint — fordulást várunk róla |
| 2 | **H4** | egy gyertya **teste** a szint fölé zár | a szint elesett |
| 3 | **H4** | az ár visszatér a szinthez, de a teste nem zár alá | a szint tartja magát ellenállásból támaszként |
| 4 | **M15** | szűk konszolidációs sáv, majd egy gyertya a sáv **csúcsa** fölé zár | a belépő |

**SL** = a szint alatt `stop_buffer_atr` × ATR · **TP** = SL × `tp_rr_ratio`
(pontban).

## Honnan jön

Egy YouTube-videó módszeréből („Hogyan alkossunk saját Forex stratégiát").

⚠ **Ez a mi változatunk, nem a szerzőé.** A videó több ponton nem elég objektív
(„momentum gyertya", trendvonal-illesztés, a belépő pillanata), és a szerző a
pontosító kérdésekre nem válaszolt. A hiányzó döntéseket mi hoztuk meg — a
kódban `[DÖNTÉS]` jelöléssel. A mérés is erre a változatra vonatkozik.

Két ilyen döntés:

* **A „momentum gyertya" elkerülhető.** A képen bekarikázott formáció 2-3 apró
  gyertya a szinten, a belépő pedig az utánuk jövő kitörés. Így nem kell
  megválaszolni, hogy „mekkora a momentum gyertya?": a kitörés a **sáv csúcsán**
  mérhető, küszöb nélkül.
* **A trendvonalat nem implementáljuk.** A rövid trendvonal kitörése gyakorlatilag
  ugyanaz, mint a sáv csúcsának átütése; a hosszú pedig szubjektív (mely
  csúcsokra illesztjük?).

## Miért H4 a szint?

Mérve, 2026-08-23 — a szintek **sűrűsége** és a köztük lévő út **költsége**:

| idősík | szint / hó | szint-táv spreadben (Ger40 / GOLD / EURUSD / UsaTec) |
|---|---|---|
| M15 | 230–300 | 13,9 / 17,9 / **4,2** / 20,6 |
| H1 | 60–75 | 33,4 / 41,0 / 10,2 / 49,5 |
| **H4** | 17–19 | 69,2 / 77,4 / 19,9 / 107 |
| D1 | 3 | 118 / 269 / 57,8 / 261 |

M15 szintekkel az EURUSD-n a teljes út szinttől szintig **4,2 spread** — a
költség megeszi. D1-en viszont 3 szint/hó/pár, ami a kötésszám-korlátokat
belátható időn belül nem érné el. A H4 a kettő között áll.

A keret adat-csővezetéke M15+M1, ezért a H4-et **belül** mintavételezzük az
M15-ből (ugyanúgy, ahogy a `bollinger_squeeze` a saját jel-idősíkját).

## Mit mutatott a mérés

**A stratégia a kill-teszten bukott el, a hangolás előtt** (2026-08-23).

A `stop_buffer_atr` söprése (0,1 → 1,0) a tanuló félen, profit-faktorban:
**7 párból 1-en** ért el PF > 1 — és az az egy pontosan **1,00**, azaz nulla,
költség előtt. A vizsga félen **0/7** teljesítette az előre rögzített olvasatot
(PF > 1,1 és ≥ 50 kötés).

⚠ **És ami a lelet érdemi része:** a találati arány mindenhol **a szükséges érték
körül vagy alatta** van. Ger40: 36,7% találat 36,6%-os követelmény mellett — ez
nem él, hanem véletlen egyezés. A belépő-jelnek tehát **nincs iránytartalma**:
pont annyiszor talál, amennyiszer a kockázat/hozam aránya megköveteli.

A hipotézis is eldőlt. A spec szerint „az él csakis a szűk stopból jöhet". A szűk
stop iránya **helyes** (0,1-en a legjobb 4/7 páron), de nem hoz élt: **a találati
arány pont annyival esik, amennyivel az RR nő** — a kettő kioltja egymást. Ez a
„nincs él" mérési aláírása: az expektanciát a stoppal nem lehet előállítani, csak
a kockázatot tologatni.

> Nem implementációs hiba: a strukturális hozam/kockázatot a modul **előtt**
> mértük 0,6–0,9-nek (1 alatt), és a mért PF pontosan az, amit a szerkezet előre
> jelzett. A kód azt csinálja, amit terveztünk; a módszer nem működik.

**Ráadás:** a kötések **0–5%-a zár TP-n** — a `tp_rr_ratio` itt is majdnem
hatástalan, ugyanaz a kép, mint a `wpr_sma`-nál.

## Paraméterek

| kulcs | mit állít |
|---|---|
| `swing_bars` | hány H4 gyertyából számít swing-aljnak/csúcsnak |
| `level_ttl_bars` | meddig él egy szint, ha nem történik vele semmi |
| `retest_atr` | mekkora ATR-távolságon belül számít visszatesztnek |
| `cons_bars` | hány M15 gyertyából áll a konszolidációs sáv |
| `cons_max_atr` | mennyire kell **szűknek** lennie a sávnak |
| `stop_buffer_atr` | a stop távolsága a szinttől (ATR-ben) |
| `tp_rr_ratio` | a célár a stop hányszorosa |
| `atr_min_pct` / `atr_max_pct` | volatilitás-szűrő a közös mércéhez képest |
