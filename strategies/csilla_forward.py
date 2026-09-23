"""CSILLA-SÁV — FORWARD PAPÍRKERESKEDÉS (jelzés-napló + utólagos kiértékelés).

Indítva: 2026-09-15. A felhasználó döntése a `Csilla beszállója — mérés`
jegyzet 5–7. szakasza után: a Csilla-sáv az egyetlen cella, ami minden
kimenet-változatban pozitív előjelet adott (t ≈ 1,4–1,5), ezért forward.

⚠ KÉT MÉRŐHELY, KÉT SZÁM (2026-09-15, a felhasználó döntése után). A szabály
a `strategies/csilla` modulban is fut (a TradeForge keretben, ugyanazt a
`csilla_rules`-t hívva — a BELÉPŐK bitre azonosak, `tests/test_csilla_parity`).
De a KILÉPÉS a két helyen nem azonos: a labor R-ben (BE 0,67 R, 2 R csúszó,
max 5 nap), a motor ATR-ben (`breakeven_r` 0,67 + trailing 3,0 × a végrehajtási
ATR, idő-kilépés nélkül, több slot). Ugyanazon a kötésen mérve a motor +1,0 R-nél
kiütött, ahol a labor +2,16 R-ig vitt. Ezért:
  * EZ a szkript az ELŐRE RÖGZÍTETT (labor-)szabály forward tesztje — a
    protokoll kimondása ezen alapul;
  * a keretben futó stratégia (jelzés-mód vagy demó) a GYAKORLATI kérdést
    válaszolja: mit hoz a TradeForge saját kilépésével. A két szám eltérhet;
    egyik sem hamisítja a másikat, de nem is cserélhetők fel.

ELŐRE RÖGZÍTVE (a mérés után nem módosítható):

    ELSŐDLEGES minta  MIND a 8 pár, MINDEN óra — nincs sáv. Egyszerre EGY
                      pozíció páronként (a mérés is így számolt). A korábbi
                      teszt Csilla-sávja a D1/W1-es szabály mérésén alapult;
                      az új láncra nincs alapja, és az első nap mind a 17
                      jelzése azon kívül esett.
    szabály           `csilla_rules` LÁNC: a felső idősík (H1) a saját utolsó
                      igazolt swingjét töri → érvényes, amíg az ár nem zár a
                      törés előtti szélsőérték túloldalára → pipa (a korrekciót
                      elnyelő gyertya) → M15 counter-trend belépők.
    kilépés           stop = a korrekció teteje + spread; BE (stop a
                      belépőre) +0,67 R-nél; utána 2 R-es csúszó stop; NINCS célár;
                      max 5 nap, utána piaci zárás. Spread + swap.
    várt érték        ~0. A mintán mérve a lánc NEM különböztethető meg a
                      véletlen belépőtől (z −0,19 … +1,70, 8 instrumentum) — a
                      nyers +0,038 R a KILÉPÉSÉ. Ez a forward tehát nem egy
                      ígéretes él megerősítése, hanem annak ellenőrzése, hogy
                      élesben sem lesz rosszabb a semminél.
    MÁSODLAGOS minta  nincs (az elsődleges már mindent lefed).

    KIMONDÁS
      * LEÁLL, ha n ≥ 60 és az átlag R < −0,10 (a minta-szórással ez már
        ~2,4 σ-val a várt alatt).
      * ERŐSÍTÉS, ha az átlag R > 0 és t ≥ 2 — de ehhez ~280 kötés kell
        (σ ≈ 1 R, +0,12 várt), ami ~40 kötés/év mellett ÉVEK. A forward teszt
        tehát a NAGY bukást tudja kiszűrni, az élt bizonyítani nem.
      * Semmilyen paramétert nem hangolunk a forward számok láttán.

ADAT-CSAPDA (2026-09-15): az MT5-ből pótolt friss gyertyákban NINCS spread
(`avg_spread` NaN), a labor ilyenkor 0 spreaddel számolna. Az értékelő ezért a
pár utolsó 12 hónapjának tick-alapú spread-mediánját teszi a hiányzó helyekre.

Használat (naponta, a session után):
    python strategies/csilla_forward.py --update   # adat + új jelzések a naplóba
    python strategies/csilla_forward.py --evaluate # lezárult kötések kiértékelése
    python strategies/csilla_forward.py --report   # állás az előre rögzített küszöbökhöz
    python strategies/csilla_forward.py --all      # mindhárom egymás után
    python main.py job csilla_forward              # ugyanaz a keret napi feladataként
Napló: data/forward/csilla_signals.csv (git-ben követve, hogy ne vesszen el).

⚠ A NAPI FUTÁS A PROGRAMÉ (2026-09-22). Az első hét megmutatta, hogy a „naponta,
kézzel" nem fut: a napló 09-15-től egy sorral állt. A keret napi-feladat
mechanizmusa (`core/daily_jobs.py`) indítja alprocesszben naponta egyszer, a
beállított idő után; a Karmester fülről és a `jobs run csilla_forward` parancsból
kézzel is. A `--report` az állást a `csilla_status.json`-ba is kiírja — a
`status_lines()` EBBŐL olvas, nem számol újra.

⚠ MIÉRT A `strategies/` CSOMAGBAN, ÉS NEM A `tools/`-BAN. Ez a csilla stratégia
SAJÁT feladata: a stratégia deklarálja (`CsillaStrategy.daily_jobs()`), a modult
a stratégia importálja, tehát a `.tfs` csomag magával viszi, és a stratégia
törlésével együtt tűnik el. A keret (`core/`, `main.py`, a felület) ezt a
modult NEM ismeri — csak a registry-n át, dinamikusan jut el ide. Az első
változat a `tools/`-ban lakott és a `main.py` importálta: a stratégia törlése
után minden este elbukott volna (a felhasználó kérdése hozta felszínre).
A `tools/research/lab`-ot (a kutató-harness) használja — az a program része,
nem a stratégiáé, mindenhol ott van, ahol a program.

⚠ A SZABÁLYT A `csilla_rules`-BÓL HÍVJA, NEM A LABOR-SZKRIPTBŐL (2026-09-22).
Az első változat a `tools/research/csilla_levels.py`-t importálta — azt viszont
a `.tfs` csomag NEM viszi magával (csak a `strategies.<x>` segédmodulokat),
tehát másik gépre telepítve a napi feladat import-hibával állt volna meg,
némán, minden este. Ugyanaz a hordozhatósági szabály, ami miatt ez a modul a
`strategies/`-ben lakik. A hívás egy az egyben ugyanaz (`entry_table`,
D1+W1, fix 1,5 ATR15 stop) — a belépők bitre azonosak maradtak.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import lab                                       # noqa: E402

from strategies import csilla_rules as sw         # noqa: E402

# ⚠ UJ FORWARD 2026-09-23-TOL. Az elso (09-15 – 09-23) a D1/W1 szint-reteges
# szabalyt merte; a felhasznalo 09-23-an kimondta, hogy az NEM az o modszere
# (H4 a plafon, ez daytrade), es a strategia atallt a LANCRA. Egy futo
# forward-teszt szabalya NEM cserelheto ki — eppen az a lenyege, hogy le van
# fagyasztva —, ezert az elso LEZARULT azzal, amit hozott (8 kotes, semmi
# erdemi), es EZ egy UJ teszt: uj kezdodatum, uj naplo. A regi naplo
# (`csilla_signals.csv`) megmarad.
START = pd.Timestamp("2026-09-23 00:00", tz="UTC")     # a forward kezdete (szerver-idő)
JOURNAL = ROOT / "data" / "forward" / "csilla_chain_signals.csv"
STATUS_JSON = ROOT / "data" / "forward" / "csilla_status.json"   # a felületnek
# ⚠ AZ ÚJ TESZTBEN NINCS SÁV (2026-09-23, az első napon rögzítve). A korábbi
# Csilla-sáv (Ger40 8–11, UsaTec/GOLD 15–18) a D1/W1-es szabály méréséből jött:
# ott az volt az EGYETLEN cella, ami pozitív előjelet adott. Az új láncra ennek
# nincs alapja, és mivel a mérés sehol nem talált élt, egy szűkítés csak
# önkényes volna — ráadásul az első nap mind a 17 jelzése a sávon KÍVÜL esett
# (elsődleges minta n = 0). Az elsődleges minta tehát MINDEN pár, MINDEN óra.
PRIMARY: dict = {}
ALL_SYMS = ["GOLD", "USDJPY", "UsaInd", "UsaTec", "Ger40",
            "EURUSD", "EURJPY", "UK100"]
STOP_ATR = 1.5
BE_AT_R = 0.67
TRAIL_R = 2.0
MAX_HOLD = 5 * 1440
KILL_N, KILL_R = 60, -0.10


def _load_journal() -> pd.DataFrame:
    if JOURNAL.exists():
        j = pd.read_csv(JOURNAL, sep=";", parse_dates=["t"])
        j["t"] = pd.to_datetime(j["t"], utc=True)
        return j
    return pd.DataFrame(columns=["sym", "t", "dir", "entry", "sl_pts", "atr15", "kind",
                                 "label", "primary", "status", "R", "t_exit", "exit_status"])


def _save_journal(j: pd.DataFrame):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    j.sort_values(["sym", "t"]).to_csv(JOURNAL, sep=";", index=False)


def _entries(sym: str):
    """`(alsó keret, belépők)` — a LÁNC egy párra: a felső idősík a saját
    swingjét töri (1. jelzés) → érvényes az új HH-ig → pipa (2. jelzés) →
    az alsó kereten counter-trend belépők. A stop PONTBAN, mint a naplóban.

    ⚠ A jelzés IDŐPONTJA az ALSÓ keret gyertyája, ezért a napló ideje is az."""
    m1 = lab.load_m1(sym)
    P = sw.with_tf_pair(None)
    hi = sw.resample(m1, P["hi_tf"])
    lo = m1 if P["lo_tf"] <= 1 else sw.resample(m1, P["lo_tf"])
    s_ = m1["avg_spread"].dropna()
    sp = float(s_[s_.index >= s_.index.max() - pd.Timedelta(days=365)].median()) \
        if len(s_) else 0.0
    et = sw.counter_entries(lo, sw.chain_setups(hi, P), P, spread=sp)
    if not len(et):
        return None
    et = et.sort_values("i").drop_duplicates("i", keep="first")
    ps = float(lab.PAIRS[sym]["point_size"])
    ent = pd.DataFrame(dict(i=et.i, dir=et.dir, sl_pts=et.sl_abs / ps,
                            atr15=et.sl_abs / ps, kind="lanc", label=et.label))
    return lo, ent


def _in_band(sym: str, t: pd.Timestamp) -> bool:
    """Az ELSŐDLEGES mintába esik-e? Üres `PRIMARY` → MINDEN jelzés beleesik
    (nincs szűkítés). Ha valaha újra sáv kell, elég ide felvenni."""
    if not PRIMARY:
        return True
    b = PRIMARY.get(sym)
    return bool(b and b[0] <= t.hour <= b[1])


def update(with_mt5: bool = True):
    if with_mt5:
        from tools.download_history import ensure_history
        cfg = json.load(open(ROOT / "config.json", encoding="utf-8"))
        for sym in ALL_SYMS:
            ok, msg = ensure_history(sym, cfg, tf_labels=("M15", "M1"))
            print(f"   {sym}: {msg}")
    lab._CACHE.clear()
    j = _load_journal()
    uj = []
    for sym in ALL_SYMS:
        r = _entries(sym)
        if r is None:
            continue
        m1, ent = r
        ent = ent.drop_duplicates("i")
        # ⚠ csak ZÁRT M1 gyertya: az utolsó bar formálódhat → kihagyjuk
        ent = ent[ent.i < len(m1) - 1]
        for x in ent.itertuples():
            t = m1.index[int(x.i)]
            if t < START:
                continue
            if ((j.sym == sym) & (j.t == t)).any():
                continue
            uj.append(dict(sym=sym, t=t, dir=int(x.dir), entry=float(m1["close"].iloc[int(x.i)]),
                           sl_pts=float(x.sl_pts), atr15=float(x.atr15), kind=x.kind,
                           label=x.label, primary=_in_band(sym, t), status="open",
                           R=np.nan, t_exit=pd.NaT, exit_status=""))
    if uj:
        j = pd.concat([j, pd.DataFrame(uj)], ignore_index=True)
    _save_journal(j)
    print(f"   +{len(uj)} új jelzés → {JOURNAL.name} (összesen {len(j)}, "
          f"elsődleges {int(j.primary.sum()) if len(j) else 0})")


def _spread_filled(m1: pd.DataFrame) -> pd.DataFrame:
    """A hiányzó spread-mezők helyére a pár utolsó 12 hónapos tick-alapú mediánja."""
    m = m1.copy()
    hist = m["avg_spread"].dropna()
    if len(hist):
        ref = float(hist[hist.index >= hist.index.max() - pd.Timedelta(days=365)].median())
        m["avg_spread"] = m["avg_spread"].fillna(ref)
        m["close_spread"] = m["close_spread"].fillna(ref)
    return m


def evaluate():
    lab._CACHE.clear()
    j = _load_journal()
    if not len(j):
        print("   üres napló")
        return
    for sym in sorted(j.sym.unique()):
        m1 = _spread_filled(lab.load_m1(sym))
        ps = float(lab.PAIRS[sym]["point_size"])
        rows = j[j.sym == sym].sort_values("t")
        idx = np.searchsorted(m1.index.to_numpy(), rows.t.to_numpy())
        ok = (idx < len(m1)) & (m1.index[np.minimum(idx, len(m1) - 1)] == rows.t.to_numpy())
        if not ok.all():
            print(f"   ! {sym}: {int((~ok).sum())} jelzés ideje nincs az adatban — kihagyva")
        rows, idx = rows[ok], idx[ok]
        if not len(rows):
            continue
        # A pár ÖSSZES jelzése időrendben, egyszerre egy pozíció (mint a mérésben)
        tr = lab.simulate(m1, idx, rows.dir.to_numpy(int), rows.sl_pts.to_numpy(float),
                          np.zeros(len(rows)), point_size=ps, max_hold=MAX_HOLD,
                          be_at_r=BE_AT_R, trail_r=TRAIL_R, one_at_a_time=True,
                          pair_cfg=lab.PAIRS[sym])
        nyitott = set(tr["i_open"].tolist())
        n = len(m1)
        for r in tr:
            lezart = (r["status"] in (0, 1, 3)) or (r["i_close"] - r["i_open"] >= MAX_HOLD) \
                or (r["i_close"] < n - 1)
            # ⚠ ha az adat vége előbb jön, mint a kilépés, a kötés még NYITOTT
            if r["status"] == 2 and r["i_close"] >= n - 1 and r["i_close"] - r["i_open"] < MAX_HOLD:
                lezart = False
            sel = (j.sym == sym) & (j.t == m1.index[r["i_open"]])
            if lezart:
                j.loc[sel, ["status", "R", "t_exit", "exit_status"]] = [
                    "closed", float(r["r"]), m1.index[r["i_close"]],
                    {0: "SL", 1: "TP", 2: "idő", 3: "BE/csúszó"}[int(r["status"])]]
            else:
                j.loc[sel, "status"] = "open"
        # amit a szimulátor átugrott (nyitott pozíció mellett jött): kihagyva
        for k, t in zip(idx, rows.t):
            if k not in nyitott:
                j.loc[(j.sym == sym) & (j.t == t) & (j.status != "closed"), "status"] = "kihagyva"
    _save_journal(j)
    print(f"   lezárt {int((j.status == 'closed').sum())}, nyitott {int((j.status == 'open').sum())}, "
          f"kihagyva {int((j.status == 'kihagyva').sum())}")


def _t(x):
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else 0.0


def summary(j: pd.DataFrame | None = None) -> dict:
    """Az állás SZÁMOKBAN — ebből ír a riport, és ez megy a `csilla_status.json`-ba.
    `verdict`: `kill` (a leállító küszöb teljesült) · `running` (n < küszöb) ·
    `holding` (n ≥ küszöb, de nem bukott)."""
    j = _load_journal() if j is None else j
    c = j[j.status == "closed"]
    p = c[c.primary == True]                                                   # noqa: E712
    def _blokk(d):
        return dict(n=int(len(d)), r_mean=(float(d.R.mean()) if len(d) else None),
                    r_sum=(float(d.R.sum()) if len(d) else 0.0), t=float(_t(d.R)) if len(d) else 0.0,
                    win=(float((d.R > 0).mean()) if len(d) else None))
    if len(p) >= KILL_N and p.R.mean() < KILL_R:
        verdict = "kill"
    elif len(p) < KILL_N:
        verdict = "running"
    else:
        verdict = "holding"
    return dict(updated_at=pd.Timestamp.now().isoformat(timespec="seconds"),
                started=f"{START:%Y-%m-%d}", signals=int(len(j)), closed=int(len(c)),
                open=int((j.status == "open").sum()), skipped=int((j.status == "kihagyva").sum()),
                primary=_blokk(p), secondary=_blokk(c), kill_n=KILL_N, kill_r=KILL_R,
                to_kill=max(0, KILL_N - int(len(p))), verdict=verdict)


def write_status(j: pd.DataFrame | None = None) -> dict:
    d = summary(j)
    try:
        STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
        STATUS_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as ex:
        # ⚠ NEM NÉMA: a felület ebből olvas; ha nem íródik, a riport mondja meg.
        print(f"   ! az állapot-fájl nem íródott ({STATUS_JSON.name}): {ex!r}")
    return d


def report():
    pd.set_option("display.width", 200)
    j = _load_journal()
    c = j[j.status == "closed"]
    write_status(j)
    print(f"\n════ CSILLA-LÁNC FORWARD — {pd.Timestamp.now():%Y-%m-%d} (indult {START:%Y-%m-%d}) ════")
    print(f"napló: {len(j)} jelzés · lezárt {len(c)} · nyitott {int((j.status == 'open').sum())} "
          f"· kihagyva {int((j.status == 'kihagyva').sum())}")
    # ⚠ Sáv nélkül a két minta AZONOS — ilyenkor EGY blokkot írunk ki. Két
    # egyforma táblázat egymás alatt azt sugallná, hogy két külön mérés fut.
    _blokkok = ([("ELSŐDLEGES (mind a pár, minden óra)", c)] if not PRIMARY else
                [("ELSŐDLEGES (Csilla-sáv)", c[c.primary == True]),            # noqa: E712
                 ("másodlagos (mind a pár, minden óra)", c)])
    for nev, d in _blokkok:
        print(f"\n── {nev} ── n={len(d)}")
        if not len(d):
            continue
        print(f"   R/kötés {d.R.mean():+.3f}  ΣR {d.R.sum():+.2f}  t {_t(d.R):+.2f}  "
              f"nyerő {100 * (d.R > 0).mean():.0f}%")
        print(d.groupby("sym").R.agg(["size", "mean", "sum"]).round(3).to_string())
        print("   kilépés: " + ", ".join(f"{k}={v}" for k, v in d.exit_status.value_counts().items()))
    p = c[c.primary == True]                                                   # noqa: E712
    print("\n── az előre rögzített küszöbökhöz ──")
    if len(p) >= KILL_N and p.R.mean() < KILL_R:
        print(f"   ❌ LEÁLL: n={len(p)} ≥ {KILL_N} és R={p.R.mean():+.3f} < {KILL_R}")
    elif len(p) < KILL_N:
        print(f"   … még {KILL_N - len(p)} kötés a leállító küszöbig; t≥2-höz ~280 kötés kell")
    else:
        print(f"   fut: n={len(p)}, R={p.R.mean():+.3f}, t={_t(p.R):+.2f} (kell ≥ 2)")


def status_lines() -> list:
    """Az állás EMBERI sorai a felületnek / az esti riportnak — a
    `csilla_status.json`-ból, amit a `--report` ír. NEM számol újra: ha nincs
    fájl, azt mondja (a „nincs adat" nem ugyanaz, mint a „0 kötés")."""
    from core.i18n import t as _tr
    try:
        d = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return [_tr("forward.no_status")]
    p = d.get("primary") or {}
    sorok = [_tr("forward.journal", signals=d.get("signals", 0), closed=d.get("closed", 0),
                 open=d.get("open", 0), skipped=d.get("skipped", 0),
                 since=d.get("started", ""))]
    if p.get("n"):
        sorok.append(_tr("forward.primary", n=p["n"], r=f"{p['r_mean']:+.3f}",
                         t=f"{p['t']:+.2f}", win=f"{100 * (p.get('win') or 0):.0f}"))
    else:
        sorok.append(_tr("forward.primary_empty"))
    v = d.get("verdict")
    if v == "kill":
        sorok.append(_tr("forward.verdict_kill", n=p.get("n", 0),
                         r=f"{p.get('r_mean') or 0:+.3f}"))
    elif v == "running":
        sorok.append(_tr("forward.verdict_running", left=d.get("to_kill", 0)))
    else:
        sorok.append(_tr("forward.verdict_holding", n=p.get("n", 0),
                         r=f"{p.get('r_mean') or 0:+.3f}", t=f"{p.get('t') or 0:+.2f}"))
    return sorok


def job_spec() -> dict:
    """A napi feladat leírása a keretnek (`Strategy.daily_jobs()` adja vissza)."""
    from core.i18n import t as _tr
    return dict(name="csilla_forward", time="22:30", label=_tr("forward.head"),
                run=lambda argv: main(argv if argv else ["--all"]),
                status_lines=status_lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--no-mt5", action="store_true", help="update MT5-frissítés nélkül")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if a.all or a.update:
        update(with_mt5=not a.no_mt5)
    if a.all or a.evaluate:
        evaluate()
    if a.all or a.report or not (a.update or a.evaluate):
        report()
    return 0


if __name__ == "__main__":
    main()
