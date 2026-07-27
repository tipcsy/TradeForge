"""
TF-együttállás figyelő — több-idősíkú SMA-irány (keretrendszer-szintű monitor).

Idősíkonként a trend-irány EGYSZERŰ: `sign(utolsó close − SMA(n))`. Ha a figyelt
idősíkok (alap: M1/M5/M15) MIND egy irányba mutatnak → erős együttállás ("S"):
BUY (mind fölfelé) vagy SELL (mind lefelé). Különben vegyes → nincs erős jel.

Ez egy MEGJELENÍTŐ (a dashboard „Együtt" oszlopa) — nem befolyásolja a kereskedést.
A modul SZÁNDÉKOSAN MT5-mentes és tiszta (tesztelhető): a bar-adatot (záróárak
idősíkonként) a hívó (dashboard) tölti native copy_rates-ből.

Konfiguráció (config.json, VÁZ-szint; per-pár felülírható a `pairs.<sym>.tf_align`-ban):
    "tf_align": { "enabled": true, "viz": false,
                  "timeframes": [1, 5, 15], "sma_period": 50, "gate": [] }

KÉT KÜLÖN kapcsoló:
  • `enabled` — a FIGYELÉS: az „Együtt" oszlop és a belépő-kapu (`gate`).
  • `viz`     — a chart-RAJZ: a figyelt idősíkok SMA-vonalai. Hiányzó `viz` esetén
                az `enabled` dönt (visszafelé kompatibilis).
"""

from __future__ import annotations

DEFAULT_TIMEFRAMES = [1, 5, 15]
DEFAULT_SMA = 50

# Idősík (perc) → rövid címke a cellához/tooltiphez.
TF_LABEL = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 240: "H4"}


def _normalize(tc: dict) -> tuple:
    """(enabled, timeframes, sma_period, gate) egy tf_align-szótárból."""
    enabled = bool(tc.get("enabled", True))
    tfs = tc.get("timeframes") or DEFAULT_TIMEFRAMES
    try:
        tfs = [int(t) for t in tfs]
    except (TypeError, ValueError):
        tfs = list(DEFAULT_TIMEFRAMES)
    sma = max(2, int(tc.get("sma_period", DEFAULT_SMA)))
    gate = list(tc.get("gate") or [])   # mely stratégiák belépőjét kapuzza
    return enabled, tfs, sma, gate


def config(cfg: dict) -> tuple:
    """GLOBÁLIS (enabled, timeframes, sma_period) a config.json `tf_align`-jából.
    Visszafelé kompatibilis (a `gate`-et nem adja vissza)."""
    en, tfs, sma, _ = _normalize(cfg.get("tf_align") or {})
    return en, tfs, sma


def _merged(cfg: dict, symbol: str) -> dict:
    """A per-pár `pairs.<sym>.tf_align` a globális `tf_align` fölé olvasztva
    (kulcsonként), az pedig az alapértékek fölé."""
    glob = cfg.get("tf_align") or {}
    pair = ((cfg.get("pairs") or {}).get(symbol) or {}).get("tf_align") or {}
    return {**glob, **pair}


def config_for(cfg: dict, symbol: str) -> tuple:
    """(enabled, timeframes, sma_period, gate) az ADOTT instrumentumra: a per-pár
    `pairs.<sym>.tf_align` FELÜLÍRJA a globális `tf_align`-t (kulcsonként), az pedig
    az alapértékeket. Így minden instrumentum mást figyelhet (pl. M1/M15/H1, SMA100).

    Az `enabled` a FIGYELÉST kapcsolja: az „Együtt" oszlopot és a belépő-kaput.
    A chart-rajzot NEM — arra külön kapcsoló van (`viz_on`)."""
    return _normalize(_merged(cfg, symbol))


def viz_on(cfg: dict, symbol: str) -> bool:
    """Látszanak-e a figyelt idősíkok SMA-vonalai a CHARTON.

    FÜGGETLEN az `enabled`-től: figyelheted az együttállást chart-rajz nélkül
    (tiszta chart), és fordítva, kirajzoltathatod az SMA-kat anélkül, hogy az
    oszlop/kapu dolgozna.

    Visszafelé kompatibilis: ha a `viz` kulcs HIÁNYZIK, az `enabled` dönt — a
    régi configok pontosan úgy viselkednek, mint eddig (egy kapcsoló mindkettőre)."""
    tc = _merged(cfg, symbol)
    v = tc.get("viz")
    if v is None:
        return bool(tc.get("enabled", True))
    return bool(v)


def _sign(closes, n: int) -> int:
    """sign(utolsó close − SMA(n)) az adott idősík záróáraiból. 0, ha kevés adat
    vagy pont a SMA-n (semleges)."""
    if not closes or len(closes) < n:
        return 0
    tail = closes[-n:]
    sma = sum(tail) / n
    d = closes[-1] - sma
    return 1 if d > 0 else -1 if d < 0 else 0


def alignment(closes_by_tf: dict, timeframes: list, sma_period: int) -> tuple:
    """(direction, signs). `signs` a `timeframes` SORRENDJÉBEN (+1 fölfelé / −1
    lefelé / 0 semleges-vagy-adathiány). `direction` = 'BUY' ha MIND +1, 'SELL' ha
    MIND −1, különben None (vegyes/hiányos)."""
    signs = [_sign(closes_by_tf.get(tf), sma_period) for tf in timeframes]
    if signs and all(s == 1 for s in signs):
        direction = "BUY"
    elif signs and all(s == -1 for s in signs):
        direction = "SELL"
    else:
        direction = None
    return direction, signs


def gate_ok(alignment_dir: "str | None", signal: str) -> bool:
    """A belépő ENGEDÉLYEZETT-e a TF-együttállás kapu szempontjából: True, ha az
    együttállás iránya EGYEZIK a jel irányával (minden figyelt idősík a trenddel).
    Ha nincs teljes együttállás (`alignment_dir is None`) → False (blokkol). A hívó
    csak akkor alkalmazza, ha a stratégia kapuzva van az adott instrumentumon."""
    return alignment_dir is not None and alignment_dir == signal


def labels(timeframes: list) -> list:
    """Az idősíkok rövid címkéi (a cella/tooltip sorrendjéhez)."""
    return [TF_LABEL.get(t, f"{t}m") for t in timeframes]


# ---------------------------------------------------------------------------
# Historikus (visszamenőleges) kapu — backtest + viz jel-replay
# ---------------------------------------------------------------------------
# Az ÉLŐ kapu (`alignment` + `gate_ok`) a copy_rates 0. pozíciójából dolgozik, azaz
# az utolsó gyertya a ma FORMÁLÓDÓ bar, aminek a „close"-a a PILLANATNYI ár. Egy
# historikus kiértékelőnek ezt kell utánoznia — és pontosan itt volt a hiba:
#
#   RÉGI (hibás): a t időpontot tartalmazó TF-gyertya VÉGLEGES záróárából számolt
#   irányt. A t pillanatában viszont még nem tudható, hogyan fog zárni az a gyertya
#   → LOOK-AHEAD. Egy M15-kapunál ez akár 15 percnyi jövőbelátás; a backtest ettől
#   olyan belépőket engedett át (és olyanokat szűrt ki), amiket az él nem tudhatott.
#
#   ÚJ (helyes): a formálódó gyertya záróára = az AKKORI ár (`price`), az SMA-ba
#   pedig a nála korábbi, MÁR LEZÁRT gyertyák mennek. Ez bitre az élő képlet:
#       sma = (a megelőző n−1 lezárt close összege + price) / n
#       irány = sign(price − sma)
#   Mivel `price − sma = ((n−1)·price − Σ_lezárt) / n`, elég az előjelet nézni.

def build_historical_signs(bars_by_tf: dict, sma_period: int):
    """Idősíkonkénti trend-előjel egy MÚLTBELI pillanatra — look-ahead NÉLKÜL.

    `bars_by_tf`: `{idősík_perc: (open_unix, closes)}` — a TF-gyertyák NYITÓ ideje
    (unix, növekvő) és VÉGLEGES záróára. A hívó tölti (a backtest resample-lel az
    M1-ből, a viz és a kutató-eszköz a saját forrásából).

    Visszaad: `fn(t_unix, price) -> [előjel, …]` a `bars_by_tf` sorrendjében, ahol a
    `price` a t pillanatban ISMERT ár. Az előjel +1 / −1 / 0 (semleges VAGY
    adathiány) — pontosan úgy, ahogy az élő `_sign`.

    Ez a KÖZÖS mag: a backtest kapuja, a viz jel-replay és a `tf_align_analysis`
    kutató-eszköz mind ezt használja, így nem csúszhatnak szét."""
    import numpy as np

    n = max(2, int(sma_period))
    prepared = []
    for tf, (open_unix, closes) in (bars_by_tf or {}).items():
        c = np.asarray(closes, dtype=float)
        t_open = np.asarray(open_unix, dtype=np.int64)
        if len(c) < n or len(t_open) != len(c):
            prepared.append(None)          # nincs elég LEZÁRT gyertya → mindig 0
            continue
        # prefix[i] = c[0..i-1] összege → a k-adik gyertya ELŐTTI n−1 lezárt close
        # összege: prefix[k] − prefix[k−n+1].
        prepared.append((t_open, np.concatenate(([0.0], np.cumsum(c)))))

    def _at(t_unix, price):
        t = int(t_unix)
        p = float(price)
        out = []
        for item in prepared:
            if item is None:
                out.append(0)
                continue
            t_open, prefix = item
            k = int(np.searchsorted(t_open, t, side="right")) - 1
            if k < n - 1:
                out.append(0)      # nincs mögötte n−1 lezárt gyertya (mint az él)
                continue
            prior_sum = prefix[k] - prefix[k - n + 1]     # az n−1 lezárt close összege
            d = (n - 1) * p - prior_sum                   # ∝ (price − sma)
            out.append(1 if d > 0 else -1 if d < 0 else 0)
        return out

    return _at


def build_historical_gate(bars_by_tf: dict, sma_period: int):
    """A TF-együttállás KAPU historikus kiértékelője — look-ahead nélkül.

    Visszaad: `fn(t_unix, price, direction) -> bool`. True, ha minden figyelt idősík
    a jel irányába állt. A döntés a `build_historical_signs` előjeleiből, ugyanazzal
    az `alignment`/`gate_ok` szabállyal, mint az élő út.

    ADATHIÁNY: az él ilyenkor BLOKKOL (a `_sign` 0-t ad → nincs teljes együttállás →
    `gate_ok` False). Ezért itt is blokkolunk, nem „fail-open"-ozunk — különben a
    backtest olyan belépőket mutatna, amiket az él sosem venne fel."""
    if not bars_by_tf:
        return lambda t_unix, price, direction: False
    signs_at = build_historical_signs(bars_by_tf, sma_period)

    def _at(t_unix, price, direction):
        signs = signs_at(t_unix, price)
        if not signs:
            return False
        if all(s == 1 for s in signs):
            aligned = "BUY"
        elif all(s == -1 for s in signs):
            aligned = "SELL"
        else:
            return False               # vegyes/semleges → nincs teljes együttállás
        return gate_ok(aligned, direction)

    return _at
