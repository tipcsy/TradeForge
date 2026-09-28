"""CONFIG-FIGYELŐ — egy KÜLÖN processzben futó motor lássa a felület beállításait.

⚠ 0029, 4b/3 — S1 (2026-09-28). Amíg a motor a felület processzében fut, a két
fél UGYANAZT a `cfg` dictet látja: egy kapu vagy limit átállítása azonnal hat.
Egy külön processzben futó motornak (`main.py console --broker …`, és később
az otthoni motor is) viszont SAJÁT másolata van — a felületen átállított
beállítás csak a következő indításkor érné el. Ez a mai RoboForex-motorra is
igaz volt.

A MEGOLDÁS: a figyelő a `config.json`-t és a stratégia-configokat nézi
(módosítási idő); változáskor BETÖLTI az újat, a motor pedig a KÖR ELEJÉN,
biztonságos ponton ALKALMAZZA (`apply_pending`).

⚠ SZÁLBIZTONSÁG — ezért nem a figyelő alkalmaz. Ha a figyelő szál írná át a
configot, miközben a motor épp bejárja, a motor „dictionary changed size during
iteration" hibával elszállhatna — a kereskedő szál halála NÉMA (a projektben
volt már ilyen: `silent-thread-death`). A figyelő csak ELŐKÉSZÍT.

⚠ HELYBEN, REKURZÍVAN. A motor alhivatkozásokat tart (`trading_cfg =
cfg["trading"]`); egy `cfg.clear(); cfg.update(új)` ezeket elavult objektumon
hagyná. A `deep_update` a meglévő dict-objektumokat tartja meg.

⚠ A HÁROMUTAS MENTÉS ALAPJA (`strategy.settings._ALAP`) CSAK AZ ALKALMAZÁSKOR
frissül. Ha már betöltéskor frissülne, a betöltés és az alkalmazás közti
időben a motor egy mentése a felület friss változásait a SAJÁTJÁNAK látná, és
visszaírná a régit.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

PERIOD_SEC = 3.0

_lock = threading.Lock()
_pending: dict | None = None          # {"cfg": új cfg, "raw": a fájl JSON-ja, "path": …}
_watcher = None


def deep_update(dst: dict, src: dict) -> None:
    """`dst` helyben `src`-vé alakítása, a beágyazott dict-OBJEKTUMOK megtartásával."""
    for k in list(dst):
        if k not in src:
            del dst[k]
    for k, v in src.items():
        if isinstance(dst.get(k), dict) and isinstance(v, dict):
            deep_update(dst[k], v)
        else:
            dst[k] = v


def _figyelt(path: Path) -> list:
    out = [Path(path)]
    try:
        from strategy import paths as _sp
        d = _sp.config_file("x").parent
        out += sorted(d.glob("*.json"))
    except Exception:
        pass
    return out


def _lenyomat(files) -> tuple:
    t = []
    for f in files:
        try:
            st = f.stat()
            t.append((str(f), st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            t.append((str(f), 0, 0))
    return tuple(t)


class Watcher:
    def __init__(self, path, loader=None, period=PERIOD_SEC):
        from strategy import settings as _s
        self.path = Path(path)
        self.loader = loader or (lambda p: _s.load_config(p, remember=False))
        self.period = period
        self._fajlok = _figyelt(self.path)
        self._utolso = _lenyomat(self._fajlok)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._fut, daemon=True, name="ConfigWatch")

    def check_once(self) -> bool:
        """Egy ellenőrzés. True, ha változott és új config várakozik."""
        global _pending
        most = _lenyomat(self._fajlok)
        if most == self._utolso:
            return False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            uj = self.loader(self.path)
        except Exception as ex:
            # Félig írt / hibás fájl: NEM alkalmazunk semmit, a következő kör
            # újrapróbálja (a lenyomatot nem léptetjük).
            log.warning("config-figyelő: az új config nem olvasható (%s) — "
                        "a régi marad érvényben.", ex)
            return False
        self._utolso = most
        with _lock:
            _pending = {"cfg": uj, "raw": raw, "path": self.path}
        return True

    def _fut(self):
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception as ex:                       # a figyelő sosem áll meg
                log.debug("config-figyelő hiba: %s", ex)
            self._stop.wait(self.period)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._stop.set()


def start(path, **kw) -> Watcher:
    """A figyelő indítása (a konzolos / külön processzben futó motor hívja)."""
    global _watcher
    _watcher = Watcher(path, **kw).start()
    return _watcher


def apply_pending(cfg: dict) -> bool:
    """A MOTOR hívja a kör elején: ha új config várakozik, HELYBEN alkalmazza.
    Figyelő nélkül (a felület processzében futó motor) üres művelet."""
    global _pending
    with _lock:
        p, _pending = _pending, None
    if p is None:
        return False
    deep_update(cfg, p["cfg"])
    try:
        from strategy import settings as _s
        _s._ALAP[_s._alap_kulcs(p["path"])] = p["raw"]
    except Exception:
        pass
    log.info("config újratöltve (a felület módosította) — a motor az új "
             "beállításokkal fut tovább.")
    return True
