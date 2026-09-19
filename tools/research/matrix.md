# A több dimenziós mátrix és a visszatekintő stop-tanulmány

> „Folyamatosan elcsúszunk a banánhéjon, és szerintem valamit nem veszünk
> észre. […] mi van, ha felállítunk egy több dimenziós mátrixot? […] Csak itt
> volna egy trükk: szerintem nem egyszerre kell ezeket keresni, hanem azt
> feltárni, hogy mi után mi jön. […] Mit tekintünk jó beszállónak? […] Mondjuk
> most látunk előre. […] milyen logika alapján érdemes most csak az SL-t
> elhelyezni, hogy belépve a max TP-t el tudjuk érni."
> — 2026-09-19

Ez a dokumentum a kérdésre adott **mérési terv**, a hozzá tartozó kód
(`seq_events.py`, `seq_matrix.py`, `sl_paths.py`, `sl_oracle.py`,
`seq_stat.py`) leírása, és — ami a legfontosabb — az **előre rögzített
elfogadási feltételek**. A számokat a saját gépeden, a saját adatodon a
futtatás adja; itt az van leírva, mit jelentenek.

---

## 1. Miért csúszunk el — három konkrét ok, mindhárom javítva

**(a) Rossz a mérce.** Eddig minden jelölt a NULLÁHOZ vagy a feltétel nélküli
átlaghoz mérődött. Egy sorrend-állításnál („dupla csúcs UTÁN doji") ez rossz
kérdés: a helyes mérce **maga a B esemény**. Ha a doji önmagában +0,02 R, és a
„dupla csúcs után doji" is +0,02 R, akkor a sorrend SEMMIT nem adott hozzá —
pedig a naiv nézetben mindkettő „pozitív találat". A `seq_matrix.py` kulcs-
oszlopa ezért a `sorrend_delta = E[R | A után B] − E[R | B]`.

**(b) Az átfedés felfújja a t-t.** Az `outcomes.py` minden rácspontot önállóan
értékel, de a tartás 480 perc = 96 rácspont. Két szomszédos „kötés" a pályája
99%-át megosztja. A sima t-statisztika ilyenkor akár **√96 ≈ 10-szeresen**
túlbecsüli a bizonyítékot. Ezért itt minden t **napra klaszterezett**
(`seq_stat.t_klaszter`). A tesztben mérve: 20-szoros átfedésnél a naiv t = 1,00,
a klaszterezett 0,22.

**(c) Hiányzik a null.** Eddig a „nulla várható érték" volt a viszonyítás. De a
nulla nem ugyanaz, mint „ugyanilyen volatilitású, de szerkezet nélküli piac".
Két új null került be:

- **körkörös eltolás** (a sorrend-mátrixhoz): megtartja mindkét eseménysor
  saját sűrűsödését (napszak, volatilitás-csomósodás), és csak a kettő közti
  időbeli kapcsolatot töri el;
- **blokk-bootstrap piac** (`sl_paths.szintetikus`): a valódi barokból
  60 perces darabokban újrafűzött ársor. Megtartja a gyertya-alakot, a
  hozam-eloszlást és az egy órán belüli szerkezetet; eltünteti a hosszabb távú
  trendet, visszahúzást, szintet. **Amit ezen a piacon is megtalálunk, az nem
  szerkezet.**

---

## 2. Definíciók — „mi a jó belépő" és „mi a sikeres trade"

Egy kötés eredménye három, KÜLÖN mérhető és KÜLÖN elromló tényező szorzata.
Eddig egyetlen számba (R/kötés) voltak sűrítve — ezért mondtak a mérések
ellentmondó dolgokat.

| fogalom | képlet | mit mér | ki felelős érte |
|---|---|---|---|
| **ELÉRHETŐ** | `mfe_s / s` | a pálya adott stop mellett ennyi R-t KÍNÁLT | a **belépő** |
| **MEGSZERZETT** | a szabály nettó R-je | ennyit vittünk haza | a **kiszállás** |
| **KIHOZATAL** | megszerzett / elérhető | a kínált hányadát fogtuk meg | a kezelés |

ahol `mfe_s` = a legjobb pont, ahova a stop ütése **előtt** eljutottunk,
`s` = a stop távolsága ATR-ben.

- **Jó belépő** = magas ELÉRHETŐ, **a null-piac ugyanazon számához mérve**.
  Nem az, hogy „gyakran nyer": az elérhető a belépő teljes hozzájárulása, mert
  a kiszállást kiveszi az egyenletből.
- **Jó kiszállás** = magas KIHOZATAL, adott elérhető mellett.
- **Sikeres trade** = **nettó pozitív R** — spread, jutalék ÉS swap után. A
  `README.md` mérése szerint a swap egymaga −0,028…−0,044 R/kötés, ami
  **nagyobb, mint az eddig mért teljes él**. Egy bruttó +0,03 R-es eredmény
  tehát nem siker, hanem nulla.
- **Sikeres SZABÁLY** (nem egy kötés): a fenti nettó R pozitív ÚGY, hogy
  napra klaszterezett t ≥ 2, az évek ≥ 60%-ában pozitív, és ≥ 3 instrumentumon
  pozitív. Ez a `README.md` protokollja, változatlanul.

Egy negyedik szám is kell, mert a belépő minőségét egyetlen számban adja meg:
**e-arány = átlag MFE / átlag MAE**. A jelenlegi mérés (5 instrumentum,
2013–2026): **1,036** — vagyis a belépő gyakorlatilag nem hordoz irányt.

---

## 3. A mátrix (`seq_matrix.py`)

**Dimenziók.** (1) idősík: M1 / M5 / M15 — (2) esemény: 18 emberi nevű alakzat
(`seq_events.py`: doji, pin, elnyelő, belső/külső bar, dupla csúcs/alj,
magasabb alj, alacsonyabb csúcs, swing-törés, trendváltás, szorulás) —
(3) **sorrend**: A esemény, majd B esemény egy időablakon belül (15 / 60 / 240
perc).

**A szótár szándékosan kicsi.** A `search.py` 480 000 jelöltjét a `holdout.py`
úgy ítélte meg, hogy a keresési rangsor NEM jelez előre. 18 × 3 = 54 jel,
54 × 53 rendezett pár — ezen a méreten a Bonferroni-küszöb teljesíthető, és
minden cellának elmondható neve van.

**Két kérdés, ebben a sorrendben:**

1. **Van-e egyáltalán nyelvtan?** Gyakrabban jön-e B az A után, mint véletlenül?
   Ez a kérdés az **árfolyam-hozamot nem használja** — tehát olcsó, és nem lehet
   rajta szerencsét találni. Ha nem, a 2. kérdést fel sem kell tenni.
2. **Fizet-e a sorrend?** `E[R | A után B] − E[R | B]`, kereső szakaszon
   válogatva, holdouton egyszer ellenőrizve.

**⚠ Amit az 1. kérdés NEM jelent.** A „B gyakrabban jön A után" **mechanikusan**
is igaz lehet: egy M15 külső bar M5-ön is külső barokat tartalmaz. A szintetikus
piacon ugyanez az átfedés megvan — ezért a `--szintetikus` kapcsoló a valódi és
a szintetikus **találati arányt** hasonlítja össze; a kettő különbsége az
érdekes szám, nem a nyers darabszám.

**A visszhang-kérdés** („ezt megismétli az M5 is, vagy az M15?") külön
kigyűjtve: ugyanaz az esemény, kisebb idősíkon, a nagyobb után.

---

## 4. A visszatekintő stop-tanulmány (`sl_oracle.py`)

**A kérdés formalizálva.** A stop CSAK egy dolgot csinál: **levág**. Ezért
pontosan két csatornán hat:

```
R(s) = mfe_s / s
```

Szűkebb `s` → nagyobb osztó-hatás (ugyanaz a mozgás több R), de gyakrabban vág
le a pálya legjobb része előtt. Tágabb `s` → biztosabban kibírjuk, de ugyanaz a
pontokban mért nyereség kevesebb R. A mérés ezt a cserearányt teszi láthatóvá.

**A kulcs-mennyiség: `s_min`** — a minimális elégséges stop, vagyis mennyi
fájdalmat kellett kiállni ahhoz, hogy a pálya **legjobb pontjáig** egyáltalán
eljuss. Ez visszatekintő szám, tehát **felső korlát**, nem szabály. Az `s_min`
eloszlása (p10 … p95, ATR-ben) mondja meg, mekkora stop ad esélyt a max TP-re,
és a `eleg_%` oszlop, hogy egy adott `s` a kötések hány százalékánál elég tág.

**⚠ A CSAPDA, amit ki kell mondani.** R-ben mérve a **tágabb stop mechanikusan
jobbnak látszik**: a fix költség (spread + jutalék + swap) pontban állandó,
tehát R-ben `költség / s` — automatikusan csökken, ahogy `s` nő. Aki csak az
R/kötés görbét nézi, arra jut, hogy „a stop legyen végtelen". Ez nem lelet,
hanem a normálás műterméke. **Az igazi kérdés nem az, melyik `s` ad nagyobb
R-t, hanem hogy a valódi piac ad-e többet ugyanazon az `s`-en, mint a
szerkezet nélküli null-piac.**

**A vizsgált stop-logikák** (mind azonos kiszállással, hogy a különbség tisztán
a stopból jöjjön): fix 1,0 / 1,5 / 2,0 / 3,0 ATR; **szerkezeti** (a legutóbb
igazolt swing mögé + 0,25 ATR); **feltételes** (a kereső szakaszon tanult
tipikus `s_min` a volatilitás- és napszak-rekeszben).

**És a döntő előkérdés:** *megjósolható-e egyáltalán az elviselendő fájdalom?*
Ha az `s_min` kvintilis-sorrendje a holdouton nem ismétlődik, akkor a feltételes
stopnak nincs mire támaszkodnia, és a stop elhelyezése nem lehet él — csak
ízlés. Ezt az 5. szakasz méri.

---

## 5. Előre rögzített elfogadási feltételek

**A sorrend-mátrixra** (2. kérdés): a jelölt a KERESŐ szakasz `sorrend_delta`
értéke szerint kerül a top-listára, és a holdout-számot **ezután egyszer**
nézzük meg. Elfogadás: (1) a top-lista átlagos holdout-deltája pozitív,
(2) a kereső rangsor előrejelző (rangkorreláció t > 2), (3) a top-lista veri a
véletlenül választott ugyanennyi cellát (p < 0,05). Bármelyik hiánya = nincs
bizonyított találat.

**Egy stop-szabályra**: akkor jobb a fix 1,5 ATR-nél, ha
(1) a nettó R/kötés különbségének napra klaszterezett t-je ≥ 2,
(2) az évek ≥ 60%-ában pozitív a különbség,
(3) legalább 3 instrumentumon pozitív,
(4) **és a valódi piacon mért előnye nagyobb, mint a null-piacon mért előnye**.

**Előre rögzített várakozás** (a mérés előtt leírva): az 1. kérdésre IGEN a
válasz lesz, a 2.-ra NEM — mert az e-arány 1,036, és egy szűrő nem tud irányt
teremteni ott, ahol nincs. A stop-tanulmánynál azt várom, hogy az `s_min`
mediánja 0,8–1,2 ATR körül lesz, a p90 3 ATR fölött, és hogy a valódi és a
null-piaci `elerheto_R` görbe **egybeesik** — vagyis a stop-optimalizálás nem
él. Ha bármelyik várakozás megdől, az érdekes lelet.

---

## 6. Futtatás

```bash
# előfeltétel: a kimenet-gyorsítótár (egyszer, szimbólumonként)
python tools/research/outcomes.py Ger40 UsaTec GOLD

# 1-2. kérdés: a sorrend-mátrix
python tools/research/seq_matrix.py --symbols Ger40 UsaTec --szintetikus

# csak a szótár (mennyi esemény, milyen gyakori)
python tools/research/seq_events.py Ger40

# a visszatekintő stop-tanulmány
python tools/research/sl_oracle.py --symbols Ger40 UsaInd UsaTec GOLD USDJPY

# a statisztikai mag önellenőrzése (adat nélkül fut)
python tests/test_seq_stat.py
```

---

## 7. Korlátok — amit a számok NEM mondanak meg

- **Az M1 sor tompa.** A rács M5 (`outcomes.STEP_MIN`), ezért egy M1 esemény a
  következő M5 rácspontra kerül: a mátrix M1 sora azt jelenti, „az elmúlt
  ≤5 percben történt". Mérve: emiatt az M1 események a rácspontok 20–70%-án
  igazak, vagyis alig szűrnek. Ha a valódi M1-es ütem számít, az `outcomes.py`-t
  `STEP_MIN = 1`-gyel kell újraépíteni (≈5× költség).
- **A swap csak akkor van levonva**, ha a config `pv1_point` /
  `commission_per_lot` / `swap_*_per_lot` kulcsai ki vannak töltve
  (`tools/refresh_costs.py`). Enélkül a „nettó" oszlop = bruttó, és a riport ezt
  ki is írja.
- **A null-piac blokkhossza kérdés-függő**: 60 perces blokkal azt kérdezzük,
  van-e EGY ÓRÁNÁL hosszabb kihasználható szerkezet. Rövidebb blokk naivabb
  nullt ad (könnyebb megverni), hosszabb szigorúbbat.
- **Ez jelzés-minőséget mér, nem portfóliót.** Nincs benne slot-korlát, átfedő
  kötés-kizárás, óra-kapu. A végső jelöltet át kell vinni a
  `trading.backtest.run_pair`-re.
