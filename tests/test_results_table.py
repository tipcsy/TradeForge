"""Az eredmenytabla: szuro, rendezes, tipusok.

A doksi kerese: "legyen szurheto es rendezheto, illetve a megfelelo mezok
legyenek megfelelo tipusuak (pl. DD = %)".

⚠ MIERT VAN EZ TESZTELVE, es miert TISZTA fuggvenyekkel: a felhasznalo ebbol a
tablabol VALASZT egy parameter-keszletet, es azzal indit el eles kereskedest. Egy
elrontott osszehasonlitas nem "csunya kijelzes", hanem ROSSZ SOR kivalasztasa.

⚠ A legalattomosabb csapda a MAGYAR SZAMFORMATUM. A CSV `;` elvalasztoju es `,`
tizedesjelu (magyar Excel). Ha a `0,1864`-et a szokasos float()-tal olvasnank,
kivetelt dobna; ha a vesszot ezresnek nezne valami, 1864 lenne belole — a 18,6%-os
visszaeses 186 400%-kent jelenne meg, es a "DD < 20%" szuro MINDEN sort
atengedne. Pont a legrosszabb sorokat.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog
applog.harden_console()

from dashboard import results_table as rt

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ── 1. A MAGYAR SZAMFORMATUM ───────────────────────────────────────────────
check("tizedes VESSZO -> szam", rt.to_num("0,1864") == 0.1864)
check("tizedes pont is atmegy", rt.to_num("0.5") == 0.5)
check("ures cella -> None", rt.to_num("") is None)
check("nem szam -> None (nem robban)", rt.to_num("kenyszer nem teljesult") is None)
check("'inf' (a profit_factor irhat ilyet) -> vegtelen",
      rt.to_num("inf") == float("inf"))
check("None -> None", rt.to_num(None) is None)


# ── 2. Tipusok es megjelenites ─────────────────────────────────────────────
check("win_rate szazalek", rt.kind_of("win_rate") == rt.KIND_PCT)
check("max_drawdown szazalek", rt.kind_of("max_drawdown") == rt.KIND_PCT)
check("trades egesz", rt.kind_of("trades") == rt.KIND_INT)
check("note szoveg", rt.kind_of("note") == rt.KIND_TEXT)
check("ismeretlen (parameter-)oszlop -> szam",
      rt.kind_of("wpr_m1_trigger") == rt.KIND_FLOAT)

check("DD megjelenitese SZAZALEK", rt.fmt("max_drawdown", "0,1864") == "18,6%",
      rt.fmt("max_drawdown", "0,1864"))
check("trades egeszkent", rt.fmt("trades", "541") == "541")
check("penz magyar alakban, NEM TORHETO ezres-szokozzel",
      rt.fmt("total_pnl", "1234,5") == "1" + rt.NBSP + "234,50",
      repr(rt.fmt("total_pnl", "1234,5")))
check("vegtelen PF jele", rt.fmt("profit_factor", "inf") == "∞")
check("ures cella -> ures szoveg (nem '0' es nem 'None')",
      rt.fmt("total_pnl", "") == "")
check("szoveg-oszlop valtozatlan", rt.fmt("note", "kevés kötés") == "kevés kötés")


# ── 3. A SZURES ────────────────────────────────────────────────────────────
ROWS = [
    {"rank": "1", "trades": "541", "win_rate": "0,3494", "max_drawdown": "0,1864",
     "total_pnl": "834,74", "profit_factor": "1,747", "note": ""},
    {"rank": "2", "trades": "120", "win_rate": "0,5000", "max_drawdown": "0,0500",
     "total_pnl": "-40,00", "profit_factor": "0,8", "note": ""},
    {"rank": "3", "trades": "300", "win_rate": "0,2000", "max_drawdown": "0,4000",
     "total_pnl": "0", "profit_factor": "1,0", "note": ""},
    {"rank": "4", "trades": "", "win_rate": "", "max_drawdown": "",
     "total_pnl": "", "profit_factor": "", "note": "kényszer nem teljesült"},
]

check("trades >= 300 -> 2 sor",
      len(rt.apply_filters(ROWS, [("trades", "≥", 300)])) == 2)
check("trades > 300 -> 1 sor",
      len(rt.apply_filters(ROWS, [("trades", ">", 300)])) == 1)

# ⚠ A SZAZALEKOS mezoknel a felhasznalo SZAZALEKOT ir (35), az adat ARANY (0,35).
# Ha ezt elvetenenk, a "win_rate >= 35" MINDEN sort kidobna (egyik sem >= 35,0).
_wr = rt.apply_filters(ROWS, [("win_rate", "≥", 35)])
check("win_rate >= 35 SZAZALEKKENT ertelmezve (nem aranykent)",
      len(_wr) == 1 and _wr[0]["rank"] == "2", f"{len(_wr)} sor")
_dd = rt.apply_filters(ROWS, [("max_drawdown", "<", 20)])
check("DD < 20 (%) -> a 18,6%-os es az 5%-os megy at",
      {r["rank"] for r in _dd} == {"1", "2"}, str(sorted(r["rank"] for r in _dd)))

check("tobb feltetel EGYUTT (ES kapcsolat)",
      [r["rank"] for r in rt.apply_filters(
          ROWS, [("profit_factor", ">", 1.5), ("max_drawdown", "<", 20)])] == ["1"])

# Az ures cellaju sor nem vetheto ossze -> kiesik (nem szall be "0"-kent).
check("az ERTEKELHETETLEN sor kiesik a szuresbol (nem 0-kent megy at)",
      all(r["rank"] != "4" for r in rt.apply_filters(ROWS, [("trades", "≥", 0)])))

check("ures szurolista -> minden sor", len(rt.apply_filters(ROWS, [])) == 4)

# Az "=" a MEGJELENITETT pontossaghoz igazodik: a felhasznalo 34,9%-ot lat.
check("'=' a lathato pontossaggal talal (0,3494 ~ 34,9%)",
      len(rt.apply_filters(ROWS, [("win_rate", "=", 34.9)])) == 1)


# ── 4. A RENDEZES ──────────────────────────────────────────────────────────
_s = rt.sort_rows(ROWS, "total_pnl", True)
check("csokkeno P&L: a legjobb elol", _s[0]["rank"] == "1")
# ⚠ A hianyzo ertek MINDIG a vegere kerul — barmelyik iranyba rendezunk.
# Kulonben csokkenoben az ures cellak ulnenek a lista tetejen, es a
# felhasznalo azt hinne, azok a legjobbak.
check("csokkenoben az ERTEKELHETETLEN sor a vegen", _s[-1]["rank"] == "4")
_a = rt.sort_rows(ROWS, "total_pnl", False)
check("novekvoben IS a vegen (nem a tetejen)", _a[-1]["rank"] == "4")
check("novekvoben a legrosszabb elol", _a[0]["rank"] == "2")
check("szamkent rendez, nem szovegkent (120 < 300 < 541)",
      [r["rank"] for r in rt.sort_rows(ROWS, "trades", False)][:3] == ["2", "3", "1"])
check("szoveg-oszlop rendezese nem robban",
      len(rt.sort_rows(ROWS, "note", True)) == 4)


# ── 5. A SOR SZINE az eredmeny szerint ─────────────────────────────────────
check("pozitiv eredmeny -> zold", rt.row_tone(ROWS[0]) == "pos")
check("negativ eredmeny -> piros", rt.row_tone(ROWS[1]) == "neg")
check("nulla -> semleges", rt.row_tone(ROWS[2]) == "zero")
check("ertekelhetetlen -> semleges (nem piros)", rt.row_tone(ROWS[3]) == "zero")


# ── 6. Beolvasas: hianyzo fajl ne robbanjon ───────────────────────────────
_c, _r = rt.load_csv(ROOT / "nincs_ilyen_fajl_12345.csv")
check("hianyzo CSV -> ures, nem kivetel", _c == [] and _r == [])


# ── 7. Vegponttol vegpontig egy VALODI trials CSV-n (ha van) ──────────────
_all_csv = list((ROOT / "data" / "optimized_params").rglob("*_trials.csv"))
# A LEGNAGYOBB fajlt nezzuk: egy 1 soros CSV-n a "szur-e" allitas ertelmetlen.
_real = max(_all_csv, key=lambda p: p.stat().st_size, default=None)
if _real:
    cols, rows = rt.load_csv(_real)
    check(f"valodi optuna-CSV beolvasva ({_real.name})",
          len(cols) > 5 and len(rows) > 10, f"{len(cols)} oszlop, {len(rows)} sor")
    check("a kulcs-oszlopok megvannak",
          all(c in cols for c in ("rank", "score", "trades", "win_rate",
                                  "max_drawdown", "profit_factor")),
          str([c for c in ("rank", "score", "trades", "win_rate", "max_drawdown",
                           "profit_factor") if c not in cols]))
    _f = rt.apply_filters(rows, [("profit_factor", ">", 1.0)])
    check("a szuro valodi adaton is szukit (es nem mindent dob ki)",
          0 < len(_f) < len(rows), f"{len(_f)}/{len(rows)}")
    check("minden sor kap szint",
          all(rt.row_tone(r) in ("pos", "neg", "zero") for r in rows))

    # ⚠ Nem minden trials CSV-ben van `score`: ha egy parhoz/strategiahoz csak
    # KEZI mentes tortent (`_append_manual_trial`, note=manual), a fajlban csak
    # a parameterek + metrikak vannak. A tabla ezt nem felteheti — kulonben
    # eppen az ujonnan bevezetett strategiaknal (ahol meg nem futott
    # optimalizalas) dobna hibat.
    _manual = [p for p in _all_csv if "score" not in (rt.load_csv(p)[0] or [])]
    if _manual:
        _c, _r = rt.load_csv(_manual[0])
        check(f"score OSZLOP NELKULI (kezi) CSV is betolt ({_manual[0].parent.name})",
              len(_c) > 3 and len(_r) > 0, f"{len(_c)} oszlop, {len(_r)} sor")
        check("...a metrikai attol meg olvashatok",
              rt.to_num(_r[0].get("trades")) is not None)
        check("...es a rendezes hianyzo oszlopra sem robban",
              len(rt.sort_rows(_r, "score", True)) == len(_r))
    else:
        check("nincs score nelkuli CSV a repoban (kihagyva)", True)
else:
    check("nincs valodi trials CSV a repoban (kihagyva)", True)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
