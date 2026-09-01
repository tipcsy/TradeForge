"""Bejövő Telegram-parancsok: KI adhat parancsot, MIT lehet, és mi nem.

⚠ A HÁROM KÉRDÉS, AMI PÉNZBE KERÜLHET:

  1. **Ki adhat parancsot.** Csak a configban felsorolt `chat_ids`. Mindenki
     más **némán** semmit nem kap vissza — egy „nincs jogod" válasz elárulná,
     hogy a bot létezik és mit tud. Egy nyilvános bot-nevet bárki megtalál.
  2. **Mit lehet távolról.** ENGEDÉLYEZŐ lista, nem tiltó: egy új parancs a
     `console_cmd`-ben ne váljon automatikusan távolról is elérhetővé.
  3. **A megerősítés nem szöveg, hanem GOMB** — és a gomb magával viszi az
     ajánlat azonosítóját. Két egyidejű ajánlatnál egy szöveges „igen"
     kétértelmű lenne, és épp rossz páron csinálna valamit.

⚠ A teszt HÁLÓZAT NÉLKÜL fut: a `feldolgoz()` KIMENŐ LÉPÉSEKET ad vissza, a
küldés külön van. Így a teljes döntési logika lejátszható.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

import logging
logging.disable(logging.INFO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


from core import console_cmd as cc
from core import telegram_cmd as tgc

ENGEDETT_CHAT = "7293441801"
IDEGEN_CHAT = "999999"


class _DS:
    def __init__(self, pnl=None):
        self.position_pnl = pnl


def ctx_epit(poz=None, pnl=None):
    cfg = {
        "pairs": {
            "Ger40": {"strategies": ["wpr_sma", "bollinger_squeeze"],
                      "run_state": {"wpr_sma": "live",
                                    "bollinger_squeeze": "live"}},
            "EURUSD": {"strategies": ["wpr_sma"],
                       "run_state": {"wpr_sma": "stopped"}},
        },
        "strategy": {"name": "wpr_sma"},
    }
    return cfg, cc.Context(
        cfg=cfg, save_config=lambda: True,
        positions=lambda: list(poz or []),
        close_position=lambda t: True,
        account=lambda: {"balance": 981.0, "currency": "EUR", "daily_pnl": -1.0},
        dashboard={"Ger40": _DS(pnl)},
        instrument_state={"Ger40": "LIVE", "EURUSD": "STOPPED"},
        strategies_of=lambda s: list(cfg["pairs"][s]["strategies"]),
        last_cycle_ts=lambda: __import__("time").time(),
        today_rows=lambda: [
            {"event": "open", "symbol": "Ger40", "strategy": "wpr_sma"},
            {"event": "close", "symbol": "Ger40", "strategy": "wpr_sma",
             "pnl_usd": 12.5},
            {"event": "signal", "symbol": "EURUSD", "strategy": "wpr_sma"},
        ])


def bot_epit(poz=None, pnl=None, ido=None):
    cfg, ctx = ctx_epit(poz, pnl)
    b = tgc.Bot(token="T", chat_ids=(ENGEDETT_CHAT,), ctx=ctx)
    if ido is not None:
        b.ora = lambda: ido[0]
    return cfg, b


def uzenet(szoveg, chat=ENGEDETT_CHAT, uid=1):
    return {"update_id": uid,
            "message": {"message_id": 10, "chat": {"id": chat}, "text": szoveg}}


def gomb(adat, chat=ENGEDETT_CHAT, uid=2, mid=10):
    return {"update_id": uid, "callback_query": {
        "id": "cb1", "data": adat,
        "message": {"message_id": mid, "chat": {"id": chat}}}}


# ── 1. KI adhat parancsot ────────────────────────────────────────────────
_cfg, b = bot_epit()
check("az engedélyezett chat parancsa lefut",
      len(b.feldolgoz(uzenet("/help"))) == 1)
# ⚠ AZ IDEGEN CHAT NEM KAP SEMMIT — még elutasítást sem. Egy „nincs jogod"
# válasz elárulná, hogy a bot létezik, és hogy van mit kérni tőle.
check("⚠ IDEGEN chat NÉMÁN nem kap semmit",
      b.feldolgoz(uzenet("/help", chat=IDEGEN_CHAT)) == [])
check("⚠ ...és a gombjára sem reagálunk",
      b.feldolgoz(gomb("i:akarmi", chat=IDEGEN_CHAT)) == [])
check("üres/nem szöveges üzenet nem hiba",
      b.feldolgoz({"update_id": 3, "message": {"chat": {"id": ENGEDETT_CHAT}}}) == [])
check("ismeretlen frissítés-fajta sem", b.feldolgoz({"update_id": 4}) == [])

# ── 2. MIT lehet távolról ────────────────────────────────────────────────
# ⚠ ENGEDÉLYEZŐ LISTA: egy új `console_cmd` parancs ne váljon automatikusan
# távolról elérhetővé. A `quit` (motor leállítása) és a `close` (pozíció
# zárása) szándékosan NINCS benne.
check("⚠ a `quit` NEM adható ki távolról",
      "quit" not in tgc.ENGEDETT and
      "Ismeretlen" in b.feldolgoz(uzenet("/quit"))[0].text)
check("⚠ a `close` sem (pozíciót zárni távolról nem lehet)",
      "close" not in tgc.ENGEDETT and
      "Ismeretlen" in b.feldolgoz(uzenet("/close 111"))[0].text)
check("⚠ az engedélyezett lista MINDEN eleme létező parancs",
      all(n in cc.COMMANDS for n in tgc.ENGEDETT),
      str([n for n in tgc.ENGEDETT if n not in cc.COMMANDS]))

for _p, _mit in (("/help", "help"), ("/pos", "pos"), ("/balance", "981"),
                 ("/state", "motor"), ("/heart", ""), ("/today", "Ma")):
    _k = b.feldolgoz(uzenet(_p))
    check(f"a {_p} válaszol", len(_k) == 1 and bool(_k[0].text),
          _k[0].text.splitlines()[0][:48] if _k else "")

# ⚠ CSOPORTBAN a Telegram `/pos@botnev` alakot küld — azt is értenünk kell.
check("⚠ a `/pos@botnev` alak is működik (csoportban ezt küldi a Telegram)",
      b.feldolgoz(uzenet("/pos@tradeforgebot"))[0].text ==
      b.feldolgoz(uzenet("/pos"))[0].text)
check("a `/` nélküli alak is jó", bool(b.feldolgoz(uzenet("pos"))[0].text))

# ── 3. A PARANCS UGYANAZ, MINT A KONZOLON ────────────────────────────────
# ⚠ Ha a bot a saját válaszát állítaná elő, a Telegram és a konzol ugyanarról
# a párról mást mondhatna.
_cfg, b = bot_epit()
_tg = b.feldolgoz(uzenet("/state"))[0].text
_konzol = "\n".join(cc.dispatch(b.ctx, "state").lines)
check("⚠ a Telegram és a konzol UGYANAZT a választ adja", _tg == _konzol)

# ── 4. A MEGERŐSÍTÉS: gomb, nem szöveg ───────────────────────────────────
POZ = [{"ticket": 111, "symbol": "Ger40", "type": "BUY", "volume": 0.1,
        "price_open": 100.0, "sl": 95.0, "tp": 110.0, "profit": 12.3}]
_cfg, b = bot_epit(poz=POZ, pnl=12.3)
_k = b.feldolgoz(uzenet("/stop Ger40"))
check("⚠ nyitott pozíciónál a `/stop` GOMBOT kínál", len(_k[0].buttons) == 2,
      str([x[0] for x in _k[0].buttons]))
check("...és a szövegében ott a KÖVETKEZMÉNY (kivezetés)",
      "pozíció" in _k[0].text, _k[0].text[:60])
check("⚠ ...de MÉG NEM csinált semmit",
      _cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "live")
# ⚠ A GOMB MAGÁVAL VISZI AZ AJÁNLAT AZONOSÍTÓJÁT — enélkül két egyidejű
# ajánlatnál egy „igen" kétértelmű lenne.
_igen = [a for f, a in _k[0].buttons if a.startswith("i:")][0]
_nem = [a for f, a in _k[0].buttons if a.startswith("n:")][0]
check("⚠ a gomb azonosítót visz (nem csak „igen”-t)",
      _igen.split(":")[1] == _nem.split(":")[1] and len(_igen) > 3)
check("⚠ a callback_data belefér a Telegram 64 bájtos korlátjába",
      len(_igen.encode("utf-8")) <= 64, f"{len(_igen)} bájt")

_k2 = b.feldolgoz(gomb(_igen))
check("megerősítve VÉGREHAJTJA",
      _cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "stopped")
check("⚠ ...a gombos üzenetet ÁTÍRJA (nincs mit kétszer megnyomni)",
      _k2[0].edit_message_id == 10 and bool(_k2[0].text))
check("...és nyugtázza a gombnyomást (nem pörög az óra)",
      _k2[0].callback_id == "cb1")
# ⚠ MÁSODSZOR ugyanaz a gomb már nem csinál semmit.
_k3 = b.feldolgoz(gomb(_igen))
check("⚠ ugyanaz a gomb MÁSODSZOR már nem hajt végre",
      "lejárt" in _k3[0].text or "expired" in _k3[0].text, _k3[0].text)

# A „Mégse" gomb ne csináljon semmit.
_cfg, b = bot_epit(poz=POZ, pnl=12.3)
_k = b.feldolgoz(uzenet("/stop Ger40"))
_nem = [a for f, a in _k[0].buttons if a.startswith("n:")][0]
_k2 = b.feldolgoz(gomb(_nem))
check("a „Mégse” nem hajt végre semmit",
      _cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "live")
check("...és ezt meg is mondja",
      "nem csinálom" in _k2[0].text or "not doing" in _k2[0].text)

# ── 5. AZ AJÁNLAT LEJÁR ──────────────────────────────────────────────────
# ⚠ Egy fél órája küldött gomb már MÁS helyzetre vonatkozna: az ár elment, a
# pozíció lezárulhatott. Lejárat után nem cselekszünk, hanem szólunk.
_ido = [1000.0]
_cfg, b = bot_epit(poz=POZ, pnl=12.3, ido=_ido)
_k = b.feldolgoz(uzenet("/stop Ger40"))
_igen = [a for f, a in _k[0].buttons if a.startswith("i:")][0]
_ido[0] += tgc.AJANLAT_MP + 1
_k2 = b.feldolgoz(gomb(_igen))
check("⚠ a LEJÁRT gomb nem hajt végre semmit",
      _cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "live")
check("...és megmondja, hogy elkésett",
      "lejárt" in _k2[0].text or "expired" in _k2[0].text)

# ⚠ MÁS CHAT gombját nem fogadjuk el, még ha az azonosító stimmelne is.
_cfg, b = bot_epit(poz=POZ, pnl=12.3)
_k = b.feldolgoz(uzenet("/stop Ger40"))
_igen = [a for f, a in _k[0].buttons if a.startswith("i:")][0]
b.chat_ids = (ENGEDETT_CHAT, IDEGEN_CHAT)     # mindkettő engedélyezett…
check("⚠ …de a MÁSIK chat gombja akkor sem hat",
      b.feldolgoz(gomb(_igen, chat=IDEGEN_CHAT)) == [] and
      _cfg["pairs"]["Ger40"]["run_state"]["wpr_sma"] == "live")

# ── 6. A HUROK NEM HALHAT MEG ────────────────────────────────────────────
# ⚠ Ha a hurokból kijönne egy kivétel, a bot NÉMÁN megszűnne válaszolni — és
# kívülről az pontosan úgy nézne ki, mint egy leállt program.
import inspect
_h = inspect.getsource(tgc.Bot._hurok)
check("⚠ a hurok minden hibát elkap", "except Exception" in _h)
check("⚠ ...és NÖVEKVŐ várakozással próbálkozik újra",
      "2 ** _hiba" in _h or "2**_hiba" in _h)
check("⚠ hosszú lekérdezést használ (nem percenként hatvanszor kérdez)",
      "timeout=POLL_MP" in _h and tgc.POLL_MP >= 10)

# Beállítás nélkül nem indul el (és nem is hibázik).
check("token/címzett nélkül a bot nem indul",
      tgc.setup({}, ctx_epit()[1]) is None)

# ── 7. Katalógus ─────────────────────────────────────────────────────────
import json
_hu = json.loads((ROOT / "lang" / "hu.json").read_text(encoding="utf-8"))
_en = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))
_k = [k for k in _hu if k.startswith("tg.")]
check("vannak `tg.*` kulcsok", len(_k) >= 5, f"{len(_k)}")
check("⚠ mind le van fordítva angolra", not [k for k in _k if k not in _en])

# ⚠ A PARANCSNEVEK ANGOLUL maradnak minden nyelven: telefonon gépelhetők, és a
# Telegram parancs-listájába változtatás nélkül átvihetők.
from core import i18n as _i18n
_i18n.set_language("en")
_cfg, b = bot_epit()
_ang = b.feldolgoz(uzenet("/help"))[0].text
_i18n.set_language("hu")
check("⚠ angol nyelven is ANGOL parancsnevek", "play" in _ang and "stop" in _ang)
check("...de a LEÍRÁS angol", "this list" in _ang or "Commands" in _ang)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
