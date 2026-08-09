//+------------------------------------------------------------------+
//|                                              TradeForgeWPR.mq4    |
//|  A TradeForge WPR-je — a PARAMETEREIT A MOTOR FAJLJABOL veszi.    |
//|                                                                  |
//|  Miert igy: ha a WPR-t kezzel allitanad be a charton, elcsuszhatna|
//|  attol, amivel a motor SZAMOL — es a manualis teszt mast mutatna, |
//|  mint amit a program latott. Ezert a periodus ES a szintek a      |
//|  Common\Files\TFV_<Symbol>[suffix].csv `IND` rekordjaibol jonnek: |
//|                                                                  |
//|     IND;<strategia>;WPR;<TF>;<periodus>;<szin>;<szint1>;<szint2>… |
//|                                                                  |
//|  KET vonalat rajzol, mert M1-en tesztelunk, de a FO KAPU M15:     |
//|     - vekony kek : a chart sajat idosikjanak WPR-je               |
//|     - vastag naracs : az M15 WPR LEPCSOSEN kiteritve (a fo kapu)  |
//|                                                                  |
//|  ⚠ Look-ahead: az iWPR a teszteloben csak a szimulalt idoig lat,  |
//|  tehat itt nem kell kulon kapu — az MT4 intezi.                   |
//|  ⚠ Az M15-os vonalhoz az MT4-nek M15 elozmeny is kell.            |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property version   "1.10"
#property strict
#property indicator_separate_window
#property indicator_minimum -100
#property indicator_maximum 0
#property indicator_buffers 2

input string InpFileSuffix = "";        // Fajl-utotag (pl. _BT)
input string InpStrategy   = "";        // Melyik strategia IND-jei (ures = MIND)
input int    InpGateTFMin  = 15;        // A FO KAPU idosikja percben (M15)

#define PFX "TFV_"
#define LBL "TFW_status"

double BufFast[];       // a chart sajat idosikjanak WPR-je
double BufGate[];       // a fo kapu (M15) WPR-je, lepcsosen

int    g_perFast = 0;
int    g_perGate = 0;
double g_levels[];
int    g_nlev = 0;
string g_msg  = "";


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
//| A HASZNALANDO fajl neve — lasd a TradeForgeViz reszletes indoklasat|
//| (SABLON-CSAPDA: a tester.tpl felulirja az inputokat, igy a kezzel  |
//| beallitott `_BT` utotag a teszteloben nemam elveszne).            |
//+------------------------------------------------------------------+
string ResolveFile(string suffix)
{
   string base = PFX + Symbol();
   if(suffix != "")
      return(base + suffix + ".csv");
   if(IsTesting())
   {
      string bt = base + "_BT.csv";
      int h = FileOpen(bt, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
      if(h != INVALID_HANDLE) { FileClose(h); return(bt); }
   }
   return(base + ".csv");
}


//+------------------------------------------------------------------+
int TfMinFromStr(string s)
{
   if(s == "M1")  return(1);
   if(s == "M5")  return(5);
   if(s == "M15") return(15);
   if(s == "M30") return(30);
   if(s == "H1")  return(60);
   if(s == "H4")  return(240);
   if(s == "D1")  return(1440);
   return(0);
}


//+------------------------------------------------------------------+
bool ReadIndRecords()
{
   string file = ResolveFile(InpFileSuffix);
   int h = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      g_msg = "NINCS FAJL: " + file + "  (hiba=" + IntegerToString(GetLastError()) + ")";
      Print("[TFWPR] ", g_msg);
      return(false);
   }

   int chartTf = Period();
   int nWpr = 0;
   string found = "";
   ArrayResize(g_levels, 0); g_nlev = 0;

   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringFind(ln, "IND;") != 0) continue;
      string f[];
      int n = StringSplit(ln, ';', f);
      if(n < 6) continue;                                  // IND;strat;kind;tf;per;szin
      if(InpStrategy != "" && f[1] != InpStrategy) continue;
      if(f[2] != "WPR") continue;

      nWpr++;
      int tf  = TfMinFromStr(f[3]);
      int per = (int)StringToInteger(f[4]);
      if(per <= 0) continue;
      found = found + (found == "" ? "" : ",") + f[3] + "(" + f[4] + ")";

      if(tf == chartTf)
      {
         g_perFast = per;
         for(int i = 6; i < n; i++)                        // a szintek a chart TF-jerol
         {
            double lv = StringToDouble(f[i]);
            if(lv >= -100.0 && lv <= 0.0)
            {
               ArrayResize(g_levels, g_nlev + 1);
               g_levels[g_nlev] = lv; g_nlev++;
            }
         }
      }
      if(tf == InpGateTFMin) g_perGate = per;
   }
   FileClose(h);

   if(nWpr == 0)
   {
      g_msg = "0 WPR rekord (" + file + ")";
      Print("[TFWPR] ", g_msg);
      return(false);
   }
   if(g_perFast == 0 && g_perGate == 0)
   {
      g_msg = "van WPR rekord [" + found + "], de EGYIK SEM illik a charthoz (M" +
              IntegerToString(chartTf) + ") vagy a kapuhoz (M" +
              IntegerToString(InpGateTFMin) + ")";
      Print("[TFWPR] ", g_msg);
      return(false);
   }
   g_msg = StringFormat("chart M%d per=%d | kapu M%d per=%d | szintek=%d | rekordok:[%s]",
                        chartTf, g_perFast, InpGateTFMin, g_perGate, g_nlev, found);
   Print("[TFWPR] ", file, "  ", g_msg);
   return(true);
}


//+------------------------------------------------------------------+
int OnInit()
{
   IndicatorBuffers(2);
   SetIndexBuffer(0, BufFast);
   SetIndexStyle(0, DRAW_LINE, STYLE_SOLID, 1, C'30,144,255');
   SetIndexLabel(0, "WPR chart TF");
   SetIndexEmptyValue(0, EMPTY_VALUE);

   SetIndexBuffer(1, BufGate);
   SetIndexStyle(1, DRAW_LINE, STYLE_SOLID, 2, C'255,140,0');
   SetIndexLabel(1, "WPR M15 (fo kapu)");
   SetIndexEmptyValue(1, EMPTY_VALUE);

   bool ok = ReadIndRecords();
   for(int i = 0; i < g_nlev && i < 8; i++)
   {
      SetLevelValue(i, g_levels[i]);
      SetLevelStyle(STYLE_DOT, 1, C'160,160,160');
   }

   IndicatorShortName("TF WPR");
   IndicatorDigits(2);
   Status("TFWPR: " + g_msg, ok ? clrSilver : clrOrangeRed);
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
   if(rates_total < 2) return(0);
   Status("TFWPR: " + g_msg,
          (g_perFast > 0 || g_perGate > 0) ? clrSilver : clrOrangeRed);

   int limit = rates_total - prev_calculated;
   if(prev_calculated > 0) limit++;
   if(limit > rates_total) limit = rates_total;

   for(int i = 0; i < limit; i++)
   {
      BufFast[i] = (g_perFast > 0) ? iWPR(Symbol(), Period(), g_perFast, i)
                                   : EMPTY_VALUE;

      // A FO KAPU (M15) WPR-je LEPCSOSEN a chart gyertyaira: minden M1 gyertyahoz
      // az az M15 gyertya, amelyikbe beleesik. A teszteloben az iWPR maga sem lat
      // a szimulalt idon tul, tehat ez nem look-ahead.
      if(g_perGate > 0)
      {
         int sh = iBarShift(Symbol(), InpGateTFMin, Time[i], false);
         BufGate[i] = (sh >= 0) ? iWPR(Symbol(), InpGateTFMin, g_perGate, sh)
                                : EMPTY_VALUE;
      }
      else BufGate[i] = EMPTY_VALUE;
   }
   return(rates_total);
}
//+------------------------------------------------------------------+
