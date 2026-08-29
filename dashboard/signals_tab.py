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
    """

    def __init__(self, parent, csv_path, on_trade=None, price_of=None,
                 digits_of=None, lot_step_of=None, max_age_hours=None):
        self.parent = parent
        self._csv = Path(csv_path)
        self._on_trade = on_trade
        self._price_of = price_of
        self._digits_of = digits_of or (lambda s: 5)
        self._lot_step_of = lot_step_of or (lambda s: (0.01, 0.01, 100.0))
        self._max_age = max_age_hours or (lambda: ALAP_MAX_ORA)
        self._sorok: list = []          # (kulcs_ido, lbl_kor, gomb)
        self._mtime = None
        self._build_ui()

    # ── felépítés ─────────────────────────────────────────────────────────
    def _build_ui(self):
        f = _theme.fonts()
        self._mono, self._small, self._header = f["mono"], f["small"], f["header"]
        p = self.parent

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(top, text="Kiküldött jelzések  (a „csak jelzés” módú "
                           "stratégiáktól)",
                 bg=BG, fg=FG_WHITE, font=self._header).pack(side="left")
        self._lbl_info = tk.Label(top, text="—", bg=BG, fg=FG_GRAY,
                                  font=self._header)
        self._lbl_info.pack(side="right", padx=8)

        # ── Időszak-választó — ugyanaz a minta, mint a Lezárt fülön ──────
        sel = tk.Frame(p, bg=BG)
        sel.pack(fill="x", padx=10, pady=(0, 4))
        self._range_var = tk.StringVar(value="today")
        for val, txt in (("today", "Ma"), ("7", "7 nap"), ("30", "30 nap"),
                         ("custom", "Tól–ig:")):
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
        tk.Button(sel, text="Betölt", bg=BG_HEADER, fg=FG_WHITE, relief="flat",
                  font=self._small, padx=8,
                  command=self._ujratolt).pack(side="left", padx=6)
        self._lbl_hiba = tk.Label(sel, text="", bg=BG, fg=FG_RED,
                                  font=self._small)
        self._lbl_hiba.pack(side="left", padx=6)

        self._oszlopok = [("Idő", 17), ("Kor", 10), ("Instrumentum", 13),
                          ("Stratégia", 20), ("Irány", 7), ("Jelzett ár", 13),
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
            self._lbl_hiba.config(text="hibás dátum (ÉÉÉÉ-HH-NN)")
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
            for ido, lbl, gomb in self._sorok:
                self._kor_frissit(ido, lbl, gomb)
            return
        self._mtime = mt

        for w in self._inner.winfo_children():
            w.destroy()
        self._sorok.clear()
        sorok = self._olvas()

        if not sorok:
            uzenet = ("Ebben az időszakban nincs jelzés.\n\n"
                      "A „csak jelzés” módú stratégiák jelei jelennek meg itt — "
                      "a kötés-módúak a Pozíciók fülön.")
            tk.Label(self._inner, text=uzenet, bg=BG, fg=FG_GRAY_DIM,
                     font=self._small,
                     justify="left").pack(anchor="w", padx=12, pady=20)
            self._lbl_info.config(text="0 jelzés")
            return

        for i, r in enumerate(sorok):
            self._sor(i, r)
        self._lbl_info.config(text=f"{len(sorok)} jelzés")

    def _kor_frissit(self, ido, lbl, gomb):
        perc = _kor_perc(ido)
        if perc == float("inf"):
            szoveg, szin = "—", FG_GRAY_DIM
        elif perc < 60:
            szoveg, szin = f"{perc:.0f} perce", (
                FG_GREEN if perc <= FRISS_PERC else FG_YELLOW)
        elif perc < 60 * 24:
            szoveg, szin = f"{perc/60:.1f} órája", FG_GRAY_DIM
        else:
            szoveg, szin = f"{perc/1440:.0f} napja", FG_GRAY_DIM
        if lbl is not None:
            lbl.config(text=szoveg, fg=szin)
        if gomb is not None:
            elavult = perc > self._max_age() * 60.0
            gomb.config(state="disabled" if elavult else "normal",
                        bg=BTN_DIS_BG if elavult else BG_HEADER,
                        fg=BTN_DIS_FG if elavult else FG_YELLOW)

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
            gomb = tk.Button(keret, text="Kötés", font=self._small,
                             bg=BG_HEADER, fg=FG_YELLOW, relief="flat", padx=8,
                             command=lambda rr=r: self._kotes_ablak(rr))
            gomb.pack(side="left", padx=2)
        self._kor_frissit(ido, lbl_kor, gomb)
        self._sorok.append((ido, lbl_kor, gomb))

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
            messagebox.showerror("Kézi kötés",
                                 "A jelzés-sor ára / SL / TP / lot nem szám.",
                                 parent=self.parent)
            return
        most = None
        try:
            most = self._price_of(sym) if self._price_of else None
        except Exception:
            most = None

        w = tk.Toplevel(self.parent)
        w.title("Kézi kötés")
        w.configure(bg=BG)
        w.transient(self.parent.winfo_toplevel())
        w.resizable(False, False)

        tk.Label(w, text=f"{sym}   {irany}", bg=BG, font=self._header,
                 fg=FG_GREEN if irany == "BUY" else FG_RED).pack(
                     anchor="w", padx=14, pady=(12, 0))
        perc = _kor_perc(r.get("time"))
        tk.Label(w, text=f"{r.get('strategy','')}  ·  a jelzés "
                         f"{perc:.0f} perce érkezett",
                 bg=BG, fg=FG_GRAY, font=self._small).pack(anchor="w", padx=14)

        info = tk.Frame(w, bg=BG)
        info.pack(fill="x", padx=14, pady=8)
        belepo = None
        if most:
            belepo = most[1] if irany == "BUY" else most[0]
            elt = (belepo - jelzett) / jelzett * 100.0 if jelzett else 0.0
            tk.Label(info, text=f"jelzéskor: {jelzett:.{dig}f}      "
                                f"most: {belepo:.{dig}f}   ({elt:+.2f}%)",
                     bg=BG, fg=FG_WHITE, font=self._mono).pack(anchor="w")
        else:
            tk.Label(info, text="A mostani ár nem elérhető (MT5 kapcsolat?).",
                     bg=BG, fg=FG_RED, font=self._small).pack(anchor="w")

        # lot-léptető: min_lot lépésekben
        lotf = tk.Frame(w, bg=BG)
        lotf.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(lotf, text="Lot:", bg=BG, fg=FG_WHITE,
                 font=self._small).pack(side="left")
        lot_var = tk.StringVar(value=f"{max(lot0, min_lot):.2f}")
        tk.Spinbox(lotf, from_=min_lot, to=max_lot, increment=lepes,
                   textvariable=lot_var, width=8, font=self._mono,
                   bg=BG_HEADER, fg=FG_WHITE, buttonbackground=BG_HEADER,
                   insertbackground=FG_WHITE,
                   relief="flat").pack(side="left", padx=6)
        tk.Label(lotf, text=f"(lépés {lepes:g}, min {min_lot:g})", bg=BG,
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
            lbl_terv.config(
                text=f"kimenő SL: {sl:.{dig}f}      TP: {tp:.{dig}f}\n"
                     f"(a jelzéskori TÁVOLSÁGOK a mostani árhoz igazítva —\n"
                     f" így az 1 R ugyanaz marad, mint amit a jel tervezett)")
        lot_var.trace_add("write", _terv)
        _terv()

        gombok = tk.Frame(w, bg=BG)
        gombok.pack(fill="x", padx=14, pady=(0, 12))

        def _kuld():
            try:
                lot = float(lot_var.get())
            except ValueError:
                messagebox.showerror("Kézi kötés", "A lot nem szám.", parent=w)
                return
            if lot < min_lot:
                messagebox.showerror("Kézi kötés",
                                     f"A lot nem lehet kisebb, mint {min_lot:g}.",
                                     parent=w)
                return
            w.destroy()
            try:
                ticket, uzenet = self._on_trade(r, lot)
            except Exception as ex:
                messagebox.showerror("Kézi kötés",
                                     f"Hiba: {type(ex).__name__}: {ex}",
                                     parent=self.parent)
                return
            if ticket:
                messagebox.showinfo("Kézi kötés", f"Megnyitva — ticket {ticket}",
                                    parent=self.parent)
            else:
                messagebox.showerror("Kézi kötés",
                                     uzenet or "A megbízás nem ment ki.",
                                     parent=self.parent)
            self._ujratolt()

        tk.Button(gombok, text="Mégsem", command=w.destroy, bg=BG_HEADER,
                  fg=FG_WHITE, font=self._small, relief="flat",
                  padx=12).pack(side="right", padx=4)
        tk.Button(gombok, text="Küldés", command=_kuld, bg=BG_HEADER,
                  fg=FG_YELLOW, font=self._small, relief="flat",
                  padx=12).pack(side="right", padx=4)
        w.grab_set()
