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

# ---------------------------------------------------------------------------
print("\n== A CELLA: van TARTALMA es KATTINTHATO ==")
# ⚠ A KETTO EGYUTT A LELET (a felhasznalo kepernyokepe, 2026-09-24): az oszlop
# fejlece ott volt, de MINDEN sor ures maradt, es a cellara nem lehetett
# kattintani. Ket kulon hiba egy helyen: (1) a cella a `ctx`-bol kereste az
# allapot-objektumot, abban viszont NEVESITETT mezok vannak, nem a `ds`;
# (2) a kapu-cellak kapunkent kulon `on_<kapu>` visszahivast kapnak, amit egy
# BEHELYEZETT kapu nem tud felvenni a feluletre — ezert kell a GENERIKUS
# `on_gate(szimbolum, kulcs)`.
from dashboard import row_source as _rs                                 # noqa: E402
from trading.live_trader import PairDashboardState as _PDS              # noqa: E402

_ds = _PDS(symbol="Ger40", trained=True, enabled=True)
_ds.digits = 2
_ds.sessions_state, _ds.sessions_market = S.state_of_server(
    sv(2026, 6, 10, 9, 5), {"markets": ["europa"]})
_KAT = []
_row = _rs.row_data("Ger40", _ds, ["wpr_sma"], cfg={}, params={},
                    pair_cfg={"point_size": 0.1},
                    on_gate=lambda s, k: _KAT.append((s, k)))
_cell = _row["gates"]["sessions"]
check("a cellanak VAN tartalma (nem '—')", bool(_cell["marks"]) or
      _cell["text"] not in ("", "—"), str(_cell))
check("...es hordozza az allapotot a szinhez", _cell["state"] == S.NYITAS_UTAN,
      str(_cell["state"]))
check("...es azt is, MELYIK piac okozza", _cell["market"] == "europa",
      str(_cell["market"]))
check("KATTINTHATO", _cell["on_click"] is not None)
if _cell["on_click"]:
    _cell["on_click"]()
check("...es a SAJAT kapujanak ablakat nyitja", _KAT == [("Ger40", "sessions")],
      str(_KAT))
_ds2 = _PDS(symbol="Ger40", trained=True, enabled=True)
_ds2.digits = 2
_cell2 = _rs.row_data("Ger40", _ds2, ["wpr_sma"], cfg={}, params={},
                      pair_cfg={"point_size": 0.1},
                      on_gate=lambda s, k: None)["gates"]["sessions"]
check("meres nelkul '—', de MEG MINDIG kattinthato",
      _cell2["text"] == "—" and _cell2["on_click"] is not None)

# ── PIACONKENT EGY BETU ────────────────────────────────────────────────
# ⚠ A felhasznalo leletje (2026-09-24): „Az hogy zarva az nem mond semmit."
# Egy osszevont szo nem arulja el, MELYIK tozsde tart hol — ezert a figyelt
# piacok betui allnak az oszlopban, mindegyik a SAJAT allapota szerint szinezve.
_ds3 = _PDS(symbol="Ger40", trained=True, enabled=True)
_ds3.digits = 2
_P2 = {"markets": ["europa", "amerika"]}
_ds3.sessions_state, _ds3.sessions_market = S.state_of_server(
    sv(2026, 6, 10, 9, 5), _P2)
_ds3.sessions_list = S.states_of_server(sv(2026, 6, 10, 9, 5), _P2)
_c3 = _rs.row_data("Ger40", _ds3, ["wpr_sma"], cfg={}, params={},
                   pair_cfg={"point_size": 0.1},
                   on_gate=lambda s, k: None)["gates"]["sessions"]
check("piaconkent egy jelolo, a FIGYELT piacokra",
      [b for b, _s in _c3["marks"]] == ["E", "NY"], str(_c3["marks"]))
check("...mindegyik a SAJAT allapotaval",
      [_s for _b, _s in _c3["marks"]] == [S.NYITAS_UTAN, S.ZARVA],
      str(_c3["marks"]))
check("a buborek SZOVAL is kiirja", "Európa" in _c3["tip"]
      and "Nyitás után" in _c3["tip"], _c3["tip"][:60])
_cells3 = _cc.cells_for(
    {"gates": {"sessions": _c3}, "strategies": [], "symbol": "Ger40"},
    {"gates": False, "strategies": set()})["sessions"]
check("a cella BETUKET rajzol, kulon szinnel",
      _cells3.kind == "dots" and [d[0] for d in _cells3.dots] == ["E", "NY"]
      and _cells3.dots[0][1] != _cells3.dots[1][1], str(_cells3.dots))
_lr_src = (ROOT / "dashboard" / "canvas_table.py").read_text(encoding="utf-8")
check("a rajzolo kezeli a `(jel, szin)` part", "isinstance(d, (tuple, list))"
      in _lr_src, "canvas_table")

# ---------------------------------------------------------------------------
print("\n== AZ IDO: falioras, nem gyertya-ido ==")
# ⚠ A kapu PERC-pontos ablakokkal dolgozik (a nyitas perce, ±10 perc). Az elso
# valtozat az utolso ZART M15 gyertya idejet adta neki — az akar 15 perccel
# korabbi, tehat a „Nyitas" allapotot (egy perc) gyakorlatilag SOSEM latta
# volna, a ±10 perces ablakokat pedig talalomra talalta volna el.
from core import mt5_connector as _mc                                   # noqa: E402
check("van szerver-falióra (`server_now`)",
      callable(getattr(_mc, "server_now", None)))
_gui_src = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
_lt_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a KIJELZES a faliorat hasznalja", "server_now()" in _gui_src)
check("a MOTOR is ugyanazt", "now=mt5_connector.server_now()" in _lt_src)

# ---------------------------------------------------------------------------
print("\n== A CSOMAG (.tfg) ==")
import json                                                             # noqa: E402
import tempfile                                                         # noqa: E402
import zipfile                                                          # noqa: E402
# ⚠ MAGUNK EPITJUK, nem a lemezen talalt fajlt nezzuk. A `data/` a .gitignore-ban
# van, tehat egy friss klonon nem letezne a csomag — az allitas nem a
# csomagolast merne, hanem azt, hogy valaki futtatta-e mar a parancsot.
from gates import pack as _pack                                         # noqa: E402
_tfg = Path(tempfile.mkdtemp(prefix="tf_tfg_")) / "sessions-1.0.0.tfg"
try:
    _pack.build("sessions", out_file=_tfg)
except Exception as _ex:
    print(f"  (a csomagolas elszallt: {type(_ex).__name__}: {_ex})")
check("a csomag elkeszult", _tfg.exists(), str(_tfg))
if _tfg.exists():
    with zipfile.ZipFile(_tfg) as _z:
        _nev = set(_z.namelist())
        _man = json.loads(_z.read("manifest.json"))
    check("manifest + modul + MINDKET doksi",
          {"manifest.json", "sessions.py", "docs/sessions.md",
            "docs/sessions.en.md"} <= _nev, str(sorted(_nev)))
    check("a manifest a szabvany szerint",
          _man["kind"] == "tradeforge-gate" and _man["key"] == "sessions"
          and _man["phase"] == "signal", str({k: _man.get(k) for k in
                                              ("kind", "key", "phase", "api")}))
    check("minden fajlnak van ellenorzo-osszege",
          set(_man["sha256"]) == _nev - {"manifest.json"},
          str(sorted(_man["sha256"])))

# ---------------------------------------------------------------------------
print("\n== KET NAPTAR: tozsde vs. deviza-szekcio ==")
# ⚠ A felhasznalo dontese (2026-09-24): „Mindketto, instrumentum szerint." Egy
# index-CFD-nek a TOZSDE nyitvatartasa a valosag, egy devizaparnak a penzugyi
# kozpont munkanapja (08-17 helyi) — az szelesebb. A kriptonak nincs
# nyitoharangja, tehat nyitasi rangasa sem.
check("index -> tozsdei naptar", S.calendar_for("Ger40") == S.CAL_EXCHANGE)
check("devizapar -> szekcio", S.calendar_for("EURUSD") == S.CAL_FX)
check("...a HUF-os kereszt is", S.calendar_for("EURHUF") == S.CAL_FX)
check("arany -> szekcio", S.calendar_for("GOLD") == S.CAL_FX)
check("kripto -> mindig nyitva", S.calendar_for("BTCUSD") == S.CAL_ALWAYS)
check("ismeretlen nev -> tozsde (a SZUKEBB olvasat)",
      S.calendar_for("Valami123") == S.CAL_EXCHANGE)

# A KULONBSEG, amiert ket naptar kell. 2026-06-10 (nyar) 00:30 szerver-ido:
# a sydney-i SZEKCIO mar megy (08:00 helyi), a TOZSDE meg nem (10:00 helyi).
_ejjel = sv(2026, 6, 10, 0, 30)
_PT = {"markets": ["ausztralia"], "naptar": S.CAL_EXCHANGE}
_PF = {"markets": ["ausztralia"], "naptar": S.CAL_FX}
check("00:30 szerver: a tozsde szerint ZARVA",
      S.state_of_server(_ejjel, _PT)[0] == S.ZARVA,
      S.state_of_server(_ejjel, _PT)[0])
check("...a szekcio szerint viszont NEM", S.state_of_server(_ejjel, _PF)[0] != S.ZARVA,
      S.state_of_server(_ejjel, _PF)[0])
# ...es a ket naptar UGYANAZT mondja ott, ahol egybeesnek (londoni delutan).
_delutan = sv(2026, 6, 10, 14, 0)
check("londoni delutan: mindket naptar NYITVA",
      S.state_of_server(_delutan, {"markets": ["london"], "naptar": S.CAL_EXCHANGE})[0]
      == S.state_of_server(_delutan, {"markets": ["london"], "naptar": S.CAL_FX})[0]
      == S.NYITVA)

# A „mindig nyitva" naptar: EGY jelolo, nem hat zold betu (hat zold azt
# allitana, hogy „Tokio nyitva" — kriptonal ertelmetlen).
_PA = S.params_of({}, {}, "BTCUSD")
check("kripto: a naptar feloldodik", _PA["naptar"] == S.CAL_ALWAYS)
check("...EGY jelolo, es az NYITVA",
      S.states_of_server(_ejjel, _PA) == [(S.CAL_ALWAYS, S.NYITVA)],
      str(S.states_of_server(_ejjel, _PA)))
check("...a jelolonek van FELIRATA is (nem nyers kulcs)",
      S.MARKET_LETTER.get("mindig", "") not in ("", "mindig")
      and S.MARKET_LABEL.get("mindig", "") not in ("", "mindig"),
      f'{S.MARKET_LETTER.get("mindig", "")} / {S.MARKET_LABEL.get("mindig", "")}')

# Az `auto` feloldasa a SZIMBOLUMBOL tortenik, de a par FELULIRHATJA.
check("auto + szimbolum -> szekcio",
      S.params_of({}, {}, "EURUSD")["naptar"] == S.CAL_FX)
check("a par felulirja (ez a vegso szo)",
      S.params_of({"sessions": {"naptar": S.CAL_EXCHANGE}}, {}, "EURUSD")["naptar"]
      == S.CAL_EXCHANGE)
check("szimbolum NELKUL a tozsdei (konzervativ) naptar",
      S.params_of({}, {})["naptar"] == S.CAL_EXCHANGE)
check("ervenytelen naptar-nev -> az alapertelmezes",
      S.params_of({"sessions": {"naptar": "szemet"}}, {}, "Ger40")["naptar"]
      == S.CAL_EXCHANGE)
check("a naptar SZERKESZTHETO mezo (a kapu-ablakban)",
      any(d["key"] == "naptar" and d["kind"] == "choice" for d in S.PARAMS))

print()
if _fail:
    print("HIBA: " + ", ".join(_fail))
print(f"{sum(_results)}/{len(_results)} teszt PASS")
sys.exit(1 if _fail else 0)
