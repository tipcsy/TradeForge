# MT5 backtest-reprodukció (BacktestReplayer)

A Python-backtest belépőit az MT5 Strategy Testerben lehet reprodukálni.

## Menete
1. **Futtass egy backtestet** a felületen (instrumentum-ablak → Backtest). A végén a
   belépők automatikusan CSV-be íródnak:
   `data/mt5_backtest/mt5_backtest_<SYMBOL>_<időbélyeg>.csv`
   (az eredmény-sáv kiírja a fájlnevet).
2. **Másold a CSV-t** az MT5 közös mappájába:
   `<Terminál>\Common\Files\` (a `BacktestReplayer.mq5` induláskor ír egy
   `ide_kell_helyezni.txt`-t a pontos útvonallal). A közös mappa a gépeden az
   MT5 **Fájl → Adatmappa megnyitása** alól is elérhető
   (`…\MetaQuotes\Terminal\Common\Files\`).

3. **Fordítsd le** a `tools/BacktestReplayer.mq5`-öt a MetaEditorban (Experts közé).
4. **Strategy Tester**: az adott `<SYMBOL>` **M1** időkeret, „Csak nyitóárak" (Open
   prices only) ajánlott. Add hozzá a `BacktestReplayer` expertet, az inputoknál
   állítsd:
   - `InpCsvFile` = a CSV fájlneve,
   - `InpPipSize` = a szimbólum pip-mérete,
   - `InpMagic` = tetszőleges egyedi szám.
5. Indítsd — az EA a Python **eseménynaplóját JÁTSSZA VISSZA** (nem szimulál újra):
   OPEN → SL_MODIFY / TP_MODIFY / PARTIAL_CLOSE / BUILD_ADD → CLOSE, és kirajzolja a
   trade-eket. Az SL/TP valódi stopként a pozícióra kerül → az MT5 a pontos SL/TP
   áron zár.

## Csak vizualizáció (Strategy Tester nélkül)

Ha nem akarsz replay-t futtatni, csak látni a kötéseket az élő charton, tedd az
ugyanezt a CSV-t olvasó **indikátorok** valamelyikét egy `<SYMBOL>` **M1** chartra
(a CSV szintén a `Common\Files\` mappába kell, `FILE_COMMON`):

- **`tools/BacktestTradesViewer.mq5`** — a kötések vonalait rajzolja (belépő, SL-lépcső,
  TP, kiszállás, részleges zárás), számolás nélkül.
- **`tools/BacktestPnLViewer.mq5`** — ugyanazok a jelölések a TradeForgeViz stílusában
  (belépő **függőleges vonal**: ZÖLD BUY / PIROS SELL + irány-nyíl; SL/TP; a kiszállás
  **szaggatott** függőleges vonal: ZÖLD ha nyert / PIROS ha vesztett), **ÉS** kötésenként
  kiszámolja az eredményt **pénzben** (`OrderCalcProfit`, a részleges zárásokkal együtt)
  és **R-ben** (a belépő és a kezdeti SL távolsága = 1R). A bal felső sarokban összesítő
  panel (kötésszám, nyerő/vesztő arány, összes P&L és R). Input: `InpCsvFile` = a CSV
  fájlneve. Csak rajzol, nem kereskedik.

## Fontos / korlátok
- **Trading-with-Erik M1-belépőket ad** → az EA **M1**-en fut. Minden esemény
  időbélyege a detektáló bar + 1 M1 (bar-záró) → az EA a következő bar nyitásán hajtja
  végre.
- **v4 (eseménynapló-alapú):** BÁRMELY preset (Felező/Pajzs/Fibo/Harmados/Risky), a
  kiszállási jel és a pozícióépítés is egyezik, mert a döntéseket a **Python** hozza, az
  MT5 csak végrehajtja. A CSV-t a `run_pair(record_events=True)` termeli (a Backtest-ablak
  automatikusan ezzel fut).
- **v4.10 — fill-eltolás:** az MT5 tényleges belépőára eltérhet a Pythonétól (más feed/
  időzítés), ezért az EA **nem abszolút** Python-szinteket tesz a pozícióra (az „invalid
  stops"/10016 miatt elutasított megbízás lenne), hanem SL/TP nélkül nyit, majd a fill
  ismeretében viszi át a Python-geometriát (távolságokat), a bróker minimum
  stop-távolságához igazítva. A további szinteket a `tid`-enkénti ár-eltolással
  (fill − Python-belépő) fordítja.
- **Elfogadott, kis eltérés:** a belépő az MT5 valós bar-open/spread-jén tölt (a Python
  `close+spread`-en), a részleges zárás pedig piaci áron zár a bar-on (a Python az 1R
  szinten) → épp ezt (a spread/pip-modellt) validálja a replayer. Az SL/TP-alapú
  kilépések viszont pontos áron egyeznek.
- **Számla-mód:** az egyidejű, ÖNÁLLÓ pozíciókhoz (kockázatmentes runner + új belépő)
  **HEDGING** tesztszámla kell — netting számlán összevonódnak.
- **Ugyanaz a bróker:** a Python-backtest adata arról a brókerről legyen, amelyiken a
  replay fut, különben a két ár-feed elcsúszik.
- A CSV a `tools/mt5_export.py`-ból jön (12 oszlop: event, datetime, symbol,
  direction, price, sl, tp, lot, comment, **be_trigger=tid**, trail_trigger, trail_dist_p).
  A `tid` (trade-azonosító) köti az eseményt a helyes pozícióhoz.
- Forrás: áthozva a `Trading-with-ai` projektből (ml_backtest.py + BacktestReplayer.mq5).
