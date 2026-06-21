# HUD Setup

The codebase exposes a HUD-style adapter in `vance.hud.HUDAdapter`.

## Contract

```python
from vance.hud import HUDAdapter
from vance.state import load_tasks

adapter = HUDAdapter(load_tasks("tasks"))
reset_payload = adapter.reset("task_id", agent_id="hud_agent", mode="live")
step_payload = adapter.step(reset_payload["episode_id"], {
    "tool": "inspect_machine",
    "args": {"machine_id": "MACHINE_ID"},
    "rationale": "Inspect affected machine."
})
```

The local adapter does not require environment variables. It is the runtime contract the HUD setup owner can register with the external HUD platform.
