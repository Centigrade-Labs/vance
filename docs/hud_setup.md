# HUD Setup

The codebase exposes a HUD v6 template in `hud_env.py` and a lightweight adapter in `vance.hud.HUDAdapter`.

## Contract

```python
from vance.data_loader import load_ai4i_rows
from vance.hud import HUDAdapter
from vance.scenarios import build_twenty_scenarios

adapter = HUDAdapter(build_twenty_scenarios(load_ai4i_rows("data/ai4i2020.csv")))
reset_payload = adapter.reset("resolve", agent_id="hud_agent", mode="fallback")
step_payload = adapter.step(reset_payload["episode_id"], {
    "tool": "inspect_machine",
    "args": {"machine_id": "CNC_12"},
    "rationale": "Inspect affected machine."
})
```

Local fallback does not require environment variables.

