"""Headless safety/consistency check across ALL scenarios (2 simulated days each)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.runner import Runner
from simulation.engine import SCENARIOS

def test_registry_valid():
    from registry.schema import load; load()

def test_all_scenarios_invariants():
    for sc in SCENARIOS:
        r = Runner(sc); B = r.sim.b; G = r.sim.g; over = 0
        for _ in range(2 * 1440):
            o = r.step()
            assert abs(o["balance"]) < 1e-6, f"{sc}: bus imbalance {o['balance']}"
            assert B["soc_min_pct"] - 1.5 <= o["soc"] <= B["soc_max_pct"] + 1.5, f"{sc}: SoC {o['soc']}"
            if o["grid_up"]: assert "MG01-LD-CLINIC" not in o["shed"], f"{sc}: T0 shed while grid-connected"
            over += o["imp"] > G["max_import_kw"] + 0.5
        assert over < 30, f"{sc}: import cap exceeded {over} steps"
