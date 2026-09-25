"""
A VOLATILITÁS-KAPU számainak átköltöztetése a stratégia-készletekből az
instrumentumhoz (v3.103.0).

MIT CSINÁL
  1. `data/optimized_params/<stratégia>/<SYM>.json` → a `VOL_KEYS`
     (`atr_min_pct`, `atr_max_pct`, `atr_baseline_bars`, `atr_avg_ref`) átkerül a
     `data/execution_params/<SYM>.json`-ba, és KIKERÜL a stratégia-készletből.
  2. `config.json` → `gates.volatility = {"default": "none", "wpr_sma": "block"}`
     (a meglévő bejegyzések megmaradnak, csak a hiányzók kerülnek be).

MIÉRT KELL A 2. PONT. Eddig csak a wpr_sma készleteiben volt küszöb, tehát a
kapu (`block` alaphatással) a többi stratégiára NEM szűrt. Instrumentum-szinten
a küszöb MINDEN stratégiára ott van — a `default: none` nélkül a csilla, a
trend_pullback és a pending_straddle ugyanazokon a párokon NÉMÁN szűrni kezdene.
Így a viselkedés bitre a régi; aki egy másik stratégiára is akarja, a kapu
ablakában bekapcsolja.

Biztonság
  • Alapból PRÓBA (semmit nem ír) — `--apply` kell az íráshoz.
  • Írás előtt MENTÉS: `data/_backup_vol_gate_<időbélyeg>/`.
  • Ütközés (ugyanarra a párra két stratégia MÁS küszöböt ad, vagy az
    instrumentumon már más érték áll) → az a pár KIMARAD, és a napló megmondja.
  • Idempotens: második futásra nincs mit költöztetni.

⚠ A PROGRAM FUSSON LE ELŐTTE: a futó TradeForge a memóriában tartott configot
visszaírja (a `gates` bejegyzés elveszne), a régi kód pedig a stratégia-
készletből olvassa a küszöböt — a költöztetés után nála a kapu nem szűrne.

Futtatás:
    python tools/migrate_vol_gate.py            # próba
    python tools/migrate_vol_gate.py --apply    # élesben
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import execution_params as _ep          # noqa: E402

GATE_SECTION = {"default": "none", "wpr_sma": "block"}


def _strategy_dirs(params_dir: Path):
    """A valódi stratégia-mappák (a `_`-kezdetű mentés/elutasított mappák nem)."""
    return sorted(p for p in params_dir.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-12 * max(1.0, abs(float(a)))
    except (TypeError, ValueError):
        return a == b


def plan(root: Path) -> dict:
    """`{"moves": {sym: {kulcs: érték}}, "files": [(path, sym)], "conflicts": [...]}`"""
    params_dir = root / "data" / "optimized_params"
    per_sym: dict = {}
    files: list = []
    conflicts: list = []
    for d in _strategy_dirs(params_dir):
        for f in sorted(d.glob("*.json")):
            if f.stem.endswith("_hours"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception as ex:
                conflicts.append(f"{f}: nem olvasható ({ex})")
                continue
            prm = (data or {}).get("params") or {}
            vol = {k: prm[k] for k in _ep.VOL_KEYS if k in prm}
            if not vol:
                continue
            sym = data.get("symbol") or f.stem
            files.append((f, sym))
            have = per_sym.setdefault(sym, {})
            for k, v in vol.items():
                if k in have and not _same(have[k], v):
                    conflicts.append(f"{sym}: {k} két stratégiában eltér "
                                     f"({have[k]} vs {v}, {f.parent.name})")
                have.setdefault(k, v)
    bad = {c.split(":")[0] for c in conflicts}
    # Az instrumentumon MÁR álló, eltérő érték is ütközés.
    for sym, vol in per_sym.items():
        try:
            own = _ep._read_own(sym)
        except Exception as ex:
            conflicts.append(f"{sym}: execution_params nem olvasható ({ex})")
            bad.add(sym)
            continue
        for k, v in vol.items():
            if k in own and not _same(own[k], v):
                conflicts.append(f"{sym}: {k} az instrumentumon már {own[k]}, "
                                 f"a készletben {v}")
                bad.add(sym)
    moves = {s: v for s, v in per_sym.items() if s not in bad}
    files = [(f, s) for f, s in files if s not in bad]
    return {"moves": moves, "files": files, "conflicts": conflicts}


def gates_patch(cfg: dict) -> dict:
    """A `gates.volatility` hiányzó bejegyzései (üres = nincs teendő)."""
    cur = ((cfg.get("gates") or {}).get("volatility") or {})
    return {k: v for k, v in GATE_SECTION.items() if k not in cur}


def apply(root: Path, p: dict, cfg_path: Path, log=print) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bdir = root / "data" / f"_backup_vol_gate_{stamp}"
    bdir.mkdir(parents=True, exist_ok=False)
    # ── MENTÉS előbb, mindenről, amihez hozzányúlunk ──
    for f, _s in p["files"]:
        dst = bdir / "optimized_params" / f.parent.name / f.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    for sym in p["moves"]:
        src = _ep.execution_params_file(sym)
        if src.exists():
            dst = bdir / "execution_params" / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if cfg_path.exists():
        shutil.copy2(cfg_path, bdir / cfg_path.name)
    # ── 1) instrumentum ←, 2) stratégia-készletből ki ──
    for sym, vol in p["moves"].items():
        _ep.save_execution_params(sym, vol)
        log(f"  {sym}: → execution_params {vol}")
    for f, sym in p["files"]:
        data = json.loads(f.read_text(encoding="utf-8"))
        data["params"] = _ep.without_vol_keys(data.get("params") or {})
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False,
                                  default=str), encoding="utf-8")
        tmp.replace(f)
        log(f"  {f.parent.name}/{f.name}: kulcsok kivéve")
    # ── 3) config: a többi stratégia hatása `none` ──
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    patch = gates_patch(cfg)
    if patch:
        cfg.setdefault("gates", {}).setdefault("volatility", {}).update(patch)
        tmp = cfg_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(cfg_path)
        log(f"  config.json: gates.volatility += {patch}")
    return bdir


def main():
    ap = argparse.ArgumentParser(description="Volatilitás-kapu számainak "
                                 "átköltöztetése az instrumentumhoz")
    ap.add_argument("--apply", action="store_true", help="írás (alap: próba)")
    args = ap.parse_args()
    cfg_path = ROOT / "config.json"
    p = plan(ROOT)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    patch = gates_patch(cfg)
    print(f"Költöztetendő pár: {len(p['moves'])}, érintett készlet: "
          f"{len(p['files'])}, config-kiegészítés: {patch or '—'}")
    for sym, vol in sorted(p["moves"].items()):
        print(f"  {sym:9s} {vol}")
    for c in p["conflicts"]:
        print(f"  ⚠ KIMARAD — {c}")
    if not args.apply:
        print("\nPRÓBA — semmi nem íródott. Élesben: --apply "
              "(előtte a TradeForge-ot zárd be).")
        return
    if not p["moves"] and not patch:
        print("Nincs teendő.")
        return
    bdir = apply(ROOT, p, cfg_path)
    print(f"\nKész. Mentés: {bdir}")


if __name__ == "__main__":
    main()
