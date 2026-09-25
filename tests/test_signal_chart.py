"""
Telegram JELZÉS-KÉP (v3.106.0) — M15 + M1 gyertyák, Entry/SL/TP, SMA és WPR.

A felhasznalo kerese (2026-09-25): „amikor erkezik egy jelzes, kuldjon egy
kepet is az aktualis beszallorol — M1 es M15", a WPR jelzesevel kulon panelen,
es a JOVAHAGYO (gombos) ajanlatra is.

Amit orzunk:
  1. a rajz elkeszul (PNG), spec nelkul is; a tavoli celar nem hibazik;
  2. a kepfeltoltes multipart-torzse helyes, a hosszu alairas nem vesz el;
  3. a jovahagyas utani ATIRAS kepes uzenetnel is mukodik (editMessageCaption
     tartalek) — enelkul a gombok a kepen maradnanak, ujra megnyomhatoan;
  4. a KEP SOSEM NYELI EL AZ UZENETET: rajz-hiba / kuldes-hiba → szoveg megy;
  5. a jovahagyo ajanlat kepe KULON SZALON keszul (a motor nem var), es ha a
     kep elbukik, a gombos szoveg akkor is kimegy;
  6. ha az ajanlat mar kepes volt, a sima jelzes-uzenet NEM kap masodik kepet.

⚠ Halozat, MT5 es valodi config NELKUL: minden kulso fuggoseg cserelve.
"""

import json
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.applog as _applog
_applog.harden_console()

import numpy as np                                  # noqa: E402
import pandas as pd                                 # noqa: E402

from core import signal_chart as sc                 # noqa: E402
from core import telegram as tg                     # noqa: E402
from core import notify as nt                       # noqa: E402

_results = []
_fail = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail else ""))
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)


def _bars(n, freq, start=100.0):
    idx = pd.date_range("2026-09-25 08:00", periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(3)
    c = start + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame({"open": c, "high": c + 0.3, "low": c - 0.3, "close": c},
                        index=idx)


SPEC = {"sma": {"tf": 15, "period": 50},
        "panels": [{"kind": "wpr", "tf": 15, "period": 21,
                    "levels": [-20, -50, -50, -80]},
                   {"kind": "wpr", "tf": 1, "period": 21,
                    "levels": [-20, -50, -50, -80]}]}
PNG = b"\x89PNG"

# ══ 1. A rajz ══════════════════════════════════════════════════════════════
print("== 1. rajz ==")
b = {15: _bars(sc.bars_needed(SPEC, 15), "15min"), 1: _bars(sc.bars_needed(SPEC, 1), "1min")}
e = float(b[1]["close"].iloc[-1])
png = sc.render_png("X", "BUY", e, e - 1, e + 2, b, SPEC, digits=2)
check("PNG keszul (4 panel)", png[:4] == PNG and len(png) > 5000, len(png))
check("spec NELKUL is keszul (csak gyertyak + szintek)",
      sc.render_png("X", "SELL", e, e + 1, e - 2, b, {}, digits=2)[:4] == PNG)
check("TAVOLI celar (15R) nem hibazik", sc.render_png(
    "X", "BUY", e, e - 1, e + 500, b, SPEC, digits=2)[:4] == PNG)
check("TP nelkul is keszul", sc.render_png("X", "BUY", e, e - 1, None, b, SPEC)[:4] == PNG)
check("csak M1 is eleg", sc.render_png("X", "BUY", e, e - 1, e + 2, {1: b[1]})[:4] == PNG)
try:
    sc.render_png("X", "BUY", e, e - 1, e + 2, {})
    check("gyertya nelkul ValueError (a hivo szoveget kuld)", False)
except ValueError:
    check("gyertya nelkul ValueError (a hivo szoveget kuld)", True)
check("bars_needed: lathato resz + 2x a leghosszabb bemelegites (EMA-memoria)",
      sc.bars_needed(SPEC, 15) == sc.SHOW[15] + 2 * 50 + 2
      and sc.bars_needed(SPEC, 1) == sc.SHOW[1] + 2 * 21 + 2)
check("fetch_bars: a hibas idosik kimarad, a masik megmarad",
      set(sc.fetch_bars("X", SPEC, lambda tf, n: b[1] if tf == 1 else 1 / 0)) == {1})

# ══ 2. Kepfeltoltes ════════════════════════════════════════════════════════
print("== 2. send_photo ==")
body, ctype = tg._multipart({"chat_id": "7", "caption": "szia"}, "photo", "a.png", PNG)
check("multipart: boundary a content-type-ban",
      ctype.startswith("multipart/form-data; boundary="))
check("multipart: mezok + fajl a torzsben",
      b'name="chat_id"' in body and b'name="photo"; filename="a.png"' in body
      and PNG in body)

_hivasok = []


class _Resp:
    def __init__(self, d):
        self._d = d

    def read(self):
        return json.dumps(self._d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_orig_urlopen = tg.urllib.request.urlopen
_orig_send, _orig_btn = tg.send, tg.send_buttons
tg.urllib.request.urlopen = lambda req, timeout=None: (
    _hivasok.append(req.full_url), _Resp({"ok": True}))[1]
tg.send = lambda token, ids, txt: _hivasok.append(("send", txt)) or True
tg.send_buttons = lambda token, cid, txt, g: _hivasok.append(("btn", txt)) or True
try:
    check("rovid alairas: EGY sendPhoto",
          tg.send_photo("T", 7, PNG, "rovid") and _hivasok == [
              f"{tg.API}/botT/sendPhoto"], _hivasok)
    _hivasok.clear()
    hosszu = "elso sor\n" + "x" * 1500
    tg.send_photo("T", 7, PNG, hosszu, gombok=[("Igen", "a:1")])
    check("HOSSZU alairas: kep + a teljes szoveg GOMBOKKAL kulon",
          any(isinstance(h, tuple) and h[0] == "btn" and h[1] == hosszu
              for h in _hivasok), _hivasok[:2])
finally:
    tg.urllib.request.urlopen = _orig_urlopen
    tg.send, tg.send_buttons = _orig_send, _orig_btn

# ══ 3. Atiras kepes uzenetnel ══════════════════════════════════════════════
print("== 3. edit_message tartalek ==")
_orig_h = tg._hivas
_m = []


def _stub_hivas(token, metodus, body, timeout=None):
    _m.append(metodus)
    if metodus == "editMessageText":
        return True, {"ok": False, "description": "there is no text in the message"}
    return True, {"ok": True}


tg._hivas = _stub_hivas
try:
    check("kepes uzenet: editMessageText bukik -> editMessageCaption",
          tg.edit_message("T", 7, 99, "Megkotve") and _m == [
              "editMessageText", "editMessageCaption"], _m)
finally:
    tg._hivas = _orig_h

# ══ 4. Az ertesito: kep vagy szoveg ════════════════════════════════════════
print("== 4. Notifier ==")
cfg = nt.Config(enabled=True, token="T", chat_ids=("7",))
szoveg, foto = [], []
n = nt.Notifier(cfg, transport=lambda t: szoveg.append(t) or True,
                photo_transport=lambda p, c: foto.append(c) or True,
                chart_maker=lambda ch: PNG)
ev = nt.Event(kind=nt.SIGNAL, text="JELZES", symbol="X", strategy="s",
              chart={"symbol": "X"})
n._kuld(ev)
check("kep-adattal KEP megy (nem szoveg)", foto == ["JELZES"] and not szoveg)
n2 = nt.Notifier(cfg, transport=lambda t: szoveg.append(t) or True,
                 photo_transport=lambda p, c: foto.append(c) or True,
                 chart_maker=lambda ch: 1 / 0)
szoveg.clear(); foto.clear()
n2._kuld(ev)
check("a RAJZ elszall -> a SZOVEG kimegy", szoveg == ["JELZES"] and not foto)
n3 = nt.Notifier(cfg, transport=lambda t: szoveg.append(t) or True,
                 photo_transport=lambda p, c: False, chart_maker=lambda ch: PNG)
szoveg.clear()
n3._kuld(ev)
check("a KEP-KULDES bukik -> a SZOVEG kimegy", szoveg == ["JELZES"])
n4 = nt.Notifier(nt.Config(enabled=True, token="T", chat_ids=("7",),
                           signal_chart=False),
                 transport=lambda t: szoveg.append(t) or True,
                 photo_transport=lambda p, c: foto.append(c) or True,
                 chart_maker=lambda ch: PNG)
szoveg.clear(); foto.clear()
n4._kuld(ev)
check("signal_chart=False -> csak szoveg", szoveg == ["JELZES"] and not foto)
check("config: signal_chart alapbol BE",
      nt.read_config({"notify": {}}).signal_chart is True
      and nt.read_config({"notify": {"signal_chart": False}}).signal_chart is False)

# trade_event: a kep-adat a sorbol, es NINCS masodik kep az ajanlat utan
_elkapott = []
_orig_kuld = nt._kuld
nt._kuld = lambda e: _elkapott.append(e) or True
try:
    row = {"event": "signal", "symbol": "X", "strategy": "wpr_sma",
           "direction": "BUY", "lot": 0.1, "price": 100.0, "sl": 99.0,
           "tp": 102.0, "chart_spec": SPEC, "offered": False}
    nt.trade_event(row)
    check("jelzes-sor chart_spec-kel -> kep-adat az esemenyen",
          _elkapott[-1].chart and _elkapott[-1].chart["entry"] == 100.0
          and _elkapott[-1].chart["spec"] == SPEC)
    nt.trade_event({**row, "offered": True})
    check("ha az ajanlat MAR kepes volt -> nincs masodik kep",
          _elkapott[-1].chart is None)
    nt.trade_event({k: v for k, v in row.items() if k != "chart_spec"})
    check("chart_spec nelkuli sor (regi hivo) -> sima szoveg",
          _elkapott[-1].chart is None)
    nt.trade_event({**row, "event": "close", "pnl_usd": 1.0})
    check("zaras soha nem kepes", _elkapott[-1].chart is None)
finally:
    nt._kuld = _orig_kuld

# ══ 5. A jovahagyo ajanlat: kep + gombok, KULON szalon ═════════════════════
print("== 5. signal_offer ==")


class _Ajanlat:
    id = "q1"; symbol = "X"; strategy = "wpr_sma"; direction = "BUY"
    lot = 0.1; entry = 100.0; created = 0.0; expires = 300.0

    def celok(self, e):
        return e - 1, e + 2

    def fmt(self, v):
        return f"{v:.2f}"


kuldesek = []
_szalnev = []
_o_photo, _o_btn = tg.send_photo, tg.send_buttons
tg.send_photo = lambda token, cid, png, cap, gombok=None: (
    kuldesek.append(("photo", cid, bool(gombok))) or True)
tg.send_buttons = lambda token, cid, txt, g: kuldesek.append(("btn", cid)) or True
_o_aktiv, _o_cfg = nt._aktiv, nt._cfg_json
nt._aktiv = nt.Notifier(cfg, chart_maker=lambda ch: (
    _szalnev.append(threading.current_thread().name) or PNG))
nt._cfg_json = {}
try:
    _szal_elotte = set(threading.enumerate())
    ok = nt.signal_offer(_Ajanlat(), chart_spec=SPEC)
    for th in set(threading.enumerate()) - _szal_elotte:
        th.join(timeout=5)
    check("az ajanlat KEPPEL + GOMBOKKAL ment ki",
          ok and kuldesek == [("photo", "7", True)], kuldesek)
    check("...a rajz KULON szalon keszult (a motor nem var ra)",
          _szalnev == ["TradeForgeOfferChart"]
          and threading.current_thread().name != "TradeForgeOfferChart", _szalnev)
    kuldesek.clear()
    nt._aktiv = nt.Notifier(cfg, chart_maker=lambda ch: 1 / 0)
    _szal_elotte = set(threading.enumerate())
    nt.signal_offer(_Ajanlat(), chart_spec=SPEC)
    for th in set(threading.enumerate()) - _szal_elotte:
        th.join(timeout=5)
    check("a kep elbukik -> a GOMBOS SZOVEG akkor is kimegy",
          kuldesek == [("btn", "7")], kuldesek)
    kuldesek.clear()
    nt.signal_offer(_Ajanlat())
    check("chart_spec nelkul (regi hivo) -> a regi gombos szoveg, szinkron",
          kuldesek == [("btn", "7")], kuldesek)
finally:
    tg.send_photo, tg.send_buttons = _o_photo, _o_btn
    nt._aktiv, nt._cfg_json = _o_aktiv, _o_cfg

# ══ 6. A strategia mondja meg, mit rajzoljon ═══════════════════════════════
print("== 6. chart_spec ==")
from strategy import get_strategy_by_name                # noqa: E402
w = get_strategy_by_name("wpr_sma").chart_spec(
    {"sma_period": 120, "wpr_m15_period": 13, "wpr_m1_period": 9,
     "wpr_m15_sell_extreme": -15, "wpr_m15_buy_extreme": -85})
check("wpr_sma: M15 SMA a sajat periodusaval", w["sma"] == {"tf": 15, "period": 120})
check("wpr_sma: KET WPR-panel (M15 + M1) a sajat szintjeivel",
      [(p["tf"], p["period"]) for p in w["panels"]] == [(15, 13), (1, 9)]
      and w["panels"][0]["levels"][0] == -15 and w["panels"][0]["levels"][3] == -85)
from strategy.base import Strategy as _Base              # noqa: E402
check("a KERET alapertelmezese ures spec (a kep akkor is keszul)",
      _Base.chart_spec(get_strategy_by_name("ml_ai"), {}) == {})

# ══ 7. /photo parancs ══════════════════════════════════════════════════════
print("== 7. /photo ==")
from core import console_cmd as cc                       # noqa: E402
from core import telegram_cmd as tc                      # noqa: E402

_kert = []


def _ctx(chart=None):
    return cc.Context(
        cfg={"pairs": {"UsaTec": {"enabled": True}, "UsaInd": {"enabled": True},
                       "Ger40": {"enabled": True}}},
        save_config=lambda: True, positions=list, close_position=lambda t: True,
        account=dict, dashboard={}, instrument_state={},
        strategies_of=lambda s: ["wpr_sma"],
        chart_png=chart or (lambda s, t: (_kert.append((s, t)) or PNG, "wpr_sma")))


r = cc.dispatch(_ctx(), "photo UsaTec M15")
check("/photo UsaTec M15 -> kep, csak M15", r.photo == PNG and _kert[-1] == ("UsaTec", (15,)))
r = cc.dispatch(_ctx(), "/photo ger40")
check("idosik nelkul a STRATEGIA sajat idosikjai (None), kisbetus nev is jo",
      r.photo == PNG and _kert[-1] == ("Ger40", None))
r = cc.dispatch(_ctx(), "photo UsaTech M1")
check("ELGEPELES (UsaTech) -> UsaTec, es kiirja, melyiket",
      r.photo == PNG and _kert[-1] == ("UsaTec", (1,)) and "UsaTec" in r.lines[0],
      r.lines)
r = cc.dispatch(_ctx(), "photo usatec")
check("csak kis/nagybetu elteres -> NINCS „→” sor (nem elgepeles)",
      r.photo == PNG and len(r.lines) == 1 and "→" not in r.lines[0], r.lines)
r = cc.dispatch(_ctx(), "photo Usa")
check("tobb jelolt -> NEM talalgat, felsorolja",
      not r.photo and "UsaTec" in r.lines[0] and "UsaInd" in r.lines[0], r.lines)
r = cc.dispatch(_ctx(), "photo UsaTec H4")
check("H4 is kerheto", r.photo == PNG and _kert[-1] == ("UsaTec", (240,)))
r = cc.dispatch(_ctx(), "photo UsaTec D7")
check("ismeretlen idosik -> hasznalati sugo", not r.photo and not r.ok)
r = cc.dispatch(_ctx(), "photo")
check("argumentum nelkul -> hasznalati sugo", not r.photo and not r.ok)
r = cc.dispatch(_ctx(lambda s, t: (b"", "")), "photo UsaTec")
check("nincs adat -> hibauzenet, nem ures kep", not r.photo and not r.ok)
r = cc.dispatch(_ctx(lambda s, t: 1 / 0), "photo UsaTec")
check("a rajz elszall -> hibauzenet (nem dol ossze a bot)", not r.photo and not r.ok)

bot = tc.Bot(token="T", chat_ids=("7",), ctx=_ctx())
out = bot.feldolgoz({"message": {"chat": {"id": 7}, "text": "/photo UsaTec M15"}})
check("a bot a /photo-t ENGEDI es kepet ad vissza",
      len(out) == 1 and out[0].photo == PNG and "UsaTec" in out[0].text)
check("a /photo a Telegram-menuben is ott van",
      "photo" in [n for n, _ in tc.parancs_lista()])
_kuldve = []
_o_photo2, _o_send2 = tg.send_photo, tg.send
tg.send_photo = lambda token, cid, png, cap, gombok=None: _kuldve.append("photo") or True
tg.send = lambda token, ids, txt: _kuldve.append("text") or True
try:
    bot.kuld(out[0])
    check("a kimenet KEPKENT megy", _kuldve == ["photo"], _kuldve)
    tg.send_photo = lambda token, cid, png, cap, gombok=None: False
    _kuldve.clear()
    bot.kuld(out[0])
    check("ha a kep nem megy ki, az alairas szovegkent igen", _kuldve == ["text"], _kuldve)
finally:
    tg.send_photo, tg.send = _o_photo2, _o_send2

_kert.clear()
_c2 = _ctx(lambda s, t, only=None: (_kert.append((s, t, only)) or PNG, "wpr_sma"))
r = cc.dispatch(_c2, "photo UsaTech M15 wpr")
check("/photo UsaTech M15 wpr -> CSAK a WPR, M15",
      r.photo == PNG and _kert[-1] == ("UsaTec", (15,), "wpr") and "WPR" in r.lines[-1],
      (_kert, r.lines))
r = cc.dispatch(_c2, "photo UsaTec wpr m1")
check("a szavak sorrendje mindegy", _kert[-1] == ("UsaTec", (1,), "wpr"))
r = cc.dispatch(_c2, "photo UsaTec wpr")
check("csak-WPR idosik nelkul -> a strategia idosikjai",
      _kert[-1] == ("UsaTec", None, "wpr"))


def _nincs(s, t, only=None):
    raise ValueError("nincs wpr panel")


r = cc.dispatch(_ctx(_nincs), "photo UsaTec wpr")
check("WPR nelkuli strategia -> ertheto uzenet", not r.photo and "WPR" in r.lines[0],
      r.lines)
check("csak-WPR rajz: elkeszul (M15)",
      sc.render_png("X", "", None, None, None, b, SPEC, tfs=(15,), only="wpr")[:4] == PNG)
try:
    sc.render_png("X", "", None, None, None, b, {}, only="wpr")
    check("spec wpr nelkul + only=wpr -> ValueError", False)
except ValueError:
    check("spec wpr nelkul + only=wpr -> ValueError", True)

# ── WPR-ertekek az alairasban ──
_v = sc.panel_values(b, SPEC)
check("panel_values: M15 es M1 WPR az utolso lezart gyertyan",
      [n for n, _ in _v] == ["WPR M15", "WPR M1"] and all(-100 <= x <= 0 for _, x in _v), _v)
check("values_text: egesz szamra kerekitve",
      sc.values_text([("WPR M15", -44.4), ("WPR M1", -79.6)]) == "WPR M15: -44 · WPR M1: -80")
r = cc.dispatch(_ctx(lambda s, t, only=None: (PNG, "wpr_sma",
                                              [("WPR M15", -44.2), ("WPR M1", -80.4)])),
                "photo UsaTec")
check("/photo alairas: a WPR ertekei is benne",
      r.lines[-1].endswith("· WPR M15: -44 · WPR M1: -80"), r.lines)
_fk = []
n5 = nt.Notifier(cfg, transport=lambda t: True,
                 photo_transport=lambda p, c: _fk.append(c) or True,
                 chart_maker=lambda ch: (PNG, "WPR M15: -44 · WPR M1: -80"))
n5._kuld(ev)
check("jelzes-kep alairasa: a szoveg + a WPR ertekei",
      _fk == ["JELZES\nWPR M15: -44 · WPR M1: -80"], _fk)

# pillanatkep-rajz: belepo NELKUL
png = sc.render_png("X", "", None, None, None, b, SPEC, digits=2, tfs=(15,))
check("pillanatkep (belepo nelkul, csak M15) elkeszul", png[:4] == PNG)

# ══ 8. A tobbi strategia kepe ══════════════════════════════════════════════
print("== 8. mas strategiak ==")
from strategy.settings import default_params as _dp      # noqa: E402
_cfg0 = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
_m1 = _bars(60 * 24 * 12, "1min", 30000.0)


def _fetch(tf, n):
    from core.indicator_engine import resample_ohlc
    d = _m1 if tf == 1 else resample_ohlc(_m1[["open", "high", "low", "close"]], tf)
    return d.iloc[-n:]


_vart = {"trend_pullback": ([60, 5], {"keltner"}, {"stoch"}),
         "bollinger_squeeze_breakout": (None, {"bb", "keltner", "ema"}, set()),
         "pending_straddle": (None, set(), {"wpr"}),
         "csilla": (None, set(), set())}
for _n, (_tfs, _ov, _pn) in _vart.items():
    _st = get_strategy_by_name(_n)
    _sp = _st.chart_spec(_dp(_st, _cfg0) or {})
    check(f"{_n}: van sajat kep-spec (idosikok)", bool(_sp.get("tfs")), _sp)
    if _tfs:
        check(f"{_n}: a sajat idosikjai", _sp["tfs"] == _tfs, _sp["tfs"])
    check(f"{_n}: a vart overlay-k",
          {o["kind"] for o in _sp.get("overlays") or ()} == _ov)
    check(f"{_n}: a vart panelek",
          {q["kind"] for q in _sp.get("panels") or ()} == _pn)
    _bb = sc.fetch_bars("X", _sp, _fetch)
    _e = float(_m1["close"].iloc[-1])
    check(f"{_n}: a kep elkeszul a sajat idosikjain",
          set(_bb) == set(sc.spec_tfs(_sp)) and sc.render_png(
              "X", "BUY", _e, _e - 5, _e + 10, _bb, _sp)[:4] == PNG, sorted(_bb))
_tp = get_strategy_by_name("trend_pullback").chart_spec({})
check("Stoch-ertek az alairasban (trend_pullback)",
      [n for n, _ in sc.panel_values(sc.fetch_bars("X", _tp, _fetch), _tp)]
      == ["Stoch M5"])
check("tf_label: M1 / M15 / H1 / H4",
      [sc.tf_label(t) for t in (1, 15, 60, 240)] == ["M1", "M15", "H1", "H4"])

print(f"\n{sum(_results)}/{len(_results)} teszt PASS")
if _fail:
    print("Bukott:", ", ".join(_fail))
sys.exit(0 if all(_results) else 1)
