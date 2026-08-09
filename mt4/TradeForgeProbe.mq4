//+------------------------------------------------------------------+
//|  TradeForgeProbe.mq4                                             |
//|  DIAGNOSZTIKA — nem rajzol semmit, csak MEGMONDJA, elér-e az MT4  |
//|  (kulonosen a Strategy Tester) a TradeForge viz-fajljahoz.        |
//|                                                                  |
//|  Miert kell: a Python a viz-pillanatkepet az MT5/MT4 KOZOS        |
//|  (Common\Files) mappajaba irja. Az MT4 tesztelo viszont           |
//|  tortenetileg homokozza a fajlelerest, es PORTABLE modban a       |
//|  Common mappa helye is elterhet. Ezt a KET dolgot itt merjuk meg,|
//|  MIELOTT barmit portolnank.                                      |
//|                                                                  |
//|  Hasznalat:                                                      |
//|    1) Masold az MT4 adatmappajaba: MQL4\Indicators\               |
//|    2) Forditsd le (MetaEditor: F7)                                |
//|    3) Huzd ra egy ELO chartra  -> latnod kell a zold osszegzest   |
//|    4) Indits Strategy Testert VIZUALIS modban, es huzd ra a       |
//|       tesztelo chartjara is -> ugyanannak kell latszania          |
//|                                                                  |
//|  A valasz a chart bal felso sarkaban + a Szakertok/Journal fulon. |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 0

// A Python oldal prefixe (strategy/visual.py: PREFIX = "TFV_")
#define TFV_PREFIX  "TFV_"
#define LBL         "TFProbe_"

input bool InpListAllFiles = true;   // ha a sajat fajl nincs meg: listazza a tobbit

string g_lines[];                    // a jelentes sorai (a chartra + a naplóba)


//+------------------------------------------------------------------+
//| Egy sor hozzaadasa a jelenteshez                                 |
//+------------------------------------------------------------------+
void Say(string s)
{
   int n = ArraySize(g_lines);
   ArrayResize(g_lines, n + 1);
   g_lines[n] = s;
   Print("[TFProbe] ", s);
}


//+------------------------------------------------------------------+
//| A jelentes kiirasa a chartra (vizualis teszteloben is latszik)    |
//+------------------------------------------------------------------+
void Render()
{
   for(int i = 0; i < ArraySize(g_lines); i++)
   {
      string name = LBL + IntegerToString(i);
      if(ObjectFind(0, name) < 0)
         ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 18 + i * 15);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  9);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_BACK,      false);
      // Az elso sor (verdikt) sarga, a tobbi vilagosszurke
      ObjectSetInteger(0, name, OBJPROP_COLOR, (i == 0 ? clrYellow : clrSilver));
      ObjectSetString (0, name, OBJPROP_FONT, "Consolas");
      ObjectSetString (0, name, OBJPROP_TEXT, g_lines[i]);
   }
   ChartRedraw(0);
}


//+------------------------------------------------------------------+
//| A Common\Files-ban levo TFV_*.csv fajlok listazasa                |
//| (ha a sajat szimbolum fajlja nincs meg, ebbol latszik a NEV-      |
//|  ELTERES: az MT5-os es az MT4-es szimbolumnev kulonbozhet)        |
//+------------------------------------------------------------------+
void ListCommonFiles()
{
   string fname;
   long   h = FileFindFirst(TFV_PREFIX + "*.csv", fname, FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      Say("  (a Common\\Files-ban NINCS egyetlen TFV_*.csv sem, vagy nem olvashato)");
      return;
   }
   int    cnt  = 0;
   string list = "";
   do
   {
      cnt++;
      if(cnt <= 12)
         list = list + (list == "" ? "" : ", ") + fname;
   }
   while(FileFindNext(h, fname));
   FileFindClose(h);
   Say("  talalt TFV_ fajl: " + IntegerToString(cnt));
   Say("  " + list + (cnt > 12 ? " ..." : ""));
}


//+------------------------------------------------------------------+
//| A sajat fajl beolvasasa es osszegzese                             |
//+------------------------------------------------------------------+
bool ProbeFile(string file)
{
   int h = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      Say("NEM SIKERULT megnyitni: " + file + "  (GetLastError=" +
          IntegerToString(GetLastError()) + ")");
      return(false);
   }

   int rows = 0, nState = 0, nArrow = 0, nVline = 0, nTrend = 0;
   int nText = 0, nLabel = 0, nInd = 0, nOther = 0, nClear = 0;
   datetime tMin = 0, tMax = 0;

   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) == 0) continue;
      rows++;

      string p[];
      int    k = StringSplit(line, ';', p);
      if(k <= 0) { nOther++; continue; }

      string kind = p[0];
      if(kind == "CLEAR")      nClear++;
      else if(kind == "STATE")
      {
         nState++;
         // STATE;<ido>;notrade;dir;window;market  — a mezo 1 a nyers bar-ido.
         // (Tobb-strategias fajlban a 1. mezo a strategia neve lehet -> akkor a 2.)
         if(k >= 2)
         {
            long t = StringToInteger(p[1]);
            if(t <= 0 && k >= 3) t = StringToInteger(p[2]);
            if(t > 0)
            {
               if(tMin == 0 || (datetime)t < tMin) tMin = (datetime)t;
               if((datetime)t > tMax)              tMax = (datetime)t;
            }
         }
      }
      else if(kind == "ARROW") nArrow++;
      else if(kind == "VLINE") nVline++;
      else if(kind == "TREND") nTrend++;
      else if(kind == "TEXT")  nText++;
      else if(kind == "LABEL") nLabel++;
      else if(kind == "IND")   nInd++;
      else                     nOther++;
   }
   FileClose(h);

   Say("OLVASAS OK: " + file);
   Say("  sorok=" + IntegerToString(rows) +
       "  STATE=" + IntegerToString(nState) +
       "  ARROW=" + IntegerToString(nArrow) +
       "  VLINE=" + IntegerToString(nVline));
   Say("  TREND=" + IntegerToString(nTrend) +
       "  TEXT="  + IntegerToString(nText) +
       "  LABEL=" + IntegerToString(nLabel) +
       "  IND="   + IntegerToString(nInd) +
       "  egyeb=" + IntegerToString(nOther + nClear));
   if(tMin > 0)
      Say("  STATE ido-tartomany: " + TimeToString(tMin, TIME_DATE | TIME_MINUTES) +
          "  ->  " + TimeToString(tMax, TIME_DATE | TIME_MINUTES));
   return(true);
}


//+------------------------------------------------------------------+
int OnInit()
{
   ArrayResize(g_lines, 0);

   bool testing = IsTesting();
   bool visual  = IsVisualMode();
   string ctx   = testing ? (visual ? "STRATEGY TESTER (vizualis)" : "STRATEGY TESTER (gyors)")
                          : "ELO CHART";

   Say("=== TradeForgeProbe ===   kontextus: " + ctx);
   Say("  szimbolum=" + Symbol() + "  idosik=" + IntegerToString(Period()) + " perc");
   // ⚠ EZ a kulcs-diagnosztika PORTABLE modhoz: hova mutat valojaban a Common?
   Say("  Common utvonal : " + TerminalInfoString(TERMINAL_COMMONDATA_PATH));
   Say("  Terminal adat  : " + TerminalInfoString(TERMINAL_DATA_PATH));
   Say("  tesztelo ideje : " + TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES));

   string file = TFV_PREFIX + Symbol() + ".csv";
   if(!ProbeFile(file))
   {
      Say("  -> a szimbolum-nev MT4-ben masmilyen lehet, mint MT5-ben.");
      if(InpListAllFiles) ListCommonFiles();
   }

   Render();
   return(INIT_SUCCEEDED);
}


//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, LBL);
}


//+------------------------------------------------------------------+
//| A tesztelo IDEJET is mutatjuk, hogy lassuk: halad-e a szimulacio  |
//| (ez lesz kesobb a look-ahead kapu alapja — csak a TimeCurrent()   |
//|  ELOTTI objektumokat szabad felfedni).                            |
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
   static datetime last = 0;
   if(TimeCurrent() != last)
   {
      last = TimeCurrent();
      string name = LBL + "clock";
      if(ObjectFind(0, name) < 0)
         ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 18 + ArraySize(g_lines) * 15 + 8);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  9);
      ObjectSetInteger(0, name, OBJPROP_COLOR,     clrAqua);
      ObjectSetString (0, name, OBJPROP_FONT,      "Consolas");
      ObjectSetString (0, name, OBJPROP_TEXT,
                       "chart ideje: " + TimeToString(last, TIME_DATE | TIME_MINUTES) +
                       "   (a look-ahead kapu ehhez fog igazodni)");
   }
   return(rates_total);
}
//+------------------------------------------------------------------+
