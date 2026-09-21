"""GÉPI VÉGREHAJTÁS — amit a karmester magától megtesz (F3/b).

⚠ EGY ÍRÁSI ÚT, KÉT HÍVÓ. A gép NEM kap saját végrehajtót: ugyanazt az
`actions.apply`-t hívja, amit az „Elfogad" gomb — csak `by="conductor"`
megjelöléssel. Így az újraérvényesítés, a visszaút rögzítése és a krónikába
írás automatikusan ugyanúgy történik. Egy második végrehajtási út előbb-utóbb
elcsúszna az elsőtől, és pont a PÉNZ útján — ez a projekt visszatérő hibája.

⚠ A BUROK ELŐBB DÖNT, MINT A VÉGREHAJTÓ. Minden tétel átmegy a
`governor.allowed`-on; ami nem megy át, az POSTALÁDÁBAN MARAD, `pending`
állapotban. Nem vetjük el, nem halasztjuk el a nevedben: a kvóta lejárta vagy a
türelmi idő nem a te döntésed — holnap ugyanaz a javaslat végrehajtható lehet,
és ha addig te döntesz róla, az a te döntésed marad.

⚠ A MEGERŐSÍTÉS-KÉRÉS ITT ELUTASÍTÁS. Ha a közös réteg `Result.confirm`-ot ad
vissza (van ilyen kérdés, amit embernek szánunk), a gép NEM ismétli meg
`confirmed=True`-val. Az a kérdés pont azért van ott, hogy egy ember válaszoljon
rá — egy gépi „igen" a kérdést értelmetlenné tenné. A tétel marad, és naplózzuk.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def run(ctx, *, limit: int = 20) -> dict:
    """A postaláda gépi feldolgozása. Visszaad:
    `{"done": n, "blocked": n, "failed": n, "reasons": {kód: n}}`.

    ⚠ SOHA NEM DOB: a motor körében fut."""
    try:
        return _run(ctx, limit)
    except Exception as ex:                                  # pragma: no cover
        log.warning("conductor.auto: a gépi feldolgozás elszállt: %s", ex)
        return {"done": 0, "blocked": 0, "failed": 0, "reasons": {}}


def _run(ctx, limit: int) -> dict:
    from conductor import actions as _act
    from conductor import autonomy as _au
    from conductor import governor as _gov
    from conductor import inbox as _ib

    stat = {"done": 0, "blocked": 0, "failed": 0, "reasons": {}}

    # ⚠ A LEGFELSŐ KAPU: ha SEHOL nincs L2+, nem olvasunk postaládát sem.
    # (A cellánkénti fokot a `governor` nézi tételenként.)
    if not _au.barmi_aktiv(ctx.cfg):
        return stat

    for tetel in _ib.items(_ib.PENDING)[:int(limit)]:
        szabad, ok = _gov.allowed(ctx.cfg, tetel, positions=ctx.positions)
        if not szabad:
            stat["blocked"] += 1
            stat["reasons"][ok] = stat["reasons"].get(ok, 0) + 1
            continue
        res = _act.apply(ctx, tetel, confirmed=False, by="conductor")
        if getattr(res, "confirm", ""):
            # ⚠ NEM VÁLASZOLUNK HELYETTED. Lásd a modul fejlécét.
            stat["blocked"] += 1
            stat["reasons"]["needs_confirm"] = \
                stat["reasons"].get("needs_confirm", 0) + 1
            log.info("karmester (gépi): %s/%s — megerősítést kérne, ezért "
                     "EMBERRE vár", tetel.get("symbol"), tetel.get("strategy"))
            continue
        if not res.ok:
            stat["failed"] += 1
            continue
        stat["done"] += 1
        log.info("karmester (GÉPI): %s — %s", tetel.get("code"),
                 " ".join(res.lines)[:160])
    return stat
