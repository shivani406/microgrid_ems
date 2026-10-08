"""Glue: sim -> controller -> safety supervisor -> sim. One process in SIM mode (plan s2 splits these later)."""
from __future__ import annotations
from collections import deque
from registry.schema import load
from simulation.engine import Sim
from controller.controller import Controller, Supervisor, MODES

class Runner:
    def __init__(self, scenario="clear_day"):
        self.reg = load(); self.playing, self.speed = False, 1
        self.scenario = scenario
        self.reset(scenario)

    def reset(self, scenario=None):
        self.scenario = scenario or self.scenario
        self.sim, self.ctrl, self.sup = Sim(self.reg, self.scenario), Controller(self.reg), Supervisor(self.reg)
        self.hist, self.new, self.log, self.active = deque(maxlen=2880), [], [], {}
        self.step()

    def step(self):
        m = self.sim.measure()
        plan = self.ctrl.decide(m)
        cmd = self.sup.supervise(plan, m)
        o = self.sim.apply(cmd)
        o.update(mode_id=plan["mode"], mode_text=MODES[plan["mode"]], why=plan["why"], violations=cmd["violations"])
        self._alarms(o)
        o["alarms"] = list(self.active.values())
        self.last = o
        p = {k: round(o[k], 2) for k in ("pv", "wt", "load", "imp", "exp", "soc")}; p["t"] = o["ts"]
        self.hist.append(p); self.new.append(p)
        return o

    def _alarms(self, o):
        G, B = self.sim.g, self.sim.b
        now = {}
        if not o["grid_up"]: now["grid_loss"] = ("critical", "Main grid lost - islanded")
        if o["assets"][B["id"]]["status"] == "FAULT": now["battery_fault"] = ("critical", "Battery tripped")
        if o["unserved"] > 0.05: now["unserved_load"] = ("critical", f"Unserved load {o['unserved']:.1f} kW")
        if o["soc"] < B["soc_min_pct"] + 5: now["soc_low"] = ("warning", f"SoC low {o['soc']:.0f}%")
        if o["shed"]: now["load_shed"] = ("warning", f"{len(o['shed'])} load(s) shed")
        if o["imp"] > 0.9 * G["max_import_kw"]: now["import_near_cap"] = ("warning", "Import >90% of cap")
        for v in o["violations"]: now["safety_" + v] = ("warning", f"Supervisor clipped command: {v}")
        for c in list(self.active):
            if c not in now: del self.active[c]
        for c, (lvl, txt) in now.items():
            if c not in self.active:
                self.active[c] = dict(code=c, level=lvl, text=txt, t=o["t"]); self.log.insert(0, self.active[c]); del self.log[50:]

    def snapshot(self, pop=False):
        pts = self.new if pop else []
        msg = dict(state=self.last, points=pts, playing=self.playing, speed=self.speed, scenario=self.scenario, log=self.log[:5])
        if pop: self.new = []
        return msg
