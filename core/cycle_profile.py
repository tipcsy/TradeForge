"""A motor-kör PROFILJA — hová megy el az idő (0030/1, 2026-10-02).

A tünet: külső motoros módban a kör átlag 1,5–2,6 mp (csúcs 4,8 mp), korábban
0,4. Mérve: a közzététel MT5-lekérdezései olcsók (0,6 ms); a felület zárva a kör
0,45 mp volt. A gyanú (NEM mérve): a felület gyertya-kérései a motor processzében
a GIL-ért és az MT5-zárért versenyeznek a kereskedési körrel.

Ez a modul azt méri, amiből eldönthető:
  • a kör FALIÓRA-ideje vs a kereskedési szál SAJÁT CPU-ideje — ha a falióra
    sokkal több, a szál VÁR (zár / GIL / I/O); ha közel egyenlő, SZÁMOL;
  • a leglassabb pár/stratégia feldolgozási ideje;
  • a csatornán érkező kérések (a felülettől) műveletenként: darab + összidő.
A motor 30 körönként egy naplósort ír (a kör-idő sora mellé). Szálbiztos.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_zar = threading.Lock()
_parok: dict = defaultdict(lambda: [0.0, 0])      # kulcs → [összidő, darab]
_muveletek: dict = defaultdict(lambda: [0.0, 0])  # művelet → [összidő, darab]
_cpu = [0.0]


def pair(key: str, dt: float) -> None:
    with _zar:
        v = _parok[key]
        v[0] += dt
        v[1] += 1


def op(name: str, dt: float) -> None:
    with _zar:
        v = _muveletek[name or "?"]
        v[0] += dt
        v[1] += 1


def cpu(dt: float) -> None:
    with _zar:
        _cpu[0] += dt


def report_and_reset(n_cycles: int, work_sum: float, top: int = 5) -> str:
    """Egy naplósor a legutóbbi `n_cycles` körről, és nullázás."""
    with _zar:
        parok = sorted(((v[0] / max(v[1], 1), k) for k, v in _parok.items()), reverse=True)
        muv = sorted(((v[0], v[1], k) for k, v in _muveletek.items()), reverse=True)
        cpu_sum = _cpu[0]
        _parok.clear()
        _muveletek.clear()
        _cpu[0] = 0.0
    n = max(n_cycles, 1)
    resz = [f"munka átl. {work_sum / n:.2f} mp, ebből a szál saját CPU-ja {cpu_sum / n:.2f} mp"]
    if parok:
        resz.append("leglassabb: " + ", ".join(f"{k} {t:.2f}" for t, k in parok[:top]))
    if muv:
        resz.append("felület-kérések: " + ", ".join(f"{k} {c}× {t:.1f} mp" for t, c, k in muv[:top]))
    else:
        resz.append("felület-kérések: nincs")
    return " · ".join(resz)
