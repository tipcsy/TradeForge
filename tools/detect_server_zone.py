"""Egy bróker SZERVER-IDŐZÓNÁJÁNAK kimérése a saját gyertyáiból.

Miért kell (0029 „Több bróker egyszerre"): a program minden órája a kanonikus
(berlini) időben van (`core/broker_time.py`). Egy új bróker gyertyáit ezért át
kell váltani — ehhez a szerverének a zónáját ÉS a nyári átállási szabályát
pontosan kell tudni. A bróker ezt nem közli, a „GMT+2" felirat pedig
kétértelmű (EU vagy USA szerint vált?). Mérni kell.

⚠ AZ ELSŐ MÓDSZER HIBÁS VOLT (2026-09-28), ÉS EZ A LECKE. A heti nyitást
(„a devizapiac NY 17:00-kor nyit") vettem horgonynak — az ActivTrades-en ez
90%-os konzisztenciát adott a Berlinre és 97%-ot a „NY+6"-ra, vagyis az
ellenkezőjét mondta annak, amit a `gates/sessions.py` kimért. A valóság: ez a
bróker minden héten a SAJÁT ÉJFELÉN (hétfő 00:00 szerver) nyit, tehát a heti
nyitás a bróker óráját méri önmagához — bármelyik zóna-feltevés ugyanezt az
adatot adná. A horgonynak a VALÓDI VILÁGÓRÁHOZ kell kötődnie.

⚠ A MÁSODIK IS GYENGE VOLT: a nyitás-PERC tüskéje. A 08:30-as amerikai hírek
tüskéje pontosan egy órára van a 09:30-as nyitástól, és egy órával elcsúszott
zóna így „találatot" kapott (a szintetikus teszt fogta meg; a valódi adaton
szerencsére nem döntött rosszul).

A MÉRÉS: a tőzsdenyitás utáni TARTÓS volatilitás-lépcső — az átlagos M1-
tartomány a nyitás utáni 30 percben / a nyitás előtti 30 percben (log-arány),
a piac SAJÁT helyi idejében: NYSE 09:30 New York, London 08:00 London. A hír
egy perc, a nyitás fél óra. Minden jelölt zónával átváltjuk a gyertyákat:
  • rossz ELTOLÁS → a lépcső kiesik az ablakból;
  • rossz nyári SZABÁLY (EU vs USA) → az évi ~4 eltérő héten egy órával mellé
    esik — ezt KÜLÖN oszlop mutatja, mert erről csak azok a hetek döntenek.
Kontroll az ActivTrades-en (UsaTec, eltérő hetek): a NYSE-tüske 14:30 szervernél
(normál héten 15:30), a Ger40 frankfurti nyitása mindkettőben 09:00 → Berlin.

⚠ CSAK TŐZSDEINDEXEN MEGBÍZHATÓ. Mérve (2026-09-28, ActivTrades):
    UsaTec  lépcső 0,70, eltérő heteken Berlin +0,63 / NY+6 −0,10   → Berlin ✔
    Ger40   lépcső 0,58, eltérő heteken Berlin +0,51 / NY+6 −0,09   → Berlin ✔
    EURUSD  lépcső 0,36 → „Europe/London"  ✘ (MAGABIZTOSAN rossz!)
    GOLD    lépcső 0,18 → „UTC+1"          ✘
A devizán/aranyon nincs EGY éles nyitás (Frankfurt, London, New York egymás
után emeli a forgalmat), a lépcső elkenődik. Ezért a gyenge lépcsőre
(< MIN_LEPCSO) az eszköz NEM ad választ — minden brókernek van amerikai vagy
német indexe, azt kell megadni.

Használat:
    python tools/detect_server_zone.py                       # data/m1/UsaTec.parquet
    python tools/detect_server_zone.py path/to/USTEC.parquet path/to/EURUSD.parquet
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core import broker_time as BT

# A VALÓDI VILÁGÓRA horgonyai: tőzsdenyitások a SAJÁT helyi idejükben. A mérce
# a nyitás utáni TARTÓS volatilitás-lépcső (30 perc utána / 30 perc előtte),
# NEM egy perc tüskéje: a 08:30-as hír-tüske egy óra távolságra van a 09:30-as
# nyitástól, és egy órával elcsúszott zóna a pontszerű mércén „találatot"
# kapott (a szintetikus teszt fogta meg). A hír egy perc, a nyitás fél óra.
# A két horgony KÜLÖNBÖZŐ nyári szabályt követ (USA / EU) — ez élesíti a döntést.
HORGONYOK = (("America/New_York", 9 * 60 + 30),      # NYSE nyitás
             ("Europe/London", 8 * 60))               # londoni nyitás
LEPCSO_PERC = 30
MIN_LEPCSO = 0.45                    # alatta nem éles a nyitás → nincs ítélet

JELOLTEK = ([BT.ServerZone(z, 0) for z in ("Europe/London", "Europe/Berlin",
                                           "Europe/Athens", "Europe/Moscow")]
            + [BT.ServerZone("UTC", k) for k in range(0, 4)]
            + [BT.ServerZone("America/New_York", k) for k in (6, 7, 8)])


def _elteres_napok(nap_utc_del: pd.DatetimeIndex) -> np.ndarray:
    """Igaz azokon a napokon, amikor az USA és Európa nyári ideje ELTÉR."""
    ny = nap_utc_del.tz_convert("America/New_York")
    be = nap_utc_del.tz_convert("Europe/Berlin")
    return np.array([bool(a.dst()) != bool(b.dst()) for a, b in zip(ny, be)])


def _lepcso(utc: pd.DatetimeIndex, rng: np.ndarray, nap_mask, zona: str,
            perc0: int) -> float:
    """log( átlag tartomány [p0, p0+30) / átlag tartomány [p0-30, p0) ), a
    horgony-zóna helyi idejében, hétköznap; `nap_mask` szűkíthet (eltérő hetek)."""
    lok = utc.tz_convert(zona)
    perc = np.asarray(lok.hour * 60 + lok.minute)
    hk = np.asarray(lok.dayofweek < 5) & nap_mask
    ut = hk & (perc >= perc0) & (perc < perc0 + LEPCSO_PERC)
    el = hk & (perc >= perc0 - LEPCSO_PERC) & (perc < perc0)
    if ut.sum() < 50 or el.sum() < 50 or rng[el].mean() <= 0:
        return np.nan
    return float(np.log(rng[ut].mean() / rng[el].mean()))


def tuske(idx: pd.DatetimeIndex, tartomany: np.ndarray, sz: BT.ServerZone,
          horgony=HORGONYOK) -> dict:
    """A jelölt zóna szerint a tőzsdenyitások volatilitás-lépcsője (log-arány,
    átlag a horgonyokon) — minden napon, és KÜLÖN az eltérő heteken.
    A helyes zónánál a legnagyobb: rossz eltolásnál a lépcső kívül esik az
    ablakon, rossz nyári szabálynál az eltérő heteken elcsúszik."""
    utc = BT.index_to_utc(idx, sz)
    ny = utc.tz_convert("America/New_York")
    be = utc.tz_convert("Europe/Berlin")
    # nyari ido = a helyi eltolas nagyobb a teli (standard) eltolasnal — vektoros
    u0 = utc.tz_localize(None)
    ny_dst = (ny.tz_localize(None) - u0) != pd.Timedelta(hours=-5)
    be_dst = (be.tz_localize(None) - u0) != pd.Timedelta(hours=1)
    elter = np.asarray(ny_dst != be_dst)
    minden = np.ones(len(idx), bool)
    l_all = [_lepcso(utc, tartomany, minden, z, p) for z, p in horgony]
    l_el = [_lepcso(utc, tartomany, elter, z, p) for z, p in horgony]
    return {"zona": str(sz), "lepcso": float(np.nanmean(l_all)),
            "elteres_heteken": float(np.nanmean(l_el)) if np.isfinite(l_el).any() else np.nan,
            "elteres_nap": int(pd.Series(ny.normalize()[elter]).nunique())}


def jelenlegi_eltolas(sz: BT.ServerZone, most: _dt.datetime | None = None) -> float:
    """A zóna szerinti szerver − UTC másodpercben, MOST."""
    most = most or _dt.datetime.now(_dt.timezone.utc)
    fal = BT.utc_to_wall(most, sz)
    return (fal - most.replace(tzinfo=None)).total_seconds()


def felismer(df: pd.DataFrame, horgony=HORGONYOK,
             mert_eltolas: float | None = None) -> pd.DataFrame:
    rng = (df["high"] - df["low"]).to_numpy(float)
    T = pd.DataFrame([tuske(df.index, rng, sz, horgony) | {"_sz": sz}
                      for sz in JELOLTEK])
    if mert_eltolas is not None:
        T["eltolas_egyezik"] = [abs(jelenlegi_eltolas(sz) - mert_eltolas) < 60
                                for sz in T._sz]
    return T.sort_values("lepcso", ascending=False).reset_index(drop=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fajlok = [Path(a) for a in args] or [ROOT / "data" / "m1" / "UsaTec.parquet"]
    mert = None
    f_off = ROOT / "data" / "server_offset.json"
    if f_off.exists():
        try:
            mert = float(json.loads(f_off.read_text(encoding="utf-8"))["offset_sec"])
        except Exception:                                     # noqa: BLE001
            mert = None
    for f in fajlok:
        if not f.exists():
            print(f"{f}: nincs ilyen fajl"); continue
        df = pd.read_parquet(f, columns=["high", "low"])
        T = felismer(df, mert_eltolas=mert)
        print(f"\n=== {f.name}: {df.index[0]:%Y-%m-%d} .. {df.index[-1]:%Y-%m-%d}, "
              f"horgonyok: NYSE 09:30 NY, London 08:00 ===")
        print(T.drop(columns=["_sz"]).head(6).to_string(
            index=False, float_format=lambda v: f"{v:.2f}"))
        b, m = T.iloc[0], T.iloc[1]
        print(f"-> LEGVALOSZINUBB: {b.zona}  (lepcso {b.lepcso:.2f}, az elteres heteken "
              f"{b.elteres_heteken:.2f}; a masodik {m.zona} {m.lepcso:.2f} / "
              f"{m.elteres_heteken:.2f})")
        print("   " + itelet(T))


def itelet(T: pd.DataFrame) -> str:
    """Szöveges ítélet — vagy annak kimondása, hogy nincs."""
    b, m = T.iloc[0], T.iloc[1]
    if b.lepcso < MIN_LEPCSO:
        return (f"!! NEM ELDONTHETO: a nyitasi lepcso gyenge ({b.lepcso:.2f} < "
                f"{MIN_LEPCSO}) — ez nem tozsdeindex? Adj meg egy US vagy nemet indexet.")
    if b.lepcso - m.lepcso < 0.05 and b.elteres_heteken - m.elteres_heteken < 0.10:
        return "!! NEM ELDONTHETO: az elso ket jelolt kozel azonos — hosszabb minta kell."
    return f"OK: {b.zona}"


if __name__ == "__main__":
    main()
