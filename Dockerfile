FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY agents agents
COPY app app
COPY data data
COPY docs docs
COPY evals evals
COPY hud_env.py hud_env.py
COPY rft rft
COPY tasks tasks
COPY vance vance

RUN pip install --no-cache-dir -e .

ENV VANCE_HOST=0.0.0.0
ENV VANCE_PORT=8000

EXPOSE 8765
CMD ["hud", "serve", "hud_env.py", "--host", "0.0.0.0"]
