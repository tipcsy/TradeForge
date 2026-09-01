"""BEJÖVŐ Telegram-parancsok — a `console_cmd` HARMADIK ügyfele.

⚠ A PARANCSOK NEM ITT LAKNAK. A `/pos`, `/play`, `/stop` ugyanazon a
`core.console_cmd.dispatch`-en megy, mint a konzolos parancssor és a TUI — a
`dispatch` a `/` előtagot már ma is érti. Ha a bot a sajátját írná meg, három
forrás romlana el külön; ez a projekt visszatérő hibaosztálya.

⚠ ENGEDÉLYEZETT CHAT-EK, ÉS SEMMI MÁS. A bot kizárólag a configban felsorolt
`chat_ids`-tól fogad parancsot. Minden más üzenetre **némán** hallgat — nem
válaszol, hogy „nincs jogod", mert az elárulná, hogy a bot létezik és mit tud.
Egy nyilvános bot-nevet bárki megtalálhat.

⚠ MEGERŐSÍTÉS GOMBBAL. A veszélyes parancsokat (`/stop` nyitott pozícióval) a
`console_cmd` NEM hajtja végre azonnal: `Result.confirm`-ot ad vissza. Itt ez
két gombbá válik. A gomb magával viszi az ajánlat AZONOSÍTÓJÁT — egy szöveges
„igen" két egyidejű ajánlatnál kétértelmű lenne, és épp rossz páron csinálna
valamit.

⚠ AZ AJÁNLAT LEJÁR. Egy fél órája küldött megerősítő gomb már más helyzetre
vonatkozna. Lejárat után a gomb megmondja, hogy elkésett — és NEM csinál semmit.

⚠ A HÁLÓZAT NEM ÁLLÍTHATJA MEG A MOTORT. A hurok külön szálon fut, hosszú
lekérdezéssel (long polling); minden hiba a szálon belül marad, és növekvő
várakozással próbálkozik újra.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field

from core import console_cmd as cc
from core.i18n import t as _t

log = logging.getLogger(__name__)

# ⚠ AMIT A BOTON KERESZTÜL SZABAD. SZÁNDÉKOSAN ENGEDÉLYEZŐ LISTA, nem tiltó:
# egy új parancs a `console_cmd`-ben ne váljon automatikusan TÁVOLRÓL is
# elérhetővé. A `quit` (a motor leállítása) és a `close` (pozíció zárása)
# szándékosan NINCS itt — azok a következő kör (kötést nyitó/záró) döntései.
ENGEDETT = ("help", "balance", "pos", "today", "state", "heart", "play", "stop")

# Meddig él egy megerősítő gomb.
AJANLAT_MP = 600

# A hosszú lekérdezés hossza. ⚠ NEM „lassú": a Telegram ennyi ideig VÁR egy új
# üzenetre, mielőtt üres választ adna — ettől lesz azonnali a válasz úgy, hogy
# közben nem terheljük percenként hatvanszor a szervert.
POLL_MP = 25


@dataclass
class Kimenet:
    """Egy kimenő lépés. ⚠ A hurok ezeket ÁLLÍTJA ELŐ, és külön küldi el — így a
    teljes döntési logika hálózat nélkül tesztelhető."""
    chat_id: str = ""
    text: str = ""
    buttons: tuple = ()
    callback_id: str = ""        # gombnyomás nyugtázása
    edit_message_id: int = 0     # meglévő üzenet átírása (a gombok eltűnnek)


@dataclass
class Bot:
    """A bejövő oldal. `ctx`: a `console_cmd.Context` (a motor állapota)."""
    token: str
    chat_ids: tuple
    ctx: "cc.Context"
    ora: object = time.time
    _offset: int = 0
    _fuggo: dict = field(default_factory=dict)   # azonosító → (chat, parancs, lejár)
    _szal: object = None
    _leall: object = field(default_factory=threading.Event)

    # ── A DÖNTÉS (tiszta, hálózat nélkül tesztelhető) ─────────────────
    def engedelyezett(self, chat_id) -> bool:
        return str(chat_id) in {str(x) for x in (self.chat_ids or ())}

    def feldolgoz(self, update: dict) -> list:
        """Egy `getUpdates`-rekord → kimenő lépések listája (lehet üres)."""
        # 1. GOMBNYOMÁS
        cq = update.get("callback_query") or {}
        if cq:
            uz = cq.get("message") or {}
            chat = str((uz.get("chat") or {}).get("id") or "")
            if not self.engedelyezett(chat):
                return []                       # ⚠ némán, lásd a modul fejlécét
            return self._gomb(cq, chat, uz)
        # 2. SZÖVEGES PARANCS
        uz = update.get("message") or update.get("edited_message") or {}
        chat = str((uz.get("chat") or {}).get("id") or "")
        szoveg = str(uz.get("text") or "").strip()
        if not chat or not szoveg or not self.engedelyezett(chat):
            return []
        return self._parancs(chat, szoveg)

    def _parancs(self, chat: str, szoveg: str) -> list:
        # A Telegram csoportban `/pos@botnev` alakot küld — a `@…` a miénk.
        elso, _, maradek = szoveg.partition(" ")
        nev = elso.lstrip("/").split("@")[0].lower()
        nev = cc.ALIASES.get(nev, nev)
        if nev not in ENGEDETT:
            return [Kimenet(chat_id=chat, text=_t("tg.unknown", name=elso))]
        sor = (nev + " " + maradek).strip()
        res = cc.dispatch(self.ctx, sor)
        if res.confirm:
            # ⚠ A parancsot NEM hajtottuk végre: gombot kínálunk hozzá.
            azon = secrets.token_urlsafe(8)
            self._fuggo[azon] = (chat, sor, float(self.ora()) + AJANLAT_MP)
            self._takarit()
            return [Kimenet(chat_id=chat, text=res.confirm,
                            buttons=((_t("tg.btn.yes"), f"i:{azon}"),
                                     (_t("tg.btn.no"), f"n:{azon}")))]
        return [Kimenet(chat_id=chat, text=self._szoveg(res))]

    def _gomb(self, cq: dict, chat: str, uz: dict) -> list:
        adat = str(cq.get("data") or "")
        cid = str(cq.get("id") or "")
        mid = int(uz.get("message_id") or 0)
        valasz, _, azon = adat.partition(":")
        bejegyzes = self._fuggo.pop(azon, None)
        if not bejegyzes or float(self.ora()) > bejegyzes[2]:
            # ⚠ LEJÁRT vagy ismeretlen → NEM csinálunk semmit. Egy fél órája
            # küldött gomb már más helyzetre vonatkozna.
            return [Kimenet(chat_id=chat, callback_id=cid,
                            edit_message_id=mid, text=_t("tg.expired"))]
        _chat, sor, _lejar = bejegyzes
        if _chat != chat:
            return []                            # más chat gombja — némán
        if valasz != "i":
            return [Kimenet(chat_id=chat, callback_id=cid,
                            edit_message_id=mid, text=_t("tg.cancelled"))]
        res = cc.dispatch(self.ctx, sor, confirmed=True)
        return [Kimenet(chat_id=chat, callback_id=cid, edit_message_id=mid,
                        text=self._szoveg(res))]

    @staticmethod
    def _szoveg(res: "cc.Result") -> str:
        return "\n".join(res.lines) if res.lines else "—"

    def _takarit(self) -> None:
        most = float(self.ora())
        for k in [k for k, v in self._fuggo.items() if v[2] < most]:
            self._fuggo.pop(k, None)

    # ── A HÁLÓZAT ─────────────────────────────────────────────────────
    def kuld(self, k: Kimenet) -> None:
        from core import telegram
        if k.callback_id:
            telegram.answer_callback(self.token, k.callback_id)
        if k.edit_message_id:
            # ⚠ ÁTÍRJUK a gombos üzenetet: onnantól az EREDMÉNY áll a helyén,
            # tehát nincs mit még egyszer megnyomni.
            if telegram.edit_message(self.token, k.chat_id,
                                     k.edit_message_id, k.text):
                return
        if k.buttons:
            telegram.send_buttons(self.token, k.chat_id, k.text, k.buttons)
        elif k.text:
            telegram.send(self.token, [k.chat_id], k.text)

    def start(self) -> None:
        if self._szal is not None:
            return
        self._szal = threading.Thread(target=self._hurok, daemon=True,
                                      name="TradeForgeTgCmd")
        self._szal.start()

    def stop(self) -> None:
        self._leall.set()

    def _hurok(self) -> None:
        from core import telegram
        _hiba = 0
        while not self._leall.is_set():
            try:
                ok, upd = telegram.updates(self.token, offset=self._offset,
                                           timeout=POLL_MP)
                if not ok:
                    # ⚠ NÖVEKVŐ VÁRAKOZÁS: egy elérhetetlen Telegram ne
                    # pörgesse a hálózatot és a naplót másodpercenként.
                    _hiba = min(_hiba + 1, 6)
                    self._leall.wait(min(60, 2 ** _hiba))
                    continue
                _hiba = 0
                for u in upd:
                    self._offset = max(self._offset,
                                       int(u.get("update_id") or 0) + 1)
                    for k in self.feldolgoz(u):
                        self.kuld(k)
            except Exception:
                # ⚠ A SZÁL NEM HALHAT MEG. Ha itt kijönne egy kivétel, a bot
                # némán megszűnne válaszolni — és kívülről az pontosan úgy
                # nézne ki, mint egy leállt program.
                log.warning("telegram-parancsok: a hurok hibára futott",
                            exc_info=True)
                self._leall.wait(5)


# ── Modul-szintű egyke ────────────────────────────────────────────────────
_bot: "Bot | None" = None


def setup(cfg: dict, ctx: "cc.Context") -> "Bot | None":
    """A bejövő oldal bekapcsolása. `None`, ha nincs beállítva."""
    global _bot
    from core import notify
    c = notify.read_config(cfg)
    if not c.kesz:
        _bot = None
        return None
    _bot = Bot(token=c.token, chat_ids=c.chat_ids, ctx=ctx)
    _bot.start()
    log.info("telegram-parancsok: BEKAPCSOLVA (%d engedélyezett chat)",
             len(c.chat_ids))
    return _bot


def active() -> "Bot | None":
    return _bot
