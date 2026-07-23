# MT5 backtest-reprodukció (BacktestReplayer)

A Python-backtest belépőit az MT5 Strategy Testerben lehet reprodukálni.

## Menete
1. **Futtass egy backtestet** a felületen (instrumentum-ablak → Backtest). A végén a
   belépők automatikusan CSV-be íródnak:
   `data/mt5_backtest/mt5_backtest_<SYMBOL>_<időbélyeg>.csv`
   (az eredmény-sáv kiírja a fájlnevet).
2. **Másold a CSV-t** az MT5 közös mappájába:
   `<Terminál>\Common\Files\` (a `BacktestReplayer.mq5` induláskor ír egy
   `ide_kell_helyezni.txt`-t a pontos útvonallal).
3. **Fordítsd le** a `tools/BacktestReplayer.mq5`-öt a MetaEditorban (Experts közé).
4. **Strategy Tester**: az adott `<SYMBOL>` **M1** időkeret, „Csak nyitóárak" (Open
   prices only) ajánlott. Add hozzá a `BacktestReplayer` expertet, az inputoknál
   állítsd:
   - `InpCsvFile` = a CSV fájlneve,
   - `InpPipSize` = a szimbólum pip-mérete,
   - `InpMagic` = tetszőleges egyedi szám.
5. Indítsd — az EA a Python **eseménynaplóját JÁTSSZA VISSZA** (nem szimulál újra):
   OPEN → SL_MODIFY / TP_MODIFY / PARTIAL_CLOSE / BUILD_ADD → CLOSE, és kirajzolja a
   trade-eket. Az OPEN-kor a valódi SL/TP a pozícióra kerül → az MT5 a pontos SL/TP
   áron zár.

## Fontos / korlátok
- **Trading-with-Erik M1-belépőket ad** → az EA **M1**-en fut. Minden esemény
  időbélyege a detektáló bar + 1 M1 (bar-záró) → az EA a következő bar nyitásán hajtja
  végre.
- **v4 (eseménynapló-alapú):** BÁRMELY preset (Felező/Pajzs/Fibo/Harmados/Risky), a
  kiszállási jel és a pozícióépítés is egyezik, mert a döntéseket a **Python** hozza, az
  MT5 csak végrehajtja. A CSV-t a `run_pair(record_events=True)` termeli (a Backtest-ablak
  automatikusan ezzel fut).
- **Elfogadott, kis eltérés:** a belépő az MT5 valós bar-open/spread-jén tölt (a Python
  `close+spread`-en), a részleges zárás pedig piaci áron zár a bar-on (a Python az 1R
  szinten) → épp ezt (a spread/pip-modellt) validálja a replayer. Az SL/TP-alapú
  kilépések viszont pontos áron egyeznek.
- **Számla-mód:** a több egyidejű pozíció (kockázatmentes runner + új belépő) és a
  ráépítés (BUILD_ADD) helyes visszajátszásához a tesztszámla legyen megfelelő
  (a ráépítés átlagár-csomagja **NETTING** számlát feltételez).
- A CSV a `tools/mt5_export.py`-ból jön (12 oszlop: event, datetime, symbol,
  direction, price, sl, tp, lot, comment, **be_trigger=tid**, trail_trigger, trail_dist_p).
  A `tid` (trade-azonosító) köti az eseményt a helyes pozícióhoz.

## Kötések megtekintése NORMÁL charton (BacktestTradesViewer.mq5)

Ha nem futtatni akarod a kötéseket, csak MEGNÉZNI az egész időszak összes
kereskedési vonalát egy sima charton (nem a Strategy Testerben):

1. Fordítsd le a `tools/BacktestTradesViewer.mq5`-öt (Indicators közé), majd húzd egy
   `<SYMBOL>` **M1** chartra (pl. GER40 M1).
2. Ugyanaz a CSV kell a `Common\Files\` mappába; az inputnál add meg az `InpCsvFile`-t.
3. Kirajzolja az ÖSSZES kötést: belépő + SL-lépcső + TP + kiszállás + részleges zárás
   jelölő — szabadon görgethető a teljes időszakon. Az `InpDaysBack`-kel az utolsó N
   napra szűkíthető (0 = mind). Csak RAJZOL, nem kereskedik.
