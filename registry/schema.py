"""PHASE 0 - digital registration. Validates config/MG01.yaml. Run: python -m registry.schema"""
from __future__ import annotations
import re, sys
from collections import deque
from pathlib import Path
import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]

class Twin(BaseModel):
    pos: list[float]
    model: str
    panels: int | None = None

class Asset(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str; type: str; bus: str; twin: Twin

class Site(BaseModel):
    site: dict; buses: list[dict]; assets: list[Asset]; topology: list[list[str]]
    tariffs: dict; shed_cost_per_kwh: dict = {}; control: dict = {}
    def by_type(self, t: str) -> list[dict]:
        return [a.model_dump() for a in self.assets if a.type == t]

def _min(s: str) -> int:
    h, m = s.split(":"); return int(h) * 60 + int(m)

def validate(c: Site) -> tuple[list[str], list[str]]:
    e, w = [], []
    ids = [a.id for a in c.assets] + [b["id"] for b in c.buses]
    if len(set(ids)) != len(ids): e.append("duplicate ids")
    for i in ids:
        if not re.fullmatch(rf"{c.site['id']}-[A-Z]+-[A-Z0-9]+", i): e.append(f"bad id format: {i}")
    adj = {i: set() for i in ids}
    for a, b in c.topology:
        if a not in adj or b not in adj: e.append(f"topology references unknown id: {a},{b}"); continue
        adj[a].add(b); adj[b].add(a)
    seen, q = {ids[-1]}, deque([ids[-1]])
    while q:
        for n in adj[q.popleft()]:
            if n not in seen: seen.add(n); q.append(n)
    if seen != set(ids): e.append(f"topology not connected, unreachable: {sorted(set(ids) - seen)}")
    if len(c.by_type("grid_tie")) != 1: e.append("need exactly one grid_tie")
    loads = c.by_type("load")
    for l in loads:
        if l.get("tier") not in ("T0", "T1", "T2", "T3") or not l.get("peak_kw"): e.append(f"load {l['id']} needs tier + peak_kw")
    b = c.by_type("battery")
    t0 = sum(l["peak_kw"] for l in loads if l.get("tier") == "T0")
    if b and t0 > b[0]["max_discharge_kw"]: w.append("T0 loads exceed battery discharge: islanded operation cannot supply critical loads")
    for p in c.by_type("pv_array"):
        if p["inverter_kw"] < 0.6 * p["rated_kwp"]: e.append(f"{p['id']}: inverter < 0.6 x kWp")
    for g in c.by_type("grid_tie"):
        if g["max_import_kw"] > 0.9 * g["transformer_kva"]: e.append("max_import_kw > 0.9 x transformer_kva")
    for name, t in c.tariffs.items():
        cnt = [0] * 1440
        for s in t["import"]:
            a, z = _min(s["from"]), _min(s["to"])
            for m in (range(a, z) if a < z else list(range(a, 1440)) + list(range(0, z))): cnt[m] += 1
        if any(x != 1 for x in cnt): e.append(f"tariff {name}: slots must cover 24h without gaps/overlaps")
    return e, w

def load(path: str | Path = ROOT / "config" / "MG01.yaml") -> Site:
    c = Site(**yaml.safe_load(Path(path).read_text()))
    e, _ = validate(c)
    if e: raise ValueError("Registry invalid:\n - " + "\n - ".join(e))
    return c

if __name__ == "__main__":
    c = Site(**yaml.safe_load((ROOT / "config" / "MG01.yaml").read_text()))
    e, w = validate(c)
    for x in w: print("WARN:", x)
    for x in e: print("ERROR:", x)
    print(f"Registry {'INVALID' if e else 'OK'}: {len(c.assets)} assets, {len(c.topology)} edges")
    sys.exit(1 if e else 0)
