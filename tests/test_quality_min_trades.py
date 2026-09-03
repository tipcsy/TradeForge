"""Hány kötés kell ahhoz, hogy a minősítés jelentsen valamit?

⚠ A LELET (2026-08-23). Öt pár „élt", de a mentett paraméterkészletével
gyakorlatilag nem kereskedett — az EURCHF, EURGBP és EURJPY a 2026-04-01…07-31
ablakon NULLA kötést adott, a UK100 tizenötöt. Közben az EURJPY (23 kötés), a
UK100 (39) és a BTCUSD (38) a felületen **„Jó"** minősítéssel állt.

Az ok nem hiba volt, hanem egy túl alacsony küszöb: a minősítés `min_trades`-e
15, az optimalizáló `score()`-jáé 10. Ekkora mintán a profit factor nem mérőszám,
hanem zaj — és a keresés pont a zajt választotta ki.

⚠ A KÜSZÖB MÉRVE, nem ízlésből. A Ger40 **998 valódi kötéséből** (igazi
PF = 1,10) bootstrappelve:

    N kötés    PF 5%   PF 50%   PF 95%    P(PF>2)   P(PF>3)
        5       0,10     1,03     5,08      24,5%     14,2%
       10       0,28     1,07     3,64      20,2%      8,0%
       15       0,38     1,09     2,89      14,8%      4,5%
       30       0,54     1,09     2,12       6,3%      0,7%
       50       0,64     1,10     1,82       2,9%      0,1%
      120       0,79     1,11     1,54       0,1%      0,0%

Vagyis egy 1,10-es PF-ű stratégia ÖT kötésen a minták 14%-ában 3 fölötti PF-et
mutat. Az EURGBP „PF 5,11 hat kötésen" értéke pontosan ez. 50-nél a 95%-os sáv
1,82-ig ér: egy „Jó" (PF ≥ 1,4) még mindig lehet véletlen, de már csak ~3%
eséllyel. Ez nem az igazság, hanem egy MÉRT kompromisszum.
"""
import json
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


# ── 1. A PRINCÍPIUM: a PF zaja a mintamérettel csökken ──────────────────
# ⚠ Determinisztikus reprodukció (rögzített mag): a lényeg nem a pontos szám,
# hanem hogy a KIS minta rendszeresen mutat „kiváló" PF-et egy közepes
# stratégián. Ha ez az állítás egyszer nem állna, a küszöbnek sincs alapja.
import numpy as np

rng = np.random.default_rng(20260823)
# 40% nyerő +1,65 / 60% vesztő −1,00  →  PF ≈ (0,4·1,65)/(0,6·1,00) ≈ 1,10
SAMPLE = np.where(rng.random(4000) < 0.4, 1.65, -1.0)


def _pf(x):
    w = x[x > 0].sum()
    l = -x[x <= 0].sum()
    return (w / l) if l > 0 else np.inf


def _p_above(n, thr, iters=3000):
    r = np.random.default_rng(7)
    v = np.array([_pf(r.choice(SAMPLE, n, replace=True)) for _ in range(iters)])
    v = v[np.isfinite(v)]
    return float((v > thr).mean())


_true = _pf(SAMPLE)
check("a minta valódi PF-je ~1,10 (közepes stratégia)", 1.0 < _true < 1.25,
      f"{_true:.2f}")
_p5, _p15, _p50 = _p_above(5, 2.0), _p_above(15, 2.0), _p_above(50, 2.0)
print(f"      (P(PF>2): 5 kötésen {_p5*100:.1f}% · 15-ön {_p15*100:.1f}% · "
      f"50-en {_p50*100:.1f}%)")
check("5 kötésen a 'kiváló' PF GYAKORI (>10%)", _p5 > 0.10, f"{_p5*100:.1f}%")
check("a régi 15-ös küszöbön MÉG MINDIG gyakori (>5%)", _p15 > 0.05,
      f"{_p15*100:.1f}%")
check("50 kötésen viszont már ritka (<5%)", _p50 < 0.05, f"{_p50*100:.1f}%")
check("...és a zaj MONOTON csökken a mintamérettel", _p5 > _p15 > _p50)


# ── 2. A KÜSZÖB: 50, MINDENHOL ─────────────────────────────────────────
from core import quality as q

check("a modul alapértelmezése 50", q._DEFAULTS["min_trades"] == 50,
      str(q._DEFAULTS["min_trades"]))
check("...és a mérés ott van indoklásként",
      "998 valódi" in (q.__doc__ or "") and "P(PF>3)" in (q.__doc__ or ""))

# ⚠ A CSAPDA, amibe belefutottam: a STRATÉGIA-CONFIG mind a 9 küszöböt
# RÖGZÍTI, tehát a modul alapértelmezése wpr_sma/ml_ai alatt HALOTT KÓD. Az
# első javításom (csak a modulban) semmit nem változtatott a minősítéseken.
_pinned = {}
for _f in sorted((ROOT / "strategies" / "config").glob("*.json")):
    _q = (json.loads(_f.read_text(encoding="utf-8")).get("quality") or {})
    if "min_trades" in _q:
        _pinned[_f.stem] = _q["min_trades"]
check("a rögzítő stratégia-configok is 50-et mondanak",
      all(v == 50 for v in _pinned.values()), str(_pinned))
check("...és van, amelyik tényleg rögzíti (a mérés értelmes)", bool(_pinned),
      str(_pinned))


# ── 3. A HATÁS: a kis mintás pár NEM lehet „Jó" ────────────────────────
from strategy.settings import load_config
_cfg = load_config("config.json")

# 39 kötés, PF 1,72 — pontosan a UK100 esete, ami eddig „Jó" volt.
_small = {"trades": 39, "total_pnl": 29.6, "profit_factor": 1.72,
          "win_rate": 0.5, "max_drawdown": 0.10}
_g, _c, _why = q.grade(_small, _cfg)
check("39 kötés + PF 1,72 → NEM 'Jó'", _g != "Jó", f"{_g} ({_why})")
check("...és megmondja, miért", "kevés trade" in _why, _why)
check("...a szín is figyelmeztet", _c == "red", _c)

# Ugyanaz a PF NAGY mintán viszont megáll.
_big = dict(_small)
_big["trades"] = 300
_g2, _c2, _why2 = q.grade(_big, _cfg)
check("300 kötésen ugyanez a PF már 'Jó'", _g2 == "Jó", f"{_g2} ({_why2})")

# ⚠ A veszteséges pár INDOKA maradjon a veszteség — a kevés kötés ne fedje el.
_loss = {"trades": 4, "total_pnl": -2.4, "profit_factor": 0.48,
         "win_rate": 0.25, "max_drawdown": 0.05}
check("a veszteséges párnál a VESZTESÉG az indok",
      q.grade(_loss, _cfg)[2] == "veszteséges", q.grade(_loss, _cfg)[2])

# A küszöb a configból FELJEBB vihető (nem bedrótozott döntés).
_strict = dict(_cfg, quality={**(_cfg.get("quality") or {}), "min_trades": 500})
check("a config felülírhatja (szigorítás)",
      "kevés trade" in q.grade(_big, _strict)[2], q.grade(_big, _strict)[2])


# ── 4. AZ OPTIMALIZÁLÓ KÜSZÖBE — ugyanabból a mérésből ─────────────────
# ⚠ A minősítés csak KIJELZÉS; a kiválasztást az optimalizáló alsó korlátja
# dönti el. Ha csak a minősítést emeljük, a keresés TOVÁBBRA IS a zajt választja
# — csak most már piros címkével látod.
from ml import optimizer as _opt

check("ablakonkénti korlát 15", _opt.MIN_TRADES_WINDOW == 15,
      str(_opt.MIN_TRADES_WINDOW))
check("összesített korlát 50 (a minősítéssel EGY szinten)",
      _opt.MIN_TRADES_TOTAL == q._DEFAULTS["min_trades"],
      f"{_opt.MIN_TRADES_TOTAL} vs {q._DEFAULTS['min_trades']}")
# ⚠ Az `n_splits` alap 4 → ablakonként 15 ≈ 60 összesített kötés, tehát a
# kiválasztott készlet EL TUD jutni értékelhető minősítésig. Ha az ablak-korlát
# túl alacsony volna, a keresés olyat adna vissza, amit a minősítés rögtön
# „kevés trade"-nek bélyegez — az önmagával vitatkozó felület.
check("...és a kettő konzisztens (4 ablak × 15 ≥ 50)",
      _opt.MIN_TRADES_WINDOW * 4 >= _opt.MIN_TRADES_TOTAL)

check("a korlátok CONFIGBÓL jönnek", _opt.min_trades_floors(None) == (15, 50))
check("...felülírhatók",
      _opt.min_trades_floors({"optimizer": {"min_trades_per_window": 40,
                                            "min_trades": 200}}) == (40, 200))
# Egy elgépelt érték ne vigyen el egy órák óta futó optimalizálást.
check("...és a hibás érték az alapra esik vissza",
      _opt.min_trades_floors({"optimizer": {"min_trades": "abc"}}) == (15, 50))

# A KÜSZÖB TÉNYLEG HAT: kevés kötésű trial pontszáma a „soha ne válaszd" érték.
_few = {"trades": 6, "total_pnl": 50.0, "profit_factor": 5.11,
        "win_rate": 0.83, "max_drawdown": 0.05}
check("6 kötés + PF 5,11 → ELUTASÍTVA (ez volt az EURGBP esete)",
      _opt.score(_few) <= -999999.0, str(_opt.score(_few)))
_many = dict(_few, trades=300)
check("...ugyanez 300 kötésen viszont értékelhető", _opt.score(_many) > 0,
      str(_opt.score(_many)))

# ⚠ A hívási helyek is a configból vesznek — különben a kulcs süket maradna.
_src = (ROOT / "ml" / "optimizer.py").read_text(encoding="utf-8")
check("az ablak-pontozás a configból veszi",
      "min_trades=min_trades_floors(cfg)[0]" in _src)
check("az összesített pontozás is", "min_trades=min_trades_floors(cfg)[1]" in _src)
_ex = (ROOT / "config.example.json").read_text(encoding="utf-8")
check("a példa-config dokumentálja", '"min_trades_per_window"' in _ex
      and "nincs mit hangolni" in _ex)


print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
