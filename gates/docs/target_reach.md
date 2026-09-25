# Célár-elérés — reális-e a célár?

A célár eddig csak egy **szorzó** volt (`tp_rr_ratio × stop`): megmondta, hány
R-re van, azt nem, hogy a piac a közelmúltban mozgott-e ennyit egyáltalán. Ez a
kapu ezt kérdezi meg — **minden stratégiára egyformán**, mert a kész
belépő-tervből (stop + célár) dolgozik, nem a stratégia belsejéből.

## A szabály

| irány | mikor enged át |
|---|---|
| **BUY** | az utolsó `lookback` lezárt gyertya **legmagasabb high**-ja elérte a belépő + `reach_pct` × célár-távolság szintet |
| **SELL** | tükörkép: a **legalacsonyabb low** elérte a belépő − … szintet |

Ha nem érte el, a célár nem reális, a kapu **bukik**.

| paraméter | alap | jelentés |
|---|---|---|
| `timeframe` | M1 | ezen az idősíkon nézünk vissza |
| `lookback` | 22 | ennyi **lezárt** gyertyát |
| `reach_pct` | 0,7 | a célár-távolság ennyi részét kell elérni (a megengedő sáv 0,6–0,8) |

A belépő referenciája a döntést hozó (lezárt) gyertya záróára — ugyanaz az ár,
amin a backtest belép.

> **Mit jelent a gyakorlatban?** BUY-nál a feltétel azt kéri, hogy az ár a
> közelmúltban **magasabban** járt, mint ahol most belép — vagyis egy
> visszaesés utáni belépőt enged. A wpr_sma-nál ez így olvasható: „a visszaesés
> mélysége legalább a célár 70%-a".

## Mérve (2026-09-25) — ⚠ a kötésenkénti eredményt RONTJA

14 wpr_sma pár, 2025-11-01 – 2026-09-24, él-paritású backtest (`run_pair`):

| változat | kötés | R/kötés |
|---|---|---|
| kapu nélkül | 6445 | −0,143 |
| Célár-elérés, **M1** / 22 / 70% | 3248 | **−0,204** |
| Célár-elérés, **M15** / 22 / 70% | 4593 | **−0,223** |

- M1-en **10 párt teljesen lenulláz** (EURUSD, GOLD, Fra40, …): 22 perc alatt
  az ár a több M15-ATR-es célár 70%-át szinte sosem járja be.
- A megmaradt kötések mindkét idősíkon **rosszabbak** — a kapu a gyengébb
  belépőket hagyja meg. A dollár-veszteség csak azért kisebb, mert kevesebb a
  kötés.

Ezért a kapu **alapból ki van kapcsolva** (`none`). Bekapcsolás előtt érdemes
más `reach_pct` / `lookback` értékkel újramérni.

## Távoli célár

Ha a készlet célára „végtelen" (`tp_rr_ratio` 15 = nincs célár, trailinggel),
a kapu szinte mindig bukik. Ilyen készleten a hatás legyen `Ki`.

## Hol dönt

Terv-fázisú kapu: a stratégia kész stopja és célára után, a Költség-kapuval egy
sorban. Élesben, egypáros és portfólió-backtestben és a charton (viz) is
ugyanazzal a méréssel.
