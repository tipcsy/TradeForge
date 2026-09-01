"""JELZÉS-AJÁNLATOK — „csak jelzés" módú belépő, amit KÉZZEL kell jóváhagyni.

⚠ MIT CSINÁL, ÉS MIÉRT VESZÉLYES. Egy `signal` módú pár+stratégia jelzésénél a
motor MINDENT kiszámol (irány, SL/TP, lot), de nem küld megbízást. Ez a modul
azt az elkészült tervet őrzi meg addig, amíg a felhasználó a Telegramban rá nem
nyom az „Igen"-re — onnantól **egy chatüzenetből valódi pozíció lesz**. Ezért
minden itteni szabály a NEMET erősíti:

* **Alapból KI.** A `notify.answer_trading` nélkül ajánlat nem is keletkezik.
  Aki csak értesítést akar, ne kapjon véletlenül távirányítót a számlájához.
* **Csak `signal` módú pár+stratégia.** A `live` módúaknál a motor amúgy is köt;
  ott a gomb vagy dupla pozíciót nyitna, vagy zavaró lenne.
* **Az ajánlat LEJÁR** — jel-gyertya/2, de legalább egy perc. Egy fél órája
  küldött gomb már más árra és más helyzetre vonatkozna.
* **Egyszer használható.** Az elfogadott (vagy elutasított) ajánlat elfogy: a
  kétszer megnyomott „Igen" EGY pozíciót nyit.
* **A kapuk nem kerülhetők meg.** A végrehajtás ugyanazon a
  `live_trader._execute_entry`-n megy, mint a motor saját belépője, és előtte
  ugyanazok az ellenőrzések futnak (nyitott pozíció, slot, napi limit).
* **A megcsúszott ár külön kérdés.** Ha az ár a terv óta 0,25 R-nél többet
  mozdult, az „Igen" NEM köt: megmondja, mennyit mozdult, és újra rákérdez.

Ez a modul TISZTA: nem ismer MT5-öt és Telegramot. Csak az ajánlatok
nyilvántartása és a lejárat/elmozdulás szabálya van benne — hálózat nélkül
végigjátszható.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

# Az ajánlat élettartama: a JEL-GYERTYA FELE. ⚠ A felhasználó döntése: „egy
# kicsit szigorúbb lennék". M15-nél 7,5 perc, H1-nél 30 perc.
FELEZO = 2
# ...de legalább ennyi: egy M1-es jelnél a fele 30 mp lenne, ami alatt az üzenet
# átérése sem biztos. ⚠ A felhasználó kérése: „M1-nél 1 perc".
MIN_ELET_MP = 60

# Mekkora ár-elmozdulásig köt az „Igen" kérdés nélkül — a STOP töredékében.
# ⚠ Egy 0,4 R-rel arrébb nyitott pozíció már nem az a kötés, amit a stratégia
# javasolt: a hozam/kockázat aránya más, a szetup logikája elveszett.
SODRODAS_R = 0.25

# Állapotok
NYITOTT = "nyitott"
ELFOGADVA = "elfogadva"
ELUTASITVA = "elutasitva"


@dataclass
class Offer:
    """Egy jóváhagyásra váró belépő TERVE."""
    id: str
    symbol: str
    strategy: str
    direction: str                 # "BUY" | "SELL"
    lot: float
    entry: float                   # a jel ára (a terv szerinti belépő)
    sl_points: float               # a stop TÁVOLSÁGA pontban (ez az 1 R)
    tp_points: float
    point_size: float
    magic: int
    pv1_point: float = 0.0
    risk_ccy: float = 0.0
    created: float = 0.0
    expires: float = 0.0
    state: str = NYITOTT
    # ⚠ A MÁSODIK megerősítés jelölése: a megcsúszott árnál az első „Igen" még
    # NEM köt, csak rákérdez. Enélkül a „mégis" gomb ugyanazt az utat járná,
    # és megint elutasítaná — a felhasználó sosem jutna a kötésig.
    drift_ok: bool = False

    def lejart(self, most: float) -> bool:
        return most > self.expires

    def elerheto(self, most: float) -> bool:
        return self.state == NYITOTT and not self.lejart(most)

    def sodrodas_r(self, ar: float) -> float:
        """Mennyit mozdult az ár a tervhez képest, R-ben (előjel nélkül)."""
        if not self.sl_points or not self.point_size:
            return 0.0
        return abs(float(ar) - self.entry) / (self.sl_points * self.point_size)

    def fmt(self, ar: float) -> str:
        """Ár SZÖVEGKÉNT, a pont-méret szerinti tizedesekkel.

        ⚠ MIÉRT NEM `%.5g`. Egy Ger40-jelzésnél az öt értékes jegy ezt adta:
        „belépő 23457 · SL 23456 · TP 23459" — a három szint ránézésre EGYFORMA,
        és épp a stop TÁVOLSÁGA tűnt el, amiből meg lehetne ítélni a kötést. A
        pont-méret pontosan megmondja, hány tizedes érdekes."""
        try:
            import math
            p = float(self.point_size or 0.0)
            tiz = 0 if p <= 0 else min(8, max(0, int(round(-math.log10(p)))))
            return f"{float(ar):.{tiz}f}"
        except (TypeError, ValueError, OverflowError):
            return f"{float(ar):.5g}"

    def celok(self, ar: float) -> tuple:
        """`(sl, tp)` egy ADOTT belépő árhoz — a TÁVOLSÁGOK megtartásával.

        ⚠ A GEOMETRIA MARAD, A SZINT CSÚSZIK. Ha az eredeti (abszolút) SL/TP
        szintet vinnénk át egy megcsúszott belépőre, a kockázat csendben
        megváltozna: ugyanaz a lot MÁS R-t jelentene."""
        d = 1 if self.direction == "BUY" else -1
        return (float(ar) - d * self.sl_points * self.point_size,
                float(ar) + d * self.tp_points * self.point_size)


class Registry:
    """Az élő ajánlatok. Szálbiztos, mert a motor írja és a Telegram olvassa."""

    def __init__(self, ora=None):
        self.ora = ora or time.time
        self._lock = threading.Lock()
        self._elemek: dict = {}

    def elettartam(self, jel_gyertya_mp: int) -> int:
        """Az ajánlat élettartama másodpercben a jel-gyertya hosszából."""
        mp = int(jel_gyertya_mp or 0) or MIN_ELET_MP
        return max(MIN_ELET_MP, mp // FELEZO)

    def keszit(self, jel_gyertya_mp: int = 0, **mezok) -> Offer:
        most = float(self.ora())
        o = Offer(id=secrets.token_urlsafe(8), created=most,
                  expires=most + self.elettartam(jel_gyertya_mp), **mezok)
        with self._lock:
            self._elemek[o.id] = o
            self._takarit(most)
        return o

    def get(self, oid: str) -> "Offer | None":
        with self._lock:
            return self._elemek.get(str(oid))

    def lezar(self, oid: str, allapot: str) -> "Offer | None":
        """Az ajánlat elfogyasztása. ⚠ Az ELSŐ hívó kapja meg — a második
        `None`-t, tehát a kétszer megnyomott gomb EGY pozíciót nyit."""
        with self._lock:
            o = self._elemek.get(str(oid))
            if o is None or o.state != NYITOTT:
                return None
            o.state = allapot
            return o

    def nyitott(self) -> list:
        most = float(self.ora())
        with self._lock:
            return [o for o in self._elemek.values() if o.elerheto(most)]

    def _takarit(self, most: float) -> None:
        # A lejárt ajánlatokat egy ideig MEGTARTJUK: így a késve megnyomott
        # gomb azt kapja vissza, hogy „lejárt", nem azt, hogy „ismeretlen".
        for k in [k for k, o in self._elemek.items()
                  if most - o.created > 24 * 3600]:
            self._elemek.pop(k, None)


# Modul-szintű nyilvántartás (a motor és a Telegram ugyanezt látja).
REGISTRY = Registry()


def enabled(cfg: dict) -> bool:
    """Be van-e kapcsolva a válaszos kötés? ⚠ ALAPBÓL NEM."""
    return bool(((cfg or {}).get("notify") or {}).get("answer_trading", False))
