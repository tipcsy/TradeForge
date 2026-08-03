//+------------------------------------------------------------------+
//| BacktestTradesViewer.mq5  v1.00 (TradeForge)                     |
//| A BacktestReplayer CSV-jét (mt5_export.py, esemény-napló) egy     |
//| NORMÁL charton rajzolja ki — nem kell Strategy Testert futtatni.  |
//|                                                                  |
//| Minden kötés vonalai: belépő (fgg. vonal), SL-lépcső (a           |
//| SL_MODIFY/átlagár-változásokkal), TP, kiszállás + részleges       |
//| zárás jelölő. A `tid` (be_trigger oszlop) köti az eseményeket a   |
//| helyes kötéshez → az egyidejű pozíciók sem keverednek.            |
//|                                                                  |
//| Használat: tedd egy <SYMBOL> M1 chartra (pl. GER40 M1). A CSV a   |
//| Terminal\Common\Files\ mappába kell (FILE_COMMON). Csak RAJZOL,   |
//| nem kereskedik. Az InpDaysBack-kel az utolsó N napra szűkíthető.  |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property description "Backtest trades viewer — draws all trade lines from the replay CSV"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_plots   0
#property indicator_buffers 0

//--- Inputs
input string InpCsvFile    = "mt5_backtest_GER40.csv";  // CSV fájlnév (Common\Files\)
input int    InpDaysBack   = 0;                          // Csak az utolsó N nap (0 = mind)
input bool   InpShowLabels = true;                       // Szöveg feliratok
input int    InpLineWidth  = 1;                          // Vonalvastagság (1-3)

#define OBJ_PFX    "BTV_"
#define MAX_EVENTS 200000

//--- CSV event (a Python-backtest egy naplósora)
struct TEvent {
    string   type;    // OPEN / SL_MODIFY / TP_MODIFY / PARTIAL_CLOSE / BUILD_ADD / CLOSE
    datetime dt;
    string   dir;
    double   price;
    double   sl;
    double   tp;
    double   lot;
    string   comment;
    int      tid;
};

TEvent g_ev[];
int    g_cnt = 0;

//+------------------------------------------------------------------+
int OnInit()
{
    DeleteObjects();
    WritePathHint();

    if(!LoadCSV()) {
        Alert("BacktestTradesViewer: nem sikerult beolvasni – ", InpCsvFile,
              "\nNezd meg az 'ide_kell_helyezni.txt' fajlt a CSV helyszineert!");
        return INIT_FAILED;
    }

    DrawAllTrades();
    ChartRedraw();
    Print("BacktestTradesViewer: ", g_cnt, " esemeny betoltve.");
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) { DeleteObjects(); }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
{
    return rates_total;   // csak rajzol (OnInit), számolni nem kell
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
    for(int c = 0; c < 12 && !FileIsEnding(fh); c++)   // fejléc átugrása
        FileReadString(fh);

    ArrayResize(g_ev, MAX_EVENTS);
    g_cnt = 0;

    // Idő-szűrő: csak az utolsó N nap (0 = mind). A "most"-hoz a szerver-időt vesszük.
    datetime cutoff = 0;
    if(InpDaysBack > 0)
        cutoff = TimeCurrent() - (datetime)InpDaysBack * 86400;

    while(!FileIsEnding(fh) && g_cnt < MAX_EVENTS)
    {
        string type = FileReadString(fh);
        if(type == "" || FileIsEnding(fh)) break;

        string dt_str  = FileReadString(fh);
        string sym     = FileReadString(fh);
        string dir     = FileReadString(fh);
        double price   = StringToDouble(FileReadString(fh));
        double sl      = StringToDouble(FileReadString(fh));
        double tp      = StringToDouble(FileReadString(fh));
        double lot     = StringToDouble(FileReadString(fh));
        string comment = FileReadString(fh);
        int    tid     = (int)StringToInteger(FileReadString(fh));   // be_trigger = tid
        FileReadString(fh);   // trail_trigger (nem használt)
        FileReadString(fh);   // trail_dist_p (nem használt)

        datetime dt = StringToTime(dt_str);
        if(cutoff > 0 && dt < cutoff) continue;   // az N napnál régebbi eseményeket kihagyjuk

        g_ev[g_cnt].type    = type;
        g_ev[g_cnt].dt      = dt;
        g_ev[g_cnt].dir     = dir;
        g_ev[g_cnt].price   = price;
        g_ev[g_cnt].sl      = sl;
        g_ev[g_cnt].tp      = tp;
        g_ev[g_cnt].lot     = lot;
        g_ev[g_cnt].comment = comment;
        g_ev[g_cnt].tid     = tid;
        g_cnt++;
    }

    FileClose(fh);
    ArrayResize(g_ev, g_cnt);
    Print("LoadCSV: ", g_cnt, " sor betoltve",
          (InpDaysBack > 0 ? " (utolso " + IntegerToString(InpDaysBack) + " nap)" : ""), ".");
    return g_cnt > 0;
}

//+------------------------------------------------------------------+
//| Minden kötés vonalainak kirajzolása — tid szerint csoportosítva   |
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

        datetime part_dt[];
        double   part_px[];
        int      part_cnt = 0;

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
            if(g_ev[j].type == "PARTIAL_CLOSE") {
                ArrayResize(part_dt, part_cnt + 1);
                ArrayResize(part_px, part_cnt + 1);
                part_dt[part_cnt] = g_ev[j].dt;
                part_px[part_cnt] = g_ev[j].price;
                part_cnt++;
            }
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

        if(tp0 > 0)
            DrawSegment(pfx + "tp", open_dt, tp0, close_dt, tp0,
                        clrLimeGreen, STYLE_SOLID, InpLineWidth);

        // SL-lépcső (a mozgó/átlagár-változásokkal)
        datetime seg_t = open_dt;
        double   seg_s = sl0;
        for(int m = 0; m < sl_mod_cnt; m++) {
            DrawSegment(pfx + "sl" + IntegerToString(m),
                        seg_t, seg_s, sl_mod_dt[m], seg_s,
                        clrCrimson, STYLE_SOLID, InpLineWidth);
            color mod_col = (sl_mod_cmt[m] == "BE") ? clrGold : clrOrange;
            DrawSegment(pfx + "slmod" + IntegerToString(m),
                        sl_mod_dt[m], seg_s, sl_mod_dt[m], sl_mod_val[m],
                        mod_col, STYLE_SOLID, 1);
            seg_t = sl_mod_dt[m];
            seg_s = sl_mod_val[m];
        }
        DrawSegment(pfx + "sl_fin", seg_t, seg_s, close_dt, seg_s,
                    clrCrimson, STYLE_SOLID, InpLineWidth);

        // Részleges zárás jelölő (Felező/Pajzs) — kis sárga pötty
        for(int p = 0; p < part_cnt; p++)
            DrawDot(pfx + "part" + IntegerToString(p), part_dt[p], part_px[p], clrGold);

        DrawVLine(pfx + "close", close_dt, col_exit, STYLE_DOT, 1);

        if(InpShowLabels) {
            string lbl = StringFormat("%s %.2f  lot:%.2f  [%s]", dir, entry, lot, profile);
            DrawText(pfx + "lbl_open", open_dt, (is_buy ? (tp0 > 0 ? tp0 : entry) : sl0),
                     lbl, col_dir);
            if(result != "")
                DrawText(pfx + "lbl_close", close_dt, close_price,
                         StringFormat("%s @ %.2f", result, close_price), col_exit);
        }

        trade_num++;
    }

    Print("BacktestTradesViewer: ", trade_num, " trade kirajzolva.");
}

//+------------------------------------------------------------------+
//| Rajz-segédek                                                      |
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

void DrawSegment(string name, datetime t1, double p1, datetime t2, double p2,
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

void DrawDot(string name, datetime dt, double price, color clr)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_ARROW, 0, dt, price);
    ObjectSetInteger(0, name, OBJPROP_ARROWCODE,  159);   // kis pötty
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      1);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       false);
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
        FileWriteString(fh, "IDE KELL MASOLNI A CSV FAJLT (BacktestTradesViewer):\r\n");
        FileWriteString(fh, ">>> " + common_path + "\\Files\\ <<<\r\n");
        FileWriteString(fh, "Keresett fajl: " + InpCsvFile + "\r\n");
        FileClose(fh);
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
