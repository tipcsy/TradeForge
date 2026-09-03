"""
A STRATÉGIÁK — és semmi más.

⚠ A KÉRÉS (2026-09-02): „Most ha megnézzük a /strategy mappát akkor látunk benne
olyan fájlokat is, amik a stratégia működését viszi. pl.: visual.py, base.py,
settings.py. Vagy ezek maradjanak a strategy mappába, és a tényleges stratégiák
meg kerüljenek a strategies mappába…"

A két csomag KÉT KÜLÖNBÖZŐ dolog, és ezt eddig egy mappa mosta össze:

    strategy/    a KERET   — mit jelent stratégiának lenni
                 (`base` interfész, `visual` rajz-primitívek, `settings`
                 config-betöltés, `signal_journal`, a registry)
    strategies/  a TARTALOM — a konkrét stratégiák, a configjaikkal és a
                 leírásaikkal (`config/`, `docs/`)

⚠ AZ IRÁNY EGYIRÁNYÚ, és ezt teszt őrzi (`tests/test_strategy_layout.py`): a
`strategies/` FÜGGHET a kerettől, a keret viszont SOSEM ismerheti a tartalmat.
Enélkül a szétválasztás egy hét alatt visszakopna — egy „gyorsan idehívom" import
a `core`-ból, és a mappa neve megint csak dísz. A `tools/` kivétel: a kutató- és
laboreszközök szándékosan ismernek konkrét stratégiát.

⚠ EZT A FÁJLT NEM KELL SZERKESZTENI ÚJ STRATÉGIÁHOZ. A regisztráció automatikus:
a `strategy/__init__.py` végigjárja ezt a csomagot, és a talált `Strategy`
-alosztályokat a `.name`-jük alapján veszi fel. Egy új stratégia = egy új modul
ITT, plusz egy `config/<név>.json` és egy `docs/<név>.md`.

⚠ AMI NEM STRATÉGIA, DE IDE TARTOZIK. Az `ml_features` és az `ml_train` az
`ml_ai` SAJÁT segédmodulja — a keretnek semmi köze hozzájuk, tehát a keretbe sem
valók. A felderítés átugorja őket (nincs bennük `Strategy`-alosztály). Ha egy
ilyen helper több stratégiának is kellene, az már a keret dolga: akkor a
`core/`-ba való, nem ide. (Pontosan ez történt a `resample_ohlc`-kal, ami az
`ml_ai`-ban lakott, miközben a bollinger, a CLB és a labor is onnan importálta —
átkerült a `core.indicator_engine`-be.)
"""
