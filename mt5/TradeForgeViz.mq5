//+------------------------------------------------------------------+
//|                                              TradeForgeViz.mq5    |
//|  TradeForge chart-vizualizáció: felolvassa a Python által írt     |
//|  Common\Files\TFV_<Symbol>.csv fájlt és kirajzolja az objektumokat|
//|                                                                  |
//|  Elv: UPSERT (létrehoz VAGY módosít stabil név alapján) — SOHA    |
//|  nem töröl. Így egy meglévő objektum (pl. SMA-doboz) csak NŐ,     |
//|  amíg tart a feltétel; nincs villódzás és nincs duplikátum.      |
//|                                                                  |
//|  Telepítés: másold a fájlt az MQL5\Indicators mappába, fordítsd  |
//|  (F7), majd húzd a kívánt chartra. A fájlt a Python az MT5 közös  |
//|  (Common) mappájába írja, ezért FILE_COMMON-nal olvassuk.        |
//+------------------------------------------------------------------+
#property version   "2.62"        // TradeForge v2.62; idosik-kapu (TFONLY) 2026-08-17
#property indicator_chart_window
#property indicator_plots 0

input int    TimerSeconds = 1;       // Fájl-újraolvasás gyakorisága (mp)
input string FilePrefix   = "TFV_";  // Objektum-név és fájl prefix
input string InpStrategy  = "";      // Melyik STRATÉGIÁT mutassa (üres = MIND)
input int    AlertMemoryDays = 3;    // Ennyi nap után felejtjük a riasztás-jelölőket

string g_file;                    // TFV_<Symbol>.csv
string g_objpref;                 // szűrő-prefix: TFV_ (mind) VAGY TFV_<InpStrategy>@
string g_ind_sig  = "";           // az utoljára felrakott IND-halmaz aláírása
string g_ma_names[];              // MINDEN általunk felrakott MA rövidneve (leszedéshez)

// IDŐSÍK-KAPU (TFONLY;<stratégia>;<perc>)
//
// A viz-fájl egy SZIMBÓLUM teljes pillanatképe, és a szimbólum MINDEN nyitott
// chartja UGYANABBÓL olvas — a rajz tehát M1-en, M5-ön és H1-en is megjelent.
// Egy H1-en számolt Bollinger-szalag viszont M1-en FÉLREVEZETŐ: nem az látszik,
// amit a döntés használ, csak ugyanaz a görbe rossz felbontásban.
//
// A Python most megmondja, melyik stratégia rajza melyik chart-idősíkra való.
// Ahol a stratégia a VÉGREHAJTÁSI gyertyán dönt (wpr_sma), ott nem küld sort —
// az mindenhol látszik, ahogy eddig.
string g_tf_strat[];              // stratégia-nevek, amikre van idősík-kikötés
int    g_tf_min[];                // …és a hozzájuk tartozó perc
int    g_ntf = 0;
int    g_ntf_notes = 0;           // hány „…a H1 charton látszik" felirat van kint

// Már LEFUTTATOTT riasztások — GLOBÁLIS VÁLTOZÓBAN, nem a memóriában.
//
// A viz-fájl a kívánt állapot teljes PILLANATKÉPE, ezért az ALERT sor minden
// olvasáskor újra ott van — enélkül másodpercenként újra szólna.
//
// Eddig egy memóriabeli tömb őrizte az id-ket. Idősík-váltáskor viszont az MT5
// ELPUSZTÍTJA és ÚJRALÉTREHOZZA az indikátort (OnDeinit → OnInit), a tömb
// kiürül, az OnInit végén pedig azonnal jön a RefreshFromFile() — és a fájlban
// még ott az ALERT sor. Ezért szólt újra MINDEN idősík-váltáskor.
//
// A terminál GLOBÁLIS VÁLTOZÓI túlélik az idősík-váltást, a template-újratöltést
// és a terminál újraindítását is. Ráadás: több chart OSZTOZIK rajtuk, tehát egy
// jelre most pontosan EGYSZER szól akkor is, ha ugyanarra a szimbólumra több
// chart van nyitva — ez eddig chartonként külön riasztást adott.
#define ALERT_GV_PREFIX "TFV_A_"

//+------------------------------------------------------------------+
//| Riasztás-jelölő neve az `aid`-ből.                               |
//|                                                                  |
//| A globális változó neve max 63 karakter, az `aid` viszont hosszabb|
//| is lehet (szimbólum + stratégia + irány + bar-idő), ezért HASH-t  |
//| használunk (FNV-1a, 32 bit). Ütközés esetén EGY riasztás maradna  |
//| el; ~100 élő jelölőnél ennek esélye ~1e-6, tehát elhanyagolható.  |
//+------------------------------------------------------------------+
string AlertMarkName(string aid)
{
   uint h = 2166136261;                       // FNV-1a offset basis
   int n = StringLen(aid);
   for(int i = 0; i < n; i++)
   {
      h ^= (uint)StringGetCharacter(aid, i);
      h *= 16777619;                          // FNV prime
   }
   return(ALERT_GV_PREFIX + IntegerToString((long)h));
}

//+------------------------------------------------------------------+
//| Szóltunk-e már erre a jelre? (A jelölő PUSZTA LÉTE a válasz.)    |
//+------------------------------------------------------------------+
bool AlertWasSeen(string aid)
{
   return(GlobalVariableCheck(AlertMarkName(aid)));
}

//+------------------------------------------------------------------+
//| Jelölő elhelyezése. Az ÉRTÉK a riasztás ideje — ebből tudja a     |
//| takarítás, mit lehet elfelejteni.                                |
//+------------------------------------------------------------------+
void AlertMarkSeen(string aid)
{
   GlobalVariableSet(AlertMarkName(aid), (double)TimeCurrent());
}

//+------------------------------------------------------------------+
//| Régi jelölők takarítása — különben a globális változók korlátlanul|
//| gyűlnének. Az OnInit hívja: idősík-váltásonként egyszer fut le, és|
//| csak néhány tucat bejegyzést jár be, tehát olcsó.                |
//|                                                                  |
//| CSAK a SAJÁT prefixűekhez nyúlunk — más eszközök globális         |
//| változóit nem bántjuk.                                           |
//+------------------------------------------------------------------+
void PurgeOldAlertMarks()
{
   if(AlertMemoryDays <= 0)
      return;
   datetime cutoff = TimeCurrent() - (datetime)((long)AlertMemoryDays * 86400);
   // CSÖKKENŐ sorrendben: a törlés eltolja az indexeket, növekvő ciklussal
   // minden törlés után kimaradna egy bejegyzés.
   for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
   {
      string nm = GlobalVariableName(i);
      if(StringFind(nm, ALERT_GV_PREFIX) != 0)
         continue;
      if((datetime)GlobalVariableGet(nm) < cutoff)
         GlobalVariableDel(nm);
   }
}

//+------------------------------------------------------------------+
//| A SAJÁT al-ablak-indikátorok (TFWPR, TFBANDS) leszedése MINDEN    |
//| al-ablakból. CSÖKKENŐ ablak- és index-sorrend → a törlés miatti   |
//| index-eltolódás nem hagy ki egyet (ez okozta az időkeret-váltós   |
//| halmozódást).                                                     |
//+------------------------------------------------------------------+
void RemoveOurWPRs()
{
   int wtot = (int)ChartGetInteger(0, CHART_WINDOWS_TOTAL);
   for(int w = wtot - 1; w >= 1; w--)
      for(int idx = ChartIndicatorsTotal(0, w) - 1; idx >= 0; idx--)
      {
         string nm = ChartIndicatorName(0, w, idx);
         if(StringFind(nm, "TFWPR") == 0 || StringFind(nm, "TFBANDS") == 0)
            ChartIndicatorDelete(0, w, nm);
      }
}

//+------------------------------------------------------------------+
//| A SAJÁT (általunk felrakott) MA-k leszedése a FŐ ablakból, név    |
//| szerint. Több MA is lehet (tf_align: idősíkonként egy) — a        |
//| g_ma_names MINDET számon tartja; azonos rövidnév (pl. két SMA100  |
//| más idősíkon) esetén az ismételt törlés egyenként szedi le.       |
//+------------------------------------------------------------------+
void RemoveOurMAs()
{
   for(int i = ArraySize(g_ma_names) - 1; i >= 0; i--)
      if(g_ma_names[i] != "")
         ChartIndicatorDelete(0, 0, g_ma_names[i]);
   ArrayResize(g_ma_names, 0);
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_file = FilePrefix + _Symbol + ".csv";
   // Szűrő-prefix: ha van InpStrategy, csak a TFV_<strat>@ nevű objektumok a mieink
   // (a Python minden objektumot a stratégia nevével jelöl). Üres → minden TFV_.
   g_objpref = (InpStrategy == "") ? FilePrefix : (FilePrefix + InpStrategy + "@");
   g_ind_sig = "";
   ArrayResize(g_ma_names, 0);
   RemoveOurWPRs();   // előző futás maradék WPR-jei (halmozódás ellen)
   PurgeOldAlertMarks();   // régi riasztás-jelölők (a globális változók ne gyűljenek)
   EventSetTimer(TimerSeconds);
   RefreshFromFile();
   WriteHeartbeat();   // azonnal, hogy ne kelljen a timerre varni
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   // ⚠ Az eletjel-fajlt TOROLJUK: chart bezarasakor a felulet AZONNAL tudja,
   // hogy ide mar nem erkezik jelzes. Nelkule a fajl kora dontene, tehat
   // percekig "elonek" latszana egy bezart chart.
   {
      string fn = "TFV_ALIVE_" + _Symbol + "_" + IntegerToString((int)Period())
                + (InpStrategy == "" ? "" : "_" + InpStrategy) + ".txt";
      FileDelete(fn, FILE_COMMON);
   }
   // Az AUTO-felrakott indikátorokat leszedjük (a TradeForgeViz-hez tartoznak).
   // A rajz-objektumok (TFV_) SZÁNDÉKOSAN maradnak.
   RemoveOurWPRs();
   RemoveOurMAs();
}

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
{
   return(rates_total);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   RefreshFromFile();
   WriteHeartbeat();
}

//+------------------------------------------------------------------+
//| ÉLETJEL: "ez a chart NYITVA van, és fut rajta a Viz"             |
//|                                                                  |
//| MIERT KELL. A dashboardon be lehet allitani egy part "csak        |
//| jelzes" modba — de ha az MT5-on NINCS nyitva hozza chart a        |
//| TradeForgeViz-cel, a jelzes SOSEM jelenik meg sehol. A program    |
//| eddig ezt nem tudhatta: a Python fajlba IR, de nem latja, hogy    |
//| olvassa-e valaki. Nema hiba — a felhasznalo varja a jelzest, es   |
//| csak annyi tortenik, hogy nincs.                                  |
//|                                                                  |
//| PELDANYONKENT KULON FAJL (szimbolum + idosik + strategia): ha     |
//| mindenki UGYANABBA a fajlba irna, egymast tulnak felul, es a      |
//| legutolso iro elnyomna a tobbit. Kulon fajlnal a Python egyszeruen|
//| kilistazza a mappat, es a fajl KORABOL latja, hogy el-e meg.      |
//+------------------------------------------------------------------+
void WriteHeartbeat()
{
   string fn = "TFV_ALIVE_" + _Symbol + "_" + IntegerToString((int)Period())
             + (InpStrategy == "" ? "" : "_" + InpStrategy) + ".txt";
   int h = FileOpen(fn, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;
   // Egyetlen sor, pontosvesszos — ugyanaz a formatum, mint a viz-fajle.
   // Az IDO a szerver ideje; a Python a FAJL koraval dolgozik (az a helyi ora),
   // de a mezot kiirjuk, hogy elteres eseten lassek.
   FileWrite(h, "ALIVE;" + _Symbol + ";" + IntegerToString((int)Period()) + ";"
              + InpStrategy + ";" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS)
              + ";" + IntegerToString((int)TimeGMT()));
   FileClose(h);
}

//+------------------------------------------------------------------+
//| IDŐSÍK-KAPU: TFONLY;<stratégia>;<perc>                           |
//+------------------------------------------------------------------+
void TfReset()
{
   ArrayResize(g_tf_strat, 0);
   ArrayResize(g_tf_min, 0);
   g_ntf = 0;
}

void TfAdd(string ln)
{
   string f[];
   if(StringSplit(ln, ';', f) < 3)
      return;
   ArrayResize(g_tf_strat, g_ntf + 1);
   ArrayResize(g_tf_min,   g_ntf + 1);
   g_tf_strat[g_ntf] = f[1];
   g_tf_min[g_ntf]   = (int)StringToInteger(f[2]);
   g_ntf++;
}

// Objektum-névből a stratégia: TFV_<stratégia>@<név>. Ha nincs „@", a sor egy
// régi (nem címkézett) formátumú név → nincs mihez kötni, tehát nem kapuzunk.
string StratOfName(string name)
{
   int at = StringFind(name, "@");
   if(at < 0 || StringFind(name, FilePrefix) != 0)
      return "";
   int p = StringLen(FilePrefix);
   return StringSubstr(name, p, at - p);
}

// Igaz, ha EZ a chart nem a stratégia döntési idősíkján áll.
bool TfBlocked(string strat)
{
   if(strat == "")
      return false;
   // ⚠ MT5-ben a `Period()` ENUM-ot ad (PERIOD_H1 == 16385), NEM percet — az
   // összehasonlítás azzal MINDEN idősíkon igazat adna, és a rajz sehol sem
   // jelenne meg. A percet a `PeriodSeconds()` mondja meg.
   int cur = (int)(PeriodSeconds() / 60);
   for(int i = 0; i < g_ntf; i++)
      if(g_tf_strat[i] == strat)
         return (g_tf_min[i] > 0 && cur != g_tf_min[i]);
   return false;   // nincs kikötés → mindenhol látszik (visszafelé kompatibilis)
}

string TfName(int minutes)
{
   if(minutes % 1440 == 0) return "D" + IntegerToString(minutes / 1440);
   if(minutes % 60   == 0) return "H" + IntegerToString(minutes / 60);
   return "M" + IntegerToString(minutes);
}

// ⚠ A KAPU NEM LEHET NÉMA. Ha egy stratégia rajzát elrejtettük, egy apró
// felirat megmondja, HOL nézhető meg — enélkül a felhasználó azt látná, hogy a
// stratégia „nem rajzol semmit", és hibát keresne ott, ahol nincs.
string TfNote(string strat, int minutes)
{
   string nm = FilePrefix + strat + "@zz_tfnote";
   if(StringFind(nm, g_objpref) != 0)
      return "";                       // ez a chart nem ezt a stratégiát mutatja
   if(ObjectFind(0, nm) < 0)
      ObjectCreate(0, nm, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, nm, OBJPROP_CORNER, CORNER_LEFT_LOWER);
   ObjectSetInteger(0, nm, OBJPROP_XDISTANCE, 6);
   ObjectSetInteger(0, nm, OBJPROP_YDISTANCE, 18 + 14 * g_ntf_notes);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clrGray);
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, nm, OBJPROP_TEXT,
                   strat + ": a rajza a " + TfName(minutes) + " charton látszik");
   g_ntf_notes++;
   return nm;
}

//+------------------------------------------------------------------+
//| Fájl felolvasása és minden sor alkalmazása (upsert)              |
//+------------------------------------------------------------------+
void RefreshFromFile()
{
   int h = FileOpen(g_file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;   // még nincs fájl — nem hiba

   // ⚠ KÉT MENET. Az idősík-kikötést (TFONLY) a stratégia MINDEN objektuma előtt
   // ismernünk kell — egy menetben az a sorrendtől függene, ami a fájlformátum
   // néma függősége lenne. Ezért előbb BEOLVASSUK a fájlt (pár száz sor), és
   // csak utána rajzolunk.
   string raw[];
   int nraw = 0;
   while(!FileIsEnding(h))
   {
      string ln0 = FileReadString(h);
      if(StringLen(ln0) == 0)
         continue;
      ArrayResize(raw, nraw + 1, 256);   // foglalással: soronkénti újrafoglalás nélkül
      raw[nraw] = ln0;
      nraw++;
   }
   FileClose(h);

   TfReset();
   for(int r = 0; r < nraw; r++)
      if(StringFind(raw[r], "TFONLY;") == 0)
         TfAdd(raw[r]);

   string inds[];
   int nind = 0;
   string seen[];        // a MOSTANI fájlban szereplő objektum-nevek (mark)
   int nseen = 0;
   bool cleared = false;
   g_ntf_notes = 0;
   string noted[];       // melyik elrejtett stratégiáról írtunk már feliratot
   int nnoted = 0;
   for(int r = 0; r < nraw; r++)
   {
      string ln = raw[r];
      if(StringFind(ln, "TFONLY;") == 0)
         continue;                       // már feldolgozva
      if(StringFind(ln, "CLEAR") == 0)   // V-off: a saját objektumok törlése
      {
         ObjectsDeleteAll(0, g_objpref);
         cleared = true;
         continue;
      }
      if(StringFind(ln, "ALERT;") == 0)  // „csak jelzés" mód riasztása
      {
         // ⚠ A RIASZTÁS NEM RAJZ: azt akkor is meg kell kapni, ha ez a chart
         // épp más idősíkon áll. Egy elrejtett rajz mellett elnémított jelzés
         // csendben elvinne egy belépőt.
         HandleAlert(ln);
         continue;
      }
      if(StringFind(ln, "IND;") == 0)   // indikátor-leírás — külön kezeljük
      {
         string fi[];
         if(StringSplit(ln, ';', fi) >= 2 && TfBlocked(fi[1]))
            continue;
         ArrayResize(inds, nind + 1);
         inds[nind] = ln;
         nind++;
         continue;
      }
      // IDŐSÍK-KAPU: a más idősíkra szánt rajzot kihagyjuk — de EGYSZER
      // kiírjuk, hol nézhető meg (a kapu nem lehet néma).
      string fs[];
      if(StringSplit(ln, ';', fs) >= 2)
      {
         string st = StratOfName(fs[1]);
         if(TfBlocked(st))
         {
            bool done = false;
            for(int k = 0; k < nnoted; k++)
               if(noted[k] == st) { done = true; break; }
            if(!done)
            {
               ArrayResize(noted, nnoted + 1);
               noted[nnoted] = st;
               nnoted++;
               int mm = 0;
               for(int q = 0; q < g_ntf; q++)
                  if(g_tf_strat[q] == st) { mm = g_tf_min[q]; break; }
               string note = TfNote(st, mm);
               if(note != "")
               {
                  ArrayResize(seen, nseen + 1);
                  seen[nseen] = note;
                  nseen++;
               }
            }
            continue;
         }
      }
      string nm = ApplyLine(ln);
      if(nm != "")
      {
         ArrayResize(seen, nseen + 1);
         seen[nseen] = nm;
         nseen++;
      }
   }

   // MARK-AND-SWEEP: a fájl a kívánt állapot TELJES pillanatképe → a SAJÁT (TFV_)
   // objektumokból leszedjük azokat, amik NEM voltak a mostani fájlban (árvák: pl.
   // már érvénytelen belépő-vonal, elmozdult ablakhoz tartozó régi jelölés). Az
   // upsert így NŐ/mozgat, a söprés pedig eltakarít — nincs halmozódás.
   // A CLEAR ág külön van (már mindent törölt), ott nem söprünk.
   if(!cleared)
      SweepOrphans(g_objpref, seen, nseen);

   // Indikátorok: az IND-halmaz ALÁÍRÁSA alapján. Ha VÁLTOZOTT (pl. a TF-együttállás
   // idősíkjai/SMA-ja átállt a dashboardon), a SAJÁT indikátorainkat leszedjük és
   // frissen felrakjuk — így a config-váltás azonnal látszik (nem csak restart után).
   // Változatlan halmaznál nem nyúlunk hozzá (nincs villódzás, nincs duplikátum).
   if(nind > 0)
   {
      string sig = "";
      for(int i = 0; i < nind; i++)
         sig += inds[i] + "|";
      if(sig != g_ind_sig)
      {
         RemoveOurMAs();
         RemoveOurWPRs();
         SetupIndicators(inds, nind);
         g_ind_sig = sig;
      }
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
//| ALERT;<stratégia>;<id>;<szöveg>                                  |
//| A „csak jelzés" módú stratégia riasztása: a Python NEM köt, csak |
//| szól, hogy MOST lépett volna be. Az <id> a jelet azonosítja      |
//| (szimbólum|stratégia|irány|gyertyaidő) — ugyanarra az id-ra      |
//| CSAK EGYSZER riasztunk, különben a pillanatkép-modell miatt      |
//| másodpercenként újra szólna.                                     |
//+------------------------------------------------------------------+
void HandleAlert(string ln)
{
   string f[];
   int n = StringSplit(ln, ';', f);
   if(n < 4)
      return;
   // Több-stratégia szűrő — ugyanaz az elv, mint az IND soroknál: ha ez a chart
   // egy KONKRÉT stratégiát mutat, a másikét ne riasszuk (különben két chart
   // kétszer szólna ugyanarra a jelre).
   if(InpStrategy != "" && f[1] != InpStrategy)
      return;

   string aid = f[2];
   if(AlertWasSeen(aid))
      return;                          // erre a jelre már szóltunk

   // ELŐBB jelölünk, AZUTÁN riasztunk. Fordítva egy Alert() alatti újrabelépés
   // (a riasztás-ablak eseményt pumpál) duplán szólalhatna meg.
   AlertMarkSeen(aid);
   Alert(f[3]);
}

//+------------------------------------------------------------------+
//| Egy sor feldolgozása: TYPE;NAME;...                              |
//| Visszaad: a felrakott objektum neve (a söpréshez), vagy "" ha a  |
//| sor nem rajz-objektum (ismeretlen/hibás típus).                 |
//+------------------------------------------------------------------+
string ApplyLine(string ln)
{
   string f[];
   int n = StringSplit(ln, ';', f);
   if(n < 2)
      return "";

   string type = f[0];
   string name = f[1];

   // Több-stratégia szűrő: csak a MI stratégiánk (g_objpref prefixű) objektumait
   // rajzoljuk. A Python minden nevet TFV_<strat>@… alakúra jelöl; InpStrategy
   // üresnél g_objpref="TFV_" → minden stratégia látszik.
   if(StringFind(name, g_objpref) != 0)
      return "";

   // RECT (SMA-szalag + M15 doboz) → a TradeForgeBands al-ablak rajzolja, itt kihagyjuk.
   if(type == "VLINE" && n >= 5) { UpsertVLine(name, f); return name; }
   else if(type == "TREND" && n >= 8) { UpsertTrend(name, f); return name; }
   else if(type == "ARROW" && n >= 7) { UpsertArrow(name, f); return name; }
   else if(type == "TEXT"  && n >= 7) { UpsertText(name, f); return name; }
   else if(type == "LABEL" && n >= 8) { UpsertLabel(name, f); return name; }
   return "";
}

//+------------------------------------------------------------------+
//| Árva-takarítás: a `prefix`-szel kezdődő objektumok közül azokat, |
//| amik NINCSENEK a `seen` (mostani fájl) listában, leszedi. Minden |
//| al-ablakon átmegy (a VLINE a 0-s ablakhoz van horgonyozva); a    |
//| TradeForgeBands TFB_ objektumaihoz nem nyúl (más prefix).        |
//+------------------------------------------------------------------+
void SweepOrphans(string prefix, string &seen[], int nseen)
{
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
   {
      string nm = ObjectName(0, i, -1, -1);
      if(StringFind(nm, prefix) != 0)     // nem a miénk
         continue;
      if(!InArray(nm, seen, nseen))
         ObjectDelete(0, nm);
   }
}

//+------------------------------------------------------------------+
bool InArray(string s, string &arr[], int cnt)
{
   for(int i = 0; i < cnt; i++)
      if(arr[i] == s)
         return true;
   return false;
}

//+------------------------------------------------------------------+
//| VLINE;name;t1;r,g,b;width                                        |
//+------------------------------------------------------------------+
void UpsertVLine(string name, string &f[])
{
   datetime t1 = (datetime)StringToInteger(f[2]);
   color    c  = StringToColor(f[3]);
   int      w  = (int)StringToInteger(f[4]);

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_VLINE, 0, t1, 0);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else
   {
      ObjectMove(0, name, 0, t1, 0);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, w);
}

//+------------------------------------------------------------------+
//| TREND;name;t1;p1;t2;p2;r,g,b;width  (sugár nélkül)              |
//+------------------------------------------------------------------+
void UpsertTrend(string name, string &f[])
{
   datetime t1 = (datetime)StringToInteger(f[2]);
   double   p1 = StringToDouble(f[3]);
   datetime t2 = (datetime)StringToInteger(f[4]);
   double   p2 = StringToDouble(f[5]);
   color    c  = StringToColor(f[6]);
   int      w  = (int)StringToInteger(f[7]);
   int      st = (ArraySize(f) >= 9) ? (int)StringToInteger(f[8]) : 0;   // vonalstílus (opcionális)

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else
   {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, w);
   ObjectSetInteger(0, name, OBJPROP_STYLE, st);
}

//+------------------------------------------------------------------+
//| ARROW;name;t1;p1;code;r,g,b;width  (valós kötés nyíl-jelölése)   |
//| code: Wingdings nyíl-kód (233 fel = BUY, 234 le = SELL). A nyíl a |
//| gyertyához horgonyozva: BUY alul (ANCHOR_TOP), SELL felül.       |
//+------------------------------------------------------------------+
void UpsertArrow(string name, string &f[])
{
   datetime t1   = (datetime)StringToInteger(f[2]);
   double   p1   = StringToDouble(f[3]);
   int      code = (int)StringToInteger(f[4]);
   color    c    = StringToColor(f[5]);
   int      w    = (int)StringToInteger(f[6]);

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_ARROW, 0, t1, p1);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else
   {
      ObjectMove(0, name, 0, t1, p1);
   }
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, code);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, (code == 234) ? ANCHOR_BOTTOM : ANCHOR_TOP);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, w);
}

//+------------------------------------------------------------------+
//| TEXT;name;t1;p1;r,g,b;fontsize;szöveg                            |
//+------------------------------------------------------------------+
void UpsertText(string name, string &f[])
{
   datetime t1 = (datetime)StringToInteger(f[2]);
   double   p1 = StringToDouble(f[3]);
   color    c  = StringToColor(f[4]);
   int      fs = (int)StringToInteger(f[5]);
   string   txt = f[6];

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_TEXT, 0, t1, p1);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else
   {
      ObjectMove(0, name, 0, t1, p1);
   }
   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fs);
}

//+------------------------------------------------------------------+
//| LABEL;name;corner;x;y;r,g,b;fontsize;szöveg  (chart-sarokhoz)    |
//+------------------------------------------------------------------+
void UpsertLabel(string name, string &f[])
{
   int    corner = (int)StringToInteger(f[2]);
   int    x      = (int)StringToInteger(f[3]);
   int    y      = (int)StringToInteger(f[4]);
   color  c      = StringToColor(f[5]);
   int    fs     = (int)StringToInteger(f[6]);
   string txt    = f[7];

   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   ObjectSetInteger(0, name, OBJPROP_CORNER, corner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fs);
}

//+------------------------------------------------------------------+
//| A stratégia által HASZNÁLT indikátorok felrakása a chartra       |
//| IND;<MA|WPR>;<TF>;<period>;[szint1;szint2;…]                     |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TfFromStr(string s)
{
   if(s == "M1")  return PERIOD_M1;
   if(s == "M5")  return PERIOD_M5;
   if(s == "M15") return PERIOD_M15;
   if(s == "M30") return PERIOD_M30;
   if(s == "H1")  return PERIOD_H1;
   if(s == "H4")  return PERIOD_H4;
   return PERIOD_CURRENT;
}

void SetupIndicators(string &inds[], int cnt)
{
   // Szalag/doboz AL-ABLAK (TradeForgeBands) — a TradeForgeViz vezérli, hogy
   // EGY indikátor rakjon fel mindent. Átadjuk a szűrő-stratégiát is (input-
   // sorrend: TimerSeconds, FilePrefix, InpStrategy), hogy a sávok UGYANARRA a
   // stratégiára szűrjenek, mint a Viz. FELTÉTEL: a TradeForgeBands.ex5 megvan.
   int bh = iCustom(_Symbol, PERIOD_CURRENT, "TradeForgeBands",
                    TimerSeconds, FilePrefix, InpStrategy);
   if(bh != INVALID_HANDLE)
      ChartIndicatorAdd(0, (int)ChartGetInteger(0, CHART_WINDOWS_TOTAL), bh);

   for(int i = 0; i < cnt; i++)
   {
      string f[];
      int n = StringSplit(inds[i], ';', f);
      if(n < 5)                              // IND;<strat>;kind;tf;period;...
         continue;
      // Több-stratégia szűrő: csak a MI stratégiánk indikátorai (f[1] = stratégia).
      if(InpStrategy != "" && f[1] != InpStrategy)
         continue;
      string          kind   = f[2];
      ENUM_TIMEFRAMES tf     = TfFromStr(f[3]);
      int             period = (int)StringToInteger(f[4]);

      // f[5] = vonalszín ("r,g,b" vagy "-" = alapértelmezett); WPR-nél f[6..] szintek.
      if(kind == "MA")
      {
         int hnd = iMA(_Symbol, tf, period, 0, MODE_SMA, PRICE_CLOSE);
         if(hnd == INVALID_HANDLE)
            continue;
         if(ChartIndicatorAdd(0, 0, hnd))   // 0 = fő (ár) ablak
         {
            // MINDEN felrakott MA nevét eltesszük (több is lehet: tf_align idősíkonként)
            string mn = ChartIndicatorName(0, 0, ChartIndicatorsTotal(0, 0) - 1);
            int k = ArraySize(g_ma_names);
            ArrayResize(g_ma_names, k + 1);
            g_ma_names[k] = mn;
         }
      }
      else if(kind == "WPR")
      {
         // Saját WPR (TradeForgeWPR): állítható szín + szintek. A matek a
         // stratégiáé. FELTÉTEL: a TradeForgeWPR.ex5 le van fordítva.
         color  clr = (n > 5 && f[5] != "-") ? StringToColor(f[5]) : clrBlack;
         double l1  = (n > 6) ? StringToDouble(f[6]) : -20.0;
         double l2  = (n > 7) ? StringToDouble(f[7]) : -50.0;
         double l3  = (n > 8) ? StringToDouble(f[8]) : -80.0;
         double l4  = (n > 9) ? StringToDouble(f[9]) : 0.0;   // opcionális 4. szint (M15: 2 trigger)
         int hnd = iCustom(_Symbol, tf, "TradeForgeWPR", period, clr, l1, l2, l3, l4);
         if(hnd == INVALID_HANDLE)
            continue;
         int win = (int)ChartGetInteger(0, CHART_WINDOWS_TOTAL);   // új al-ablak
         ChartIndicatorAdd(0, win, hnd);   // a leszedést a RemoveOurWPRs intézi (név szerint)
      }
   }
}
//+------------------------------------------------------------------+
