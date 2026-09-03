"""
A KAPUK — és semmi más.

⚠ A KÉRÉS (2026-09-02): „Most vettem észre, hogy az összes kapu a core-ban
helyezkedik el! Ez így szerintem hibás. A kapu ugyanolyan szabadon
»költöztethetőnek« kellene lennie, mint a stratégiának."

Ugyanaz a szétválasztás, mint a stratégiáknál (`strategy/` ↔ `strategies/`),
csak itt a keret nem kapott saját csomagot — és ezt jobb kimondani, mint
elhallgatni:

    core/gates.py         a KERET: mi egy kapu, milyen hatásai vannak
                          (`block`/`reduce`/`none`), a hatás feloldása
                          örökléssel, és a `decide` — a döntés EGY helyen
    core/gate_bands.py    a sávos létra (v3.28.0)
    core/gate_params.py   a kapuk szerkeszthető számainak leírása
    core/gate_layout.py   melyik kapu látszik/él egyáltalán

    gates/                a TARTALOM: EGY-EGY kapu MÉRÉSE + a leírásuk (`docs/`)
                          spread_gate · cost_gate · momentum · tf_align ·
                          vol_baseline

⚠ MIÉRT MARADT A KERET A `core/`-BAN. Mert az EGÉSZ motor rá épül: a
`live_trader`, mindkét backtest-ág, a dashboard sora és a beállító ablakok mind a
`core.gates`-ből dolgoznak. Egy `core/gate_api/` átnevezés ~30 fájl importját
írná át azért, hogy a modul neve szebb legyen — a hatáson nem változtatna. A
kérés a KAPUKRÓL szólt, és a kapuk azok, amik itt vannak.

⚠ AMI ITT NINCS, ÉS MIÉRT. A piac-osztályozó (`core/market_strategy.py`,
`core/regime.py`, `core/market_state.py`) NEM kapu: az egy önálló, cserélhető
seam („milyen a piac most?"), amit a Piac-kapu csak FOGYASZT. Ha idekerülne, a
`gates/` mappa megint két különböző dolgot tartalmazna — pontosan azt, ami ellen
ez a rendezés készült.

⚠ A KÜLÖNBSÉG A STRATÉGIÁKHOZ KÉPEST, amit nem szabad összemosni: egy stratégiát
csak a registry ismer, a kapuk MÉRÉSÉT viszont a motor közvetlenül hívja — ott,
ahol az irány és a friss adat van (lásd `core.gates.decide` docstringjét). Ezért
itt NINCS „a keret sosem importálhat innen" szabály; ami van, az fordítva szól:
egy kapu-modul nem tudhat a másikról, és nem hívhat stratégiát.

⚠ A `_gate` UTÓTAG MOSTANTÓL REDUNDÁNS (`gates.spread_gate`). A átnevezés
SZÁNDÉKOSAN kimaradt ebből a lépésből: egy mozgatás és egy átnevezés együtt
olvashatatlan diffet adna, és ez a commit épp arról szól, hogy a mozgatás
ellenőrizhető legyen.
"""
