"""PIACI NYITÁSOK kapu — a naptár, a keret-bekötés és az öröklés teteje.

⚠ A LEGFONTOSABB, AMIT ŐRZÜNK: a SZERVER ÓRÁJA. A gyertyák időbélyege
szerver-időben van, és a szerver `Europe/Berlin` (mérve: a frankfurti nyitás
télen-nyáron is a 09h indexnél adja a legnagyobb M1-tartományt). Ha ez elcsúszik
— pl. valaki „valódi UTC"-nek veszi —, a kapu NYÁRON két órát téved, és épp a
nyitási tüskét hagyja ki, amiért készült. Ezért a teszt a KONKRÉT szerver-órákat
rögzíti, nem a belső számítást.
"""
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                                  # noqa: E402
applog.harden_console()

from gates import sessions as S                                          # noqa: E402

_results, _fail = [], []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    if not ok:
        _fail.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def sv(y, m, d, h, mi=0):
    """Szerver-idő (a gyertya-fájlok így tárolják: berlini fal-óra)."""
    return dt.datetime(y, m, d, h, mi)


# ---------------------------------------------------------------------------
print("== A SZERVER ORAJA: a nyitasok ugyanott, telen es nyaron ==")
for cim, nap in (("nyar (CEST)", (2026, 6, 10)), ("tel (CET)", (2026, 1, 14))):
    st, m = S.state_of_server(sv(*nap, 9, 0), {"markets": ["europa"]})
    check(f"{cim}: 09:00 szerver = EUROPAI NYITAS", (st, m) == (S.NYITAS, "europa"),
          f"{st} / {m}")
    st, m = S.state_of_server(sv(*nap, 15, 30), {"markets": ["amerika"]})
    check(f"{cim}: 15:30 szerver = AMERIKAI NYITAS", (st, m) == (S.NYITAS, "amerika"),
          f"{st} / {m}")

# ---------------------------------------------------------------------------
print("\n== Az allapotok a nyitas korul (europa, 10 perces ablakok) ==")
P1 = {"markets": ["europa"], "elott_perc": 10, "utan_perc": 10}
for h, mi, vart in ((8, 49, S.ZARVA), (8, 50, S.NYITAS_ELOTT), (8, 59, S.NYITAS_ELOTT),
                    (9, 0, S.NYITAS), (9, 1, S.NYITAS_UTAN), (9, 10, S.NYITAS_UTAN),
                    (9, 11, S.NYITVA), (17, 20, S.ZARAS_ELOTT), (17, 30, S.ZARVA)):
    st, _m = S.state_of_server(sv(2026, 6, 10, h, mi), P1)
    check(f"{h:02d}:{mi:02d} -> {vart}", st == vart, st)

# ---------------------------------------------------------------------------
print("\n== Hetvege, es az ablak-hossz allithato ==")
check("szombat = zarva", S.state_of_server(sv(2026, 6, 13, 12, 0))[0] == S.ZARVA)
check("vasarnap = zarva", S.state_of_server(sv(2026, 6, 14, 12, 0))[0] == S.ZARVA)
check("5 perces ablak: 8:54 mar NEM nyitas elott",
      S.state_of_server(sv(2026, 6, 10, 8, 54),
                        {"markets": ["europa"], "elott_perc": 5})[0] == S.ZARVA)
check("15 perces ablak: 8:46 MAR nyitas elott",
      S.state_of_server(sv(2026, 6, 10, 8, 46),
                        {"markets": ["europa"], "elott_perc": 15})[0] == S.NYITAS_ELOTT)

# ---------------------------------------------------------------------------
print("\n== Az ES/VAGY a piac-halmazon oldodik fel ==")
# ⚠ EZ A TERVEZESI DONTES LENYEGE (2026-09-24). A felhasznalo szabaly-motort
# kert ES/VAGY kapcsolattal; kiderult, hogy nem kell: a „mindegyik zarva" = ES,
# a „barmelyik nyitas utani ablakaban" = VAGY — mindketto EGYETLEN allapot a
# parhoz rendelt piacok halmazan. Ha ez elromlik, visszajon a szabaly-motor.
_t = sv(2026, 6, 10, 9, 5)          # Europa nyitas utan, Azsia nyitva
check("VAGY: barmelyik nyitas utani ablakaban -> nyitas_utan",
      S.state_of_server(_t, {"markets": ["europa", "azsia"]})[0] == S.NYITAS_UTAN)
check("a legelesebb NYER (nem a 'nyitva' nyomja el)",
      S.state_of_server(_t, {"markets": ["azsia", "europa"]})[0] == S.NYITAS_UTAN)
# 04:00 szerver (CEST) = 02:00 UTC: Tokio es Sydney NYITVA, a nyugati piacok
# meg alszanak. Igy az "ES" allitas nem trivialis: ugyanabban a pillanatban a
# valasz a PIAC-HALMAZTOL fugg.
_hajnal = sv(2026, 6, 10, 4, 0)
check("ES: a nyugati piacok mindegyike zarva -> zarva",
      S.state_of_server(_hajnal,
                        {"markets": ["europa", "london", "amerika"]})[0] == S.ZARVA)
check("... de ugyanakkor JAPAN es AUSZTRALIA nyitva (tehat nem trivialis)",
      S.state_of_server(_hajnal, {"markets": ["japan"]})[0] != S.ZARVA
      and S.state_of_server(_hajnal, {"markets": ["ausztralia"]})[0] != S.ZARVA,
      f'japan={S.state_of_server(_hajnal, {"markets": ["japan"]})[0]} '
      f'ausztralia={S.state_of_server(_hajnal, {"markets": ["ausztralia"]})[0]}')

# ---------------------------------------------------------------------------
print("\n== A KERET-BEKOTES ==")
from core import gates as _g, gate_bands as _gb                          # noqa: E402
_g.refresh_registry()
check("a kapu FELDERITVE (nincs kezzel felveve a registrybe)",
      "sessions" in [e["key"] for e in _g.REGISTRY])
check("alap-hatas NONE (a kapu mutat, nem tilt)",
      _g.default_effect_of("sessions") == "none", _g.default_effect_of("sessions"))
check("a sav-fajta KATEGORIA (a modul GATE['kind']-jebol)",
      _gb.kind_of("sessions") == _gb.CATEGORY, _gb.kind_of("sessions"))
check("van magyar neve", _g.label_of("sessions") != "gate.name.sessions",
      _g.label_of("sessions"))

_ctx = _g.GateCtx(symbol="Ger40", strategy="csilla", signal="BUY", cfg={},
                  pair_cfg={"sessions": {"markets": ["europa"]}},
                  now=sv(2026, 6, 10, 9, 5))
check("measure a kereten at: a SZINT maga az allapot",
      _g.measure("sessions", _ctx) == (False, S.NYITAS_UTAN),
      str(_g.measure("sessions", _ctx)))
_ctx2 = _g.GateCtx(symbol="Ger40", strategy="csilla", signal="BUY", cfg={},
                   pair_cfg={"sessions": {"markets": ["europa"],
                                          "adverse": [S.NYITAS_UTAN]}},
                   now=sv(2026, 6, 10, 9, 5))
check("kedvezotlennek jelolt allapotra BUKIK",
      _g.measure("sessions", _ctx2)[0] is True)
_log = _g.block_log("sessions", _ctx2)
check("az indoklas KONKRET (nem a generikus mondat)",
      "Nyitás után" in _log and "Európa" in _log, _log)
check("ido nelkul NEM szol bele (fail-open)",
      _g.measure("sessions", _g.GateCtx(symbol="X", cfg={}, pair_cfg={})) == (False, None))

# ---------------------------------------------------------------------------
print("\n== AZ OROKLES TETEJE irhato ==")
# ⚠ A felhasznalo leletje (2026-09-24): „pont az elso allapot (a forras!) az,
# ami nincs kivezetve, ahonnan az oroklés szabály indul". A globalis szintet
# eddig CSAK a kod adhatta — a felulet minden parba kulon irt.
_cfg = {"gates": {"sessions": {"default": "block"}}}
check("globalis alapertek -> a forras 'global_default'",
      _g.effect_with_source(_cfg, "Ger40", "csilla", "sessions")
      == ("block", _g.SRC_GLOBAL_DEFAULT),
      str(_g.effect_with_source(_cfg, "Ger40", "csilla", "sessions")))
_cfg["pairs"] = {"Ger40": {"gates": {"sessions": {"csilla": "none"}}}}
check("a par felulirja -> a forras 'pair'",
      _g.effect_with_source(_cfg, "Ger40", "csilla", "sessions")
      == ("none", _g.SRC_PAIR))
check("a masik par TOVABBRA is orokol",
      _g.effect_with_source(_cfg, "UsaTec", "csilla", "sessions")
      == ("block", _g.SRC_GLOBAL_DEFAULT))
_GD = (ROOT / "dashboard" / "gate_dialog.py").read_text(encoding="utf-8")
check("a kapu-ablak tud a GLOBALIS szintre irni", "_global_var" in _GD)
check("... es nem a parokba fejti ki", "_gazdak = ([self.cfg]" in _GD)

# ---------------------------------------------------------------------------
print("\n== A LIVE OSZLOP ==")
from dashboard import live_row as _lr, canvas_cells as _cc, canvas_columns as _cco  # noqa: E402
check("a 'sessions' oszlop ott van a fix oszlopok kozt",
      "sessions" in _cco.column_keys(["wpr_sma"], {}))
_row = _lr.demo_row()
_szinek = {}
for _st in S.STATES:
    _row["gates"]["sessions"] = {"text": _st, "state": _st}
    _szinek[_st] = _cc.cells_for(_row, {"gates": False, "strategies": set()})["sessions"].fg
check("CELLA is keletkezik (nem csak fejlec)", all(_szinek.values()), str(_szinek))
check("zarva = szurke, nyitva = zold", _szinek[S.ZARVA] != _szinek[S.NYITVA])
check("nyitas elott = nyitas utan? NEM (sarga vs piros)",
      _szinek[S.NYITAS_ELOTT] != _szinek[S.NYITAS_UTAN])
check("a nyitas es a nyitas utan EGYFORMA eles (piros)",
      _szinek[S.NYITAS] == _szinek[S.NYITAS_UTAN])

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
