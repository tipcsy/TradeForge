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
//|     - vekony  : a chart sajat idosikjanak WPR-je (a sok kis belepo)|
//|     - vastag  : az M15 WPR LEPCSOSEN kiteritve (a fo kapu)        |
//|  Igy egyetlen al-ablakban ott a teljes dontesi kontextus, anelkul |
//|  hogy idosikot kellene valtani (a teszteloben nem is lehetne).    |
//|                                                                  |
//|  ⚠ Look-ahead: az iWPR a teszteloben csak a szimulalt idoig lat,  |
//|  tehat itt nem kell kulon kapu — az MT4 intezi.                   |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property version   "1.00"
#property strict
#property indicator_separate_window
#property indicator_minimum -100
#property indicator_maximum 0
#property indicator_buffers 2

#property indicator_color1  DodgerBlue
#property indicator_width1  1
#property indicator_label1  "WPR (chart TF)"

#property indicator_color2  Orange
#property indicator_width2  2
#property indicator_label2  "WPR M15 (fo kapu)"

input string InpFileSuffix = "";        // Fajl-utotag (pl. _BT)
input string InpStrategy   = "";        // Melyik strategia IND-jei (ures = az elso)
input int    InpGateTFMin  = 15;        // A FO KAPU idosikja percben (M15)
input bool   InpShowStatus = true;      // Fejlec az al-ablakban

#define PFX "TFV_"

double BufFast[];       // a chart sajat idosikjanak WPR-je
double BufGate[];       // a fo kapu (M15) WPR-je, lepcsosen

int    g_perFast = 0;   // a chart TF-jehez talalt periodus
int    g_perGate = 0;   // az M15-hoz talalt periodus
double g_levels[];
int    g_nlev = 0;
string g_src  = "";     // mit talaltunk (a fejlechez)


//+------------------------------------------------------------------+
//| "M1"/"M5"/"M15"… -> perc                                          |
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
//| Az IND;…;WPR;… rekordok kiolvasasa a motor fajljabol              |
//+------------------------------------------------------------------+
bool ReadIndRecords()
{
   string file = PFX + Symbol() + InpFileSuffix + ".csv";
   int h = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      Print("[TFWPR] NEM talalom: ", file);
      return(false);
   }

   int chartTf = Period();
   ArrayResize(g_levels, 0); g_nlev = 0;

   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringFind(ln, "IND;") != 0) continue;

      string f[];
      int n = StringSplit(ln, ';', f);
      // IND;<strat>;<kind>;<tf>;<period>;<color>;<levels...>
      if(n < 6) continue;
      if(InpStrategy != "" && f[1] != InpStrategy) continue;
      if(f[2] != "WPR") continue;

      int tf  = TfMinFromStr(f[3]);
      int per = (int)StringToInteger(f[4]);
      if(per <= 0) continue;

      if(tf == chartTf)
      {
         g_perFast = per;
         // A SZINTEKET a chart sajat idosikjanak rekordjabol vesszuk — az a
         // relevans annak, amit epp nezel.
         for(int i = 6; i < n; i++)
         {
            double lv = StringToDouble(f[i]);
            if(lv >= -100.0 && lv <= 0.0)
            {
               ArrayResize(g_levels, g_nlev + 1);
               g_levels[g_nlev] = lv; g_nlev++;
            }
         }
      }
      if(tf == InpGateTFMin)
         g_perGate = per;
   }
   FileClose(h);

   g_src = StringFormat("chartTF=%d per=%d | M%d per=%d | szintek=%d",
                        chartTf, g_perFast, InpGateTFMin, g_perGate, g_nlev);
   Print("[TFWPR] ", file, "  ", g_src);
   return(g_perFast > 0 || g_perGate > 0);
}


//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BufFast);
   SetIndexStyle(0, DRAW_LINE);
   SetIndexBuffer(1, BufGate);
   SetIndexStyle(1, DRAW_LINE);

   if(!ReadIndRecords())
      Print("[TFWPR] nincs hasznalhato IND rekord — a WPR ures marad.");

   // A szintek a MOTOR ertekei (extrem / trigger) — nem kezzel allitottak.
   for(int i = 0; i < g_nlev && i < 8; i++)
   {
      SetLevelValue(i, g_levels[i]);
      SetLevelStyle(STYLE_DOT, 1, clrSilver);
   }

   IndicatorShortName(StringFormat("TF WPR  %s(%d) + M%d(%d)",
                                   Symbol(), g_perFast, InpGateTFMin, g_perGate));
   IndicatorDigits(2);
   return(INIT_SUCCEEDED);
}


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

   int limit = rates_total - prev_calculated;
   if(prev_calculated > 0) limit++;
   if(limit > rates_total) limit = rates_total;

   for(int i = 0; i < limit; i++)
   {
      // 1) A chart sajat idosikjanak WPR-je
      BufFast[i] = (g_perFast > 0)
                   ? iWPR(Symbol(), Period(), g_perFast, i)
                   : EMPTY_VALUE;

      // 2) A FO KAPU (M15) WPR-je LEPCSOSEN kiteritve a chart gyertyaira.
      //    Ez a lenyeg M1-en: a teszteloben nem tudsz idosikot valtani, tehat a
      //    magasabb idosik allapotat IDE kell hozni. Minden M1 gyertyahoz azt az
      //    M15 gyertyat vesszuk, amelyikbe beleesik (iBarShift).
      if(g_perGate > 0)
      {
         int sh = iBarShift(Symbol(), (ENUM_TIMEFRAMES)InpGateTFMin, Time[i], false);
         BufGate[i] = (sh >= 0) ? iWPR(Symbol(), (ENUM_TIMEFRAMES)InpGateTFMin,
                                       g_perGate, sh)
                                : EMPTY_VALUE;
      }
      else BufGate[i] = EMPTY_VALUE;
   }
   return(rates_total);
}
//+------------------------------------------------------------------+
