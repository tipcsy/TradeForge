"""ÁTJÁRÓ a felület és a motor között — helyi vagy távoli, EGY hívási ponton.

⚠ 0029, 4b/3 S3b (2026-09-28). A felület műveletei (BE, trailing, ráépítés,
kézi kötés, örökbefogadás, viz-törlés) ma a MOTOR memóriáját írják közvetlenül
— ez csak addig működik, amíg a motor a felület processzében fut. Az átjáró:

  • HELYI mód (ma, alapértelmezés): a `local` függvényt hívja — PONTOSAN azt,
    amit eddig a hívási hely futtatott. A mai viselkedés nem változik.
  • TÁVOLI mód (a motor külön processzben; az S5 kapcsolja be): a műveletet a
    csatornán (`core/engine_channel`, `op` + `args`) a MOTOR hajtja végre, a
    motor saját művelet-listájából (`live_trader.remote_ops`).

Azért modul-szintű (és nem a főablak metódusa), mert a hívók közt az
instrumentum-ablak is ott van, amelynek nincs hozzáférése a főablak állapotához.

⚠ A háttérszál SOSEM nyúl a Tk-hoz: az eredményt a közös pumpa (`remote_cmd.Pump`)
viszi a főszálra.
"""
from __future__ import annotations

import threading

from core import engine_channel as CH

_remote = None
_pump = None
_status = None
_request = None


def configure(profile, pump, status_cb=None, request=None) -> None:
    """Távoli mód bekapcsolása (a `gui.start_remote_mode` hívja)."""
    global _remote, _pump, _status, _request
    _remote, _pump, _status, _request = profile, pump, status_cb, request


def reset() -> None:
    configure(None, None)


def is_remote() -> bool:
    return _remote is not None


def _jelez(szoveg: str) -> None:
    if _status is not None and szoveg:
        try:
            _status(szoveg)
        except Exception:
            pass


def op(name: str, local, *, sync: bool = False, timeout: float = 8.0, **args):
    """Egy művelet. Helyi módban `local()` (változatlanul); távoli módban a motor.

    `sync=True` (pl. a kézi kötés, amelynek a hívója a ticketet várja): blokkol,
    legfeljebb `timeout` mp-ig, és a motor eredményét adja vissza (None, ha
    nem sikerült / nem válaszolt). Különben azonnal visszatér, az eredmény az
    állapotsorba kerül."""
    if _remote is None:
        return local()
    req = _request or CH.request
    if sync:
        r = req(_remote, op=name, args=args, timeout=timeout)
        if r is None:
            from core.i18n import t as _t
            _jelez(_t("brokers.cmd.no_answer", tag=_remote.tag))
            return None
        if not r.get("ok"):
            _jelez(" ".join(str(x) for x in (r.get("lines") or [])))
            return None
        return r.get("result")

    def _fut():
        r = req(_remote, op=name, args=args, timeout=timeout)

        def _vissza():
            if r is None:
                from core.i18n import t as _t
                _jelez(_t("brokers.cmd.no_answer", tag=_remote.tag if _remote else "?"))
            elif not r.get("ok"):
                _jelez(" ".join(str(x) for x in (r.get("lines") or [])))
        if _pump is not None:
            _pump.put(_vissza)
    threading.Thread(target=_fut, daemon=True, name=f"RemoteOp-{name}").start()
    return None
