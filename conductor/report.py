"""JELENTÉSEK — a mérésből EMBERI mondat.

Az F0 egyetlen jelentése: **„miért nem kötött?"** Ez az a kérdés, amire a
rendszer eddig nem tudott válaszolni, és amit napi szinten felteszel.

⚠ A JELENTÉS NEM SZÁMOL ÚJRA SEMMIT. A számok a `conductor.snapshot`-ból jönnek;
itt csak sorrend és megfogalmazás van. Egy külön „kijelző-számítás" az első
config-változásnál elcsúszna az igazitól, és a felület MAGABIZTOSAN hazudna —
ugyanez az indoklás áll a `core/opt_plan.py` elején is.

⚠ ÉS MEGMONDJA, HA NINCS MIT MONDANI. A leggyakoribb válasz az lesz, hogy „nem
volt jel" — ez NEM hiba és nem hiányzó adat, hanem a valódi ok. A „nincs adat"
és a „nem történt semmi" összemosása pontosan az a néma állapot, ami miatt ez a
mérés egyáltalán elkészült.
"""

from __future__ import annotations

from core.i18n import t as _t
from conductor import telemetry as _tlm


def _arany(resz: int, egesz: int) -> str:
    return f"{(100.0 * resz / egesz):.0f}%" if egesz else "-"


def why_lines(snap: dict) -> list:
    """„Miért nem kötött ma?" — sorok EGY cellára (a `snapshot.cell` kimenetéből)."""
    sym, strat = snap.get("symbol"), snap.get("strategy")
    t = snap.get("today") or {}
    jelek = int(t.get("signals") or 0)
    kotes = int(t.get("entries") or 0)
    sorok = [_t("conductor.why.head", symbol=sym, strategy=strat)]

    # ── ÁLLAPOT: fut-e egyáltalán? ───────────────────────────────────────
    # ⚠ EZ AZ ELSŐ KÉRDÉS. Egy leállított vagy nem engedélyezett cellánál minden
    # további magyarázat félrevezetne: nem a kapuk miatt nem kötött.
    if snap.get("enabled") is False:
        sorok.append(_t("conductor.why.not_enabled"))
    elif snap.get("intent") != "live":
        sorok.append(_t("conductor.why.stopped"))
    elif snap.get("mode") == "signal":
        sorok.append(_t("conductor.why.signal_mode"))

    if not jelek:
        # ⚠ „Nem volt jel" ≠ „nincs adat". Kimondjuk, és hozzátesszük, mihez
        # képest kevés — ha van mentett várakozás.
        sorok.append(_t("conductor.why.no_signal"))
        sorok += _aktivitas_sorok(snap)
        return sorok

    sorok.append(_t("conductor.why.signals", n=jelek, entries=kotes,
                    pct=_arany(kotes, jelek)))
    # ⚠ A MÁR BEOLVASOTT pillanatképből rendezünk, nem olvassuk újra a fájlt: a
    # jelentés és a pillanatkép ugyanazt a napot kell mutassa.
    _akadalyok = sorted(((k, v) for k, v in (t.get("outcomes") or {}).items()
                         if k in _tlm.BLOCKERS and v),
                        key=lambda x: (-x[1], x[0]))
    for kod, db in _akadalyok:
        sorok.append(_t("conductor.why.blocker", n=db, pct=_arany(db, jelek),
                        reason=_tlm.LABELS[kod] if kod in _tlm.LABELS else kod))
    # A KAPUK nevesítve: a „belépő-kapu blokkolt" önmagában nem cselekvőképes.
    kapuk = sorted(((k, v) for k, v in (t.get("gates_blocked") or {}).items() if v),
                   key=lambda x: (-x[1], x[0]))
    if kapuk:
        sorok.append(_t("conductor.why.gates",
                        list=", ".join(f"{k} ({v})" for k, v in kapuk)))
    sorok += _aktivitas_sorok(snap)
    return sorok


def _aktivitas_sorok(snap: dict) -> list:
    """Az ÉLŐ ↔ VÁRT összevetés — csak akkor, ha van mihez mérni.

    ⚠ ARÁNYOKON, SOSEM PÉNZBEN: a backtest méretezése az AKKORI egyenlegé volt
    (lásd `conductor/expectation.py`)."""
    d = snap.get("divergence") or {}
    v = snap.get("expected") or {}
    e = snap.get("live") or {}
    ki = []
    ar = d.get("activity_ratio")
    if ar is not None:
        ki.append(_t("conductor.why.activity",
                     live=f"{e.get('trades_per_day') or 0:.2f}",
                     expected=f"{v.get('trades_per_day') or 0:.2f}",
                     pct=f"{ar * 100:.0f}%"))
    elif v.get("source") != "saved":
        # ⚠ Enélkül az „elszáradt-e?" kérdés megválaszolhatatlan — és ezt jobb
        # kimondani, mint csendben kihagyni a sort.
        ki.append(_t("conductor.why.no_expectation"))
    n = int(e.get("trades") or 0)
    if n:
        ki.append(_t("conductor.why.live",
                     n=n, days=int(snap.get("window_days") or 0),
                     pf=("-" if e.get("profit_factor") is None
                         else f"{e['profit_factor']:.2f}"),
                     net=f"{e.get('net') or 0:+.2f}"))
        if not d.get("enough"):
            # ⚠ A KIS MINTA FIGYELMEZTETÉSE KÖTELEZŐ: a `core/quality.py` mérése
            # szerint 15 kötésen a minták 4,5%-a PF>3-at mutat egy 1,10-es
            # stratégián. Egy szám indoklás nélkül itt többet árt, mint használ.
            ki.append(_t("conductor.why.thin", n=n))
    return ki


def health_lines(leletek: list) -> list:
    """Az egészségőr leletei emberi sorokként, súlyosság szerint.

    ⚠ A „NINCS LELET" NEM „MINDEN RENDBEN". A frissesség-ellenőrzés MT5-kapcsolat
    nélkül a saját szerződése szerint ÜRES listát ad, és az üres lista
    megkülönböztethetetlen a „minden friss"-től. Ezt a jelentés kimondja —
    különben egy zöld pipa takarná el, hogy senki nem nézett oda."""
    if not leletek:
        return [_t("conductor.health.none")]
    sorok = [_t("conductor.health.head", n=len(leletek))]
    for f in leletek:
        sorok.append(_t("conductor.health.row", sev=(f.get("sev") or "?").upper(),
                        text=_cimzett(f)))
    return sorok


def _cimzett(f: dict) -> str:
    """A lelet szövege a CELLA megnevezésével.

    ⚠ MIÉRT KELL. A `core/overview.py` leletei cella-szintűek, de a szövegük nem
    nevezi meg a cellát — a felületen ez rendben van (a sor mellett áll), egy
    listában viszont a „Az optimalizálás 201 napja futott." önmagában
    használhatatlan: nem derül ki, MELYIKÉ. Ha a szöveg már tartalmazza a
    szimbólumot (a saját leleteink így írják), nem ismételjük meg."""
    szoveg = f.get("text") or f.get("code") or ""
    sym, strat = f.get("symbol"), f.get("strategy")
    if not sym or sym in szoveg:
        return szoveg
    return f"{sym}/{strat}: {szoveg}" if strat else f"{sym}: {szoveg}"
