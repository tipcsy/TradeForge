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

### MÉRT méret és tartomány (2026-08-27, ActivTrades)

A becslés helyett a `tools/tick_probe.py` valódi mérése (5 kereskedési nap
mintából, a végleges formátumban — idő ms + ár pontban, int64, zstd):

| szimbólum | legkorábbi tick | év | tick/nap | byte/tick | GB/év | teljes előzmény |
|---|---|---|---|---|---|---|
| GOLD   | **2013-05-22** | 14 | 664 192 | 5,21 | 0,87 | ~12 GB |
| USDJPY | **2013-05-22** | 14 | 205 724 | 4,44 | 0,23 | ~3 GB |
| UsaTec | **2017-02-13** | 10 | 832 633 | 5,54 | 1,16 | ~12 GB |
| UsaInd | **2017-02-13** | 10 | 165 952 | 5,85 | 0,24 | ~2 GB |
| Ger40  | **2021-10-08** | 6 | 135 701 | 6,08 | 0,21 | ~1 GB |

**A byte/tick 4,4–6,1** — az int64+zstd tárolás tehát tartja, amit ígért (a
nyers float64-es hármas 24 byte lenne). Öt szimbólum TELJES előzménye ~30 GB;
egy visszafogottabb 5 éves ablak ~14 GB.

**A minta-növekedés, amiért az egészet csináljuk** (a mostani ~480 kereskedési
naphoz képest):

| | mostani | tickből | szorzó |
|---|---|---|---|
| Ger40 | 480 nap | ~1230 | 2,5× |
| UsaTec / UsaInd | 480 nap | ~2400 | 5× |
| GOLD | 480 nap | ~3300 | 6,9× |

⚠ A legjobb jelöltünk instrumentuma (Ger40) kapja a LEGRÖVIDEBB előzményt —
a szorzó ott csak 2,5×.

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

---

## 6. ⚠ A LETÖLTÉS MECHANIKÁJA — mért viselkedés (2026-08-27)

A tick-előzmény **nincs a gépen, amíg le nem kéred**. Mérve, ActivTrades / Ger40:

| hívás | idő | eredmény |
|---|---|---|
| `copy_ticks_from(epoch, 1)` — **első** | 91 mp | `None`, `(-1, 'Terminal: Call failed')` |
| ugyanaz — **második** | 65 mp | ✅ első tick: **2021-10-08** |
| `copy_ticks_range(2022-03-09 … +1 nap)` | **0,1 mp** | **152 553 tick** |

Vagyis: az első hívás **elindítja a szinkront** és menet közben elbukik; a
második megkapja az adatot; onnantól a történelmi napok azonnal jönnek.
A szinkron **egyszeri, szimbólumonkénti ~2–3 perces költség**.

Három következmény, amit a tervbe be kell építeni:

1. **Nem hibatűrés, hanem protokoll.** A letöltőnek többször kell hívnia. Egy
   egyszeri hívás „nincs adat"-ot ad, ami HAMIS — az első `tick_probe` ezért írt
   mindenhol nullát.
2. **A szinkron alatt a terminál foglalt.** A `main.py live` `mt5.initialize()`-e
   ilyenkor BEÁLL, és a dashboard főablaka meg sem jelenik. A tick-letöltést
   ezért **külön kell futtatni**, nem az élő program mellett.
3. **A tartomány szimbólumonként eltér.** A Ger40 2021-10-ig nyúlik vissza (~5
   év) — a gyertyák 2 évéhez képest 2,5× minta. Minden szimbólumot külön kell
   megmérni; ez a `tick_probe` dolga.
