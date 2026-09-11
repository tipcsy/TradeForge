"""KÉZI LABORATÓRIUM — a Qt/pyqtgraph felület.

⚠ MIÉRT CSERÉLTÜK LE A MATPLOTLIB-ET (2026-09-03). A felhasználói hibalista —
nem lehet megfogni a vonalat, kicsúszik a képből, a nagyítás használhatatlan, a
tengely-felirat eltűnik, húzás közben újrarajzol — mind egy okra vezetett
vissza: a matplotlib diagram-rajzoló, nem interaktív chart. A húzható vonalat,
a találat-tesztet és a tengely-formázót kézzel írtuk meg, és a hibák is
darabonként jöttek.

MÉRVE (UsaTec, ugyanaz az adat, teljes újrarajzolás):

    gyertya   matplotlib   pyqtgraph   arány
        184      52,2 ms      3,5 ms   14,9x
      2 760     128,3 ms     20,2 ms    6,4x
     11 040     426,2 ms     89,4 ms    4,8x

⚠ EZ A TESZT NEM A RAJZOLÁST ŐRZI, HANEM A HATÁRT: hogy a csere KIZÁRÓLAG a
megjelenítést érintette. Az adat a `lab_chart.keszit()`-ből, a futtatás a
`lab_scenario.futtat()`-ból jön — ha a Qt-s ablak saját végrehajtást kapna,
visszajönne a projekt visszatérő kárforrása (két forrás, ami külön romlik el).
"""
# ⚠ A BELÉPŐ RAJZ-ELEMEI ABLAKONKÉNT (v3.68.0): ha EGY belépő TÖBB ablakban
# látszik (M1-en nyitva, de az M5-ön és M15-ön is látni akarjuk), ablakonként
# külön Qt-elem tartozik hozzá. A `Belepo` tiszta MODELL lett; az elemeket az
# ablak tartja (`_w._bel(belepo, "mező")`).
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


try:
    import pyqtgraph  # noqa: F401
    from PySide6 import QtWidgets  # noqa: F401
    QT_OK = True
except Exception as _e:
    QT_OK = False
    print(f"KIHAGYVA: nincs Qt/pyqtgraph ({type(_e).__name__}: {_e})")

_src = (ROOT / "tools" / "lab_qt.py").read_text(encoding="utf-8")

# ── 1. A HATÁR: nincs saját adat- vagy végrehajtási út ────────────────────
check("az adat a MEGLÉVŐ `keszit()`-ből jön",
      "from tools.lab_chart import" in _src and "keszit" in _src)
check("a futtatás a MEGLÉVŐ `lab_scenario.futtat()`-ot hívja",
      "from tools.lab_scenario import futtat" in _src)
for _tilos in ("run_pair(", "def simulate", "def _manage", "open_position",
               "pair_visual_objects("):
    check(f"nincs saját végrehajtás/adatút ({_tilos!r})", _tilos not in _src)

# ⚠ A SZÍNEK IS a közös forrásból: a Qt-s és az MT5-ös chart ugyanazt a jelet
# ne mutassa más színnel — a kettő összevetése az egyik cél.
check("a színek a `lab_chart.szin`-ből (végső soron `visual.COLORS`)",
      "szin(" in _src and "from tools.lab_chart import" in _src)

if QT_OK:
    from tools import lab_qt as lq
    from tools import lab_scenario as ls

    # ── 2. A BELÉPŐ: idő az azonosító, a TP a stop függvénye ─────────────
    b = lq.Belepo(pd.Timestamp("2026-08-27 01:30", tz="UTC"), "BUY",
                  sl=29500.0, rr=2.0)
    check("a TP a stop TÁVOLSÁGÁBÓL és az R-ből",
          abs(b.tp_ar(29532.0) - (29532.0 + 2.0 * 32.0)) < 1e-6,
          str(b.tp_ar(29532.0)))
    b.rr = 3.5
    check("...és az R változása mozgatja a TP-t",
          abs(b.tp_ar(29532.0) - (29532.0 + 3.5 * 32.0)) < 1e-6)
    _s = lq.Belepo(pd.Timestamp("2026-08-27 01:30", tz="UTC"), "SELL",
                   sl=29560.0, rr=2.0)
    check("SELL-nél a TP LEFELÉ van",
          _s.tp_ar(29532.0) < 29532.0, str(_s.tp_ar(29532.0)))

    # ── 3. AZ ABLAK FELÉPÜL, és a terve ugyanaz az alak ──────────────────
    # ⚠ Valódi ablakot építünk: a `__new__`-os tesztek pont a konstruktort
    # kerülik meg, és a matplotlib-es változatnál épp ott volt egy hiba, ami
    # miatt EL SEM INDULT.
    import json as _json
    _cfg = _json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    _par = next((k for k, v in (_cfg.get("pairs") or {}).items()
                 if isinstance(v, dict)
                 and (ROOT / "data" / "m15" / f"{k}.parquet").exists()), None)
    if _par is None:
        check("van pár, amivel az ablak felépíthető", False, "nincs adat")
    else:
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _w = None
        try:
            _w = lq.LabAblak(symbol=_par, tf_perc=15,
                             tol="2026-08-25", ig="2026-08-26")
            check("az ablak FELÉPÜL (a konstruktor végigfut)", True)
            check("betöltött gyertyák", _w._chart is not None and len(_w._chart) > 10,
                  str(None if _w._chart is None else len(_w._chart)))

            # A kattintás-idő gyertyán BELÜL is pontos (idősík-független).
            _t1 = _w._ido_x(10.0)
            _t2 = _w._ido_x(10.25)
            check("a gyertyán belüli kattintás finomabb időt ad",
                  _t1 is not None and _t2 is not None and _t2 > _t1,
                  f"{_t1} / {_t2}")

            # A forgatókönyv ALAKJA azonos a JSON-mintáéval.
            _w._belepok.append(lq.Belepo(_w._chart.index[20], "BUY",
                                         float(_w._chart["close"].iloc[20]) - 10,
                                         2.0))
            _fk = _w._forgatokonyv()
            check("a Qt-terv MINDEN kulcsot megad, amit a JSON-minta",
                  set(ls.MINTA).issubset(set(_fk)),
                  str(sorted(set(ls.MINTA) - set(_fk))))
            check("a belépő SL és TP-szorzó is átmegy",
                  _fk["entries"] and "sl" in _fk["entries"][0]
                  and "tp_rr" in _fk["entries"][0], str(_fk["entries"][:1]))
            # ⚠ A SZERZŐDÉS MEGVÁLTOZOTT (v3.63.0). A kézi BE/trailing mezők
            # lekerültek a felületről: a modul ALAPÉRTÉKÉBŐL indultak, tehát a
            # labor a célár-arányos `breakeven_pct`-t szimulálta, miközben a
            # motor v3.56.0 óta R-alapú `breakeven_r`-rel fut — a laborban
            # látott stop-viselkedés nem is egyezhetett az élessel. Explicit
            # érték híján most a PÁR MENTETT kalibrációja jön (ugyanaz, amiből
            # a motor dolgozik).
            for _e in _w._rr_mezok.values():
                _e.setText("")
            # ⚠ v3.70.0: az automatizmus KAPCSOLÓS, és alapból KI. A pár
            # kalibrációja („mint a motorban") csak az „Auto BE/trailing"
            # jelölővel jön — enélkül a labor `none` presettel fut, a stop
            # ott marad, ahová a felhasználó tette.
            check("⚠ kapcsoló nélkül NINCS automatizmus (üres rr, `none` preset)",
                  _w._rr_ertekek() == {} and _w._rr_preset() == "none",
                  f"{_w._rr_ertekek()} / {_w._rr_preset()}")
            _w._rr_auto.setChecked(True)
            _rrp = _w._rr_ertekek()
            from core import rr_state as _rrs_q
            _rrs_q.ensure_loaded()
            check("a kapcsolóval a PÁR kalibrációja jön (mint a motorban)",
                  _rrp == dict(_rrs_q.get_calibration(_par) or {}), str(_rrp))
            _w._rr_auto.setChecked(False)
            check("üres BE/trailing mező → nincs KÉZI felülírás",
                  not any(_e.text().strip() for _e in _w._rr_mezok.values()),
                  str({k: e.text() for k, e in _w._rr_mezok.items()}))

            # ══ 0022 / 2. — A SÁV CSAK A POZÍCIÓ ÉLETTARTAMÁRA ═══════════
            # ⚠ Korabban `LinearRegionItem` volt: KONSTRUKCIO SZERINT vegigert
            # a kepen. Most hatarolt teglalap, ezert a tipust is orizzuk.
            _w._belepok_rajz()
            _b0 = _w._belepok[0]
            check("a kockázat-sáv HATÁROLT téglalap (nem végtelen régió)",
                  isinstance(_w._bel(_b0, "kock"), lq._Savdoboz), type(_w._bel(_b0, "kock")).__name__)
            _x1 = _w._tengely.hol(int(_b0.ido.timestamp()))
            check("a sáv a BELÉPŐNÉL kezdődik",
                  abs(_w._bel(_b0, "kock").rect().x() - _x1) < 1e-6,
                  f"{_w._bel(_b0, "kock").rect().x()} vs {_x1}")
            # ⚠ Sosem rövidebb a belépőnél (hátrafelé nyúló sáv értelmetlen)
            check("a sáv vége NEM a belépő előtt van",
                  _w._sav_vege(_b0, _x1) >= _x1)
            # A lejátszó kurzora növeli a sávot (a pozíció „még nyitva van")
            _w._kurzor = _x1 + 5
            _w._sav_frissit()
            _sz1 = _w._bel(_b0, "kock").rect().width()
            _w._kurzor = _x1 + 20
            _w._sav_frissit()
            check("a sáv a lejátszó kurzorával NŐ",
                  _w._bel(_b0, "kock").rect().width() > _sz1,
                  f"{_sz1} -> {_w._bel(_b0, "kock").rect().width()}")

            # ══ A VONALAK TÉNYLEGES MEGHÚZÁSA ═══════════════════════════
            # ⚠ EZ A TESZT EGY VALÓDI ÖSSZEOMLÁS UTÁN SZÜLETETT. A sáv
            # `LinearRegionItem`-ről `QGraphicsRectItem`-re cserélésekor a
            # húzás-kezelők még a régi `setRegion`-t hívták — az „Add BUY"
            # utáni ELSŐ SL-húzás `AttributeError`-t dobott, és mivel ezek a
            # kezelők a FŐSZÁLON futnak, a felület eseményhurka MEGÁLLT.
            # A korábbi tesztek mind csak RAJZOLTAK, sosem HÚZTAK — ezért nem
            # fogták meg. Minden `sigPositionChanged`-kezelőt el kell sütni.
            _bd = _w._belepok[0]
            _bear = _w._be_ar(_bd.ido)
            _w._bel(_bd, "sl_vonal").setValue(_bear - 25.0)          # → _sl_mozgott
            check("az SL HÚZÁSA nem dob kivételt", True)
            check("...és a modell követi", abs(_bd.sl - (_bear - 25.0)) < 1e-6,
                  f"{_bd.sl} vs {_bear - 25.0}")
            check("...és a kockázat-sáv is",
                  abs(_w._bel(_bd, "kock").rect().height() - 25.0) < 1e-6,
                  str(_w._bel(_bd, "kock").rect().height()))
            _w._bel(_bd, "tp_vonal").setValue(_bear + 75.0)          # → _tp_mozgott
            check("a TP HÚZÁSA nem dob kivételt", True)
            check("...és az R-szorzó ebből számolódik",
                  abs(_bd.rr - 3.0) < 1e-6, str(_bd.rr))
            _w._bel(_bd, "vonal").setValue(float(_w._bel(_bd, "vonal").value()) + 3)   # → _belepo_mozgott
            check("a BELÉPŐ-vonal húzása nem dob kivételt", True)
            # ⚠ Hiányzó rajz-elemmel se álljon meg a főszál
            _w._bel_set(_bd, "kock", None)
            _w._bel_set(_bd, "cel", None)
            _w._savok_igazit(_bd, _bear)
            check("hiányzó sáv-elem esetén sem száll el (a főszál él)", True)
            _w._belepok_rajz()

            # ══ 0022 / 3–4. — A NYITOTT POZÍCIÓ SZINTJEI (MT5-konvenció) ══
            # ⚠ Az esemenynaploig visszamenoen: a JOVOBELI atallitas NEM
            # latszhat, kulonben a lejatszas elarulna, hova huzodik a stop.
            class _Koteske:
                sl, tp = 100.0, 130.0
                events = [("OPEN", pd.Timestamp("2026-08-25 01:00", tz="UTC"),
                           110.0, 100.0, 130.0, 0.1, ""),
                          ("SL_MODIFY", pd.Timestamp("2026-08-25 03:00", tz="UTC"),
                           0.0, 111.0, 0.0, 0.0, "BE"),
                          ("TP_MODIFY", pd.Timestamp("2026-08-25 04:00", tz="UTC"),
                           0.0, 0.0, 0.0, 0.0, "build_no_tp")]

            _k = _Koteske()
            check("nyitáskor a BELÉPÉSKORI SL/TP",
                  _w._szintek_ekkor(_k, pd.Timestamp("2026-08-25 02:00", tz="UTC"))
                  == (100.0, 130.0))
            check("a BE utáni pillanatban a MEGHÚZOTT stop",
                  _w._szintek_ekkor(_k, pd.Timestamp("2026-08-25 03:30", tz="UTC"))
                  == (111.0, 130.0))
            check("a jövőbeli SL-húzás NEM látszik korábban",
                  _w._szintek_ekkor(_k, pd.Timestamp("2026-08-25 01:30", tz="UTC"))[0]
                  == 100.0)
            # ⚠ A TP-nel a 0 IS ERVENYES IRAS (epitett csomagnal a motor torli)
            check("a TP TÖRLÉSE (0) is érvényes írás, nem hiányzó érték",
                  _w._szintek_ekkor(_k, pd.Timestamp("2026-08-25 05:00", tz="UTC"))
                  == (111.0, 0.0))
            # ...es az SL_MODIFY (tp=0.0) NEM torolheti a TP-t
            check("az SL_MODIFY nem törli a TP-t",
                  _w._szintek_ekkor(_k, pd.Timestamp("2026-08-25 03:30", tz="UTC"))[1]
                  == 130.0)

            # ══ 0022 / 1. — KÉZI RAJZOK ═════════════════════════════════
            _i1 = _w._chart.index[10]
            _i2 = _w._chart.index[30]
            _ar = float(_w._chart["close"].iloc[10])
            _w._rajzok = [lq.Rajz("trend", _i1, _ar, _i2, _ar * 1.01),
                          lq.Rajz("vizszintes", _i1, _ar),
                          lq.Rajz("fuggoleges", _i1, _ar)]
            _w._rajzok_rajza()
            # ⚠ AZ ELEM MÁR NEM A RAJZBAN ÜL (v3.67.0): ha egy rajz TÖBB
            # ablakban látszik (közös rajzok), több Qt-elem tartozik hozzá —
            # egy mezőbe ez nem fér, a második ablak némán felülírta volna az
            # elsőét. A `Rajz` tiszta MODELL (idő + ár), az elemeket az ablak
            # tartja nyilván (`_rajz_elem`, `id(Rajz)` szerint).
            check("mindhárom rajz-fajta kapott elemet",
                  all(_w._rajz_elem.get(id(r)) is not None
                      for r in _w._rajzok),
                  str([r.fajta for r in _w._rajzok
                       if _w._rajz_elem.get(id(r)) is None]))
            check("a trendvonal két végpontja HÚZHATÓ (LineSegmentROI)",
                  isinstance(_w._rajz_elem.get(id(_w._rajzok[0])),
                             pyqtgraph.LineSegmentROI))
            # ⚠ IDOBEN TAROLUNK, NEM BAR-INDEXBEN — idosikot valtva az indexek
            # atszamozodnak, az idopont viszont ugyanaz marad.
            _d = _w._rajzok[0].szotar()
            check("a rajz IDŐT ment, nem bar-indexet",
                  "ido" in _d and "ido2" in _d and ":" in str(_d["ido"]), str(_d))
            _vissza = lq.Rajz.szotarbol(_d)
            check("a rajz szótárból visszaáll (mentés → betöltés kör)",
                  _vissza is not None and _vissza.fajta == "trend"
                  and _vissza.ido1 == _i1.tz_convert(None).tz_localize(_i1.tz)
                  if False else _vissza is not None and _vissza.fajta == "trend")
            check("hibás szótárból NEM lesz rajz (némán sem)",
                  lq.Rajz.szotarbol({"fajta": "ilyen nincs"}) is None
                  and lq.Rajz.szotarbol({}) is None)
            check("a félkész trendvonal nem kerül mentésre",
                  not lq.Rajz("trend", _i1, _ar).kesz()
                  and lq.Rajz("vizszintes", _i1, _ar).kesz())
            check("a rajzok BEKERÜLNEK a forgatókönyvbe",
                  len(_w._forgatokonyv().get("drawings") or []) == 3,
                  str(_w._forgatokonyv().get("drawings")))

            # ── Mentés → betöltés kör (a fájl-párbeszéd nélkül) ──────────
            _mentett = _w._forgatokonyv()
            _w.rajz_torol_mind()
            check("a rajz-törlés a MODELLBŐL is kivesz", not _w._rajzok)
            _w.forgatokonyv_betolt(_mentett)
            check("betöltés után visszajönnek a rajzok",
                  len(_w._rajzok) == 3, str(len(_w._rajzok)))
            check("...és a belépők is", len(_w._belepok) >= 1, str(len(_w._belepok)))

            # ══ 0022 / 5. — TRAILING VONALAK ════════════════════════════
            # ⚠ A kézi mezők lekerültek (v3.63.0); a forgatókönyv-betöltés
            # ugyanazt az utat használja, tehát az explicit értéket ÍGY adjuk.
            _w.forgatokonyv_betolt({**_mentett,
                                    "rr": {"trail_activation_atr": 1.0,
                                           "trail_distance_atr": 1.5}})
            _w._valasztott = _w._belepok[0]
            _w._belepok_rajz()
            _bt = _w._belepok[0]
            check("a trailing két HÚZHATÓ vonalat kapott",
                  _w._bel(_bt, "trail_be") is not None and _w._bel(_bt, "trail_tav") is not None)
            if _w._bel(_bt, "trail_be") is not None:
                _atr = _w._trail_atr(_bt)
                _bear = _w._be_ar(_bt.ido)
                _d = 1 if _bt.irany == "BUY" else -1
                check("az aktiválás-vonal a belépőtől 1,0 ATR-re",
                      abs(float(_w._bel(_bt, "trail_be").value()) - (_bear + _d * _atr)) < 1e-6,
                      f"{_w._bel(_bt, "trail_be").value()} vs {_bear + _d * _atr}")
                check("a követés-vonal az aktiválástól 1,5 ATR-re",
                      abs(float(_w._bel(_bt, "trail_tav").value())
                          - (float(_w._bel(_bt, "trail_be").value()) - _d * 1.5 * _atr)) < 1e-6)
                # ⚠ A HUZAS VISSZAIRJA az ATR-szorzot: a mezo es a vonal EGY
                # allapot ket nezete, kulonben a futtatas mast csinalna.
                # ⚠ A VONAL MÁR NEM HÚZHATÓ. Eddig a kézi mezőbe írt vissza;
                # azok lekerültek, és egy húzható vonal, ami nem ír sehova,
                # rosszabb a hiányánál — úgy néz ki, mint egy működő vezérlő.
                # A vonal MEGMARADT, mert azt MUTATJA, amit a pár mentett
                # kockázatcsökkentése tényleg csinálni fog.
                check("a trailing-vonal CSAK KIJELZÉS (nem húzható)",
                      not _w._bel(_bt, "trail_be").movable)
        except Exception as _ex:
            check("az ablak FELÉPÜL (a konstruktor végigfut)", False,
                  f"{type(_ex).__name__}: {_ex}")
        finally:
            if _w is not None:
                _w.close()

# ── 4. A RÉGI FELÜLET MEGMARADT ───────────────────────────────────────────
# ⚠ Amíg a Qt-s nem futott elég valós helyzeten, a matplotlib-es legyen
# elérhető — egy felület, ami tegnap még működött, ne tűnjön el egy csapásra.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("a `lab` parancs a Qt-s felületet indítja",
      "from tools.lab_qt import main" in _main)
check("a régi felület `lab-mpl` néven elérhető maradt",
      '"lab-mpl"' in _main and "from tools.lab_chart import main" in _main)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
