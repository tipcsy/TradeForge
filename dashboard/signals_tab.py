"""JELZÉSEK fül — amit a „csak jelzés" módú stratégiák kiküldtek.

A felhasználó kérése (2026-08-29): „ha valamelyik instrumentum jelzésre van
állítva, akkor ne csak MT5-ön jelezzen, hanem legyen egy lapfül, ahol látom,
milyen jelzéseket küldött ki a rendszer, mikor, melyik stratégia — esetleg egy
nyomógomb, hogy kötés."

Eddig a jelzés-módú stratégia jele CSAK az MT5 chartra és a naplóba ment: ha épp
nem ott néztél, elveszett. Az adat viszont már megvolt — a `trades.csv`-ben,
`event="signal"` sorként (`trading.live_trader.log_trade`). Ez a fül azt mutatja
meg; új adatgyűjtésre nem volt szükség.

⚠ A „Kötés" gomb VALÓDI megbízást küld. Négy dolog védi:

  1. A `live_trader.open_position()`-t hívja — UGYANAZT az utat, amit a motor.
     Nincs második kötés-implementáció, ami elcsúszhatna (csúszás-tűrés,
     kitöltési mód, naplózás mind onnan jön).
  2. A stopot és a célárat a jelzéskori TÁVOLSÁGBÓL, a MOSTANI árhoz igazítva
     számolja újra. Egy régi jelzés abszolút stopja ma egészen más kockázatot
     jelentene — a stratégiából a TÁVOLSÁG jön, nem a szint.
  3. ELAVULÁS: a `max_age_hours`-nál (alap 4 óra) régebbi jelzésnél a gomb
     PASSZÍV. Egy fél napja kiadott belépő már nem az a szetup.
  4. Megerősítő ablak, ami mutatja a kort, az ármozgást azóta, és a ténylegesen
     kimenő SL/TP-t — ott a lot is állítható, min_lot lépésekben.

⚠ TÖRLÉS NINCS, szándékosan. A napló AUDITNYOM: abból, hogy egy jelzés kiment,
utólag nem lehet „nem ment ki". Ami zavarna — a régiek —, azt az időszak-szűrő
teszi láthatatlanná, nem a törlés.
"""

from __future__ import annotations

from core.i18n import t as _t, num as _num

import tkinter as tk
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from dashboard import theme as _theme
from dashboard.scroll_area import scrollable
from dashboard.theme import (BG, BG_HEADER, BG_ROW_EVEN, BG_ROW_ODD,
                             BTN_DIS_BG, BTN_DIS_FG, FG_GRAY, FG_GRAY_DIM,
                             FG_GREEN, FG_RED, FG_WHITE, FG_YELLOW)

MAX_SOR = 500            # ennyi legutóbbi jelzésig olvasunk vissza
FRISS_PERC = 15          # ennél régebbi jelzésnél a kor már nem zöld
ALAP_MAX_ORA = 4.0       # ennél régebbi jelzésre nem enged kötni (configból)


def _kor_perc(iso) -> float:
    """A jelzés kora percben. `inf`, ha az időbélyeg értelmezhetetlen."""
    try:
        t = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return float("inf")
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 60.0


class SignalsTab:
    """`csv_path` — a `trades.csv`. A többi seam a hívóé (a fül nem ismer MT5-öt):

    `on_trade(sor, lot) -> (ticket|None, üzenet)` · None → a gomb rejtve
    `price_of(symbol)   -> (bid, ask) | None`
    `digits_of(symbol)  -> int`   az ár tizedesjegyei (Bra50: 2, EURUSD: 5)
    `lot_step_of(symbol)-> (min_lot, lot_step, max_lot)`
    `max_age_hours()    -> float` ennél régebbire nem enged kötni
    `open_of(sym, strat)-> "BUY"|"SELL"|None`  van-e MÁR nyitott pozíció

    ⚠ AZ `open_of` A NYITOTT POZÍCIÓT KÉRDEZI, NEM A GOMBNYOMÁST. A megnyomott
    gomb megjegyzése hamis biztonságot adna: ugyanez a kötés létrejöhet a
    Telegram „Igen" gombjáról, egy másik gépen futó felületről, vagy kézzel az
    MT5-ben — a felület egyikről sem tudna. A megjegyzett gombnyomás ráadásul
    a program újraindításakor elveszne, a pozíció viszont megmarad. Az egyetlen
    megbízható forrás tehát a BRÓKER.
    """

    def __init__(self, parent, csv_path, on_trade=None, price_of=None,
                 digits_of=None, lot_step_of=None, max_age_hours=None,
                 open_of=None):
        self.parent = parent
        self._csv = Path(csv_path)
        self._on_trade = on_trade
        self._price_of = price_of
        self._digits_of = digits_of or (lambda s: 5)
        self._lot_step_of = lot_step_of or (lambda s: (0.01, 0.01, 100.0))
        self._max_age = max_age_hours or (lambda: ALAP_MAX_ORA)
        # ⚠ Alapból NINCS nyitott pozíció: a seam hiánya nem tilthat le gombot.
        self._open_of = open_of or (lambda sym, strat: None)
        self._sorok: list = []          # (sor, lbl_kor, gomb)
        self._mtime = None
        self._build_ui()

    # ── felépítés ─────────────────────────────────────────────────────────
    def _build_ui(self):
        f = _theme.fonts()
        self._mono, self._small, self._header = f["mono"], f["small"], f["header"]
        p = self.parent

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(top, text=_t("signals.title"),
                 bg=BG, fg=FG_WHITE, font=self._header).pack(side="left")
        self._lbl_info = tk.Label(top, text="—", bg=BG, fg=FG_GRAY,
                                  font=self._header)
        self._lbl_info.pack(side="right", padx=8)

        # ── Időszak-választó — ugyanaz a minta, mint a Lezárt fülön ──────
        sel = tk.Frame(p, bg=BG)
        sel.pack(fill="x", padx=10, pady=(0, 4))
        self._range_var = tk.StringVar(value="today")
        for val, txt in (("today", _t("range.today")), ("7", _t("range.7d")),
                         ("30", _t("range.30d")), ("custom", _t("range.custom"))):
            tk.Radiobutton(sel, text=txt, value=val, variable=self._range_var,
                           bg=BG, fg=FG_WHITE, selectcolor=BG_HEADER,
                           activebackground=BG, activeforeground=FG_WHITE,
                           font=self._small,
                           command=self._ujratolt).pack(side="left", padx=(0, 6))
        ma = date.today()
        self._from_var = tk.StringVar(value=str(ma))
        self._to_var = tk.StringVar(value=str(ma))
        for v in (self._from_var, self._to_var):
            tk.Entry(sel, textvariable=v, width=11, bg=BG_HEADER, fg=FG_WHITE,
                     font=self._small, insertbackground=FG_WHITE,
                     relief="flat").pack(side="left", padx=2)
        tk.Button(sel, text=_t("range.load"), bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=self._small, padx=8,
                  command=self._ujratolt).pack(side="left", padx=6)
        self._lbl_hiba = tk.Label(sel, text="", bg=BG, fg=FG_RED,
                                  font=self._small)
        self._lbl_hiba.pack(side="left", padx=6)

        self._oszlopok = [(_t("signals.col.time"), 17), (_t("signals.col.age"), 10),
                          (_t("signals.col.symbol"), 13),
                          (_t("signals.col.strategy"), 20),
                          (_t("signals.col.dir"), 7),
                          (_t("signals.col.price"), 13),
                          ("SL", 13), ("TP", 13), ("Lot", 7), ("", 10)]
        fej = tk.Frame(p, bg=BG_HEADER)
        fej.pack(fill="x", padx=10)
        for cim, w in self._oszlopok:
            tk.Label(fej, text=cim, width=w, anchor="w", bg=BG_HEADER,
                     fg=FG_GRAY, font=self._header).pack(side="left", padx=2)

        holder, self._inner, _ = scrollable(p)
        holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    # ── adat ──────────────────────────────────────────────────────────────
    def _idoszak(self):
        """(tól, ig) dátum, vagy None ha hibás a kézi bevitel."""
        mod = self._range_var.get()
        ma = date.today()
        if mod == "today":
            return ma, ma
        if mod in ("7", "30"):
            return ma - timedelta(days=int(mod) - 1), ma
        try:
            return (date.fromisoformat(self._from_var.get().strip()),
                    date.fromisoformat(self._to_var.get().strip()))
        except ValueError:
            return None

    def _olvas(self) -> list:
        if not self._csv.exists():
            return []
        try:
            d = pd.read_csv(self._csv)
        except Exception:
            return []
        if "event" not in d.columns:
            return []
        d = d[d["event"] == "signal"]
        if d.empty:
            return []
        tart = self._idoszak()
        if tart is None:
            self._lbl_hiba.config(text=_t("range.bad_date"))
            return []
        self._lbl_hiba.config(text="")
        tol, ig = tart
        # A jelzés ideje UTC ISO; a NAPOT abból vesszük (a Lezárt fül a bróker
        # napját használja — itt a naplózás ideje az egyetlen forrás).
        napok = pd.to_datetime(d["time"], errors="coerce", utc=True).dt.date
        d = d[(napok >= tol) & (napok <= ig)]
        return d.tail(MAX_SOR).iloc[::-1].to_dict("records")

    # ── megjelenítés ──────────────────────────────────────────────────────
    def _ujratolt(self):
        self._mtime = None
        self.refresh()

    def refresh(self):
        try:
            mt = self._csv.stat().st_mtime if self._csv.exists() else None
        except OSError:
            mt = None
        # A fájl nem változott → csak a KORT frissítjük (az idő telik), és a
        # gomb elavulhat közben.
        if mt == self._mtime and self._sorok:
            for r, lbl, gomb in self._sorok:
                self._sor_frissit(r, lbl, gomb)
            return
        self._mtime = mt

        for w in self._inner.winfo_children():
            w.destroy()
        self._sorok.clear()
        sorok = self._olvas()

        if not sorok:
            uzenet = _t("signals.empty")
            tk.Label(self._inner, text=uzenet, bg=BG, fg=FG_GRAY_DIM,
                     font=self._small,
                     justify="left").pack(anchor="w", padx=12, pady=20)
            self._lbl_info.config(text=_t("signals.count", n=0))
            return

        self._tulhaladt_jeloles(sorok)
        for i, r in enumerate(sorok):
            self._sor(i, r)
        self._lbl_info.config(text=_t("signals.count", n=len(sorok)))

    @staticmethod
    def _tulhaladt_jeloles(sorok: list) -> None:
        """A pár+stratégia RÉGEBBI jelzéseit lejárttá jelöli.

        ⚠ A KÉRÉS (2026-09-02): „ha látom, hogy két / három kötésünk is van,
        akkor simán az előzőeket is érvényteleníthetjük" — a képen a Ger40 /
        wpr_sma háromszor szerepelt (09:12, 08:39, 08:10). Csak a LEGFRISSEBB
        szetup él: a régebbi másik árra, másik stopra szólt, és a mostani
        árhoz igazítva már egy harmadik kötés lenne belőle.

        ⚠ AZ IRÁNY NEM RÉSZE A KULCSNAK. Ha a friss jelzés az ELLENKEZŐ irányba
        szól, a régi attól még — sőt, még inkább — érvénytelen.

        A lista a legfrissebbel kezdődik (`_olvas` megfordítja), tehát egy
        kulcs ELSŐ előfordulása az élő."""
        latott = set()
        for r in sorok:
            kulcs = (str(r.get("symbol") or ""), str(r.get("strategy") or ""))
            # ⚠ A jelölés a MEGJELENÍTETT másolatra kerül (`to_dict("records")`),
            # nem a naplóba: a `trades.csv` auditnyom, azt nem írjuk át.
            r["_tulhaladt"] = kulcs in latott
            latott.add(kulcs)

    def _kotve(self, r: dict) -> bool:
        """Van-e MÁR nyitott pozíció erre a párra + stratégiára?

        ⚠ AZ IRÁNYT ITT SEM NÉZZÜK. Egy nyitott ellenirányú pozíció mellett a
        gomb ugyanúgy ne legyen aktív: a motor alapból nem nyit ellenirányt
        (`no_opposite`), és egy hedge biztosan nem egy kattintás szándéka."""
        try:
            return bool(self._open_of(str(r.get("symbol") or ""),
                                      str(r.get("strategy") or "")))
        except Exception:
            # ⚠ A LEKÉRDEZÉS HIBÁJA NE ÁLLÍTSON SEMMIT. Ha az MT5-kapcsolat épp
            # elbukik, a „Kötve" felirat AZT állítaná, hogy van pozíciód —
            # holott csak nem tudjuk. A kor és a túlhaladás ilyenkor is véd.
            return False

    def _sor_frissit(self, r, lbl, gomb):
        ido = r.get("time") if isinstance(r, dict) else r
        perc = _kor_perc(ido)
        if perc == float("inf"):
            szoveg, szin = "—", FG_GRAY_DIM
        elif perc < 60:
            szoveg, szin = _t("age.min", n=f"{perc:.0f}"), (
                FG_GREEN if perc <= FRISS_PERC else FG_YELLOW)
        elif perc < 60 * 24:
            szoveg, szin = _t("age.hour", n=_num(f"{perc/60:.1f}")), FG_GRAY_DIM
        else:
            szoveg, szin = _t("age.day", n=f"{perc/1440:.0f}"), FG_GRAY_DIM
        if lbl is not None:
            lbl.config(text=szoveg, fg=szin)
        if gomb is not None:
            # ⚠ A SORREND: a „Kötve" TÖBBET mond, mint a „Lejárt" — ha van
            # pozíció, azt kell látni, akkor is, ha a jelzés közben elévült.
            _sor = r if isinstance(r, dict) else {}
            if self._kotve(_sor):
                felirat, passziv = _t("signals.traded"), True
            elif _sor.get("_tulhaladt") or perc > self._max_age() * 60.0:
                felirat, passziv = _t("signals.expired"), True
            else:
                felirat, passziv = _t("signals.trade"), False
            gomb.config(text=felirat,
                        state="disabled" if passziv else "normal",
                        bg=BTN_DIS_BG if passziv else BG_HEADER,
                        fg=BTN_DIS_FG if passziv else FG_YELLOW)

    def _sor(self, i: int, r: dict):
        bg = BG_ROW_ODD if i % 2 else BG_ROW_EVEN
        keret = tk.Frame(self._inner, bg=bg)
        keret.pack(fill="x")
        ido = str(r.get("time", ""))
        sym = str(r.get("symbol", ""))
        irany = str(r.get("direction", ""))
        dig = self._digits_of(sym)

        cellak = [(ido[:16].replace("T", " "), FG_WHITE),
                  ("", FG_GRAY),                       # a Kor — alább töltjük
                  (sym, FG_WHITE),
                  (str(r.get("strategy", "")), FG_GRAY),
                  (irany, FG_GREEN if irany == "BUY" else FG_RED),
                  (self._ar(r.get("price"), dig), FG_WHITE),
                  (self._ar(r.get("sl"), dig), FG_GRAY),
                  (self._ar(r.get("tp"), dig), FG_GRAY),
                  (self._lot(r.get("lot")), FG_WHITE)]
        lbl_kor = None
        for j, ((szoveg, szin), (_, w)) in enumerate(zip(cellak, self._oszlopok)):
            lbl = tk.Label(keret, text=szoveg, width=w, anchor="w", bg=bg,
                           fg=szin, font=self._mono)
            lbl.pack(side="left", padx=2)
            if j == 1:
                lbl_kor = lbl

        gomb = None
        if self._on_trade is not None:
            gomb = tk.Button(keret, text=_t("signals.trade"), font=self._small,
                             bg=BG_HEADER, fg=FG_YELLOW, relief="flat", padx=8,
                             command=lambda rr=r: self._kotes_ablak(rr))
            gomb.pack(side="left", padx=2)
        self._sor_frissit(r, lbl_kor, gomb)
        self._sorok.append((r, lbl_kor, gomb))

    @staticmethod
    def _ar(v, digits: int) -> str:
        """Ár FIX tizedesjeggyel — sosem tudományos alakban.

        ⚠ A korábbi `:.5g` a Bra50-en `1.7573e+05`-öt adott: a `g` nagy
        számoknál átvált exponenciálisra, és az árlistában olvashatatlan. A
        tizedesek száma az INSTRUMENTUMÉ (Bra50: 2, EURUSD: 5)."""
        try:
            return f"{float(v):.{max(0, int(digits))}f}"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _lot(v) -> str:
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return "—"

    # ── kézi kötés ────────────────────────────────────────────────────────
    def _kotes_ablak(self, r: dict):
        """Megerősítő ablak lot-léptetővel. A `messagebox` nem tud vezérlőt
        befogadni, ezért saját `Toplevel`."""
        from tkinter import messagebox
        sym = str(r.get("symbol", ""))
        irany = str(r.get("direction", ""))
        dig = self._digits_of(sym)
        min_lot, lepes, max_lot = self._lot_step_of(sym)
        try:
            jelzett = float(r.get("price"))
            sl0, tp0 = float(r.get("sl")), float(r.get("tp"))
            lot0 = float(r.get("lot"))
        except (TypeError, ValueError):
            messagebox.showerror(_t("manual.title"), _t("manual.bad_row"),
                                 parent=self.parent)
            return
        most = None
        try:
            most = self._price_of(sym) if self._price_of else None
        except Exception:
            most = None

        w = tk.Toplevel(self.parent)
        w.title(_t("manual.title"))
        w.configure(bg=BG)
        w.transient(self.parent.winfo_toplevel())
        w.resizable(False, False)

        tk.Label(w, text=f"{sym}   {irany}", bg=BG, font=self._header,
                 fg=FG_GREEN if irany == "BUY" else FG_RED).pack(
                     anchor="w", padx=14, pady=(12, 0))
        perc = _kor_perc(r.get("time"))
        tk.Label(w, text=_t("manual.head", strategy=r.get("strategy", ""),
                            min=f"{perc:.0f}"),
                 bg=BG, fg=FG_GRAY, font=self._small).pack(anchor="w", padx=14)

        info = tk.Frame(w, bg=BG)
        info.pack(fill="x", padx=14, pady=8)
        belepo = None
        if most:
            belepo = most[1] if irany == "BUY" else most[0]
            elt = (belepo - jelzett) / jelzett * 100.0 if jelzett else 0.0
            tk.Label(info, text=_t("manual.prices",
                                   signal=_num(f"{jelzett:.{dig}f}"),
                                   now=_num(f"{belepo:.{dig}f}"),
                                   diff=_num(f"{elt:+.2f}")),
                     bg=BG, fg=FG_WHITE, font=self._mono).pack(anchor="w")
        else:
            tk.Label(info, text=_t("manual.no_price"),
                     bg=BG, fg=FG_RED, font=self._small).pack(anchor="w")

        # lot-léptető: min_lot lépésekben
        lotf = tk.Frame(w, bg=BG)
        lotf.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(lotf, text=_t("manual.lot"), bg=BG, fg=FG_WHITE,
                 font=self._small).pack(side="left")
        lot_var = tk.StringVar(value=f"{max(lot0, min_lot):.2f}")
        tk.Spinbox(lotf, from_=min_lot, to=max_lot, increment=lepes,
                   textvariable=lot_var, width=8, font=self._mono,
                   bg=BG_HEADER, fg=FG_WHITE, buttonbackground=BG_HEADER,
                   insertbackground=FG_WHITE,
                   relief="flat").pack(side="left", padx=6)
        tk.Label(lotf, text=_t("manual.lot_step", step=_num(f"{lepes:g}"),
                               min=_num(f"{min_lot:g}")), bg=BG,
                 fg=FG_GRAY_DIM, font=self._small).pack(side="left")

        lbl_terv = tk.Label(w, text="", bg=BG, fg=FG_GRAY, font=self._mono,
                            justify="left")
        lbl_terv.pack(anchor="w", padx=14, pady=(0, 8))

        sl_tav, tp_tav = abs(jelzett - sl0), abs(tp0 - jelzett)

        def _terv(*_a):
            if belepo is None:
                lbl_terv.config(text="")
                return
            if irany == "BUY":
                sl, tp = belepo - sl_tav, belepo + tp_tav
            else:
                sl, tp = belepo + sl_tav, belepo - tp_tav
            lbl_terv.config(text=_t("manual.plan",
                                    sl=_num(f"{sl:.{dig}f}"),
                                    tp=_num(f"{tp:.{dig}f}")))
        lot_var.trace_add("write", _terv)
        _terv()

        gombok = tk.Frame(w, bg=BG)
        gombok.pack(fill="x", padx=14, pady=(0, 12))

        def _kuld():
            try:
                lot = float(lot_var.get())
            except ValueError:
                messagebox.showerror(_t("manual.title"), _t("manual.lot_nan"),
                                     parent=w)
                return
            if lot < min_lot:
                messagebox.showerror(_t("manual.title"),
                                     _t("manual.lot_min",
                                        min=_num(f"{min_lot:g}")), parent=w)
                return
            w.destroy()
            try:
                ticket, uzenet = self._on_trade(r, lot)
            except Exception as ex:
                messagebox.showerror(_t("manual.title"),
                                     _t("manual.failed",
                                        type=type(ex).__name__, error=ex),
                                     parent=self.parent)
                return
            if ticket:
                # ⚠ SIKERNÉL NINCS ABLAK. A felhasználó kérése (2026-09-02):
                # „nem kell külön megnyitva figyelmeztetés ablak. (A kötve
                # státuszból látszik, hogy megnyitva!)" — a gomb felirata a
                # visszajelzés. Ehhez viszont a gombnak AZONNAL át kell
                # váltania: a `_signal_open_of` a pozíció-cache-ből dolgozik,
                # amit egy 5 másodperces szál tölt. A hívó ezért a ticket után
                # frissíti a cache-t, mielőtt visszatér — enélkül a gomb
                # másodpercekig „Kötés" maradna egy MEGNYITOTT pozíció mellett,
                # és ez pont a duplakattintás ablaka lenne.
                pass
            else:
                messagebox.showerror(_t("manual.title"),
                                     uzenet or _t("manual.not_sent"),
                                     parent=self.parent)
            self._ujratolt()

        tk.Button(gombok, text=_t("btn.cancel2"), command=w.destroy, bg=BG_HEADER,
                  fg=FG_WHITE, font=self._small, relief="flat",
                  padx=12).pack(side="right", padx=4)
        tk.Button(gombok, text=_t("manual.send"), command=_kuld, bg=BG_HEADER,
                  fg=FG_YELLOW, font=self._small, relief="flat",
                  padx=12).pack(side="right", padx=4)
        w.grab_set()
