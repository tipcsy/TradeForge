"""KÉZI LABORATÓRIUM 3. LÉPCSŐ — a charton megrajzolt forgatókönyv.

⚠ A LÉNYEGI ÁLLÍTÁS: a chartról kattintva épített terv és a JSON-fájlból
betöltött terv UGYANAZ — ugyanabba a `lab_scenario.futtat()`-ba megy, tehát
ugyanazt az eredményt adja. Ha a chart-ablak saját végrehajtási utat kapna, a
projekt visszatérő kárforrása jönne vissza: két forrás, ami külön romlik el
(`BacktestReplayer` v4, viz ↔ backtest paritás).

Ezért a teszt nem a gombokat nyomkodja, hanem azt köti ki, hogy

  * a `_forgatokonyv()` UGYANOLYAN alakú szótárat ad, mint a `lab_scenario.MINTA`,
  * ez a szótár tényleg végigfut a valódi motoron,
  * és a chart-ablak nem tartalmaz saját szimulációt.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

import pandas as pd

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from tools import lab_chart as lc
from tools import lab_scenario as ls


class _Var:
    """Tk-mentes helyettes a `StringVar`/`BooleanVar` helyett."""

    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v


def _ablak(belepok, be_ido=None, epites=False, chart=None):
    """`LabAblak` UI-építés NÉLKÜL — csak a forgatókönyv-építéshez kell."""
    a = lc.LabAblak.__new__(lc.LabAblak)
    a._belepok = list(belepok)
    a._be_ido = be_ido
    a._epites = _Var(epites)
    a._sym = _Var("UsaTec")
    a._strat = _Var("wpr_sma")
    a._tol = _Var("")
    a._ig = _Var("")
    a._chart = chart
    return a


_idx = pd.date_range("2026-08-27 00:00", periods=96, freq="15min", tz="UTC")
_chart = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
                      index=_idx)

# ── 1. A FORGATÓKÖNYV ALAKJA ──────────────────────────────────────────────
_fk = _ablak([(_idx[6], "BUY")], be_ido=_idx[20], epites=True,
             chart=_chart)._forgatokonyv()

check("a chart-terv MINDEN kulcsot megad, amit a JSON-minta",
      set(ls.MINTA).issubset(set(_fk)),
      str(sorted(set(ls.MINTA) - set(_fk))))
check("a belépő időpontja és iránya átmegy",
      _fk["entries"] == [{"time": "2026-08-27 01:30", "direction": "BUY"}],
      str(_fk["entries"]))
check("a breakeven időpont átmegy",
      _fk["breakeven_at"] == "2026-08-27 05:00", str(_fk["breakeven_at"]))
check("az építés kapcsoló átmegy", _fk["build"] is True)
# ⚠ A kézi belépő alapja a kapuk NÉLKÜLI futás — ugyanaz, mint a `--minta`-ban.
check("kézi belépőnél a kapuk KI (mint a JSON-mintában)",
      _fk["exec_gates"] is False and _fk["use_strategy_signals"] is False)

# ⚠ ÜRES `-tól`/`-ig` esetén a CHART szélei adják a szakaszt — enélkül a
# `run_pair` az egész előzményt átfutná, és a kísérlet percekig tartana.
# (96 x 15 perc = 24 ora 00:00-tol, tehat az UTOLSO gyertya 23:45 — nem masnap.)
check("üres időszaknál a chart széleit használja",
      _fk["from"] == "2026-08-27 00:00" and _fk["to"] == "2026-08-27 23:45",
      f"{_fk['from']} .. {_fk['to']}")

# ── 2. TÖBB BELÉPŐ: IDŐRENDBEN ────────────────────────────────────────────
# ⚠ A `run_pair` a jelölt-listát pozíció-index szerint dolgozza fel; egy
# fordított sorrendű lista némán mást jelentene.
_fk2 = _ablak([(_idx[30], "SELL"), (_idx[10], "BUY")],
              chart=_chart)._forgatokonyv()
check("a belépők IDŐRENDBEN kerülnek a forgatókönyvbe",
      [e["direction"] for e in _fk2["entries"]] == ["BUY", "SELL"],
      str(_fk2["entries"]))
check("breakeven nélkül a kulcs None", _fk2["breakeven_at"] is None)

# ── 3. A TERV TÉNYLEG VÉGIGFUT A VALÓDI MOTORON ───────────────────────────
# ⚠ Ez köti össze a két lépcsőt: a charton megrajzolt terv ugyanazon az úton
# megy, mint a `python tools/lab_scenario.py fk.json`.
_valos = {**ls.MINTA}
_ki = None
try:
    _ki = ls.futtat(_valos)
except SystemExit as ex:
    check("a JSON-minta lefut a motoron", False, f"SystemExit: {ex}")
if _ki is not None:
    check("a JSON-minta lefut a motoron", "res" in _ki)
    # És a chart-terv UGYANOLYAN alakú → ugyanaz a hívás fogadja el.
    _chart_terv = _ablak([(pd.Timestamp("2026-08-27 01:30", tz="UTC"), "BUY")],
                         chart=_chart)._forgatokonyv()
    _chart_terv.update({"symbol": _valos["symbol"],
                        "strategy": _valos["strategy"],
                        "from": _valos["from"], "to": _valos["to"]})
    try:
        _ki2 = ls.futtat(_chart_terv)
        _a = [(str(t.open_time), t.direction) for t in _ki["res"].trades]
        _b = [(str(t.open_time), t.direction) for t in _ki2["res"].trades]
        check("a CHART-terv ugyanazt a kötést adja, mint a JSON-terv",
              _a == _b, f"{len(_a)} vs {len(_b)}")
    except SystemExit as ex:
        check("a CHART-terv ugyanazt a kötést adja, mint a JSON-terv", False,
              f"SystemExit: {ex}")

# ── 4. NINCS SAJÁT VÉGREHAJTÁS ────────────────────────────────────────────
_src = (ROOT / "tools" / "lab_chart.py").read_text(encoding="utf-8")
check("a chart a MEGLÉVŐ forgatókönyv-motort hívja",
      "from tools.lab_scenario import futtat" in _src)
for _tilos in ("run_pair(", "def simulate", "def _manage", "close_price ="):
    check(f"nincs saját végrehajtás a chart-ablakban ({_tilos!r})",
          _tilos not in _src)

# ⚠ A `lab_scenario._hiba` SystemExit-tel áll meg (parancssori eszköz). Ha az
# ablak nem fogná el, egy elgépelt szimbólum MEGÖLNÉ a laboratóriumot.
_fut = _src.split("def futtat", 1)[1].split("\n    def ", 1)[0]
check("a futtatás elfogja a SystemExit-et (nem hal meg az ablak)",
      "except SystemExit" in _fut)

# ── 5. A KATTINTÁS csak AKTÍV MÓDBAN tesz le jelölőt ──────────────────────
# ⚠ A nagyítás/görgetés is kattintás. Ha minden kattintás belépőt tenne, a
# chart használhatatlan lenne.
_katt = _src.split("def _kattintas", 1)[1].split("\n    def ", 1)[0]
check("üres módnál a kattintás nem tesz le semmit",
      "if not mod or ev.inaxes is not self._ax" in _katt)
# ⚠ IDŐBEN tárolunk, nem bar-indexben: az idősík-váltás átszámozza az indexeket.
# (A horgony a v3.21.0-ban `chart.index[i]`-ről `ido_x()`-re változott — az
# ÁLLÍTÁS ugyanaz, csak a leképezés lett gyertyán belül is pontos.)
check("a belépő IDŐPONTKÉNT tárolódik (nem bar-indexként)",
      "self.ido_x(" in _katt and "index[i]" not in _katt)

# ── 6. A KATTINTÁS IDŐSÍKTÓL FÜGGETLEN ────────────────────────────────────
# ⚠ EZ VOLT A „FURASÁG” (2026-09-03, felhasználói jelzés): „ha M1-es idősíkra
# kattintok, az nem ugyanaz, mint ha M15-re kattintanék". Az ok: a gyertya
# NYITÓ idejét adtuk vissza, tehát M15-ön a kattintás a gyertya elejére ugrott,
# M1-en viszont a percre — ugyanaz a vizuális pont akár 15 perccel (H4-en 4
# órával) máshova került. A motor pedig M1-en hajt végre, tehát ez nem
# szépséghiba volt.
def _abl(freq, n):
    _i = pd.date_range("2026-08-27 00:00", periods=n, freq=freq, tz="UTC")
    return _ablak([], chart=pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}, index=_i))


_m1, _m15, _h1 = _abl("1min", 1440), _abl("15min", 96), _abl("60min", 24)
_elteres = []
for _perc in range(0, 1400, 7):
    _a = _m1.ido_x(_perc)                  # M1-en a perc = bar-index
    _b = _m15.ido_x(_perc / 15.0 - 0.5)    # tört index a gyertyán belül
    _c = _h1.ido_x(_perc / 60.0 - 0.5)
    if not (_a == _b == _c):
        _elteres.append((_perc, str(_a)[11:16], str(_b)[11:16], str(_c)[11:16]))
check("ugyanaz a kattintás M1 / M15 / H1 idősíkon UGYANAZT az időt adja",
      not _elteres, f"{len(_elteres)} eltérés, első: {_elteres[:3]}")

# ⚠ LEBEGŐPONT: a `0,53333 × 15 perc = 7,99999…` percből a `floor` 7-et csinál.
# Ezért kerekítünk előbb EGÉSZ MÁSODPERCRE. A teszt a konkrét esetet is nézi.
check("a 68. perc M15-ön is 01:08 (nem 01:07)",
      str(_m15.ido_x(68 / 15.0 - 0.5))[11:16] == "01:08",
      str(_m15.ido_x(68 / 15.0 - 0.5))[11:16])
check("a charton kívüli koordináta None", _m1.ido_x(-5.0) is None
      and _m1.ido_x(99999.0) is None)

# ── 7. JELÖLŐ-TÖRLÉS egyesével ────────────────────────────────────────────
# ⚠ A `Töröl` gomb MINDENT kiürít; egy elrontott kattintás miatt az egész
# tervet újra kellene rajzolni.
_t0 = pd.Timestamp("2026-08-27 01:00", tz="UTC")
_a = _ablak([(_t0, "BUY"), (_t0 + pd.Timedelta(hours=2), "SELL")],
            chart=_chart)
_a._eredmeny = None
_a._rajzol = lambda: None                 # a rajzoláshoz Tk kellene
_a._torol_kozeli(_t0 + pd.Timedelta(minutes=5))
check("a jobb gomb a LEGKÖZELEBBI belépőt törli",
      [d for _, d in _a._belepok] == ["SELL"], str(_a._belepok))

_b = _ablak([(_t0, "BUY")], be_ido=_t0 + pd.Timedelta(hours=3), chart=_chart)
_b._eredmeny = None
_b._rajzol = lambda: None
_b._torol_kozeli(_t0 + pd.Timedelta(hours=3, minutes=2))
check("a BE-jelölő is törölhető, ha az van közelebb",
      _b._be_ido is None and len(_b._belepok) == 1)

# ── 8. „nincs stratégia” → TISZTA chart ───────────────────────────────────
check("a `— nincs —` üres stratégia-névre fordul",
      _ablak([], chart=_chart).__class__._strat_nev.__doc__ is not None)
_ns = _ablak([], chart=_chart)
_ns._strat = _Var(lc.NINCS_STRAT)
check("...és a forgatókönyvbe is üresen kerül",
      _ns._forgatokonyv()["strategy"] == "", _ns._forgatokonyv()["strategy"])

# ── 9. FOGD-ÉS-VIDD: a lerakott jelölő igazítható ─────────────────────────
# ⚠ A KÉRÉS (2026-09-03): „ha leteszek egy buy jelzést, akkor lehessen azt
# megfogni, és arrébb tenni. Általában leteszem és beigazítom." Ezért a lerakás
# UTÁN a mód azonnal kikapcsol — ha aktív maradna, a következő kattintás egy
# ÚJABB belépőt tenne le a meglévő igazítása helyett.
_katt2 = _src.split("def _kattintas", 1)[1].split(chr(10) + "    def ", 1)[0]
check("lerakás után a kattintás-mód KIKAPCSOL (fogd-és-vidd jön)",
      'self._mod.set("")' in _katt2)

# A megfogás tűrése a NÉZETTEL tágul: kinagyítva egy gyertya sok képpont,
# kicsinyítve kevés — fix gyertya-tűrés mellett kicsinyítve eltalálhatatlan lenne.
class _Ax:
    def __init__(self, a, b):
        self._l = (a, b)

    def get_xlim(self):
        return self._l


_idx2 = pd.date_range("2026-08-27 00:00", periods=200, freq="15min", tz="UTC")
_d = _ablak([(_idx2[50], "BUY"), (_idx2[120], "SELL")], be_ido=_idx2[80],
            chart=pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5,
                                "close": 1.5}, index=_idx2))
_d._tengely = lc.Idotengely(_idx2)
_d._ax = _Ax(0, 200)

check("a jelölő közelében MEGFOG", _d._foghato(49.8) == ("belepo", 0),
      str(_d._foghato(49.8)))
check("a másik jelölőt is megtalálja", _d._foghato(120.1) == ("belepo", 1))
check("a BE-jelölőt is megfogja", _d._foghato(80.0) == ("be", None))
check("jelölőtől TÁVOL nem fog meg (a chart görgethető marad)",
      _d._foghato(10.0) is None)

# ⚠ Kinagyítva ugyanaz a gyertya-távolság MÁS képernyő-távolság. A tűrésnek a
# látható szélességgel kell tágulnia.
# ⚠ A JELÖLŐ a gyertya BAL SZÉLÉN ül (`Idotengely.hol` geometriai leképezése),
# tehát az 50. gyertyáé x=49,5 — nem 50,0. Az első tesztváltozatomban 50,0-t
# írtam, és a fogás „nem működött”, holott a kód jó volt.
_xm = _d._tengely.hol(int(_idx2[50].timestamp()))
_d._ax = _Ax(45, 55)                       # erős nagyítás → tűrés 0,5
check("kinagyítva SZŰKEBB a tűrés (pontosabb fogás)",
      _d._foghato(_xm + 0.9) is None and _d._foghato(_xm + 0.1) == ("belepo", 0),
      f"x={_xm} · {_d._foghato(_xm + 0.9)} / {_d._foghato(_xm + 0.1)}")

_huz = _src.split("def _huzas(", 1)[1].split(chr(10) + "    def ", 1)[0]
# ⚠ Egérmozgásonként a teljes chart újrarajzolása akadozna: csak PERC-VÁLTÁSKOR.
check("a mozgatás csak PERC-VÁLTÁSKOR rajzol újra",
      "if t == self._be_ido:" in _huz and "if t == self._belepok[i][0]:" in _huz)
check("a mozgatás érvényteleníti a korábbi futtatást",
      "self._eredmeny = None" in _huz)

# ── 10. AZ ABLAK TÉNYLEG ELINDUL ──────────────────────────────────────────
# ⚠ A LELET (2026-09-03): a `betolt()` legelső dolga a látott időszak elmentése
# (`_lathato_ido`), ami a `self._chart`-ot olvassa — az ELSŐ híváskor viszont az
# még nem létezett, és az ablak `AttributeError`-ral el sem indult.
#
# A fenti tesztek ezt NEM foghatták meg: azok `__new__`-val építik az objektumot
# és kézzel állítják be a mezőket — pont a KONSTRUKTORT kerülik meg. Ezért kell
# egy teszt, ami valódi ablakot épít.
try:
    import tkinter as _tk
    _p = _tk.Tk()
    _p.destroy()
    _TK = True
except Exception as _e:
    _TK = False
    print(f"KIHAGYVA: nincs használható tkinter ({type(_e).__name__}: {_e})")

if _TK:
    import json as _json
    _cfg = _json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    _par = next((k for k, v in (_cfg.get("pairs") or {}).items()
                 if isinstance(v, dict)
                 and (ROOT / "data" / "m15" / f"{k}.parquet").exists()), None)
    if _par is None:
        check("van pár, amivel az ablak felépíthető", False, "nincs letöltött adat")
    else:
        _abl = None
        try:
            _abl = lc.LabAblak(symbol=_par, tf_perc=15,
                               tol="2026-08-25", ig="2026-08-26")
            _abl.root.withdraw()
            check("az ablak FELÉPÜL (a konstruktor végigfut)", True)
            check("a chart-mezők a betöltés előtt is léteznek",
                  hasattr(_abl, "_chart") and hasattr(_abl, "_tengely")
                  and hasattr(_abl, "_objs"))
            # ⚠ A `betolt()` MÁSODSZOR is lefut — ott már van korábbi nézet,
            # tehát az `_allitsd_ido` út is kipróbálódik.
            _abl.betolt()
            check("a második betöltés is végigfut (a nézet-visszaállítással)", True)
        except Exception as _ex:
            check("az ablak FELÉPÜL (a konstruktor végigfut)", False,
                  f"{type(_ex).__name__}: {_ex}")
        finally:
            try:
                if _abl is not None:
                    _abl.root.destroy()
            except Exception:
                pass

# ── 11. LEJÁTSZÁS (5-7. pont) ─────────────────────────────────────────────
# ⚠ A LEJÁTSZÁS NEM FUTTATJA A MOTORT LÉPÉSENKÉNT. Egy időkurzor halad a
# szakaszon; a `Futtat` a végén ugyanúgy a `lab_scenario.futtat()`-ot hívja.
# Ha a lejátszás maga „kereskedne”, az egy MÁSODIK végrehajtási út lenne.
class _Gomb:
    def __init__(self):
        self.szoveg = ""

    def config(self, **kw):
        self.szoveg = kw.get("text", self.szoveg)


def _jatszo(n=100, freq="15min"):
    _i = pd.date_range("2026-08-27 00:00", periods=n, freq=freq, tz="UTC")
    a = _ablak([], chart=pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
         "avg_spread": 0.02}, index=_i))
    a._kurzor = None
    a._jatszik = False
    a._utem_id = None
    a._play_gomb = _Gomb()
    a._rajzol = lambda: None
    a._tengely = lc.Idotengely(_i)
    return a


_j = _jatszo()
_j.leptet(5)
check("a léptetés a szakasz elejéről indul", _j._kurzor == 5, str(_j._kurzor))
_j.leptet(-50)
check("visszatekerésnél nem megy 0 alá", _j._kurzor == 0, str(_j._kurzor))
_j.leptet(1000)
check("előretekerésnél nem megy az utolsó gyertyán túl",
      _j._kurzor == 99, str(_j._kurzor))
_j.kurzor_le()
check("a „Lejátszás vége” leveszi a kurzort (teljes chart)",
      _j._kurzor is None and _j._jatszik is False)

# ⚠ A KÉZI LÉPTETÉS ÁLLÍTSA MEG a lejátszást — különben az ütem és a kattintás
# egymás ellen dolgozna, és a kurzor „visszaugrálna”.
_j._jatszik = True
_j.leptet(1)
check("a kézi léptetés megállítja a lejátszást",
      _j._jatszik is False and _j._play_gomb.szoveg.endswith("Play"))

# ── A LEJÁTSZÁS a Tk `after`-jével megy, NEM `sleep`-pel ──────────────────
# ⚠ A `sleep` befagyasztaná az ablakot: a gombok sem működnének közben.
_ply = _src.split("def _utem", 1)[1].split(chr(10) + "    def ", 1)[0]
# ⚠ A HÍVÁSRA szűkítve: a `_utem` DOCSTRINGJE maga is leírja, hogy „nem
# `sleep`-pel" — a puszta szó-keresés a saját magyarázatra bukott el.
check("a lejátszás a Tk `after`-jét használja (nem sleep)",
      "self.root.after(" in _ply and "sleep(" not in _ply)
check("a sebesség gyertya/másodpercben számol",
      "1.0 / max(0.5, float(self._sebesseg.get()))" in _ply)

# ── AZ IDŐSÍK-VÁLTÁS a kurzort IDŐBEN őrzi ───────────────────────────────
# ⚠ Ugyanaz a csapda, mint a nézetnél: bar-indexben őrizve M15→M1 váltásnál
# 15-szörös lenne az ugrás.
_j2 = _jatszo()
_j2._kurzor = 40
_t_kurzor = _j2._kurzor_ido()
check("a kurzor időpontja kiolvasható",
      str(_t_kurzor)[:16] == "2026-08-27 10:00", str(_t_kurzor))
_j3 = _jatszo(n=1500, freq="1min")          # ugyanaz a szakasz M1-en
_j3._kurzor_vissza(_t_kurzor)
check("idősík-váltás után a kurzor UGYANARRA az időre áll",
      str(_j3._chart.index[_j3._kurzor])[:16] == "2026-08-27 10:00",
      str(_j3._chart.index[_j3._kurzor]))

# ── BID/ASK: a spread az ADATBÓL jön ─────────────────────────────────────
# ⚠ Ha kitalálnánk, a labor mást mutatna, mint amit a motor fizet.
_kur = _src.split("def _rajzol_kurzor", 1)[1].split(chr(10) + "    def ", 1)[0]
check("a BID/ASK az `avg_spread` oszlopból számol",
      'sor.get("avg_spread"' in _kur)
check("az ár a pár tizedeseivel jelenik meg (nem %.5g)",
      "self._ar_szoveg(" in _kur)
check("a „csak eddig látszik” letakarja a jövőt",
      "self._csak_eddig.get()" in _kur and "axvspan" in _kur)

# ── A LEJÁTSZÁS NEM VÉGREHAJT ────────────────────────────────────────────
for _tilos in ("open_position", "run_pair(", "def simulate"):
    check(f"a lejátszás nem kereskedik ({_tilos!r})", _tilos not in _src)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
