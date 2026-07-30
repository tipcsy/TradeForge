"""A „Lezart" ful datum-intervalluma: a nap hatara a BROKER naptara szerint.

Miert ez a lenyeg: a `server_day_bounds()` doksija egy MAR MEGTORTENT hibat ir le
— a nap hatara a gep HELYI datumabol jott, UTC-nek cimkezve, es ezert a napi limit
orakkal korabban lenullazodott. Az intervallumos valtozat ugyanebbe a csapdaba
tudna belefutni, ezert itt a szerver-eltolas kezeleset teszteljuk.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import mt5_connector as mc

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def with_offset(off, fn):
    """A modul-szintu szerver-eltolas ATMENETI beallitasa."""
    prev = mc._server_offset["v"]
    mc._server_offset["v"] = off
    try:
        return fn()
    finally:
        mc._server_offset["v"] = prev


D = date(2026, 7, 30)

# ══ 1. Nulla eltolas: a hatarok pontosan UTC-ejfelek ═════════════════════
frm, to = with_offset(0.0, lambda: mc.server_day_bounds_for(D, D))
check("egy nap -> 24 ora", (to - frm) == timedelta(days=1), f"{to - frm}")
check("eltolas nelkul a kezdet UTC-ejfel",
      frm == datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc), str(frm))
check("a vege a KOVETKEZO nap ejfele (a 'ig' beleertve)",
      to == datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc), str(to))

# ══ 2. A hatar NEM fugg az eltolastol — es ez SZANDEKOS ══════════════════
# A konvencio: a visszaadott datetime a BROKER FALIORAJANAK ideje, UTC-nek
# CIMKEZVE (a history_deals_get igy varja). A datum mar a broker napjat nevezi
# meg, tehat nincs mit korrigalni. Az elso valtozatom kivonta az eltolast, es
# ezzel GMT+3-nal 3 oraval elcsuszott volna a "ma" nezettol.
for _off in (0.0, 3 * 3600, -5 * 3600):
    b = with_offset(_off, lambda: mc.server_day_bounds_for(D, D))
    check(f"eltolas {_off/3600:+.0f}h -> UGYANAZ a hatar (broker-falioras konvencio)",
          b == (frm, to), f"{b[0]}")

# ══ 3. Tobb napos intervallum ════════════════════════════════════════════
f7, t7 = with_offset(0.0, lambda: mc.server_day_bounds_for(D - timedelta(days=6), D))
check("7 napos intervallum -> 7x24 ora", (t7 - f7) == timedelta(days=7), f"{t7 - f7}")

# ══ 4. FORDITOTT sorrend: megcsereljuk, nem adunk ures listat ════════════
# Ha nem cserelnenk, a lekeres ures lenne, es ugy tunne, "nincs adat" — holott
# csak a ket mezo fel van cserelve.
fa, ta = with_offset(0.0, lambda: mc.server_day_bounds_for(D, D - timedelta(days=3)))
check("forditva megadott intervallum MEGCSEREL (nem ures)",
      ta > fa and (ta - fa) == timedelta(days=4), f"{fa} .. {ta}")

# ══ 5. A 'ma' nezet a SZUKITETT esete az intervallumnak ══════════════════
# Ugyanaz a deal-feldolgozas fut mindkettoben (`closed_positions_range`), hogy a
# "ma" es a "tol-ig" SOSE mondhasson mast ugyanarra a kereskedesre.
import inspect
src = inspect.getsource(mc.closed_positions_today)
check("closed_positions_today() a range-valtozatot hivja",
      "closed_positions_range" in src, src.strip().splitlines()[-1].strip())
check("closed_positions_range letezik es hivhato",
      callable(mc.closed_positions_range))
check("a szerver-hatart a today-nezet is a bounds-bol veszi",
      "server_day_bounds()" in src)
check("server_today() a BROKER datumat adja (nem a gepét)",
      callable(mc.server_today))

# ══ 6. A 'ma' es az explicit mai intervallum EGYEZIK ═════════════════════
def _same():
    # A broker mai datuma -> explicit intervallum. Ennek EGYEZNIE kell a
    # server_day_bounds() altal adott "ma" hatarral, kulonben a ket nezet mast
    # mutatna ugyanarra a napra.
    return mc.server_day_bounds(), mc.server_day_bounds_for(mc.server_today(),
                                                            mc.server_today())


a, b = with_offset(3 * 3600, _same)
check("a 'ma' hatarai megegyeznek az explicit mai intervallummal",
      a == b, f"{a} vs {b}")

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
