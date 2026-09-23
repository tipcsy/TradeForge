# Csilla beszállója (`csilla`)

Szerkezet-törés **két idősíkon**, ahogy a felhasználó 2026-09-23-án chartról
chartra végigvezette: a **felső idősík áttöri a saját utolsó igazolt swingjét**,
majd megvárjuk a korrekció végét jelző gyertyát (**pipa**), és onnantól az
**alsó idősíkon** lépünk be minden counter-trend korrekció törésekor. A szabály
a `strategies/csilla_rules.py`-ban van, amit a kutató-labor is ugyanígy hív.

⚠ **H4 a plafon — ez daytrade.** A jegyzet négy idősík-párt sorol fel; a felső
kettő (W1-D1, D1-H4) nem használható. A `csilla_rules.MAX_TF_MIN` ki is
kényszeríti, és ez **csak erre a stratégiára** vonatkozik.

## A lánc

| lépés | mi történik |
|---|---|
| **1. jelzés** (felső) | a felső idősík egy gyertyája **ZÁR** a saját utolsó igazolt swingjén túl (`k_hi` = 3 → a swing 3 gyertyával később igazolódik). Egy swing egyszer törhet. Címke: folytatás / fordulat / trend nélkül, a két-két utolsó swingből. |
| **érvényesség** | **időkorlát nincs**: a setup addig él, amíg az ár nem zár a **törés előtti szélsőérték** túloldalára — az az „új HH", ami a trendfordulót érvényteleníti. |
| **2. jelzés — pipa** (felső) | a korrekciót **elnyelő** gyertya: a korrekció kiindulási szintje (`P0` = a tető előtti `pipa_w1` = 5 gyertya legalacsonyabb zárása) alá zár, és ez az **első** ilyen zárás a tető óta. A korrekció magassága ≥ `pipa_melyseg` (1) ATR, a jelző gyertya ≥ `pipa_min_tart` (0,5) ATR. ⚠ **Szár-arány nincs** (ebben tér el a `candle_lib.pipa` ✓-definíciójától). |
| **belépők** (alsó) | a pipa gyertya lezárása után **több** belépő: minden counter-trend korrekció (emelkedő aljak, legalább `korr_min` = 3 gyertya) törésekor. Ha a törő gyertya **rossz színű** (short-setupnál zöld), megvárjuk a következő jót, és annak a zárásán lépünk be (`belepo_mod` = `varj_pirosra`). |
| **napszak** | NEM a stratégia paramétere: a keret stratégia-hatókörű **kereskedési órái** (`data/optimized_params/csilla/<PÁR>_hours.json`). A stratégia minden órában jelez, az óra-kapu dönt. |

**SL** = a **korrekció teteje + spread** — belépőnként más. A keret
`sl_tp_points`-ja csak a felső sort látja, ezért a `bt_on_low_close` a belépő
pillanatában páronként félreteszi a stopot, és a `sl_tp_points` onnan veszi.
**TP** = SL × `tp_rr_ratio` (alap 30 R, azaz gyakorlatilag nincs célár).

## A jelölő-pöttyök (öt állomás)

A live tábla `Csilla` blokkjában öt pötty mutatja, hol tart a lánc:

| pötty | mit jelent |
|---|---|
| **szerk** | él egy szerkezet-törés (zöld = felfelé, piros = lefelé) |
| **korr** | a törés megvolt, a korrekció épül, a pipa még nincs (sárga) |
| **pipa** | a pipa megvolt → nyitva a belépő-ablak az alsó kereten |
| **zaszlo** | az alsón épp épül egy elég hosszú counter-trend korrekció (sárga) |
| **belep** | az utolsó zárt alsó gyertya belépőt ad |

## A kilépés — NEM a stratégiáé

A mért (forward-tesztelt) változat kilépése: **BE +0,67 R-nél**, utána
**2 R-es csúszó stop**, célár nélkül, max 5 nap. Ezt a pár
**kockázatcsökkentésében** kell beállítani: `breakeven_r = 0,67`,
`trail_activation_atr = 3,0`, `trail_distance_atr = 3,0` (2 R = 3 ATR15),
preset `off`. A célár azért messze, mert az R-alapú BE-t a távoli célár nem
kapcsolja ki.

## Mit mértünk, és mit nem

8 pár, 2013–2026 (tick-alapú M1), teljes költség:

| változat | R/kötés | év poz. | pár poz. |
|---|---|---|---|
| minden fraktál-szint, M1-stop (első olvasat) | −0,22 | 0/14 | 0/8 |
| D1/W1 szintek, M15-stop (ez a modul, sáv nélkül) | −0,07 | 3/14 | 3/8 |
| **Csilla-sáv** (Ger40 de., UsaTec+GOLD US-nyitás), fix 1,5 ATR15, BE 0,67 R, 2R csúszó | **+0,12** (t = 1,5) | 9/14 | 3/3 |

A sáv volt az egyetlen cella, amit a felhasználó **előre** nevezett meg, és
minden kimenet-változatban pozitív előjelet adott — de **t < 2**, tehát nem
bizonyíték. Ezért **forward papírkereskedés** 2026-09-15-től
(`strategies/csilla_forward.py`), előre rögzített leállító küszöbbel (n ≥ 60 és
R < −0,10). A kicsi célár, a korai BE, a csúszó stop és a pozícióépítés
mind mérve: egyik sem fordítja pozitívba a 8 páros eredményt.

A forward-napló frissítését **a program végzi** (v3.87.x): a stratégia
deklarálja a napi feladatát (`CsillaStrategy.daily_jobs()` →
`strategies/csilla_forward.py`, a `.tfs` csomag viszi), a motor naponta egyszer,
a beállított idő után (`daily_jobs.csilla_forward.time`, alap 22:30, helyi idő)
alprocesszben futtatja (`main.py job csilla_forward`); kézzel a Karmester fül
„▶ Futtat most" gombjával vagy a `jobs run csilla_forward` parancssal
indítható, az állás a `jobs` parancsból és az esti riportból olvasható. A
keret a stratégiát név szerint nem ismeri: a stratégia törlésével a feladat is
eltűnik. Az első hét megmutatta, hogy a „naponta, kézzel" nem fut — ezért
került a programba. A páros olvasat (H1→M1, H1→M15, szerkezeti ablak, forduló-belépő)
2026-09-22-én mérve és bukott — a mérés-jegyzet 12. szakasza.

## Amit ez a stratégia NEM csinál

A modul 2026-09-22-én **megtisztult**: csak az maradt benne, ami a forwardban
fut. A megmért és megbukott változatok kódja a `tools/research/csilla_variants.py`
fagyasztott kutató-modulba került — a `.tfs` csomag nem viszi, a program nem
hívja, de a lezárt kérdések újrafuttathatók maradtak:

| kivezetve | mit csinált | miért nincs itt |
|---|---|---|
| `retest` belépő | visszaérés a tört szintre | az első 14 éves mérés 4 változatának egyike, mind negatív (−0,217 R) |
| `fordulo` belépő | a zászló utáni első ellenoldali M1-swing | −0,435 R/kötés, 6% találat (n = 212 000) |
| H1 / H4 szintek | a „páros olvasat" felső idősíkja | H1→M15 −0,049 R, H1→M1 −0,167 R, 0/14 év |
| fibo célár | a tört szinttől 138,2% × a láb | célár nélkül minden változat jobb volt; 14 éven egyetlen csomag sem ért el 10–20 R-t |

Ami **maradt** a lezárt kísérletekből: a **szerkezeti stop** (`stop_atr=None`,
a törés előtti utolsó ellenoldali M15-swing). Nem azért, mert nyert — hanem mert
ez az egyetlen nyitva hagyott kérdés: a bukások közös tényezője a szűk
zászló-stop volt.

## Paraméterek

A szint-paraméterek (`k_d1`, `k_w1`, `ttl_*`) a „jelentős szint" definíciója —
a forward teszt alatt **nem hangolhatók**. Az Opt rács csak a `stop_atr`,
`max_wait`, `tp_rr_ratio` tengelyeket tartalmazza.

⚠ Mély M15-warmup (~1 év, a W1-szintek miatt); a kontextus páronként
gyorsítótárazott.
