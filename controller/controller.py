"""Rule-based real-time controller (plan s7.2/7.3) + independent safety supervisor (s7.4).
Knows nothing about the simulator: it consumes measure() dicts and emits commands."""
from __future__ import annotations

MODES = {1: "PV/WT → Load", 2: "PV/WT → Load + Charge Battery", 3: "PV/WT → Load + Export", 4: "Battery → Load",
         5: "PV/WT + Battery → Load", 6: "Grid → Load + Charge Battery", 7: "Grid → Load",
         8: "Islanded: RES + Battery → Load", 9: "Islanded + Load Shed", 10: "Safe State"}
SHED = [[], ["T3"], ["T3", "T2"], ["T3", "T2", "T1"]]   # shed in tier order; T0 is NEVER shed here

def clip(x, lo, hi): return max(lo, min(hi, x))

class Controller:
    def __init__(self, reg):
        self.B, self.G = reg.by_type("battery")[0], reg.by_type("grid_tie")[0]
        self.tier = {l["id"]: l["tier"] for l in reg.by_type("load")}
        c = reg.control
        self.reserve, self.target, self.restore_n = c.get("reserve_soc_pct", 30), c.get("grid_charge_target_pct", 85), c.get("restore_after_steps", 10)
        rates = [s["rate"] for s in reg.tariffs[self.G["tariff"]]["import"]]
        self.lo, self.hi = min(rates), max(rates)
        self.level = self.cnt = 0

    def decide(self, m):
        B, G, soc = self.B, self.G, m["soc"]
        res, island, fault = m["pv"] + m["wt"], not m["grid_up"], m["batt_fault"]
        dis_cap = 0.0 if fault else B["max_discharge_kw"] * clip((soc - B["soc_min_pct"]) / 5, 0, 1)
        chg_cap = 0.0 if fault else B["max_charge_kw"] * clip((B["soc_max_pct"] - soc) / 5, 0, 1)
        imp_cap = 0.0 if island else min(G["max_import_kw"], 0.9 * G["transformer_kva"])
        exp_cap = 0.0 if island else G["max_export_kw"]
        price = m["price"]; cheap, peak = price <= self.lo + 1e-9, price >= self.hi - 1e-9
        floor = B["soc_min_pct"] if (island or peak) else self.reserve

        def solve(level):
            shed = [i for i, t in self.tier.items() if t in SHED[level]]
            L = sum(v for i, v in m["loads"].items() if i not in shed)
            net, chg, dis, imp, exp_, curt = res - L, 0.0, 0.0, 0.0, 0.0, 0.0
            if net >= 0:
                chg = min(net, chg_cap); rem = net - chg; exp_ = min(rem, exp_cap); curt = rem - exp_
            else:
                dis = min(-net, dis_cap if soc > floor else 0.0); imp = -net - dis
            if cheap and not island and soc < self.target:            # tariff-aware grid charging
                extra = max(0.0, min(chg_cap - chg, imp_cap - imp)); chg += extra; imp += extra
            return dict(shed=shed, chg=chg, dis=dis, imp=imp, exp=exp_, curt=curt, unmet=max(0.0, imp - imp_cap))

        need = next((l for l in range(4) if solve(l)["unmet"] <= 0.01), 3)
        if need > self.level: self.level, self.cnt = need, 0                       # shed immediately
        elif need < self.level:                                                    # restore one tier at a time, after stable margin
            self.cnt += 1
            if self.cnt >= self.restore_n: self.level, self.cnt = self.level - 1, 0
        else: self.cnt = 0
        s = solve(self.level)
        if s["unmet"] > 0.01: mode = 10
        elif island: mode = 9 if s["shed"] else 8
        elif s["chg"] > .05 and s["imp"] > .05: mode = 6
        elif s["dis"] > .05: mode = 5 if res > .1 else 4
        elif s["imp"] > .05: mode = 7
        elif s["exp"] > .05: mode = 3
        elif s["chg"] > .05: mode = 2
        else: mode = 1
        why = f"{MODES[mode]}. Tariff ₹{price:.1f}/kWh ({'off-peak' if cheap else 'peak' if peak else 'normal'}); SoC {soc:.0f}% (discharge floor {floor:.0f}%)."
        if s["shed"]: why += f" Shedding {', '.join(SHED[self.level])} loads (tier order, T0 protected)."
        if fault: why += " Battery faulted: re-planned without it."
        if island: why += " Grid lost: islanded operation."
        return dict(batt_kw=s["dis"] - s["chg"], curt_kw=s["curt"], shed_ids=s["shed"], mode=mode, why=why)


class Supervisor:
    """Independent veto layer: clips any command that breaks a hard invariant; never trusts the controller."""
    def __init__(self, reg):
        self.B, self.G, self.prev = reg.by_type("battery")[0], reg.by_type("grid_tie")[0], 0.0

    def supervise(self, cmd, m):
        v, B, b = [], self.B, cmd["batt_kw"]
        if m["soc"] >= B["soc_max_pct"] and b < 0: b = 0.0; v.append("soc_max")
        if m["soc"] <= B["soc_min_pct"] and b > 0: b = 0.0; v.append("soc_min")
        b = clip(b, -B["max_charge_kw"], B["max_discharge_kw"])
        lim = B["ramp_kw_per_s"] * 60
        b = clip(b, self.prev - lim, self.prev + lim)
        lo, hi = self.G["freq_window_hz"]
        if m["grid_up"] and not lo <= m["hz"] <= hi and b < 0: b = 0.0; v.append("freq_window")
        self.prev = b
        return dict(cmd, batt_kw=b, violations=v)
