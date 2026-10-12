"""A kézi előszűrő vezérlése parancsból és Telegramról (Tibi, 2026-10-12).

`manual` — lista; `manual <pár>` — állapot (+ Telegramon gombok);
`manual <pár>|all <állapot>` — beállítás. A gomb ugyanazt a parancsot hívja.

⚠ A valódi data/manual_filter.json-t NEM írja (ideiglenes útvonal), és nem
küld semmit a hálózatra (a bot döntési része tiszta).
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import applog                                         # noqa: E402
applog.harden_console()

from core import console_cmd as cc, telegram_cmd as tgc         # noqa: E402
from core import manual_filter as MF                             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def ctx(enabled=True):
    cfg = {"pairs": {"GOLD": {}, "Ger40": {}, "EURUSD": {}},
           "manual_filter": {"enabled": enabled}}
    dash = {"GOLD": NS(manual_state=None)}
    return cc.Context(cfg=cfg, save_config=lambda: True, positions=list,
                      close_position=lambda t: True, account=dict, dashboard=dash,
                      instrument_state={}, strategies_of=lambda s: ["wpr_sma"])


_valodi = MF.PATH
MF.PATH = Path(tempfile.mkdtemp()) / "manual_filter.json"
try:
    c = ctx()
    r = cc.dispatch(c, "manual")
    check("lista: ma minden Nincs", r.ok and "Nincs" in " ".join(r.lines) or
          "None" in " ".join(r.lines), r.lines)
    r = cc.dispatch(c, "manual gold ne")
    check("beállítás kisbetűs párral + magyar szóval", r.ok and MF.state_of("GOLD") == MF.NO_TRADE,
          r.lines)
    check("...a kijelzés-állapot is azonnal frissül",
          c.dashboard["GOLD"].manual_state == MF.NO_TRADE)
    for szo, st in (("ovatos", MF.CAUTIOUS), ("fel", MF.BULL), ("down", MF.BEAR),
                    ("szép", MF.NICE), ("nincs", MF.NONE), ("no_trade", MF.NO_TRADE)):
        cc.dispatch(c, f"manual Ger40 {szo}")
        check(f"„{szo}” → {st}", MF.state_of("Ger40") == st)
    r = cc.dispatch(c, "manual GOLD")
    check("egy pár lekérdezése", r.ok and "GOLD" in r.lines[0], r.lines)
    r = cc.dispatch(c, "manual GOLD valami")
    check("ismeretlen állapot → hiba, nem állít", not r.ok and MF.state_of("GOLD") == MF.NO_TRADE)
    r = cc.dispatch(c, "manual all nincs")
    check("all → minden pár", r.ok and MF.states() == {}, MF.states())
    r = cc.dispatch(ctx(enabled=False), "manual GOLD ne")
    check("kikapcsolt előszűrő → nem állít", not r.ok and MF.state_of("GOLD") == MF.NONE)

    # ── Telegram ───────────────────────────────────────────────────────
    check("a bot engedi a `manual`-t", "manual" in tgc.ENGEDETT)
    check("benne van a menüben", "manual" in [n for n, _l in tgc.parancs_lista()])
    b = tgc.Bot(token="T", chat_ids=("42",), ctx=c)
    out = b.feldolgoz({"message": {"chat": {"id": 42}, "text": "/manual gold"}}) \
        if hasattr(b, "feldolgoz") else b._parancs("42", "/manual gold")
    k = out[0]
    check("`/manual <pár>` → gombok KÉT sorban, 3-3", len(k.buttons) == 2
          and all(len(s) == 3 for s in k.buttons), k.buttons)
    adatok = [a for sor in k.buttons for _f, a in sor]
    check("a gombok a párt és az állapotot viszik", adatok == [f"k:GOLD:{s}" for s in MF.STATES],
          adatok)
    check("a callback-adat elfér 64 bájtban", all(len(a.encode()) <= 64 for a in adatok))
    out = b._gomb({"data": "k:GOLD:bull", "id": "cb1"}, "42", {"message_id": 7})
    check("gombnyomás → beállítva", MF.state_of("GOLD") == MF.BULL)
    check("...és az üzenet átíródik (a gombok eltűnnek)",
          out[0].edit_message_id == 7 and out[0].callback_id == "cb1", out[0])
    out = b._parancs("42", "/manual GOLD le")
    check("begépelve is megy", MF.state_of("GOLD") == MF.BEAR and not out[0].buttons)

    # A gombos küldés több sort is tud (egy sor = a régi alak, változatlan).
    from core import telegram as T
    _kuldott = []
    _orig = T._hivas
    T._hivas = lambda token, met, adat: (_kuldott.append(adat) or (True, {"ok": True}))
    try:
        T.send_buttons("T", "42", "x", k.buttons)
        T.send_buttons("T", "42", "x", (("Igen", "i:1"), ("Nem", "n:1")))
    finally:
        T._hivas = _orig
    kb1 = _kuldott[0]["reply_markup"]["inline_keyboard"]
    kb2 = _kuldott[1]["reply_markup"]["inline_keyboard"]
    check("több sor → több billentyűzet-sor", len(kb1) == 2 and len(kb1[0]) == 3)
    check("egy sor → egy sor (a régi alak)", len(kb2) == 1 and len(kb2[0]) == 2)
finally:
    MF.PATH = _valodi

print(f"\n{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
