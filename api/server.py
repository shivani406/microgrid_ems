"""FastAPI: REST + WebSocket + static frontend. Run: python run.py"""
from __future__ import annotations
import asyncio, json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from api.runner import Runner
from simulation.engine import SCENARIOS, FAULTS

R = Runner()
R.playing, R.speed = True, 5          # start running immediately so charts/KPIs fill in
clients: set[WebSocket] = set()
_j = lambda o: o.item() if hasattr(o, "item") else str(o)

async def broadcast():
    msg = json.dumps(R.snapshot(pop=True), default=_j)
    for ws in list(clients):
        try: await ws.send_text(msg)
        except Exception: clients.discard(ws)

async def ticker():
    while True:
        await asyncio.sleep(1)
        if R.playing:
            for _ in range(R.speed): R.step()      # x1 = 1 sim-minute per wall-second
        await broadcast()

@asynccontextmanager
async def lifespan(app):
    t = asyncio.create_task(ticker()); yield; t.cancel()

app = FastAPI(title="Microgrid Digital Twin", lifespan=lifespan)

@app.get("/api/site")
def site():
    c = R.reg
    return dict(site=c.site, buses=c.buses, assets=[a.model_dump() for a in c.assets], topology=c.topology,
                tariffs=c.tariffs, scenarios=list(SCENARIOS), faults=FAULTS)

@app.get("/api/state")
def state(): return json.loads(json.dumps(R.snapshot(), default=_j))

@app.get("/api/history")
def history(every: int = 5):
    h = list(R.hist); return h[::every] + ([h[-1]] if h and (len(h) - 1) % every else [])

@app.post("/api/sim/{action}")
async def sim(action: str, scenario: str | None = None, value: int = 1, fault: str | None = None, dur: int = 120):
    if action == "load":
        if scenario not in SCENARIOS: raise HTTPException(400, "unknown scenario")
        R.reset(scenario); R.playing = True
    elif action == "play": R.playing = True
    elif action == "pause": R.playing = False
    elif action == "reset": R.reset(); R.playing = True
    elif action == "step": R.step()
    elif action == "speed":
        if value not in (1, 5, 20): raise HTTPException(400, "speed must be 1, 5 or 20")
        R.speed = value
    elif action == "fault":
        if fault not in FAULTS: raise HTTPException(400, "unknown fault")
        R.sim.inject(fault, dur)
    else: raise HTTPException(404)
    await broadcast()
    return {"ok": True, "playing": R.playing, "speed": R.speed, "scenario": R.scenario}

@app.websocket("/ws/live")
async def live(ws: WebSocket):
    await ws.accept(); clients.add(ws)
    await ws.send_text(json.dumps(R.snapshot(), default=_j))   # full snapshot on connect
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: clients.discard(ws)

app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "frontend", html=True), name="ui")
