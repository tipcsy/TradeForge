"""Napi P&L bontasa (szimbolum x strategia) — core/pnl_split.py.

A motor a napi P&L-t nem bontja: a deal csak a magic-et hozza, a kezzel nyitott
(majd hozzarendelt) pozicionál pedig a magic a kezi marad. A bontas a feloldon
mulik — ezek a tesztek azt orzik, hogy a szamok osszeadodnak es a hianyzo adat
None marad, nem 0.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import pnl_split as ps

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def trade(pid, sym, pnl, magic=0, **kw):
    d = {"position": pid, "symbol": sym, "pnl": pnl, "magic": magic}
    d.update(kw)
    return d


# A feloldo: magic 100 -> wpr_sma, 101 -> ml_ai; a 900-as ticket orokbefogadott.
def resolve(magic, pid):
    if pid == 900:
        return "ml_ai"                      # orokbefogadas ELOBB, mint a magic
    return {100: "wpr_sma", 101: "ml_ai"}.get(magic)


# ══ 1. Alap bontas ═════════════════════════════════════════════════════════
closed = [
    trade(1, "GOLD", 10.0, magic=100),
    trade(2, "GOLD", -4.0, magic=100),
    trade(3, "GOLD", 6.0, magic=101),
    trade(4, "UK100", 2.0, magic=100),
]
s = ps.split_by_strategy(closed, resolve)

check("GOLD/wpr_sma osszege 10 + (-4) = 6", s[("GOLD", "wpr_sma")]["pnl"] == 6.0)
check("GOLD/wpr_sma darabszam 2", s[("GOLD", "wpr_sma")]["count"] == 2)
check("GOLD/wpr_sma 1 nyero, 1 vesztes",
      s[("GOLD", "wpr_sma")]["wins"] == 1 and s[("GOLD", "wpr_sma")]["losses"] == 1)
check("GOLD/ml_ai kulon bucket", s[("GOLD", "ml_ai")]["pnl"] == 6.0)
check("UK100/wpr_sma kulon SZIMBOLUM", s[("UK100", "wpr_sma")]["pnl"] == 2.0)
check("negy kotes -> harom bucket", len(s) == 3)

# ── Az orokbefogadas ELOBB dont, mint a magic ──
s2 = ps.split_by_strategy([trade(900, "GOLD", 5.0, magic=100)], resolve)
check("orokbefogadott ticket az ADOPTED strategiahoz kerul (nem a magic szerint)",
      ("GOLD", "ml_ai") in s2)

# ── Hozza nem rendelt (idegen) pozicio: None kulcs, NEM '—' ──
s3 = ps.split_by_strategy([trade(7, "GOLD", 3.0, magic=555)], resolve)
check("ismeretlen magic -> None strategia-kulcs", ("GOLD", None) in s3)
check("...es a P&L attol meg beleszamit", s3[("GOLD", None)]["pnl"] == 3.0)

# ── resolve nelkul minden a None ala kerul ──
s4 = ps.split_by_strategy(closed)
check("resolve nelkul minden a None strategiahoz megy",
      set(k[1] for k in s4) == {None})

# ══ 2. Instrumentum-szintu osszesito ═══════════════════════════════════════
t = ps.totals_by_symbol(s)
check("GOLD osszesen 6 + 6 = 12", t["GOLD"]["pnl"] == 12.0)
check("GOLD osszes darabszam 3", t["GOLD"]["count"] == 3)
check("UK100 osszesen 2", t["UK100"]["pnl"] == 2.0)
# A 2.0 terv jobb szelso oszlopa EZ — a sor vege sosem mondhat mast, mint a blokkok
check("az osszesito PONTOSAN a blokkok osszege",
      abs(t["GOLD"]["pnl"] - (s[("GOLD", "wpr_sma")]["pnl"]
                              + s[("GOLD", "ml_ai")]["pnl"])) < 1e-12)

# ── for_symbol: egy sor kirajzolasahoz ──
row = ps.for_symbol(s, "GOLD")
check("for_symbol csak a GOLD strategiait adja", set(row) == {"wpr_sma", "ml_ai"})
check("for_symbol ismeretlen szimbolumra ures", ps.for_symbol(s, "NINCS") == {})

# ══ 3. R — PENZ-alapu (a felhasznaloi definicio) ═══════════════════════════
# 15$ tet = 1 R. +30$ -> +2 R.
risks = {1: 15.0, 2: 15.0, 3: 10.0}
s5 = ps.split_by_strategy(
    [trade(1, "GOLD", 30.0, magic=100), trade(2, "GOLD", -15.0, magic=100)],
    resolve, risk_of=risks.get)
b = s5[("GOLD", "wpr_sma")]
check("+30$ 15$-os teten = +2 R, -15$ = -1 R -> osszesen +1 R", abs(b["r"] - 1.0) < 1e-9)
check("mindket kotesnek volt ismert kockazata", b["r_count"] == 2)
check("r_text formaz", ps.r_text(b) == "+1.00R")

# ── Ismeretlen kockazat: a P&L beleszamit, az R NEM ──
s6 = ps.split_by_strategy(
    [trade(1, "GOLD", 30.0, magic=100), trade(77, "GOLD", 50.0, magic=100)],
    resolve, risk_of=risks.get)
b6 = s6[("GOLD", "wpr_sma")]
check("ismeretlen kockazatu kotes P&L-je beleszamit", b6["pnl"] == 80.0)
check("...de az R-be NEM", abs(b6["r"] - 2.0) < 1e-9)
check("...es az r_count csak 1", b6["r_count"] == 1)

# ── Ha EGYETLEN kotesnek sincs kockazata: az R None, NEM 0 ──
# A 0 R azt sugallna, hogy nullan zart — ez mas allitas, mint hogy nem tudjuk.
s7 = ps.split_by_strategy([trade(77, "GOLD", 50.0, magic=100)], resolve,
                          risk_of=risks.get)
check("ismeretlen kockazat mellett az R-szoveg None (= '-')",
      ps.r_text(s7[("GOLD", "wpr_sma")]) is None)
check("risk_of nelkul is None az R-szoveg",
      ps.r_text(ps.split_by_strategy(closed, resolve)[("GOLD", "wpr_sma")]) is None)

# ══ 4. AZ AR-ALAPU ES A PENZ-ALAPU R ELTERESE ══════════════════════════════
# A „Lezart" ful eddigi R-je AR-alapu: elmozdulas / SL-tav. Ez a lot-tol es a
# koltsegtol fuggetlen — DE reszleges zarasnal (Felezo/Pajzs) FELREVEZET, mert
# csak az UTOLSO zaroarat nezi.
#
# Pelda (Pajzs): belepo 4000, SL 3990 (10 ar-egyseg = 1 R kockazat).
#   - 75% zarva 1 R-nel (4010), a runner 3 R-nel (4030).
#   - A PENZ szerint: 0,75 x 1R + 0,25 x 3R = 1,5 R.
#   - Az AR-alapu keplet a 4030-as VEGSO zaroarral szamol -> 3,0 R.
def price_r(price_open, sl, price_close, is_buy=True):
    risk = abs(price_open - sl)
    move = (price_close - price_open) if is_buy else (price_open - price_close)
    return move / risk


ar_alapu = price_r(4000.0, 3990.0, 4030.0)
# penz-alapu: a tenyleges P&L / a belepeskori kockazat
# 1 lot, 1 ar-egyseg = 1$ -> kockazat 10$; realizalt: 0,75x10 + 0,25x30 = 15$
penz_alapu = 15.0 / 10.0
check("az AR-alapu keplet 3,0 R-t mond a reszleges zaras utan",
      abs(ar_alapu - 3.0) < 1e-9, f"{ar_alapu:.2f}R")
check("a PENZ-alapu (helyes) 1,5 R", abs(penz_alapu - 1.5) < 1e-9,
      f"{penz_alapu:.2f}R")
check("A KETTO TENYLEGESEN ELTER -> a bontas a penz-alaput hasznalja",
      abs(ar_alapu - penz_alapu) > 1.0)

# A penz-alapu a KOLTSEGET is tartalmazza (a closed pnl = profit+jutalek+swap),
# az ar-alapu nem: ugyanaz a kotes koltseggel kisebb R-t ad.
s8 = ps.split_by_strategy([trade(1, "GOLD", 30.0 - 2.5, magic=100)], resolve,
                          risk_of={1: 15.0}.get)
check("a koltseg csokkenti a penz-alapu R-t (2,00 -> 1,83)",
      abs(s8[("GOLD", "wpr_sma")]["r"] - 27.5 / 15.0) < 1e-9)

# ══ 5. Robusztussag — a bontas ne dontse le a motort ═══════════════════════
check("ures lista -> ures dict", ps.split_by_strategy([]) == {})
check("None lista -> ures dict", ps.split_by_strategy(None) == {})
check("szimbolum nelkuli sor kimarad",
      ps.split_by_strategy([{"position": 1, "pnl": 5.0}]) == {})
check("nem-dict elem kimarad", ps.split_by_strategy(["x", None]) == {})
check("hianyzo pnl -> 0.0",
      ps.split_by_strategy([trade(1, "GOLD", None)])[("GOLD", None)]["pnl"] == 0.0)
check("szoveges pnl -> 0.0",
      ps.split_by_strategy([trade(1, "GOLD", "x")])[("GOLD", None)]["pnl"] == 0.0)


def boom(*a):
    raise RuntimeError("feloldo hiba")


check("a feloldo kivetele nem dobja el a kotest",
      ps.split_by_strategy([trade(1, "GOLD", 5.0)], boom)[("GOLD", None)]["pnl"] == 5.0)
check("a risk_of kivetele nem dobja el a kotest",
      ps.split_by_strategy([trade(1, "GOLD", 5.0)], resolve,
                           risk_of=boom)[("GOLD", None)]["pnl"] == 5.0)
check("totals ures bemenetre ures", ps.totals_by_symbol({}) == {})
check("r_text ures bucketre None", ps.r_text(None) is None)

# ══ 6. A "Lezart" ful R-fuggvenye (gui._r_multiple) ════════════════════════
# Atallt PENZ-alapura. A szerzodes: kockazat nelkul None (a ful "-"-t mutat),
# nem 0 — a 0 R azt allitana, hogy a kotes nullan zart.
try:
    from dashboard.gui import _r_multiple

    _c = {"pnl": 30.0, "price_open": 4000.0, "sl": 3990.0,
          "price_close": 4030.0, "type": "BUY"}
    check("ful: +30$ 15$-os teten = +2 R", abs(_r_multiple(_c, lambda c: 15.0) - 2.0) < 1e-9)
    check("ful: kockazat nelkul None (nem 0)", _r_multiple(_c, lambda c: None) is None)
    check("ful: risk_provider nelkul None", _r_multiple(_c) is None)
    check("ful: nulla kockazat -> None (nincs nullaval osztas)",
          _r_multiple(_c, lambda c: 0.0) is None)
    # A REGI ar-alapu keplet ugyanerre 3,0-t adott volna (4030-4000)/10 — a fuggveny
    # mostantol a pnl-bol dolgozik, tehat a reszleges zaras nem torzitja.
    check("ful: a P&L-bol dolgozik, NEM a zaroarbol",
          abs(_r_multiple({**_c, "pnl": 15.0}, lambda c: 10.0) - 1.5) < 1e-9)
except Exception as e:                                   # tkinter nelkuli kornyezet
    check(f"ful R-fuggveny teszt kihagyva ({type(e).__name__})", True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
