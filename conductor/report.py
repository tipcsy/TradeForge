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


def plan_lines(javaslatok: list) -> list:
    """Az életciklus-létra javaslatai emberi sorokként.

    ⚠ A „NINCS TEENDŐ" IS VÁLASZ, de KÜLÖN blokkban: a kérdés az, hogy MI
    VÁLTOZNA — ha a holdok a javaslatok közé keverednének, egy 60 cellás
    mátrixban a három valódi javaslat elveszne a sorok között.

    ⚠ ÉS KIMONDJUK, HOGY EZ ÁRNYÉK-MÓD. Egy javaslatlista, amiről nem derül ki,
    hogy nem hajtódott végre, rosszabb a semminél: a felhasználó azt hinné, a
    rendszer már lépett."""
    from conductor.proposals import HOLD

    if not javaslatok:
        return [_t("conductor.plan.none")]
    lepes = [p for p in javaslatok if p.action != HOLD]
    hold = [p for p in javaslatok if p.action == HOLD]

    sorok = [_t("conductor.plan.shadow"), ""]
    sorok.append(_t("conductor.plan.head", n=len(lepes)))
    for p in lepes:
        # ⚠ A PÉNZT BEKAPCSOLÓ javaslat MEGJELÖLVE: a terv szerint ez emberi
        # jóváhagyáshoz kötött, autonómia-szinttől függetlenül.
        sorok.append(_t("conductor.plan.row", mark="⚠" if p.needs_human else "•",
                        text=p.text or p.code))
    if hold:
        sorok.append("")
        sorok.append(_t("conductor.plan.hold_head", n=len(hold)))
        for p in hold:
            sorok.append(_t("conductor.plan.row", mark=" ", text=p.text or p.code))
    return sorok


# ---------------------------------------------------------------------------
# NAPI RIPORT — a karmester része az esti összefoglalóban
# ---------------------------------------------------------------------------
# ⚠ MIÉRT NEM KÜLÖN ÜZENET. A napi összefoglaló MÁR MEGY (`notify`,
# `daily_summary_time`), és a `console_cmd.cmd_today` adja a tartalmát. Egy
# MÁSODIK esti üzenet két dolgot rontana el: versenyezne az elsővel a
# figyelmedért, és a két üzenet előbb-utóbb mást mondana ugyanarról a napról —
# ez a projekt visszatérő hibaosztálya. Ezért a karmester SZAKASZOKAT ad a
# meglévő üzenethez, nem új csatornát.
#
# ⚠ ÉS MIÉRT A KRÓNIKÁBÓL OLVAS, nem futtatja újra az egészségőrt. Ha 23:00-kor
# újraszámolna, a MOSTANI állapotot mutatná — ami eltérhet attól, ami napközben
# a krónikába került. Akkor az üzenet és a nyilvántartás MÁST mondana, és
# utólag nem lehetne eldönteni, melyik az igaz. Így a kettő szerkezetileg
# azonos: az üzenet a krónika kivonata.


def daily_lines(cfg: dict, *, strategies_of=None, day=None) -> list:
    """A karmester napi szakaszai: mérés · leletek · árnyék-javaslatok."""
    from conductor import journal as _j
    from conductor import telemetry as _tlm

    nap = _tlm.day_key(day)
    sorok = ["", _t("conductor.daily.head", day=nap)]

    # ── 1. MÉRÉS: jelből mi lett? ────────────────────────────────────────
    cellak = _tlm.load(nap)
    jelek = sum(int((r or {}).get("signals") or 0) for r in cellak.values())
    kotes = sum(int((r or {}).get("entries") or 0) for r in cellak.values())
    if not cellak:
        # ⚠ „Nincs adat" ≠ „nem történt semmi". Ha a motor ma nem futott (vagy
        # most indult), a hiányzó mérést ki kell mondani — különben egy csendes
        # nap és egy álló rendszer ugyanúgy néz ki.
        sorok.append(_t("conductor.daily.no_data"))
    else:
        sorok.append(_t("conductor.daily.telemetry", signals=jelek, entries=kotes,
                        pct=_arany(kotes, jelek)))
        # ⚠ MELY CELLÁK VOLTAK ÉBREN. Hétvégén és ünnepnapon a devizapárok
        # alszanak, a kripto viszont megy — a puszta „3 jel" ilyenkor
        # félrevezető, mert úgy néz ki, mintha az egész rendszer csendes volna.
        # A `core/market_state.py` ugyanezt a leletet írja le a tick korából:
        # egy zárt piacú pár pontosan úgy néz ki, mint egy nyitott, amelyik épp
        # nem talál belépőt.
        _ebren = sorted({c.split("|")[0] for c, r in cellak.items()
                         if int((r or {}).get("signals") or 0) > 0})
        sorok.append(_t("conductor.daily.awake", n=len(_ebren),
                        symbols=", ".join(_ebren) or "-"))
        akadalyok = {}
        for r in cellak.values():
            for k, v in ((r or {}).get("outcomes") or {}).items():
                if k in _tlm.BLOCKERS:
                    akadalyok[k] = akadalyok.get(k, 0) + int(v or 0)
        for kod, db in sorted(akadalyok.items(), key=lambda x: (-x[1], x[0]))[:3]:
            sorok.append(_t("conductor.daily.blocker", n=db,
                            pct=_arany(db, jelek),
                            reason=(_tlm.LABELS[kod] if kod in _tlm.LABELS else kod)))
        # ⚠ A NÉMA CELLÁK KÜLÖN: az a cella érdekes, amelyik JELZETT, de egyszer
        # sem kötött — ott van mit megnézni holnap.
        _nemak = sorted(c for c, r in cellak.items()
                        if int((r or {}).get("signals") or 0) > 0
                        and not int((r or {}).get("entries") or 0))
        if _nemak:
            sorok.append(_t("conductor.daily.no_entry",
                            cells=", ".join(x.replace("|", "/") for x in _nemak)))

    # ── 2. LELETEK (a krónikából: amit MA látott) ────────────────────────
    _lel = _j.read(limit=200, kind=_j.KIND_HEALTH, since_day=nap)
    if _lel:
        sorok.append("")
        sorok.append(_t("conductor.daily.health_head", n=len(_lel)))
        for e in _lel[:8]:
            sorok.append(_t("conductor.health.row",
                            sev=(e.get("sev") or "?").upper(), text=_cimzett(e)))
        if len(_lel) > 8:
            sorok.append(_t("conductor.daily.more", n=len(_lel) - 8))
    else:
        sorok.append(_t("conductor.daily.health_none"))

    # ── 3. ÁRNYÉK-JAVASLATOK ────────────────────────────────────────────
    _sh = _j.read(limit=100, kind=_j.KIND_SHADOW, since_day=nap)
    if _sh:
        sorok.append("")
        sorok.append(_t("conductor.daily.shadow_head", n=len(_sh)))
        for e in _sh[:8]:
            _human = bool((e.get("data") or {}).get("needs_human"))
            sorok.append(_t("conductor.plan.row", mark="⚠" if _human else "•",
                            text=e.get("text") or e.get("code") or ""))
        if len(_sh) > 8:
            sorok.append(_t("conductor.daily.more", n=len(_sh) - 8))
    return sorok
