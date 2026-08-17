"""Rovid strategia-nev a szuk helyekre, es CIMKE a belepo-vonalon.

⚠ 1. A ROVID NEV. A `bollinger_squeeze_breakout` 26 karakter — egy
tablazat-fejlecben es egy chart-cimken egyarant hasznalhatatlan; a sor-blokkok
szelesebbek voltak, mint a bennuk levo adat. A HOSSZU nev ott marad, ahol van
hely (beallito ablakok, naplo, FAJLNEVEK, config-kulcsok): ott az
egyertelmuseg er tobbet.

⚠ A FELIRAT es a KULCS nem ugyanaz. A kulcs AZONOSIT (osszecsukas, cella-kulcs,
`strategy_name`), a felirat csak megjelenit. Aki a kettot osszevonja, egy
atnevezessel elrontja az allapot-tarolast.

⚠ 2. A CIMKE a fuggoleges vonalon: MELYIK strategia es MEKKORA merettel. Egy
chartra tobb strategia rajza is kerulhet, es a vonal szine csak az IRANYT
mondja — a szetup gazdaja eddig sehol nem latszott. A LOT keretrendszer-tudas
(egyenleg x kockazat / slotok), ezert a keret adja at (`md.lot_of`), UGYANAZZAL
a `calc_lot`-tal, amivel a motor kot. Egyenleg nelkul a meret KIMARAD — nem
talalgatunk meretet a charton.
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy import get_strategy_by_name
from strategy.base import Strategy

# ── 1. A ROVID NEVEK ──────────────────────────────────────────────────────
_want = {"wpr_sma": "WPRSma", "bollinger_squeeze_breakout": "BSB",
         "ml_ai": "MLAI"}
for _n, _s in _want.items():
    _got = get_strategy_by_name(_n).short_name
    check(f"{_n} -> {_s!r}", _got == _s, _got)

# ⚠ A HOSSZ a lenyeg: a felhasznalo kerése „max ilyen 10 betu".
for _n in _want:
    _got = get_strategy_by_name(_n).short_name
    check(f"{_n}: legfeljebb 10 karakter", len(_got) <= 10, f"{len(_got)}")

# ⚠ A NEV (kulcs) VALTOZATLAN — a rovidites csak megjelenites.
for _n in _want:
    check(f"{_n}: a `name` valtozatlan", get_strategy_by_name(_n).name == _n)


# ── 2. AZ ALAPERTELMEZETT SZARMAZTATAS ───────────────────────────────────
# Egy UJ strategia is kapjon hasznalhato roviditest, ne a teljes nevet.
class _Fake:
    name = "uj_teszt_strategia"
    short = ""


check("sajat rovid nev nelkul a KEZDOBETUKBOL kepzodik",
      Strategy.short_name.fget(_Fake()) == "UTS",
      Strategy.short_name.fget(_Fake()))


class _Long:
    name = "a_b_c_d_e_f_g_h_i_j_k_l"
    short = ""


check("...es a szarmaztatott is 10 karakterre vagva",
      len(Strategy.short_name.fget(_Long())) <= 10,
      Strategy.short_name.fget(_Long()))


class _Explicit:
    name = "barmi"
    short = "EZ_EGY_TUL_HOSSZU_ROVIDITES"


check("a KEZI rovidites is vagva van",
      len(Strategy.short_name.fget(_Explicit())) <= 10,
      Strategy.short_name.fget(_Explicit()))


# ── 3. A FEJLECEK ─────────────────────────────────────────────────────────
from dashboard import live_row as _lr
from dashboard.canvas_table import groups

check("ismeretlen nevre ONMAGAT adja (a fejlec sose maradjon ures)",
      _lr.short_of("nincs_ilyen") == "nincs_ilyen")

_g = {lab: tkey for lab, _k, tkey in groups(list(_want), {})}
check("a vaszon-fejlec a ROVID nevet mutatja",
      "BSB" in _g and "WPRSma" in _g, str(list(_g)))
# ⚠ A KULCS marad a teljes nev: az azonosit (osszecsukas, allapot-mentes).
check("...de a kapcsolo-KULCS a TELJES nev",
      _g.get("BSB") == "bollinger_squeeze_breakout", str(_g))
# A cella-kulcsok is a teljes nevre epulnek.
_keys = [k for lab, ks, _t in groups(["bollinger_squeeze_breakout"], {}) for k in ks]
check("...es a cella-kulcsok is", any(k.startswith("bollinger_squeeze_breakout|")
                                      for k in _keys), str(_keys)[:90])

_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("a classic fejlec is a rovid nevet hasznalja",
      "header=st.short_name" in _gui)
check("...de a strategy_name ott is a teljes nev",
      "strategy_name=st.name" in _gui)


# ── 4. A BELEPO-CIMKE ─────────────────────────────────────────────────────
from strategy.base import MarketData
check("a MarketData-nak van lot-szamolo varrata",
      "lot_of" in MarketData.__dataclass_fields__)
check("...es alapbol None (nem talalgatunk meretet)",
      MarketData.__dataclass_fields__["lot_of"].default is None)

for _mod, _needle in (("strategy/wpr_sma.py", "m1lbl_"),
                      ("strategy/bollinger_squeeze.py", "bsqlbl_")):
    _src = (ROOT / _mod).read_text(encoding="utf-8")
    check(f"{_mod}: van cimke a belepo-vonalon", _needle in _src)
    check(f"{_mod}: a ROVID nevet irja ki", "self.short_name" in _src)
    # ⚠ A lot CSAK akkor kerul ra, ha a keret adott szamolot ES pozitiv az ertek.
    _i = _src.find(_needle)
    _blk = _src[max(0, _i - 900):_i + 400]
    check(f"{_mod}: a lot a keret varratabol jon",
          'getattr(md, "lot_of", None)' in _blk)
    check(f"{_mod}: egyenleg nelkul a meret KIMARAD",
          "if _l and _l > 0:" in _blk)

# A keret UGYANAZT a calc_lot-ot adja at, amivel a motor kot.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
_i = _lt.find("md.lot_of = _lot_of")
check("a keret bekoti a lot-szamolot", _i > 0)
_blk = _lt[max(0, _i - 1400):_i]
check("...a MOTORRAL azonos fuggvennyel (calc_lot)",
      "calc_lot as _cl" in _blk and "calc_effective_slots as _ces" in _blk)
check("...es egyenleg nelkul NEM koti be (marad None)",
      "if _bal and _bal > 0" in _blk)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
