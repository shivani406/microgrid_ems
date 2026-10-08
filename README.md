# Hybrid Microgrid Digital Twin (MVP of the v2 plan: Phases 0-4, SIM mode)

Run **in this order** (details in the chat reply / below):

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m registry.schema          # 1. validate the asset registry (must print "Registry OK")
python -m pytest -q                # 2. headless safety check across all 10 scenarios
python run.py                      # 3. start server + open http://127.0.0.1:8000
```

In the UI: pick a scenario -> **Load** -> **Play** (Space) -> speed ×1/×5/×20 (keys 1/2/3). **Inject fault** adds a live fault.
Mouse: wheel = zoom, left-drag = orbit, right-drag = pan, click = inspect, double-click = focus. Needs internet once for three.js/fonts (CDN).

## Layout
- `config/MG01.yaml` - asset registry: single source of truth for simulator, controller and the 3D scene
- `registry/schema.py` - pydantic schema + validation rules (Phase 0)
- `simulation/engine.py` - physics (PV, wind, battery, loads, grid), seeded generators, sensor noise, scenarios/faults (Phase 1)
- `controller/controller.py` - rule-based dispatcher, mode FSM (modes 1-10), tiered shedding w/ hysteresis, independent safety supervisor
- `api/runner.py`, `api/server.py` - orchestration, alarms, REST + WebSocket (`/ws/live`)
- `frontend/` - HUD console + three.js 3D twin (no build step)
- `tests/test_smoke.py` - bus balance, SoC bounds, T0 protection, import cap over 2 simulated days x 10 scenarios

## Not yet built (plan items deferred)
Forecasting + 15-min optimiser (controller is reactive/rule-based, i.e. the plan's fallback), MQTT bus, TimescaleDB,
auth/RBAC/audit log, approve/reject workflow, SLD fallback view, Playwright tests, Modbus gateway (Phases 6-8).
Single process in SIM mode only; bound to 127.0.0.1. Do not expose it to a network or connect it to hardware.
