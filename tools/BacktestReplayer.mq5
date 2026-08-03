//+------------------------------------------------------------------+
//| BacktestReplayer.mq5  v4.00 (TradeForge)                         |
//| Reads mt5_backtest_SYMBOL.csv from tools/mt5_export.py and       |
//| REPLAYS the Python backtest event log 1:1 (no re-simulation).    |
//|                                                                  |
//| A korábbi verzió az OFF preset BE/trail-jét ÚJRASZIMULÁLTA →     |
//| a Felező/Pajzs/Fibo/Harmados/Risky részleges zárása, a kiszállási |
//| jel és a pozícióépítés kimaradt → teljesen más eredmény.         |
//|                                                                  |
//| v4: az EA már NEM dönt semmiről — a Python ESEMÉNYNAPLÓJÁT hajtja |
//| végre: OPEN → SL_MODIFY / TP_MODIFY / PARTIAL_CLOSE / BUILD_ADD → |
//| CLOSE. Az SL/TP a pozícióra VALÓDI stopként kerül, így az MT5 a   |
//| pontos SL/TP áron zár (a felezés/kiszállás piaci áron). Minden    |
//| eseményt a `tid` (be_trigger oszlop) köt a helyes pozícióhoz →    |
//| egy páron az egyidejű pozíciók sem keverednek.                   |
//|                                                                  |
//| v4.10: az MT5 fillje ELTÉRHET a Python belépőárától (más bróker/  |
//| feed, más időzítés) — ezért NEM abszolút Python-szinteket teszünk |
//| a pozícióra (az "invalid stops"/10016 miatt elutasított megbízás  |
//| lenne), hanem: SL/TP nélkül nyitunk, majd a FILL ismeretében a    |
//| Python-geometriát (távolságokat) visszük át, a bróker minimum     |
//| stop-távolságához igazítva. Minden további Python-szintet a       |
//| tid-enkénti ár-eltolással (fill − python_belépő) fordítunk.       |
//|                                                                  |
//| Strategy Tester: <SYMBOL> M1. A CSV a Terminal\Common\Files\      |
//| mappába kell (FILE_COMMON). Az egyidejű, ÖNÁLLÓ pozíciókhoz       |
//| HEDGING számla kell (netting számlán összevonódnak!).             |
//| FONTOS: a Python-backtest adata UGYANARRÓL a brókerről legyen,    |
//| amelyiken a replay fut — különben a két ár-feed elcsúszik.        |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property description "Backtest event-log replayer (M1) — executes Python decisions"
#property version   "4.10"
#property strict

#include <Trade\Trade.mqh>

//--- Inputs
input string InpCsvFile    = "mt5_backtest_EURUSD.csv"; // CSV fájlnév (Common\Files\)
input long   InpMagic      = 20260627;                   // Magic number
input int    InpSlippage   = 50;                         // Max slippage (points)
input double InpPipSize    = 0.0001;                     // Pip méret (CSAK a rajzoláshoz)
input bool   InpShowLines  = true;                       // Vonalak az összes trade-re
input bool   InpShowLabels = true;                       // Szöveg feliratok
input int    InpLineWidth  = 1;                          // Vonalvastagság (1-3)

//--- Object prefix
#define OBJ_PFX    "BTR_"
#define MAX_EVENTS 200000

//--- CSV event (a Python-backtest egy naplósora)
struct TEvent {
    string   type;    // OPEN / SL_MODIFY / TP_MODIFY / PARTIAL_CLOSE / BUILD_ADD / CLOSE
    datetime dt;      // az esemény ideje (a detektáló bar záró = a köv. bar nyitása)
    string   dir;     // BUY / SELL
    double   price;   // esemény-ár (OPEN belépő, PARTIAL 1R ár, CLOSE záróár, BUILD láb ár)
    double   sl;      // OPEN kezdeti SL / SL_MODIFY új SL / BUILD_ADD új átlagár-SL
    double   tp;      // OPEN TP / TP_MODIFY új TP (0 = törlés)
    double   lot;     // OPEN teljes lot / PARTIAL lezárandó lot / BUILD_ADD adalék lot
    string   comment; // OPEN: stratégia; egyébként a reason (BE/TRAIL/tp/sl/exit/…)
    int      tid;     // trade-azonosító (a be_trigger oszlopból) → pozícióhoz kötés
};

//--- Globals
CTrade   g_trade;
TEvent   g_ev[];
int      g_cnt      = 0;
int      g_next     = 0;
datetime g_last_bar = 0;

ulong    g_ticket[];    // tid -> nyitott pozíció ticket (0 = nincs)
double   g_offset[];    // tid -> (MT5 fill − Python belépő) ÁR-ELTOLÁS
int      g_maxtid  = 0;

//+------------------------------------------------------------------+
//| A bróker minimális stop-távolsága ÁRBAN (0 = nincs korlát)       |
//+------------------------------------------------------------------+
double MinStopDist()
{
    long lvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
    return (double)lvl * SymbolInfoDouble(_Symbol, SYMBOL_POINT);
}

//+------------------------------------------------------------------+
//| A Python abszolút SL/TP szintjeit a SAJÁT fillünkre tolja és a    |
//| bróker stop-távolságára igazítja, majd ráteszi a pozícióra.       |
//| (0 = az adott láb törlése.)                                       |
//+------------------------------------------------------------------+
void ApplyStops(int tid, string dir, double py_sl, double py_tp, string tag)
{
    ulong tk = g_ticket[tid];
    if(tk == 0 || !PositionSelectByTicket(tk)) return;

    double off  = g_offset[tid];
    double cur  = PositionGetDouble(POSITION_PRICE_CURRENT);
    double mind = MinStopDist();
    int    dg   = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
    bool   isbuy = (dir == "BUY");

    double sl = (py_sl > 0) ? py_sl + off : 0.0;
    double tp = (py_tp > 0) ? py_tp + off : 0.0;

    // A bróker minimum stop-távolságára toljuk, ha közelebb esne (invalid stops)
    if(sl > 0) {
        if(isbuy  && cur - sl < mind) sl = cur - mind;
        if(!isbuy && sl - cur < mind) sl = cur + mind;
    }
    if(tp > 0) {
        if(isbuy  && tp - cur < mind) tp = cur + mind;
        if(!isbuy && cur - tp < mind) tp = cur - mind;
    }
    sl = (sl > 0) ? NormalizeDouble(sl, dg) : 0.0;
    tp = (tp > 0) ? NormalizeDouble(tp, dg) : 0.0;

    if(!g_trade.PositionModify(tk, sl, tp))
        PrintFormat("%s[%d] stop-allitas HIBA (%d): %s  sl=%.2f tp=%.2f cur=%.2f",
                    tag, tid, g_trade.ResultRetcode(),
                    g_trade.ResultRetcodeDescription(), sl, tp, cur);
}

//+------------------------------------------------------------------+
int OnInit()
{
    g_trade.SetExpertMagicNumber(InpMagic);
    g_trade.SetDeviationInPoints(InpSlippage);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);

    g_last_bar = 0;
    g_next     = 0;

    DeleteObjects();
    WritePathHint();

    if(!LoadCSV()) {
        Alert("BacktestReplayer: nem sikerult beolvasni – ", InpCsvFile,
              "\nNezd meg az 'ide_kell_helyezni.txt' fajlt a CSV helyszineert!");
        return INIT_FAILED;
    }

    ArrayResize(g_ticket, g_maxtid + 1);
    ArrayInitialize(g_ticket, 0);
    ArrayResize(g_offset, g_maxtid + 1);
    ArrayInitialize(g_offset, 0.0);

    if(InpShowLines)
        DrawAllTrades();

    ChartRedraw();

    Print("BacktestReplayer v4.10: ", g_cnt, " esemeny betoltve (event-log replay).");
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) { DeleteObjects(); }

//+------------------------------------------------------------------+
//| Egy tick/bar (Open prices only) → a lejárt eseményeket végrehajtja|
//+------------------------------------------------------------------+
void OnTick()
{
    datetime bar0 = iTime(_Symbol, PERIOD_M1, 0);   // az aktuális M1 bar nyitása
    if(bar0 == g_last_bar) return;                  // ugyanaz a bar — nincs teendő
    g_last_bar = bar0;

    // Minden esemény, aminek ideje <= az aktuális bar nyitása → sorrendben végrehajt
    while(g_next < g_cnt && g_ev[g_next].dt <= bar0)
    {
        ExecEvent(g_ev[g_next]);
        g_next++;
    }
}

//+------------------------------------------------------------------+
//| Esemény-diszpécser                                                |
//+------------------------------------------------------------------+
void ExecEvent(const TEvent &ev)
{
    if(ev.tid < 0 || ev.tid > g_maxtid) return;   // védelmi (pl. régi, tid nélküli CSV)

    if(ev.type == "OPEN")               ExecOpen(ev);
    else if(ev.type == "SL_MODIFY")     ExecModify(ev, true,  false);
    else if(ev.type == "TP_MODIFY")     ExecModify(ev, false, true);
    else if(ev.type == "BUILD_ADD")     ExecBuildAdd(ev);
    else if(ev.type == "PARTIAL_CLOSE") ExecPartial(ev);
    else if(ev.type == "CLOSE")         ExecClose(ev);
}

//+------------------------------------------------------------------+
//| OPEN — piaci belépő, VALÓDI SL/TP a pozícióra (MT5 zár pontos áron)|
//+------------------------------------------------------------------+
void ExecOpen(const TEvent &ev)
{
    // SL/TP NÉLKÜL nyitunk! Az MT5 fillje eltérhet a Python belépőárától (más
    // adat-feed / bróker, más végrehajtási időzítés) — az abszolút Python-szintek
    // ilyenkor a piaci ár ROSSZ OLDALÁRA esnének → "invalid stops" (10016) és a
    // megbízás elutasítva. Ezért előbb nyitunk, majd a FILL ismeretében tesszük
    // rá a stopokat, a Python-geometriát (távolságokat) megőrizve.
    bool ok;
    if(ev.dir == "BUY")
        ok = g_trade.Buy(ev.lot, _Symbol, 0, 0, 0, ev.comment);
    else
        ok = g_trade.Sell(ev.lot, _Symbol, 0, 0, 0, ev.comment);

    if(!ok) {
        PrintFormat("OPEN[%d] HIBA (%d): %s", ev.tid,
                    g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
        return;
    }

    ulong tk = g_trade.ResultOrder();       // a nyitó pozíció ticketje
    g_ticket[ev.tid] = tk;

    // Ár-eltolás: MINDEN további Python-szintet (SL_MODIFY/TP_MODIFY) ezzel tolunk
    double fill = ev.price;
    if(PositionSelectByTicket(tk))
        fill = PositionGetDouble(POSITION_PRICE_OPEN);
    g_offset[ev.tid] = fill - ev.price;

    ApplyStops(ev.tid, ev.dir, ev.sl, ev.tp, "OPEN");

    PrintFormat("OPEN[%d] %s lot=%.2f fill=%.2f (py=%.2f, offset=%+.2f) [%s] ticket=%I64u",
                ev.tid, ev.dir, ev.lot, fill, ev.price, g_offset[ev.tid],
                ev.comment, tk);
}

//+------------------------------------------------------------------+
//| SL_MODIFY / TP_MODIFY — a pozíció stopjának/TP-jének frissítése   |
//+------------------------------------------------------------------+
void ExecModify(const TEvent &ev, bool do_sl, bool do_tp)
{
    ulong tk = g_ticket[ev.tid];
    if(tk == 0 || !PositionSelectByTicket(tk)) return;   // már zárva (pl. SL/TP betelt)

    // A meglévő szinteket VISSZA-fordítjuk Python-térbe (−offset), hogy az
    // ApplyStops egységesen tolhassa és igazíthassa a stop-távolsághoz.
    double off    = g_offset[ev.tid];
    double cur_sl = PositionGetDouble(POSITION_SL);
    double cur_tp = PositionGetDouble(POSITION_TP);
    double py_sl  = do_sl ? ev.sl : (cur_sl > 0 ? cur_sl - off : 0.0);
    double py_tp  = do_tp ? ev.tp : (cur_tp > 0 ? cur_tp - off : 0.0);

    ApplyStops(ev.tid, ev.dir, py_sl, py_tp, ev.type);
}

//+------------------------------------------------------------------+
//| PARTIAL_CLOSE — a lot egy részének zárása (Felező/Pajzs)          |
//+------------------------------------------------------------------+
void ExecPartial(const TEvent &ev)
{
    ulong tk = g_ticket[ev.tid];
    if(tk == 0 || !PositionSelectByTicket(tk)) return;

    if(g_trade.PositionClosePartial(tk, ev.lot))
        PrintFormat("PARTIAL[%d] lot=%.2f @~%.5f [%s]", ev.tid, ev.lot, ev.price, ev.comment);
    else
        PrintFormat("PARTIAL[%d] HIBA (%d): %s", ev.tid,
                    g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| CLOSE — a maradék zárása (kiszállási jel / cost-cut / EOD).       |
//| SL/TP-záráskor az MT5 már natívan zárt → itt a ticket üres (no-op)|
//+------------------------------------------------------------------+
void ExecClose(const TEvent &ev)
{
    ulong tk = g_ticket[ev.tid];
    if(tk != 0 && PositionSelectByTicket(tk)) {
        if(g_trade.PositionClose(tk))
            PrintFormat("CLOSE[%d] @~%.5f [%s]", ev.tid, ev.price, ev.comment);
    }
    g_ticket[ev.tid] = 0;
}

//+------------------------------------------------------------------+
//| BUILD_ADD — piramidális ráépítés: volument ad a csomaghoz.        |
//| NETTING számlán a pozíció (ticket) átlagára/mérete frissül, a     |
//| soron következő SL_MODIFY (átlagár) + TP_MODIFY(0) állítja be a   |
//| csomag stopját. (Hedging számlán a láb külön ticket lenne.)       |
//+------------------------------------------------------------------+
void ExecBuildAdd(const TEvent &ev)
{
    bool ok;
    if(ev.dir == "BUY")
        ok = g_trade.Buy(ev.lot, _Symbol, 0, 0, 0, "build");
    else
        ok = g_trade.Sell(ev.lot, _Symbol, 0, 0, 0, "build");

    if(ok) {
        // Netting: a csomag ticketje változatlan marad (nem írjuk felül).
        PrintFormat("BUILD_ADD[%d] +%.2f lot @%.5f (uj atlagar-SL=%.5f)",
                    ev.tid, ev.lot, ev.price, ev.sl);
    }
    else {
        PrintFormat("BUILD_ADD[%d] HIBA (%d): %s", ev.tid,
                    g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
    }
}

//+------------------------------------------------------------------+
//| Load CSV (12 columns, FILE_COMMON). A be_trigger oszlop = tid.    |
//+------------------------------------------------------------------+
bool LoadCSV()
{
    int fh = FileOpen(InpCsvFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
    if(fh == INVALID_HANDLE) {
        Print("FileOpen hiba (", GetLastError(), "): ", InpCsvFile);
        return false;
    }

    // Fejléc (12 mező) átugrása
    for(int c = 0; c < 12 && !FileIsEnding(fh); c++)
        FileReadString(fh);

    ArrayResize(g_ev, MAX_EVENTS);
    g_cnt    = 0;
    g_maxtid = 0;

    while(!FileIsEnding(fh) && g_cnt < MAX_EVENTS)
    {
        string type = FileReadString(fh);
        if(type == "" || FileIsEnding(fh)) break;

        string dt_str     = FileReadString(fh);
        string sym        = FileReadString(fh);
        string dir        = FileReadString(fh);
        double price      = StringToDouble(FileReadString(fh));
        double sl         = StringToDouble(FileReadString(fh));
        double tp         = StringToDouble(FileReadString(fh));
        double lot        = StringToDouble(FileReadString(fh));
        string comment    = FileReadString(fh);
        int    tid        = (int)StringToInteger(FileReadString(fh));  // be_trigger = tid
        FileReadString(fh);   // trail_trigger (nem használt)
        FileReadString(fh);   // trail_dist_p (nem használt)

        g_ev[g_cnt].type    = type;
        g_ev[g_cnt].dt      = StringToTime(dt_str);
        g_ev[g_cnt].dir     = dir;
        g_ev[g_cnt].price   = price;
        g_ev[g_cnt].sl      = sl;
        g_ev[g_cnt].tp      = tp;
        g_ev[g_cnt].lot     = lot;
        g_ev[g_cnt].comment = comment;
        g_ev[g_cnt].tid     = tid;
        if(tid > g_maxtid) g_maxtid = tid;
        g_cnt++;
    }

    FileClose(fh);
    ArrayResize(g_ev, g_cnt);
    Print("LoadCSV: ", g_cnt, " sor betoltve (max tid=", g_maxtid, ").");
    return g_cnt > 0;
}

//+------------------------------------------------------------------+
//| Draw all trades statically (visual preview) — tid szerint kötve   |
//+------------------------------------------------------------------+
void DrawAllTrades()
{
    int trade_num = 0;

    for(int i = 0; i < g_cnt; i++)
    {
        if(g_ev[i].type != "OPEN") continue;

        int      tid     = g_ev[i].tid;
        datetime open_dt = g_ev[i].dt;
        double   entry   = g_ev[i].price;
        double   sl0     = g_ev[i].sl;
        double   tp0     = g_ev[i].tp;
        double   lot     = g_ev[i].lot;
        string   dir     = g_ev[i].dir;
        string   profile = g_ev[i].comment;
        bool     is_buy  = (dir == "BUY");

        datetime close_dt    = open_dt + 3600;
        double   close_price = entry;
        string   result      = "";

        datetime sl_mod_dt[];
        double   sl_mod_val[];
        string   sl_mod_cmt[];
        int      sl_mod_cnt = 0;

        // Az UGYANEZEN tid-hez tartozó SL_MODIFY / CLOSE események (a zárásig)
        for(int j = i + 1; j < g_cnt; j++)
        {
            if(g_ev[j].tid != tid) continue;

            if(g_ev[j].type == "SL_MODIFY" || g_ev[j].type == "BUILD_ADD") {
                ArrayResize(sl_mod_dt,  sl_mod_cnt + 1);
                ArrayResize(sl_mod_val, sl_mod_cnt + 1);
                ArrayResize(sl_mod_cmt, sl_mod_cnt + 1);
                sl_mod_dt[sl_mod_cnt]  = g_ev[j].dt;
                sl_mod_val[sl_mod_cnt] = g_ev[j].sl;
                sl_mod_cmt[sl_mod_cnt] = g_ev[j].comment;
                sl_mod_cnt++;
            }
            if(g_ev[j].type == "TP_MODIFY")
                tp0 = 0.0;   // épített csomag: TP törölve

            if(g_ev[j].type == "CLOSE") {
                close_dt    = g_ev[j].dt;
                close_price = g_ev[j].price;
                result      = g_ev[j].comment;
                break;
            }
        }

        string pfx      = OBJ_PFX + IntegerToString(trade_num) + "_";
        color  col_dir  = is_buy ? clrDodgerBlue : clrOrangeRed;
        color  col_exit = (result == "tp") ? clrLimeGreen :
                          (result == "sl") ? clrCrimson   : clrGray;

        DrawVLine(pfx + "open", open_dt, col_dir, STYLE_SOLID, 1);

        if(InpShowLines && tp0 > 0)
            DrawSegment(pfx + "tp", open_dt, tp0, close_dt, tp0,
                        clrLimeGreen, STYLE_SOLID, InpLineWidth);

        if(InpShowLines) {
            datetime seg_t = open_dt;
            double   seg_s = sl0;

            for(int m = 0; m < sl_mod_cnt; m++) {
                DrawSegment(pfx + "sl" + IntegerToString(m),
                            seg_t, seg_s, sl_mod_dt[m], seg_s,
                            clrCrimson, STYLE_SOLID, InpLineWidth);

                color mod_col = (sl_mod_cmt[m] == "BE") ? clrGold : clrOrange;
                if(sl_mod_cmt[m] == "BE")
                    DrawVLine(pfx + "be" + IntegerToString(m),
                              sl_mod_dt[m], mod_col, STYLE_DASH, 1);

                DrawSegment(pfx + "slmod" + IntegerToString(m),
                            sl_mod_dt[m], seg_s, sl_mod_dt[m], sl_mod_val[m],
                            mod_col, STYLE_SOLID, 1);

                seg_t = sl_mod_dt[m];
                seg_s = sl_mod_val[m];
            }

            DrawSegment(pfx + "sl_fin",
                        seg_t, seg_s, close_dt, seg_s,
                        clrCrimson, STYLE_SOLID, InpLineWidth);
        }

        DrawVLine(pfx + "close", close_dt, col_exit, STYLE_DOT, 1);

        if(InpShowLabels) {
            string lbl = StringFormat("%s %.5f  lot:%.2f  [%s]",
                                      dir, entry, lot, profile);
            DrawText(pfx + "lbl_open", open_dt, is_buy ? (tp0 > 0 ? tp0 : entry) : sl0,
                     lbl, col_dir);

            if(result != "") {
                string lbl2 = StringFormat("%s @ %.5f", result, close_price);
                DrawText(pfx + "lbl_close", close_dt, close_price, lbl2, col_exit);
            }
        }

        trade_num++;
    }

    Print("BacktestReplayer: ", trade_num, " trade kirajzolva (elonezet).");
}

//+------------------------------------------------------------------+
//| Drawing helpers                                                   |
//+------------------------------------------------------------------+
void DrawVLine(string name, datetime dt, color clr, ENUM_LINE_STYLE style, int width)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_VLINE, 0, dt, 0);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       true);
}

void DrawSegment(string name,
                 datetime t1, double p1, datetime t2, double p2,
                 color clr, ENUM_LINE_STYLE style, int width)
{
    if(t1 >= t2) return;
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
    ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT,  false);
    ObjectSetInteger(0, name, OBJPROP_RAY_LEFT,   false);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       true);
}

void DrawText(string name, datetime dt, double price, string text, color clr)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TEXT, 0, dt, price);
    ObjectSetString(0,  name, OBJPROP_TEXT,       text);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   8);
    ObjectSetString(0,  name, OBJPROP_FONT,       "Courier New");
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       false);
}

//+------------------------------------------------------------------+
void WritePathHint()
{
    string common_path = TerminalInfoString(TERMINAL_COMMONDATA_PATH);

    int fh = FileOpen("ide_kell_helyezni.txt", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
    if(fh != INVALID_HANDLE) {
        FileWriteString(fh, "IDE KELL MASOLNI A CSV FAJLT!\r\n");
        FileWriteString(fh, "============================================================\r\n\r\n");
        FileWriteString(fh, "FONTOS: a Strategy Tester minden indulasakor torli a sajat\r\n");
        FileWriteString(fh, "Tester\\Files\\ mappajat! Ezert a CSV-t IDE kell masolni:\r\n\r\n");
        FileWriteString(fh, ">>> " + common_path + "\\Files\\ <<<\r\n\r\n");
        FileWriteString(fh, "Keresett CSV fajl neve:\r\n  " + InpCsvFile + "\r\n\r\n");
        FileWriteString(fh, "Teljes utvonal:\r\n");
        FileWriteString(fh, "  " + common_path + "\\Files\\" + InpCsvFile + "\r\n");
        FileClose(fh);
        Print("CSV helye: ", common_path, "\\Files\\", InpCsvFile);
    }
}

void DeleteObjects()
{
    int total = ObjectsTotal(0);
    for(int i = total - 1; i >= 0; i--) {
        string name = ObjectName(0, i);
        if(StringFind(name, OBJ_PFX) == 0)
            ObjectDelete(0, name);
    }
}
//+------------------------------------------------------------------+
