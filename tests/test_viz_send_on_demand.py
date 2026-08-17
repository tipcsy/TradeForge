"""„Kuldes a charthoz": a viz-fajl a MOSTANI beallitasokkal, MOTOR NELKUL.

⚠ A SPEC KERESE (MT5 ful): „Mivel ez itt egy elo kapcsolat, folyamatos
transzparenciat szeretnek latni. Ha beallitom mondjuk a spread kaput, akkor
rogton »reagalja le« a TBAND." Es kulon: „legyen egy Generalas/Kuldes gomb…
Persze a mentéskor is le kell futnia! De a kuldes nem egyenlo a mentessel."

Eddig a viz-fajlt KIZAROLAG a futo motor irta, a sajat utemeben:
  • leallitott paron EGYALTALAN nem lehetett megnezni, mit csinalna,
  • futo paron varni kellett a kovetkezo viz-korre.

⚠ ES A LEGFONTOSABB SZABALY: a pillanatkep a szimbolum TELJES rajza. Egyetlen
strategiat kiirva a TOBBI rajza NEMAN eltunne a chartrol — ezert a kuldes MINDEN
engedelyezett strategiat ujrarajzol, nem csak azt, amelyikbol inditottad.
"""
import copy
import inspect
import pathlib
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


import trading.live_trader as lt

# ── 1. A FUGGVENY SZERZODESE (MT5-kapcsolat nelkul is merheto) ───────────
check("van motor-fuggetlen pillanatkep-iro", hasattr(lt, "render_symbol_viz"))
_src = inspect.getsource(lt.render_symbol_viz)

# ⚠ MINDEN engedelyezett strategiat vegigjar — nem csak egyet.
check("MINDEN engedelyezett strategiat vegigjar",
      "strategies_for(cfg, symbol)" in _src, "")
# ⚠ A kikapcsolt RAJZU strategiat kihagyja, de JELENTI (nem nemán).
check("a kikapcsolt rajzut kihagyja, de jelenti",
      "viz_on" in _src and 'out["skipped"]' in _src)
# ⚠ URES pillanatkepet CLEAR-rel SOHA: az letorolne a chartot, es ugy nezne ki,
# mintha a Kuldes ürítette volna ki.
check("ures pillanatkepet NEM ir ki", 'if not lines:' in _src
      and 'régi rajza megmarad' in _src)
# ⚠ A parameterek a MENTETT allapotbol + a strategia sajat alapertekeibol —
# ugyanaz a keplet, mint az elo uton (`config_for_strategy` nelkul a bollinger a
# wpr_sma indikator-blokkjat kapna).
check("a strategia SAJAT config-nezetebol dolgozik",
      "config_for_strategy(cfg, st.name)" in _src)
check("...es a mentett keszlet hianyaban az alapertekekbol",
      "fallback=default_params" in _src)


# ── 2. A GOMB: csak MT5-on, es beszedes visszajelzessel ─────────────────
from dashboard import instrument_dialog as idlg
_gsrc = inspect.getsource(idlg.InstrumentParamsDialog._send_viz)
check("a gomb kezeloje letezik", bool(_gsrc))
check("...es KIIRJA, hany objektum ment ki", "Kiküldve:" in _gsrc)
# ⚠ A kihagyott strategia nem lehet nema: kulonben ugy nezne ki, mintha a
# kuldes nem mukodne.
check("...es a kihagyott strategiakat is", 'r["skipped"]' in _gsrc
      and "ki van kapcsolva" in _gsrc)
check("...hibat pirossal", "FG_RED" in _gsrc)

_psrc = inspect.getsource(idlg.InstrumentParamsDialog._build_link_pane)
check("a gomb CSAK az MT5 fulon van (ott van elo kapcsolat)",
      "if name == _md.MT5:" in _psrc)
# ⚠ A spec kulon kikoti: a kuldes NEM mentes.
check("...es kiirja, hogy a kuldes NEM mentes",
      "NEM mentés" in _psrc, "")

# ── 3. A MENTES IS KULD ─────────────────────────────────────────────────
# „Persze a mentéskor is le kell futnia!" — de CSENDESEN: egy sikertelen
# rajzolas nem akadalyozhatja meg a MENTEST.
_ssrc = inspect.getsource(idlg.InstrumentParamsDialog._persist)
check("a mentes is kuld a charthoz", "render_symbol_viz" in _ssrc)
check("...de a hiba NEM akasztja meg a mentest",
      "except Exception" in _ssrc and "popup.destroy()" in _ssrc)


# ── 4. ELES MERES, ha van MT5-kapcsolat ─────────────────────────────────
# ⚠ MT5 nelkul a `pair_visual_lines` ures listat ad (nincs honnan gyertyat
# venni) — ilyenkor a merest KIHAGYJUK, nem hamis PASS-t adunk ra.
try:
    from strategy.settings import load_config
    from core import mt5_connector as _C
    cfg = load_config("config.json")
    _C.connect(cfg)
    _live = bool(_C.connection_info(cfg).get("connected"))
except Exception:
    _live = False

if _live:
    import logging
    logging.disable(logging.INFO)
    sym = next(s for s in cfg["pairs"] if not s.startswith("_"))
    r = lt.render_symbol_viz(sym, cfg)
    logging.disable(logging.NOTSET)
    check(f"[{sym}] a pillanatkep KIIRODOTT", r["lines"] > 0 and r["path"],
          f"{r['lines']} sor, hibak: {r['errors']}")
    # ⚠ A TELJES rajz megy ki: ha ket strategia engedelyezett, MINDKETTO benne van.
    from strategy import strategies_for
    from core import viz_prefs as _vp
    _want = [st.name for st in strategies_for(cfg, sym)
             if _vp.viz_on(cfg, sym, st.name)]
    check(f"[{sym}] MINDEN engedelyezett strategia benne van",
          {n for n, _ in r["strategies"]} == set(_want),
          f"kiirt={[n for n, _ in r['strategies']]} varhato={_want}")
    check(f"[{sym}] a fajl a KOZOS mappaba ment",
          "Common" in str(r["path"]) and str(r["path"]).endswith(".csv"),
          str(r["path"]))
else:
    check("nincs MT5-kapcsolat (az eles meres kihagyva)", True)


# ── 5. DIAGNOSZTIKA: MIERT nincs fajl ───────────────────────────────────
# ⚠ A motor viz-iroja OT ponton lep ki csendben — kivulrol mind ugyanugy nez ki
# (a fajl nincs ott). Egy MASIK gepen ezt kitalalni remenytelen.
_d = inspect.getsource(lt.viz_diagnose)
check("van diagnosztika", bool(_d))
from strategy.settings import load_config as _lc
_cfg = _lc("config.json")

# Ismeretlen szimbolum -> ELSO sorban megmondja, es nem megy tovabb.
_rows = lt.viz_diagnose("__NINCS_ILYEN__", _cfg)
check("ismeretlen szimbolumra AZONNAL szol",
      len(_rows) == 1 and not _rows[0][0] and "NINCS a config" in _rows[0][1],
      str(_rows))

# Hianyzo point_size -> nevesitve, a JAVITAS parancsaval.
import copy as _cp
_c2 = _cp.deepcopy(_cfg)
_sym0 = next(s for s in _c2["pairs"] if not s.startswith("_"))
_c2["pairs"][_sym0].pop("point_size", None)
_bad = [t for ok, t in lt.viz_diagnose(_sym0, _c2) if not ok]
check("hianyzo point_size-t NEVESITI", any("point_size" in t for t in _bad),
      str(_bad)[:110])
check("...es megmondja a JAVITAST is",
      any("refresh_point_values" in t for t in _bad), str(_bad)[:110])

# ⚠ A kikapcsolt RAJZ a leggyakoribb ok — kulon nevet kell kapnia.
_c3 = _cp.deepcopy(_cfg)
_pc = _c3["pairs"][_sym0]
# ⚠ A HELYES KULCS: `strategy_viz` (per strategia) — az elso valtozatom `viz`-t
# irt, ami nem letezik, tehat a kikapcsolas nem is tortent meg, es a teszt nem
# azt merte, amit allitott. A modul sajat konstansat hasznaljuk, hogy egy
# atnevezes ITT bukjon el, ne elesben.
from core.viz_prefs import VIZ as _VIZAX
_pc[_VIZAX[0]] = {st.name: False for st in strategies_for(_c3, _sym0)}
_bad3 = [t for ok, t in lt.viz_diagnose(_sym0, _c3) if not ok]
check("a kikapcsolt RAJZ kulon nevet kap",
      any("RAJZA sincs bekapcsolva" in t for t in _bad3), str(_bad3)[:120])
check("...es megmondja, HOL kapcsolod be",
      any("Vizualizáció" in t or "instrumentum NEVÉRE" in t for t in _bad3),
      str(_bad3)[:120])

# A rendereles ugyanezt az okot adja vissza (nem „ures a pillanatkep").
_r3 = lt.render_symbol_viz(_sym0, _c3)
check("a renderelesnel is ez az ok jon vissza, nem az „ures pillanatkep”",
      any("RAJZA sincs bekapcsolva" in e for e in _r3["errors"]),
      str(_r3["errors"])[:120])

# A feluleten is elerheto.
_gsrc2 = inspect.getsource(idlg.InstrumentParamsDialog._diag_viz)
check("a felulet is kinalja (gomb)", "viz_diagnose" in _gsrc2)
check("...es a BUKOTT felteteleket emeli ki", "FG_RED" in _gsrc2)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
