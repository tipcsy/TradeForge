"""KARMESTER — döntési réteg a `(instrumentum × stratégia)` mátrix fölé.

A teljes terv: `docs/karmester.md`. Ez a csomag az **F0 fázis**: CSAK MÉRÉS.
Nem dönt, nem javasol, nem ír configot, és nem nyúl a kereskedéshez.

    conductor/
      paths.py      — hol laknak a karmester fájljai (EGY gazda)
      telemetry.py  — belépő-kísérletek kimenetele (a „miért nem kötött")

⚠ MIÉRT MÉRÉSSEL KEZDÜNK. A terv szerint a karmester önállósága (L3/L4) csak
akkor adható meg, ha a döntései utólag SZÁMONKÉRHETŐK — és egyáltalán van mit
néznie. Ma a rendszer nem tudja megmondani, mi NEM történt: nincs
kapu-telemetria, nincs élő gördülő teljesítmény-tár, és nincs krónika. Amíg ez
nincs meg, minden döntési logika vakon dolgozna.

⚠ EZ A CSOMAG NEM IMPORTÁL MT5-öt, pandas-t és tkintert. A motor, a felület és a
tesztek ugyanúgy használhatják — és egy mérés-hiba SOHA nem állíthatja meg a
kereskedést.
"""
