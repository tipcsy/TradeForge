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
    """(minősítő_szöveg, szín-név, indok) a test_summary alapján.

    Ha nincs adat → ("—", "muted", "").
    """
    if not test_summary:
        return ("—", "muted", "")
    q = _q(cfg)
    trades = test_summary.get("trades", 0)
    pnl    = test_summary.get("total_pnl", 0.0)
    pf     = test_summary.get("profit_factor", 0.0)
    wr     = test_summary.get("win_rate", 0.0)
    mdd    = test_summary.get("max_drawdown", 1.0)

    # 🔴 Rossz — bármelyik súlyos kizáró feltétel
    if pnl <= 0:
        return ("Rossz", "red", "veszteséges")
    if trades < q["min_trades"]:
        return ("Rossz", "red", f"kevés trade ({trades})")
    if pf < q["pf_bad"]:
        return ("Rossz", "red", f"PF {pf:.2f}")
    if mdd >= q["maxdd_bad"]:
        return ("Rossz", "red", f"MaxDD {mdd*100:.0f}%")

    # 🟠 Gyenge
    if mdd >= q["maxdd_weak"]:
        return ("Gyenge", "orange", f"MaxDD {mdd*100:.0f}%")
    if pf < q["pf_weak"]:
        return ("Gyenge", "orange", f"PF {pf:.2f}")

    # 🟡 Közepes  (a win_rate csak enyhe jelzés: a PF már fedi a nyereségességet,
    #  alacsony WR + erős PF = ritka nagy nyerő, attól még jó lehet)
    if mdd >= q["maxdd_mid"]:
        return ("Közepes", "yellow", f"MaxDD {mdd*100:.0f}%")
    if pf < q["pf_mid"]:
        return ("Közepes", "yellow", f"PF {pf:.2f}")
    if wr < q["winrate_weak"]:
        return ("Közepes", "yellow", f"Win {wr*100:.0f}%")

    # 🟢 Jó
    return ("Jó", "green", "")


_RANK = {"Jó": 0, "Közepes": 1, "Gyenge": 2, "Rossz": 3}


def grade_rank(grade_text: str) -> int:
    """Minősítő szöveg → rang (kisebb = erősebb). Ismeretlen/nincs → 4.
    A 'Csak erősebb' korreláció-mód a feldolgozási sorrendhez használja."""
    return _RANK.get(grade_text, 4)


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
