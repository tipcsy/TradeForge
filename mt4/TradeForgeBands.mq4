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
//|  — igy egyetlen M1 charton is latod a magasabb idosik allapotat.   |
//|                                                                  |
//|  ⚠ LOOK-AHEAD: egy 10:00-as M15 gyertya allapota csak 10:15-kor   |
//|  ISMERT (akkor zar). Ezert egy M1 gyertyahoz alapbol az UTOLSO MAR|
//|  LEZART M15 gyertya allapotat vesszuk (InpUseClosedOnly). Enelkul  |
//|  a sav 15 percet elore latna — pont az a hiba, amit a manualis     |
//|  teszt kiszurni hivatott.                                         |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property version   "1.00"
#property strict
#property indicator_separate_window
#property indicator_minimum 0.0
#property indicator_maximum 1.0
#property indicator_buffers 8
#property indicator_plots   4

input string InpFileSuffix     = "";     // Fajl-utotag (pl. _BT)
input string InpStrategy       = "";     // Melyik strategia STATE sorai (ures = az elso)
input int    InpStateTFMin     = 15;     // A STATE sorok idosikja percben
input bool   InpUseClosedOnly  = true;   // CSAK lezart M15 allapot (look-ahead ellen)
input bool   InpShowStatus     = true;   // Fejlec

#define PFX "TFV_"

// 3 sav × (also, felso) — DRAW_FILLING-gel kitoltve. A trend-savhoz KET plot kell
// (zold es piros), mert az MQL4-ben egy ploton belul nincs per-gyertya szinindex.
double NtTop[],  NtBot[];      // 0: no-trade (szurke)
double BuTop[],  BuBot[];      // 1: trend BUY (zold)
double SeTop[],  SeBot[];      // 2: trend SELL (piros)
double WnTop[],  WnBot[];      // 3: M15 ablak (kek)

// A beolvasott STATE sorok (ido szerint novekvo — a Python igy irja)
datetime g_t[];
int      g_nt[], g_dir[], g_win[];
int      g_ns = 0;
string   g_info = "";


//+------------------------------------------------------------------+
//| Egy sav fuggoleges helye (0..1) — k. sav n-bol, fentrol           |
//+------------------------------------------------------------------+
void BandPos(int k, int n, double &top, double &bot)
{
   double h = 1.0 / n;
   top = 1.0 - k * h - h * 0.10;
   bot = 1.0 - (k + 1) * h + h * 0.10;
}


//+------------------------------------------------------------------+
//| STATE sorok beolvasasa                                           |
//+------------------------------------------------------------------+
bool ReadStates()
{
   string file = PFX + Symbol() + InpFileSuffix + ".csv";
   int h = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE) { Print("[TFBands] NEM talalom: ", file); return(false); }

   ArrayResize(g_t, 0); ArrayResize(g_nt, 0);
   ArrayResize(g_dir, 0); ArrayResize(g_win, 0);
   g_ns = 0;

   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringFind(ln, "STATE;") != 0) continue;
      string f[];
      int n = StringSplit(ln, ';', f);
      // Tagelt alak: STATE;<strat>;<t>;<notrade>;<dir>;<window>;<market>
      if(n < 6) continue;
      if(InpStrategy != "" && f[1] != InpStrategy) continue;

      ArrayResize(g_t,   g_ns + 1); g_t[g_ns]   = (datetime)StringToInteger(f[2]);
      ArrayResize(g_nt,  g_ns + 1); g_nt[g_ns]  = (int)StringToInteger(f[3]);
      ArrayResize(g_dir, g_ns + 1); g_dir[g_ns] = (int)StringToInteger(f[4]);
      ArrayResize(g_win, g_ns + 1); g_win[g_ns] = (int)StringToInteger(f[5]);
      g_ns++;
   }
   FileClose(h);
   g_info = StringFormat("%s | STATE=%d", file, g_ns);
   Print("[TFBands] ", g_info);
   return(g_ns > 0);
}


//+------------------------------------------------------------------+
//| Az `at` idohoz tartozo STATE indexe (binaris kereses: az UTOLSO,  |
//| amelyik <= at). -1 ha nincs.                                      |
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
   SetIndexBuffer(0, NtTop); SetIndexBuffer(1, NtBot);
   SetIndexBuffer(2, BuTop); SetIndexBuffer(3, BuBot);
   SetIndexBuffer(4, SeTop); SetIndexBuffer(5, SeBot);
   SetIndexBuffer(6, WnTop); SetIndexBuffer(7, WnBot);

   SetIndexStyle(0, DRAW_FILLING, STYLE_SOLID, 1, C'150,150,150');  // no-trade
   SetIndexStyle(2, DRAW_FILLING, STYLE_SOLID, 1, C'0,170,0');      // BUY
   SetIndexStyle(4, DRAW_FILLING, STYLE_SOLID, 1, C'220,0,0');      // SELL
   SetIndexStyle(6, DRAW_FILLING, STYLE_SOLID, 1, C'0,120,255');    // ablak

   SetIndexLabel(0, "No-trade");  SetIndexLabel(1, NULL);
   SetIndexLabel(2, "Trend BUY"); SetIndexLabel(3, NULL);
   SetIndexLabel(4, "Trend SELL");SetIndexLabel(5, NULL);
   SetIndexLabel(6, "M15 ablak"); SetIndexLabel(7, NULL);

   for(int b = 0; b < 8; b++) SetIndexEmptyValue(b, EMPTY_VALUE);

   if(!ReadStates())
      Print("[TFBands] nincs STATE sor — a sav ures marad.");

   IndicatorShortName(StringFormat("TF Bands  %s  (M%d -> chart, %s)",
                      Symbol(), InpStateTFMin,
                      InpUseClosedOnly ? "csak lezart" : "nyers"));
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
   if(g_ns == 0) return(rates_total);

   double t0, b0, t1, b1, t2, b2;
   BandPos(0, 3, t0, b0);
   BandPos(1, 3, t1, b1);
   BandPos(2, 3, t2, b2);

   int limit = rates_total - prev_calculated;
   if(prev_calculated > 0) limit++;
   if(limit > rates_total) limit = rates_total;

   int holdSec = InpStateTFMin * 60;
   for(int i = 0; i < limit; i++)
   {
      NtTop[i] = EMPTY_VALUE; NtBot[i] = EMPTY_VALUE;
      BuTop[i] = EMPTY_VALUE; BuBot[i] = EMPTY_VALUE;
      SeTop[i] = EMPTY_VALUE; SeBot[i] = EMPTY_VALUE;
      WnTop[i] = EMPTY_VALUE; WnBot[i] = EMPTY_VALUE;

      // Look-ahead ellen: az M15 gyertya allapota csak a ZARASAKOR ismert.
      datetime at = Time[i];
      if(InpUseClosedOnly) at -= holdSec;

      int k = FindState(at);
      if(k < 0) continue;
      // Ne hordjuk at az allapotot hetvegen/adathezagon: max egy idosiknyi tavolsag
      // + egy kis turés (a STATE sorok kozott lehet piaci szunet).
      if(at - g_t[k] > holdSec * 2) continue;

      if(g_nt[k] != 0) { NtTop[i] = t0; NtBot[i] = b0; }
      if(g_dir[k] > 0) { BuTop[i] = t1; BuBot[i] = b1; }
      else if(g_dir[k] < 0) { SeTop[i] = t1; SeBot[i] = b1; }
      if(g_win[k] != 0) { WnTop[i] = t2; WnBot[i] = b2; }
   }
   return(rates_total);
}
//+------------------------------------------------------------------+
