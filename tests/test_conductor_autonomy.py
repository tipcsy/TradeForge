"""AUTONÓMIA-LÉTRA ÉS KIKAPCSOLÓ — „a karmester bármikor kikapcsolható legyen".

⚠ A LELET (2026-09-21). A `paths.off_switch()` docstringje azt allitotta, hogy
„a szal minden ciklus elejen megnezi" — kozben az EGESZ kodbazisban egyetlen
hivatkozas volt ra: a sajat definicioja. A kapcsolo, amit a terv a karmester
elso szamu feltetelenek nevez, NEM LETEZETT. Ez a teszt az, ami ezt tobbe nem
engedi vissza: nem azt meri, hogy van-e fuggveny, hanem hogy a kapcsolo
TENYLEG megallitja a munkat.

⚠ ES A FELIRAT NEM HAZUDHAT ONALLOSAGOT. Amig a gepi vegrehajtas (F3/b) nincs
meg, az L2+ ugyanazt teszi, mint az L1 — ezt a kiiras KIMONDJA. Egy „L3"
felirat, ami mogott semmi nincs, ugyanaz a nema hiba, mint a nem hivott
kapcsolo volt.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.WARNING)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from conductor import paths as cp

TMP = Path(tempfile.mkdtemp(prefix="tf_auto_"))
cp.DIR = TMP / "conductor"
cp.DIR.mkdir(parents=True, exist_ok=True)

from conductor import autonomy as au
from conductor import report as rep
from conductor import telemetry as tl
from core import console_cmd as cc


def _be():
    """Tiszta lap: a kikapcsolo fajl NE legyen ott."""
    cp.off_switch().unlink(missing_ok=True)


def _cfg():
    return {"optimizer": {"test_start_date": "2026-01-01"},
            "pairs": {"GOLD": {"enabled": True, "strategies": ["csilla", "ml_ai"],
                               "run_state": {"csilla": "live", "ml_ai": "live"}}}}


def _ctx(cfg):
    return cc.Context(cfg=cfg, save_config=lambda: True, positions=list,
                      close_position=lambda t: False, account=dict, dashboard={},
                      instrument_state={}, strategies_of=lambda s: ["csilla", "ml_ai"])


# ══ 1. A LETRA ES A FELOLDAS SORRENDJE ═════════════════════════════════
_be()
c = _cfg()
check("alapbol TANACSADO (L1)", au.level(c) == au.ADVISOR, str(au.level(c)))
# ⚠ AZ ALAPERTEK MA NEM L3. A terv vegallapota az — de onallosagot akkor adunk,
# ha van gepi vegrehajtas ES lattad az arnyek bizonyitekat.
check("...es ez KEVESEBB, mint a terv vegallapota (L3)", au.DEFAULT < au.LIMITED)

au.set_default(c, au.OBSERVER)
au.set_override(c, "GOLD", None, au.LIMITED)
au.set_override(c, "GOLD", "ml_ai", au.ADVISOR)
check("a legszukebb talalat nyer: CELLA",
      au.level(c, "GOLD", "ml_ai") == au.ADVISOR
      and au.forras(c, "GOLD", "ml_ai") == "cell")
check("...aztan az INSTRUMENTUM",
      au.level(c, "GOLD", "csilla") == au.LIMITED
      and au.forras(c, "GOLD", "csilla") == "symbol")
check("...vegul az ALAPERTEK",
      au.level(c, "GER40", "csilla") == au.OBSERVER
      and au.forras(c, "GER40", "csilla") == "default")

# ══ 2. ⚠ A `0` NEM „NINCS BEJEGYZES" ═══════════════════════════════════
# A `-1` igaz-erteke True, a `0`-e False — egy `x or alap` tehat a MEGFIGYELO
# fokot nemán az alapra cserelne, vagyis a lefokozas kapcsolna fel valamit.
c2 = _cfg()
au.set_default(c2, au.OBSERVER)
check("⚠ a `0` fok megmarad (nem esik vissza az alapra)",
      au.level(c2) == au.OBSERVER, str(au.level(c2)))
c3 = {"conductor": {"autonomy": {"default": -1}}}
check("⚠ a `-1` is", au.level(c3) == au.OFF, str(au.level(c3)))
# ⚠ A be/ki kapcsolo NEM fok: aki `true`-t ir, az valoszinuleg felreerti.
c4 = {"conductor": {"autonomy": {"default": True}}}
check("a `true` NEM fok — visszaesunk az alapra", au.level(c4) == au.DEFAULT)
c5 = {"conductor": {"autonomy": {"default": 7}}}
check("a letran kivuli szam sem", au.level(c5) == au.DEFAULT)
c6 = {"conductor": {"autonomy": {"default": "2"}}}
check("a szoveges szam viszont ertelmezodik", au.level(c6) == au.ASSISTED)

# ══ 3. ⚠ A KIKAPCSOLO — EZ A LENYEG ════════════════════════════════════
_be()
c7 = _cfg()
au.set_default(c7, au.LIMITED)
check("bekapcsolva van dolga", au.barmi_aktiv(c7))
check("...es merhet is", au.enged(c7, au.MEASURE))

check("a kikapcsolas sikerul", au.set_off_file(True))
check("⚠ a fajl MINDENT felulir — L-1 lesz belole",
      au.level(c7) == au.OFF and au.level(c7, "GOLD", "csilla") == au.OFF)
check("...a config viszont VALTOZATLAN (a fajl fuggetlen ut)",
      au.default_level(c7) == au.LIMITED)
check("...es semmi nem szabad",
      not any(au.enged(c7, k) for k in (au.MEASURE, au.PROPOSE, au.INBOX,
                                        au.REPORT, au.EXECUTE, au.AUTO)))
check("⚠ ...tehat a szalnak SINCS dolga", not au.barmi_aktiv(c7))
check("a forras megmondja, hogy a FAJL dontott", au.forras(c7) == "off_file")
check("a visszakapcsolas is sikerul", au.set_off_file(False))
check("...es visszaall a config szerinti fok", au.level(c7) == au.LIMITED)

# ⚠ HA MINDEN FOK -1, a szalnak nincs dolga — de egyetlen magasabb cella is
# eleg ahhoz, hogy fusson („a GOLD-ot figyeld, a tobbit ne").
c8 = _cfg()
au.set_default(c8, au.OFF)
check("minden -1: nincs dolga", not au.barmi_aktiv(c8))
au.set_override(c8, "GOLD", None, au.OBSERVER)
check("...de EGY figyelt cella miatt mar van", au.barmi_aktiv(c8))

# ══ 4. A MERES KAPUJA (a motor forro utja) ═════════════════════════════
# ⚠ A `record()` utjan NINCS config-olvasas es fajlkerdezes: a motor allitja
# koronkent EGYSZER. A kapcsolo igy is <= 5 mp alatt hat.
tl.set_enabled(False)
check("kikapcsolt merésnél a rogzites NO-OP",
      tl.record("GOLD", "csilla", "buy", tl.ENTERED) is False)
tl.set_enabled(True)
check("...bekapcsolva viszont rogzit",
      tl.record("GOLD", "csilla", "buy", tl.ENTERED) is True)
tl.reset_for_test()

# ══ 5. A PARANCSOK NEM HALLGATNAK ══════════════════════════════════════
# ⚠ Egy kikapcsolt karmester lekerdezesere URES listat adni a legrosszabb
# valasz: pont ugy nez ki, mintha minden rendben volna.
_be()
c9 = _cfg()
ctx = _ctx(c9)
au.set_off_file(True)
for _p in ("plan", "health", "inbox", "optq", "why GOLD"):
    _r = cc.dispatch(ctx, _p)
    _sz = chr(10).join(_r.lines)
    check(f"`{_p}` kikapcsolva MEGMONDJA, hogy ki van kapcsolva",
          not _r.ok and "KI van kapcsolva" in _sz, _sz[:70])
# ⚠ A NAPI OSSZEFOGLALO viszont MEGY: a kotesek es az eredmeny nem a karmester
# szakaszai; azokat egy kikapcsolas nem veheti el.
_r = cc.dispatch(ctx, "report")
check("⚠ a napi osszefoglalo kikapcsolva is kimegy",
      _r.ok and _r.lines and "KI van kapcsolva" not in chr(10).join(_r.lines),
      chr(10).join(_r.lines)[:70])
# A `karmester` maga viszont MINDIG valaszol — kulonben nem lehetne
# visszakapcsolni.
_r = cc.dispatch(ctx, "karmester")
check("⚠ a `karmester` parancs kikapcsolva is valaszol", _r.ok)
check("...es kimondja, hogy a fajl felulir",
      "felülír" in chr(10).join(_r.lines), chr(10).join(_r.lines)[:120])
au.set_off_file(False)

# ══ 6. A PARANCS: fok-allitas ══════════════════════════════════════════
c10 = _cfg()
ctx = _ctx(c10)
_r = cc.dispatch(ctx, "karmester 0")
check("az alapertek allithato", _r.ok and au.default_level(c10) == au.OBSERVER)
_r = cc.dispatch(ctx, "karmester GOLD ml_ai 3")
check("a cella-felulbiralas is",
      _r.ok and au.level(c10, "GOLD", "ml_ai") == au.LIMITED)
check("⚠ ...es a felirat KIMONDJA, hogy ma meg nincs gepi vegrehajtas",
      "nem készült el" in chr(10).join(_r.lines), chr(10).join(_r.lines)[:120])
_r = cc.dispatch(ctx, "karmester GOLD ml_ai auto")
check("az `auto` torli a felulbiralast",
      _r.ok and au.level(c10, "GOLD", "ml_ai") == au.OBSERVER)
check("...es kimondja, mi lett belole", "mostantól" in chr(10).join(_r.lines))
check("az `L3` alak is megy", cc.dispatch(ctx, "karmester L3").ok
      and au.default_level(c10) == au.LIMITED)
check("a letran kivuli szamra hasznalatot ir",
      not cc.dispatch(ctx, "karmester 9").ok)
check("ismeretlen parra sem allitunk", not cc.dispatch(ctx, "karmester XX 2").ok)
check("nem engedelyezett strategiara sem",
      not cc.dispatch(ctx, "karmester GOLD nincsilyen 2").ok)
check("a `karmester` be van jegyezve", "karmester" in cc.COMMANDS)
check("...es szerepel a sugoban", any("karmester" in n for n, _k in cc._HELP))
# ⚠ A TELEGRAMON NINCS: a kikapcsolas/fok tartos dontes, mint a `mode`.
from core import telegram_cmd as tgc
check("⚠ a `karmester` NINCS a Telegram listajan", "karmester" not in tgc.ENGEDETT)

# ══ 7. A HAZIREND CELLANKENT SZUR ══════════════════════════════════════
# ⚠ „A GOLD-ot csak figyeld, a tobbit vezenyeld" — ez a per-cella autonomia.
from conductor.policies import lifecycle as lc
c11 = _cfg()
_sof = lambda s: ["csilla", "ml_ai"]
_mind = lc.proposals(c11, strategies_of=_sof)
check("alapbol minden cellara szuletik javaslat", len(_mind) == 2, str(len(_mind)))
au.set_override(c11, "GOLD", "ml_ai", au.OBSERVER)
_szurt = lc.proposals(c11, strategies_of=_sof)
check("⚠ a MEGFIGYELO cellara nem szuletik javaslat",
      len(_szurt) == 1 and _szurt[0].strategy == "csilla", str(len(_szurt)))

# ══ 8. A MOTOR TENYLEG MEGNEZI (forras-szintu or) ══════════════════════
# ⚠ EZ A LELET MAGA: a kapcsolo letezett, de senki nem hivta. Ez a blokk azt
# orzi, hogy a MOTOR SZALA kerdezi — nem eleg, hogy a modul megvan.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("a motor importalja az autonomiat", "from conductor import autonomy" in _lt)
check("⚠ a motor KORONKENT kerdezi a kapcsolot", "barmi_aktiv(cfg)" in _lt)
check("...es a merest is ebbol allitja", "_tlm.set_enabled(" in _lt)
check("...az orankenti blokk kapuja a fok", "if _karm_be and time.time()" in _lt)
check("...a javaslatnak kulon kapuja van", "_cau.enged(cfg, _cau.PROPOSE)" in _lt)
check("...a postaladanak is", "_cau.enged(cfg, _cau.INBOX)" in _lt)
check("...es az opt-sor hajtasanak is", "_cau.enged(cfg, _cau.EXECUTE)" in _lt)

# A FELULET is mutatja es kapcsolja.
_tab = (ROOT / "dashboard" / "conductor_tab.py").read_text(encoding="utf-8")
check("a ful kiirja a fokot", "cond.tab.level" in _tab)
check("...van rajta kapcsolo", "_kapcsol" in _tab and "cond.tab.switch_off" in _tab)
check("...a KOZOS parancs-retegen at", 'dispatch(\n' in _tab or '"karmester "' in _tab)
check("⚠ ...es a kikapcsolo fajlt is FIGYELI (kivulrol is atallithato)",
      "_p.off_switch()" in _tab)

# ══ 9. ⚠ A SIKERTELEN KIKAPCSOLAS NEM „SIKERES" ════════════════════════
# Egy „kikapcsolva" felirat egy futo karmester felett a leheto legrosszabb
# hazugsag — ezert a `set_off_file` hamisat ad, es a parancs ezt kimondja.
_eredeti = cp.DIR
try:
    cp.DIR = TMP / "nincs_ilyen_fajl" / "melyebben"
    (TMP / "nincs_ilyen_fajl").write_text("ez egy FAJL, nem mappa", encoding="utf-8")
    check("⚠ ha a fajl nem irhato, a kikapcsolas HAMISAT ad",
          au.set_off_file(True) is False)
    _r = cc.dispatch(_ctx(_cfg()), "karmester off")
    check("...es a parancs KIMONDJA, hogy NEM allt le",
          not _r.ok and "NEM állt le" in chr(10).join(_r.lines),
          chr(10).join(_r.lines)[:90])
finally:
    cp.DIR = _eredeti

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
