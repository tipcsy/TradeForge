"""VISSZATEKINTŐ STOP-TANULMÁNY — „ha látjuk a jövőt, hová tegyük az SL-t?"

A felhasználó kérdése (2026-09-19): *„Mit tekintünk jó beszállónak? Mit
tekintünk sikeres TRADE-nek? Mondjuk most látunk előre, látjuk a trendeket:
nézzük meg, milyen logika alapján érdemes csak az SL-t elhelyezni, hogy belépve
a max TP-t el tudjuk érni. Erre kellene válaszolni statisztikai számokkal."*

A KÉRDÉS FORMALIZÁLVA. Egy belépő pályájából a stop CSAK EGY dolgot csinál:
LEVÁG. Ezért pontosan két számon keresztül hat:

    R(s) = (az az elérhető nyereség, ameddig a stop ütése ELŐTT eljutottunk) / s

  (a) minél szűkebb az `s`, annál nagyobb az osztó-hatás (jobb R ugyanazért a
      mozgásért), és annál gyakrabban vág le a pálya legjobb része ELŐTT;
  (b) minél tágabb, annál biztosabban „kibírjuk" a mozgást, de ugyanaz a
      pontokban mért nyereség kevesebb R.

A visszatekintő mérés ezt a cserearányt teszi láthatóvá. Három fogalmat vezet
be, és MINDHÁRMAT megméri:

  ELÉRHETŐ (available)  = mfe_s / s     — amit a pálya adott, a stop mellett
  MEGSZERZETT (captured)= a valódi szabály R-je
  KIHOZATAL             = megszerzett / elérhető

⚠ EZ A DEFINÍCIÓ VÁLASZOL A „MIT TEKINTÜNK JÓ BELÉPŐNEK" KÉRDÉSRE IS.
Jó belépő = nagy ELÉRHETŐ. Jó kiszállás = nagy KIHOZATAL. Sikeres trade =
pozitív NETTÓ R (spread + jutalék + swap után). A három külön mérhető, és
külön is romlik el — ezért kell szétválasztani: az eddigi mérések azért
mondtak ellentmondó dolgokat, mert egyetlen számba (R/kötés) sűrítették
mindhármat.

⚠⚠ A CSAPDA, AMIT KI KELL MONDANI. R-ben mérve a TÁGABB STOP MECHANIKUSAN
JOBBNAK LÁTSZIK: a fix költség (spread + jutalék + swap) pontban állandó, tehát
R-ben `költség/s` — vagyis automatikusan csökken, ahogy `s` nő. Ha valaki csak
az R/kötés görbét nézi, arra jut, hogy „a stop legyen végtelen". Ezért a riport
MINDIG kiírja a bruttó és a nettó görbét is, és a null-piaci összehasonlítást:
az igazi kérdés nem az, hogy melyik `s` ad nagyobb R-t, hanem hogy a valódi
piac ad-e TÖBBET ugyanazon az `s`-en, mint egy azonos volatilitású, szerkezet
nélküli piac (`sl_paths.szintetikus`).

⚠ ELŐRE RÖGZÍTETT ELFOGADÁSI FELTÉTEL (a mérés előtt leírva):
egy stop-szabály akkor jobb a fix 1,5 ATR-nél, ha
  (1) a nettó R/kötés különbsége napra klaszterezett t >= 2,
  (2) az évek >= 60%-ában pozitív a különbség,
  (3) legalább 3 instrumentumon pozitív,
  (4) ÉS a VALÓDI piacon mért előnye nagyobb, mint a NULL-piacon mért előnye
      (különben nem szerkezetet fogtunk meg, csak a volatilitás alakját).

Futtatás:

    python tools/research/sl_oracle.py --symbols Ger40 UsaTec --minta 20000
    python tools/research/sl_oracle.py --symbols GOLD --nincs-null
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(ROOT))
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import argparse

import numpy as np
import pandas as pd

import core.applog as _applog
_applog.harden_console()   # cp1250 konzol: a ⚠ / ≥ / → ne dobjon UnicodeEncodeError-t

import lab
import seq_stat as ST
import sl_paths as SP
from core import trade_costs as TC

S_FOKUSZ = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
C_FOKUSZ = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
REFERENCIA_S = 1.5           # a projekt bevett stopja (outcomes.SL_ATR)
VAGAS = "2023-01-01"


# ───────────────────────────────────────────────────────────── költség ──
class Koltseg:
    """Jutalék + swap R-ben, kötésenként — a `core.trade_costs` számaival.

    A swap csak akkor terheli a kötést, ha a KILÉPÉS átlépi a szerver-éjfélt;
    a háromszoros napot a config `swap_3x_weekday` kulcsa adja. A `pv1_point`
    hiányában a költség 0, és a riport ezt kiírja — mert akkor a számok
    BRUTTÓK, és a `README.md` szerint a swap egymaga nagyobb, mint az eddig
    mért teljes él.
    """

    def __init__(self, sym: str, K: pd.DataFrame, h: int):
        cfg = lab.PAIRS.get(sym, {})
        self.ps = float(cfg.get("point_size", 0) or 0)
        pv1 = float(cfg.get("pv1_point", 0) or 0)
        self.ervenyes = pv1 > 0 and self.ps > 0
        self.atr_pts = (K["atr"].to_numpy(float) / self.ps if self.ps > 0
                        else np.full(len(K), np.nan))
        if not self.ervenyes:
            self.comm_pts = 0.0
            self.swap_pts = np.zeros(len(K))
            self.ejfelig = np.full(len(K), 10 ** 9)
            return
        self.comm_pts = TC.commission_usd(1.0, cfg) / pv1
        ido = pd.DatetimeIndex(K["ido"])
        self.ejfelig = (1440 - (ido.hour * 60 + ido.minute)).to_numpy()
        nap = (ST.ns(ido) // (86400 * 10 ** 9)) + 1          # az átlépett éjfél napja
        hetnap = (nap + 3) % 7
        r3 = cfg.get("swap_3x_weekday", TC.DEFAULT_3X_WEEKDAY)
        suly = np.where(hetnap == (r3 if r3 is not None else -1), 3.0, 1.0)
        d = K["dir"].to_numpy(int)
        per_ej = np.where(d > 0, float(cfg.get("swap_long_per_lot", 0) or 0),
                          float(cfg.get("swap_short_per_lot", 0) or 0))
        self.swap_pts = -(per_ej * suly) / pv1              # pozitív = költség

    def r(self, s: float | np.ndarray, kilep_bar: np.ndarray) -> np.ndarray:
        """A költség R-ben, `s` ATR-es stop és adott kilépési bar mellett."""
        pts = self.comm_pts + np.where(kilep_bar >= self.ejfelig,
                                       self.swap_pts, 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            return pts / (np.asarray(s, float) * self.atr_pts)


# ─────────────────────────────────────────────────────────── kimenetek ──
def cella(K: pd.DataFrame, s: float, c: float | None, h: int,
          k: Koltseg | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Egy (stop, cél) cella kötésenkénti R-je. `c=None` -> NINCS célár.

    Konvenció (a motoré): azonos baron a STOP nyer; ha egyik sem teljesül, a
    tartás végén záróáron lépünk ki.
    """
    sb = K[f"s{s}"].to_numpy(int)
    cb = (K[f"c{c}"].to_numpy(int) if c is not None
          else np.full(len(K), h, dtype=int))
    nyer = cb < sb
    veszt = (sb <= cb) & (sb < h)
    r = np.where(nyer, (c / s if c is not None else 0.0),
                 np.where(veszt, -1.0, K["zaro"].to_numpy(float) / s))
    kilep = np.minimum(np.minimum(sb, cb), h)
    if k is not None:
        r = r - k.r(s, kilep)
    return r, kilep


def _sor(r: np.ndarray, K: pd.DataFrame, alap: float | None = None) -> dict:
    nap = ST.ns(pd.DatetimeIndex(K["ido"]).floor("D"))
    mu, t, n = ST.t_klaszter(r, nap)
    ar, evek = ST.evek_pozitiv(r, pd.DatetimeIndex(K["ido"]), alap or 0.0)
    return {"R": mu, "t_nap": t, "n": n, "evek_poz": ar, "evek": evek}


# ───────────────────────────────────────────────────────────── riportok ──
def r1_mennyi_fajdalom(K: pd.DataFrame) -> pd.DataFrame:
    """1. Mennyit kell elviselni ahhoz, hogy a pálya LEGJOBB pontjáig eljuss?"""
    sm = K["s_min"].to_numpy(float)
    print("\n=== 1. A MINIMÁLIS ELÉGSÉGES STOP (s_min) ===")
    print("   „mekkora stop kell ahhoz, hogy a legjobb pontig egyáltalán eljuss")
    print("    — visszatekintve, tehát ez a FELSŐ korlát, nem szabály\"")
    kv = np.nanpercentile(sm, [10, 25, 50, 75, 90, 95])
    print("   percentilisek (ATR):  " + "  ".join(
        f"p{p}={v:.2f}" for p, v in zip([10, 25, 50, 75, 90, 95], kv)))
    sorok = []
    for s in S_FOKUSZ:
        eleg = sm <= s
        sorok.append({"stop_ATR": s, "eleg_%": 100 * float(np.nanmean(eleg)),
                      "atlag_mfe": float(np.nanmean(K["mfe"][eleg])) if eleg.any() else np.nan,
                      "atlag_mfe_s": float(np.nanmean(K[f"mfe_s{s}"])),
                      "elerheto_R": float(np.nanmean(K[f"mfe_s{s}"]) / s)})
    t = pd.DataFrame(sorok)
    print(t.to_string(index=False, float_format=lambda v: f"{v:9.3f}"))
    print("   `eleg_%`  : ennyi kötésnél elég tág a stop a LEGJOBB pontig")
    print("   `elerheto_R`: E[mfe_s]/s — a tökéletes kiszállás FELSŐ korlátja R-ben")
    return t


def r2_felulet(K: pd.DataFrame, h: int, k: Koltseg) -> pd.DataFrame:
    """2. A valódi (stop, cél) felület — elsőként-érintés szerint."""
    print("\n=== 2. A (STOP, CÉL) FELÜLET — valódi, nem visszatekintő ===")
    sorok = []
    for s in S_FOKUSZ:
        for c in list(C_FOKUSZ) + [None]:
            if c is not None and c / s > 8:
                continue
            r_b, kilep = cella(K, s, c, h, None)
            r_n, _ = cella(K, s, c, h, k)
            d = _sor(r_n, K)
            sb = K[f"s{s}"].to_numpy(int)
            cb = (K[f"c{c}"].to_numpy(int) if c is not None
                  else np.full(len(K), h, int))
            sorok.append({"stop_ATR": s, "cel_ATR": (c if c is not None else np.nan),
                          "RR": (c / s if c is not None else np.nan),
                          "nyero_%": 100 * float((cb < sb).mean()),
                          "R_brutto": float(np.nanmean(r_b)), "R_netto": d["R"],
                          "t_nap": d["t_nap"], "evek_poz": d["evek_poz"]})
    t = pd.DataFrame(sorok)
    print(t.sort_values("R_netto", ascending=False).head(12)
          .to_string(index=False, float_format=lambda v: f"{v:9.3f}"))
    print("   (`cel_ATR` = NaN -> NINCS célár: a tartás végéig futni hagyva)")
    return t


def r3_kihozatal(K: pd.DataFrame, h: int, k: Koltseg) -> None:
    """3. ELÉRHETŐ vs MEGSZERZETT — a belépő és a kiszállás szétválasztása."""
    print("\n=== 3. ELÉRHETŐ / MEGSZERZETT / KIHOZATAL ===")
    sorok = []
    for s in S_FOKUSZ:
        elerheto = float(np.nanmean(K[f"mfe_s{s}"]) / s)
        for c0 in (2.0 * s, None):
            c = (min(SP.C_RACS, key=lambda x: abs(x - c0))
                 if c0 is not None else None)
            nev = f"cél {c / s:.1f}R" if c is not None else "nincs cél"
            r, _ = cella(K, s, c, h, k)
            megszerzett = float(np.nanmean(r))
            sorok.append({"stop_ATR": s, "kiszallas": nev,
                          "elerheto_R": elerheto, "megszerzett_R": megszerzett,
                          "kihozatal_%": (100 * megszerzett / elerheto
                                          if elerheto > 0 else np.nan)})
    print(pd.DataFrame(sorok).to_string(index=False,
                                        float_format=lambda v: f"{v:9.3f}"))
    e = K["mfe"].mean() / max(1e-9, K["mae"].mean())
    print(f"   e-arány (MFE/MAE a teljes tartáson): {e:.3f}   "
          f"(1,000 = a belépő nem hordoz irányt)")
    print(f"   a kötések {100 * (K.mfe > K.mae).mean():.1f}%-ánál ment többet a "
          f"jó irányba")


def r4_szabalyok(sym: str, m1, atr, K: pd.DataFrame, h: int,
                 k: Koltseg) -> pd.DataFrame:
    """4. STOP-SZABÁLYOK — fix, szerkezeti, feltételes. Ez a tulajdonképpeni kérdés.

    Mindegyik szabály UGYANAZT a kiszállást kapja (nincs célár, a tartás végéig),
    hogy a különbség tisztán a STOP elhelyezéséből jöjjön.
    """
    print("\n=== 4. STOP-SZABÁLYOK ÖSSZEHASONLÍTÁSA (azonos kiszállás mellett) ===")
    ido = pd.DatetimeIndex(K["ido"])
    kereso = np.asarray(ido < pd.Timestamp(VAGAS, tz=ido.tz))
    d = K["dir"].to_numpy(int)

    # szerkezeti stop: a legutóbb IGAZOLT swing mögé, negyed ATR ráhagyással
    szerk = np.where(d > 0, K.get("swing_ala", np.nan), K.get("swing_fole", np.nan))
    szerk = np.clip(np.asarray(szerk, float) + 0.25, 0.4, 6.0)

    # feltételes stop: a KERESŐ szakaszon tanult tipikus s_min a jellemző-rekeszben
    rek = pd.Series(pd.cut(K.get("atr_arany", pd.Series(np.nan, index=K.index)),
                           bins=[-np.inf, .7, .9, 1.1, 1.4, np.inf]).astype(str)
                    ) + "|" + pd.Series(ido.hour // 4, index=K.index).astype(str)
    tan = (pd.Series(K["s_min"].to_numpy(float))[kereso]
           .groupby(rek[kereso].to_numpy()).median())
    felt = rek.map(tan).to_numpy(float)
    felt = np.clip(np.where(np.isfinite(felt), felt, np.nanmedian(K["s_min"])),
                   0.4, 6.0)

    szabalyok = {f"fix {REFERENCIA_S} ATR": np.full(len(K), REFERENCIA_S)}
    for s in (1.0, 2.0, 3.0):
        szabalyok[f"fix {s} ATR"] = np.full(len(K), s)
    if np.isfinite(szerk).mean() > 0.5:
        szabalyok["szerkezeti (swing mögé)"] = szerk
    szabalyok["feltételes (tanult s_min)"] = felt

    sorok = []
    ref_r = None
    for nev, s_arr in szabalyok.items():
        # ⚠ A `kivonat_egyedi` kihagyja azokat a sorokat, ahol a stop NaN vagy
        # ≤ 0 (a szerkezeti stopnál 2–5 belépő páronként: nincs igazolt swing).
        # Az első futásban (2026-09-19) ilyenkor a költség-tömbök elcsúsztak
        # volna, ezért a sor költség NÉLKÜL és `kulonbseg_t` nélkül ment ki —
        # összehasonlíthatatlanul. Most a kieső belépőket ELŐRE kivesszük a
        # költségből ÉS a referenciából is, így minden szabály ugyanazokon a
        # belépőkön, párosítva mérődik.
        ok = np.isfinite(s_arr) & (s_arr > 0)
        E = SP.kivonat_egyedi(m1, atr, K["i"].to_numpy(int)[ok], d[ok],
                              np.asarray(s_arr, float)[ok], h)
        if E.empty:
            continue
        if len(E) != int(ok.sum()) or not np.array_equal(
                E["i"].to_numpy(int), K["i"].to_numpy(int)[ok]):
            print(f"   ⚠ {nev}: a kivonat nem illeszkedik a belépőkre "
                  f"({len(E)} vs {int(ok.sum())}) — a sor kihagyva")
            continue
        if not ok.all():
            print(f"   ({nev}: {int((~ok).sum())} belépőn nincs stop-távolság, "
                  f"a párosított különbség a többi {int(ok.sum()):,} soron)")
        s_e = E["s"].to_numpy(float)
        stop_b = E["stop_bar"].to_numpy(int)
        utott = stop_b < h
        r_brutto = np.where(utott, -1.0, E["zaro"].to_numpy(float) / s_e)
        kilep = np.minimum(stop_b, h)
        k_e = k if ok.all() else Koltseg(sym, K[ok].reset_index(drop=True), h)
        r = r_brutto - k_e.r(s_e, kilep)
        st = _sor(r, E)
        hold = ~np.asarray(pd.DatetimeIndex(E["ido"])
                           < pd.Timestamp(VAGAS, tz=pd.DatetimeIndex(E["ido"]).tz))
        st_h = _sor(r[hold], E[hold]) if hold.sum() > 50 else {"R": np.nan}
        elerheto = float(np.nanmean(E["mfe_s"].to_numpy(float) / s_e))
        sor = {"szabaly": nev, "atlag_s": float(np.nanmean(s_e)),
               "eleg_%": 100 * float(E["eleg"].mean()),
               "elerheto_R": elerheto, "R_netto": st["R"], "t_nap": st["t_nap"],
               "R_holdout": st_h["R"],
               "evek_poz": st["evek_poz"], "n": st["n"]}
        if ref_r is None:
            # a referencia (fix 1,5 ATR) minden belépőn értelmezett -> teljes
            ref_r = r
            sor["kulonbseg_t"] = np.nan
            sor["kulonbseg_evek_poz"] = np.nan
        else:
            # ugyanazokon a belépőkön, párosítva: a referencia a kieső sorok
            # nélkül. Az `evek_poz` fent a szabály SAJÁT R-jére vonatkozik; az
            # elfogadás (2) feltétele a KÜLÖNBSÉG évenkénti előjele — ez az.
            kul = r - ref_r[ok]
            sor["kulonbseg_t"] = _sor(kul, E)["t_nap"]
            sor["kulonbseg_evek_poz"] = _sor(kul, E)["evek_poz"]
        sorok.append(sor)
    t = pd.DataFrame(sorok)
    print(t.to_string(index=False, float_format=lambda v: f"{v:9.3f}"))
    print("   `kulonbseg_t`: a fix referenciához mért KÜLÖNBSÉG napra "
          "klaszterezett t-je (ugyanazokon a belépőkön, párosítva)")
    print("   `kulonbseg_evek_poz`: az évek hányadában pozitív ez a különbség "
          "— az elfogadás (2) feltétele; az `evek_poz` a szabály saját R-jéé")
    print("   ⚠ a `feltételes` szabály a KERESŐ szakaszon tanult — rá NÉZVE "
          "csak az `R_holdout` oszlop érvényes;")
    print("     a fix szabályoknál a két oszlop különbsége csak a két "
          "időszak eltérése.")
    return t


def r5_megjosolhato(K: pd.DataFrame) -> None:
    """5. MEGJÓSOLHATÓ-E a szükséges stop? Enélkül a feltételes stop értelmetlen."""
    print("\n=== 5. MEGJÓSOLHATÓ-E AZ ELVISELENDŐ FÁJDALOM (s_min)? ===")
    ido = pd.DatetimeIndex(K["ido"])
    kereso = np.asarray(ido < pd.Timestamp(VAGAS, tz=ido.tz))
    sm = K["s_min"].to_numpy(float)
    for jell in ("atr_arany", "sma_tav", "tart_poz", "tart_szel", "ora"):
        if jell not in K:
            continue
        v = K[jell].to_numpy(float)
        ok = np.isfinite(v) & np.isfinite(sm)
        if ok.sum() < 500:
            continue
        # kvintilisek a KERESŐ szakaszon tanulva, a HOLDOUTON kiértékelve
        try:
            hat = np.nanpercentile(v[ok & kereso], [20, 40, 60, 80])
        except (ValueError, IndexError):
            continue
        rek_k = np.digitize(v, hat)
        cs_k = pd.Series(sm[ok & kereso]).groupby(rek_k[ok & kereso]).median()
        cs_h = pd.Series(sm[ok & ~kereso]).groupby(rek_k[ok & ~kereso]).median()
        if len(cs_k) < 3 or len(cs_h) < 3:
            continue
        rho = ST.spearman(cs_k, cs_h)
        print(f"   {jell:>10s}: kereső kvintilis-mediánok "
              f"{np.array(cs_k.values).round(2)} | holdout "
              f"{np.array(cs_h.values).round(2)} | rang-egyezés {rho:+.2f}")
    print("   -> ha a kvintilis-sorrend a holdouton NEM ismétlődik, a feltételes")
    print("      stopnak nincs mire támaszkodnia.")


def fuss(sym: str, db: int, mag: int, h: int, blokk: int, null: bool) -> None:
    print(f"\n{'=' * 78}\n=== {sym} ===\n{'=' * 78}", flush=True)
    m1 = lab.load_m1(sym)
    atr = SP.atr_m1(m1)
    idx = SP.mintavetel(m1, atr, db, mag, h)
    print(f"   {len(idx):,} belépő-pont mintavéve, {m1.index[0]:%Y-%m} … "
          f"{m1.index[-1]:%Y-%m}", flush=True)
    K = SP.kivonat(m1, atr, idx, h)
    J = SP.jellemzok(m1, idx)
    K = K.merge(J, on="i", how="left")
    print(f"   {len(K):,} pálya-kivonat (mindkét irány)", flush=True)

    k = Koltseg(sym, K, h)
    if not k.ervenyes:
        print("   ⚠ nincs `pv1_point`/`point_size` a configban -> a NETTÓ "
              "számok = BRUTTÓ (a swap NINCS levonva!)")
    else:
        print(f"   jutalék {k.comm_pts:.1f} pont, swap-medián "
              f"{np.median(k.swap_pts):.1f} pont/éjszaka")

    r1_mennyi_fajdalom(K)
    r2_felulet(K, h, k)
    r3_kihozatal(K, h, k)
    r4_szabalyok(sym, m1, atr, K, h, k)
    r5_megjosolhato(K)

    if null:
        print(f"\n=== 6. NULL-PIAC (blokk-bootstrap, {blokk} perces blokkok) ===")
        print("   ugyanaz a mérés egy AZONOS VOLATILITÁSÚ, de szerkezet nélküli")
        print("   piacon. Ami itt is kijön, az nem szerkezet.")
        mn = SP.szintetikus(m1, blokk, mag)
        atr_n = SP.atr_m1(mn)
        Kn = SP.kivonat(mn, atr_n, idx, h)
        kn = Koltseg(sym, Kn, h)
        o = []
        for s in S_FOKUSZ:
            rv, _ = cella(K, s, None, h, k)
            rn, _ = cella(Kn, s, None, h, kn)
            o.append({"stop_ATR": s,
                      "valodi_elerheto": float(np.nanmean(K[f"mfe_s{s}"]) / s),
                      "null_elerheto": float(np.nanmean(Kn[f"mfe_s{s}"]) / s),
                      "valodi_R": float(np.nanmean(rv)),
                      "null_R": float(np.nanmean(rn)),
                      "valodi_s_min": float(np.nanmedian(K["s_min"])),
                      "null_s_min": float(np.nanmedian(Kn["s_min"]))})
        print(pd.DataFrame(o).to_string(index=False,
                                        float_format=lambda v: f"{v:9.3f}"))
        print("   -> ha a `valodi_*` és a `null_*` oszlop egybeesik, akkor a stop")
        print("      elhelyezése nem szerkezetet használ ki, csak a volatilitás")
        print("      alakját — és nincs mit optimalizálni rajta.")

    K.to_parquet(ROOT / "data" / f"sl_oracle_{sym}.parquet", index=False)
    print(f"\n   kivonat elmentve: data/sl_oracle_{sym}.parquet")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="*",
                    default=["Ger40", "UsaInd", "UsaTec", "GOLD", "USDJPY"])
    ap.add_argument("--minta", type=int, default=20000, help="belépő-pontok száma")
    ap.add_argument("--mag", type=int, default=0)
    ap.add_argument("--tartas", type=int, default=SP.H_ALAP, help="perc")
    ap.add_argument("--blokk", type=int, default=60, help="null-piac blokk-hossz")
    ap.add_argument("--nincs-null", action="store_true")
    a = ap.parse_args()
    pd.set_option("display.width", 200)
    for sym in a.symbols:
        try:
            fuss(sym, a.minta, a.mag, a.tartas, a.blokk, not a.nincs_null)
        except FileNotFoundError:
            print(f"({sym}: nincs data/m1/{sym}.parquet)")


if __name__ == "__main__":
    main()
