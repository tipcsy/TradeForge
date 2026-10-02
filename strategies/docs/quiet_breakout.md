# Csendes szerkezeti áttörés (`quiet_breakout`)

Belépési jel, amely **csendes piacon**, **emelkedő szerkezet** mellett, egy
**visszahúzódás után** az előző M15-csúcs átzárására vásárol.

A HH/HL-szerkezet kutatásából született (2026-10-02, `tools/research/swing_*.py`).
A szerkezet önmagában nem hordozott irányt (a trendek hossza, mérete és
beágyazása a véletlenével egyezett), de ez a szűrő-kombináció egy független
időszakon is megállt. Korlátai alább.

## Mikor long?

| # | időkeret | feltétel |
|---|---|---|
| 1 | **M15** | a záró ár ELŐSZÖR lép az utolsó igazolt M15-csúcs fölé, és előtte az M15-szerkezet nem volt emelkedő (visszahúzódás volt) |
| 2 | **M1 / M5 / H1 / H4** | közülük legalább `min_align` (2) emelkedő: az utolsó két igazolt csúcs magasabb csúcs ÉS az utolsó két völgy magasabb völgy |
| 3 | **M15** | csendes piac: az ATR(14) legfeljebb `vol_max` (0,78) × az ugyanabban az órában (magyar idő) szokásos az előző ~20 napban |

Swing-pont: a gyertya magasabb (völgynél alacsonyabb) a `pivot_k` (3) előtte és
utána lévőnél — ezért csak 3 gyertyával KÉSŐBB ismert, nincs jövőbe látás.

**SL** = az utolsó igazolt M15-völgy (szerkezeti stop); ha a táv nem esik 0,5–4
ATR közé, nincs belépő. **TP** = SL × `tp_rr_ratio` (alap 15 ≈ nincs célár).

## Mikor short?

**Soha.** A short oldal a kutatásban minden szűrővel negatív volt.

## Mért eredmény (100 kockázat / kötés, 10 000-es számla)

Belépés 10:00–20:59 között (magyar idő), zárás 21:45-kor vagy 8 óra után.

| szakasz | mérőhely | kötés / év | nettó / kötés | t |
|---|---|---|---|---|
| 2013–2022 (független próba) | kutató-labor | 95 | **+9,07** | 1,58 |
| 2013–2022 | **motor** (`run_pair`, idő-kilépéssel) | 94 | **+6,56** | 1,17 |
| 2023–2026 | kutató-labor | 201 | +8,18 | 1,40 |
| 2023–2026 | **motor** (idő-kilépéssel) | 199 | +6,58 | 1,16 |
| 2023–2026 | motor, idő-kilépés NÉLKÜL | 140 | +1,46 | 0,08 |

A 2013–2022-es szakaszon a jelölt a véletlen longot szignifikánsan veri
(különbség +12,1, t = 2,01); 2023 óta a véletlen long is +5,6, a különbség nem
szignifikáns.

⚠ **t < 2: nyom, nem bizonyíték.** Élesben előbb CSAK JELZÉS módban fusson.

## Amit a keret ad, nem a stratégia

* **Napszak:** belépés 10:00–20:59 — a keret óra-kapuja (`trade_hours`: 10–20).
  ⚠ A gyertya-index KANONIKUS fal-óra (berlini = magyar idő), az óra-lista tehát
  közvetlenül magyar óra — nincs UTC-átváltás.
* **Kilépés:** a kockázatcsökkentés IDŐ-KILÉPÉSE (`eod_close` = "21:45",
  `max_hold_min` = 480; per pár, `core/risk_reduction.time_exit_due`). Nélküle a
  pozíció éjszakára nyitva marad, és a swap elviszi az eredményt (lásd a táblát).
  ⚠ A kockázatcsökkentés PER PÁR él: ha ugyanazon a páron más stratégia is fut,
  az idő-kilépés arra is vonatkozik.

## Paritás

A szabály a `strategies/quiet_breakout_rules.py`-ban él; a kutató-labor és a
stratégia is onnan hív. `tests/test_quiet_breakout_parity.py` őrzi.
