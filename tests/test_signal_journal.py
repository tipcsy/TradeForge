"""Perzisztens belépő-napló: a chart előzménye ne az MQL-upsert mellékhatása legyen.

⚠ A KÉRÉS (2026-07-07, a vault „Leendő feladatok" listáján): „minden múltbeli
belépő őrződjön meg és legyen megjeleníthető, függetlenül attól, mekkora
adatablakot töltünk be éppen."

A MEGOLDÁS SZERKEZETE, és amit ez a teszt őriz belőle:

  1. **Két forrás, éles határral.** Az ablakon BELÜL az újraszámolás az igazság
     (marad a viz↔backtest paritás), az ablakon KÍVÜL a napló. A kettő SOSEM
     rajzolja ugyanazt a jelzést kétszer.
  2. **Egy rajzoló.** A jelölőt mindkét út a `visual.entry_marks`-szal állítja
     elő, UGYANABBÓL a rekordból → nem tud elcsúszni. Ha valaki visszaír egy
     második rajzoló-utat a stratégiába, itt bukjon el.
  3. **A napló csak az ÉLŐ útról telhet.** A backtest/export egy tetszőleges
     múltbeli ablakot számol újra a MAI paraméterekkel; ha az is írna, a napló
     többé nem azt tartalmazná, ami megtörtént.
  4. **A „K" gomb nem némítja.** A `show_signals` a RAJZOT kapcsolja ki, nem a
     történést — különben a chart előzménye csendben lyukas lenne pont azokon az
     időszakokon, amikor a felhasználó elrejtette a jeleket.
  5. **Paraméter-ujjlenyomat.** Hangolás után a napló és az újraszámolás JOGOSAN
     tér el; az összevetés csak azonos ujjlenyomatnál értelmes.
"""
import io
import json
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()
logging.disable(logging.ERROR)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from strategy import signal_journal as sj
from strategy import visual as viz

# ⚠ A VALÓDI naplóhoz NEM nyúlunk (a futtató őre is ezt figyeli).
_REAL_DIR = sj.DIR
_TMP = Path(tempfile.mkdtemp(prefix="tfv_sj_"))
sj.DIR = _TMP


def rec(t, d="BUY", e=100.0, sl=99.0, tp=102.0, lab="W BUY"):
    return {"t": t, "d": d, "e": e, "sl": sl, "tp": tp, "lab": lab}


try:
    # ── 1. Alap: hozzáfűzés, dedup, sorrend ────────────────────────────────
    S, ST = "TESTSYM", "wpr_sma"
    n1 = sj.append(S, ST, [rec(1000), rec(2000)], fp="aaa")
    check("két új jelzés bekerül", n1 == 2, str(n1))
    n2 = sj.append(S, ST, [rec(2000), rec(3000)], fp="aaa")
    check("a MÁR NAPLÓZOTT időbélyeg nem kerül be újra", n2 == 1, str(n2))
    rows = sj.load(S, ST, limit=0)
    check("a napló időrendben áll", [r["t"] for r in rows] == [1000, 2000, 3000],
          str([r["t"] for r in rows]))
    check("a rekord mindent visz, amiből újrarajzolható",
          all(k in rows[0] for k in ("t", "d", "e", "sl", "tp", "lab", "fp")),
          str(sorted(rows[0])))

    # ⚠ A DEDUP a LÉNYEG: a viz-szál 30 mp-enként UGYANAZT az ablakot számolja
    # újra. Enélkül a napló percek alatt megtelne ugyanannak a jelzésnek a
    # másolataival, és a chart is többször rajzolná ki.
    for _ in range(20):
        sj.append(S, ST, [rec(1000), rec(2000), rec(3000)], fp="aaa")
    check("20 újraszámolás után sem nő a napló",
          len(sj.load(S, ST, limit=0)) == 3, str(len(sj.load(S, ST, limit=0))))

    # ── 2. Az ABLAK-HATÁR: a napló csak a múltat adja vissza ───────────────
    past = sj.load(S, ST, before_t=2000)
    check("before_t: csak a RÉGEBBI jelzések jönnek",
          [r["t"] for r in past] == [1000], str([r["t"] for r in past]))
    check("...az ablakon belülit az újraszámolás adja (nincs duplikátum)",
          2000 not in [r["t"] for r in past])

    # ── 3. EGY RAJZOLÓ: a naplóból és a friss rekordból AZONOS sor ─────────
    r0 = rec(1234567890, "SELL", 55.5, 56.5, 53.5, "W SELL 0.10 lot")
    sj.append("SYM2", ST, [r0], fp="bbb")
    from_journal = sj.load("SYM2", ST, limit=0)[0]
    a = [o.line() for o in viz.entry_marks(from_journal)]
    b = [o.line() for o in viz.entry_marks(r0)]
    check("a naplóból visszatöltött jelölő BITRE azonos a frissel", a == b,
          f"{len(a)} sor")
    check("...és tényleg az 5 elem (vonal, címke, belépő, TP, SL)", len(a) == 5,
          str([x.split(";")[0] for x in a]))
    check("a jelölő-nevek az IDŐBÉLYEGRE kulcsoltak (upsert, nem halmozódik)",
          all(str(r0["t"]) in x for x in a))

    # ── 4. Sérült sor csak önmagát viszi el ────────────────────────────────
    p = sj.path_of("SYM3", ST)
    sj.append("SYM3", ST, [rec(10), rec(20)], fp="ccc")
    with io.open(p, "a", encoding="utf-8") as f:
        f.write("{ ez nem json\n")
    sj._seen.pop(str(p), None)
    rows3 = sj.load("SYM3", ST, limit=0)
    check("a sérült SOR nem viszi el az egész előzményt",
          [r["t"] for r in rows3] == [10, 20], str(rows3))

    # ── 5. Takarítás ───────────────────────────────────────────────────────
    sj.append("SYM4", ST, [rec(t) for t in range(1, 51)], fp="ddd")
    killed = sj.prune("SYM4", ST, keep_records=10, keep_days=0)
    check("darabszám-korlát takarít", killed == 40 and
          len(sj.load("SYM4", ST, limit=0)) == 10, str(killed))
    now = int(time.time())
    sj.append("SYM5", ST, [rec(now - 100 * 86400), rec(now - 1 * 86400)], fp="e")
    sj.prune("SYM5", ST, keep_records=0, keep_days=30, now_t=now)
    check("kor-korlát takarít", len(sj.load("SYM5", ST, limit=0)) == 1)
    check("...a 0 korlát KIKAPCSOL (nem töröl mindent)",
          sj.prune("SYM5", ST, keep_records=0, keep_days=0) == 0)

    # ⚠ A CHART-korlát KÜLÖN van a tárolásitól: a viz-fájl minden körben
    # teljesen újraíródik, és egy jelölő ÖT objektum — 800 visszatöltött jelzés
    # 4000 sor lenne 30 másodpercenként, szimbólumonként.
    check("a chart-korlát szűkebb, mint a tárolási",
          sj.SHOW_RECORDS < sj.KEEP_RECORDS, f"{sj.SHOW_RECORDS} < {sj.KEEP_RECORDS}")
    sj.append("SYM7", ST, [rec(t) for t in range(1, 31)], fp="g")
    check("a limit tényleg a LEGUTOLSÓ N-t adja",
          [r["t"] for r in sj.load("SYM7", ST, limit=5)] == [26, 27, 28, 29, 30],
          str([r["t"] for r in sj.load("SYM7", ST, limit=5)]))

    # ── 6. Ujjlenyomat + összevetés ────────────────────────────────────────
    check("azonos paraméterek → azonos ujjlenyomat",
          sj.fingerprint({"a": 1, "b": 2}) == sj.fingerprint({"b": 2, "a": 1}))
    check("eltérő paraméter → MÁS ujjlenyomat",
          sj.fingerprint({"a": 1}) != sj.fingerprint({"a": 2}))

    sj.append("SYM6", ST, [rec(100), rec(200)], fp="f1")
    same = sj.compare("SYM6", ST, [rec(100), rec(200)], "f1")
    check("az egyező újraszámolás EGYEZÉST mutat",
          same["egyezik"] == 2 and not same["elter"], str(same))
    moved = sj.compare("SYM6", ST, [rec(100), rec(200, e=999.0)], "f1")
    check("⚠ az ELTÉRŐ ár leletként jelenik meg", moved["elter"] == [200],
          str(moved))
    miss = sj.compare("SYM6", ST, [rec(100), rec(300)], "f1")
    check("a csak-naplóban / csak-számolt szétválik",
          miss["csak_naploban"] == [200] and miss["csak_szamolt"] == [300],
          str(miss))
    # ── ÁRTICK-TŰRÉS ───────────────────────────────────────────────────
    # ⚠ EZ EGY VALÓDI, ÉLES LELETBŐL SZÜLETETT (2026-08-25). Az összevetés
    # riasztott az EURCHF/bollinger párosnál — de az eltérés a NYOLCADIK
    # tizedesjegyen volt (napló 0.92402994 vs újraszámolás 0.9240299443…),
    # vagyis sokkal kisebb, mint egy ártick. Az SL/TP csúszó ablakon számolt
    # indikátorból jön, tehát ez természetes ingadozás. Ilyet jelezni ZAJ — és
    # a zajos figyelmeztetésben elvész a valódi lelet.
    jo2 = rec(300, e=0.92462, sl=0.92402994, tp=0.92580011)
    sj.append("SYM8", ST, [jo2], fp="t1")
    apro = rec(300, e=0.92462, sl=0.92402995, tp=0.92580012)   # 8. tizedes
    szoros = sj.compare("SYM8", ST, [apro], "t1")
    check("tűrés NÉLKÜL a hajszálnyi eltérés is leletnek látszik",
          szoros["elter"] == [300], str(szoros["elter"]))
    laza = sj.compare("SYM8", ST, [apro], "t1", price_tol=0.00005)
    check("⚠ ártick-tűréssel viszont EGYEZÉS", laza["egyezik"] == 1
          and not laza["elter"], str(laza))

    # ...de egy VALÓDI eltérés a tűréssel is átjön.
    nagy = rec(300, e=0.92462, sl=0.9200, tp=0.92580011)
    check("a valódi ár-eltérés a tűréssel is LELET",
          sj.compare("SYM8", ST, [nagy], "t1", price_tol=0.00005)["elter"] == [300])

    # ⚠ Az IRÁNY sosem lehet „közel": egy BUY/SELL csere mindig lelet.
    forditva = rec(300, "SELL", e=0.92462, sl=0.92402994, tp=0.92580011)
    check("⚠ az IRÁNY eltérése a tűréstől FÜGGETLENÜL lelet",
          sj.compare("SYM8", ST, [forditva], "t1", price_tol=1.0)["elter"] == [300])

    # ⚠ Hangolás után a különbség JOGOS — az összevetés ne riasszon.
    other = sj.compare("SYM6", ST, [rec(100, e=888.0)], "MASIK_FP")
    check("MÁS ujjlenyomatnál nincs összevetés (a hangolás nem hiba)",
          other["osszevetve"] == 0 and not other["elter"], str(other))

    # ── 7. A MOTOR ÚTJA: csak az élő ír, és a „K" gomb nem némítja ─────────
    _lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
    check("a pair_visual_lines-nak van `journal` kapcsolója",
          "journal: bool = False" in _lt)
    # ⚠ A SZÁMOT a SZÁNDÉKRA cseréltük. Eddig azt kötötte ki, hogy a paraméter
    # PONTOSAN egyszer szerepel — a `pair_visual_objects` kiemelésekor (a Python
    # chart-labor miatt) viszont két függvénynek lett `journal` kapcsolója, és
    # a teszt elbukott, holott a viselkedés nem változott. A lényeg nem a
    # darabszám, hanem hogy SEHOL ne legyen írásra állítva alapból.
    check("...és az ALAPÉRTELMEZÉS mindenhol a nem-írás (export/backtest néma)",
          _lt.count("journal: bool = False") >= 1
          and "journal: bool = True" not in _lt)
    check("...az ÉLŐ út viszont bekapcsolja", "journal=True" in _lt)
    check("a napló írása a `journal` kapuhoz kötött",
          "if journal and m1 is not None" in _lt)
    # ⚠ Az ÖSSZEVETÉS a napló legfőbb mellékterméke: ugyanannak a ZÁRT gyertyának
    # körről körre ugyanazt kell adnia. Ha nem, az néma eltérés — és eddig semmi
    # nem tudta volna megmutatni. Ha valaki kiszedi, itt bukjon el.
    check("a motor ÖSSZEVETI a naplót az újraszámolással",
          "signal_journal.compare(" in _lt)
    check("...és az eltérés MEGSZÓLAL (nem néma)",
          '"journal_diff"' in _lt and "_warn_once" in _lt)
    check("a chartra visszatöltés a SHOW korláttal megy",
          "signal_journal_show_records" in _lt)
    # ⚠ A motor ÁRTICK-TŰRÉSSEL vet össze — különben minden körben riasztana a
    # csúszó ablak természetes ingadozására.
    check("az összevetés ártick-tűréssel megy",
          "price_tol=float(point_size" in _lt)
    # ⚠ Az ÚJONNAN FELVETT INSTRUMENTUM kezelése ÁTKERÜLT a
    # `test_hot_add_pair.py`-ba: itt eleve rossz helyen volt (a pár-kezelésről
    # szól, nem a naplóról), és időközben a puszta figyelmeztetésből VALÓDI
    # menet közbeni bekötés lett.

    # ⚠ MINDEN élő stratégiának a KÖZÖS rajzolón kell mennie — különben a napló
    # csendben CSAK az egyikre működne. A `bollinger_squeeze` eredetileg saját
    # nevekkel (`bsq*`) és saját vonalvastagsággal rajzolt; így a jelölői nem is
    # kerültek volna be az előzménybe.
    for _f, _old in (("strategy/wpr_sma.py", 'name=f"m1sig_'),
                     ("strategy/bollinger_squeeze.py", 'name=f"bsq')):
        _ss = (ROOT / _f).read_text(encoding="utf-8")
        check(f"{_f}: a KÖZÖS rajzolót hívja", "viz.entry_marks(rec)" in _ss)
        check(f"{_f}: ⚠ nincs MÁSODIK rajzoló-út", _old not in _ss)
        check(f"{_f}: a rekord a naplóba is kimegy", "_sink(rec)" in _ss)

    _ws = (ROOT / "strategy" / "wpr_sma.py").read_text(encoding="utf-8")
    # A rekord-gyűjtés a `show_signals` ELLENŐRZÉSÉN KÍVÜL van: a sorrend a
    # forrásban is látszik — előbb a gyűjtő, utána a rajz-kapu.
    _i_sink = _ws.find("_sink(rec)")
    _i_draw = _ws.find("if _draw_sig:")
    check("a naplózás MEGELŐZI a rajz-kaput (a „K” gomb nem némítja)",
          0 < _i_sink < _i_draw, f"{_i_sink} < {_i_draw}")

    from strategy.base import MarketData
    check("a MarketData-nak van rekord-gyűjtő seamje",
          "on_entry_record" in (ROOT / "strategy" / "base.py").read_text(
              encoding="utf-8"))
    check("...és alapból KI van (a régi hívók változatlanok)",
          MarketData(symbol="X", params={}).on_entry_record is None)

    # ── 8. VÉGPONTTÓL VÉGPONTIG valódi adaton ──────────────────────────────
    # A szerkezeti ellenőrzés nem elég: az számít, hogy a rekordok TÉNYLEG
    # megszülessenek, és a rajz-kikapcsolás tényleg csak a rajzot vigye el.
    try:
        from strategy.settings import load_config, config_for_strategy
        from strategy import get_strategy_by_name
        from trading.backtest import load_data
        from trading.live_trader import default_params
        cfg = load_config("config.json")
        st = get_strategy_by_name("wpr_sma")
        sym = next((s for s in ("Ger40", "UsaTec", "UsaInd", "EURUSD")
                    if s in (cfg.get("pairs") or {})), None)
        d15, d1 = load_data(sym) if sym else (None, None)
    except Exception as ex:
        d15 = None
        print(f"      (nincs adat az end-to-end ellenőrzéshez: {ex})")

    if d15 is not None and d1 is not None and len(d15) > 3000:
        # ⚠ Az `atr_period` (és a többi végrehajtási kulcs) 2026-08-03 óta a
        # KÖZÖS execution configban lakik, nem a stratégiáéban — enélkül a
        # visual_objects `KeyError`-rel száll el (ez élesben is megtörtént).
        from core.execution_params import load_execution_params
        prm = {**default_params(st, config_for_strategy(cfg, "wpr_sma")),
               **load_execution_params(sym, cfg),
               "point_size": cfg["pairs"][sym].get("point_size", 0.0001)}
        bars = {"M15": d15.iloc[-3000:], "M1": d1.iloc[-4000:]}
        got_on, got_off = [], []
        o_on = st.visual_objects(MarketData(
            symbol=sym, params=prm, bars=bars, show_signals=True,
            on_entry_record=got_on.append))
        o_off = st.visual_objects(MarketData(
            symbol=sym, params=prm, bars=bars, show_signals=False,
            on_entry_record=got_off.append))
        check("valódi adaton születik belépő-rekord", len(got_on) > 0,
              f"{sym}: {len(got_on)} db")
        check("⚠ a „K” gomb KI állapotában UGYANANNYI rekord születik",
              len(got_on) == len(got_off), f"{len(got_on)} vs {len(got_off)}")
        _v_on = sum(1 for o in o_on if o.line().startswith("VLINE"))
        _v_off = sum(1 for o in o_off if o.line().startswith("VLINE"))
        check("...de a RAJZ eltűnik (a jelölő-vonalak elmaradnak)",
              _v_on > 0 and _v_off == 0, f"{_v_on} vs {_v_off}")
        if got_on:
            check("a rekord rajzolható (entry_marks nem dob)",
                  len(viz.entry_marks(got_on[0])) == 5)
            check("...és a rajza BENNE VAN az élő objektumokban",
                  viz.entry_marks(got_on[0])[0].line()
                  in [o.line() for o in o_on])
finally:
    sj.DIR = _REAL_DIR
    sj._seen.clear()
    shutil.rmtree(_TMP, ignore_errors=True)

check("a valódi napló-útvonal visszaállt", str(sj.DIR).endswith("signal_journal")
      and "Temp" not in str(sj.DIR), str(sj.DIR))

# ── 9. A config kulcsai dokumentáltak ─────────────────────────────────────
_ex = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
_tr = _ex.get("trading", {})
check("a megtartás a példa-configban is szerepel",
      "signal_journal_keep_records" in _tr and "signal_journal_keep_days" in _tr,
      str([k for k in _tr if "signal_journal" in k]))
check("...és el is magyarázza, MIÉRT kell",
      "MQL-indikátor sosem töröl" in _tr.get("_comment_signal_journal", ""))

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
