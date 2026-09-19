# Karmester — terv

**Állapot:** terv, még nincs megvalósítva. A dokumentum a *mit és miért* rögzíti;
a kód még nem létezik.

**A kiváltandó probléma:** a rendszer ma 10–12 instrumentumot, 4-5 stratégiát,
5 kaput és két kötés-módot (`live` / `signal`) kombinál. Ez több száz
`(instrumentum × stratégia)` cella, mindegyik saját paraméterkészlettel,
minősítéssel és életciklus-állapottal. A dashboard ezt **megmutatja** — de nem
dönt róla. Ami hiányzik, az nem egy újabb nézet, hanem egy **döntési réteg**.

---

## 1. A lelet: minden alkatrész megvan, csak a karmester nincs

| Réteg | Hol lakik | Mit ad |
|---|---|---|
| Kereskedés-szándék | `core/run_state.py` (live/stopped) | ki fut |
| Kötés-mód | `core/trade_mode.py` (live/signal) | ki köt valódi pénzzel |
| Kockázat | `core/rr_state.py`, `risky_mode.py`, `risk_manager.py`, `correlation.py` | presetek, slotok, kitettség |
| Minősítés | `core/quality.py`, `core/overview.py` | ki jó, és hol hazudik a szám |
| Parancsréteg | `core/console_cmd.py` | play/stop/close, megerősítés-mintával |
| Bizonyíték | `strategy/signal_journal.py`, `core/position_meta.py`, `core/pnl_split.py`, `core/applog.py` | mi történt valójában |
| Higiénia | `core/config_check.py`, `config_freshness.py`, `scope_check.py`, `opt_plan.py` | mi romlott el némán |

A hangszerek tehát hangolva vannak. Ami nincs: egy entitás, aki a mátrixot
ciklikusan végignézi, **dönt, cselekszik, és leírja, hogy miért**.

### A második, kevésbé feltűnő hiány

A rendszer ma nem tudja megmondani, **mi NEM történt**. Nincs kapu-telemetria
(a `core/gates.py` és a `core/gate_bands.py` nem számlál blokkolást), ezért a
leggyakoribb kérdésre — *„miért nem kötött ma az EURUSD?"* — nincs válasz.
Több tucat cellánál ez naponta visszatérő, megválaszolhatatlan kérdés.

---

## 2. Alapelv: a karmester vezényel, nem játszik

> **A karmester nem ír át kottát.** Nem nyúl a stratégiák paramétereihez, nem
> küld megbízást, nem számol jelet. Azt dönti el, **ki játszik, mikor és milyen
> hangerővel** — és elindítja az optimalizálót, ha egy szólam hamis.

Ebből következik a három réteg:

```
┌─ L2: TANÁCSADÓ (LLM) ──────────────── óránként / naponta ─┐
│  magyaráz · rangsorol · anomáliát nyomoz · riportol        │
│  KIMENETE: javaslat-objektum, soha nem akció               │
└───────────────────────┬────────────────────────────────────┘
                        │ séma-validált javaslat
┌─ L1: SZABÁLYMOTOR (tiszta Python) ── percenként / óránként ─┐
│  determinisztikus házirendek · invariánsok · kvóták          │
│  EZ az egyetlen réteg, ami pénzhez érhet                     │
└───────────────────────┬──────────────────────────────────────┘
                        │ Action → console_cmd / run_state / rr_state / …
┌─ L0: KOTTA (snapshot) ─ a motor ciklusvégén ─┐
│  egyetlen fagyasztott adatkép az egész rendszerről │
└────────────────────────────────────────────────────┘
```

**⚠ MIÉRT NEM EGY NAGY LLM-ÜGYNÖK.** A projekt legdrágább hibaosztálya végig
ugyanaz volt: **néma, nem reprodukálható hiba** — a viz↔backtest paritás, a két
stratégia-lista, a `cfg` NameError a `process_pair`-ben, a „PF 5,11 hat kötésen".
Egy LLM-et beengedni a kötési útvonalra ugyanennek az osztálynak egy új,
*elvileg* reprodukálhatatlan forrása lenne. Az LLM ott ér sokat, ahol nyelv és
ítélet kell, nem ott, ahol kapcsoló.

---

## 3. Hol lakik: a motor processzében, külön szálon

A karmester a `trading/live_trader.py` processzében fut, saját szálon — nem
külön program.

**⚠ MIÉRT ÍGY, ÉS NEM KÜLÖN PROCESSZKÉNT.** Három oka van, és mind gyakorlati:

1. **Mind a három felület egyszerre kapja meg, ingyen.** A `live`, a `console`
   és a `console --tui` UGYANAZT a motort futtatja (`live_trader.run` szálban,
   a főszálon pedig a tkinter / a parancssor / a `rich` tábla ül). Ha a
   karmester a motorban lakik, a felület csak *megjelenít*. Külön processznél
   mindhárom felületnek saját kapcsolatot kellene építenie hozzá — és három
   külön módon romlana el.
2. **Ugyanazon a licenc-, zár- és életciklus-kapun megy át, mint a kötés.** A
   `core/live_lock.py` számlánként zár, a `core/licence_gate.py` a számlához
   szól. Ha a motor nem futhat, a karmester sem — automatikusan, külön kód
   nélkül. Egy önálló felügyelőnél a legkellemetlenebb hibaosztály az, amikor
   a felügyelő fut, a felügyelt nem.
3. **Nincs külön karbantartás, indítás, verziózás, config.** A karmester a
   program része, nem melléktermék.

**Amit cserébe elveszítünk:** a karmester csak addig él, amíg a motor. Két
helyen jelentkezik, mindkettő kezelhető:

* **Éjszakai / hétvégi munka** — a munkaelemek lemezre kerülnek
  (`data/conductor/queue.jsonl`), és induláskor a karmester felveszi a fonalat.
  Ugyanaz a minta, mint a `run_state` reconcilere vagy a
  `params_store.unfinished_studies`.
* **`main.py dashboard` (demo mód, MT5 nélkül)** — ott nincs motor, tehát nincs
  karmester. A Karmester fül ilyenkor **krónika-nézet**: a naplót olvassa, nem
  dönt. Szűkített üzemmód, nem hibaüzenet.

**⚠ KÖVETKEZMÉNY: a karmester állapota nem lehet memóriában.** A motor
újraindulása a karmester újraindulása is. Hol tart egy cella az életciklus-
létrán, mikor volt az utolsó változtatás, mennyi kvóta fogyott ma — mind
lemezre kerül (`data/conductor/state.json`), a napi számláló **dátumhoz kötve**,
különben egy újraindítás nullázná a hatósugarat.

### A szál szerződése — öt szabály

**① Olvasás: pillanatkép, nem élő hivatkozás.**
A karmester nem olvas félig átírt szótárból. A motor a ciklusa végén készít egy
fagyasztott másolatot (`snapshot.capture()`); a szál csak ezen dolgozik. Egy
tick alatt inkonzisztens adatból hozott döntés az a fajta hiba, ami
háromhavonta egyszer jön elő, és sosem reprodukálható.

**② Írás: nincs közvetlen írás — sorbaállítás és alkalmazási pont.**
A karmester `Action`-t tesz egy sorba; a motor a **pár-ciklusok között**,
definiált helyen üríti. Soha nem változik mód / preset / run_state egy pozíció
feldolgozása *közben*. Ez a `core/pstate.py` tanulságának („öt helyen hoztuk
létre, aki előbb ér oda, az nyer") megelőzése — most nem rekordra, hanem
szándékra.

**③ Izoláció: a karmester nem állíthatja meg a motort.**
A `core/telegram_cmd.py` mintája: minden kivétel a szálon belül marad, és
**három egymást követő hiba után a karmester önmagát L-1-re ejti**, naplóz,
értesít. A motor ebből semmit nem vesz észre.

**④ Watchdog: a karmestert is figyelni kell.**
Szívverés-bélyeg minden cikluson. Ha egy ciklus túllép a küszöbön, az akció-sor
**eldobódik** (nem alkalmazódik később, elavultan), és a szál újraindul.

**⑤ Az LLM külön, eldobható munkásszálon.**
Hálózati hívás nem lehet a döntési útvonalon. Szigorú időkorlát, saját
költségkorlát; ha nem válaszol, a szabálymotor **nélküle is teljes értékűen
dolgozik**. Az LLM sosem előfeltétele egy döntésnek. A neki átadott pillanatkép
**maszkolt**: bróker-jelszó, licenctoken nem megy ki.

**Gyakorlati következmény (GIL):** a karmester számolása a motor CPU-idejét
lopja. Ezért a nehéz munka (gördülő KPI-k, riport, elemzés) **ütemezett**, nem
ciklikus — piaczárás után vagy alacsony aktivitású ablakban. Percenként csak az
olcsó egészségőr fut.

---

## 4. Amit lát: a Kotta (`conductor/snapshot.py`)

Egyetlen struktúra `(instrumentum × stratégia)` cellánként — a rendszer egyetlen
igazságforrása, amiből később a dashboard is élhet:

* **Szándék és mód** — `run_state`, `trade_mode`, engedélyezettség **a motor
  listájából** (`pairs.<sym>.strategies`), nem a megjelenítéséből.
* **Pozíció-valóság** — nyitott ticketek, R-ben mért kitettség, slot-súly,
  korrelációs klaszter.
* **Teljesítmény** — élő gördülő PF / expectancy / kötésszám, a mentett
  backtest-várakozás, és a kettő **eltérése**.
* **Bizonyíték-erő** — hány valódi kötés áll a minősítés mögött.
* **Paraméter-eredet** — mikor optimalizálták, milyen kapu-beállítással, egyezik-e
  az ujjlenyomat a mostanival.
* **Kapu-telemetria** — kapunként napi blokkolás/csökkentés-szám és az utolsó
  blokkolás indoka. *(ma nincs — építeni kell)*
* **Piac** — regime (`core/regime.py`), nyitva van-e (`core/market_state.py`),
  spread/ATR állapot.
* **Higiénia** — `config_check` és `config_freshness` leletek, lock-ütközés,
  optimalizálás-aktivitás.

### Hiánylista — ezek előbb kellenek, mint maga a karmester

1. **Kapu-telemetria számlálók** (`core/gates.py` → napi aggregátum fájlba).
2. **Élő gördülő KPI-tár** `(sym × strat)` bontásban — a nyersanyag megvan
   (`pnl_split`, `position_meta`, `signal_journal`), az aggregátum nincs.
3. **„Várt aktivitás"** — a backtestből mennyi kötés/nap várható. Enélkül az
   elszáradt pár anomáliája **nem detektálható**.
4. **Döntésnapló és javaslat-tár** (új).

⚠ **A KRÓNIKA AZ F1-BE CSÚSZOTT, SZÁNDÉKOSAN.** Az F0-ban nem lett volna EGYETLEN
írója sem: a mérő réteg nem hoz döntést, amit naplózni kellene. Egy író nélküli
napló-modul halott kód — és pont az a fajta, ami hónapokig „kész funkciónak"
látszik, miközben soha nem futott le (lásd a `.tfg`-kapu esetét a
`live_trader`-ben). Az első valódi írója az F1 **árnyék-módja** lesz, ahol a
karmester leírja, mit TENNE — ott a krónika formátuma is a tényleges használatból
következik majd, nem egy előre kitalált sémából.

---

## 5. Amit tehet: a keskeny írási kapu (`conductor/actions.py`)

| Akció | Mit ír | Visszafordítható | Jóváhagyás |
|---|---|---|---|
| `set_mode(sym, strat, signal/live)` | `trade_mode` | igen | L3-ig ember |
| `play` / `stop(sym, strat)` | `run_state` a `console_cmd`-en át | igen | stop: L2-től gépi |
| `set_risk_preset(sym, preset)` | `rr_state` | igen | L2-től gépi |
| `set_risky(sym, bool)` | `data/risky_mode.json` | igen | L2-től gépi |
| `set_correlation_mode(mode)` | `data/correlation_mode.json` | igen | L3-tól gépi |
| `queue_optimize(sym, strat, scope)` | opt-sor | igen | L1-től gépi |
| `adopt_params(sym, strat, run_id)` | `params_store` | igen (előző verzió marad) | L3-ig ember |
| `set_gate_band(sym, strat, gate, létra)` | config-delta | igen | L3-ig ember |
| `close_position(ticket)` | `console_cmd.cmd_close` | **NEM** | külön kapcsoló, alapból tiltva |
| `freeze_all()` | globális stop | igen | mindig gépi (vészág) |
| `notify` / `report` | Telegram, napló | – | gépi |

Két szabály itt dől el:

* **Minden akció rögzíti az előző állapotot** → egykattintásos visszavonás.
* **Config-írás csak a meglévő delta-házirenddel** (`config_check` tiszta, és
  csak az ELTÉRÉS kerül a fájlba). `config_check` WARN mellett a karmester
  **nem ír**, hanem szól.

**⚠ AZ AKCIÓK A `console_cmd`-ON KERESZTÜL MENNEK, nem mellette.** A
`core/console_cmd.py` nyitó bekezdése erről szól: *„ha mindhárom felület a
sajátját írná meg, három forrás romlana el külön"*. A karmester nem lehet egy
újabb forrás — különben a benne lévő, élesben megtanult szabályok (csak
engedélyezett stratégia indítható; a „maradt-e élő stratégia" kérdést a MOTOR
listájából kell megválaszolni) rá nem vonatkoznának, és ugyanaz a hiba megint
megtörténhetne — most már automatikusan, éjjel.

---

## 6. A feladatkörök — hét kalap

### ① Krónikás ✅ (v3.77.0 · v3.79.0)
Döntésnapló és napi riport: mi változott, mi kötött, **mi nem, és miért nem**.

A napi riport **a meglévő esti üzenetbe** épül (`notify.daily_summary_time`),
nem új csatorna: egy második esti üzenet versenyezne az elsővel, és a kettő
előbb-utóbb mást mondana ugyanarról a napról. Három szakaszt tesz hozzá —
mérés (jel → kötés, a fő akadályok, **mely instrumentum volt ébren**), a nap
leletei, és az aznapi árnyék-javaslatok. Parancs: `report`.

⚠ **A riport a KRÓNIKÁBÓL olvas**, nem futtatja újra az egészségőrt. Ha
23:00-kor újraszámolna, a MOSTANI állapotot mutatná — ami eltérhet attól, ami
napközben a krónikába került —, és utólag nem lehetne eldönteni, melyik az igaz.
Így az üzenet szerkezetileg a krónika kivonata.

⚠ **Zárt piac ≠ álló motor.** A telemetria csak JELRE ír, tehát egy üres napi
fájl mindkettőt jelentheti — a riport ezt kimondja, nem választ magabiztosan
(hétvégén tipikusan csak a kripto ad jelet, és a riport ki is írja, melyik
instrumentum volt ébren).

### ② Egészségőr ✅ (v3.77.0)
A projekt visszatérő hibaosztályának automatizált vadászata. **Nem írja újra a
meglévő detektorokat**, hanem összefogja őket (`config_check`,
`config_freshness`, `overview`), és hozzáteszi, amit csak a mérésből lehet tudni:

| Lelet | Mit fog meg |
|---|---|
| `dried_up` | fut, nem blokkolja semmi, nem is veszít — csak nem köt (a mentett várakozás töredékét hozza) |
| `gate_wall.<kapu>` | egy kapu a napi jelek ~mindegyikét blokkolta, és egy kötés sem lett |
| `silent_days` | N olyan napja nincs jel, **amikor a motor futott** (hétvége és leállás nem számít) |
| `source_error.<forrás>` | egy ellenőrzés NEM futott le — a mérés hiánya is lelet |

Óránként fut a motorban; a leletek naponta egyszer a **krónikába** kerülnek
(`data/conductor/decisions.jsonl`), így a „mióta áll fenn?" utólag
megválaszolható. Parancs: `health` (a konzolon, a TUI-n és Telegramon is).

⚠ A jelentés SOSEM mondja, hogy „minden rendben": a `config_freshness`
MT5-kapcsolat nélkül üres listát ad, és az üres lista megkülönböztethetetlen a
„minden friss"-től. Csak annyit állít, hogy NINCS LELET.

### ③ Életciklus-kapus ✅ (v3.78.0, árnyék-módban)
A promóciós létra, írott feltételekkel:

```
STOPPED ──► UNTUNED ──► PAPER ──► LIVE
            (nincs      (csak     (valódi
             készlet)    jelzés)   kötés)
               ▲            ▲         │
               └────────────┴─────────┘
                   visszaminősítés
```

*Ez a feladatkör teszi a mátrixot kézben tarthatóvá: minden cella egy
életciklus-ÁLLAPOTBAN van, nem egy sor egymástól független kapcsolóban.*

| Lépés | Feltétel |
|---|---|
| `UNTUNED` → optimalizálás | nincs mentett készlet (a cella fut tovább az alapértékekkel) |
| `PAPER` → `LIVE` | N jel M olyan napon, amikor a motor futott + mentett OOS minősítés + **nincs KOCKÁZATI lelet** → **mindig emberi jóváhagyás** |
| `LIVE` → `PAPER` | elszáradás, vagy romlás (PF a küszöb alatt) **elég bizonyítékkal** |
| `LIVE` → optimalizálás | a mentett készlet avult (a kereskedés megy tovább) |

**Három dolog, amit a terv eredeti szövegéhez képest a valóság átírt:**

1. **Nincs külön „felezett élő" fok.** A kockázatcsökkentő preset
   (`core/rr_state.py`) **instrumentum-szintű**, nem cella-szintű: egy páron a
   `wpr_sma`-t nem lehet felezni úgy, hogy az `ml_ai` teljes mérettel menjen.
   Egy kitalált fok olyan állapotot ígérne, amit a rendszer nem tud előállítani.
2. **A papír AKTIVITÁST bizonyít, nyereségességet nem.** A „csak jelzés" módú
   sorok a `trades.csv`-ben P&L nélküliek. Aki papírból következtet hozamra, a
   backtestjét méri újra, csak lassabban. Ezért a `PAPER → LIVE` lépés három
   feltételt köt össze (aktivitás + mentett OOS + tiszta egészség), és mindig
   emberi.
3. **A kis mintából nem minősítünk vissza.** 15 kötésen egy 1,10-es PF-ű
   stratégia a minták 4,5%-ában PF>3-at mutat — és ugyanennyire tud lefelé is
   tévedni. A romlás-szabály `demote_min_trades` alatt nem szólal meg.

Az F1-ben mindez **árnyék-mód**: a házirend javaslatot ad, a javaslat a
krónikába kerül (`kind="shadow"`, a döntést hozó SZÁMOKKAL együtt), és semmi nem
hajtódik végre. Parancs: `plan`.

### ④ Optimalizálás-ütemező — a sor megvan ✅ (v3.82.0)

Az optimalizálás indítása eddig **csak a grafikus felületen** létezett
(`OptimizerController`): a konzolos és a fej nélküli (VM, SSH) futás egyáltalán
nem tudott optimalizálást kérni. A `conductor/optqueue.py` ezt adja meg —
és ezzel a `queue_optimize` javaslat végrehajthatóvá vált.

* **Alprocesszben, nem szálon.** Az optimalizálás órákig tartó, CPU-nehéz
  munka; a motor szálán a kereskedés körideje nyúlna meg. A sor a MEGLÉVŐ
  belépési pontot indítja (`main.py optimize <SYM> --strategy <S>`), tehát
  nincs második optimalizáló-implementáció, és a `core/opt_lock.py`
  (processzek közötti zár) pontosan erre való.
* **⚠ Kereskedő cellát nem optimalizál.** A futás végén a paraméterfájlja
  íródna felül az alól a cella alól, amelyik épp vele kereskedik — ez a felület
  szabálya, és itt ugyanaz a képlet dönt (`run_state.live_strategies`). A
  „csak jelzés" módú cella is ilyen: ott a papír-bizonyíték gyűlik. A blokkolt
  kérés **nem vész el és nem fut le csendben**: `blocked` állapotban várakozik,
  az okával együtt.
* **Alapból egy párhuzamos futás.** Az élő motor mellett fut; hat párhuzamos
  optimalizálás elvenné a gépet a kereskedés elől.
* **Adatletöltés nincs** — a lemezen lévő előzményből dolgozik (amit az
  `data.gap_fill_on_start` tart frissen). Ha nincs adat, a job hibával áll le,
  és ez a sorban látszik.

Parancs: `optq` (és `optq cancel <id>`). A hajtás a **motoré** (óránként): egy
alprocessz indítása egy lekérdezés mellékhatásaként meglepetés volna.

### ④/b Ami még hátra van az ütemezőből
Ki avult el, kinek kevés a bizonyítéka, kinél csúszott el a kapu-beállítás →
prioritási sor a `max_parallel_optimizers` keretén belül, éjszakára időzítve.

**⚠ Az eredmény ÁTVÉTELE külön döntés**, és beépül a mért figyelmeztetés: a
walk-forward vizsga-ablak **nem független mérés** (2,51× felfújás, lásd
`core/overview.py`), tehát az átvételhez friss out-of-sample kell.

### ⑤ Kockázati karmester
Napi limit, presetek, korrelációs klaszterek, regime-váltásra globális
óvatosság. **A karmester önállóan csak LEFELÉ léphet** (kockázatot csökkenteni),
felfelé sosem.

### ⑥ Portfólió-elosztó
A `max_open_slots` globális — ma „aki előbb jelez, az nyer". A karmester
**keretet** adhat: melyik cella versenyezhet a slotokért, milyen súllyal. Ez a
legmélyebben hozamba nyúló feladatkör, ezért **utoljára** jön.

### ⑦ Tolmács (LLM)
Természetes nyelvű kérdés–válasz az állapotról, heti elemzés,
hipotézis-generálás („három páron ugyanaz a kapu blokkol — nézd meg a sávot"),
és a javaslatok emberi nyelvű indoklása.

---

## 7. A célfüggvény — configból hangolva

A karmester alapértelmezett célja a **kockázattal súlyozott hozam**, de a súlyok
a configból állíthatók.

**⚠ A CSAPDA: ha a célfüggvény szabadon hangolható, a döntés csak annyit ér,
amennyire a súlyok őszinték.** Ezért a súlyok mellé kötelező a *kijelző*: minden
döntésnél látszik a pontszám bontása, nem csak a végeredmény.

Egy központi fájl (`conductor/scoring.py`), egyetlen függvénnyel, amit MINDEN
házirend hív (elosztás, előléptetés, visszaminősítés, opt-sorrend):

```
score(cella) =  w_ret  · norm(expectancy_R_per_nap)
             −  w_dd   · norm(max_drawdown_R)
             −  w_var  · norm(hozam_szórás)
             +  w_eqty · norm(élő ↔ várt egyezés)
             −  w_cost · norm(költség / bruttó nyereség)
             ×  conf(kötésszám)
```

Két elem, ami nem szokásos, de itt muszáj:

* **`conf(kötésszám)` — bizonyíték-szorzó.** A `core/quality.py` mérése (PF 5,11
  hat kötésen = zaj) pont arról szól, hogy a nyers metrika kis mintán hazudik. A
  szorzó 0-ról kúszik 1-re a kötésszámmal (50 körül ér a közelébe), tehát egy
  csillogó, de vékony cella **nem nyerheti meg** a slot-versenyt egy unalmas, de
  bizonyított ellen. Enélkül a kockázattal súlyozott hozam szisztematikusan a
  zajt jutalmazná.
* **`w_eqty` — élő↔várt egyezés.** Nem hozam, hanem *megbízhatóság*: az a cella
  értékesebb, amelyik azt csinálja, amit a backtestje ígért. Ez az egyetlen
  védelem a túlillesztés ellen, ami élesben is mér.

```jsonc
"conductor": {
  "_comment_objective": "A karmester CÉLFÜGGVÉNYE. A preset beállítja a súlyokat; a 'weights' felülírja, amit megadsz benne. A döntésnaplóba MINDIG a tényleges súlyok kerülnek.",
  "objective": {
    "preset": "risk_adjusted",       // survival | risk_adjusted | evidence | custom
    "weights": {
      "return": 1.0, "drawdown": 1.2, "variance": 0.5,
      "equity_fit": 0.8, "cost": 0.3
    },
    "_comment_conf": "Hány valódi kötésnél éri el a bizonyíték-szorzó a 0,9-et. A quality.min_trades mérése alapján 50 az alsó józan határ.",
    "confidence_trades": 50,
    "lookback_days": 90
  }
}
```

**⚠ A preset NEM mód, hanem SÚLY-SABLON.** A `survival` és a `risk_adjusted`
ugyanazon a képleten fut, csak más számokkal — egy kódút, nem három.

---

## 8. Autonómia: L-1 … L4, configból, cellánként is

| Szint | Név | Mit tesz |
|---|---|---|
| **L-1** | **Kikapcsolt** | A szál el sem indul. Nem figyel, nem ír fájlt, nem riportol. |
| L0 | Megfigyelő | Csak mér és naplóz. Nincs javaslat, nincs értesítés. |
| L1 | Tanácsadó | Javaslatot tesz, mindent ember hagy jóvá. |
| L2 | Segített | Visszafordítható + kockázatcsökkentő akciók gépiek. |
| **L3** | **Korlátozott önálló** *(alapérték)* | A teljes akciókészlet gépi — kvótákon és hatókörön belül, visszavonási ablakkal. |
| **L4** | **Teljes önálló** | Nincs kvóta-plafon, nincs várakozás. A burok marad. |

**⚠ AZ L4 NEM AZT JELENTI, HOGY „MINDENT SZABAD", hanem hogy nincs emberi
jóváhagyási lépés.** A burok (kvóták, hatósugár, a motor saját kockázati kapui)
L4-en is a helyén marad — különben nem autonómia, hanem felügyelet nélküli
szabadesés.

**A kulcs: az autonómia per `(instrumentum × stratégia)` cella állítható**,
ugyanúgy, ahogy a `run_state` és a `trade_mode` már ma is. Így a bevizsgált
cellák mehetnek L4-en, az új stratégia L1-en marad, a GOLD pedig L0-ra
fixálható, amíg nem érted, mit csinál.

```jsonc
"conductor": {
  "autonomy": {
    "_comment": "-1=kikapcsolva | 0=megfigyelő | 1=tanácsadó | 2=segített | 3=korlátozott önálló | 4=teljes önálló",
    "default": 3,

    "_comment_scope": "Felülbírálás hatókörönként. A LEGSZŰKEBB találat nyer: cella > instrumentum > alapérték.",
    "overrides": { "GOLD": 0, "EURUSD.ml_ai": 1 },

    "_comment_quota": "A HATÓSUGÁR. L3-on kötelező, L4-en 0 = korlátlan. L4-en is érdemes megtartani: ez az egyetlen dolog, ami egy elszálló visszacsatolási hurkot megállít.",
    "max_changes_per_day": 6,
    "cooldown_hours_per_cell": 72,
    "no_change_while_position_open": true,
    "undo_window_hours": 24,

    "_comment_irreversible": "A VISSZA NEM VONHATÓ akciók (pozíciózárás) külön kapcsolón — L4 SEM oldja fel magától.",
    "allow_irreversible": false
  }
}
```

### Ami L4-en sem tűnik el

1. **A motor kockázati kapui a MOTORÉI, nem a karmesteréi.**
   `daily_loss_limit`, `max_open_slots`, `same_symbol_policy`, `correlation` — a
   karmester ezeken *belül* dolgozik, nem tudja őket felülírni. Ez nem
   autonómia-kérdés, hanem rétegzés: ha a karmester átírhatná a saját
   korlátait, a korlát nem korlát.
2. **`config_check` WARN továbbra is írás-tiltó.**
3. **Minden akció naplózott és visszavonható** — L4-en ez *fontosabb*, mert
   reggel ebből tudod meg, mi történt éjjel.
4. **Az LLM L4-en sem kapcsol semmit.** A javaslat → validáció → akció útvonal
   marad; a szint csak azt mondja meg, kell-e emberi pipa a validáció után.
5. **Vissza nem vonható akció külön flagen**, alapból tiltva, minden szinten.

### Az L-1 kapcsoló — három, egymástól független úton

„Bármikor kikapcsolható" csak akkor igaz, ha akkor is működik, amikor a program
épp nem válaszol:

| Réteg | Hogyan | Mikor hat |
|---|---|---|
| Config | `conductor.autonomy.default = -1` | újraindításkor + config-újraolvasáskor |
| **Kill-switch fájl** | `data/conductor/off` létezik | **a következő szál-cikluson belül (≤ 5 mp)** |
| GUI / TUI / Telegram | „Karmester: KI" | azonnal |

A szál minden ciklus elején, **a pillanatkép elkészítése ELŐTT** ellenőrzi a
kapcsolót — L-1-ben tehát tényleg nem olvas, nem számol, nem ír. Induláskor
L-1 esetén a szál el sem indul.

**⚠ KIKAPCSOLÁSKOR A KARMESTER ÁLTAL BEÁLLÍTOTT ÁLLAPOTOK MARADNAK.** A
visszaállítás maga is cselekvés, kikapcsolt állapotban pedig nem cselekszik.
Helyette külön, kézi parancs van: *„Vissza az utolsó emberi állapotra"*, ami a
krónikából visszagörgeti a karmester összes változtatását egy megadott
időpontig. A kikapcsolás gyors és néma; a visszaállítás tudatos és látható.

---

## 9. A karmesternek is van életciklusa

Ha a plafon L4, akkor a karmesternek **ugyanazt a bizonyítási utat kell
bejárnia, amit a stratégiáktól elvársz**:

```
ÁRNYÉK-MÓD (L0)          → minden ciklusban LEÍRJA, mit tenne — de nem teszi
   ↓  ≥30 nap, ≥50 döntés
TANÁCSADÓ (L1)           → a döntéseit ember hagyja jóvá; mérhető, hányszor volt igaza
   ↓  magas elfogadási arány, a kihagyott döntések utólag rosszabbnak bizonyulnak
SEGÍTETT (L2)            → visszafordítható akciók gépiek
   ↓  0 káros beavatkozás N napig
KORLÁTOZOTT ÖNÁLLÓ (L3)  ← az alapértelmezés
   ↓  mért döntésminőség, CELLÁNKÉNT
TELJES ÖNÁLLÓ (L4)       ← cellánként nyílik meg, nem globálisan
```

Az árnyék-mód **ingyen van** (a döntésnapló úgyis kell), és ez az egyetlen mód,
hogy az L4-et ne hitből add meg, hanem adatból. A karmester döntései ugyanazzal
az eszközzel minősíthetők, mint a stratégiák: elfogadási arány, a beavatkozás
utáni R-változás, és a `conf(n)` bizonyíték-szorzó a döntésszámra.

---

## 10. Sérthetetlen szabályok (`conductor/invariants.py`)

Kódban élnek, minden akció áthalad rajtuk — az LLM nem tudja őket „meggyőzni":

1. Az LLM **soha** nem hív MT5-öt, nem küld/zár megbízást, nem ír configot.
   Kimenete kizárólag séma-validált `Proposal`.
2. Az LLM nem lát titkot (bróker-jelszó, licenctoken) — a pillanatkép maszkolt.
3. `live` módba kapcsolás előfeltétele ≥50 valódi kötés bizonyíték, **vagy**
   kifejezett emberi felülbírálás.
4. Előléptetés nem alapulhat a walk-forward vizsga-ablak metrikáján egyedül.
5. `config_check` WARN → nem ír configot, csak jelent.
6. Minden akció előtti állapot naplózva. **Fail closed:** ha a karmester beteg
   (adat hiányzik, LLM elérhetetlen), befagy az utolsó jó állapotban.
7. Kill switch: `data/conductor/off` → azonnali L-1.
8. Indok nélkül nincs döntés: `(szabály-azonosító, bemenő számok, küszöb)`
   triplet kötelező a naplóban.

---

## 11. Ütem

| Ciklus | Ki fut | Mi |
|---|---|---|
| ~1 perc | L0+L1 | pillanatkép, egészségőr, vészfékek |
| ~1 óra | L1 | házirendek kiértékelése, javaslatok |
| napi (piaczárás után) | L1+L2 | riport, opt-sor, életciklus-léptetések |
| heti | L2 | portfólió-átvizsgálás, LLM mélyelemzés |

Az LLM így **napi néhány hívás**, nem tickenkénti — a valós idejű döntés végig
determinisztikus marad.

---

## 12. Felület

**„Karmester" fül / nézet**, mind a három felületen ugyanabból az állapotból:

* **Postaláda** ✅ (v3.80.0) — javaslat-kártyák: *mit, miért, mi a bizonyíték,
  mi a visszaút* → Elfogad / Elvet / Elhalaszt. A `core/signal_offer.py`
  lejárat- és egyszer-használhatóság-mintája itt is érvényes; a parancsréteg
  felől: `inbox` · `accept <id>` · `reject <id>` · `defer <id>` · `undo <id>`.

  Négy szabály, ami kóddá vált benne:

  1. **A javaslat nem parancs.** Az elfogadás pillanatában a házirend
     ÚJRASZÁMOLJA a javaslatot, és csak akkor lép, ha ma is ugyanazt mondja.
     Egy tegnapi „minősítsd vissza" egy azóta megjavult cellán kárt tenne — és
     az ilyen, időközben elavult döntés a legnehezebben észrevehető hiba:
     minden lépés helyesnek *látszik*, csak épp egy régi világra vonatkozik.
     A lejárat csak a második védvonal.
  2. **Az elvetésnek meg kell maradnia.** Ha az elvetett javaslat másnap
     újraszületne, az elvetés semmit nem jelentene — a postaláda pedig arra
     tanítana, hogy hagyd figyelmen kívül.
  3. **Minden akció rögzíti az előző állapotot.** A visszaút a tételbe és a
     krónikába is bekerül; a visszavonás maga is akció (egy visszaminősítés
     visszavonása valódi kötést kapcsol vissza — ugyanaz a megerősítés-minta).
  4. **Amihez nincs végrehajtási út, arra nem teszünk úgy, mintha lenne.** Az
     ilyen tétel TANÁCSKÉNT jelenik meg, és az elfogadás megmondja, hol
     végezhető el. *(Az optimalizálás v3.82.0-ig pont ilyen volt — lásd lent.)*

  ⚠ Telegramon a postaláda **csak olvasható**. Az `accept` valódi kötést
  kapcsolhatna be egy chatüzenetből — az a `notify.answer_trading` kategóriája
  (külön opt-in, gombos megerősítéssel), nem egy parancs-listás döntés.
* **Mátrix** ✅ — a `12 × 5` rács egy képen, cellánként az életciklus-fokkal és
  a leletek számával. *Ez váltja ki azt, amit ma fejben tartasz.*
* **Krónika** ✅ — mit tett a karmester, visszavonás gombbal.

A fül (`dashboard/conductor_tab.py`, v3.81.0) **nem tud semmit**: se házirendet,
se küszöböt, se végrehajtást. Egyetlen seamet kap — a `DashboardWindow._cmd_ctx`
által előállított `console_cmd.Context`-et —, és minden döntés a közös
parancsrétegen megy. Egy „felületi másolat" a szabályokból az első
config-változásnál elcsúszna, és a fül magabiztosan hazudna.

Két dolog, ami a felületi valóságból következett:

* **Két frissítés, két költség.** A dashboard köre 30 másodpercenként fut; a
  házirendek újraszámolása (cellánként fájlokkal) ott mérhető lassulást okozna
  a felület szálán — a projekt ezt egyszer már megmérte (7,64 → 0,31 mp/kör).
  A periodikus `refresh()` ezért csak a postaláda- és krónika-fájlt olvassa; a
  teljes átvizsgálás a **⟳ Átvizsgálás** gombon (és az első megnyitáson) megy.
* **Csak változáskor rajzolunk újra.** A két állapotfájl módosulási ideje a
  kapu. Enélkül a fül 30 másodpercenként villogna, a görgetés visszaugrana
  olvasás közben, és egy épp megnyomott gomb kicsúszhatna az ujjad alól. Saját
  döntés után viszont kényszerített újrarajzolás kell: a másodperc-felbontású
  mtime kiszűrné a saját hatásunkat.

Telegramon ugyanez, a `telegram_cmd.ENGEDETT` engedélyező lista bővítésével,
a meglévő gombos megerősítés-mintával.

---

## 13. Fájlszerkezet

```
conductor/
  config.py        # a conductor.* config blokk olvasása, EGY helyen
  objective.py     # a célfüggvény presetjei és súlyai
  scoring.py       # score(cella) — minden házirend ezt hívja
  mandate.py       # autonómia-feloldás: cella > instrumentum > alapérték; kvóták
  killswitch.py    # L-1: config + data/conductor/off + felület, egy helyen
  snapshot.py      # fagyasztott pillanatkép a motor ciklusvégén
  metrics.py       # gördülő KPI-k, élő↔várt eltérés
  actions.py       # Action-sor; az EGYETLEN írási út (a console_cmd-en át)
  apply.py         # a motor oldali ürítés a biztonságos ponton
  invariants.py    # a burok — L4-en is érvényes szabályok
  proposals.py     # Proposal séma + validátor
  journal.py       # krónika: data/conductor/decisions.jsonl
  undo.py          # visszavonás + „vissza az utolsó emberi állapotra"
  thread.py        # a szál életciklusa, watchdog, hiba→L-1 ejtés
  policies/        # health · lifecycle · optimize · risk · allocation
  agent/           # tools · prompts · runner (külön munkásszál, időkorlát)
  reports/         # daily · weekly · explain
```

---

## 14. Fázisok

| Fázis | Tartalom | Kockázat |
|---|---|---|
| **F0** ✅ | belépő-telemetria · élő KPI-tár · várt aktivitás · pillanatkép · **„miért nem kötött" jelentés** (v3.75.0–v3.76.0) | nulla (csak mérés) |
| **F1** ✅ | egészségőr · krónika (v3.77.0) · életciklus-létra + **árnyék-mód** (v3.78.0) · napi riport (v3.79.0) | nulla |
| **F2** ✅ | **javaslat-postaláda** (v3.80.0) · **Karmester fül** (v3.81.0) · **fej nélküli optimalizálás-sor** (v3.82.0) | alacsony |
| **F3** | életciklus-létra · kockázati karmester (L2→L3) | közepes |
| **F4** | LLM tanácsadó réteg · természetes nyelvű lekérdezés | alacsony (csak javasol) |
| **F5** | portfólió-elosztás, slot-keret | magas — utoljára |

**Az F0 nem halasztható.** Az L3/L4 cél miatt a krónika és a visszavonás nem
kényelmi funkció, hanem az önállóság feltétele — és a kapu-telemetria nélkül a
karmesternek nincs mit néznie.

---

## 15. Az F0 MEGVAN (v3.75.0 · v3.76.0)

A mérő réteg áll, és a rendszer először tud válaszolni a napi kérdésre:

```
tf> why EURUSD
EURUSD/wpr_sma — miért nem kötött ma?
  12 jel → 3 kötés (25%).
    • 6× (50%) — belépő-kapu blokkolt
    • 3× (25%) — nincs szabad kockázati slot
    kapuk: spread (5), tf_align (1)
  Aktivitás: 0.33 kötés/nap, a mentett mérés 2.00-t ígért (17%).
  Élő 90 nap: 30 kötés · PF 1.24 · +182.40
  ⚠ Csak 30 élő kötés — ennyiből a PF még zaj is lehet.
```

| Modul | Mit ad |
|---|---|
| `conductor/telemetry.py` | minden JEL kimenetele napi bontásban, ismétlődés-védelemmel |
| `conductor/metrics.py` | gördülő élő PF / expectancy / kötésszám a `trades.csv`-ből |
| `conductor/expectation.py` | mit ígért a mentett OOS mérés — és az élő ↔ várt eltérés |
| `conductor/snapshot.py` | a cella teljes állapota egy képben (a Kotta) |
| `conductor/report.py` | ebből emberi mondat |

A `why <pár> [stratégia]` a **közös parancsrétegben** van, tehát a konzol, a TUI
és a Telegram ugyanazt a választ adja. (A Telegramon elérhető: csak olvas.)

Két szabály, ami a számokba van kódolva:

* **A kis minta figyelmeztetése kötelező.** Minden cella viszi a kötésszámot és
  a belőle számolt bizonyíték-szorzót; a jelentés kimondja, ha a PF még zaj is
  lehet (a `core/quality.py` mért adata alapján).
* **Az élő ↔ várt eltérést SOSEM pénzben mérjük.** A backtest méretezése az
  akkori egyenleghez igazodott — csak arányok és ráták hasonlíthatók össze.

---

## 16. Előfeltétel: EGY parancsréteg — MEGVAN (v3.73.0 · v3.74.0)

A karmester akciói a `core/console_cmd.py`-on mennek. Ezért még a karmester előtt
helyre kellett állítani, hogy **minden felület ugyanott írjon**: a felület
korábban közvetlenül a `core.run_state`-be írt, a konzol / TUI / Telegram pedig a
parancsrétegen át. Két írási út — a karmester a harmadik lett volna.

A szabályok mostantól a `console_cmd.start_strategies()` / `stop_strategies()`
függvényekben laknak; a parancsok már csak argumentumot bontanak, a felület pedig
a környezetet köti be és megjelenít. A szétcsúszás három mérhető pontja:

| Szabály | Korábban | Most |
|---|---|---|
| Optimalizálás alatti indítás | csak a felület tiltotta | mindenhol tilt, indoklással |
| Hangolatlan (alapértelmezett paraméteres) indulás | csak a felület írta ki | mindenhol kiírja |
| Kivezetés-figyelmeztetés nyitott pozíciónál | csak a parancs kérdezett rá | a felület is rákérdez |

**A kötés-mód (`signal` ↔ `live`) is bekerült** (v3.74.0) — ez lesz a karmester
legfontosabb akciója az életciklus-létrán, és egyben a rendszer legdrágább
kapcsolója: a váltás után a motor a **következő jelnél valódi megbízást küld**.
Itt nem két forrás volt a baj (egyetlen író volt, a beállítás-ablak legördülője),
hanem hogy **semmilyen közös szabály nem állt mögötte**:

| | Korábban | Most (`console_cmd.set_trade_mode`) |
|---|---|---|
| Egy instrumentum mentése `signal` → `live` | **néma** — a Mentés bekapcsolta a pénzt, kérdés nélkül | nevesített megerősítés, csak a TÉNYLEGES váltásokra |
| Nem engedélyezett stratégia módja | némán hatástalan | eltárolja, de kimondja, hogy a motor addig nem futtatja |
| Nyitott pozíció sorsa | sehol nem szerepelt | kimondja: a motor tovább kezeli, a mód csak az ÚJ belépőkre vonatkozik |

Új parancs a konzolon és a TUI-n: `mode <pár> [stratégia] <live|signal>`.
**A Telegram szándékosan NEM kapja meg** — a `telegram_cmd.ENGEDETT` engedélyező
lista, amiben a `close` és a `quit` sincs benne; egy chatüzenetből bekapcsolható
valódi kötés ugyanabba a kategóriába tartozik.

Ugyanebben a körben egy azonos osztályú hiba is megszűnt: a *„a régi
`risky_mode`-ot szinkronban tartjuk (preset==risky)"* sor **négy** helyen élt
egymás mellett, háromnál néma `except: pass` mögött. Mostantól a
`rr_state.set_preset` / `cycle_preset` **mellékhatása** — vagyis a karmester (és
bárki más) sem tudja majd véletlenül kihagyni.

Az invariánst a `tests/test_command_layer_single_source.py` őrzi: forrás-szinten
is elbukik, ha a felület újra saját írási utat nyit.
