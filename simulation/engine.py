"""PHASE 1 - digital twin. Holds TRUE state; the controller only ever sees measure() output."""
from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
import numpy as np

SCENARIOS = {
    "clear_day": {"regime": 0},
    "passing_clouds": {"regime": 1, "start_h": 8},
    "monsoon_overcast": {"regime": 2},
    "heatwave": {"regime": 0, "temp_add": 8},
    "wind_storm": {"wind_scale": 2.8},
    "grid_outage_midday": {"start_h": 10, "events": [{"at": 690, "dur": 150, "type": "grid_outage"}]},
    "grid_outage_night": {"start_h": 18, "events": [{"at": 1200, "dur": 240, "type": "grid_outage"}]},
    "battery_trip": {"start_h": 10, "events": [{"at": 690, "dur": 150, "type": "battery_trip"}]},
    "inverter_fault_pv": {"start_h": 8, "events": [{"at": 600, "dur": 300, "type": "pv_fault"}]},
    "price_spike": {"start_h": 15, "events": [{"at": 1020, "dur": 300, "type": "price_spike"}]},
}
FAULTS = ["battery_trip", "grid_outage", "pv_fault", "price_spike"]

def _m(s): h, m = s.split(":"); return int(h) * 60 + int(m)
def clip(x, lo, hi): return max(lo, min(hi, x))

class Sim:
    DT_H = 1 / 60  # 1 simulated minute per step

    def __init__(self, reg, scenario="clear_day", seed=42):
        self.reg, self.name, self.sc = reg, scenario, SCENARIOS[scenario]
        self.lat, self.lon = reg.site["lat"], reg.site["lon"]
        self.pv, self.wt = reg.by_type("pv_array")[0], reg.by_type("wind_turbine")[0]
        self.b, self.g = reg.by_type("battery")[0], reg.by_type("grid_tie")[0]
        self.loads = reg.by_type("load")
        tar = reg.tariffs[self.g["tariff"]]
        self.slots = [(_m(s["from"]), _m(s["to"]), s["rate"]) for s in tar["import"]]
        self.exp_rate = tar["export_rate"]
        self.typ = {a.id: a.type for a in reg.assets}
        self.busids = {b["id"] for b in reg.buses}
        self.rng = np.random.default_rng(seed)               # seeded => Reset gives identical trajectory
        self.events = [dict(e) for e in self.sc.get("events", [])]
        self.mid0 = datetime(2026, 5, 1)
        self.t = datetime(2026, 5, 1, self.sc.get("start_h", 6), 0)
        self.n = 0
        self.soc, self.temp_b, self.soh = 45.0, 30.0, 100.0
        self.fixed, self.regime = "regime" in self.sc, self.sc.get("regime", 0)
        self.kt_ar = self.temp_ar = self.wind_u = 0.0
        self.ramp_left = self.ramp_len = 0; self.ramp_depth = 0.0
        self.wt_lock, self.hz, self.e = False, 50.0, None
        self.lar = {l["id"]: 0.0 for l in self.loads}
        self.k = dict(buy=0.0, sell=0.0, curt=0.0, served=0.0, cost=0.0, ren=0.0, unserved=0.0)

    def _active(self, typ):
        m = (self.t - self.mid0).total_seconds() / 60
        return any(e["type"] == typ and e["at"] <= m < e["at"] + e["dur"] for e in self.events)

    def inject(self, typ, dur):
        self.events.append({"at": (self.t - self.mid0).total_seconds() / 60, "dur": dur, "type": typ})

    # ---------- environment generators (seeded, deterministic) ----------
    def env(self):
        r, t = self.rng, self.t
        h = t.hour + t.minute / 60
        doy = t.timetuple().tm_yday
        dec = math.radians(23.45) * math.sin(2 * math.pi * (284 + doy) / 365)
        lat = math.radians(self.lat)
        ha = math.radians(15 * (h + (self.lon - 82.5) / 15 - 12))
        sin_el = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha)
        el = math.asin(sin_el)
        az = math.atan2(math.sin(ha), math.cos(ha) * math.sin(lat) - math.tan(dec) * math.cos(lat)) + math.pi
        ghi_clear = 1050 * sin_el ** 1.2 if sin_el > 0 else 0.0
        # clear-sky index: 3-state Markov regime + AR(1) + cloud-ramp events
        if not self.fixed and r.random() < 1 / 90: self.regime = int(r.choice(3, p=[.5, .35, .15]))
        mean, sd = [(0.95, 0.02), (0.60, 0.12), (0.25, 0.05)][self.regime]
        self.kt_ar = 0.9 * self.kt_ar + float(r.normal(0, sd * 0.45))
        if self.ramp_left <= 0 and self.regime == 1 and r.random() < (1 / 60 if self.fixed else 1 / 150):
            self.ramp_len = self.ramp_left = int(r.integers(8, 20)); self.ramp_depth = float(r.uniform(.4, .8))
        ramp = 1.0
        if self.ramp_left > 0:
            ramp = 1 - self.ramp_depth * math.sin(math.pi * (1 - self.ramp_left / self.ramp_len)); self.ramp_left -= 1
        kt = clip((mean + self.kt_ar) * ramp, 0.02, 1.05)
        ghi = ghi_clear * kt
        self.temp_ar = 0.98 * self.temp_ar + float(r.normal(0, .15))
        temp = 30 + 8 * math.sin(2 * math.pi * (h - 9) / 24) - 4 * (1 - kt) + self.sc.get("temp_add", 0) + self.temp_ar
        # PV
        p = self.pv
        tc = temp + (p["noct_c"] - 20) / 800 * ghi
        pv = p["rated_kwp"] * ghi / 1000 * (1 + p["gamma_pct_per_c"] / 100 * (tc - 25)) * (1 - p["soiling_loss_pct"] / 100)
        pv = max(0.0, min(pv, p["inverter_kw"])) * (0.5 if self._active("pv_fault") else 1.0)
        # Wind: Weibull(k=2) marginal through AR(1) Gaussian copula
        self.wind_u = 0.995 * self.wind_u + math.sqrt(1 - 0.995 ** 2) * float(r.normal())
        u = min(0.5 * (1 + math.erf(self.wind_u / math.sqrt(2))), 1 - 1e-9)
        v = self.sc.get("wind_scale", 1.0) * 5.5 * (-math.log(1 - u)) ** 0.5
        w = self.wt
        if v > w["cut_out_ms"]: self.wt_lock = True
        if self.wt_lock and v < w["cut_out_ms"] - 3: self.wt_lock = False
        if self.wt_lock or v < w["cut_in_ms"]: wt = 0.0
        elif v >= w["rated_ms"]: wt = float(w["rated_kw"])
        else: wt = w["rated_kw"] * (v ** 3 - w["cut_in_ms"] ** 3) / (w["rated_ms"] ** 3 - w["cut_in_ms"] ** 3)
        # Loads: class profile x weekday x temperature x lognormal AR(1) noise
        wd = t.weekday() < 5
        loads = {}
        for L in self.loads:
            c = L["class"]
            com = 1 / (1 + math.exp(-(h - 8.5) * 2)) / (1 + math.exp((h - 18) * 2))
            if c == "residential":
                f = (.25 + .55 * math.exp(-((h - 7.5) / 1.6) ** 2) + .85 * math.exp(-((h - 20) / 2.2) ** 2)) / 1.1 * (1 + .02 * max(0, temp - 26))
            elif c == "commercial": f = (.1 + .9 * com) * (1 if wd else .35)
            elif c == "hvac": f = (.05 + com * clip((temp - 24) / 10, 0, 1.2)) * (1 if wd else .5)
            else: f = .7 + .1 * math.sin(2 * math.pi * (h - 14) / 24)
            self.lar[L["id"]] = 0.9 * self.lar[L["id"]] + float(r.normal(0, .04))
            loads[L["id"]] = L["peak_kw"] * min(f, 1.1) * math.exp(self.lar[L["id"]])
        # Grid + tariff
        up = not self._active("grid_outage")
        self.hz = self.hz + 0.15 * (50 - self.hz) + float(r.normal(0, .02))
        mins = t.hour * 60 + t.minute
        price = self.slots[0][2]
        for a, z, rate in self.slots:
            if (a <= mins < z) if a < z else (mins >= a or mins < z): price = rate
        if self._active("price_spike"): price *= 2
        return dict(pv=pv, wt=wt, loads=loads, temp=temp, ghi=ghi, wind=v, grid_up=up, hz=self.hz, price=price, sun=[el, az])

    def measure(self):
        """What the controller sees: true values + sensor noise."""
        e = self.e = self.env(); r = self.rng
        nz = lambda x, s=.005: float(x * (1 + r.normal(0, s)))
        return dict(t=self.t, pv=nz(e["pv"]), wt=nz(e["wt"]), loads={k: nz(v) for k, v in e["loads"].items()},
                    soc=float(self.soc + r.normal(0, .2)), grid_up=e["grid_up"], hz=e["hz"], price=e["price"],
                    batt_fault=self._active("battery_trip"), temp_b=self.temp_b)

    def apply(self, cmd):
        """Advance one step with the (safety-checked) command; return TRUE flows + status."""
        e, B, G, dt = self.e, self.b, self.g, self.DT_H
        shed = set(cmd["shed_ids"])
        dem = dict(e["loads"]); served = {k: (0.0 if k in shed else v) for k, v in dem.items()}
        curt_cmd = min(cmd["curt_kw"], e["pv"] + e["wt"])
        cpv = min(curt_cmd, e["pv"]); pv, wt = e["pv"] - cpv, e["wt"] - (curt_cmd - cpv)
        S = sum(served.values()); fault = self._active("battery_trip"); soc = self.soc
        dis_cap = 0.0 if fault else B["max_discharge_kw"] * clip((soc - B["soc_min_pct"]) / 5, 0, 1)
        chg_cap = 0.0 if fault else B["max_charge_kw"] * clip((B["soc_max_pct"] - soc) / 5, 0, 1)
        p = cmd["batt_kw"] if e["grid_up"] else S - (pv + wt)      # islanded: battery forms the grid, balances the bus
        p = clip(p, -chg_cap, dis_cap)
        unserved = extra = 0.0
        if e["grid_up"]:
            grid = S + max(-p, 0) - (pv + wt + max(p, 0))
            if grid < -G["max_export_kw"]: extra = -grid - G["max_export_kw"]; grid = -G["max_export_kw"]
        else:
            grid, res = 0.0, S - (pv + wt) - p
            if res > 1e-9 and S > 0: unserved = res; sc = (S - res) / S; served = {k: v * sc for k, v in served.items()}; S -= res
            elif res < -1e-9: extra = -res
        e2 = min(extra, pv); pv -= e2; wt -= extra - e2
        curt = curt_cmd + extra
        pch, pdi = max(-p, 0), max(p, 0); imp, exp_ = max(grid, 0), max(-grid, 0)
        eta = math.sqrt(B["round_trip_eff"])
        self.soc = clip(self.soc + (eta * pch - pdi / eta) * dt / B["energy_kwh"] * 100, 0, 100)
        self.temp_b += 0.03 * (e["temp"] + 0.08 * abs(p) - self.temp_b)
        self.soh -= abs(p) * dt / B["energy_kwh"] * 0.002
        sup = pv + wt + pdi + imp
        k = self.k
        k["buy"] += imp * dt; k["sell"] += exp_ * dt; k["curt"] += curt * dt; k["served"] += S * dt; k["unserved"] += unserved * dt
        k["cost"] += (imp * e["price"] - exp_ * self.exp_rate) * dt + B["cycle_cost_per_kwh"] * abs(p) * dt
        k["ren"] += S * ((pv + wt) / sup if sup > .01 else 0) * dt
        mix = {"pv": pv / sup, "wt": wt / sup, "batt": pdi / sup, "grid": imp / sup} if sup > .01 else dict.fromkeys(("pv", "wt", "batt", "grid"), 0.0)
        # per-edge flows with source attribution (proportional sharing on the bus)
        edges = []
        for a, b in self.reg.topology:
            x = b if a in self.busids else a; ty = self.typ[x]; kw, kind, into = 0.0, "idle", True
            if ty == "pv_array": kw, kind = pv, "pv"
            elif ty == "wind_turbine": kw, kind = wt, "wt"
            elif ty == "battery":
                if pdi > .05: kw, kind = pdi, "dis"
                elif pch > .05: kw, kind, into = pch, "chg", False
            elif ty == "grid_tie":
                if imp > .05: kw, kind = imp, "imp"
                elif exp_ > .05: kw, kind, into = exp_, "exp", False
            elif ty == "load": kw, kind, into = served[x], "load", False
            edges.append(dict(id=f"{a}>{b}", kw=round(kw, 2), kind=kind if kw > .05 else "idle", dir=1 if (a == x) == into else -1, shares=mix))
        st = {}
        for l in self.loads: st[l["id"]] = dict(kw=served[l["id"]], status="OK", shed=l["id"] in shed, demand=dem[l["id"]])
        st[self.pv["id"]] = dict(kw=pv, status="DEGRADED" if self._active("pv_fault") else "OK", shed=False)
        st[self.wt["id"]] = dict(kw=wt, status="DEGRADED" if self.wt_lock else "OK", shed=False)
        near = self.soc <= B["soc_min_pct"] + 5 or self.soc >= B["soc_max_pct"] - 5 or self.temp_b > B["temp_limits_c"][1] - 5
        st[B["id"]] = dict(kw=p, status="FAULT" if fault else "DEGRADED" if near else "OK", shed=False)
        st[G["id"]] = dict(kw=grid, status="FAULT" if not e["grid_up"] else "DEGRADED" if imp > .9 * G["max_import_kw"] else "OK", shed=False)
        o = dict(ts=int(self.t.replace(tzinfo=timezone.utc).timestamp() * 1000), t=self.t.strftime("%Y-%m-%d %H:%M:%S"), step=self.n,
                 pv=pv, wt=wt, load=S, demand=sum(dem.values()), imp=imp, exp=exp_, curt=curt, batt=p, soc=self.soc, soh=self.soh,
                 batt_kwh=self.soc / 100 * B["energy_kwh"], temp_b=self.temp_b, price=e["price"], hz=e["hz"],
                 v=415 * (1 - 0.02 * imp / G["max_import_kw"]), grid_up=e["grid_up"], unserved=unserved, shed=sorted(shed),
                 sun=e["sun"], wind=e["wind"], ghi=e["ghi"], temp=e["temp"], balance=sup - (S + pch + exp_), assets=st, edges=edges,
                 kpi=dict(coe=k["cost"] / k["served"] if k["served"] > 1 else 0.0, ref=100 * k["ren"] / k["served"] if k["served"] > 1 else 0.0,
                          buy=k["buy"], sell=k["sell"], curt=k["curt"], unserved=k["unserved"]))
        self.t += timedelta(minutes=1); self.n += 1
        return o
