FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY agents agents
COPY app app
COPY docs docs
COPY evals evals
COPY tasks tasks
COPY vance vance

RUN pip install --no-cache-dir -e .

ENV VANCE_HOST=0.0.0.0
ENV VANCE_PORT=8000

EXPOSE 8000
CMD ["python", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
