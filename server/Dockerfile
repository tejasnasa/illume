FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && find /app -name "uvicorn" 2>/dev/null && find / -name "uvicorn" 2>/dev/null

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV=/app/.venv
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]