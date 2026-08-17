"""Optimalizalas NELKUL is indithato egy strategia — a sajat alapertekeivel.

⚠ A LELET. A bollinger strategiat 9 parbol 6-on EGYALTALAN nem lehetett
elinditani: a Play gomb megtagadta („nincs parameterkeszlet — elobb futtasd az
OPT-ot"), a motor pedig `strategy_params() -> None` miatt kihagyta a part. Egy UJ
strategia igy minden paron hasznalhatatlan volt, amig le nem futott ra egy tobb
oras optimalizalas — akkor is, ha az alapertekei epp jok.

A doksi kerese ennek az ELLENKEZOJE (Dashboard/Live szakasz): „minden
strategianak van egy alapertelmezett paramétere. Ha betoltunk egy instrumentumot,
az alapertelmezett parametereket vegye alapul, es azzal helybol engedjen
kereskedni, ne kelljen optimalizalni."

⚠ ES AMIT CSEREBE VALLALUNK: az allapot NEM lehet nema. Egy hangolt es egy
hangolatlan par kulonben ranezesre EGYFORMA — mindketto „el", es a mentett
minosites helyen sem all semmi, ami elarulna. Ezert van `params_source`, ezert
ir a naplo, es ezert marad az Attekintes figyelmeztetese.
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
from strategy.settings import load_config, config_for_strategy
from trading import live_trader as lt

cfg = load_config("config.json")
BB = "bollinger_squeeze_breakout"
bb = get_strategy_by_name(BB)
wpr = get_strategy_by_name("wpr_sma")


# ── 1. AZ ALAPERTELMEZES a strategia SAJAT configjabol jon ───────────────
dp = lt.default_params(bb, cfg)
check("a bollingernek VAN alapertelmezese", bool(dp), str(dp and len(dp)))
# ⚠ EZ A LENYEG: a `config_for_strategy` nelkul a bollinger a wpr_sma
# indikator-blokkjat kapna (a futasideju cfg az ELSODLEGES strategiaval van
# merge-elve) — sajat `bb_period`/`kc_*` kulcsai helyett.
check("...es azok BOLLINGER kulcsok, nem a wpr_sma-e",
      "bb_period" in dp and "kc_atr_mult" in dp
      and "wpr_m15_period" not in dp, str(sorted(dp)))
_raw = bb.base_params(cfg)          # NYERS cfg — a hibas hivas
check("nyers cfg-vel TENYLEG a masik strategiaet kapnank (ezert kell a nezet)",
      "wpr_m15_period" in _raw and "bb_period" not in _raw, str(sorted(_raw))[:90])

# A kommentek nem parameterek.
check("a `_`-kezdetu kommentek KIMARADNAK",
      not any(str(k).startswith("_") for k in dp), str(sorted(dp))[:80])

check("a wpr_sma-nak is van", bool(lt.default_params(wpr, cfg)))


# ── 2. A FORRAS MEGKULONBOZTETHETO ───────────────────────────────────────
from core.params_store import params_file
_tuned = [s for s in cfg["pairs"] if not s.startswith("_")
          and params_file(s, BB).exists()]
_untuned = [s for s in cfg["pairs"] if not s.startswith("_")
            and not params_file(s, BB).exists()]
check("van hangolt ES hangolatlan par is (a teszt mer valamit)",
      bool(_tuned) and bool(_untuned), f"hangolt={_tuned} hangolatlan={_untuned}")
if _tuned:
    check("a mentett keszlet 'tuned'", lt.params_source(_tuned[0], BB) == "tuned")
if _untuned:
    check("a mentett nelkuli 'default'",
          lt.params_source(_untuned[0], BB) == "default")


# ── 3. A MOTOR TENYLEG KAP PARAMETERT ────────────────────────────────────
if _untuned:
    sym = _untuned[0]
    check("mentett keszlet nelkul a nyers hivas MA IS None-t ad "
          "(a tartalek a kulonbseg)",
          lt.strategy_params(sym, BB, cfg) is None)
    _p = lt.strategy_params(sym, BB, cfg, fallback=dp)
    check("...tartalekkal viszont VAN parameter", _p is not None and len(_p) > 0,
          str(_p and len(_p)))
    # ⚠ A vegrehajtasi config RAKERUL a tartalekra is — kulonben a hangolatlan
    # par mas vilagban futna, mint a hangolt (pl. hianyzo `atr_period` ->
    # `KeyError` a `compute_indicators`-ban, nema ures chart).
    check("...es a KOZOS vegrehajtasi config ra van fuzve",
          "atr_period" in (_p or {}), str(sorted(_p or {}))[:100])

# A motor az UJ uton kerdez
_ms = inspect.getsource(lt.run) if hasattr(lt, "run") else ""
_src = Path(lt.__file__).read_text(encoding="utf-8")
check("a `_make_state` a tartalekkal hivja",
      "fallback=default_params(strat, cfg)" in _src)
# ⚠ ES NAPLOZ: a hangolatlan futas ne csak a felületen latszodjon.
_i = _src.find("fallback=default_params(strat, cfg)")
check("...es NAPLOZZA, hogy alapertelmezessel fut",
      'params_source(symbol, strat.name) == "default"' in _src[_i:_i + 900])


# ── 4. A FELULET: nincs tobbe tiltas, de LATSZIK az allapot ──────────────
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_start = _gui.split("def _start_strategy")[1].split(chr(10) + "    def ")[0]
check("a Play MAR NEM tagadja meg parameter hianyaban",
      "előbb futtasd az OPT-ot" not in _start, _start[:120])
check("...de KIIRJA, hogy alapertelmezettel indul",
      "ALAPÉRTELMEZETT paramétereivel" in _start)
# A strategia-engedelyezettseg kapuja MEGMARAD: az mas kerdes.
check("az engedelyezettseg kapuja megmaradt",
      "if not self._strategy_enabled(symbol, name):" in _start)

# Az Attekintes figyelmeztetese: elesben SULYOSABB.
from core import overview as ov
_w_live = ov.warnings(cfg, "X", BB, {}, state="live")
_w_off = ov.warnings(cfg, "X", BB, {}, state="")
_t_live = [w["text"] for w in _w_live if "ALAPÉRTELMEZETT" in w["text"]]
check("az Attekintes kiirja a hangolatlansagot", bool(_t_live), str(_t_live)[:110])
check("...es ELESBEN sulyosabb fokozatban",
      [w["sev"] for w in _w_live if "ALAPÉRTELMEZETT" in w["text"]] == [ov.SEV_RISK]
      and [w["sev"] for w in _w_off if "ALAPÉRTELMEZETT" in w["text"]] == [ov.SEV_WARN])
# Mentett parameterrel viszont NINCS ilyen figyelmeztetes.
check("hangolt parnal nincs ilyen figyelmeztetes",
      not [w for w in ov.warnings(cfg, "X", BB, {"params": {"a": 1}}, state="live")
           if "ALAPÉRTELMEZETT" in w["text"]])


# ── 5. A POZICIO-HOZZARENDELES sem tilthat parameter hianyaban ──────────
# ⚠ A LELET (a felhasznalotol): a GOLD-ra rakva a bollingert egy tilto ablak
# fogadta — „nincs optimalizalva …, igy a motor nem tudja kezelni a poziciot".
# Ez a v2.47.0 ota NEM IGAZ: a motor a strategia sajat alapertekeivel is
# elindul. A tiltas tehat egy MUKODO muveletet akadalyozott meg.
_adopt = _gui.split("def _adopt_position")[1].split(chr(10) + "    def ")[0]
check("a hozzarendeles MAR NEM tilt parameter hianyaban",
      "nem tudja kezelni a pozíciót" not in _adopt, _adopt[:150])
# ⚠ AMI VISZONT TENYLEG AKADALY: ha a strategia nincs ENGEDELYEZVE a paron, a
# motor sosem futtatja — akkor a pozicio valoban kezeletlen maradna.
check("...de az ENGEDELYEZETTSEGET ellenorzi",
      "_strategy_enabled(symbol, strategy_name)" in _adopt)
check("...es megmondja, hol lehet bekapcsolni",
      "instrumentum NEVÉRE" in _adopt, "")
# ⚠ A hangolatlansag TAJEKOZTATAS, nem tiltas — de kimondva.
check("a hangolatlan keszletrol TAJEKOZTAT (nem tilt)",
      "ALAPÉRTELMEZETT" in _adopt and "kezelni fogja" in _adopt,
      _adopt[_adopt.find("MEGJEGYZ"):][:90])


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
