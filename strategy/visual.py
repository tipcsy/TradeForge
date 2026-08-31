"""
Rajzolási primitívek a chart-vizualizációhoz (MT5-MENTES seam-modul).

A stratégia ezeket adja vissza a `visual_objects()`-ból; a `core.mt5_visual`
sorosítja őket az MT5 Common\\Files fájlba, ahonnan a `TradeForgeViz.mq5`
indikátor kirajzolja. Ez a modul SZÁNDÉKOSAN nem importál MetaTrader5-öt (mint a
base.py), hogy a stratégia és a tesztek MT5 nélkül is futtathatók legyenek.

Elv (mint a Cell): a stratégia SZEMANTIKUS színnevet ad; a sorosítás fordítja
"r,g,b" hármassá (az MQL5 `StringToColor` ezt érti). Minden objektumnak STABIL
neve van → az indikátor upsert-el (létrehoz vagy módosít), sosem töröl, így egy
objektum (pl. SMA-doboz) csak NŐ, amíg tart a feltétel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

# Minden objektum neve ezzel a prefixszel kezdődik — az indikátor ez alapján
# ismeri fel a SAJÁT objektumait (kézzel rajzolt objektumhoz nem nyúl).
PREFIX = "TFV_"

# Szemantikus szín-név → (R, G, B). A stratégia sosem ad hex/rgb kódot.
COLORS: dict[str, tuple[int, int, int]] = {
    "green":  (0, 170, 0),
    "lime":   (0, 255, 0),
    "red":    (220, 0, 0),
    "blue":   (0, 120, 255),
    "yellow": (240, 210, 0),
    "orange": (255, 140, 0),
    "white":  (255, 255, 255),
    "black":  (0, 0, 0),
    "gray":   (128, 128, 128),
    "muted":  (110, 110, 110),
    "magenta": (230, 40, 230),   # átlagár (null pont) — erős, jól elkülönülő
    "cyan":    (0, 220, 220),     # ráépítés-küszöb (ref_close)
}


def _rgb(color: str) -> str:
    r, g, b = COLORS.get(color, COLORS["white"])
    return f"{r},{g},{b}"


def _clean(text: str) -> str:
    """A szöveges mezőkből eltávolítjuk az elválasztót és a sortörést."""
    return text.replace(";", ",").replace("\n", " ").replace("\r", " ")


def _name(name: str) -> str:
    return name if name.startswith(PREFIX) else PREFIX + name


# A stratégia-tag elválasztója az objektum-névben: TFV_<strategy>@<eredeti_név>.
# Így az MQL5 indikátor egy `InpStrategy` input alapján szűrhet (a névre), és
# TÖBB stratégia objektumai UGYANABBAN a fájlban sem ütköznek (upsert stratégiánként).
STRAT_SEP = "@"


def tag_line(line: str, strategy: str) -> str:
    """Egy sorosított objektum-sort megjelöl a stratégia nevével (több-stratégiás
    viz: minden stratégia UGYANABBA a szimbólum-fájlba ír, az indikátor szűr).

    - Nevesített objektum (RECT/VLINE/TREND/ARROW/TEXT/LABEL): a NÉV mezőt
      namespace-eljük: `TFV_<eredeti>` → `TFV_<strategy>@<eredeti>`.
    - Névtelen sor (STATE/IND/ALERT): a stratégiát a TÍPUS UTÁN szúrjuk be
      (`STATE;<strat>;…`), mert az IND változó-hosszú szint-listája miatt a sor
      VÉGE nem egyértelmű.
    - CLEAR: érintetlen (direktíva).
    `strategy` üres → a sor változatlan (egy-stratégiás, régi viselkedés)."""
    if not strategy:
        return line
    typ, sep, rest = line.partition(";")
    if typ == "CLEAR":
        return line
    if typ in ("STATE", "IND", "ALERT", "TFONLY"):
        return f"{typ};{strategy};{rest}" if sep else f"{typ};{strategy}"
    fields = line.split(";")
    if len(fields) >= 2 and fields[1].startswith(PREFIX):
        fields[1] = PREFIX + strategy + STRAT_SEP + fields[1][len(PREFIX):]
    return ";".join(fields)


# ---------------------------------------------------------------------------
# Primitívek — mindegyik egy `;`-elválasztott sorrá sorosítható (.line()).
# ---------------------------------------------------------------------------

@dataclass
class Rect:
    """Telített téglalap (pl. SMA-irány doboz). Két sarok: (t1,p1)–(t2,p2)."""
    name: str
    t1: int
    p1: float
    t2: int
    p2: float
    color: str = "green"
    fill: bool = True

    def line(self) -> str:
        return ";".join([
            "RECT", _name(self.name),
            str(int(self.t1)), repr(float(self.p1)),
            str(int(self.t2)), repr(float(self.p2)),
            _rgb(self.color), "1" if self.fill else "0",
        ])


@dataclass
class VLine:
    """Függőleges vonal egy időpontnál (pl. M15 jelzés / M1 belépő jelölés)."""
    name: str
    t1: int
    color: str = "yellow"
    width: int = 1

    def line(self) -> str:
        return ";".join([
            "VLINE", _name(self.name),
            str(int(self.t1)), _rgb(self.color), str(int(self.width)),
        ])


@dataclass
class Trend:
    """Trendvonal (sugár nélkül): (t1,p1)–(t2,p2). Pl. 6-gyertyás TP/SL szint.
    style: MT5 vonalstílus (0=folytonos, 1=szaggatott, 2=pont, …) — a szaggatott
    CSAK width=1-nél látszik. A valós kötés SL/TP-jét szaggatottal különböztetjük
    meg a replay tömör szegmensétől."""
    name: str
    t1: int
    p1: float
    t2: int
    p2: float
    color: str = "green"
    width: int = 1
    style: int = 0

    def line(self) -> str:
        return ";".join([
            "TREND", _name(self.name),
            str(int(self.t1)), repr(float(self.p1)),
            str(int(self.t2)), repr(float(self.p2)),
            _rgb(self.color), str(int(self.width)), str(int(self.style)),
        ])


@dataclass
class Arrow:
    """Nyíl egy (idő, ár) ponton — pl. VALÓS kötés belépő-jelölése (MT5 deal). A
    jel-vonalaktól (VLine, replay) SZÁNDÉKOSAN eltérő alakzat: a betöltési áron ül a
    gyertyán, így egyből látszik, melyik jelből lett tényleges trade. `code` =
    Wingdings nyíl-kód (233 fel = BUY, 234 le = SELL)."""
    name: str
    t1: int
    p1: float
    code: int = 233
    color: str = "white"
    width: int = 1

    def line(self) -> str:
        return ";".join([
            "ARROW", _name(self.name),
            str(int(self.t1)), repr(float(self.p1)),
            str(int(self.code)), _rgb(self.color), str(int(self.width)),
        ])


@dataclass
class Text:
    """Chart-hoz (idő/ár) horgonyzott szöveg."""
    name: str
    t1: int
    p1: float
    text: str
    color: str = "white"
    fontsize: int = 9

    def line(self) -> str:
        return ";".join([
            "TEXT", _name(self.name),
            str(int(self.t1)), repr(float(self.p1)),
            _rgb(self.color), str(int(self.fontsize)), _clean(self.text),
        ])


@dataclass
class BarState:
    """Per-M15-gyertya SÁV-ÁLLAPOT a dedikált al-ablakhoz (TradeForgeBands).

    Nem klasszikus rajz-objektum (nincs neve/upsertje): a Python gyertyánként egy
    STATE sort ad, az indikátor SZÍNBUFFERBE (DRAW_COLOR_HISTOGRAM2) tölti — három
    fix magasságú sávban: szürke no-trade / zöld-piros trend / kék M15-ablak.

    Mezők:
      t:       nyers bar-idő (epoch, mint a copy_rates)
      notrade: 1 ha az adott gyertya no-trade órában van (különben 0)
      dir:     -1 SELL (piros), 0 nincs, 1 BUY (zöld) — az SMA-irány
      window:  1 ha aktív az M15 jelzési ablak, különben 0

    A no-trade maszkolást a KÜLDŐ (live_trader) végzi: no-trade gyertyánál
    notrade=1 ÉS dir=0, window=0 (így a Viz csak a szürkét mutatja). A stratégia
    az órákról nem tud → mindig notrade=0-t ad, a keret írja felül.

    `gate`: MIÉRT nem lépne be a motor ezen a gyertyán — a `core.gates` kulcsainak
    kódja (0 = nyitva, semmi nem zár). A KERET tölti (`live_trader.apply_gate_state`),
    a stratégia mindig 0-t ad.

    Miért kell: eddig a sáv azt mutatta, hogy a trend és az M15-ablak KÉSZEN áll —
    a chart tehát „belépőt ígért", miközben egy kapu némán zárt. (Mérve: UsaInd
    2026-06-12 délelőtt 6 M1-jelölt tüzelt, mind kiesett, mert az ATR 0,67–0,89×
    volt a mércének; a charton semmi nem árulta el.) Ugyanaz az aszimmetria, ami a
    BTCUSD-nél hetekbe került — lásd `core.gates` VOLATILITY megjegyzését.

    ⚠ Csak az ÉRVÉNYES kapuk kaphatnak kódot: a `none` hatású kapu SOSEM zár, tehát
    nem is villoghat (`gates.evaluate` konvenciója). A `display_only` (Volatilitás)
    viszont MINDIG érvényes, mert a szűrés a stratégia `bt_entry`-jében történik.

    `market_state`: GENERIKUS piac-állapot kód. **-1 = NINCS piac-sáv** (a piac-viz
    kikapcsolva vagy nincs kiválasztott piac-stratégia) → a TradeForgeBands NEM
    rajzol piac-sávot, és 3-sávos elrendezésre vált. **0..8 = besorolás-kód** (0 =
    besorolatlan). A KERET (a per-pár piac-stratégia) tölti fel — jelenleg a
    `core.regime` osztályozó kódjával, de bármely más piac-osztályozó ugyanebbe a
    mezőbe/sávba írhat. A színt a TradeForgeBands indikátor rendeli a kódhoz."""
    t: int
    notrade: int = 0
    dir: int = 0
    window: int = 0
    market_state: int = -1
    gate: int = 0

    def line(self) -> str:
        return ";".join([
            "STATE", str(int(self.t)), str(int(self.notrade)),
            str(int(self.dir)), str(int(self.window)),
            str(int(self.market_state)),
            str(int(self.gate)),
        ])


@dataclass
class TfOnly:
    """A strategia rajza CSAK ezen a chart-idosikon jelenjen meg (percben).

    ⚠ MIERT KELL. A viz-fajl egy szimbolum TELJES pillanatkepe, es MINDEN nyitott
    chart ugyanabbol olvas — a rajz tehat M1-en, M5-on es H1-en is megjelent.
    Egy H1-en szamolt Bollinger-szalag viszont egy M1-charton FELREVEZETO: nem
    az latszik, amit a dontés hasznal, csak ugyanaz a gorbe rossz felbontasban.

    A sor NEVTELEN (mint a STATE/IND/ALERT), a strategia-tag a TIPUS UTAN all
    (`tag_line`). `0` = nincs korlat (a regi viselkedes).

    ⚠ Visszafele kompatibilis: a regi indikator az ismeretlen sort atugorja, es
    ugy rajzol, ahogy eddig.
    """
    minutes: int

    def line(self) -> str:
        return ";".join(["TFONLY", str(int(self.minutes))])


@dataclass
class Indicator:
    """A stratégia által HASZNÁLT indikátor leírása — az indikátor (MQL5) a chartra
    rakja (ChartIndicatorAdd). Nem rajz-objektum: az indikátor külön kezeli.

    kind: "MA" | "WPR" ; timeframe: "M1"/"M15"/… ; period: egész ;
    levels: WPR jelentős szintek (extrém/trigger) — az al-ablakba vízszintes
    vonalként kerülnek. Az MA-hoz üres."""
    kind: str
    timeframe: str
    period: int
    levels: tuple = ()
    color: str = ""        # vonalszín (szemantikus név); "" = MT5 alapértelmezett

    def line(self) -> str:
        col = _rgb(self.color) if self.color else "-"
        parts = ["IND", self.kind, self.timeframe, str(int(self.period)), col]
        parts += [repr(float(x)) for x in self.levels]
        return ";".join(parts)


@dataclass
class Alert:
    """RIASZTÁS az MQL5 `Alert()`-en keresztül (nem rajz-objektum).

    A „csak jelzés" módú stratégia ezzel szól, hogy MOST kellene belépni — valódi
    megbízás nélkül (lásd `core.trade_mode`). Mivel a viz-fájl a kívánt állapot
    teljes PILLANATKÉPE (minden ciklusban újraíródik), a sor önmagában ismétlődne;
    ezért van `aid` (alert-id): az indikátor MEGJEGYZI az utoljára lefuttatottat, és
    csak ÚJ id-re riaszt. Az id-t úgy kell képezni, hogy egy jelre stabil legyen
    (pl. szimbólum+irány+gyertyaidő) — így pontosan egyszer szól.

    A sor a STATE/IND-hez hasonlóan névtelen: a stratégia-tag a TÍPUS UTÁN áll
    (`tag_line`), hogy az indikátor `InpStrategy` szerint szűrhessen."""
    aid: str
    text: str

    def line(self) -> str:
        return ";".join(["ALERT", _clean(self.aid), _clean(self.text)])


@dataclass
class Label:
    """Chart-SAROKHOZ pinnelt szöveg (pixel-koordináta, nem mozog az árral).
    Pl. a beállítás-táblázat. corner: 0=bal-fent, 1=jobb-fent, 2=bal-lent,
    3=jobb-lent. x/y: távolság a saroktól pixelben."""
    name: str
    text: str
    corner: int = 0
    x: int = 10
    y: int = 20
    color: str = "white"
    fontsize: int = 9

    def line(self) -> str:
        return ";".join([
            "LABEL", _name(self.name),
            str(int(self.corner)), str(int(self.x)), str(int(self.y)),
            _rgb(self.color), str(int(self.fontsize)), _clean(self.text),
        ])


# ── Összetett jelölő: EGY belépő teljes rajza ─────────────────────────────
def entry_marks(rec: dict, span_sec: int = 180) -> list:
    """Egy belépő-jel öt rajz-objektuma EGY rekordból.

    ⚠ MIÉRT ÖNÁLLÓ FÜGGVÉNY, és miért nem a stratégiában marad: a jelölőket
    KÉT út állítja elő — az aktuális ablak ÚJRASZÁMOLÁSA és a perzisztens
    `strategy.signal_journal` (az ablakon kívüli múlt). Ha a rajzolás két
    helyen élne, a két út csendben elcsúszna egymástól (ugyanaz az osztály,
    mint a viz-sáv és a warmup-mélység leletei). Így mindkettő UGYANEBBŐL a
    rekordból dolgozik, tehát bitre azonos sorokat ad.

    A rekord mezői: `t` (epoch), `d` ("BUY"/"SELL"), `e` belépő ár, `sl`, `tp`
    (elhagyható), `lab` (címke; elhagyható). `span_sec`: a vízszintes
    szegmensek fél-hossza a belépő körül (alap ±3 M1 gyertya).
    """
    t = int(rec["t"])
    buy = str(rec.get("d", "")).upper() == "BUY"
    # ⚠ AMI KIMARAD, AZ NE NÉZZEN KI KÖTÉSNEK. Egy páron egyszerre EGY pozíció
    # lehet, tehát a jelzések többsége élesben sosem lesz kötés (`mark_blocked`).
    # Az ilyen jelzés VÉKONY, SZÜRKE vonalat kap — látszik, hogy volt jel, de
    # nincs se címke, se belépő/SL/TP vonal, ami kötést sugallna.
    #
    # ⚠ A NÉV UGYANAZ (`m1sig_<t>`), tehát az MT5 upsert-je ÁTSZÍNEZI a meglévő
    # vonalat, ha egy jelzés később mégis kötővé válik (a blokkoló pozíció
    # kigörgült az ablakból). A fordított irány — kötőből kimaradó — csak
    # ablak-MÉLYÍTÉS vagy hangolás után fordulhat elő; olyankor a korábbi
    # SL/TP-vonalak a charton maradnak (az indikátor sosem töröl), amíg az MT5
    # újra nem indul. Ugyanaz az elévülés, mint egy hangolás utáni régi jelölőnél.
    if rec.get("skip"):
        return [VLine(name=f"m1sig_{t}", t1=t, color="muted", width=1)]
    col = "green" if buy else "red"
    entry = float(rec["e"])
    sl, tp = rec.get("sl"), rec.get("tp")
    t0, t_end = t - int(span_sec), t + int(span_sec)
    out = [VLine(name=f"m1sig_{t}", t1=t, color=col, width=2)]
    if rec.get("lab"):
        # A címke a nyereség-oldalon ül (BUY-nál a TP fölött, SELL-nél az SL
        # fölött) — ha nincs ár hozzá, a belépő szintjén, hogy ne vesszen el.
        anchor = (tp if buy else sl)
        out.append(Text(name=f"m1lbl_{t}", t1=t,
                        p1=float(anchor if anchor is not None else entry),
                        text=str(rec["lab"]), color=col, fontsize=9))
    out.append(Trend(name=f"m1entry_{t}", t1=t0, p1=entry, t2=t_end, p2=entry,
                     color="orange", width=2))
    if tp is not None:
        out.append(Trend(name=f"tp_{t}", t1=t0, p1=float(tp), t2=t_end,
                         p2=float(tp), color="green", width=2))
    if sl is not None:
        out.append(Trend(name=f"sl_{t}", t1=t0, p1=float(sl), t2=t_end,
                         p2=float(sl), color="red", width=2))
    return out


# ── MELYIK JELZÉSBŐL LESZ TÉNYLEGES KÖTÉS ─────────────────────────────────
def mark_blocked(recs: list, bars, strategy: str = "") -> int:
    """A rekordokba beírja, melyik jelzés maradna KI (`skip` = 1).

    ⚠ MIÉRT KELL. A chart eddig MINDEN jelzést ugyanúgy rajzolt ki — pedig egy
    páron egyszerre egy pozíció lehet, tehát a jelzések többsége élesben sosem
    lesz kötés. 2026-08-31-én a felhasználó egy öt-jeles csomóból hármat olvasott
    kötésnek, holott a motor kettőt kötött volna (és a csomó nettó +1,00 R volt,
    nem veszteséges). A rajz nem hazudott, csak nem mondta el a különbséget —
    ugyanaz a néma osztály, mint a viz-sáv és a warmup-mélység leleteinél.
    Mérve ugyanezen a napon: 10 jelzésből 1 kötés, 5-ből 2.

    A MODELL: a belépő utáni első bár, amelyik megüti az SL-t vagy a TP-t, zárja
    a pozíciót; amíg nyitva van, a következő jelzés kimarad. Ha egy báron belül
    mindkettő teljesül, a STOP nyer — ugyanaz a konzervatív konvenció, mint a
    kutató-labor szimulátorában (`tools/research/lab.simulate`), hogy a chart és
    a mérés ne mondjon mást ugyanarra a csomóra.

    ⚠ AMIT NEM TUD, ÉS AMERRE TÉVED:
      * A tiltás élesben a PÁRRA vonatkozik, nem a stratégiára. Ha egy MÁSIK
        stratégia tart nyitott pozíciót ugyanazon a páron, a „kötne" jelölő is
        kimaradhat — a zöld jelölők tehát FELSŐ becslést adnak.
      * A kilépés élesben lehet BE/trailing/kiszállás-jel is, nem csak SL/TP.
        Azok KORÁBBAN zárnak, tehát a valóságban a kötések száma csak nőhet.
      * `t` konvenció: a `trend_pullback`/`bollinger_squeeze` a belépő gyertya
        ZÁRÁSÁT írja a rekordba, a `wpr_sma` a NYITÁSÁT. Utóbbinál a kilépést
        kereső ablak a belépő gyertyát is tartalmazza (egy bár optimizmus).

    Visszaadja, hány jelzés kapott `skip` jelölést.
    """
    if not recs:
        return 0
    recs.sort(key=lambda r: int(r["t"]))
    for r in recs:                       # újraszámolás: a régi jelölés nem él túl
        r.pop("skip", None)
    try:
        _t = np.asarray(bars.index.asi8, dtype="int64") // 1_000_000_000
        hi = np.asarray(bars["high"], dtype=float)
        lo = np.asarray(bars["low"], dtype=float)
    except Exception:
        # ⚠ NEM néma: enélkül a chart visszaesne a régi képre (minden jelzés
        # kötésnek látszik), és pontosan azt a félreolvasást hozná vissza,
        # amiért ez a függvény készült.
        log.warning("a KÖTNE/KIMARAD jelölés kimarad (%s): a bárok nem "
                    "olvashatók — a chart MINDEN jelzést kötésként rajzol",
                    strategy or "?", exc_info=True)
        return 0
    if len(_t) < 2:
        return 0

    _nincs_sl = 0
    kimarad = 0
    foglalt = -1                          # eddig (epoch mp) tart a nyitott pozíció
    _VEGTELEN = 1 << 62
    for r in recs:
        t = int(r["t"])
        if t <= foglalt:
            r["skip"] = 1
            kimarad += 1
            continue
        if t < int(_t[0]):
            # Az ablak ELŐTTI jelzés (naplóból visszatöltött múlt): nem tudjuk
            # végigjátszani, tehát nem is állítunk róla semmit.
            continue
        sl, tp = r.get("sl"), r.get("tp")
        if sl is None:
            # Stop nélkül nem tudjuk, meddig tart a pozíció -> nem foglal le
            # semmit. A jelölőknek EGYÉBKÉNT IS van SL-vonala (teszt őrzi), ez
            # az ág adathiánynál fut.
            _nincs_sl += 1
            continue
        j = int(np.searchsorted(_t, t, side="left"))
        if j >= len(_t):
            foglalt = _VEGTELEN
            continue
        buy = str(r.get("d", "")).upper() == "BUY"
        h, l = hi[j:], lo[j:]
        m = (l <= float(sl)) if buy else (h >= float(sl))
        if tp is not None:
            m = m | ((h >= float(tp)) if buy else (l <= float(tp)))
        # ⚠ Ha a pozíció az ablak VÉGÉIG nyitva marad, az utána jövő jelzések
        # jogosan maradnak ki — élesben is nyitva volna.
        foglalt = int(_t[j + int(np.argmax(m))]) if bool(m.any()) else _VEGTELEN
    if _nincs_sl:
        log.warning("a KÖTNE/KIMARAD jelölés %d jelzésnél kimaradt (%s): "
                    "nincs SL a rekordban, így a pozíció hossza ismeretlen",
                    _nincs_sl, strategy or "?")
    return kimarad
