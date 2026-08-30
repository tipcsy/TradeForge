"""
Optimalizált instrumentum minősítése a test_summary (out-of-sample) alapján.

Szabály-alapú, "legrosszabb-elv" besorolás — átlátható, mert megmondja, MI
húzza le a párt (indok). A küszöbök a config.json "quality" blokkjából
felülírhatók. A modul stratégia- és tkinter-független (szemantikus szín-neveket
ad vissza: "green"/"yellow"/"orange"/"red"/"muted").

Fő mérőszám a profit_factor (PF), mert a win_rate önmagában félrevezető:
2:1 hozam/kockázatnál a nullszaldó ~33% win_rate.

⚠ A `min_trades` NEM ízlés kérdése — MÉRVE (2026-08-23). A Ger40 998 valódi
kötéséből (igazi PF = 1,10) bootstrappel, N kötéses mintákon:

    N kötés    PF 5%   PF 50%   PF 95%    P(PF>2)   P(PF>3)
        5       0,10     1,03     5,08      24,5%     14,2%
       15       0,38     1,09     2,89      14,8%      4,5%
       30       0,54     1,09     2,12       6,3%      0,7%
       50       0,64     1,10     1,82       2,9%      0,1%
      120       0,79     1,11     1,54       0,1%      0,0%

Vagyis egy 1,10-es PF-ű stratégia 5 kötésen a minták 14%-ában 3 FÖLÖTTI PF-et
mutat. A korábbi 15-ös küszöb tehát semmitől nem védett: az EURGBP „PF 5,11"
értéke HAT kötésen pontosan ilyen zaj volt — mégis ez alapján választotta ki az
optimalizáló a paramétereit, és a pár azóta gyakorlatilag nem köt.

50-nél a 95%-os sáv 1,82-ig ér: egy „Jó" (PF ≥ 1,4) még mindig lehet véletlen,
de már csak ~3% eséllyel. Ez a kompromisszum — nem az igazság, hanem egy MÉRT
küszöb, ami a configból feljebb vihető.
"""

from typing import Optional

from core.i18n import t as _t

# ── A minősítés KÓDJAI ─────────────────────────────────────────────────────
# ⚠ A KÓD AZ AZONOSÍTÓ, A SZÖVEG CSAK A KIJELZÉS. Korábban a magyar szó volt
# mindkettő: a `grade()` „Közepes"-t adott vissza, és ugyanez a szó volt a
# rangsor kulcsa (`_RANK`), a sor-rendezésé (`row_source`) és a cellaszínezésé
# (`live_row`). Angolra fordítva egyik sem talált volna — a tábla NÉMÁN rossz
# sorrendben és szürkén állt volna, mert a `.get(...)` nem hiba, hanem `None`.
GOOD, MID, WEAK, BAD = "good", "mid", "weak", "bad"
NONE = ""                       # nincs adat
GRADES = (GOOD, MID, WEAK, BAD)

# Rang: kisebb = erősebb. A „—" (nincs adat) mindig a végére.
_RANK = {GOOD: 0, MID: 1, WEAK: 2, BAD: 3}

# Szemantikus szín kódonként (a modul tkinter-független marad).
_COLOR = {GOOD: "green", MID: "yellow", WEAK: "orange", BAD: "red"}


def label(code: str) -> str:
    """Kód → a felhasználónak mutatott felirat az aktív nyelven."""
    return _t(f"quality.{code}") if code in _RANK else "—"


# Alapértelmezett küszöbök (a config "quality" blokkja felülírja)
_DEFAULTS = {
    "min_trades":   50,     # ⚠ MÉRVE (lásd a modul fejlécét) — 15-nél a PF zaj
    "maxdd_mid":    0.18,
    "maxdd_weak":   0.25,
    "maxdd_bad":    0.35,
    "pf_mid":       1.4,
    "pf_weak":      1.2,
    "pf_bad":       1.0,
    "winrate_weak": 0.35,
    "winrate_good": 0.45,
}


def _q(cfg: dict) -> dict:
    d = dict(_DEFAULTS)
    d.update((cfg or {}).get("quality", {}) or {})
    return d


def grade(test_summary: dict, cfg: dict) -> tuple[str, str, str]:
    """(minősítő_SZÖVEG, szín-név, indok) — a KIJELZÉSHEZ.

    Ha nincs adat → ("—", "muted", "").

    ⚠ Ez a szöveg le van fordítva: rendezni, összehasonlítani, kulcsként
    használni SOSEM szabad vele. Arra a `grade_code()` van."""
    code, color, why = grade_code(test_summary, cfg)
    return (label(code) if code else "—", color, why)


def grade_code(test_summary: dict, cfg: dict) -> tuple[str, str, str]:
    """(minősítés-KÓD, szín-név, indok) a test_summary alapján.

    A kód nyelvfüggetlen (`GOOD`/`MID`/`WEAK`/`BAD`, nincs adat → `""`), tehát
    ez való rendezéshez, összehasonlításhoz és mentéshez.
    """
    if not test_summary:
        return (NONE, "muted", "")
    q = _q(cfg)
    trades = test_summary.get("trades", 0)
    pnl    = test_summary.get("total_pnl", 0.0)
    pf     = test_summary.get("profit_factor", 0.0)
    wr     = test_summary.get("win_rate", 0.0)
    mdd    = test_summary.get("max_drawdown", 1.0)

    def _r(code, why=""):
        return (code, _COLOR[code], why)

    # 🔴 Rossz — bármelyik súlyos kizáró feltétel
    if pnl <= 0:
        return _r(BAD, _t("quality.why.losing"))
    if trades < q["min_trades"]:
        return _r(BAD, _t("quality.why.few_trades", trades=trades))
    if pf < q["pf_bad"]:
        return _r(BAD, _t("quality.why.pf", pf=f"{pf:.2f}"))
    if mdd >= q["maxdd_bad"]:
        return _r(BAD, _t("quality.why.maxdd", mdd=f"{mdd*100:.0f}"))

    # 🟠 Gyenge
    if mdd >= q["maxdd_weak"]:
        return _r(WEAK, _t("quality.why.maxdd", mdd=f"{mdd*100:.0f}"))
    if pf < q["pf_weak"]:
        return _r(WEAK, _t("quality.why.pf", pf=f"{pf:.2f}"))

    # 🟡 Közepes  (a win_rate csak enyhe jelzés: a PF már fedi a nyereségességet,
    #  alacsony WR + erős PF = ritka nagy nyerő, attól még jó lehet)
    if mdd >= q["maxdd_mid"]:
        return _r(MID, _t("quality.why.maxdd", mdd=f"{mdd*100:.0f}"))
    if pf < q["pf_mid"]:
        return _r(MID, _t("quality.why.pf", pf=f"{pf:.2f}"))
    if wr < q["winrate_weak"]:
        return _r(MID, _t("quality.why.win", wr=f"{wr*100:.0f}"))

    # 🟢 Jó
    return _r(GOOD)


def grade_rank(grade: str) -> int:
    """Minősítés → rang (kisebb = erősebb). Ismeretlen/nincs → 4.
    A 'Csak erősebb' korreláció-mód a feldolgozási sorrendhez használja.

    ⚠ KÓDOT vár (`GOOD`/`MID`/…), de a LEFORDÍTOTT feliratot is elfogadja — a
    hívók egy része a kijelzett szöveget adja tovább, és egy néma 4-es rang ott
    a rendezést borítaná fel, észrevétlenül."""
    if grade in _RANK:
        return _RANK[grade]
    for code in GRADES:
        if grade and grade == label(code):
            return _RANK[code]
    return 4


def metric_colors(test_summary: dict, cfg: dict) -> dict:
    """Per-metrika szemantikus szín (a részletes popuphoz)."""
    if not test_summary:
        return {}
    q = _q(cfg)
    pnl = test_summary.get("total_pnl", 0.0)
    pf  = test_summary.get("profit_factor", 0.0)
    wr  = test_summary.get("win_rate", 0.0)
    mdd = test_summary.get("max_drawdown", 1.0)

    def dd_c(v):
        return ("green" if v < q["maxdd_mid"] else "yellow" if v < q["maxdd_weak"]
                else "orange" if v < q["maxdd_bad"] else "red")

    def pf_c(v):
        return ("green" if v >= q["pf_mid"] else "yellow" if v >= q["pf_weak"]
                else "orange" if v >= q["pf_bad"] else "red")

    def wr_c(v):
        return ("green" if v >= q["winrate_good"] else "yellow" if v >= q["winrate_weak"]
                else "red")

    return {
        "total_pnl":     "green" if pnl > 0 else "red",
        "profit_factor": pf_c(pf),
        "win_rate":      wr_c(wr),
        "max_drawdown":  dd_c(mdd),
    }
