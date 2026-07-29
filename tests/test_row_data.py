"""A (par x strategia) sorok ADATA — a bekotes ket NEMA hibaja ellen.

Mindkettot a valodi dashboard felepitese fogta meg, nem a tesztek:

  1. A `split_open` eloszor a SZIMBOLUMRA AGGREGALT pozicio-gyorsitotarat kapta
     (`open_positions_by_symbol()`), amiben NINCS strategia -> mindig (0,0)-t
     adott, es a "Nyitott" oszlop nemán ures maradt, holott futottak poziciok.
     A per-strategia sorhoz PER-TICKET adat kell (`open_positions_detailed()`).
  2. A minoseg-olvaso `except Exception`-t fogott, es ezzel ELNYELTE a
     `NameError`-t (a `params_file` nem volt importalva a gui.py-ban) -> a
     Minoseg-oszlop nemán "—" lett, pedig a fajlok ott voltak.

Ezert itt szandekosan a FORMATUMOT es a hibatureset teszteljuk.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import applog
applog.harden_console()

from core import gates as G
from dashboard import row_data as rd

R = []


def check(name, ok, detail=""):
    R.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ 1. split_open: a VALODI (per-ticket, LISTA) formatum ═════════════════
DETAIL = [
    {"ticket": 1, "symbol": "GOLD", "profit": 3.20, "magic": 111},
    {"ticket": 2, "symbol": "UsaTec", "profit": -0.90, "magic": 111},
    {"ticket": 3, "symbol": "UsaTec", "profit": -0.50, "magic": 222},
    {"ticket": 4, "symbol": "GOLD", "profit": 1.10, "magic": 111},
]
OWNER = {111: "wpr_sma", 222: "ml_ai"}


def owner_of(ticket, magic=None):
    return OWNER.get(magic)


check("egy strategia ket pozicioja OSSZEADODIK",
      rd.split_open(DETAIL, "GOLD", "wpr_sma", owner_of) == (4.30, 2),
      str(rd.split_open(DETAIL, "GOLD", "wpr_sma", owner_of)))
check("a PER-STRATEGIA bontas helyes (ugyanazon a paron)",
      rd.split_open(DETAIL, "UsaTec", "wpr_sma", owner_of) == (-0.90, 1)
      and rd.split_open(DETAIL, "UsaTec", "ml_ai", owner_of) == (-0.50, 1))
check("mas strategia -> nincs talalat",
      rd.split_open(DETAIL, "GOLD", "ml_ai", owner_of) == (0.0, 0))
check("mas par -> nincs talalat",
      rd.split_open(DETAIL, "EURUSD", "wpr_sma", owner_of) == (0.0, 0))

# A `strategy` mezo (ha a hivo mar feloldotta) ELSOBBSEGET kap
PRE = [{"ticket": 9, "symbol": "GOLD", "profit": 2.0, "strategy": "ml_ai"}]
check("elore feloldott 'strategy' mezo hasznalatban",
      rd.split_open(PRE, "GOLD", "ml_ai", owner_of) == (2.0, 1))

# ══ 2. A REGI (szimbolumra aggregalt) formatum NEM ad hamis eredmenyt ════
# Ez volt a nema hiba: a dict-formatumbol nem lehet strategiat kiolvasni.
BY_SYM = {"GOLD": {"pnl": 3.20, "count": 1, "risk_free": False}}
check("szimbolumra aggregalt dict -> (0,0), nem hamis szam",
      rd.split_open(list(BY_SYM.values()), "GOLD", "wpr_sma", owner_of) == (0.0, 0))

# ══ 3. Robusztussag ══════════════════════════════════════════════════════
check("ures/None bemenet -> (0,0)",
      rd.split_open([], "GOLD", "s") == (0.0, 0)
      and rd.split_open(None, "GOLD", "s") == (0.0, 0))
check("szemet elem kihagyva (nem robban)",
      rd.split_open([None, "izé", 42, DETAIL[0]], "GOLD", "wpr_sma", owner_of)
      == (3.20, 1))
check("owner_of kivetelt dob -> a sor kimarad, nem all meg",
      rd.split_open(DETAIL, "GOLD", "wpr_sma",
                    lambda t, m=None: (_ for _ in ()).throw(RuntimeError()))
      == (0.0, 0))
check("hianyzo owner_of -> csak az elore feloldottak szamitanak",
      rd.split_open(DETAIL, "GOLD", "wpr_sma", None) == (0.0, 0))

# ══ 4. gate_ctx: a spread-korlat a STRATEGIA parametereibol ══════════════
class DS:
    spread_pts = 120
    atr_price = 16.0
    tf_align_signs = [1, 1, 1]
    tf_align_labels = ["M1", "M5", "M15"]
    tf_align_dir = "BUY"
    market_strategy = "regime_adx"
    market_state_label = "trend"


PC = {"point_size": 0.01, "pv1_point": 1.0}
c1 = rd.gate_ctx(DS(), {"max_spread_atr_ratio": 0.20}, PC, "wpr_sma", ["wpr_sma"])
c2 = rd.gate_ctx(DS(), {"max_spread_atr_ratio": 0.02}, PC, "ml_ai", ["wpr_sma"])
check("a spread-korlat KULONBOZIK ket strategia kozt (ez volt a panasz)",
      c1["max_spread_points"] != c2["max_spread_points"],
      f"{c1['max_spread_points']:.0f} vs {c2['max_spread_points']:.0f}")
check("a TF-kapu PER STRATEGIA dol el a gate-listabol",
      c1["tf_align_gated"] is True and c2["tf_align_gated"] is False)
check("a mert spread atkerul", c1["spread_points"] == 120)
check("hianyzo pair_cfg -> nem robban, korlat 0 (kikapcsolt kapu)",
      rd.gate_ctx(DS(), {}, {}, "s", [])["max_spread_points"] == 0.0)
check("None ds -> nem robban", isinstance(rd.gate_ctx(None, {}, PC, "s", []), dict))

# A kiertekelo tenylegesen mast mond a ket strategiara
check("a szorosabb korlat BLOKKOL, a bo nem",
      not G.is_blocked(G.evaluate(c1)) and G.is_blocked(G.evaluate(c2)),
      f"{G.strip(G.evaluate(c1))} / {G.strip(G.evaluate(c2))}")

# ══ 5. row_items: a sor-leiro kulcsai ════════════════════════════════════
items = rd.row_items(
    symbols=["GOLD"], cfg={"pairs": {"GOLD": PC}},
    dashboard_ref={"GOLD": DS()},
    strategies_of=lambda s: ["wpr_sma", "ml_ai"],
    params_of=lambda s, n: {"max_spread_atr_ratio": 0.20},
    quality_of=lambda s, n: ("Jó", "green"),
    mode_of=lambda s, n: "KÖT" if n == "wpr_sma" else "Jelzés",
    live_of=lambda s, n: True,
    tf_gate_of=lambda s: ["wpr_sma"],
    open_of=lambda s, n: ((3.2, 1) if n == "wpr_sma" else (0.0, 0)),
    daily_of=lambda s, n: 1.5,
    opt_status_of=lambda s, n: "")
check("ket strategia -> ket sor-leiro", len(items) == 2)
check("a strategy_order NOVEKVO (a csoporton beluli allando sorrendhez)",
      [i["strategy_order"] for i in items] == [0, 1])
check("nyitott pozicio -> state='position'",
      items[0]["state"] == "position", items[0]["state"])
check("jelzes-mod, pozicio nelkul -> state='signal'",
      items[1]["state"] == "signal", items[1]["state"])
check("minden varhato kulcs megvan",
      {"symbol", "strategy", "states", "quality", "open_pnl", "open_n",
       "daily", "opt_status", "trained", "live", "state"} <= set(items[0]))

print()
print(f"{sum(R)}/{len(R)} teszt PASS")
sys.exit(0 if all(R) else 1)
