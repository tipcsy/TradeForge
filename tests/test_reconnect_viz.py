"""A #5 (MT5-ujrakapcsolodas) es #8 (viz kulon szalon) tesztje."""
import sys, threading, time, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import mt5_connector as mc
import trading.live_trader as lt

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# ══ #5  Ujrakapcsolodas ════════════════════════════════════════════════════
class Acct:
    login, server, balance, currency, margin_mode = 6254822, "S", 1000.0, "EUR", 2


class Term:
    def __init__(self, connected=True):
        self.connected = connected
        self.path = "x"


class FakeMT5:
    def __init__(self, acct=None, term=None):
        self.acct, self.term = acct, term
        self.shutdown_calls = 0

    def account_info(self):
        return self.acct

    def terminal_info(self):
        return self.term

    def shutdown(self):
        self.shutdown_calls += 1


def reset_state():
    mc._conn_state.update(next_try=0.0, attempt=0, was_down=False, last_note="")


CFG = {"broker": {"login": 6254822, "password": "x", "server": "S"}, "mt5": {}}
orig_mt5, orig_connect = mc.mt5, mc.connect

# 1) Minden rendben -> True, es NEM nyul a kapcsolathoz
reset_state()
fake = FakeMT5(Acct(), Term(True))
mc.mt5 = fake
connect_calls = []
mc.connect = lambda cfg: connect_calls.append(1) or True
check("elo kapcsolat -> True", mc.ensure_connected(CFG) is True)
check("elo kapcsolatnal NINCS ujrakapcsolodas", not connect_calls and fake.shutdown_calls == 0)

# 2) A terminal fut, de NINCS szerver-kapcsolat -> False, de NEM inicializal ujra
reset_state()
fake = FakeMT5(Acct(), Term(False))
mc.mt5 = fake
connect_calls.clear()
check("terminal-szerver szakadas -> False", mc.ensure_connected(CFG) is False)
check("...es NEM inicializal ujra (felesleges lenne)",
      not connect_calls and fake.shutdown_calls == 0)

# 3) Python-terminal szakadas -> ujrakapcsolodas, sikerrel
reset_state()
fake = FakeMT5(None, None)
mc.mt5 = fake
connect_calls.clear()
mc.connect = lambda cfg: connect_calls.append(1) or True
check("API-szakadas -> ujrakapcsolodas sikerul", mc.ensure_connected(CFG) is True)
check("...a connect() meghivodott (fiok-ellenorzessel)", len(connect_calls) == 1)
check("...a fel-holt session eltakaritva (shutdown)", fake.shutdown_calls == 1)
check("...az allapot visszaallt", mc._conn_state["attempt"] == 0
      and mc._conn_state["was_down"] is False)

# 4) Sikertelen ujrakapcsolodas -> False + BACKOFF (nem ostromolja a terminalt)
reset_state()
fake = FakeMT5(None, None)
mc.mt5 = fake
mc.connect = lambda cfg: False
check("sikertelen ujrakapcsolodas -> False", mc.ensure_connected(CFG) is False)
n1 = fake.shutdown_calls
check("azonnali ujrahivas NEM probalkozik ismet (backoff)",
      mc.ensure_connected(CFG) is False and fake.shutdown_calls == n1,
      f"shutdown={fake.shutdown_calls}")
check("a szakadas jelezve van a felulet fele", mc.connection_lost_since() is True)

# 5) Helyreallas jelzese
mc.mt5 = FakeMT5(Acct(), Term(True))
check("helyreallas -> True es a szakadas-jelzes megszunik",
      mc.ensure_connected(CFG) is True and mc.connection_lost_since() is False)

mc.mt5, mc.connect = orig_mt5, orig_connect
reset_state()

# ══ #8  A viz le van valasztva a kereskedesrol ═════════════════════════════
class S:
    def __init__(self, name):
        self.name = name


class PS:
    def __init__(self, params):
        self.params = params


all_pairs = {"Ger40": {"point_size": 1.0}, "EURUSD": {"point_size": 0.0001}}
strats_by_symbol = {"Ger40": [S("wpr_sma"), S("ml_ai")], "EURUSD": [S("wpr_sma")]}
pair_states = {("Ger40", "wpr_sma"): PS({"a": 1}), ("Ger40", "ml_ai"): PS({"b": 2}),
               ("EURUSD", "wpr_sma"): PS({"c": 3})}
lt.instrument_state.clear()
lt.instrument_state.update({"Ger40": "LIVE", "EURUSD": "CLOSING"})

lt._publish_viz_jobs(all_pairs, strats_by_symbol, pair_states)
jobs = lt._viz_jobs
check("LIVE es CLOSING par is bekerul a munkalistaba", len(jobs) == 2, f"{len(jobs)} job")
g = next(j for j in jobs if j[0] == "Ger40")
check("mindket Ger40-strategia parameterei benne vannak",
      set(g[3]) == {"wpr_sma", "ml_ai"}, str(sorted(g[3])))

# STOPPED par kimarad
lt.instrument_state["EURUSD"] = "STOPPED"
lt._publish_viz_jobs(all_pairs, strats_by_symbol, pair_states)
check("STOPPED par kimarad", {j[0] for j in lt._viz_jobs} == {"Ger40"})

# A LENYEG: a motor modosithatja a pair_states-t, a viz-szal listaja ettol ep marad
snapshot = lt._viz_jobs
pair_states.clear()                       # a motor "Stop"-ot kapott menet kozben
ok = True
try:
    for symbol, pair_cfg, strats, params in snapshot:
        _ = list(params.items())
except RuntimeError:
    ok = False
check("a publikalt lista tullel egy pair_states-modositast (nincs kozos allapot)", ok)

# Egyideju publikalas + olvasas -> nincs 'changed size during iteration'
errors = []


def reader():
    end = time.time() + 1.0
    while time.time() < end:
        try:
            for j in lt._viz_jobs:
                _ = j[3].get("wpr_sma")
        except Exception as e:
            errors.append(e)


def writer():
    end = time.time() + 1.0
    while time.time() < end:
        lt._publish_viz_jobs(all_pairs, strats_by_symbol,
                             {("Ger40", "wpr_sma"): PS({"a": 1})})


t1, t2 = threading.Thread(target=reader), threading.Thread(target=writer)
t1.start(); t2.start(); t1.join(); t2.join()
check("1 mp parhuzamos olvasas+iras -> nincs kivetel", not errors,
      str(errors[:1]) if errors else "")

# A lock re-entrans (a mely hivasi lancok nem okozhatnak holtpontot)
with mc.MT5_LOCK:
    with mc.MT5_LOCK:
        pass
check("MT5_LOCK re-entrans (nincs holtpont egymasba agyazaskor)", True)

print()
print(f"{sum(results)}/{len(results)} teszt PASS")
sys.exit(0 if all(results) else 1)
