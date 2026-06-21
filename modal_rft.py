"""Modal deployment entrypoint for the Vance Fireworks RFT bridge."""

from __future__ import annotations

import os

try:
    import modal
except Exception as exc:  # pragma: no cover - optional dependency branch
    raise RuntimeError("Modal is not installed. Install modal to use modal serve/deploy.") from exc


image = (
    modal.Image.debian_slim()
    .pip_install(
        "fastapi>=0.111",
        "uvicorn[standard]>=0.30",
        "openai>=1.0",
        "python-dotenv>=1.0",
        "eval-protocol>=0.2",
    )
    .env(
        {
            "FIREWORKS_MODEL": os.environ.get("FIREWORKS_MODEL", ""),
            "FIREWORKS_BASE_URL": os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"),
        }
    )
    .add_local_dir("agents", remote_path="/root/agents")
    .add_local_dir("vance", remote_path="/root/vance")
    .add_local_dir("rft", remote_path="/root/rft")
    .add_local_dir("data", remote_path="/root/data")
)

app = modal.App("vance-rft-bridge")


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("vance-fireworks", required_keys=["FIREWORKS_API_KEY"]),
    ],
    timeout=300,
)
@modal.asgi_app()
def fastapi_app():
    from rft.remote_server import create_app

    return create_app()
