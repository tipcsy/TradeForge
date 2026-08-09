//+------------------------------------------------------------------+
//|                                              TradeForgeViz.mq4    |
//|  A TradeForge chart-vizualizacio MT4-es valtozata: felolvassa a    |
//|  Python altal irt Common\Files\TFV_<Symbol>[suffix].csv fajlt es   |
//|  kirajzolja az objektumokat.                                      |
//|                                                                  |
//|  ⚠ AMIBEN ELTER AZ MT5-OSTOL — es ez a lenyeg:                    |
//|                                                                  |
//|  LOOK-AHEAD KAPU. A fajl a TELJES pillanatkep, a JOVOBELI jelekkel|
//|  egyutt. Ha a Strategy Testerben mindet kirajzolnank, latnad a    |
//|  holnapi belepot ma — a manualis teszt ertelmet vesztene. Ezert az|
//|  objektumok CSAK a chart aktualis idejeig (Time[0]) fedodnek fel, |
//|  a szakaszok (TREND: SL/TP, szalag) pedig EGYUTT NONEK az idovel. |
//|                                                                  |
//|  Telepites: masold az MQL4\Indicators mappaba, forditsd (F7),     |
//|  majd huzd a chartra (elo VAGY vizualis tesztelo).                |
//|                                                                  |
//|  A fajl a KOZOS (Common) mappaban van — merve: az MT4 tesztelo    |
//|  olvassa, es PORTABLE modban sem koltozik.                        |
//+------------------------------------------------------------------+
#property copyright "TradeForge"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 0

input string InpFileSuffix    = "";     // Fajl-utotag (pl. _BT a visszajatszashoz)
input string InpStrategy      = "";     // Melyik STRATEGIAT mutassa (ures = MIND)
input bool   InpReplayGate    = true;   // Look-ahead kapu (tesztelohoz KELL)
input int    InpTimerSeconds  = 1;      // Ujraolvasas elo charton (mp)
input bool   InpShowStatus    = true;   // Allapotsor megjelenitese
// ⚠ A viz-fajl SAJAT tabla-feliratai (SMA Period / WPR M15 / WPR M1) is a bal
// felso sarokban ulnek, y=20..68 kozott — ezert az allapotsor alapbol ALATTUK
// kezdodik. Ha nalad mas is ott van (FxSmartHand, masik indikator), told lejjebb.
input int    InpStatusCorner  = 0;      // Sarok: 0=bal-fent 1=bal-lent 2=jobb-fent 3=jobb-lent
input int    InpStatusX       = 10;     // Vizszintes eltolas (px)
input int    InpStatusY       = 90;     // FUGGOLEGES eltolas (px) — ezt told, ha takar
input int    InpStatusFont    = 9;      // Betumeret
input color  InpStatusColor   = clrNavy;// Alapszin (VILAGOS hatterhez sotet kell!)
// ⚠ SPOILER: megmondja, MENNYI IDO mulva jon a kovetkezo belepo. Kenyelmes, de
// elrontja a merest: ha tudod, hogy 3 oran belul nincs jel, nem tudod oszinten
// megiteni, hogy TE beszalltal-e volna kozben. Alapbol KI.
input bool   InpShowNextTime  = false;  // Kovetkezo jel IDEJE is (spoiler!)

#define PFX      "TFV_"
#define STATUSNM "TFV_zz_status"

string g_file;        // TFV_<Symbol><suffix>.csv
string g_objpref;     // szuro-prefix: TFV_  VAGY  TFV_<InpStrategy>@

// A beolvasott rekordok. A tesztelo miatt CACHE-eljuk: a fajl ott nem valtozik,
// viszont bar-onkent ujra kell donteni, mi lathato mar.
string   g_ln[];      // a nyers sor
datetime g_t[];       // a rekord horgony-ideje (0 = mindig lathato, pl. LABEL)
datetime g_t2[];      // szakasz-vegpont (TREND); 0 ha nem szakasz
bool     g_done[];    // mar veglegesen kirakva (nem no tovabb)
int      g_n = 0;
string   g_names[];   // a felrakott objektumok nevei (sopreshez)
int      g_nnames = 0;
datetime g_lastReveal = 0;
bool     g_isTester   = false;

// ── Belepo-jelzes szamlalo ────────────────────────────────────────────────────
// Kerdes volt: "hany kotes van meg hatra? Nem a vegtelenbe tekerem a chartot?"
// A VLINE a belepo-jelzes fuggoleges vonala (strategiatol fuggetlenul), a szine
// adja az iranyt: zold = BUY, piros = SELL.
bool     g_isSig[];      // a rekord belepo-jelzes-e
int      g_sigDir[];     // +1 BUY, -1 SELL
int      g_sigTotal = 0, g_sigBuy = 0, g_sigSell = 0;
datetime g_sigLast  = 0; // az UTOLSO jel ideje (meddig van ertelme tekerni)


//+------------------------------------------------------------------+
//| A HASZNALANDO fajl neve.                                          |
//|                                                                  |
//| ⚠ SABLON-CSAPDA: a Strategy Tester indulaskor RAHUZZA a           |
//| `tester.tpl`-t, es azzal FELULIRJA az inputokat azokra, amik a    |
//| sablon mentesekor voltak. A kezzel beallitott `_BT` utotag ott    |
//| tehat NEMAN elveszik — a mert eset: mindharom indikator a `_BT`   |
//| helyett az ELO fajlt olvasta, es ures maradt.                     |
//|                                                                  |
//| Ezert: ha nincs EXPLICIT utotag ES teszteloben vagyunk, ELOSZOR a |
//| `_BT` fajlt probaljuk (az a visszajatszas-export). Igy nem kell   |
//| sablont menteni ahhoz, hogy a teszt a helyes adatot lassa.        |
//|                                                                  |
//| (Ugyanez a fuggveny megvan a TradeForgeWPR/Bands-ben is. Az MQL4  |
//| include kulon mappaba (MQL4\Include) telepulne — egy hianyzo      |
//| include-tol EGYIK indikator sem fordulna le, ezert itt a rovid    |
//| duplikacio a kisebb kockazat.)                                    |
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
//| "r,g,b" -> color. Sajat parser: az MQL4 StringToColor viselkedese |
//| buildenkent elter, ez viszont mindig ugyanaz.                     |
//+------------------------------------------------------------------+
color RgbFromStr(string s)
{
   string p[];
   if(StringSplit(s, ',', p) < 3)
      return(clrGray);
   int r = (int)StringToInteger(p[0]);
   int g = (int)StringToInteger(p[1]);
   int b = (int)StringToInteger(p[2]);
   return((color)(r + (g << 8) + (b << 16)));
}


//+------------------------------------------------------------------+
//| Az elem neve mar szerepel-e a felrakottak kozt                    |
//+------------------------------------------------------------------+
void RememberName(string nm)
{
   for(int i = 0; i < g_nnames; i++)
      if(g_names[i] == nm) return;
   ArrayResize(g_names, g_nnames + 1);
   g_names[g_nnames] = nm;
   g_nnames++;
}


//+------------------------------------------------------------------+
//| A fajl beolvasasa a cache-be (rajzolas NELKUL)                    |
//+------------------------------------------------------------------+
bool LoadFile()
{
   int h = FileOpen(g_file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return(false);

   ArrayResize(g_ln, 0); ArrayResize(g_t, 0);
   ArrayResize(g_t2, 0); ArrayResize(g_done, 0);
   ArrayResize(g_isSig, 0); ArrayResize(g_sigDir, 0);
   g_n = 0;
   g_sigTotal = 0; g_sigBuy = 0; g_sigSell = 0; g_sigLast = 0;

   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringLen(ln) == 0) continue;

      if(StringFind(ln, "CLEAR") == 0)
      {
         ObjectsDeleteAll(0, g_objpref);
         continue;
      }
      // ALERT / IND / STATE / RECT: nem ennek az indikatornak szolnak.
      //  - STATE + RECT -> TradeForgeBands (al-ablak)
      //  - IND          -> TradeForgeWPR   (al-ablak, sajat parameterekkel)
      //  - ALERT        -> a teszteloben ertelmetlen (nincs valos ido)
      if(StringFind(ln, "ALERT;") == 0) continue;
      if(StringFind(ln, "IND;")   == 0) continue;
      if(StringFind(ln, "STATE;") == 0) continue;
      if(StringFind(ln, "RECT;")  == 0) continue;

      string f[];
      int nf = StringSplit(ln, ';', f);
      if(nf < 2) continue;

      string type = f[0];
      string name = f[1];
      if(StringFind(name, g_objpref) != 0)   // masik strategia
         continue;

      datetime t1 = 0, t2 = 0;
      if(type == "VLINE" && nf >= 5)      { t1 = (datetime)StringToInteger(f[2]); }
      else if(type == "TREND" && nf >= 8) { t1 = (datetime)StringToInteger(f[2]);
                                            t2 = (datetime)StringToInteger(f[4]); }
      else if(type == "ARROW" && nf >= 7) { t1 = (datetime)StringToInteger(f[2]); }
      else if(type == "TEXT"  && nf >= 7) { t1 = (datetime)StringToInteger(f[2]); }
      else if(type == "LABEL" && nf >= 8) { t1 = 0; }   // sarokhoz kotott: mindig lathato
      else continue;

      // Belepo-jelzes? A VLINE a jel fuggoleges vonala; a szinbol jon az irany.
      bool  isSig = (type == "VLINE");
      int   dir   = 0;
      if(isSig)
      {
         color c = RgbFromStr(f[3]);
         int r = (int)(c & 0xFF), g = (int)((c >> 8) & 0xFF);
         dir = (g > r) ? 1 : -1;
         g_sigTotal++;
         if(dir > 0) g_sigBuy++; else g_sigSell++;
         if(t1 > g_sigLast) g_sigLast = t1;
      }

      ArrayResize(g_ln, g_n + 1);   g_ln[g_n]   = ln;
      ArrayResize(g_t,  g_n + 1);   g_t[g_n]    = t1;
      ArrayResize(g_t2, g_n + 1);   g_t2[g_n]   = t2;
      ArrayResize(g_done, g_n + 1); g_done[g_n] = false;
      ArrayResize(g_isSig, g_n + 1);  g_isSig[g_n]  = isSig;
      ArrayResize(g_sigDir, g_n + 1); g_sigDir[g_n] = dir;
      g_n++;
   }
   FileClose(h);
   return(true);
}


//+------------------------------------------------------------------+
//| A LOOK-AHEAD KAPU: a `now`-ig felfedjuk a rekordokat.             |
//|                                                                  |
//| - t1 > now            -> meg NEM latszik (ez a lenyeg)            |
//| - szakasz (TREND):    -> a vegpontot `now`-ra vagjuk, es a kesobbi|
//|                          korokben UJRA rajzoljuk -> EGYUTT NO az  |
//|                          idovel, mint elesben.                    |
//+------------------------------------------------------------------+
void Reveal(datetime now)
{
   bool gate = InpReplayGate;
   for(int i = 0; i < g_n; i++)
   {
      if(g_done[i]) continue;
      if(gate && g_t[i] > now) continue;          // meg a jovoben van

      string f[];
      StringSplit(g_ln[i], ';', f);
      string type = f[0];
      string name = f[1];

      if(type == "VLINE")      UpsertVLine(name, f);
      else if(type == "TREND")
      {
         datetime tEnd = g_t2[i];
         bool growing = false;
         if(gate && tEnd > now) { tEnd = now; growing = true; }
         UpsertTrend(name, f, tEnd);
         if(growing) { RememberName(name); continue; }   // marad "elo", meg no
      }
      else if(type == "ARROW") UpsertArrow(name, f);
      else if(type == "TEXT")  UpsertText(name, f);
      else if(type == "LABEL") UpsertLabel(name, f);

      g_done[i] = true;
      RememberName(name);
   }
}


//+------------------------------------------------------------------+
//| VLINE;name;t1;r,g,b;width                                        |
//+------------------------------------------------------------------+
void UpsertVLine(string name, string &f[])
{
   datetime t1 = (datetime)StringToInteger(f[2]);
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_VLINE, 0, t1, 0);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
   }
   else ObjectMove(0, name, 0, t1, 0);
   ObjectSetInteger(0, name, OBJPROP_COLOR, RgbFromStr(f[3]));
   ObjectSetInteger(0, name, OBJPROP_WIDTH, (int)StringToInteger(f[4]));
}


//+------------------------------------------------------------------+
//| TREND;name;t1;p1;t2;p2;r,g,b;width[;style]                        |
//| A `tEnd` a KAPUZOTT vegpont (a hivo vagja `now`-ra).              |
//+------------------------------------------------------------------+
void UpsertTrend(string name, string &f[], datetime tEnd)
{
   datetime t1 = (datetime)StringToInteger(f[2]);
   double   p1 = StringToDouble(f[3]);
   double   p2 = StringToDouble(f[5]);
   int      st = (ArraySize(f) >= 9) ? (int)StringToInteger(f[8]) : 0;
   if(tEnd < t1) tEnd = t1;

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, tEnd, p2);
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, name, OBJPROP_RAY, false);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
   }
   else
   {
      ObjectMove(0, name, 0, t1,   p1);
      ObjectMove(0, name, 1, tEnd, p2);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR, RgbFromStr(f[6]));
   ObjectSetInteger(0, name, OBJPROP_WIDTH, (int)StringToInteger(f[7]));
   ObjectSetInteger(0, name, OBJPROP_STYLE, st);
}


//+------------------------------------------------------------------+
//| ARROW;name;t1;p1;code;r,g,b;width                                |
//+------------------------------------------------------------------+
void UpsertArrow(string name, string &f[])
{
   datetime t1   = (datetime)StringToInteger(f[2]);
   double   p1   = StringToDouble(f[3]);
   int      code = (int)StringToInteger(f[4]);
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_ARROW, 0, t1, p1);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else ObjectMove(0, name, 0, t1, p1);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, code);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, (code == 234) ? ANCHOR_BOTTOM : ANCHOR_TOP);
   ObjectSetInteger(0, name, OBJPROP_COLOR, RgbFromStr(f[5]));
   ObjectSetInteger(0, name, OBJPROP_WIDTH, (int)StringToInteger(f[6]));
}


//+------------------------------------------------------------------+
//| TEXT;name;t1;p1;r,g,b;fontsize;szoveg                            |
//+------------------------------------------------------------------+
void UpsertText(string name, string &f[])
{
   datetime t1 = (datetime)StringToInteger(f[2]);
   double   p1 = StringToDouble(f[3]);
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_TEXT, 0, t1, p1);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else ObjectMove(0, name, 0, t1, p1);
   ObjectSetString (0, name, OBJPROP_TEXT, f[6]);
   ObjectSetInteger(0, name, OBJPROP_COLOR, RgbFromStr(f[4]));
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, (int)StringToInteger(f[5]));
}


//+------------------------------------------------------------------+
//| LABEL;name;corner;x;y;r,g,b;fontsize;szoveg                       |
//+------------------------------------------------------------------+
void UpsertLabel(string name, string &f[])
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   ObjectSetInteger(0, name, OBJPROP_CORNER,    (int)StringToInteger(f[2]));
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, (int)StringToInteger(f[3]));
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, (int)StringToInteger(f[4]));
   ObjectSetString (0, name, OBJPROP_TEXT,      f[7]);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     RgbFromStr(f[5]));
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  (int)StringToInteger(f[6]));
}


//+------------------------------------------------------------------+
//| Allapotsor — a teszteloben ebbol latszik, hogy a kapu dolgozik.   |
//+------------------------------------------------------------------+
//| `row`: hanyadik sor (0,1,2) — a sortavolsag a betumeretbol jon, hogy nagyobb
//| fontnal se csusszanak egymasra.
void PutLabel(string name, int row, color c, string txt)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetString (0, name, OBJPROP_FONT, "Consolas");
   }
   int corner = InpStatusCorner;
   if(corner < 0 || corner > 3) corner = 0;
   int step = InpStatusFont + 6;
   // Also sarkoknal FELFELE noveljuk a tavolsagot, kulonben a sorok kilognanak.
   bool lower = (corner == 1 || corner == 3);
   ObjectSetInteger(0, name, OBJPROP_CORNER, corner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, InpStatusX);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE,
                    lower ? (InpStatusY + (2 - row) * step)
                          : (InpStatusY + row * step));
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpStatusFont);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetString (0, name, OBJPROP_TEXT, txt);
}


void Status(datetime now)
{
   if(!InpShowStatus) return;

   // Belepo-jelzesek: mennyi volt eddig, mennyi van MEG. Enelkul nem tudod, hogy
   // erdemes-e meg tekerni, vagy mar csak ures ora jon.
   int seen = 0, seenB = 0, seenS = 0;
   datetime next = 0;
   for(int i = 0; i < g_n; i++)
   {
      if(!g_isSig[i]) continue;
      if(g_done[i]) { seen++; if(g_sigDir[i] > 0) seenB++; else seenS++; }
      else if(next == 0 || g_t[i] < next) next = g_t[i];
   }
   int left = g_sigTotal - seen;

   // ⚠ SZINEK: a chart hattere VILAGOS, ezert sotet arnyalatok kellenek. A fehér
   // gyakorlatilag olvashatatlan volt rajta.
   PutLabel(STATUSNM, 0, (InpReplayGate ? clrDarkGreen : clrRed),
      StringFormat("TFViz %s | %s | kapu:%s | %s",
                   g_file, (g_isTester ? "TESZTELO" : "ELO"),
                   (InpReplayGate ? "BE" : "KI  ⚠LATSZIK A JOVO"),
                   TimeToString(now, TIME_DATE | TIME_MINUTES)));

   string s2 = StringFormat("BELEPO: %d / %d volt  (%d BUY, %d SELL)   |   HATRA: %d",
                            seen, g_sigTotal, seenB, seenS, left);
   if(g_sigLast > 0)
      s2 = s2 + "   |   utolso jel: " + TimeToString(g_sigLast, TIME_DATE | TIME_MINUTES);
   PutLabel(STATUSNM + "2", 1, (left > 0 ? InpStatusColor : clrSaddleBrown), s2);

   // Spoiler-sor: csak kifejezett keresre.
   if(InpShowNextTime && next > 0)
   {
      long mins = (long)(next - now) / 60;
      PutLabel(STATUSNM + "3", 2, clrDarkOrange,
         StringFormat("kovetkezo jel: %s  (%d ora %d perc mulva)  ⚠spoiler",
                      TimeToString(next, TIME_DATE | TIME_MINUTES),
                      (int)(mins / 60), (int)(mins % 60)));
   }
   else if(left == 0 && g_sigTotal > 0)
      PutLabel(STATUSNM + "3", 2, clrSaddleBrown, "Nincs tobb belepo ebben az ablakban.");
}


//+------------------------------------------------------------------+
int OnInit()
{
   g_isTester = IsTesting();
   g_file     = ResolveFile(InpFileSuffix);
   g_objpref  = (InpStrategy == "") ? PFX : (PFX + InpStrategy + "@");
   g_nnames   = 0;
   ArrayResize(g_names, 0);

   if(!LoadFile())
      Print("[TFViz] NEM talalom: ", g_file, "  (Common\\Files)");
   else
      Print("[TFViz] betoltve: ", g_file, "  rekordok=", g_n,
            "  kontextus=", (g_isTester ? "tesztelo" : "elo"),
            "  kapu=", (InpReplayGate ? "BE" : "KI"));

   // Elo charton a fajl VALTOZIK -> idozitett ujraolvasas. A teszteloben NEM
   // valtozik (fix export), es ott az OnTimer sem megbizhato -> csak OnCalculate.
   if(!g_isTester && InpTimerSeconds > 0)
      EventSetTimer(InpTimerSeconds);
   return(INIT_SUCCEEDED);
}


//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(!g_isTester) EventKillTimer();
   ObjectsDeleteAll(0, g_objpref);
   ObjectDelete(0, STATUSNM);
   ObjectDelete(0, STATUSNM + "2");
   ObjectDelete(0, STATUSNM + "3");
}


//+------------------------------------------------------------------+
//| Elo chart: a fajl valtozhat -> ujraolvasas, majd teljes felfedes. |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(LoadFile())
   {
      g_nnames = 0; ArrayResize(g_names, 0);
      datetime now = InpReplayGate ? TimeCurrent() : D'2038.01.01';
      Reveal(now);
      Status(TimeCurrent());
      ChartRedraw();
   }
}


//+------------------------------------------------------------------+
//| A tesztelo IDEJE itt halad. Minden uj gyertyanal (es a tesztelo   |
//| oraval) ujra donthetunk: mi lathato MAR.                          |
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
   // A chart JELEN ideje: a LEGUTOLSO bar. A teszteloben ez a szimulalt ido —
   // ehhez igazodik a felfedes.
   //
   // ⚠ NEM `time[rates_total-1]`: az OnCalculate-nek atadott tomb indexelesi
   // IRANYA MQL4-ben nem garantalt (a predefinialt Time[]-tol elteroen), es a
   // gyakorlatban SORONKENT (series) jott — vagyis a `rates_total-1` a LEGREGEBBI
   // gyertyat adta. A kapu emiatt a chart ELEJEN allt: a tesztelo mar 06-09-nel
   // jart, a felfedes viszont 06-05-nel — a kozbenso belepok NEM latszottak.
   // A predefinialt Time[0] MQL4-ben MINDIG a legfrissebb bar.
   datetime now = (rates_total > 0) ? Time[0] : TimeCurrent();
   if(!InpReplayGate)
      now = D'2038.01.01';

   if(now != g_lastReveal)
   {
      g_lastReveal = now;
      Reveal(now);
      Status(now);
   }
   return(rates_total);
}
//+------------------------------------------------------------------+
