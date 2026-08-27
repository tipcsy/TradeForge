# Tick-alapú adattárolás — terv

**Állapot:** terv, még nincs megvalósítva. Kiváltandó probléma: az MT5 csak
1–2 év M1/M15 gyertyát tart, **tickből viszont sokkal többet** — és a jelenlegi
~480 kereskedési napos minta túl kicsi ahhoz, hogy egy kis élet megkülönböztessen
a nullától.

---

## 1. Miért nem csak „több adat"

Két külön haszna van, és a **második a nagyobb**:

**(a) Hosszabb minta.** Egy +0,05R-es él szórása 1500 kötésnél ~0,026R — vagyis
a jelenlegi mintaméreteken a +0,05 és a 0 megkülönböztethetetlen. 5 év adat a
felbontást megduplázza.

**(b) ÚJ információ.** Az M1 OHLC négy számra (O/H/L/C) tömöríti a percet, és
eldobja azt, amit csak a tick tud:

| jellemző | mit mond | ma elérhető? |
|---|---|---|
| jegyzés-frissítési sűrűség | mennyire „él" a piac | nem |
| bid/ask aszimmetria | melyik oldal mozdul | nem |
| spread dinamikája a percen belül | mikor drágul be | csak átlag+záró |
| mikro-ár (súlyozott közép) | a valódi „ár" | nem |
| kötés-intenzitás eloszlása | impulzus vs. csordogálás | csak darabszám |

Az eddigi összes kudarcom ugyanabból a négy számból dolgozott. Ez az egyetlen
lépés, ami **genuinely új bemenetet** ad, nem ugyanannak az újraszeletelését.

---

## 2. Alapelv: a tick az IGAZSÁG, a gyertya CACHE

```
data/ticks/<SYMBOL>/<YYYY>-<MM>.parquet     ← forrás, soha nem írjuk felül
data/m1/<SYMBOL>.parquet                    ← ebből dolgozik minden futás
data/m15/<SYMBOL>.parquet                     (egyszer épül, marad a lemezen)
```

**Kell-e még az M1/M15 parquet? IGEN, és MARAD A LEMEZEN.** A „származtatott"
itt nem azt jelenti, hogy ideiglenes: a gyertya-fájl **egyszer épül fel**, utána
ugyanúgy ott van, mint ma, és minden backteszt/optimalizálás abból olvas. Tickből
újraszámolni minden futásnál percekbe kerülne — egy 500 trialos optimalizálás így
használhatatlan lenne.

A különbség csak annyi, hogy tudjuk: van egy **forrás** (a tick), amiből a
gyertya bármikor újraelőállítható — tehát egy sérült vagy hiányos gyertya-fájl
nem adatvesztés. Újraépítés két esetben kell: (a) a tick-tartomány bővült
(letöltöttünk régebbi évet), (b) a számítási logika változott. Ezt egy manifest
teszi ellenőrizhetővé, hogy az elavulás ne NÉMÁN történjen:

```json
{ "symbol": "Ger40", "tf": "M1",
  "source_from": "2019-01-01", "source_to": "2026-08-27",
  "built_at": "2026-08-27T14:00:00Z", "builder_version": 3 }
```

Ha a tick-tartomány bővül vagy a `builder_version` nő → a cache újraépül. E
nélkül a legrosszabb hiba fenyeget: a gyertya és a tick **némán** széttart.

---

## 3. Tárolási formátum

### Oszlopok

| oszlop | típus | megjegyzés |
|---|---|---|
| `time_msc` | int64 | ezredmásodperc epoch (az MT5 `time_msc` mezője) |
| `bid_pt` | int64 | **ár PONTBAN** (`round(bid / point_size)`) |
| `ask_pt` | int64 | ugyanígy |
| `flags` | uint8 | opcionális (MT5 tick flags: bid/ask/last változott-e) |

⚠ **Az árat pontban, egészként tároljuk, nem float32-ben.** Egy EURUSD ár
(1,16549) hat értékes jegy; a float32 ~7 jegyet bír, tehát a kerekítés a
legalsó pontot elviheti — épp azt, amiből a spread áll. Az int64 pont-érték
egzakt, és delta+zstd tömörítéssel kisebb is, mint a float64.

`last`/`volume`: CFD/FX-en jellemzően üres → nem tároljuk. Ha egy szimbólumon
van (tőzsdei), külön oszlopként jöhet.

### Particionálás: HAVI fájlok

Miért havi: (a) a `copy_ticks_range` úgyis havonta hívható a memória miatt —
a `tools/download_history.py` már így csinálja; (b) az inkrementális pótlás egy
fájlt érint; (c) egy hibás hónap újratölthető a többi bántása nélkül.

### Méretbecslés

Referencia: a mostani M1 parquet **25 byte/sor**. A tick sűrűbb, de jobban
tömöríthető (a `bid_pt` szomszédos értékei alig térnek el → delta-kódolás).

| | tick/év (nagyságrend) | becsült méret/év |
|---|---|---|
| EURUSD | 40–80 M | 0,4–1,0 GB |
| Ger40 | 20–50 M | 0,3–0,7 GB |
| GOLD | 30–60 M | 0,4–0,8 GB |

**5 szimbólum × 5 év ≈ 10–25 GB.** Ez a becslés a letöltés első hónapja után
pontosítható — a terv első lépése ezért egy MÉRÉS, nem a teljes letöltés.

---

## 4. Megvalósítás lépései

1. **Felderítés (`tools/tick_probe.py`)** — szimbólumonként megnézi, meddig
   nyúlik vissza a tick (`copy_ticks_range` bináris kereséssel), és letölt EGY
   hónapot, hogy a valódi tick/hó és a valódi tömörített méret kiderüljön.
   *Ez dönti el, érdemes-e egyáltalán.*
2. **Letöltő (`tools/download_ticks.py`)** — havi bontásban, folytatható,
   a meglévő `_MT5_LOCK` + hibakezelés mintájára. Idempotens: a meglévő hónapot
   nem tölti újra, hacsak nem `--force`.
3. **Építő (`tools/build_bars.py`)** — tick → M1/M5/M15/H1 parquet. A logika
   MÁR MEGVAN: `download_history._ticks_to_bars` pontosan ezt csinálja
   (bid-alapú OHLC + `avg_spread` + `close_spread`). Csak ki kell emelni és
   a tick-tárra ráültetni.
4. **Manifest + frissesség-őr** — a `core/config_freshness.py` mintájára:
   ha a cache elavult, a felület SZÓL, nem némán téves adattal fut.

Az 1. lépés fél nap, és utána tudjuk, hogy a 2–4 megéri-e.

---

## 5. A rezsimváltás kezelése — ez PROTOKOLL, nem adatmennyiség

Jogos ellenvetés: „egy 2022-ben működő szabály 2025-ben halott lehet". Ez nem a
több adat ellen szól, hanem **egy másik kiértékelés mellett**:

- **Gördülő walk-forward**, nem egyetlen IS/OOS vágás: tanulj 12 hónapon,
  tesztelj a következő 3-on, told el, ismételd.
- **Évenkénti él-riport**: az R/kötés évről évre. Ha monoton romlik, az él
  elhasználódott — ezt csak hosszú adaton lehet meglátni.
- **Elfogadási feltétel**: az él legyen pozitív az ablakok többségében, ne
  csak összesítve. Egy 2022-es óriási nyereség + 2024–25-ös vérzés összesítve
  szép, élesben halálos.

Több adattal nemcsak nagyobb a statisztikai erő — **meg lehet mérni, hogy az él
romlik-e.** Kevés adattal ez a kérdés fel sem tehető.
