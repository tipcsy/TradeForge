"""BRÓKEREK fül — a többi bróker motorja: állapot ÉS vezérlés.

⚠ 0029 „Több bróker egyszerre". Minden további bróker külön processzben fut
(`python main.py console --broker <id>`).
  • 4a (v3.112.0): a fül OLVASTA a motor állapotképét (`core/engine_status`):
    életjel (fut / áll / hibás / nincs adat), SZERVER-óra, egyenleg, napi P&L,
    nyitott pozíciók.
  • 4b (v3.113.0): VEZÉRLÉS a `core/engine_channel` postaládáján át — pár/
    stratégia Play/Stop, pozíció-zárás, a motor leállítása.

⚠ A SZABÁLYOK A KÖZÖS PARANCS-RÉTEGBEN. A gomb egy parancssort küld
(`play GOLD wpr_sma`, `close 12345`, `quit`) — ugyanazt, amit a konzolba írnál.
Ha a parancs rákérdez (zárás, kivezetés), a kérdést a MOTOR adja vissza, a fül
megmutatja, és csak igen esetén küldi újra megerősítve. A fül maga semmit nem
dönt el — így nem is csúszhat el a konzoltól/Telegramtól.

⚠ A PARANCS HÁTTÉRSZÁLON MEGY: egy nem válaszoló motor nem fagyaszthatja be a
felületet. A válasz (vagy a „nem válaszolt") az állapotsorba kerül.

⚠ A fül csak akkor jön létre, ha egynél több bróker-profil van.
A fül NEM ismer MT5-öt: a profilokat, a képeket és a csatornát a modulok adják.
"""
from __future__ import annotations

import time
import tkinter as tk

from core import engine_channel as CH
from core import engine_status as ES
from core.i18n import t as _t
from dashboard import theme as _theme
from dashboard.scroll_area import scrollable
from dashboard.theme import (BG, BG_HEADER, BG_ROW_EVEN, BG_ROW_ODD, FG_GRAY,
                             FG_GREEN, FG_RED, FG_WHITE, FG_YELLOW)

FRISSITES_MS = 2000
FELUGYELO_MS = 30000                 # az autostart-figyelés köre

_ALLAPOT_SZIN = {ES.FUT: FG_GREEN, ES.ALL: FG_GRAY, ES.HIBAS: FG_RED,
                 ES.NINCS: FG_YELLOW}


def _penz(v, cur=""):
    try:
        return f"{float(v):+,.2f} {cur}".strip()
    except (TypeError, ValueError):
        return "—"


def rows(profiles, now=None, reader=ES.read) -> list:
    """A fül adat-sorai (a teszt ezt nézi, a felület ezt rajzolja).
    `[{profile, tag, name, account, health, clock, balance, daily, n_pos, age,
       positions, pairs}]`"""
    now = time.time() if now is None else now
    out = []
    for p in profiles:
        snap = reader(p)
        acc = (snap or {}).get("account") or {}
        cur = acc.get("currency", "")
        clock = ES.server_clock(snap, now)
        poz = (snap or {}).get("positions") or []
        out.append({
            "profile": p, "tag": p.tag, "name": p.name,
            "account": f"#{p.login} {p.server}".strip(),
            "health": ES.health(snap, now),
            "clock": clock.strftime("%H:%M") if clock else "—",
            "balance": (f"{float(acc['balance']):,.2f} {cur}".strip()
                        if acc.get("balance") is not None else "—"),
            "daily": _penz(acc.get("daily_pnl"), cur) if acc.get("daily_pnl") is not None else "—",
            "n_pos": len(poz),
            "age": (_t("age.sec", n=f"{max(0.0, now - float(snap['ts'])):.0f}")
                    if snap and snap.get("ts") else "—"),
            "positions": [dict(x, tag=p.tag) for x in poz],
            "pairs": [dict(x, tag=p.tag) for x in ((snap or {}).get("pairs") or [])],
        })
    return out


def structure_signature(adat) -> tuple:
    """A Brókerek fül SZERKEZETE: minden, ami újraépítést igényel — az
    időfüggő értékek (óra, életjel kora, pozíció P&L) NÉLKÜL. Ha ez nem
    változott, a fül helyben frissít (nem villog)."""
    out = []
    for r in adat or []:
        out.append((
            r.get("tag"), r.get("name"), r.get("account"), r.get("health"), r.get("proc"),
            r.get("balance"), r.get("daily"), r.get("n_pos"),
            tuple((p.get("symbol"), p.get("state"),
                   tuple(tuple(s) for s in (p.get("strategies") or [])))
                  for p in (r.get("pairs") or [])),
            tuple((x.get("ticket"), x.get("symbol"), x.get("type"), x.get("volume"),
                   x.get("price_open"), x.get("sl"), x.get("tp"))
                  for x in (r.get("positions") or []))))
    return tuple(out)


def toggle_line(symbol: str, strategy: str, running: bool) -> str:
    """A Play/Stop gomb parancssora — ugyanaz, amit a konzolba írnál."""
    return f"{'stop' if running else 'play'} {symbol} {strategy}"


class BrokersTab:
    """`profiles_provider() -> [BrokerProfile]` — a MÁSIK (nem-otthoni) brókerek.
    `confirm(szöveg) -> bool` — a felület IGEN/NEM kérdése (tesztben cserélhető).
    `request(profil, sor, megerősítve) -> dict|None` — a csatorna (tesztben
    cserélhető; alapból `core.engine_channel.request`)."""

    def __init__(self, parent, profiles_provider, confirm=None, request=None,
                 starter=None, supervisor=None, running=None):
        self.parent = parent
        self._profiles = profiles_provider
        self._confirm = confirm or (lambda szoveg: False)
        self._request = request or CH.request
        from core import engine_supervisor as SV
        self._starter = starter or SV.start
        # `running(profile) -> bool`: él-e a motor processze (a futás-zár) —
        # beadható, hogy a fül hamis képpel, valódi zár nélkül is tesztelhető
        self._running = running or SV.running
        self._supervisor = supervisor or SV.Supervisor()
        # Az utolsó JÓ kép brókerenként: egy átmeneti olvasási hiba (a motor épp
        # cseréli a fájlt) ne villantsa „nincs adat"-ra a sort. Nem hazudik: az
        # életjel KORA tovább nő, és egy tartós hiba így is „hibás"-ra vált.
        self._utolso: dict = {}
        self._build_ui()
        # A háttérszálak válaszai a FŐSZÁLON — a közös segéddel (dashboard/remote_cmd).
        from dashboard import remote_cmd as _rc
        self._pump = _rc.Pump(self.parent)
        self._frissit()
        self.parent.after(FELUGYELO_MS, self._felugyel)

    # ── felépítés ─────────────────────────────────────────────────────────
    def _build_ui(self):
        f = _theme.fonts()
        self._mono, self._small, self._header = f["mono"], f["small"], f["header"]
        p = self.parent
        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(top, text=_t("brokers.title"), bg=BG, fg=FG_WHITE,
                 font=self._header).pack(side="left")
        self._lbl_statusz = tk.Label(top, text="", bg=BG, fg=FG_GRAY,
                                     font=self._small, anchor="e")
        self._lbl_statusz.pack(side="right", padx=8)
        tk.Label(p, text=_t("brokers.howto"), bg=BG, fg=FG_GRAY,
                 font=self._small, anchor="w", justify="left").pack(
                     fill="x", padx=10, pady=(0, 6))

        self._fo_oszlop = [(_t("brokers.col.tag"), 5), (_t("brokers.col.broker"), 14),
                           (_t("brokers.col.account"), 24), (_t("brokers.col.state"), 12),
                           (_t("brokers.col.clock"), 9), (_t("brokers.col.balance"), 15),
                           (_t("brokers.col.daily"), 13), (_t("brokers.col.npos"), 5),
                           (_t("brokers.col.age"), 9)]
        self._fo = self._tabla(p, self._fo_oszlop, expand=False, gomb=True)

        tk.Label(p, text=_t("brokers.pairs"), bg=BG, fg=FG_WHITE,
                 font=self._header, anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        self._par_oszlop = [(_t("brokers.col.tag"), 5), (_t("brokers.col.symbol"), 12),
                            (_t("brokers.col.pairstate"), 12)]
        self._par = self._tabla(p, self._par_oszlop, expand=False, gomb=True)

        tk.Label(p, text=_t("brokers.positions"), bg=BG, fg=FG_WHITE,
                 font=self._header, anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        self._poz_oszlop = [(_t("brokers.col.tag"), 5), ("Ticket", 11),
                            (_t("brokers.col.symbol"), 12),
                            (_t("brokers.col.dir"), 6), ("Lot", 7),
                            (_t("brokers.col.open"), 12), ("SL", 12), ("TP", 12),
                            (_t("brokers.col.pnl"), 12)]
        self._poz = self._tabla(p, self._poz_oszlop, expand=True, gomb=True)

    def _tabla(self, p, oszlopok, expand, gomb=False):
        fej = tk.Frame(p, bg=BG_HEADER)
        fej.pack(fill="x", padx=10)
        for cim, w in oszlopok:
            tk.Label(fej, text=cim, width=w, anchor="w", bg=BG_HEADER, fg=FG_GRAY,
                     font=self._header).pack(side="left", padx=2)
        if expand:
            holder, inner, _ = scrollable(p)
            holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))
            return inner
        inner = tk.Frame(p, bg=BG)
        inner.pack(fill="x", padx=10)
        return inner

    def _sor(self, hova, i, cellak):
        bg = BG_ROW_EVEN if i % 2 == 0 else BG_ROW_ODD
        r = tk.Frame(hova, bg=bg)
        r.pack(fill="x")
        for szoveg, w, szin in cellak:
            tk.Label(r, text=szoveg, width=w, anchor="w", bg=bg, fg=szin,
                     font=self._mono).pack(side="left", padx=2)
        return r, bg

    def _gomb(self, sor, bg, szoveg, parancs, szin=FG_WHITE, aktiv=True):
        b = tk.Button(sor, text=szoveg, bg=BG_HEADER, fg=szin, relief="flat",
                      font=self._small, padx=6, command=parancs,
                      state=("normal" if aktiv else "disabled"))
        b.pack(side="left", padx=3)
        return b

    # ── parancs (háttérszálon) ────────────────────────────────────────────
    def _statusz(self, szoveg, szin=FG_GRAY):
        try:
            self._lbl_statusz.config(text=szoveg, fg=szin)
        except tk.TclError:
            pass

    def send(self, profile, line):
        """Egy parancs a bróker motorjának, a kétlépcsős megerősítéssel
        (a KÖZÖS segéden át: dashboard/remote_cmd). Azonnal visszatér; az
        eredmény az állapotsorba kerül."""
        from dashboard import remote_cmd as _rc
        self._statusz(_t("brokers.cmd.sending", tag=profile.tag, line=line))

        def _eredmeny(r, megszakitva):
            if r is None:
                self._statusz(_t("brokers.cmd.no_answer", tag=profile.tag), FG_RED)
            elif megszakitva:
                self._statusz(_t("brokers.cmd.cancelled"), FG_GRAY)
            else:
                szoveg = " ".join(str(x) for x in (r.get("lines") or [])) or "OK"
                self._statusz(f"{profile.tag}: {szoveg}",
                              FG_GREEN if r.get("ok") else FG_RED)

        _rc.send(self._pump, profile, line, confirm=self._confirm,
                 on_result=_eredmeny, request=self._request)

    # ── frissítés ─────────────────────────────────────────────────────────
    def _helyben(self, adat) -> None:
        """Az időfüggő cellák helyben: a fő tábla órája (4.) és kora (8.), a
        pozíciók P&L-je (8.). A `_sor` a címkéket a gombok ELŐTT hozza létre,
        tehát a `winfo_children()` első elemei a címkék."""
        fo = self._fo.winfo_children()
        poz = self._poz.winfo_children()
        k_poz = 0
        for i, r in enumerate(adat):
            if i < len(fo):
                cimkek = [w for w in fo[i].winfo_children() if isinstance(w, tk.Label)]
                for idx, v in ((4, r["clock"]), (8, r["age"])):
                    if idx < len(cimkek) and cimkek[idx].cget("text") != str(v):
                        cimkek[idx].config(text=str(v))
            for x in r["positions"]:
                if k_poz < len(poz):
                    cimkek = [w for w in poz[k_poz].winfo_children()
                              if isinstance(w, tk.Label)]
                    pnl = x.get("profit")
                    if len(cimkek) > 8:
                        try:
                            szin = FG_GREEN if float(pnl) >= 0 else FG_RED
                        except (TypeError, ValueError):
                            szin = FG_WHITE
                        cimkek[8].config(text=_penz(pnl), fg=szin)
                k_poz += 1

    def _frissit(self):
        def _olvas(p):
            snap = ES.read(p)
            if snap is None and ES.path(p).exists():
                return self._utolso.get(p.id)
            self._utolso[p.id] = snap
            return snap
        try:
            adat = rows(self._profiles(), reader=_olvas)
        except Exception:
            adat = []
        # ⚠ VILLOGÁS (Tibi, 2026-09-30: „törli és újratölti"): eddig 2 mp-enként
        # MINDEN sort újraépítettünk, akkor is, ha csak az óra és az életjel kora
        # változott. Most csak SZERKEZETI változásnál; egyébként helyben írjuk át
        # az időfüggő cellákat.
        # ⚠ 2026-09-30: a leállított motor nem írta ki a záró képét → „hibás"
        # maradt, és a gomb „Motor leállítása" (tiltva) → ÚJRAINDÍTANI SEM
        # lehetett. A processz életét a futás-zár mondja meg (MÉRT adat).
        for r in adat:
            try:
                r["proc"] = bool(self._running(r["profile"]))
            except Exception:
                r["proc"] = r["health"] == ES.FUT
            # a halott processz utolsó képe még „fut"-ot mondhat (30 mp-ig nem
            # elavult) — az Állapot és a gomb ne mondjon ellent egymásnak
            if not r["proc"] and r["health"] in (ES.FUT, ES.HIBAS):
                r["health"] = ES.ALL
        alairas = structure_signature(adat)
        if alairas == getattr(self, "_alairas", None):
            try:
                self._helyben(adat)
                self.parent.after(FRISSITES_MS, self._frissit)
            except tk.TclError:
                pass
            return
        self._alairas = alairas
        for w in (list(self._fo.winfo_children()) + list(self._par.winfo_children())
                  + list(self._poz.winfo_children())):
            w.destroy()
        k_par = k_poz = 0
        for i, r in enumerate(adat):
            prof = r["profile"]
            fut = r["health"] == ES.FUT
            ertek = (r["tag"], r["name"], r["account"],
                     _t(f"brokers.state.{r['health']}"), r["clock"], r["balance"],
                     r["daily"], str(r["n_pos"]), r["age"])
            szinek = [FG_WHITE] * len(ertek)
            szinek[3] = _ALLAPOT_SZIN.get(r["health"], FG_GRAY)
            sor, bg = self._sor(self._fo, i, [(v, w, c) for v, (_, w), c
                                             in zip(ertek, self._fo_oszlop, szinek)])
            if r["health"] in (ES.FUT, ES.HIBAS) and r.get("proc", True):
                self._gomb(sor, bg, _t("brokers.btn.quit"),
                           lambda p=prof: self._leallit(p), FG_RED, aktiv=fut)
            else:
                self._gomb(sor, bg, _t("brokers.btn.start"),
                           lambda p=prof: self._indit(p), FG_GREEN)

            for par in r["pairs"]:
                sor, bg = self._sor(self._par, k_par, [
                    (par["tag"], 5, FG_WHITE), (str(par.get("symbol", "")), 12, FG_WHITE),
                    (str(par.get("state", "")), 12, FG_GRAY)])
                for nev, elo in (par.get("strategies") or []):
                    self._gomb(sor, bg, f"{nev} {'■' if elo else '▶'}",
                               lambda p=prof, s=par["symbol"], n=nev, e=elo:
                               self.send(p, toggle_line(s, n, e)),
                               FG_GREEN if elo else FG_GRAY, aktiv=fut)
                k_par += 1

            for x in r["positions"]:
                pnl = x.get("profit")
                ertek = (x["tag"], str(x.get("ticket", "")), str(x.get("symbol", "")),
                         str(x.get("type", "")), f"{x.get('volume', '')}",
                         f"{x.get('price_open', '')}", f"{x.get('sl', '')}",
                         f"{x.get('tp', '')}", _penz(pnl))
                szinek = [FG_WHITE] * len(ertek)
                try:
                    szinek[8] = FG_GREEN if float(pnl) >= 0 else FG_RED
                except (TypeError, ValueError):
                    pass
                sor, bg = self._sor(self._poz, k_poz, [(v, w, c) for v, (_, w), c
                                                       in zip(ertek, self._poz_oszlop, szinek)])
                self._gomb(sor, bg, _t("brokers.btn.close"),
                           lambda p=prof, t=x.get("ticket"): self.send(p, f"close {t}"),
                           FG_RED, aktiv=fut)
                k_poz += 1
        try:
            self.parent.after(FRISSITES_MS, self._frissit)
        except tk.TclError:
            pass                                  # az ablak bezárult

    def _indit(self, profile):
        """A motor indítása leválasztott processzként (core/engine_supervisor).
        A dupla indítást a számla futás-zára akadályozza meg."""
        try:
            ok, kulcs = self._starter(profile)
        except Exception as ex:
            self._statusz(_t("brokers.start.failed", tag=profile.tag, error=ex), FG_RED)
            return
        self._statusz(_t(f"brokers.start.{kulcs}", tag=profile.tag),
                      FG_GREEN if ok else FG_YELLOW)

    def _felugyel(self):
        """Az `autostart` profilok figyelése (a felügyelő szabályaival)."""
        try:
            for azon, esemeny in self._supervisor.tick(
                    self._profiles(), autostart_of=lambda p: p.autostart):
                self._statusz(_t(f"brokers.sv.{esemeny}", id=azon),
                              FG_YELLOW if esemeny == "restarted" else FG_RED)
        except Exception:
            pass
        try:
            self.parent.after(FELUGYELO_MS, self._felugyel)
        except tk.TclError:
            pass

    def _leallit(self, profile):
        """A motor leállítása — a felület MAGA kérdez rá (a `quit` parancs a
        konzolon sem kérdez, de a felületen egy félrekattintás ne állítson le
        egy kereskedő motort)."""
        if self._confirm(_t("brokers.confirm_quit", name=profile.name)):
            self.send(profile, "quit")
