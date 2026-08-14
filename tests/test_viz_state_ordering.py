"""A viz-fajl STATE sorai: EGY sav = EGY strategia, es a keresés nem felteheti,
hogy a fajl idorendben van.

⚠ A LELET (Ger40, 2026-08-14). A TFBANDS sav „szaggatottan" jelzett, holott a
motor kozben pozicioba lepett. A sav a fajl OSSZES strategiajanak STATE sorait
egy tombbe olvasta (`InpStrategy` alapertelmezese „ures = MIND"), majd BINARIS
KERESESSEL kereste hozza az idopontot — az viszont RENDEZETT tombot feltetelez.
A fajl strategia-BLOKKONKENT keszul: a wpr_sma teljes sorozata (06-25 -> 08-14)
UTAN a bollinger sorozata UJRAKEZDTE az idot. A binaris keresés egy nem-monoton
tombon tetszoleges indexet ad vissza.

Merve a valodi fajlon (211 M1 gyertya, 11:30-15:00): a rajzolt allapot 0%-ban
egyezett a wpr_sma valos allapotaval — 55% NEM RAJZOLT SEMMIT (ez volt a
„szaggatas"), 45% pedig a MASIK strategia orankenti sorait mutatta. A javitas
utan 100% (folytonos zold + a addig teljesen hianyzo kek ablak-sav).

⚠ KET FUGGETLEN HIBA volt egyszerre, es MINDKETTOT javitani kell:
  1. TOBB strategia EGY savon — ertelmetlen: egy sav nem tud ket allapotot
     egyszerre mutatni. Ures input -> a fajl ELSO strategiaja, es KI VAN IRVA.
  2. RENDEZETLEN tomb + binaris keresés. Az egyes szures ma helyreallitja a
     monotonitast, de a keresés helyessege NEM fugghet attol, milyen sorrendben
     irja ki a Python a blokkokat — egy artalmatlan atrendezes nemam elrontana.
"""
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


from strategy.visual import BarState, tag_line

M15 = 900
T0 = 1_780_000_000 - (1_780_000_000 % M15)


def _block(strategy, n, step, dir_):
    """Egy strategia STATE blokkja — pont ugy, ahogy a live_trader tageli."""
    return [tag_line(BarState(t=T0 + i * step, notrade=0, dir=dir_,
                              window=1, market_state=-1, gate=0).line(), strategy)
            for i in range(n)]


# A fajl igy all ossze: minden strategia a SAJAT blokkjat adja hozza.
lines = _block("wpr_sma", 40, M15, 1) + _block("bollinger_squeeze_breakout", 10,
                                               4 * M15, -1)


def parse(lines):
    out = []
    for ln in lines:
        f = ln.split(";")
        if f[0] != "STATE":
            continue
        out.append({"strat": f[1], "t": int(f[2]), "nt": int(f[3]),
                    "dir": int(f[4]), "win": int(f[5])})
    return out


rows = parse(lines)
check("a fajl ket strategia STATE sorait tartalmazza",
      len({r["strat"] for r in rows}) == 2, str({r["strat"] for r in rows}))

# ── 1. A FAJL NEM GLOBALISAN IDOREND ─────────────────────────────────────
# ⚠ Ez NEM hiba a fajlban — igy keszul, es minden strategia a sajat blokkjaban
# rendezett. A hiba az volt, hogy az OLVASO tobbet feltetelezett ennel.
_ts = [r["t"] for r in rows]
check("a nyers STATE folyam VISSZAUGRIK az idoben",
      any(b < a for a, b in zip(_ts, _ts[1:])),
      f"{sum(1 for a, b in zip(_ts, _ts[1:]) if b < a)} visszaugras")
for s in ("wpr_sma", "bollinger_squeeze_breakout"):
    t = [r["t"] for r in rows if r["strat"] == s]
    check(f"...de a(z) {s} blokkja onmagaban rendezett",
          all(a <= b for a, b in zip(t, t[1:])))


# ── 2. AZ INDIKATOR ALGORITMUSA (a MQL-lel SZO SZERINT egyezo tukor) ─────
def find_state(ts, at):
    """A `FindState` binaris keresése — pontosan ahogy a .mq4/.mq5 csinalja."""
    if not ts or at < ts[0]:
        return -1
    lo, hi, res = 0, len(ts) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ts[mid] <= at:
            res, lo = mid, mid + 1
        else:
            hi = mid - 1
    return res


def read_states(rows, want=""):
    """Az UJ `ReadStates`: EGY strategiara szur (ures -> az elso), majd RENDEZ."""
    strat = want
    out = []
    for r in rows:
        if not strat:
            strat = r["strat"]
        if r["strat"] != strat:
            continue
        out.append(r)
    out.sort(key=lambda r: r["t"])
    return strat, out


HOLD = 2 * M15          # a `at - g_t[k] > holdSec * 2` atvitel-korlat

def draw(rows, want=""):
    """Mit rajzol a sav minden M1 gyertyara: (dir, window) vagy None."""
    strat, st = read_states(rows, want)
    ts = [r["t"] for r in st]
    out = []
    for at in range(T0, T0 + 40 * M15, 60):
        k = find_state(ts, at)
        out.append(None if (k < 0 or at - ts[k] > HOLD)
                   else (st[k]["dir"], st[k]["win"]))
    return strat, out


strat, drawn = draw(rows)
check("ures input -> a fajl ELSO strategiaja", strat == "wpr_sma", strat)
check("a sav MINDEN gyertyara rajzol (nincs 'szaggatas')",
      all(d is not None for d in drawn),
      f"{sum(1 for d in drawn if d is None)}/{len(drawn)} ures")
check("...es vegig a HELYES iranyt", all(d == (1, 1) for d in drawn),
      str(sorted({d for d in drawn})))

# A masik strategia KERHETO — es akkor az O allapotat adja, nem a keverekét.
strat2, drawn2 = draw(rows, "bollinger_squeeze_breakout")
check("nevesitve a MASIK strategia jon", strat2 == "bollinger_squeeze_breakout")
check("...a sajat iranyaval", {d for d in drawn2 if d} == {(-1, 1)},
      str({d for d in drawn2 if d}))


# ── 3. A REGI VISELKEDES: bizonyitsuk, hogy TENYLEG rossz volt ───────────
# ⚠ Enelkul a javitas csak allitas volna. A regi kod NEM szurt es NEM rendezett.
def draw_old(rows):
    ts = [r["t"] for r in rows]          # nyers fajl-sorrend, MIND a strategia
    out = []
    for at in range(T0, T0 + 40 * M15, 60):
        k = find_state(ts, at)
        out.append(None if (k < 0 or at - ts[k] > HOLD)
                   else (rows[k]["dir"], rows[k]["win"]))
    return out


old = draw_old(rows)
_hibas = sum(1 for a, b in zip(old, drawn) if a != b)
check("a REGI valtozat masik kepet rajzolt", _hibas > 0,
      f"{_hibas}/{len(old)} gyertyan tert el")
check("...es a regi kepben VOLTAK lyukak", any(d is None for d in old),
      f"{sum(1 for d in old if d is None)} ures gyertya")


# ── 4. A FORRAS: a ket vedelem BENNE van mindket indikatorban ────────────
# ⚠ Forras-szintu ellenorzes, mert MQL-t itt nem tudunk futtatni. A cel nem a
# szoveg orzese, hanem hogy egy kesobbi atirasnal ne tunjon el NEMAN a szures
# vagy a rendezes — a hiba pontosan igy keletkezett.
for _f, _lbl in ((ROOT / "mt4" / "TradeForgeBands.mq4", "MQL4"),
                 (ROOT / "mt5" / "TradeForgeBands.mq5", "MQL5")):
    src = _f.read_text(encoding="utf-8", errors="replace")
    check(f"{_lbl}: EGY strategiara szur (g_strat)",
          "g_strat" in src and 'g_strat = (InpStrategy != "" ? InpStrategy' in src)
    check(f"{_lbl}: RENDEZ a binaris keresés elott",
          "Beszúró rendezés" in src or "Beszuro rendezes" in src)
    check(f"{_lbl}: KIIRJA, melyik strategiat mutatja",
          "g_avail" in src and "SHORTNAME" in src.upper())
    check(f"{_lbl}: az input alapertelmezese mar NEM 'MIND'",
          "üres = MIND" not in src and "ures = MIND" not in src)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
