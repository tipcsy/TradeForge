//+------------------------------------------------------------------+
//|                                            TradeForgeBands.mq4    |
//|  A TradeForge allapot-SAVJA (TBAND) MT4-re.                       |
//|                                                                  |
//|  Adat: a Common\Files\TFV_<Symbol>[suffix].csv STATE sorai:       |
//|     STATE;<strategia>;<epoch>;<notrade>;<dir>;<window>;<market>   |
//|                                                                  |
//|  Harom sav, fentrol lefele:                                       |
//|     1) szurke : no-trade ora (a motor ilyenkor nem lep be)        |
//|     2) zold/piros : SMA-irany (a fo trend-kapu)                   |
//|     3) kek   : aktiv M15 jelzesi ablak                            |
//|                                                                  |
//|  ⚠ MIERT KELL EZ M1-EN: a Strategy Testerben NEM tudsz idosikot   |
//|  valtani. A dontes viszont M15-on szuletik. A STATE sorok M15-hoz |
//|  vannak horgonyozva, ezert itt teritjuk ki oket a chart gyertyaira|
//|                                                                  |
//|  ⚠ LOOK-AHEAD: egy 10:00-as M15 gyertya allapota csak 10:15-kor   |
//|  ISMERT (akkor zar). Ezert egy M1 gyertyahoz alapbol az UTOLSO MAR|
//|  LEZART M15 gyertya allapotat vesszuk (InpUseClosedOnly).         |
//|                                                                  |
//|  ⚠ MQL4-SPECIFIKUS: itt NINCS DRAW_FILLING es nincs per-gyertya   |
//|  szinindex (DRAW_COLOR_HISTOGRAM2) — azok MQL5-osek. Helyette      |
//|  EGYMASRA RAJZOLT DRAW_HISTOGRAM: minden histogram 0-tol indul,   |
//|  a magasabbat rajzoljuk ELOBB, a rovidebb kesobb RA — igy allnak   |
//|  ossze a vizszintes savok. Ez tisztan MQL4-natív, nem fugg build-  |
//|  specifikus MQL5-atvetelektol.                                    |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property version   "1.10"
#property strict
#property indicator_separate_window
#property indicator_minimum 0.0
#property indicator_maximum 1.0
#property indicator_buffers 4

input string InpFileSuffix    = "";     // Fajl-utotag (pl. _BT)
input string InpStrategy      = "";     // Melyik strategia STATE sorai (ures = MIND)
input int    InpStateTFMin    = 15;     // A STATE sorok idosikja percben
input bool   InpUseClosedOnly = true;   // CSAK lezart M15 allapot (look-ahead ellen)

#define PFX "TFV_"
#define LBL "TFB_status"

// Egymasra rajzolt histogramok. A SORREND SZAMIT: a magasabb elobb.
double NoTrade[];    // 0 -> 1.00 magas  (a legfelso sav lesz lathato)
double TrBuy[];      // 1 -> 0.67
double TrSell[];     // 2 -> 0.67
double Window[];     // 3 -> 0.33        (a legalso sav)

datetime g_t[];
int      g_nt[], g_dir[], g_win[];
int      g_ns  = 0;
string   g_msg = "";


//+------------------------------------------------------------------+
void Status(string txt, color c)
{
   int win = ChartWindowFind();
   if(win < 0) win = 0;
   if(ObjectFind(0, LBL) < 0)
      ObjectCreate(0, LBL, OBJ_LABEL, win, 0, 0);
   ObjectSetInteger(0, LBL, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, LBL, OBJPROP_XDISTANCE, 6);
   ObjectSetInteger(0, LBL, OBJPROP_YDISTANCE, 2);
   ObjectSetInteger(0, LBL, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, LBL, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, LBL, OBJPROP_COLOR, c);
   ObjectSetString (0, LBL, OBJPROP_FONT, "Consolas");
   ObjectSetString (0, LBL, OBJPROP_TEXT, txt);
}


//+------------------------------------------------------------------+
bool ReadStates()
{
   string file = PFX + Symbol() + InpFileSuffix + ".csv";
   int h = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      g_msg = "NINCS FAJL: " + file + "  (hiba=" + IntegerToString(GetLastError()) + ")";
      Print("[TFBands] ", g_msg);
      return(false);
   }

   ArrayResize(g_t, 0); ArrayResize(g_nt, 0);
   ArrayResize(g_dir, 0); ArrayResize(g_win, 0);
   g_ns = 0;
   int skippedStrat = 0;

   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringFind(ln, "STATE;") != 0) continue;
      string f[];
      int n = StringSplit(ln, ';', f);
      if(n < 6) continue;
      if(InpStrategy != "" && f[1] != InpStrategy) { skippedStrat++; continue; }

      ArrayResize(g_t,   g_ns + 1); g_t[g_ns]   = (datetime)StringToInteger(f[2]);
      ArrayResize(g_nt,  g_ns + 1); g_nt[g_ns]  = (int)StringToInteger(f[3]);
      ArrayResize(g_dir, g_ns + 1); g_dir[g_ns] = (int)StringToInteger(f[4]);
      ArrayResize(g_win, g_ns + 1); g_win[g_ns] = (int)StringToInteger(f[5]);
      g_ns++;
   }
   FileClose(h);

   if(g_ns == 0)
   {
      g_msg = "0 STATE sor (" + file + ")" +
              (skippedStrat > 0 ? "  — mind MAS strategiae, allitsd az InpStrategy-t!" : "");
      Print("[TFBands] ", g_msg);
      return(false);
   }
   g_msg = StringFormat("%s | STATE=%d | %s -> %s", file, g_ns,
                        TimeToString(g_t[0], TIME_DATE | TIME_MINUTES),
                        TimeToString(g_t[g_ns - 1], TIME_DATE | TIME_MINUTES));
   Print("[TFBands] ", g_msg);
   return(true);
}


//+------------------------------------------------------------------+
//| Az `at` idohoz tartozo STATE (az UTOLSO, amelyik <= at). -1: nincs|
//+------------------------------------------------------------------+
int FindState(datetime at)
{
   if(g_ns == 0 || at < g_t[0]) return(-1);
   int lo = 0, hi = g_ns - 1, res = -1;
   while(lo <= hi)
   {
      int mid = (lo + hi) / 2;
      if(g_t[mid] <= at) { res = mid; lo = mid + 1; }
      else                 hi = mid - 1;
   }
   return(res);
}


//+------------------------------------------------------------------+
int OnInit()
{
   IndicatorBuffers(4);
   SetIndexBuffer(0, NoTrade); SetIndexStyle(0, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'150,150,150');
   SetIndexBuffer(1, TrBuy);   SetIndexStyle(1, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'0,170,0');
   SetIndexBuffer(2, TrSell);  SetIndexStyle(2, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'220,0,0');
   SetIndexBuffer(3, Window);  SetIndexStyle(3, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'0,120,255');

   SetIndexLabel(0, "No-trade");
   SetIndexLabel(1, "Trend BUY");
   SetIndexLabel(2, "Trend SELL");
   SetIndexLabel(3, "M15 ablak");
   for(int b = 0; b < 4; b++) SetIndexEmptyValue(b, 0.0);

   bool ok = ReadStates();
   IndicatorShortName("TF Bands");
   IndicatorDigits(2);
   Status("TFBands: " + g_msg, ok ? clrSilver : clrOrangeRed);
   return(INIT_SUCCEEDED);
}


//+------------------------------------------------------------------+
void OnDeinit(const int reason) { ObjectDelete(0, LBL); }


//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   Status("TFBands: " + g_msg, (g_ns > 0) ? clrSilver : clrOrangeRed);
   if(g_ns == 0) return(rates_total);

   int limit = rates_total - prev_calculated;
   if(prev_calculated > 0) limit++;
   if(limit > rates_total) limit = rates_total;

   int holdSec = InpStateTFMin * 60;
   int hit = 0;
   for(int i = 0; i < limit; i++)
   {
      NoTrade[i] = 0.0; TrBuy[i] = 0.0; TrSell[i] = 0.0; Window[i] = 0.0;

      // Look-ahead ellen: az M15 gyertya allapota csak a ZARASAKOR ismert.
      datetime at = Time[i];
      if(InpUseClosedOnly) at -= holdSec;

      int k = FindState(at);
      if(k < 0) continue;
      if(at - g_t[k] > holdSec * 2) continue;   // hetvege / adathezag: ne hordjuk at
      hit++;

      // A MAGASABB histogramot elobb rajzoljuk (kisebb buffer-index), a rovidebbet
      // kesobb RA -> igy allnak ossze a vizszintes savok.
      if(g_nt[k]  != 0) NoTrade[i] = 1.00;
      if(g_dir[k] > 0)  TrBuy[i]   = 0.67;
      else if(g_dir[k] < 0) TrSell[i] = 0.67;
      if(g_win[k] != 0) Window[i]  = 0.33;
   }
   if(hit == 0)
      Status("TFBands: " + g_msg + "  ⚠ a chart idotartomanya NEM fedi a STATE ablakot",
             clrOrangeRed);
   return(rates_total);
}
//+------------------------------------------------------------------+
