"""Modal deployment entrypoint for Vance Judge Mode."""

from __future__ import annotations

try:
    import modal
except Exception as exc:  # pragma: no cover - optional dependency branch
    raise RuntimeError("Modal is not installed. Install modal to use modal serve/deploy.") from exc

from app.main import create_app


image = modal.Image.debian_slim().pip_install(
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "openai>=1.0",
    "python-dotenv>=1.0",
)

app = modal.App("vance-safeopsrl")


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("vance-fireworks", required_keys=["FIREWORKS_API_KEY", "FIREWORKS_MODEL"]),
    ],
)
@modal.asgi_app()
def fastapi_app():
    return create_app()

