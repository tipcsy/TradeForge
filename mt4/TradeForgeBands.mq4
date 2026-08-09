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
//|  ⚠ LOOK-AHEAD — ES HOL TORTENIK: egy 10:30-as M15 gyertya allapota|
//|  csak 10:45-kor ISMERT (akkor zar). Ezt az eltolast a PYTHON EXPORT|
//|  MAR ELVEGZI (`t = tl_t[k] + m15_sec`), tehat a fajlban levo T     |
//|  idopontu STATE mar look-ahead-mentes. Itt NEM szabad ujra eltolni |
//|  — az duplan kesleltetne (lasd InpUseClosedOnly).                  |
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
// ⚠ ALAPBOL KI — es ez FONTOS. A Python export MAR ELTOLTA a STATE sorokat egy
// M15 gyertyaval (`wpr_sma.visual_objects`: `t = tl_t[k] + m15_sec`, "a jelzes az
// M15 gyertya ZARASA UTAN el"). A fajlban levo T idopontu allapot tehat MAR a
// T-15p gyertya zarasabol szamolt, look-ahead-mentes ertek.
// Ha itt MEG EGYSZER visszalepunk 15 percet, a sav DUPLAN kesik: merve a kek
// ablak-sav 15 perccel tovabb maradt bekapcsolva, mint ahogy a motor latta.
// Csak akkor kapcsold BE, ha egy strategia NEM tolja el a sajat STATE sorait.
input bool   InpUseClosedOnly = false;  // EXTRA visszalepes egy idosikkal (duplan kesleltet!)
// A fejlec helye/merete: vilagos charton a szurke olvashatatlan volt, ezert
// sotet az alapszin; az eltolas azert input, mert mas indikator is odaerhet.
input int    InpStatusX       = 6;      // Fejlec vizszintes eltolas (px)
input int    InpStatusY       = 2;      // Fejlec FUGGOLEGES eltolas (px)
input int    InpStatusFont    = 8;      // Betumeret
input int    InpBandHeightPx  = 24;     // EGY sav magassaga px (0 = kezi meretezes)

#define PFX "TFV_"
#define LBL "TFB_status"

// ── SAV-SORREND (fentrol lefele) — AZONOS az MT5-os TradeForgeBands-szel ──────
//     1) KEK    : aktiv M15 jelzesi ablak
//     2) ZOLD/PIROS : SMA-irany (a fo trend-kapu)
//     3) SZURKE : no-trade ora
//
// ⚠ Az elso MQL4-portom ezt FORDITVA rakta le (szurke felul, kek alul) — a
// megszokott kep feje tetejere allt.
//
// Technika: egymasra rajzolt DRAW_HISTOGRAM. Mind 0-tol indul, ezert a LEGFELSO
// sav a LEGMAGASABB es azt rajzoljuk ELOSZOR; a kesobbi (rovidebb) histogramok
// rafestenek az also reszre. A buffer-sorrend tehat a sav-sorrend.
double Window[];     // 0 -> a legmagasabb  (a KEK sav lesz lathato felul)
double TrBuy[];      // 1
double TrSell[];     // 2
double NoTrade[];    // 3 -> a legrovidebb  (SZURKE, alul)

// Csak azok a savok kapnak helyet, amelyekben VAN adat. Ha pl. minden ora
// engedelyezett (a no-trade vegig 0), a szurke sav elhagyasa a maradek kettonek
// KETSZER akkora helyet ad — a merteknel ez a kulonbseg dont.
double h_win = 0.0, h_trend = 0.0, h_nt = 0.0;
int    g_nbands = 0;

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
   ObjectSetInteger(0, LBL, OBJPROP_XDISTANCE, InpStatusX);
   ObjectSetInteger(0, LBL, OBJPROP_YDISTANCE, InpStatusY);
   ObjectSetInteger(0, LBL, OBJPROP_FONTSIZE, InpStatusFont);
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
bool ReadStates()
{
   string file = ResolveFile(InpFileSuffix);
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
   // A buffer-sorrend = a sav-sorrend fentrol lefele (lasd fent).
   SetIndexBuffer(0, Window);  SetIndexStyle(0, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'0,120,255');
   SetIndexBuffer(1, TrBuy);   SetIndexStyle(1, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'0,170,0');
   SetIndexBuffer(2, TrSell);  SetIndexStyle(2, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'220,0,0');
   SetIndexBuffer(3, NoTrade); SetIndexStyle(3, DRAW_HISTOGRAM, STYLE_SOLID, 3, C'150,150,150');

   SetIndexLabel(0, "M15 ablak");
   SetIndexLabel(1, "Trend BUY");
   SetIndexLabel(2, "Trend SELL");
   SetIndexLabel(3, "No-trade");
   for(int b = 0; b < 4; b++) SetIndexEmptyValue(b, 0.0);

   bool ok = ReadStates();

   // ⚠ A SZURKE es a ZOLD/PIROS EGY sorba kerul (v2.24.6). Nem tomorites: a ketto
   // KIZARJA egymast. A Python `apply_no_trade` a no-trade gyertyan `dir=0`-t is
   // beallit, tehat ha szurke van, trend-szin SOSEM lehet — es forditva. Ket kulon
   // sor egyiket mindig uresen hagyta, feleslegesen fogyasztva a magassagot.
   bool useWin = false, useState = false;
   for(int i = 0; i < g_ns; i++)
   {
      if(g_win[i] != 0) useWin = true;
      if(g_dir[i] != 0 || g_nt[i] != 0) useState = true;
   }
   g_nbands = (useWin ? 1 : 0) + (useState ? 1 : 0);
   if(g_nbands == 0) g_nbands = 1;

   // Fentrol lefele: kek (M15-ablak) -> allapot (szurke VAGY zold/piros).
   int k = 0;
   if(useWin)   { h_win = (double)(g_nbands - k) / g_nbands; k++; }
   if(useState)
   {
      double h = (double)(g_nbands - k) / g_nbands;
      h_trend = h; h_nt = h;                 // KOZOS sor — kizarjak egymast
      k++;
   }

   // Az al-ablak magassaga a savszamhoz igazodik — kulonben harom sav egy 20 px-es
   // csikban osszemosodik (pontosan ez tette olvashatatlanna az elso valtozatot).
   if(InpBandHeightPx > 0)
   {
      int w = ChartWindowFind();
      if(w > 0) ChartSetInteger(0, CHART_HEIGHT_IN_PIXELS, w, g_nbands * InpBandHeightPx);
   }

   IndicatorShortName("TF Bands");
   IndicatorDigits(2);
   Status("TFBands: " + g_msg, ok ? clrNavy : clrRed);
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
   Status("TFBands: " + g_msg, (g_ns > 0) ? clrNavy : clrRed);
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
      // A magassagok az OnInit-ben dolnek el (csak a HASZNALT savok kapnak helyet).
      if(g_win[k] != 0)     Window[i]  = h_win;
      if(g_dir[k] > 0)      TrBuy[i]   = h_trend;
      else if(g_dir[k] < 0) TrSell[i]  = h_trend;
      if(g_nt[k]  != 0)     NoTrade[i] = h_nt;
   }
   if(hit == 0)
      Status("TFBands: " + g_msg + "  ⚠ a chart idotartomanya NEM fedi a STATE ablakot",
             clrRed);
   return(rates_total);
}
//+------------------------------------------------------------------+
