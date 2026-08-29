"""JELZÉSEK fül — amit a „csak jelzés" módú stratégiák kiküldtek.

A felhasználó kérése (2026-08-29): „ha valamelyik instrumentum jelzésre van
állítva, akkor ne csak MT5-ön jelezzen, hanem legyen egy lapfül, ahol látom,
milyen jelzéseket küldött ki a rendszer, mikor, melyik stratégia — esetleg egy
nyomógomb, hogy kötés."

Eddig a jelzés-módú stratégia jele CSAK az MT5 chartra és a naplóba ment: ha épp
nem ott néztél, elveszett. Az adat viszont már megvolt — a `trades.csv`-ben,
`event="signal"` sorként (`trading.live_trader.log_trade`). Ez a fül azt mutatja
meg; új adatgyűjtésre nem volt szükség.

⚠ A „Kötés" gomb VALÓDI megbízást küld. Három dolog védi:

  1. A `live_trader.open_position()`-t hívja — UGYANAZT az utat, amit a motor.
     Nincs második kötés-implementáció, ami elcsúszhatna (csúszás-tűrés,
     kitöltési mód, naplózás mind onnan jön).
  2. A stopot és a célárat a jelzéskori TÁVOLSÁGBÓL, a MOSTANI árhoz igazítva
     számolja újra. Egy órája kiadott jelzés abszolút stopja ma egészen más
     kockázatot jelentene — a távolság az, ami a stratégiából jön, nem a szint.
  3. Megerősítő ablak, ami megmutatja a jelzés KORÁT, az ármozgást azóta, és
     pontosan azt, ami kimegy.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dashboard import theme as _theme
from dashboard.scroll_area import scrollable
from dashboard.theme import (BG, BG_HEADER, BG_ROW_EVEN, BG_ROW_ODD, FG_GRAY,
                             FG_GRAY_DIM, FG_GREEN, FG_RED, FG_WHITE,
                             FG_YELLOW)

MAX_SOR = 200            # ennyi legutóbbi jelzést mutatunk
FRISS_PERC = 15          # ennél régebbi jelzésnél a kor sárga/piros


class SignalsTab:
    """A kiküldött jelzések listája + kézi kötés.

    `csv_path`   — a `trades.csv` (a live_trader írja)
    `on_trade`   — `(sor_dict) -> (ticket|None, uzenet)`; None → a gomb rejtve
    `price_of`   — `(symbol) -> (bid, ask) | None`; a kor/elmozdulás kijelzéséhez
    """

    def __init__(self, parent, csv_path, on_trade=None, price_of=None):
        self.parent = parent
        self._csv = Path(csv_path)
        self._on_trade = on_trade
        self._price_of = price_of
        self._sorok: dict = {}          # kulcs -> sor-keret
        self._mtime = None              # a fájl utolsó módosítása (fölösleges olvasás ellen)
        self._build_ui()

    # ── felépítés ─────────────────────────────────────────────────────────
    def _build_ui(self):
        f = _theme.fonts()
        self._mono, self._small = f["mono"], f["small"]
        self._header = f["header"]
        p = self.parent

        fejlec = tk.Frame(p, bg=BG_HEADER)
        fejlec.pack(fill="x", padx=8, pady=(8, 0))
        self._lbl_info = tk.Label(
            fejlec, text="—", bg=BG_HEADER, fg=FG_GRAY, font=self._small,
            anchor="w")
        self._lbl_info.pack(side="left", padx=8, pady=4)
        tk.Button(fejlec, text="Frissítés", command=self.refresh,
                  bg=BG, fg=FG_WHITE, font=self._small,
                  relief="flat", padx=10).pack(side="right", padx=8, pady=3)

        oszlopok = [("Idő", 17), ("Kor", 9), ("Instrumentum", 13),
                    ("Stratégia", 20), ("Irány", 7), ("Jelzett ár", 12),
                    ("SL", 12), ("TP", 12), ("Lot", 7), ("", 10)]
        self._szelesseg = oszlopok
        fej = tk.Frame(p, bg=BG_HEADER)
        fej.pack(fill="x", padx=8)
        for cim, w in oszlopok:
            tk.Label(fej, text=cim, width=w, anchor="w", bg=BG_HEADER,
                     fg=FG_GRAY, font=self._header).pack(side="left", padx=2)

        holder, self._inner, _ = scrollable(p)
        holder.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ── adat ──────────────────────────────────────────────────────────────
    def _olvas(self) -> list:
        """A jelzés-sorok a trades.csv-ből, legfrissebb elöl."""
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
        d = d.tail(MAX_SOR).iloc[::-1]
        return d.to_dict("records")

    @staticmethod
    def _kor(iso: str):
        """(szöveg, szín) — mennyi ideje jött a jelzés."""
        try:
            t = datetime.fromisoformat(str(iso))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except Exception:
            return "—", FG_GRAY_DIM
        perc = (datetime.now(timezone.utc) - t).total_seconds() / 60.0
        if perc < 0:
            return "—", FG_GRAY_DIM
        if perc < 60:
            szoveg = f"{perc:.0f} perce"
        elif perc < 60 * 24:
            szoveg = f"{perc/60:.1f} órája"
        else:
            szoveg = f"{perc/1440:.0f} napja"
        szin = FG_GREEN if perc <= FRISS_PERC else (
            FG_YELLOW if perc <= 60 else FG_GRAY_DIM)
        return szoveg, szin

    # ── megjelenítés ──────────────────────────────────────────────────────
    def refresh(self):
        try:
            mt = self._csv.stat().st_mtime if self._csv.exists() else None
        except OSError:
            mt = None
        sorok = self._olvas()

        # A KORT akkor is frissítjük, ha a fájl nem változott — az idő telik.
        if mt == self._mtime and self._sorok:
            for kulcs, (keret, lbl_kor, _) in self._sorok.items():
                szoveg, szin = self._kor(kulcs.split("|", 1)[0])
                lbl_kor.config(text=szoveg, fg=szin)
            return
        self._mtime = mt

        for w in self._inner.winfo_children():
            w.destroy()
        self._sorok.clear()

        if not sorok:
            uzenet = ("Még nem érkezett jelzés.\n\n"
                      "A „csak jelzés” módú stratégiák jelei itt jelennek "
                      "meg — a kötés-módúak a Pozíciók fülön.")
            tk.Label(self._inner, text=uzenet, bg=BG, fg=FG_GRAY_DIM,
                     font=self._small,
                     justify="left").pack(anchor="w", padx=12, pady=20)
            self._lbl_info.config(text="0 jelzés")
            return

        for i, r in enumerate(sorok):
            self._sor(i, r)
        self._lbl_info.config(
            text=f"{len(sorok)} jelzés  (a legutóbbi {MAX_SOR} látszik)")

    def _sor(self, i: int, r: dict):
        bg = BG_ROW_ODD if i % 2 else BG_ROW_EVEN
        keret = tk.Frame(self._inner, bg=bg)
        keret.pack(fill="x")
        ido = str(r.get("time", ""))
        irany = str(r.get("direction", ""))
        szin_irany = FG_GREEN if irany == "BUY" else FG_RED
        kor_txt, kor_szin = self._kor(ido)

        cellak = [
            (ido[:16].replace("T", " "), FG_WHITE),
            (kor_txt, kor_szin),
            (str(r.get("symbol", "")), FG_WHITE),
            (str(r.get("strategy", "")), FG_GRAY),
            (irany, szin_irany),
            (self._szam(r.get("price")), FG_WHITE),
            (self._szam(r.get("sl")), FG_GRAY),
            (self._szam(r.get("tp")), FG_GRAY),
            (self._szam(r.get("lot"), 2), FG_WHITE),
        ]
        lbl_kor = None
        for (szoveg, szin), (_, w) in zip(cellak, self._szelesseg):
            lbl = tk.Label(keret, text=szoveg, width=w, anchor="w", bg=bg,
                           fg=szin, font=self._mono)
            lbl.pack(side="left", padx=2)
            if len(cellak) and szoveg == kor_txt and lbl_kor is None:
                lbl_kor = lbl

        gomb = None
        if self._on_trade is not None:
            gomb = tk.Button(keret, text="Kötés", font=self._small,
                             bg=BG_HEADER, fg=FG_YELLOW, relief="flat",
                             padx=8, command=lambda rr=r: self._kotes(rr))
            gomb.pack(side="left", padx=2)
        self._sorok[f"{ido}|{i}"] = (keret, lbl_kor, gomb)

    @staticmethod
    def _szam(v, tizedes: int = 5):
        try:
            return f"{float(v):.{tizedes}g}" if tizedes == 5 else f"{float(v):.2f}"
        except (TypeError, ValueError):
            return "—"

    # ── kézi kötés ────────────────────────────────────────────────────────
    def _kotes(self, r: dict):
        """Megerősítő ablak, majd a hívó `on_trade`-je küldi a megbízást."""
        from tkinter import messagebox
        sym = str(r.get("symbol", ""))
        irany = str(r.get("direction", ""))
        kor_txt, _ = self._kor(r.get("time"))

        # A MOSTANI ár — hogy lássa, mennyit mozdult a jelzés óta.
        most = None
        if self._price_of:
            try:
                most = self._price_of(sym)
            except Exception:
                most = None

        sorok = [f"{sym}  {irany}   ({r.get('strategy','')})",
                 f"A jelzés {kor_txt} érkezett."]
        try:
            jelzett = float(r.get("price"))
        except (TypeError, ValueError):
            jelzett = None
        if most and jelzett:
            ar = most[1] if irany == "BUY" else most[0]
            elt = (ar - jelzett) / jelzett * 100.0
            sorok.append(f"\njelzéskor: {jelzett:.5g}     most: {ar:.5g}"
                         f"     ({elt:+.2f}%)")
        elif jelzett:
            sorok.append(f"\njelzéskor: {jelzett:.5g}     (a mostani ár nem "
                         f"elérhető)")
        sorok.append(
            "\nA stop és a célár a jelzéskori TÁVOLSÁGBÓL, a MOSTANI árhoz\n"
            "igazítva megy ki — az abszolút szintek egy régi jelzésnél már\n"
            "más kockázatot jelentenének.")
        sorok.append("\nElküldjem a megbízást?")

        if not messagebox.askyesno("Kézi kötés", "\n".join(sorok),
                                   parent=self.parent):
            return
        try:
            ticket, uzenet = self._on_trade(r)
        except Exception as ex:                       # a GUI ne dőljön el tőle
            messagebox.showerror("Kézi kötés", f"Hiba: {type(ex).__name__}: {ex}",
                                 parent=self.parent)
            return
        if ticket:
            messagebox.showinfo("Kézi kötés", f"Megnyitva — ticket {ticket}",
                                parent=self.parent)
        else:
            messagebox.showerror("Kézi kötés",
                                 uzenet or "A megbízás nem ment ki.",
                                 parent=self.parent)
        self._mtime = None        # a következő refresh olvasson újra
        self.refresh()
