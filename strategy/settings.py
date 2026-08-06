"""
Stratégia-config betöltés és szétválasztás.

A `config.json` a VÁZ (főprogram) beállításait tartja (broker, mt5, trading,
data, pairs, dashboard, optimizer-MOTOR). A stratégiához tartozó beállítások
(quality, indicators, sltp, position_mgmt és az optimizer PARAMÉTERTÉR) a
stratégia SAJÁT fájljában élnek: `strategy/config/<name>.json`.

Betöltéskor a kettő EGY futásidejű cfg-vé olvad (a downstream kód változatlanul
`cfg["indicators"]` stb. formában olvassa). Mentéskor a `main_config_view()` a
stratégia-szekciókat KISZŰRI, így a `config.json` sosem szennyeződik vissza.

Egyetlen helyen definiált a szétválasztás (STRATEGY_SECTIONS + az optimizer
motor-kulcsai), hogy a merge és a mentés mindig konzisztens maradjon.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# A stratégiához tartozó, teljes egészében átmozgatott top-level szekciók.
STRATEGY_SECTIONS = ("quality", "indicators", "sltp", "position_mgmt", "param_meta")

# Az `optimizer` szekció MEGOSZTOTT: a MOTOR-kulcsok a vázhoz (config.json),
# minden más (a paramétertér-tartományok + piaci szűrők) a stratégiához tartozik.
OPTIMIZER_ENGINE_KEYS = frozenset({
    "_comment_method", "method", "max_trials", "max_parallel_optimizers",
    "_comment_timeout", "stall_timeout_sec", "hard_timeout_sec",
    "_comment_wf", "wf_n_splits", "wf_train_months", "wf_test_months",
    "_comment_split", "train_start_date", "test_start_date",
    # Él-paritás: az optimalizáló a végrehajtási kapukkal (spread + TF-együttállás)
    # fusson-e. MOTOR-szintű (minden stratégiára ugyanaz) → a config.json-ban marad.
    "_comment_gates", "exec_gates",
    # Kockázatcsökkentés (rr) mint optimalizált dimenzió — framework-szintű engine
    # kapcsoló (opt-in) + a hangolható rr-tér; a config.json-ban marad (nem strat.).
    "_comment_rr", "optimize_rr", "rr_space",
})


def strategy_name(cfg: dict) -> str:
    return (cfg.get("strategy", {}) or {}).get("name", "wpr_sma")


def strategy_config_path(name: str) -> Path:
    """A stratégia saját config-fájlja (a strategy csomag mellett)."""
    return Path(__file__).resolve().parent / "config" / f"{name}.json"


def load_strategy_config(name: str) -> dict:
    """A stratégia saját beállításai. Hiányzó fájl esetén üres dict."""
    p = strategy_config_path(name)
    if not p.exists():
        log.warning("Stratégia-config nem található: %s", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base: dict, overlay: dict) -> dict:
    """overlay beolvasztása base-be (overlay nyer a levélértékeknél). Helyben."""
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def apply_strategy_config(cfg: dict) -> dict:
    """A futásidejű cfg-be beolvasztja az aktív stratégia saját beállításait.

    Visszafelé kompatibilis: ha a stratégia-fájl hiányzik, a cfg változatlan
    (egy régi, monolitikus config.json is működik).
    """
    strat = load_strategy_config(strategy_name(cfg))
    if strat:
        # A stratégia-szekciók felülírják / kiegészítik a vázat; az optimizer
        # motor-kulcsai a config.json-ból maradnak (nincs átfedés a terekkel).
        _deep_merge(cfg, {k: v for k, v in strat.items() if not k.startswith("_")})
    return cfg


def main_config_view(cfg: dict) -> dict:
    """A `config.json`-ba MENTHETŐ nézet: a stratégia-szekciók kiszűrve.

    A merge-elt futásidejű cfg-ből előállítja a tiszta váz-configot (perzisztálás
    és a Beállítás-szerkesztő megjelenítéséhez), hogy a fájl ne szennyeződjön.
    """
    view = copy.deepcopy(cfg)
    for sec in STRATEGY_SECTIONS:
        view.pop(sec, None)
    opt = view.get("optimizer")
    if isinstance(opt, dict):
        view["optimizer"] = {k: v for k, v in opt.items()
                             if k in OPTIMIZER_ENGINE_KEYS}
    return view


def write_config_file(data: dict, path: Path | str) -> str:
    """Egy MÁR KÉSZ váz-config dict ATOMIKUS kiírása. Visszaad: `""` ha sikerült,
    különben az EMBERI hibaüzenet (a hívó kiteszi az állapotsorba / hibacímkére).

    Két dolgot rendez, amit a korábbi `open(..., "w")` nem:

    **1. Atomicitás.** A `"w"` mód ELŐBB csonkolja a fájlt, és csak utána ír. Ha a
    szerializálás közben bármi elszáll (nem JSON-osítható érték), vagy a processz
    megáll, a `config.json` CSONKÁN marad — és az a fájl tartja a broker-belépőt, a
    párokat és a kereskedés-szándékot. A projekt MINDEN más állapotfájlja
    (`params_store`, `adopted`, `build_state`, `execution_params`…) temp→replace-szel
    ír; a legértékesebb fájl volt az egyetlen kivétel. Ráadásul előbb STRINGGÉ
    alakítunk, és csak utána nyitunk fájlt: egy szerializálási hiba így hozzá sem
    ér a lemezhez.

    **2. Beszédes hiba.** A mentés elbukhat (zárolt fájl, jogosultság, tele a
    lemez). Némán elnyelve a Play/Stop, a slot- és a limit-állítás úgy nézne ki,
    mintha megtörtént volna — és csak újraindításkor derülne ki, hogy nem. Ezért ad
    ez a függvény ÜZENETET, nem bool-t."""
    p = Path(path)
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error("config.json szerializálási hiba: %s", e)
        return f"A config nem alakítható JSON-ná: {e}"
    tmp = p.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        tmp.replace(p)
        return ""
    except Exception as e:
        log.error("config.json mentési hiba (%s): %s", p, e)
        try:
            tmp.unlink(missing_ok=True)      # ne maradjon félkész fájl
        except Exception:
            pass
        return f"Mentési hiba ({p.name}): {e}"


def save_main_config(cfg: dict, path: Path | str) -> str:
    """A FUTÁSIDEJŰ cfg kiírása váz-configként (a stratégia-szekciók kiszűrve).

    Ezt hívja a dashboard minden perzisztálásnál (Play/Stop, slot, napi limit,
    per-pár kapcsolók). Aki már kész váz-dictet tart a kezében (a ⚙ szerkesztő),
    az a `write_config_file`-t hívja — így a nézet-szűrés pontosan egyszer fut."""
    return write_config_file(main_config_view(cfg), path)


def config_for_strategy(cfg: dict, name: str) -> dict:
    """A futásidejű cfg átképezése EGY ADOTT stratégia nézetére.

    A futásidejű cfg az AKTÍV (elsődleges) stratégia szekcióival van merge-elve;
    ha egy MÁSIK stratégiát optimalizálunk/futtatunk (több-stratégia), annak a
    SAJÁT szekciói kellenek. A váz-szekciók (broker, mt5, trading, data, pairs,
    optimizer-MOTOR) maradnak, a stratégia-szekciók a `name` saját fájljából
    jönnek. Az elsődleges stratégiára identitás (ugyanazt adja, mint a cfg)."""
    view = main_config_view(cfg)
    strat = load_strategy_config(name)
    if strat:
        _deep_merge(view, {k: v for k, v in strat.items() if not k.startswith("_")})
    return view


def save_param_comments(name: str, comments: dict) -> bool:
    """A paraméter-megjegyzések visszaírása a stratégia configba
    (`param_meta.params.<kulcs>.comment`). A többi szekciót érintetlenül hagyja.
    Csak akkor ír, ha VÁLTOZOTT valamelyik megjegyzés (nincs felesleges fájlírás)."""
    p = strategy_config_path(name)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    pm = data.setdefault("param_meta", {})
    params = pm.setdefault("params", {})
    changed = False
    for k, c in comments.items():
        entry = params.setdefault(k, {})
        if entry.get("comment", "") != c:
            entry["comment"] = c
            changed = True
    if not changed:
        return False
    try:
        tmp = p.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(p)
        return True
    except Exception as ex:
        log.warning("param_meta mentési hiba (%s): %s", name, ex)
        return False


def duplicate_keys(text: str) -> list[str]:
    """A JSON-szövegben TÖBBSZÖR szereplő objektum-kulcsok (egy szinten belül).

    MIÉRT KELL. A JSON megengedi az ismételt kulcsot, és a `json.load` NÉMÁN az
    UTOLSÓT tartja meg — az előzőt eldobja. Egy kettévált szekció (pl. két `gates`
    blokk egy fájlban) így úgy néz ki, mintha be lenne állítva, közben az egyik
    fele teljes egészében halott. Pontosan az a hibaosztály, amit a
    `core/config_check.py` is céloz, csak ez a szintaxis szintjén ül, tehát a
    dictből MÁR NEM LÁTSZIK — a betöltéskor kell elkapni.

    (Ezt a `config.example.json`-ban egy kézi átnézés találta meg, nem a program.)

    A kulcsneveket adja vissza (rendezve, egyediesítve); a fészkelési utat nem
    követjük, mert a `object_pairs_hook` nem kap kontextust — a puszta név a
    keresést így is egy `Ctrl+F`-re szűkíti."""
    dups: list[str] = []

    def _hook(pairs):
        seen = {}
        for k, v in pairs:
            if k in seen:
                dups.append(k)
            seen[k] = v
        return seen

    json.loads(text, object_pairs_hook=_hook)
    return sorted(set(dups))


def load_config(cfg_path: Path | str) -> dict:
    """config.json betöltése + a stratégia-config beolvasztása (központi belépő)."""
    with open(cfg_path, encoding="utf-8") as f:
        text = f.read()
    cfg = json.loads(text)
    # Ismételt kulcs: a betöltés némán az UTOLSÓT tartja meg. Szólunk, mert a
    # fájlt olvasva a felhasználó az ELSŐT hiheti érvényesnek. Sosem gátol.
    try:
        dups = duplicate_keys(text)
        if dups:
            log.warning("%s — TÖBBSZÖR szereplő kulcs: %s. A JSON-ban az UTOLSÓ "
                        "előfordulás nyer, a korábbi(ak) NÉMÁN eldobódnak — "
                        "vond össze őket.", Path(cfg_path).name, ", ".join(dups))
    except Exception:
        pass
    return apply_strategy_config(cfg)
