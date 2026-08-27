"""Fájl-alapú érték gyorsítótár — hogy a FŐ SZÁL ne olvasson lemezt soronként.

LELET (2026-08-27). A dashboard 2.0 sora minden képfrissítésnél megnyitotta és
JSON-ként beparse-olta a stratégia mentett paraméter-fájlját (`_live2_quality`),
plusz `exists()`+`stat()`-olt egy done-markert (`opt_done_date`). 12 pár × 2
stratégia = **24 fájlművelet 3 másodpercenként**. Amíg egy 672 futásos hangolás
nyomta a lemezt, ezek a hívások beragadtak, és a **fő szál 93,5 másodpercre
megállt** — a program teljesen befagyottnak látszott.

Ugyanaz a hibafajta, mint a mély-warmup GIL-fogás: a kijelzési út csinál drága
munkát körönként. A megoldás is ugyanaz: NE csináld újra, ha nem változott.

Két lépcsőben véd:
  1. **TTL** — a `ttl` másodpercen belül a lemezhez HOZZÁ SEM nyúlunk.
  2. **mtime+méret** — a TTL lejárta után is csak `stat()`; a drága olvasás
     (`loader`) akkor fut, ha a fájl tényleg megváltozott.

TISZTA modul: se tkinter, se MT5. Az órajel (`clock`) becserélhető → tesztelhető.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable


class FileCache:
    """`path` → a `loader(path)` eredménye, amíg a fájl nem változik.

    Szálbiztos: a dashboard több szála is olvashatja ugyanazt a bejegyzést.
    A `loader` a LOCKON KÍVÜL fut — egy lassú lemez ne fogja meg a többi szálat
    (épp ez volt az eredeti hiba)."""

    def __init__(self, ttl: float = 10.0, clock: Callable[[], float] = time.monotonic):
        self.ttl = float(ttl)
        self._clock = clock
        self._lock = threading.Lock()
        # kulcs → (utolsó ellenőrzés ideje, mtime_ns, méret, érték)
        self._store: dict[str, tuple[float, int, int, Any]] = {}
        self.hits = self.stats = self.loads = 0     # diagnosztika/teszt

    def get(self, path: "Path | str", loader: Callable[[Path], Any],
            default: Any = None) -> Any:
        """A fájlból származó érték. `default`, ha a fájl nincs meg vagy a
        `loader` elszáll — a hívónak nem kell hibát kezelnie."""
        p = Path(path)
        key = str(p)
        now = self._clock()

        with self._lock:
            ent = self._store.get(key)
            if ent is not None and (now - ent[0]) < self.ttl:
                self.hits += 1
                return ent[3]                    # a lemezhez HOZZÁ SEM nyúlunk

        # TTL lejárt → EGY olcsó stat. (A locknál kívül: ne blokkoljunk mást.)
        self.stats += 1
        try:
            st = p.stat()
            mtime, size = st.st_mtime_ns, st.st_size
        except OSError:
            with self._lock:
                self._store[key] = (now, -1, -1, default)
            return default

        with self._lock:
            ent = self._store.get(key)
            if ent is not None and ent[1] == mtime and ent[2] == size:
                # nem változott → csak az időbélyeget frissítjük
                self._store[key] = (now, mtime, size, ent[3])
                self.hits += 1
                return ent[3]

        self.loads += 1
        try:
            value = loader(p)
        except Exception:
            # A hívó szempontjából ez „nincs adat"; a hibát NEM nyeljük el
            # csendben abban az értelemben, hogy a default megkülönböztethető.
            value = default
        with self._lock:
            self._store[key] = (now, mtime, size, value)
        return value

    def invalidate(self, path: "Path | str | None" = None) -> None:
        """Egy fájl (vagy minden) bejegyzésének eldobása — ha a hívó TUDJA,
        hogy változott, és nem akarja megvárni a TTL-t."""
        with self._lock:
            if path is None:
                self._store.clear()
            else:
                self._store.pop(str(Path(path)), None)

    def counters(self) -> dict:
        with self._lock:
            return {"hits": self.hits, "stats": self.stats, "loads": self.loads,
                    "entries": len(self._store)}
