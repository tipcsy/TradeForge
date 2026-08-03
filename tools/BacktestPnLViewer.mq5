//+------------------------------------------------------------------+
//| BacktestPnLViewer.mq5  v1.10 (TradeForge / Trading-with-Erik)    |
//| A BacktestReplayer CSV-jét (mt5_export.py, esemény-napló) egy     |
//| NORMÁL charton rajzolja ki — nem kell Strategy Testert futtatni — |
//| ÉS kiszámolja minden kötés eredményét PÉNZBEN és R-ben.           |
//|                                                                  |
//| Jelölések (a TradeForgeViz / BacktestReplayer stílusában):        |
//|   • Belépő: FÜGGŐLEGES vonal — ZÖLD BUY / PIROS SELL + irány-nyíl |
//|   • SL: piros lépcső (a SL_MODIFY/trail/átlagár-változásokkal)     |
//|   • TP: zöld vonal (ha van)                                        |
//|   • Részleges zárás (Felező/Pajzs): sárga pötty                    |
//|   • Kiszállás: SZAGGATOTT függőleges vonal — ZÖLD ha NYERT,        |
//|     PIROS ha VESZTETT                                             |
//|   • Felirat: „DIR ár lot:x [profil]" a belépőn; a kiszállón a      |
//|     reason (sl/tp/exit/…) @ záróár + „P&L: <pénz>  (<R>R)"         |
//|                                                                  |
//| P&L: OrderCalcProfit-tal (a szimbólum tick-value-ja alapján),     |
//| részleges zárásokkal együtt. R = teljes P&L / kezdeti kockázat    |
//| (a belépő és a KEZDETI SL távolsága, az OPEN sorból).             |
//|                                                                  |
//| Használat: tedd egy <SYMBOL> M1 chartra (pl. UsaTec M1). A CSV a  |
//| Terminal\Common\Files\ mappába kell (FILE_COMMON). Csak RAJZOL,   |
//| nem kereskedik. Az InpDaysBack-kel az utolsó N napra szűkíthető.  |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property description "Backtest P&L viewer — draws trades and computes P&L (money + R) from the replay CSV"
#property version   "1.10"
#property strict
#property indicator_chart_window
#property indicator_plots   0
#property indicator_buffers 0

//--- Inputs
input string InpCsvFile    = "mt5_backtest_UsaTec_20260725_122343.csv"; // CSV fájlnév (Common\Files\)
input int    InpDaysBack   = 0;              // Csak az utolsó N nap (0 = mind)
input bool   InpShowLabels = true;           // Kötésenkénti szöveg feliratok
input bool   InpShowArrows = true;           // Belépő irány-nyíl (BUY fel / SELL le)
input bool   InpShowSummary= true;           // Összesítő panel (bal felső sarok)
input int    InpPanelX     = 6;              // Összesítő panel X (bal felső saroktól)
input int    InpPanelY     = 110;            // Összesítő panel Y (a One-Click panel ALÁ)
input int    InpLineWidth  = 1;              // Vonalvastagság (1-3)
input int    InpFontSize   = 8;              // Felirat betűméret
//--- Színek (alap: VILÁGOS charthoz jól olvasható, sötét árnyalatok)
input color  InpBuyColor   = clrGreen;       // BUY belépő (vonal/nyíl/felirat)
input color  InpSellColor  = clrRed;         // SELL belépő
input color  InpWinColor   = clrGreen;       // Nyerő kiszállás
input color  InpLossColor  = clrCrimson;     // Vesztő kiszállás
input color  InpTpColor    = clrTeal;        // TP vonal
input color  InpSlColor    = clrFireBrick;   // SL vonal

#define OBJ_PFX    "BTP_"
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

//--- Összesítő
double g_tot_pnl   = 0.0;
double g_tot_r     = 0.0;
int    g_wins      = 0;
int    g_losses    = 0;
int    g_trades    = 0;

//+------------------------------------------------------------------+
int OnInit()
{
    DeleteObjects();
    WritePathHint();

    if(!LoadCSV()) {
        Alert("BacktestPnLViewer: nem sikerult beolvasni – ", InpCsvFile,
              "\nNezd meg az 'ide_kell_helyezni.txt' fajlt a CSV helyszineert!");
        return INIT_FAILED;
    }

    DrawAllTrades();
    if(InpShowSummary)
        DrawSummary();
    ChartRedraw();
    Print("BacktestPnLViewer: ", g_cnt, " esemeny, ", g_trades, " kotes. ",
          "Osszes P&L=", DoubleToString(g_tot_pnl, 2),
          " ", AccountInfoString(ACCOUNT_CURRENCY),
          "  R=", DoubleToString(g_tot_r, 2),
          "  (", g_wins, " nyero / ", g_losses, " veszto).");
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
//| Egy kötés eredménye PÉNZBEN: OrderCalcProfit a nyitó- és záróárra,|
//| a részleges zárásokkal együtt (mindegyik a saját lot- jával). Ha  |
//| az OrderCalcProfit nem elérhető (0-t ad vissza), ár×lot fallback. |
//+------------------------------------------------------------------+
double MoneyPnL(string dir, double entry, double close_price, double close_lot,
                const double &part_px[], const double &part_lot[], int part_cnt)
{
    ENUM_ORDER_TYPE ot = (dir == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    double total = 0.0, prof = 0.0;

    for(int p = 0; p < part_cnt; p++) {
        if(OrderCalcProfit(ot, _Symbol, part_lot[p], entry, part_px[p], prof))
            total += prof;
        else
            total += DirSign(dir) * (part_px[p] - entry) * part_lot[p];
    }
    if(OrderCalcProfit(ot, _Symbol, close_lot, entry, close_price, prof))
        total += prof;
    else
        total += DirSign(dir) * (close_price - entry) * close_lot;

    return total;
}

double DirSign(string dir) { return (dir == "BUY") ? 1.0 : -1.0; }

//+------------------------------------------------------------------+
//| Minden kötés kirajzolása + P&L/R számítás — tid szerint csoport.  |
//+------------------------------------------------------------------+
void DrawAllTrades()
{
    int    trade_num = 0;
    int    dg        = (int)_Digits;

    for(int i = 0; i < g_cnt; i++)
    {
        if(g_ev[i].type != "OPEN") continue;

        int      tid     = g_ev[i].tid;
        datetime open_dt = g_ev[i].dt;
        double   entry   = g_ev[i].price;
        double   sl0     = g_ev[i].sl;      // KEZDETI SL → az R kockázati alapja
        double   tp0     = g_ev[i].tp;
        double   lot0    = g_ev[i].lot;
        string   dir     = g_ev[i].dir;
        string   profile = g_ev[i].comment;
        bool     is_buy  = (dir == "BUY");
        double   tp_draw = tp0;             // a TP-t az épített csomag törölheti (rajzhoz)

        datetime close_dt    = open_dt + 3600;
        double   close_price = entry;
        double   close_lot   = lot0;        // a maradék lot a végső CLOSE-nál
        string   result      = "";
        bool     has_close   = false;

        datetime sl_mod_dt[];  double sl_mod_val[];  string sl_mod_cmt[];  int sl_mod_cnt = 0;
        datetime part_dt[];    double part_px[];      double part_lot[];    int part_cnt   = 0;

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
                tp_draw = 0.0;   // épített csomag: TP törölve
            if(g_ev[j].type == "PARTIAL_CLOSE") {
                ArrayResize(part_dt,  part_cnt + 1);
                ArrayResize(part_px,  part_cnt + 1);
                ArrayResize(part_lot, part_cnt + 1);
                part_dt[part_cnt]  = g_ev[j].dt;
                part_px[part_cnt]  = g_ev[j].price;
                part_lot[part_cnt] = g_ev[j].lot;
                part_cnt++;
            }
            if(g_ev[j].type == "CLOSE") {
                close_dt    = g_ev[j].dt;
                close_price = g_ev[j].price;
                result      = g_ev[j].comment;
                has_close   = true;
                break;
            }
        }

        // A végső CLOSE-nál a maradék lot = kezdeti − a részlegesen zártak
        double part_sum = 0.0;
        for(int p = 0; p < part_cnt; p++) part_sum += part_lot[p];
        close_lot = lot0 - part_sum;
        if(close_lot < 0.0) close_lot = 0.0;

        //--- P&L (pénz) és R
        double pnl = 0.0;
        double rr  = 0.0;
        if(has_close) {
            pnl = MoneyPnL(dir, entry, close_price, close_lot,
                           part_px, part_lot, part_cnt);

            // R = a lot-tal SÚLYOZOTT ár-elmozdulás / kezdeti kockázat. A kockázat a
            // TELJES kezdeti méret (a belépő és a KEZDETI SL távolsága). A részleges
            // zárások a saját lot-hányadukkal adnak hozzá; a maradék a végső CLOSE-nál.
            double risk_px = MathAbs(entry - sl0);   // kezdeti kockázat ÁRBAN
            if(risk_px > 0.0 && lot0 > 0.0) {
                rr = DirSign(dir) * (close_price - entry) / risk_px * (close_lot / lot0);
                for(int p = 0; p < part_cnt; p++)
                    rr += DirSign(dir) * (part_px[p] - entry) / risk_px * (part_lot[p] / lot0);
            }

            g_tot_pnl += pnl;
            g_tot_r   += rr;
            g_trades++;
            if(pnl >= 0.0) g_wins++; else g_losses++;
        }

        //--- Színek: belépő ZÖLD/PIROS; kiszállás NYERT=zöld / VESZTETT=piros
        string pfx      = OBJ_PFX + IntegerToString(trade_num) + "_";
        color  col_dir  = is_buy ? InpBuyColor : InpSellColor;
        color  col_exit = !has_close ? clrGray : (pnl >= 0.0 ? InpWinColor : InpLossColor);

        //--- Belépő függőleges vonal + irány-nyíl
        DrawVLine(pfx + "open", open_dt, col_dir, STYLE_SOLID, InpLineWidth);
        if(InpShowArrows)
            DrawArrow(pfx + "arr", open_dt, entry, is_buy ? 233 : 234, col_dir, is_buy);

        //--- TP vonal (ha van)
        if(tp_draw > 0)
            DrawSegment(pfx + "tp", open_dt, tp_draw, close_dt, tp_draw,
                        InpTpColor, STYLE_DOT, InpLineWidth);

        //--- SL-lépcső (a mozgó/átlagár-változásokkal)
        datetime seg_t = open_dt;
        double   seg_s = sl0;
        for(int m = 0; m < sl_mod_cnt; m++) {
            DrawSegment(pfx + "sl" + IntegerToString(m),
                        seg_t, seg_s, sl_mod_dt[m], seg_s,
                        InpSlColor, STYLE_SOLID, InpLineWidth);
            color mod_col = (sl_mod_cmt[m] == "BE") ? clrGoldenrod : clrDarkOrange;
            DrawSegment(pfx + "slmod" + IntegerToString(m),
                        sl_mod_dt[m], seg_s, sl_mod_dt[m], sl_mod_val[m],
                        mod_col, STYLE_SOLID, 1);
            seg_t = sl_mod_dt[m];
            seg_s = sl_mod_val[m];
        }
        DrawSegment(pfx + "sl_fin", seg_t, seg_s, close_dt, seg_s,
                    InpSlColor, STYLE_SOLID, InpLineWidth);

        //--- Részleges zárás jelölő (Felező/Pajzs) — kis sárga pötty
        for(int p = 0; p < part_cnt; p++)
            DrawDot(pfx + "part" + IntegerToString(p), part_dt[p], part_px[p], clrGold);

        //--- Kiszállás: SZAGGATOTT függőleges vonal (nyert=zöld / vesztett=piros)
        DrawVLine(pfx + "close", close_dt, col_exit, STYLE_DASH, InpLineWidth);

        //--- Feliratok (BacktestReplayer szövegezés + P&L/R)
        if(InpShowLabels) {
            string lbl = StringFormat("%s %s  lot:%.2f  [%s]",
                                      dir, DoubleToString(entry, dg), lot0, profile);
            DrawText(pfx + "lbl_open", open_dt,
                     (is_buy ? (tp_draw > 0 ? tp_draw : entry) : sl0), lbl, col_dir);

            if(has_close) {
                string lbl2 = StringFormat("%s @ %s  P&L: %s %s  (%sR)",
                                           result, DoubleToString(close_price, dg),
                                           DoubleToString(pnl, 2),
                                           AccountInfoString(ACCOUNT_CURRENCY),
                                           DoubleToString(rr, 2));
                DrawText(pfx + "lbl_close", close_dt, close_price, lbl2, col_exit);
            }
        }

        trade_num++;
    }

    Print("BacktestPnLViewer: ", trade_num, " trade kirajzolva.");
}

//+------------------------------------------------------------------+
//| Összesítő panel a bal felső sarokban — SÖTÉT háttérrel, hogy       |
//| bármilyen chart-témán olvasható legyen (világos bg-en is).        |
//+------------------------------------------------------------------+
void DrawSummary()
{
    string ccy = AccountInfoString(ACCOUNT_CURRENCY);
    double wr  = (g_trades > 0) ? (100.0 * g_wins / g_trades) : 0.0;
    color  col = (g_tot_pnl >= 0.0) ? clrLime : clrTomato;   // sötét panelen a világos jól látszik

    string l0 = StringFormat("BacktestPnLViewer  —  %s", InpCsvFile);
    string l1 = StringFormat("Kotesek: %d   (nyero: %d / veszto: %d,  %.1f%%)",
                             g_trades, g_wins, g_losses, wr);
    string l2 = StringFormat("Osszes P&L: %s %s", DoubleToString(g_tot_pnl, 2), ccy);
    string l3 = StringFormat("Osszes R: %s R", DoubleToString(g_tot_r, 2));

    int x = InpPanelX, y = InpPanelY;
    DrawPanel(OBJ_PFX + "panel", x, y, 360, 92);        // sötét háttér-doboz
    DrawLabel(OBJ_PFX + "sum0", x + 8, y + 6,  l0, clrWhite,     9);
    DrawLabel(OBJ_PFX + "sum1", x + 8, y + 26, l1, clrGainsboro, 9);
    DrawLabel(OBJ_PFX + "sum2", x + 8, y + 46, l2, col,         10);
    DrawLabel(OBJ_PFX + "sum3", x + 8, y + 66, l3, col,         10);
}

//+------------------------------------------------------------------+
//| Sötét háttér-panel (OBJ_RECTANGLE_LABEL, képernyő-koordináta)     |
//+------------------------------------------------------------------+
void DrawPanel(string name, int x, int y, int w, int h)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
    ObjectSetInteger(0, name, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
    ObjectSetInteger(0, name, OBJPROP_XDISTANCE,  x);
    ObjectSetInteger(0, name, OBJPROP_YDISTANCE,  y);
    ObjectSetInteger(0, name, OBJPROP_XSIZE,      w);
    ObjectSetInteger(0, name, OBJPROP_YSIZE,      h);
    ObjectSetInteger(0, name, OBJPROP_BGCOLOR,    C'25,25,30');   // sötét szürke
    ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clrDimGray);    // keret
    ObjectSetInteger(0, name, OBJPROP_BACK,       false);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
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

void DrawArrow(string name, datetime dt, double price, int code, color clr, bool is_buy)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_ARROW, 0, dt, price);
    ObjectSetInteger(0, name, OBJPROP_ARROWCODE,  code);   // 233 fel = BUY, 234 le = SELL
    ObjectSetInteger(0, name, OBJPROP_ANCHOR,     is_buy ? ANCHOR_TOP : ANCHOR_BOTTOM);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      1);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       false);
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
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   InpFontSize);
    ObjectSetString(0,  name, OBJPROP_FONT,       "Courier New");
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       false);
}

void DrawLabel(string name, int x, int y, string text, color clr, int fs)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
    ObjectSetInteger(0, name, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
    ObjectSetInteger(0, name, OBJPROP_XDISTANCE,  x);
    ObjectSetInteger(0, name, OBJPROP_YDISTANCE,  y);
    ObjectSetString(0,  name, OBJPROP_TEXT,       text);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   fs);
    ObjectSetString(0,  name, OBJPROP_FONT,       "Consolas");
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_BACK,       false);
}

//+------------------------------------------------------------------+
void WritePathHint()
{
    string common_path = TerminalInfoString(TERMINAL_COMMONDATA_PATH);
    int fh = FileOpen("ide_kell_helyezni.txt", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
    if(fh != INVALID_HANDLE) {
        FileWriteString(fh, "IDE KELL MASOLNI A CSV FAJLT (BacktestPnLViewer):\r\n");
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
