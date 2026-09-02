"""Telegram-értesítés: mi megy ki, mi nem, és mi NEM állíthatja meg a motort.

⚠ A KÉT KÉRDÉS, AMI PÉNZBE KERÜLHET:

  1. **Az értesítés sosem állíthatja meg a kereskedést.** Ha a Telegram lassú,
     elérhetetlen vagy hibára fut, a motor köre attól még menjen tovább. Ezért
     a hívó oldalon minden azonnal visszatér, kivétel nem jön ki, és a küldés
     külön szálon megy.
  2. **A NÉGY kritikus eseményt nem a motor jelenti.** Egy elhalt szál nem tud
     üzenni magáról — a 2026-08-XX-i néma szál-halálnál (11 pár állt le) a
     napló hallgatott, és nem volt MIÉRT megkérdezni. Ezért az értesítő szála
     kérdezi meg periodikusan, hogy minden rendben van-e.

⚠ A teszt HÁLÓZAT NÉLKÜL fut: a küldés egy cserélhető `transport`, az idő egy
cserélhető óra. Így a csendes órák, a dedup és az életjel is lejátszható —
várakozás nélkül.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

from datetime import datetime

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import notify, viz_prefs

# ── 0. Beállítás nélkül NEM megy semmi (és nem is hibázik) ────────────────
_ures = notify.read_config({})
check("beállítás nélkül nincs értesítés", not _ures.kesz)
check("⚠ `enabled` önmagában NEM elég (token/címzett nélkül némán a semmibe menne)",
      not notify.read_config({"notify": {"enabled": True}}).kesz)
_c = notify.read_config({"notify": {"enabled": True, "telegram": {
    "token": "T", "chat_ids": ["1"]}}})
check("token + címzett + enabled → kész", _c.kesz)
# Egyetlen chat_id sztringként is jó (a felhasználó könnyen így írja be).
check("egyetlen chat_id sztringként is elfogadott",
      notify.read_config({"notify": {"enabled": True, "telegram": {
          "token": "T", "chat_ids": "12345"}}}).chat_ids == ("12345",))

# ── 1. Csendes órák — HELYI idő, ÁTNYÚLÓ intervallummal ──────────────────
# ⚠ A felhasználó döntése: „az ember nem szerver-időben alszik".
_ejjel = notify.Config(enabled=True, token="T", chat_ids=("1",),
                       quiet_from="22:00", quiet_to="07:00")
for _ora, _var in ((23, True), (2, True), (6, True), (7, False), (12, False),
                   (21, False), (22, True)):
    check(f"csendes óra {_ora:02d}:00 → {'csend' if _var else 'mehet'}",
          notify.csendben(_ejjel, datetime(2026, 8, 31, _ora, 0)) is _var)
check("csendes óra nélkül SOSEM csend",
      not notify.csendben(notify.Config(), datetime(2026, 8, 31, 3, 0)))
# ⚠ Elgépelt időpont ne bénítsa meg az értesítést — inkább ne legyen csend.
check("⚠ hibás időpont-formátum nem dob (csak nincs csend)",
      not notify.csendben(notify.Config(quiet_from="huszkettő", quiet_to="7"),
                          datetime(2026, 8, 31, 3, 0)))


def epit(cfg_json=None, **kw):
    c = notify.Config(enabled=True, token="T", chat_ids=("1",), **kw)
    kuldott = []
    n = notify.Notifier(c, transport=lambda t: (kuldott.append(t) or True))
    notify._cfg_json = cfg_json or {"pairs": {}}
    return n, kuldott


# ── 2. Per pár + stratégia kapcsolók ─────────────────────────────────────
# ⚠ KÉT TENGELY, NEM EGY. A „szólj, ha JELZÉS van" (sok, zajos) és a „szólj, ha
# KÖTÉS van" (ritka, fontos) nem ugyanaz: egyetlen kapcsolóval a zaj miatt
# kikapcsolnád — és onnantól a KÖTÉSEKRŐL sem kapnál hírt.
_cfg = {"pairs": {"Ger40": {}}}
n, _ = epit(_cfg)
_most = datetime(2026, 8, 31, 12, 0)
_kot = notify.Event(kind=notify.OPEN, text="x", symbol="Ger40", strategy="wpr_sma")
_jel = notify.Event(kind=notify.SIGNAL, text="x", symbol="Ger40", strategy="wpr_sma")
check("⚠ a KÖTÉS-értesítés alapból BE", n.kimehet(_kot, _cfg, _most)[0])
check("⚠ a JELZÉS-értesítés alapból KI (abból sok van)",
      not n.kimehet(_jel, _cfg, _most)[0])
viz_prefs.set_on(_cfg, "Ger40", "wpr_sma", viz_prefs.NOTIFY_SIGNAL, True)
check("...de bekapcsolható pár+stratégia szinten",
      n.kimehet(_jel, _cfg, _most)[0])
viz_prefs.set_on(_cfg, "Ger40", "wpr_sma", viz_prefs.NOTIFY_TRADE, False)
check("...és a kötés-értesítés külön némítható",
      not n.kimehet(_kot, _cfg, _most)[0])
# A két tengely FÜGGETLEN: a némított kötés nem némítja a jelzést.
check("⚠ a két tengely független", n.kimehet(_jel, _cfg, _most)[0])

# ── 3. Mi történik a csendes órában ──────────────────────────────────────
_cfg2 = {"pairs": {"Ger40": {}}}
viz_prefs.set_on(_cfg2, "Ger40", "wpr_sma", viz_prefs.NOTIFY_SIGNAL, True)
n, _ = epit(_cfg2, quiet_from="22:00", quiet_to="07:00")
_ej = datetime(2026, 8, 31, 3, 0)
_ok, _ok_szoveg = n.kimehet(_jel, _cfg2, _ej)
check("⚠ csendben a JELZÉS elvész (reggel már úgysem lépnél be)",
      not _ok and "elvész" in _ok_szoveg, _ok_szoveg)
_ok, _ = n.kimehet(_kot, _cfg2, _ej)
check("⚠ csendben a KÖTÉS nem megy ki AZONNAL", not _ok)
check("...de FÉLRETESSZÜK (reggel összesítve jön)", len(n._halasztott) == 1)
# ⚠ A HIBA a csendet is átüti: ha a motor éjjel elhalt, azt reggel tudni kell.
_hiba = notify.Event(kind=notify.ERROR, text="baj", key="thread|2026-08-31")
check("⚠ a KRITIKUS hiba a csendes órát is átüti",
      n.kimehet(_hiba, _cfg2, _ej)[0])

# ── 4. Napi dedup a hibákra ──────────────────────────────────────────────
# ⚠ KÖZÖS ÓRA. A dedup napját a `_kuld` a Notifier órájából írja be, a
# `kimehet` pedig ugyanabból olvassa — ha a teszt külön időt adna át, a kettő
# elcsúszna, és a teszt hazudna a valódi útról. Ezért itt az ÓRÁT állítjuk.
_ido = [datetime(2026, 8, 31, 12, 0).timestamp()]
n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",)),
                    transport=lambda t: True, ora=lambda: _ido[0])
notify._cfg_json = {"pairs": {}}
check("a hiba először kimehet", n.kimehet(_hiba, {})[0])
n._kuld(_hiba)
check("...és tényleg elment", n.kuldve == 1)
_ido[0] = datetime(2026, 8, 31, 18, 0).timestamp()
_ok, _ok_szoveg = n.kimehet(_hiba, {})
check("⚠ ugyanaz a hiba MA már nem megy ki újra", not _ok, _ok_szoveg)
_ido[0] = datetime(2026, 9, 1, 8, 0).timestamp()
check("...holnap viszont igen",
      n.kimehet(notify.Event(kind=notify.ERROR, text="baj",
                             key="thread|2026-09-01"), {})[0])

# ── 5. Perc-limit: a zajos nap ne fojtsa meg a beszélgetést ──────────────
_ido = [1000.0]
n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",)),
                    transport=lambda t: True, ora=lambda: _ido[0])
for i in range(notify.PERC_LIMIT + 5):
    n._kuld(notify.Event(kind=notify.OPEN, text=f"m{i}"))
check("⚠ percenként legfeljebb PERC_LIMIT üzenet megy ki",
      n.kuldve == notify.PERC_LIMIT, f"{n.kuldve} küldve, {n.eldobva} vissza")
_ido[0] += 61
n._kuld(notify.Event(kind=notify.OPEN, text="egy perccel később"))
check("...egy perc múlva újra mehet", n.kuldve == notify.PERC_LIMIT + 1)

# ── 6. A KÜLDÉS SOSEM VISZI EL A HÍVÓT ───────────────────────────────────
# ⚠ EZ A LEGFONTOSABB: ha a Telegram hibára fut, a motor köre menjen tovább.
def _robban(_t):
    raise RuntimeError("a Telegram nem elérhető")


n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",)),
                    transport=_robban)
_hiba_jott = False
try:
    n._munka_egy = None
    n._kuld(notify.Event(kind=notify.OPEN, text="x"))
except Exception:
    _hiba_jott = True
check("a `_kuld` felengedi a hibát (a szál kapja el)", _hiba_jott)
# ...és a szál elkapja: a `_munka` hurok minden kivételt lenyel.
import inspect
_forras = inspect.getsource(notify.Notifier._munka)
check("⚠ a küldő SZÁL minden hibát elkap (különben némán meghalna)",
      "except Exception" in _forras)

# A modul-szintű belépési pontok beállítás NÉLKÜL sem dobnak.
notify._aktiv = None
check("⚠ beállítatlanul a `trade_event` nem dob és nem küld",
      notify.trade_event({"event": "open", "symbol": "Ger40"}) is False)
check("⚠ ...a `sl_moved` sem", notify.sl_moved("Ger40", "wpr_sma", 1, 1.0) is False)
check("⚠ ...és az `error` sem", notify.error("k", "x") is False)
# Hibás rekord se szálljon el (a `log_trade` hívja, ami NEM állhat meg).
check("⚠ hibás rekordtól sem dob",
      notify.trade_event({"event": "open", "price": "nem szám"}) is False)

# ── 7. Az üzenet TARTALMA ────────────────────────────────────────────────
n, kuldott = epit()
notify._aktiv = n
notify._cfg_json = {"pairs": {}}
notify.trade_event({"event": "open", "symbol": "Ger40", "strategy": "wpr_sma",
                    "direction": "BUY", "lot": 0.1, "price": 23456.7,
                    "sl": 23400.0, "tp": 23600.0})
n._kuld(n._q.get_nowait())
# ⚠ „23457" ÁLLT ITT — a `%.5g` KEREKÍTÉSE. A régi formátum nem csak
# exponenciálisra váltott nagy szinteknél: Ger40-méretű számon egy valós
# tizedest is eldobott, és a teszt ezt a veszteséget rögzítette helyesként.
check("a kötés üzenete tartalmazza a párat, az irányt és a PONTOS árat",
      kuldott and all(x in kuldott[-1] for x in ("Ger40", "BUY", "23456.7")),
      kuldott[-1] if kuldott else "")
notify.trade_event({"event": "close", "symbol": "Ger40", "strategy": "wpr_sma",
                    "ticket": 111, "pnl_usd": -12.5})
n._kuld(n._q.get_nowait())
check("a zárás üzenetében ott a P&L", "-12.50" in kuldott[-1], kuldott[-1])
notify.sl_moved("Ger40", "wpr_sma", 111, 23500.0, breakeven=True)
n._kuld(n._q.get_nowait())
check("⚠ a KOCKÁZATMENTESÍTÉS külön üzenet (nem sima SL-mozgás)",
      "23500" in kuldott[-1] and kuldott[-1] != "", kuldott[-1])
_be_szoveg = kuldott[-1]
notify.sl_moved("Ger40", "wpr_sma", 111, 23510.0, breakeven=False)
n._kuld(n._q.get_nowait())
check("...és a sima SL-mozgás MÁS szöveget kap", kuldott[-1] != _be_szoveg)
notify._aktiv = None

# ── 8. A NÉGY kritikus esemény forrása a MOTOR ÁLLAPOTA ──────────────────
# ⚠ Nem a motor küldi: egy elhalt szál nem tud üzenni magáról. Az értesítő
# szála kérdezi meg — az akkor is fut, ha a motor már nem.
from trading import live_trader as lt
import time as _t_mod
_regi_ts = lt.last_cycle_ts
try:
    lt.last_cycle_ts = _t_mod.time() - 3600      # egy órája nem futott kör
    _rep = lt.health_report({"trading": {}, "notify": {}})
    check("⚠ az ELAKADT motort a jelentés megfogja",
          any(k.startswith("thread|") for k, _ in _rep), str([k for k, _ in _rep]))
    lt.last_cycle_ts = _t_mod.time()
    _rep2 = lt.health_report({"trading": {}, "notify": {}})
    check("...friss kör mellett nem panaszkodik a szálra",
          not any(k.startswith("thread|") for k, _ in _rep2))
    check("⚠ a dedup-kulcs NAPRA szól (naponta legfeljebb egy üzenet)",
          all("|" in k and len(k.split("|")[1]) == 10 for k, _ in _rep2 + _rep))
finally:
    lt.last_cycle_ts = _regi_ts

# ⚠ Az értesítő szála KÉRDEZZE a jelentést — ne a motor tolja.
_src = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("⚠ a motor a `health` FÜGGVÉNYT adja át (nem ő küld)",
      "notify.setup(cfg, health=" in _src)
check("⚠ ...és a kötés-értesítés a KÖZÖS `log_trade`-ből megy",
      "notify.trade_event(row)" in _src)
check("⚠ ...az SL-mozgás pedig a KÖZÖS SL-naplóból",
      "notify.sl_moved(" in _src)

# ── 9. A Telegram-réteg hálózat nélkül is viselkedik ─────────────────────
from core import telegram
_ok, _uz = telegram._hivas("", "getMe", {})
check("⚠ token nélkül a hívás NEM dob, csak nemet mond", not _ok)
check("a hosszú üzenet DARABOLVA megy (nem levágva)",
      len(telegram._darabol("x" * (telegram.MAX_HOSSZ * 2 + 10))) >= 2)
_hosszu = "sor\n" * 3000
check("⚠ ...és SORHATÁRON darabol",
      all(len(d) <= telegram.MAX_HOSSZ for d in telegram._darabol(_hosszu)))
check("a rövid üzenet egy darab", telegram._darabol("rövid") == ["rövid"])
# ⚠ Saját User-Agent: a Cloudflare a `Python-urllib`-et blokkolta a
# licencszervernél — ott ez működési feltétellé vált.
check("⚠ saját User-Agent (nem `Python-urllib`)",
      "TradeForge" in telegram._user_agent())

# ── 7b. A FELÜLETI KAPCSOLÓ ──────────────────────────────────────────────
# ⚠ A KÉT ÉRTESÍTÉS-TENGELY az instrumentum-ablakban is állítható legyen: eddig
# CSAK a `config.json`-ban lehetett, tehát gyakorlatilag elérhetetlen volt.
_gui = (ROOT / "dashboard" / "gui.py").read_text(encoding="utf-8")
check("⚠ a kötés-értesítés sor ott van az instrumentum-ablakban",
      '"notify_trade", _t("gui2.telegram_kotes")' in _gui)
check("⚠ ...és a jelzés-értesítés is",
      '"notify_signal", _t("gui2.telegram_jelzes")' in _gui)
check("⚠ a mentés MIND A NÉGY tengelyt egy táblából írja (nem külön if-ekkel)",
      "_TENGELYEK = ((\"viz\", _vp.VIZ)" in _gui)

# ⚠ A SOROK KULCSRA HIVATKOZNAK, NEM INDEXRE. Korábban a `_vars` a sor
# INDEXÉVEL volt kulcsozva (`_vars[(2, n)]` = vizualizáció): egy új sor
# beszúrása némán elcsúsztatta volna az alatta lévőket, és a mentés MÁS
# kapcsolót írt volna, mint amit a felhasználó átállított.
import re as _re
# ⚠ A KOMMENTEKET KI KELL SZŰRNI: a régi alak MAGYARÁZATKÉNT ott áll a kódban
# (épp azért, hogy ne kerüljön vissza) — egy szöveges keresés kódnak látná.
_gui_kod = chr(10).join(l for l in _gui.splitlines()
                        if not l.strip().startswith("#"))
check("⚠ nincs SOR-INDEXRE hivatkozó `_vars` (a beszúrás ne csússzon el)",
      not _re.search(r"_vars\[\(\d", _gui_kod),
      str(_re.findall(r"_vars\[\(\d+, n\)\]", _gui_kod)[:3]))

# A tömeges alkalmazás („minden instrumentumra") is ismerje a két sort —
# különben átállítanád, és NÉMÁN csak ezen a páron érvényesülne.
from core import bulk_apply as _ba
check("⚠ a tömeges alkalmazás ismeri a két értesítés-sort",
      "notify_trade" in _ba.ROWS and "notify_signal" in _ba.ROWS)
check("...és NEM jelöli pénzt érintőnek (csak szól, nem köt)",
      not _ba.affects_money(["notify_trade", "notify_signal"]))
check("a változás-felismerés meglátja őket",
      _ba.changed_rows({"notify_signal": {"a": False}},
                       {"notify_signal": {"a": True}}) == {"notify_signal"})

# ── 8b. NAPI ZÁRÁS-ÖSSZEFOGLALÓ ──────────────────────────────────────────
# ⚠ CSAK HA KÉRTED: üres `daily_summary_time` → nincs esti üzenet.
_ido = [datetime(2026, 9, 1, 23, 1).timestamp()]
_hivva = []
n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",)),
                    transport=lambda t: (_hivva.append(t) or True),
                    ora=lambda: _ido[0], daily=lambda: "Ma: 3 nyitás")
notify._cfg_json = {"pairs": {}}
n._idozitett()
check("⚠ időpont nélkül NINCS napi összefoglaló", not _hivva)

_ido = [datetime(2026, 9, 1, 23, 1).timestamp()]
_hivva = []
n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",),
                                  daily_time="23:00"),
                    transport=lambda t: (_hivva.append(t) or True),
                    ora=lambda: _ido[0], daily=lambda: "Ma: 3 nyitás")
n._idozitett()
check("a megadott időpontban KIMEGY", len(_hivva) == 1, str(_hivva)[:60])
check("...a dátummal a fejlécében", "2026-09-01" in _hivva[0])
check("...és a NAP TARTALMÁVAL", "3 nyitás" in _hivva[0])
# ⚠ NAPONTA EGYSZER: a szál 30 mp-enként néz oda, az ablak öt perc — enélkül
# tízszer menne ki ugyanaz.
_ido[0] += 60
n._utolso_ellenorzes = 0
n._idozitett()
check("⚠ ...de NAPONTA CSAK EGYSZER", len(_hivva) == 1, f"{len(_hivva)} üzenet")
_ido[0] = datetime(2026, 9, 2, 23, 1).timestamp()
n._utolso_ellenorzes = 0
n._idozitett()
check("...másnap viszont újra", len(_hivva) == 2)

# ⚠ A CSENDES ÓRÁT TISZTELETBEN TARTJA: ha 23:00-ra állítod és a csend 22:00-kor
# kezdődik, az összefoglaló REGGEL jön meg — a halasztott kötésekkel együtt.
_ido = [datetime(2026, 9, 1, 23, 1).timestamp()]
_hivva = []
n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",),
                                  daily_time="23:00", quiet_from="22:00",
                                  quiet_to="07:00"),
                    transport=lambda t: (_hivva.append(t) or True),
                    ora=lambda: _ido[0], daily=lambda: "Ma: 3 nyitás")
n._csend_volt = True
n._idozitett()
check("⚠ csendes órában NEM csörög az esti összefoglaló", not _hivva)
check("...de FÉLRETESSZÜK", len(n._halasztott) == 1)
_ido[0] = datetime(2026, 9, 2, 7, 30).timestamp()
n._utolso_ellenorzes = 0
n._idozitett()
check("⚠ ...és reggel, a csend végén megjön", len(_hivva) == 1
      and "3 nyitás" in _hivva[0], str(_hivva)[:60])

# ⚠ A TARTALOM ELŐÁLLÍTÁSA NEM VIHETI EL A SZÁLAT.
_ido = [datetime(2026, 9, 1, 23, 1).timestamp()]


def _robban_daily():
    raise RuntimeError("a mai sorok nem olvashatók")


n = notify.Notifier(notify.Config(enabled=True, token="T", chat_ids=("1",),
                                  daily_time="23:00"),
                    transport=lambda t: True, ora=lambda: _ido[0],
                    daily=_robban_daily)
n._idozitett()
check("⚠ hibás tartalom-előállítás sem dob", True)

# A napi összefoglaló UGYANABBÓL a `cmd_today`-ből épül, mint a `/today`.
_lt = (ROOT / "trading" / "live_trader.py").read_text(encoding="utf-8")
check("⚠ az esti üzenet a KÖZÖS `cmd_today`-ből jön",
      "cmd_today(_ctx" in _lt and "daily=_napi_szoveg" in _lt)
check("⚠ ...és a Telegram-parancsok UGYANAZT a környezetet kapják",
      _lt.count("_cc.live_context(") == 1 and "_tgc.setup(cfg, _ctx)" in _lt)

# ── 9b. A CHAT_ID MEGTALÁLÁSA ────────────────────────────────────────────
# ⚠ MIÉRT A BOT KERESI MEG. A bot ÚGYSEM tud írni annak, aki nem kezdeményezett
# vele beszélgetést — ha tehát valaki írt már neki, a `chat_id`-ja a
# `getUpdates`-ben amúgy is ott van. Egy kézzel átmásolt azonosítónál ez
# kevesebbet lehet elgépelni, és a @userinfobot-ot is megspórolja.
_eredeti_upd = telegram.updates
try:
    telegram.updates = lambda tok, offset=0, timeout=0: (True, [
        {"update_id": 1, "message": {"chat": {
            "id": 12345, "first_name": "Tibor", "last_name": "B"}}},
        {"update_id": 2, "message": {"chat": {"id": 12345}}},        # ismétlés
        {"update_id": 3, "channel_post": {"chat": {
            "id": -100, "title": "Csoport"}}},
    ])
    _t2 = telegram.discover_chats("T")
    check("a `chat_id` a bejövő üzenetekből megtalálható", len(_t2) == 2,
          str(_t2))
    check("...névvel együtt", _t2[0]["name"] == "Tibor B", str(_t2[0]))
    check("⚠ ...és ugyanaz a chat csak EGYSZER szerepel",
          [x["id"] for x in _t2] == ["12345", "-100"])
    telegram.updates = lambda tok, offset=0, timeout=0: (False, [])
    check("⚠ hálózati hibánál ÜRES lista (nem kivétel)",
          telegram.discover_chats("T") == [])
finally:
    telegram.updates = _eredeti_upd

# A beüzemelő parancs be van kötve, és a HIBÁT is jelzi a kilépési kóddal.
_main = (ROOT / "main.py").read_text(encoding="utf-8")
check("a `notify-test` parancs regisztrálva van", '"notify-test"' in _main)
check("⚠ ...és a kilépési kód a hibát is jelzi (szkriptelhető)",
      "sys.exit(fn() or 0)" in _main)
# ⚠ A kikapcsolt `enabled`-et NEM állítjuk át magunktól: lehet szándékos.
check("⚠ a beüzemelő nem kapcsolja be magától az értesítést",
      'notify.cli.disabled' in _main and '"enabled"] = True' not in _main)

# ── 10. Katalógus + config-példa ─────────────────────────────────────────
import json
_hu = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
_en = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
_nk = [k for k in _hu if k.startswith("notify.")]
check("vannak `notify.*` kulcsok", len(_nk) >= 10, f"{len(_nk)}")
check("⚠ mind le van fordítva angolra", not [k for k in _nk if k not in _en])
_pelda = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
check("a `notify` blokk dokumentálva van a config-példában", "notify" in _pelda)
check("⚠ ...és alapból KI van kapcsolva (senki ne kapjon váratlan üzenetet)",
      _pelda["notify"]["enabled"] is False)
check("⚠ ...token nélkül (a példa-config nyilvános)",
      _pelda["notify"]["telegram"]["token"] == "")

# ── AZ ÁR SOSEM TUDOMÁNYOS ALAKBAN ────────────────────────────────────────
# ⚠ HARMADSZOR UGYANAZ A HIBA. A `%.5g` nagy szintnél exponenciálisra vált; a
# felhasználó Telegram-üzenetében ez állt (2026-09-02):
#     Bra50 BUY JELZÉS @ 1.8087e+05 / SL 1.8044e+05 · TP 1.8173e+05
# Ebből a stop TÁVOLSÁGA — az egyetlen szám, amiből a kockázat megítélhető —
# leolvashatatlan. (Ugyanez elsült az `Offer.fmt`-ben és a kézi laborban is.)
_regi_cfg = notify._cfg_json
notify._cfg_json = {"pairs": {
    "Bra50":  {"point_size": 1.0},
    "USDJPY": {"point_size": 0.001},
    "EURCHF": {"point_size": 0.00001},
    "Ger40":  {"point_size": 0.01},
}}
try:
    for _sym, _ertek, _vart in (("Bra50", 180870.0, "180870"),
                                ("USDJPY", 159.55, "159.550"),
                                ("EURCHF", 0.94287, "0.94287"),
                                ("Ger40", 25816.16, "25816.16")):
        _kapott = notify._szam(_ertek, _sym)
        check(f"{_sym}: az ar az instrumentum tizedeseivel",
              _kapott == _vart, f"{_kapott} (vart: {_vart})")
    for _sym, _ertek in (("Bra50", 180870.0), ("Ger40", 25816.16)):
        check(f"{_sym}: NINCS exponencialis alak",
              "e" not in notify._szam(_ertek, _sym).lower())
    # ⚠ ISMERETLEN PARNAL SEM eshet vissza tudomanyosra: ott a nagysagrend dont.
    check("ismeretlen parnal sincs exponencialis alak",
          "e" not in notify._szam(180870.0, "NINCSILYEN").lower(),
          notify._szam(180870.0, "NINCSILYEN"))
    check("szimbolum nelkul sincs exponencialis alak",
          "e" not in notify._szam(180870.0).lower(), notify._szam(180870.0))
    check("ertelmezhetetlen ertekre '-'", notify._szam(None) == "-")
finally:
    notify._cfg_json = _regi_cfg


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
