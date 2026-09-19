"""JAVASLAT — amit a karmester TENNE.

⚠ MIÉRT VAN EZ KÜLÖN TÍPUS, ÉS MIÉRT MOST. A terv szerint a karmester (és
később az LLM) SOHA nem hív közvetlenül végrehajtást: a kimenete mindig egy
javaslat-objektum, amit determinisztikus ellenőrzés enged tovább. Ha a
házirendek egyszerűen „megcsinálnák", amit jónak látnak, akkor
  • nem volna hol megállítani őket (mandátum, kvóta, emberi jóváhagyás),
  • nem volna mit naplózni az árnyék-módban (ahol MÉG nem cselekszünk),
  • és nem volna mit visszavonni.

⚠ MINDEN JAVASLAT VISZI A BIZONYÍTÉKÁT. A `evidence` a döntést hozó SZÁMOK
szótára. Enélkül a krónika sora („visszaminősítés") fél év múlva
értelmezhetetlen: nem derülne ki, mi alapján született, és nem lehetne utólag
megmondani, jó döntés volt-e. A terv invariánsa szó szerint ez: indok nélkül
nincs döntés — `(szabály-azonosító, bemenő számok, küszöb)`.

⚠ A `needs_human` NEM UDVARIASSÁG. A PÉNZT BEKAPCSOLÓ lépés (papír → élő) a
terv szerint emberi jóváhagyáshoz kötött, és ez nem az autonómia-szinttől függ:
a `console_cmd.set_trade_mode` is megerősítést kér rá. Ami a BIZTONSÁGOS irányba
visz (élő → papír, leállítás, kockázatcsökkentés), az nem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── AMIT JAVASOLNI LEHET (stabil kódok) ──────────────────────────────────
# ⚠ Mindegyikhez VAN meglévő végrehajtási út a közös parancs-rétegben —
# szándékosan: egy javaslat, amit nem lehet végrehajtani, csak zaj.
SET_MODE_LIVE   = "set_mode_live"     # console_cmd.set_trade_mode(..., live)
SET_MODE_SIGNAL = "set_mode_signal"   # console_cmd.set_trade_mode(..., signal)
QUEUE_OPTIMIZE  = "queue_optimize"    # az optimalizálás-sor (F2)
HOLD            = "hold"              # nincs teendő — de az OKÁT kimondjuk

ACTIONS = (SET_MODE_LIVE, SET_MODE_SIGNAL, QUEUE_OPTIMIZE, HOLD)

# A pénzt BEKAPCSOLÓ akciók: ezekhez a terv szerint EMBER kell.
MONEY_ON = (SET_MODE_LIVE,)


@dataclass
class Proposal:
    """Egy javaslat. TISZTA adat: se fájl, se hálózat, se végrehajtás."""
    action: str
    symbol: str = ""
    strategy: str = ""
    reason: str = ""                     # stabil kód (pl. "dried_up")
    text: str = ""                       # emberi mondat (a kijelzéshez)
    evidence: dict = field(default_factory=dict)
    from_stage: str = ""
    to_stage: str = ""

    @property
    def needs_human(self) -> bool:
        """Kell-e hozzá emberi jóváhagyás, autonómia-szinttől függetlenül?"""
        return self.action in MONEY_ON

    @property
    def code(self) -> str:
        """A krónika/ismétlődés-szűrés kulcsa: az AKCIÓ és az INDOK együtt.

        ⚠ Miért mindkettő: ugyanaz az akció más okból MÁS döntés (a
        visszaminősítés elszáradás miatt és romlás miatt nem ugyanaz), és a
        krónikában ezt látni kell."""
        return f"{self.action}:{self.reason}" if self.reason else self.action

    def valid(self) -> bool:
        return (self.action in ACTIONS
                and bool(self.symbol) and bool(self.strategy))

    def as_dict(self) -> dict:
        return {"action": self.action, "symbol": self.symbol,
                "strategy": self.strategy, "reason": self.reason,
                "text": self.text, "evidence": dict(self.evidence or {}),
                "from_stage": self.from_stage, "to_stage": self.to_stage,
                "needs_human": self.needs_human}
