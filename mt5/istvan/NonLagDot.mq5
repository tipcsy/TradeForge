//+------------------------------------------------------------------+
//|                                                  NonLagDot.mq5    |
//|  István „NonLagDot.ex4" (MT4) indikátorának MT5-ös mása — a        |
//|  NonLagMA (igorad) pöttyös változata. Feketedobozos visszafejtés   |
//|  (2026-10-07): 5001 GOLD H1 gyertyán a vonal 5e-7 pontosan, a szín |
//|  100%-ban egyezik az eredetivel (Length=40, Cycle=4, PctFilter=1). |
//|                                                                  |
//|  1. Nyers vonal: az utolsó Length*Cycle+Length-2 záróár súlyozott  |
//|     átlaga; súly(t) = cos(pi*t) * (t<=0.5 ? 1 : 1/(3*pi*t+1)),     |
//|     t = j/(Phase-1) az első Phase lépésben (Phase = Length-1),     |
//|     utána lépésenként +(2*Cycle-1)/(Cycle*Length-1).               |
//|  2. Szűrő: Del = |nyers - előző vonal|; AvgDel = Del átlaga Length |
//|     gyertyán; Szórás = sqrt(átlag((Del-AvgDel)^2), Length gyertya);|
//|     Filter = PctFilter*Szórás. Ha Del < Filter, a vonal áll.       |
//|  3. Szín: ha a vonal Filter-nél többet lépett felfelé -> +1 (kék),  |
//|     lefelé -> -1 (piros); különben marad.                          |
//|                                                                  |
//|  Pufferek (iCustom, az MT4-es sorrenddel azonos):                 |
//|    0 = vonal, 1 = emelkedő pötty, 2 = csökkenő pötty, 3 = állapot, |
//|    4 = Del, 5 = AvgDel                                            |
//+------------------------------------------------------------------+
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 6
#property indicator_plots   3
#property indicator_type1   DRAW_NONE
#property indicator_label1  "NonLagMA"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrDodgerBlue
#property indicator_width2  2
#property indicator_label2  "NonLag up"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrRed
#property indicator_width3  2
#property indicator_label3  "NonLag down"

input int    InpLength    = 40;    // Length
input int    InpCycle     = 4;     // Cycle
input double InpPctFilter = 1.0;   // PctFilter (0 = nincs szűrő)

double MaBuf[], UpBuf[], DnBuf[], TrendBuf[], DelBuf[], AvgBuf[];
double W[];
double WSum;
int    NW;

int OnInit()
{
   if(InpLength < 3 || InpCycle < 1)
      return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, MaBuf, INDICATOR_DATA);
   SetIndexBuffer(1, UpBuf, INDICATOR_DATA);
   SetIndexBuffer(2, DnBuf, INDICATOR_DATA);
   SetIndexBuffer(3, TrendBuf, INDICATOR_CALCULATIONS);
   SetIndexBuffer(4, DelBuf, INDICATOR_CALCULATIONS);
   SetIndexBuffer(5, AvgBuf, INDICATOR_CALCULATIONS);
   PlotIndexSetInteger(1, PLOT_ARROW, 159);
   PlotIndexSetInteger(2, PLOT_ARROW, 159);
   for(int p = 0; p < 3; p++)
      PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);

   int phase = InpLength - 1;
   NW = InpLength * InpCycle + phase - 1;
   ArrayResize(W, NW);
   WSum = 0;
   double step2 = (2.0 * InpCycle - 1.0) / (InpCycle * InpLength - 1.0);
   for(int j = 0; j < NW; j++)
   {
      double t = (j <= phase - 1) ? (double)j / (phase - 1) : 1.0 + (j - (phase - 1)) * step2;
      double g = (t > 0.5) ? 1.0 / (3.0 * M_PI * t + 1.0) : 1.0;
      W[j] = g * MathCos(M_PI * t);
      WSum += W[j];
   }
   PlotIndexSetInteger(0, PLOT_DRAW_BEGIN, NW);
   PlotIndexSetInteger(1, PLOT_DRAW_BEGIN, NW);
   PlotIndexSetInteger(2, PLOT_DRAW_BEGIN, NW);
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   IndicatorSetString(INDICATOR_SHORTNAME, "NonLagDot(" + (string)InpLength + ")");
   return INIT_SUCCEEDED;
}

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
{
   if(rates_total <= NW + 1)
      return 0;
   int first = NW - 1;                     // az első számolható gyertya
   int start = (prev_calculated > 0) ? prev_calculated - 1 : first;
   if(prev_calculated == 0)
      for(int k = 0; k < rates_total && k <= first; k++)
      {
         MaBuf[k] = EMPTY_VALUE; UpBuf[k] = EMPTY_VALUE; DnBuf[k] = EMPTY_VALUE;
         TrendBuf[k] = 0; DelBuf[k] = 0; AvgBuf[k] = 0;
      }

   for(int i = start; i < rates_total; i++)
   {
      double sum = 0;
      for(int j = 0; j < NW; j++)
         sum += W[j] * close[i - j];
      double raw = sum / WSum;

      if(i == first)
      {
         MaBuf[i] = raw; TrendBuf[i] = 0; DelBuf[i] = 0; AvgBuf[i] = 0;
         UpBuf[i] = EMPTY_VALUE; DnBuf[i] = EMPTY_VALUE;
         continue;
      }
      double prev = MaBuf[i - 1];
      double del = MathAbs(raw - prev);
      DelBuf[i] = del;

      // átlag és szórás az utolsó Length gyertyán (a bemelegedéskor kevesebből)
      int lo = MathMax(first + 1, i - InpLength + 1);
      int cnt = i - lo + 1;
      double s = 0;
      for(int k = lo; k <= i; k++) s += DelBuf[k];
      AvgBuf[i] = s / cnt;
      double filter = 0;
      if(InpPctFilter > 0 && i > first + 1)
      {
         double sp = 0;
         for(int k = lo; k <= i; k++) sp += MathPow(DelBuf[k] - AvgBuf[k], 2);
         filter = InpPctFilter * MathSqrt(sp / cnt);
      }
      double ma = (del < filter) ? prev : raw;
      MaBuf[i] = ma;

      double tr = TrendBuf[i - 1];
      if(ma - prev > filter) tr = 1;
      if(prev - ma > filter) tr = -1;
      TrendBuf[i] = tr;
      UpBuf[i] = (tr > 0) ? ma : EMPTY_VALUE;
      DnBuf[i] = (tr < 0) ? ma : EMPTY_VALUE;
   }
   return rates_total;
}
