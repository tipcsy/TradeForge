"""SWING-SZINTEK ÉS SZERKEZET-TÖRÉS — a „Csilla beszállója" szabály KÖZÖS magja.

Egyetlen hely, ahonnan a kutató-labor (`tools/research/csilla_levels.py`, a
`csilla_variants`-on át) ÉS a stratégia-modul (`strategies/csilla.py`) ugyanazt
a szabályt hívja.

⚠ MIÉRT A `strategies/`-BEN, ÉS NEM A `core/`-BAN. A `.tfs` csomagoló a
stratégia SAJÁT segédmoduljait viszi magával (amiket `strategies.<x>`-ből
importál, mint az `ml_ai` → `ml_features`), a `core/`-t nem. Egy `core/`-ra
épülő stratégia máshol telepítve importhibával esne szét. Ez a modul tehát a
csilla segédmodulja — a labor is innen importál (a tools/ nem a keret). Ez nem
kényelem, hanem a paritás feltétele: a projekt háromszor tanulta meg, hogy egy
másodszor leírt szabály némán elcsúszik az elsőtől (lásd
`duplication-produced-its-own-bug`, `vacuous-parity-tests`).

⚠ Szándékosan NEM importál se `lab`-ot, se MetaTrader5-öt — csak numpy/pandas.

A SZABÁLY (a mérés előtt rögzítve, 2026-09-14; a vault „Csilla beszállója —
mérés" jegyzet 5. szakasza):

    1. SZINTEK: igazolt D1 fraktál-swing (k_d1 → ennyi nappal később ismert)
       és igazolt W1 fraktál-swing (k_w1). Csúcs = ellenállás, völgy = támasz.
       Egy szint az igazolásától él, amíg egy M15 gyertya át nem zár rajta
       (= esemény), vagy le nem jár (ttl_d1 / ttl_w1 nap). Minden szint egyszer.
    2. ESEMÉNY (M15): zárás egy élő ellenállás FÖLÖTT (+1) / támasz ALATT (−1).
       Címke: a D1-trend a törés előtt → folytatás / fordulat / nincs.
    3. BELÉPŐ (M1): a M15 gyertya zárása utáni `max_wait` M15-gyertyányi M1
       baron belül igazolt M1-swing az irány oldalán (a „zászló"), majd zárás
       azon túl. Egy eseményhez több belépő is tartozhat.
    4. STOP: `stop_atr` × ATR(M15) a törés gyertyáján (a mért, fix változat).

Az M1 az egyetlen bemenet: a M15 / D1 / W1 keretek belőle képződnek
(`resample`), így a labor és a stratégia ugyanazt a gyertyát látja.

⚠ EZ A MODUL CSAK AZT TARTALMAZZA, AMI FUT (takarítás: 2026-09-22). A Csilla
körül nyolc gépi olvasat készült, és mind MÉRVE ÉS BUKOTT; a kódjuk ezért
átkerült a `tools/research/csilla_variants.py` fagyasztott modulba, hogy a
szállított stratégia ne vigye magával a zsákutcákat:

  * `retest` és `fordulo` belépő-mód — az első 14 éves mérés 4 változata
    (−0,22 R), illetve a 09-22-i páros olvasat (−0,435 R, 6% találat);
  * H1 és H4 szint-fajta — a páros olvasat (H1→M15 −0,049, H1→M1 −0,167);
  * fibo célár (`fib_ext`, `leg`, `tp_abs`) — a mért változatban NINCS célár,
    és célár nélkül mindig jobb volt; a motor `tp_rr_ratio`-ból számol.

Ami MARAD a bukott kísérletekből: a SZERKEZETI stop (`stop_atr=None`, a törés
előtti utolsó ellenoldali M15-swing). Nem azért, mert nyert — hanem mert ez az
EGYETLEN nyitva hagyott kérdés (a bukások közös tényezője a szűk zászló-stop
volt), és a mérés-jegyzet kifejezetten erre tart fenn egy visszatérést.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ⚠ H4 A PLAFON — EZ DAYTRADE (a felhasználó kikötése, 2026-09-22). A jegyzet
# négy idősík-párt sorol fel (W1-D1, D1-H4, H1-M15, M15-M1); a felső kettő NEM
# használható, mert a felső tagjuk (W1, D1) a plafon fölött van. A `MAX_TF_MIN`
# nem dísz: a `parse_tf_pair` KIKÉNYSZERÍTI, tehát egy config-érték sem hozhatja
# vissza a napi/heti réteget — az egyszer már némán bent maradt.
#
# ⚠ EZ CSAK A CSILLÁRA VONATKOZIK. A plafon ennek a stratégiának a SAJÁT
# moduljában él, nem a keretben: más stratégia (wpr_sma, bollinger, …)
# tetszőleges idősíkot használhat. A daytrade-kikötés a csilla döntése.
MAX_TF_MIN = 240                          # H4
DEFAULTS = dict(tf_pair="H1-M15", hi_tf=60, lo_tf=15, k_hi=3, k_lo=3,
                max_wait=8, buffer_atr=0.2, min_sl_atr=1.0, stop_atr=1.5,
                # ── a 2. JELZES (pipa) a felso kereten ──────────────────────
                pipa_k=12,          # ennyi gyertyas ablakban keressuk a korrekcio tetejet
                pipa_w1=5,          # a teto elotti ennyi gyertya legalacsonyabb ZARASA = P0
                pipa_melyseg=1.0,   # (teto - P0) / ATR ennyi legyen legalabb
                pipa_min_tart=0.5,  # a jelzo gyertya tartomanya >= ennyi x ATR
                # ── az M15 BELEPOK ─────────────────────────────────────────
                korr_min=3,         # a korrekcio legalabb ennyi gyertya
                belepo_mod="varj_pirosra",   # varj_pirosra | leszuras | piros_zaras
                veg_mod="h1")       # h1 | emelkedo_teto | n_kotes
# A szint-fajták: k = fraktál félablak, ttl = élettartam NAPBAN. A H1/H4
# 2026-09-22-én kikerült (mérve és bukott) — a `csilla_variants` viszi tovább.
# ── segédek ──────────────────────────────────────────────────────────────────
def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """M1 → nagyobb TF (zárt gyertyák, a bar címkéje a NYITÓ ideje)."""
    agg = dict(open=("open", "first"), high=("high", "max"),
               low=("low", "min"), close=("close", "last"))
    o = df.resample(f"{minutes}min", label="left", closed="left").agg(**agg)
    return o.dropna(subset=["close"])


def atr(h, l, c, n):
    """ATR — a true range EGYSZERŰ mozgóátlaga (mint `lab.atr`)."""
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def pivots(h: np.ndarray, l: np.ndarray, k: int):
    """`(csucs, volgy)` bool tömbök a PIVOT baron. Szigorú: a csúcs magasabb a
    bal és a jobb k bar MINDEGYIKÉNÉL. A pivot csak k barral később ismerhető
    fel — a hívó tolja el."""
    hs, ls = pd.Series(h), pd.Series(l)
    bal_h = hs.rolling(k).max().shift(1).to_numpy()
    jobb_h = hs.rolling(k).max().shift(-k).to_numpy()
    bal_l = ls.rolling(k).min().shift(1).to_numpy()
    jobb_l = ls.rolling(k).min().shift(-k).to_numpy()
    csucs = (h > bal_h) & (h > jobb_h)
    volgy = (l < bal_l) & (l < jobb_l)
    return np.nan_to_num(csucs, nan=False), np.nan_to_num(volgy, nan=False)


# ── AZ ESEMÉNY: a felső idősík a SAJÁT utolsó swingjét töri ─────────────────
TF_PAIRS = {"H1-M15": (60, 15), "M15-M1": (15, 1)}
"""A kereskedési idősík-párok, amiket Csilla használ. A jegyzet négyet sorol
fel (W1-D1, D1-H4, H1-M15, M15-M1), de a felhasználó 2026-09-22-én kimondta,
hogy a két felsőt NEM használja — ezért csak ez a kettő létezik itt."""


def parse_tf_pair(spec) -> tuple:
    """`"H1-M15"` → `(60, 15)`. Ismeretlen vagy a plafon fölötti → az alap."""
    hi_lo = TF_PAIRS.get(str(spec or "").strip().upper().replace("_", "-"))
    if hi_lo is None or hi_lo[0] > MAX_TF_MIN:
        return TF_PAIRS["H1-M15"]
    return hi_lo


def with_tf_pair(P: dict | None) -> dict:
    """A paraméterek + a `tf_pair`-ből levezetett `hi_tf`/`lo_tf`. EGY hely,
    ahol az idősík-pár számmá válik — enélkül a hívók külön-külön fejtenék meg,
    és az egyikük elcsúszna."""
    P = {**DEFAULTS, **(P or {})}
    P["hi_tf"], P["lo_tf"] = parse_tf_pair(P.get("tf_pair"))
    return P


def own_swing_events(hi: pd.DataFrame, P: dict | None = None) -> list[dict]:
    """A FELSŐ IDŐSÍK SZERKEZET-TÖRÉSEI, kauzálisan.

    Ez a módszer magja: a felső idősík a SAJÁT utolsó igazolt swingjét töri át
    — nincs külső szint-réteg. Egy `i` barnál a „legutóbbi igazolt swing" az,
    aminek a pivotja ≤ i−k (a fraktál csak k barral később ismerhető fel).
    Törés: `close[i]` a csúcs FÖLÖTT (+1) vagy a völgy ALATT (−1). Minden swing
    egyszer törhet.

    `label` a törés ELŐTTI szerkezet: `folyt` (a törés a trend irányába megy),
    `ford` (ellene) vagy `nincs` — a két-két utolsó swingből (HH+HL / LL+LH).
    `stop_lvl` a törés előtti utolsó IGAZOLT ellenoldali swing (a szerkezeti
    stophoz; a fix ATR-stop ezt nem használja, de a létezése feltétel: enélkül
    a szerkezet még nem olvasható).

    ⚠ EZ VÁLTOTTA FEL A D1/W1 SZINT-RÉTEGET (2026-09-22). Az a réteg az én
    bevezetésem volt, nem a módszer: a felhasználó a jegyzetet újraolvasva
    kimondta, hogy Csilla EGY idősík-párt választ, és a felső a saját csúcsát
    töri. A szint-réteg kódja a `tools/research/csilla_variants`-ba került.
    """
    P = {**DEFAULTS, **(P or {})}
    k = P["k_hi"]
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    c = hi["close"].to_numpy(float)
    t_close = (hi.index + pd.Timedelta(minutes=P["hi_tf"])).to_numpy()
    pc, pv = pivots(h, l, k)
    sw_h: list[tuple[int, float]] = []
    sw_l: list[tuple[int, float]] = []
    tort_h = tort_l = -1          # az utoljára TÖRT swing indexe a listában
    out = []
    for i in range(k, len(c)):
        j = i - k                 # ez a bar MOST igazolódik pivotnak
        if pc[j]:
            sw_h.append((j, h[j]))
        if pv[j]:
            sw_l.append((j, l[j]))
        trend = 0
        if len(sw_h) >= 2 and len(sw_l) >= 2:
            hh = sw_h[-1][1] > sw_h[-2][1]
            hl = sw_l[-1][1] > sw_l[-2][1]
            trend = 1 if (hh and hl) else (-1 if (not hh and not hl) else 0)
        if sw_h and len(sw_h) - 1 > tort_h and c[i] > sw_h[-1][1]:
            out.append(dict(i=i, dir=1, level=sw_h[-1][1],
                            piv_hi=sw_h[-1][0],
                            stop_lvl=(sw_l[-1][1] if sw_l else np.nan),
                            label=("folyt" if trend == 1 else
                                   "ford" if trend == -1 else "nincs"),
                            t_close=t_close[i]))
            tort_h = len(sw_h) - 1
        if sw_l and len(sw_l) - 1 > tort_l and c[i] < sw_l[-1][1]:
            out.append(dict(i=i, dir=-1, level=sw_l[-1][1],
                            piv_hi=sw_l[-1][0],
                            stop_lvl=(sw_h[-1][1] if sw_h else np.nan),
                            label=("folyt" if trend == -1 else
                                   "ford" if trend == 1 else "nincs"),
                            t_close=t_close[i]))
            tort_l = len(sw_l) - 1
    return out


# ── A 2. JELZÉS: a korrekciót elnyelő gyertya („pipa") ──────────────────────
def pipa_events(hi: pd.DataFrame, P: dict | None = None) -> list[dict]:
    """A felső kereten: az a gyertya, ami ELNYELI a korrekciót — a korrekció
    KIINDULÁSI szintje (`P0`) alá (medve) vagy fölé (bika) zár, és ez az első
    ilyen zárás a korrekció teteje óta.

    Medve (short-setuphoz), a `t` gyertyán, `pipa_k` gyertyás ablakban:
      m  = az ablak legmagasabb csúcsa (a korrekció teteje)
      P0 = a legalacsonyabb ZÁRÁS az `[m − pipa_w1, m)` gyertyákon
      (high[m] − P0) / ATR(t) ≥ `pipa_melyseg`
      close[t] < P0, és az (m, t) közti zárások egyike sem < P0
      a `t` gyertya tartománya ≥ `pipa_min_tart` × ATR

    ⚠ NINCS SZÁR-ARÁNY. A `candle_lib.pipa` megköveteli, hogy a visszafordulás
    ne legyen GYORSABB, mint amit visszafordít (a ✓ rövid bal, hosszú jobb
    szára). A felhasználó 2026-09-23-án egy olyan gyertyára mutatott (Ger40 H1,
    01-28 08:00), ami 6 óra emelkedést töröl el EGGYEL — ár-feltétel teljesül,
    idő-feltétel nem. A szár-arány ezért itt nincs benne; a `candle_lib` szigorú
    változata érintetlen marad.

    Vissza: [{i, dir, P0, teto, t_close}] — `dir` −1 medve, +1 bika.
    """
    P = with_tf_pair(P)
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    c = hi["close"].to_numpy(float)
    a14 = atr(h, l, c, 14)
    t_close = (hi.index + pd.Timedelta(minutes=P["hi_tf"])).to_numpy()
    K, W1 = int(P["pipa_k"]), int(P["pipa_w1"])
    out = []
    for t in range(K + W1 + 1, len(c)):
        a = a14[t]
        if not (np.isfinite(a) and a > 0) or (h[t] - l[t]) < P["pipa_min_tart"] * a:
            continue
        for d, szelso, jobb in ((-1, np.argmax, h), (1, np.argmin, l)):
            m = t - K + int(szelso(jobb[t - K:t]))
            if m - W1 < 0 or m >= t:
                continue
            seg = c[m - W1:m]
            if not len(seg):
                continue
            P0 = float(np.min(seg)) if d < 0 else float(np.max(seg))
            if (jobb[m] - P0) * (-d) / a < P["pipa_melyseg"]:
                continue
            if (c[t] >= P0) if d < 0 else (c[t] <= P0):
                continue
            koz = c[m + 1:t]
            if len(koz) and ((koz < P0).any() if d < 0 else (koz > P0).any()):
                continue
            out.append(dict(i=t, dir=d, P0=P0, teto=float(jobb[m]),
                            t_close=t_close[t]))
    return out


def chain_setups(hi: pd.DataFrame, P: dict | None = None) -> list[dict]:
    """A TELJES H1-LÁNC (a felhasználó olvasata, 2026-09-23):

      1. JELZÉS  a felső keret áttöri a saját utolsó igazolt swingjét
      ÉRVÉNYES   amíg az ár nem zár a TÖRÉS ELŐTTI csúcs (medve) fölé — ez az
                 „új HH", ami a trendfordulót érvényteleníti. NINCS időkorlát.
      2. JELZÉS  az első `pipa_events` a törés IRÁNYÁBA, az érvényesség alatt.
                 Innen (a gyertya lezárása után) megyünk az alsó keretre.

    Vissza: [{i_break, dir, level, hatar, i_pipa, t_pipa_close, t_veg}] —
    `hatar` az érvénytelenítő ár, `t_veg` a setup vége (az érvénytelenítés
    ideje, vagy az adat vége)."""
    P = with_tf_pair(P)
    h = hi["high"].to_numpy(float)
    l = hi["low"].to_numpy(float)
    c = hi["close"].to_numpy(float)
    evs = own_swing_events(hi, P)
    pipak = pipa_events(hi, P)
    pipa_i = {}
    for e in pipak:
        pipa_i.setdefault(e["dir"], []).append(e)
    # ⚠ EGY ÚJABB, AZONOS IRÁNYÚ TÖRÉS LEVÁLTJA A RÉGI SETUPOT. Az
    # „időkorlát nincs" önmagában abszurd élettartamot ad: egy csúcs közelében
    # keletkezett lefelé törés addig él, amíg az ár a csúcs fölé nem zár — az
    # MÉRVE Ger40-en p99 = 14 939 felső gyertya (≈ 2 év), és emiatt évekkel
    # korábbi setupok generáltak ma belépőt. A leváltással a mért élettartam
    # median 13 / p99 54 / max 117 gyertya. Ez nem időkorlát: az új törés EGY ÚJ
    # szerkezet, ami magába olvasztja a régit.
    kov_tores = {}
    for e in evs:
        kov_tores.setdefault(e["dir"], []).append(e["i"])
    out = []
    for e in evs:
        d, i_b = e["dir"], e["i"]
        # a LEG szelso pontja: a torest megelozo szakasz csucsa/volgye. A
        # `piv_hi` a TORT swing pivotja; onnantol a toresig nezunk.
        szak = slice(int(e["piv_hi"]), i_b + 1)
        hatar = float(np.max(h[szak])) if d < 0 else float(np.min(l[szak]))
        # ervenytelenites: ZARAS a hataron tul
        veg = len(c)
        for z in range(i_b + 1, len(c)):
            if (c[z] > hatar) if d < 0 else (c[z] < hatar):
                veg = z
                break
        # ... vagy a kovetkezo AZONOS iranyu tores, ha az elobb jon
        _kov = next((b for b in kov_tores[d] if b > i_b), len(c))
        veg = min(veg, _kov)
        # az elso pipa a tores IRANYABA, meg az ervenyesseg alatt
        pipa = next((x for x in pipa_i.get(d, [])
                     if i_b < x["i"] < veg), None)
        # ⚠ A PIPA NÉLKÜLI TÖRÉS IS BENNE MARAD (`i_pipa=None`). A felület három
        # helyett ÖT pöttyöt mutat, és az egyik épp az, hogy „a törés megvolt, a
        # korrekció épül, a pipa még nincs" — ha ezeket kiszűrnénk, az a stádium
        # SOHA nem gyulladna ki. A belépő-generálás kihagyja őket.
        out.append(dict(i_break=i_b, dir=d, level=e["level"], hatar=hatar,
                        i_pipa=(pipa["i"] if pipa else None),
                        t_pipa_close=(pipa["t_close"] if pipa else None),
                        # ⚠ TZ-AWARE Timestamp marad. Egy tz-aware DatetimeIndex
                        # `.to_numpy()`-ja OBJECT tömb (Timestampekkel), nem
                        # datetime64 — egy naiv datetime64-gyel összehasonlítva
                        # a `searchsorted` TypeError-t dob.
                        t_veg=(hi.index[veg] if veg < len(c) else hi.index[-1]),
                        label=e["label"]))
    return out


def counter_entries(lo: pd.DataFrame, setups: list, P: dict | None = None,
                    spread: float = 0.0) -> pd.DataFrame:
    """Az ALSÓ keret belépői egy setuphoz: a counter-trend korrekciók törése.

    A korrekció = emelkedő aljak sorozata (medve setupnál), legalább `korr_min`
    gyertya. A trigger az, hogy az ár a korrekció alja alá megy; a BELÉPÉS módja
    `belepo_mod`:
      `varj_pirosra` — a trigger gyertyájától az első ELLENIRÁNYÚ SZÍNŰ gyertya
                       zárásán (medvénél az első piros). A felhasználó olvasata:
                       zöld gyertyába nem lépünk be, de a jelzés nem vész el.
      `leszuras`     — stop-megbízás a korrekció alján (a szín nem számít)
      `piros_zaras`  — CSAK az a gyertya, ami PIROS és az előző alja alá ZÁR
    A STOP a korrekció teteje + `spread`. Célár nincs.
    Korrekciónként EGY belépő.
    """
    P = with_tf_pair(P)
    o, h, l, c = (lo[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    idx = lo.index.to_numpy()
    mod, kmin = str(P["belepo_mod"]), int(P["korr_min"])
    rows = []
    for su in setups:
        if su.get("t_pipa_close") is None:
            continue                      # a törés megvolt, de a pipa még nem
        d = su["dir"]
        s0 = int(np.searchsorted(idx, su["t_pipa_close"], side="left"))
        s1 = int(np.searchsorted(idx, su["t_veg"], side="right"))
        utolso = -1
        for t in range(max(s0 + 2, 2), min(s1, len(c))):
            # a korrekcio tores: medvenel uj minimum az elozo gyertya alatt
            if (l[t] >= l[t - 1]) if d < 0 else (h[t] <= h[t - 1]):
                continue
            j = t - 1
            while j > 0 and ((l[j - 1] <= l[j]) if d < 0 else (h[j - 1] >= h[j])):
                j -= 1
            if t - j < kmin or t <= utolso:
                continue
            q = j + int((np.argmax(h[j:t]) if d < 0 else np.argmin(l[j:t])))
            teto = float(h[q]) if d < 0 else float(l[q])
            piros = (c[t] <= o[t]) if d < 0 else (c[t] >= o[t])
            if mod == "leszuras":
                be, i_be = float(l[t - 1] if d < 0 else h[t - 1]), t
            elif mod == "piros_zaras":
                if not (piros and ((c[t] < l[t - 1]) if d < 0 else (c[t] > h[t - 1]))):
                    continue
                be, i_be = float(c[t]), t
            else:                                   # varj_pirosra
                z = t
                while z < min(s1, len(c)) and ((c[z] > o[z]) if d < 0 else (c[z] < o[z])):
                    z += 1
                if z >= min(s1, len(c)):
                    continue
                be, i_be = float(c[z]), z
            sl = teto + spread * (-d)
            if (sl <= be) if d < 0 else (sl >= be):
                continue
            rows.append(dict(i=i_be, t=lo.index[i_be], dir=d, be=be, sl=sl,
                             sl_abs=abs(sl - be), korr=t - j,
                             i_break=su["i_break"], label=su["label"]))
            utolso = i_be
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── az M1 belépők egy eseményhez ─────────────────────────────────────────────
def lo_entries(ev: dict, start: int, end: int, h, l, c, atr1, pc, pv, k,
               P: dict) -> list[dict]:
    """[{i, sl_abs, level, piv, b}] — a zászló-törés belépői az [start, end]
    ablakban. `pc`/`pv` az M1 pivotjai (a pivot baron), `k` a félablak (az
    igazolás késése). `sl_abs`: az M1-alapú (első mérés) stop — a hívó
    felülírhatja.

    A SZABÁLY: az esemény iránya felőli első IGAZOLT M1-swing a „zászló" csúcsa;
    belépő az a gyertya, amelyik ezen TÚL zár. Az ablakban több belépő is lehet.

    ⚠ A `mode` PARAMÉTER MEGSZŰNT (2026-09-22). Két másik belépő-mód létezett
    itt — `retest` (visszaérés a tört szintre) és `fordulo` (a zászló utáni első
    igazolt ellenoldali swing) —, mindkettő mérve és bukva; a kódjuk a
    `tools/research/csilla_variants.py`-ban él tovább, és ONNAN hívja vissza ezt
    a függvényt a `break` ágra, hogy az élő szabályból ne legyen második példány.
    """
    d = ev["dir"]
    out = []
    i = start
    while i <= end:
        piv = -1
        while i <= end:
            j = i - k
            if j >= start and ((d > 0 and pc[j]) or (d < 0 and pv[j])):
                piv = j
                break
            i += 1
        if piv < 0:
            break
        lvl = h[piv] if d > 0 else l[piv]
        b = -1
        for t in range(i, end + 1):
            if (d > 0 and c[t] > lvl) or (d < 0 and c[t] < lvl):
                b = t
                break
        if b < 0:
            break
        ent = b
        if np.isfinite(atr1[ent]) and atr1[ent] > 0:
            a = atr1[ent]
            if d > 0:
                szel = min(l[piv:ent + 1])
                sl_abs = c[ent] - (szel - P["buffer_atr"] * a)
            else:
                szel = max(h[piv:ent + 1])
                sl_abs = (szel + P["buffer_atr"] * a) - c[ent]
            sl_abs = max(sl_abs, P["min_sl_atr"] * a)
            out.append(dict(i=ent, sl_abs=sl_abs, level=lvl, piv=piv, b=b))
            i = ent + 1
        else:
            i = b + 1
    return out


# ── A TELJES SZABÁLY: magas-keret kontextus + M1 belépők ────────────────────
def hi_context(hi: pd.DataFrame, P: dict | None = None) -> dict:
    """A FELSŐ keret KONTEXTUSA: szerkezet-törések + ATR. Csak akkor változik,
    ha új felső gyertya zár — a stratégia ezért gyorsítótárazhatja.

    ⚠ Nincs benne se szint-tábla, se külső trend-sorozat: a módszer EGY
    idősík-párt néz, a felső a saját swingjét töri (`own_swing_events`)."""
    P = with_tf_pair(P)
    a_hi = atr(hi["high"].to_numpy(float), hi["low"].to_numpy(float),
               hi["close"].to_numpy(float), 14)
    return dict(evs=own_swing_events(hi, P), a15=a_hi, P=P)


def entries_from(ctx: dict, m1: pd.DataFrame,
                 stop_atr: float | None = None) -> pd.DataFrame:
    """A belépők táblája az ALSÓ keret soraira egy `hi_context`-ből: `i` (alsó
    sorindex), `dir`, `sl_abs` (ÁRBAN), `atr15` (a törés felső gyertyáján),
    `label`, `piv`, `b`, `level`, `ev_i` (a felső esemény sorindexe).

    ⚠ CÉLÁR NINCS. Volt: `tp_abs` = a tört szinttől `fib_ext` × a láb hossza
    (a jegyzet fibo 138,2-je). A mérés minden változatban célár NÉLKÜL adott
    jobb eredményt (−0,013 vs −0,068 R), 14 éven EGYSZER sem ért el csomag
    10–20 R-t, és a motor amúgy is a `tp_rr_ratio`-ból számol messzi célárat
    (lásd `be-threshold-is-tp-relative`: rövid célár némán kikapcsolná a BE-t)."""
    P = ctx["P"]
    evs, a15 = ctx["evs"], ctx["a15"]
    if not evs or not len(m1):
        return pd.DataFrame()
    if stop_atr is None:
        stop_atr = P.get("stop_atr")
    h, l, c = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
    atr1 = atr(h, l, c, 14)
    atr1 = np.where(atr1 > 0, atr1, np.nan)
    pc, pv = pivots(h, l, P["k_lo"])
    start = np.searchsorted(m1.index.to_numpy(), [e["t_close"] for e in evs], side="left")
    # ⚠ AZ ABLAK ALSÓ GYERTYÁBAN. Eddig `max_wait * hi_tf` volt, ami CSAK akkor
    # helyes, ha az alsó keret M1 (1 perc). H1-M15 párnál a 8 felső gyertya
    # 8 × 60 / 15 = 32 alsó gyertya — a régi képlet 480-at adott volna, azaz
    # 5 napos ablakot a 8 órás helyett, némán.
    max_wait_lo = max(1, P["max_wait"] * P["hi_tf"] // max(1, P["lo_tf"]))
    rows = []
    n = len(c)
    t0 = m1.index[0]
    for e, s in zip(evs, start):
        if s >= n:
            continue
        # ⚠ Az ALSÓ keret ELEJE előtt zárt esemény kimarad: a `searchsorted` 0-t
        # adna rá, és egy rég lezárult ablak a keret első gyertyáira
        # csúszna (a motor lo-kerete a warmupnál kezdődik, a laboré nem).
        if e["t_close"] < t0:
            continue
        a = a15[e["i"]]
        if not (np.isfinite(a) and a > 0) or not np.isfinite(e["stop_lvl"]):
            continue
        end = min(n - 1, int(s) + max_wait_lo)
        for x in lo_entries(e, int(s), end, h, l, c, atr1, pc, pv, P["k_lo"], P):
            i = x["i"]
            d = e["dir"]
            sl_abs = (c[i] - (e["stop_lvl"] - P["buffer_atr"] * a)) if d > 0                 else ((e["stop_lvl"] + P["buffer_atr"] * a) - c[i])
            sl_abs = max(sl_abs, P["min_sl_atr"] * a)
            if stop_atr:
                sl_abs = float(stop_atr) * a
            rows.append(dict(i=i, dir=d, sl_abs=sl_abs,
                             atr15=a, label=e["label"],
                             piv=x["piv"], b=x["b"], level=x["level"], ev_i=e["i"]))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def entry_table(m1: pd.DataFrame, P: dict | None = None,
                stop_atr: float | None = None,
                hi: pd.DataFrame | None = None,
                lo: pd.DataFrame | None = None) -> pd.DataFrame:
    """A teljes szabály egy M1 keretből. `hi`/`lo` = None → a két keret az
    M1-ből képződik a `tf_pair` szerint (labor); megadva (a motor MT5-ös
    keretei) azokat használja.

    `stop_atr` = None → a szerkezeti swing-stop (a nyitva hagyott kérdés);
    szám → fix `stop_atr` × ATR(felső) — ez a mért változat."""
    P = with_tf_pair(P)
    if hi is None:
        hi = resample(m1, P["hi_tf"])
    if lo is None:
        lo = m1 if P["lo_tf"] <= 1 else resample(m1, P["lo_tf"])
    return entries_from(hi_context(hi, P), lo, stop_atr)


def signal_column(m1: pd.DataFrame, P: dict | None = None,
                  stop_atr: float | None = None, hi: pd.DataFrame | None = None,
                  ctx: dict | None = None):
    """A stratégia-motornak: `(sig, sl_abs, atr15)` tömbök az ALSÓ keret
    soraira — `sig` = +1/−1 a belépő baron (0 máshol), `sl_abs` a stop ÁRBAN,
    `atr15` a törés felső gyertyájának ATR-je. Ugyanaz, oszloppá téve.
    Ha egy bar két eseményből is belépő volna, az ELSŐ esemény számít."""
    n = len(m1)
    sig = np.zeros(n, dtype=np.int8)
    sl = np.full(n, np.nan)
    a15 = np.full(n, np.nan)
    if ctx is not None:
        et = entries_from(ctx, m1, stop_atr)
    else:
        et = entry_table(m1, P, stop_atr=stop_atr, hi=hi)
    if len(et):
        et = et.drop_duplicates("i", keep="first")
        ii = et.i.to_numpy(int)
        sig[ii] = et.dir.to_numpy(int)
        sl[ii] = et.sl_abs.to_numpy(float)
        a15[ii] = et.atr15.to_numpy(float)
    return sig, sl, a15
