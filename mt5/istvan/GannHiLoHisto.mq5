//+------------------------------------------------------------------+
//|                                              GannHiLoHisto.mq5    |
//|  István „GannHiLo-Histo2.ex4" (MT4) indikátorának MT5-ös mása.    |
//|  Feketedobozos visszafejtés (2026-10-07): 5001 GOLD H1 gyertyán   |
//|  100%-ban egyezik az eredetivel.                                  |
//|                                                                  |
//|  Felső = SMA(High, N) az ELŐZŐ N gyertyán (az aktuális nincs benne)|
//|  Alsó  = SMA(Low,  N) az ELŐZŐ N gyertyán                          |
//|  Close > Felső -> emelkedő (+1, kék)                              |
//|  Close < Alsó  -> csökkenő (-1, piros)                            |
//|  különben marad az előző állapot.                                 |
//|                                                                  |
//|  Pufferek (iCustom, az MT4-es sorrenddel azonos):                 |
//|    0 = emelkedő hisztogram (1/0), 1 = csökkenő (1/0), 2 = állapot  |
//+------------------------------------------------------------------+
#property version   "1.00"
#property indicator_separate_window
#property indicator_buffers 3
#property indicator_plots   2
#property indicator_minimum 0
#property indicator_maximum 1
#property indicator_type1   DRAW_HISTOGRAM
#property indicator_color1  clrDodgerBlue
#property indicator_width1  3
#property indicator_label1  "Gann up"
#property indicator_type2   DRAW_HISTOGRAM
#property indicator_color2  clrRed
#property indicator_width2  3
#property indicator_label2  "Gann down"

input int InpPeriod = 10;   // periódus (SMA a csúcsokon / mélypontokon)

double UpBuf[];
double DnBuf[];
double StateBuf[];

int OnInit()
{
   SetIndexBuffer(0, UpBuf, INDICATOR_DATA);
   SetIndexBuffer(1, DnBuf, INDICATOR_DATA);
   SetIndexBuffer(2, StateBuf, INDICATOR_CALCULATIONS);
   PlotIndexSetInteger(0, PLOT_DRAW_BEGIN, InpPeriod + 1);
   PlotIndexSetInteger(1, PLOT_DRAW_BEGIN, InpPeriod + 1);
   IndicatorSetInteger(INDICATOR_DIGITS, 0);
   IndicatorSetString(INDICATOR_SHORTNAME, "GannHiLoHisto(" + (string)InpPeriod + ")");
   return INIT_SUCCEEDED;
}

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
{
   if(rates_total <= InpPeriod + 1)
      return 0;
   // nem-sorozat indexelés: 0 = legrégebbi gyertya
   int start = (prev_calculated > 0) ? prev_calculated - 1 : InpPeriod;
   if(start < InpPeriod)
      start = InpPeriod;
   if(prev_calculated == 0)
      for(int k = 0; k < InpPeriod; k++) { UpBuf[k] = 0; DnBuf[k] = 0; StateBuf[k] = 0; }

   for(int i = start; i < rates_total; i++)
   {
      double sh = 0, sl = 0;
      for(int j = 1; j <= InpPeriod; j++) { sh += high[i - j]; sl += low[i - j]; }
      sh /= InpPeriod;
      sl /= InpPeriod;
      double st = StateBuf[i - 1];
      if(close[i] > sh)      st = 1;
      else if(close[i] < sl) st = -1;
      StateBuf[i] = st;
      UpBuf[i] = (st > 0) ? 1 : 0;
      DnBuf[i] = (st < 0) ? 1 : 0;
   }
   return rates_total;
}
