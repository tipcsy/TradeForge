"""A rajz azon a chart-idosikon jelenjen meg, amelyiken a strategia DONT.

⚠ A LELET (a felhasznalotol, 2026-08-17): „Inkabb M1-en es M5-M15-on ne jelenjen
meg semmi. Ha meg akarom nezni a bollingert, akkor azt eleg ha H1-en vagy a
beallitott idosikon mutatja."

Az ok szerkezeti: a viz-fajl egy SZIMBOLUM teljes pillanatkepe, es a szimbolum
MINDEN nyitott chartja UGYANABBOL a fajlbol olvas. Az indikator eddig csak
strategia szerint tudott szurni (`InpStrategy`), idosik szerint sehogy — a H1-en
szamolt Bollinger-szalag tehat az M1 charton is kirajzolodott. Az pedig nem
„ugyanaz kisebbben": FELREVEZETO, mert nem azt mutatja, amit a dontes hasznal.

A megoldas a MEGLEVO varraton (`signal_bar_seconds`) all: a strategia mar
megmondja, milyen hosszu a dontesi gyertyaja (ugyanez dedupalja a riasztast). Aki
a VEGREHAJTASI gyertyan dont (wpr_sma -> 0), annak nincs kikotese: mindenhol
latszik, ahogy eddig.

⚠ ES KET DOLOG, AMI NEM ESHET AT A KAPUN:
  • a RIASZTAS (ALERT) — az nem rajz; egy elrejtett szalag mellett elnemitott
    jelzes csendben elvinne egy belepot;
  • a NEMASAG — ahol elrejtettuk a rajzot, egy apro felirat megmondja, HOL
    nezheto meg; kulonben ugy tunne, a strategia nem rajzol semmit.
"""
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
from strategy.visual import TfOnly, tag_line

# ── 1. A PRIMITIV ─────────────────────────────────────────────────────────
check("a sor formatuma TFONLY;<perc>", TfOnly(minutes=60).line() == "TFONLY;60",
      TfOnly(minutes=60).line())
# ⚠ NEVTELEN sor: a strategia a TIPUS UTAN kerul (mint a STATE/IND/ALERT),
# nem egy nev-mezobe — kulonben az indikator a nevbol probalna kiolvasni.
check("a strategia a TIPUS UTAN kerul",
      tag_line(TfOnly(minutes=60).line(), "bollinger_squeeze_breakout")
      == "TFONLY;bollinger_squeeze_breakout;60",
      tag_line(TfOnly(minutes=60).line(), "bollinger_squeeze_breakout"))
check("strategia nelkul valtozatlan (egy-strategias, regi ut)",
      tag_line(TfOnly(minutes=60).line(), "") == "TFONLY;60")


# ── 2. KI KAP KIKOTEST ───────────────────────────────────────────────────
# ⚠ A varrat mar letezett: ugyanaz mondja meg a dontesi gyertya hosszat, ami a
# riasztast dedupalja. Uj forras = ket igazsag, ami elcsuszhat egymastol.
from strategy.settings import load_strategy_config


def _min(name):
    st = get_strategy_by_name(name)
    return st.signal_bar_seconds(st.base_params(load_strategy_config(name))) // 60


check("bollinger -> H1 (60 perc)", _min("bollinger_squeeze_breakout") == 60,
      str(_min("bollinger_squeeze_breakout")))
check("ml_ai -> M15", _min("ml_ai") == 15, str(_min("ml_ai")))
# ⚠ EZ A VISSZAFELE KOMPATIBILITAS: a wpr_sma a vegrehajtasi gyertyan dont, tehat
# NINCS kikotese — a rajza minden idosikon marad, ahogy eddig.
check("wpr_sma -> nincs kikotes (0)", _min("wpr_sma") == 0)

_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a keret a MEGLEVO varratbol szarmaztatja",
      "strategy.signal_bar_seconds(params)" in _lt)
check("...es csak egesz percnel kuld sort (0 -> semmi)",
      "if _sig_sec >= 60:" in _lt)
# ⚠ A DEKLARACIO a sajat objektumai ELE kerul: az MT4-valtozat egy menetben
# olvas, ott a sorrend DONT.
check("a deklaracio az objektumok ELE kerul",
      "[_TfOnly(minutes=_sig_sec // 60)] + objects" in _lt)


# ── 3. ELES MERES a valodi viz-sorokon ───────────────────────────────────
try:
    import logging
    from strategy.settings import load_config, config_for_strategy
    from core import mt5_connector as _C
    from trading.live_trader import (pair_visual_lines, strategy_params,
                                     default_params)
    cfg = load_config("config.json")
    _C.connect(cfg)
    _live = bool(_C.connection_info(cfg).get("connected"))
except Exception:
    _live = False

if _live:
    logging.disable(logging.INFO)
    sym = next(s for s in cfg["pairs"] if not s.startswith("_"))
    _out = {}
    for _n in ("wpr_sma", "bollinger_squeeze_breakout"):
        _st = get_strategy_by_name(_n)
        _cs = config_for_strategy(cfg, _n)
        _p = strategy_params(sym, _n, _cs, fallback=default_params(_st, _cs))
        _pc = cfg["pairs"][sym]
        _out[_n] = pair_visual_lines(sym, _p, _st, _pc["point_size"], _pc, cfg=_cs)
    logging.disable(logging.NOTSET)

    _bb = _out["bollinger_squeeze_breakout"]
    _tf = [l for l in _bb if l.startswith("TFONLY")]
    check(f"[{sym}] a bollinger sorai kozott OTT a kikotes",
          _tf == ["TFONLY;bollinger_squeeze_breakout;60"], str(_tf))
    if _bb:
        check(f"[{sym}] ...meghozza ELSOKENT", _bb[0].startswith("TFONLY;"), _bb[0])
    check(f"[{sym}] a wpr_sma sorai kozott NINCS",
          not [l for l in _out["wpr_sma"] if l.startswith("TFONLY")])
else:
    check("nincs MT5-kapcsolat (az eles meres kihagyva)", True)


# ── 4. AZ MT5 INDIKATOR ──────────────────────────────────────────────────
_m5 = (ROOT / "mt5" / "TradeForgeViz.mq5").read_text(encoding="utf-8")
check("mq5: ismeri a TFONLY sort", 'StringFind(raw[r], "TFONLY;") == 0' in _m5)
# ⚠ A LEGKONNYEBBEN ELNEZETT HIBA: MT5-ben a `Period()` ENUM-ot ad
# (PERIOD_H1 == 16385), NEM percet. Azzal osszehasonlitva a kapu MINDEN idosikon
# zarna, es a rajz SEHOL nem jelenne meg.
_i = _m5.find("bool TfBlocked")
_blk = _m5[_i:_i + 900]
check("mq5: PERCBEN hasonlit (PeriodSeconds), nem az enummal",
      "PeriodSeconds() / 60" in _blk and "(int)Period() !=" not in _blk, _blk[:0])
check("mq5: kikotes nelkul NEM kapuz (visszafele kompatibilis)",
      "return false;   // nincs kikötés" in _blk)
# ⚠ KET MENET: a kikotest a strategia MINDEN objektuma elott ismerni kell.
# Egy menetben ez a sorrendtol fuggene — a fajlformatum nema fuggosege lenne.
check("mq5: elobb beolvas, csak utana rajzol (ket menet)",
      "TfReset();" in _m5 and _m5.find("TfReset();") < _m5.find("ApplyLine(ln)"))
# ⚠ A RIASZTAS ATMEGY a kapun.
_ai = _m5.find('if(StringFind(ln, "ALERT;") == 0)')
check("mq5: a riasztast NEM kapuzza", "HandleAlert(ln);" in _m5[_ai:_ai + 600])
check("...es ki is mondja, miert", "elnémított jelzés" in _m5[_ai:_ai + 600])
# ⚠ A KAPU NEM NEMA.
check("mq5: felirat mondja meg, HOL nezheto meg",
      "charton látszik" in _m5 and "string TfNote(" in _m5)
check("mq5: az IND (al-ablak) sorokat is kapuzza",
      "TfBlocked(fi[1])" in _m5)

# ── 5. AZ MT4 INDIKATOR ──────────────────────────────────────────────────
_m4 = (ROOT / "mt4" / "TradeForgeViz.mq4").read_text(encoding="utf-8")
check("mq4: ismeri a TFONLY sort", 'StringFind(ln, "TFONLY;") == 0' in _m4)
# ⚠ ES ITT FORDITVA: MT4-ben a `Period()` MAR percet ad — nincs PeriodSeconds().
_i4 = _m4.find("bool TfBlocked")
_blk4 = _m4[_i4:_i4 + 800]
check("mq4: a Period() itt MAR perc", "Period() != g_tf_min[i]" in _blk4)
check("mq4: a szurot a strategia-szuro UTAN alkalmazza",
      "if(TfBlocked(name))" in _m4
      and _m4.find("g_objpref) != 0") < _m4.find("if(TfBlocked(name))"))

# ── 6. A VERZIOK: a felhasznalonak UJRA KELL FORDITANIA ─────────────────
# ⚠ Ha a verzio nem valtozik, a felhasznalo nem tudja, MELYIK fordul epp —
# ez mar egyszer megtortent (TradeForgeBands 2.44).
import re


def _ver(p):
    m = re.search(r'#property\s+version\s+"([\d.]+)"',
                  (ROOT / p).read_text(encoding="utf-8"))
    return m and m.group(1)


check("mq5 verzio felemelve", _ver("mt5/TradeForgeViz.mq5") == "2.62",
      str(_ver("mt5/TradeForgeViz.mq5")))
check("mq4 verzio UGYANAZ (egyutt fordulnak)",
      _ver("mt4/TradeForgeViz.mq4") == _ver("mt5/TradeForgeViz.mq5"),
      f"{_ver('mt4/TradeForgeViz.mq4')} vs {_ver('mt5/TradeForgeViz.mq5')}")


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
