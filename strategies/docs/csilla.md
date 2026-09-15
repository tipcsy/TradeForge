# Csilla beszállója (`csilla`)

Szerkezet-törés **két idősíkon**: egy **jelentős napi/heti szint** (igazolt D1
vagy W1 swing-csúcs/-völgy) M15-ös letörése/kitörése után az **M1-en egy
„zászló" (visszahúzódás) törésére** lépünk be a törés irányába. Csilla
diszkrecionális módszerének gépi olvasata; a szabály a `strategies/csilla_rules.py`
modulban van, amit a kutató-labor is ugyanígy hív.

## A szabály

| lépés | mi történik |
|---|---|
| **szint** | igazolt D1 fraktál-swing (`k_d1` = 2 → 2 nappal később ismert) vagy W1 swing (`k_w1` = 1). Csúcs = ellenállás, völgy = támasz. Él `ttl_d1` / `ttl_w1` napig, vagy amíg át nem törik. Minden szint egyszer törhet. |
| **törés** (M15) | egy M15 gyertya a szint FÖLÖTT zár (BUY-irány) / ALATT zár (SELL-irány) |
| **belépő** (M1) | a törés utáni `max_wait` × 15 percen belül egy igazolt M1 swing az irány oldalán (`k_lo` = 3), majd zárás azon túl → **belépés a zárón**. Egy töréshez több belépő is jöhet. |
| **napszak** | NEM a stratégia paramétere: a **Csilla-sáv** (Ger40 8–11h, UsaTec és GOLD 15–18h, szerver-idő) a keret stratégia-hatókörű **kereskedési órái** (a dashboard óra-választója, `data/optimized_params/csilla/<PÁR>_hours.json`). A stratégia minden órában jelez, az óra-kapu dönt. |

**SL** = `stop_atr` (1,5) × a **törés M15-gyertyájának** ATR-je · **TP** =
SL × `tp_rr_ratio` — alapból 30 R, azaz gyakorlatilag nincs célár.

## A kilépés — NEM a stratégiáé

A mért (forward-tesztelt) változat kilépése: **BE +0,67 R-nél**, utána
**2 R-es csúszó stop**, célár nélkül, max 5 nap. Ezt a pár
**kockázatcsökkentésében** kell beállítani: `breakeven_r = 0,67`,
`trail_activation_atr = 3,0`, `trail_distance_atr = 3,0` (2 R = 3 ATR15),
preset `off`. A célár azért messze, mert az R-alapú BE-t a távoli célár nem
kapcsolja ki.

## Mit mértünk, és mit nem

8 pár, 2013–2026 (tick-alapú M1), teljes költség:

| változat | R/kötés | év poz. | pár poz. |
|---|---|---|---|
| minden fraktál-szint, M1-stop (első olvasat) | −0,22 | 0/14 | 0/8 |
| D1/W1 szintek, M15-stop (ez a modul, sáv nélkül) | −0,07 | 3/14 | 3/8 |
| **Csilla-sáv** (Ger40 de., UsaTec+GOLD US-nyitás), fix 1,5 ATR15, BE 0,67 R, 2R csúszó | **+0,12** (t = 1,5) | 9/14 | 3/3 |

A sáv volt az egyetlen cella, amit a felhasználó **előre** nevezett meg, és
minden kimenet-változatban pozitív előjelet adott — de **t < 2**, tehát nem
bizonyíték. Ezért **forward papírkereskedés** 2026-09-15-től
(`tools/csilla_forward.py`), előre rögzített leállító küszöbbel (n ≥ 60 és
R < −0,10). A kicsi célár, a korai BE, a csúszó stop és a pozícióépítés
mind mérve: egyik sem fordítja pozitívba a 8 páros eredményt.

## Paraméterek

A szint-paraméterek (`k_d1`, `k_w1`, `ttl_*`) a „jelentős szint" definíciója —
a forward teszt alatt **nem hangolhatók**. Az Opt rács csak a `stop_atr`,
`max_wait`, `tp_rr_ratio` tengelyeket tartalmazza.

⚠ Mély M15-warmup (~1 év, a W1-szintek miatt); a kontextus páronként
gyorsítótárazott.
