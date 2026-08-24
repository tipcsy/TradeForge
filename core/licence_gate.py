"""A licenc-kapu az élő kereskedés indulásánál — a felhasználóval együtt.

A `core.licence` a hálózat és a kriptográfia; EZ a modul az, ami dönt és
beszél a felhasználóval: bekéri a belépést, ha kell, és érthetően megmondja,
miért nem indul a program.

⚠ CSAK AZ ÉLŐ KERESKEDÉS VAN KAPUZVA. A backtest, az optimalizálás és az
adatletöltés licenc nélkül is fut. Ezek nem nyúlnak a brókerszámlához, és ha
egy lejárt licenc a backtestet is blokkolná, épp akkor nem tudnál dolgozni a
rendszeren, amikor a megújításról döntesz.

⚠ A BELÉPŐ-ABLAK CSAK AKKOR JÖN ELŐ, ha tényleg kell (nincs mentett belépő,
vagy visszavonták). Minden más indulás néma.
"""

from __future__ import annotations

import logging

from core import licence

log = logging.getLogger(__name__)


def _ask_login_tk(email_hint: str = "") -> "tuple[str, str] | None":
    """Belépő-ablak. `(email, jelszó)` vagy `None`, ha a felhasználó elvetette.

    ⚠ A jelszó SEHOL nem tárolódik: innen egyenesen a `login_and_get_token`-be
    megy, ami tokent hoz vissza, és a jelszó ott véget ér."""
    import tkinter as tk
    from tkinter import ttk

    out: dict = {}
    root = tk.Tk()
    root.title("TradeForge — licenc belépés")
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=16)
    frm.grid(sticky="nsew")

    ttk.Label(frm, text="Jelentkezz be a licenchez",
              font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2,
                                                  sticky="w", pady=(0, 4))
    ttk.Label(frm, text="Ezt csak egyszer kell megtenned ezen a gépen.",
              foreground="#666").grid(row=1, column=0, columnspan=2,
                                      sticky="w", pady=(0, 12))

    ttk.Label(frm, text="E-mail cím").grid(row=2, column=0, sticky="w")
    e_mail = ttk.Entry(frm, width=34)
    e_mail.grid(row=2, column=1, pady=3)
    e_mail.insert(0, email_hint)

    ttk.Label(frm, text="Jelszó").grid(row=3, column=0, sticky="w")
    e_pw = ttk.Entry(frm, width=34, show="•")
    e_pw.grid(row=3, column=1, pady=3)

    hiba = ttk.Label(frm, text="", foreground="#c0392b", wraplength=320)
    hiba.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def ok(_evt=None):
        if not e_mail.get().strip() or not e_pw.get():
            hiba.config(text="Az e-mail cím és a jelszó is kell.")
            return
        out["email"] = e_mail.get().strip()
        out["pw"] = e_pw.get()
        root.destroy()

    gombok = ttk.Frame(frm)
    gombok.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(gombok, text="Mégse", command=root.destroy).pack(side="left", padx=4)
    ttk.Button(gombok, text="Belépés", command=ok).pack(side="left")

    root.bind("<Return>", ok)
    (e_pw if email_hint else e_mail).focus_set()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()

    return (out["email"], out["pw"]) if "email" in out else None


def _show_error_tk(cim: str, uzenet: str) -> None:
    """Hibaüzenet ablakban. ⚠ Egy ablakos programnál a `print` SEHOL nincs —
    ha csak a konzolra írnánk, a felhasználó annyit látna, hogy nem indul el."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(cim, uzenet)
        r.destroy()
    except Exception:
        # Fejgép nélküli környezetben (CI, szerver) nincs Tk — ott a napló marad.
        log.error("%s — %s", cim, uzenet)


def ensure_licence(cfg: dict, account_number: str, account_name: str = "",
                   broker_server: str = "", app_version: str = "",
                   interactive: bool = True) -> bool:
    """A licenc-kapu. `True` → indulhat az élő kereskedés.

    Legfeljebb EGYSZER kér belépést: ha a friss token után is elutasít a
    szerver, az már valódi ok (lejárt, betelt slot), nem hiányzó belépő —
    és egy második kérdés csak zavarná a felhasználót.
    """
    api = str((cfg.get("licence") or {}).get("api_url") or licence.DEFAULT_API)

    def _check() -> "licence.Result":
        return licence.check(account_number, api=api, account_name=account_name,
                             broker_server=broker_server,
                             app_version=app_version)

    r = _check()

    if not r.ok and r.needs_login and interactive:
        log.info("licenc: belépés szükséges (%s)", r.reason)
        hint = str(licence._read_json(licence.TOKEN_PATH).get("email") or "")
        while True:
            adat = _ask_login_tk(hint)
            if adat is None:
                _show_error_tk("TradeForge — licenc",
                               "Belépés nélkül az élő kereskedés nem indítható.\n\n"
                               "A backtest és az optimalizálás továbbra is "
                               "használható.")
                return False
            ok, res = licence.login_and_get_token(adat[0], adat[1], api=api)
            if ok:
                licence.save_token(res, adat[0])
                break
            # ⚠ ÚJRA KÉRDEZÜNK, nem lépünk ki: a rossz jelszó a leggyakoribb
            # eset, és egy azonnali kilépés miatt a felhasználónak újra kellene
            # indítania a programot.
            hint = adat[0]
            _show_error_tk("Sikertelen belépés", str(res))
        r = _check()

    if r.ok:
        if r.from_cache:
            # ⚠ Ez NEM néma: a felhasználónak tudnia kell, hogy a program most
            # a türelmi időből fut, mert az véges.
            log.warning("licenc: %s", r.message)
        else:
            log.info("licenc: %s", r.message)
        return True

    log.error("licenc: %s (%s)", r.message, r.reason)
    if interactive:
        _reszlet = ""
        p = r.payload or {}
        if p.get("account_limit"):
            _reszlet = (f"\n\nSzámla-slotok: {p.get('accounts_used')}"
                        f"/{p.get('account_limit')}")
        _show_error_tk(
            "TradeForge — a licenc nem érvényes",
            f"{r.message}\n\nSzámlaszám: {account_number}{_reszlet}"
            f"\n\nA licenceidet a portálon kezelheted.")
    return False
