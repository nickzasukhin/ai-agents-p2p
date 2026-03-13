# Orchestrator service — manages personal cloud agent containers
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl util-linux && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi>=0.115 \
    "uvicorn[standard]>=0.30" \
    pydantic-settings>=2.5 \
    "pydantic[email]>=2.0" \
    structlog>=24.0 \
    aiosqlite>=0.20 \
    httpx>=0.27 \
    docker>=7.0

COPY orchestrator/ /app/orchestrator/
COPY orchestrator/run.py /app/run.py

ENV ORCH_HOST=0.0.0.0 \
    ORCH_PORT=8000 \
    ORCH_DB_PATH=/data/orchestrator.db \
    ORCH_JWT_SECRET=change-me-in-production \
    ORCH_AGENT_IMAGE=a2a-agent:latest \
    ORCH_AGENT_DATA_ROOT=/opt/agents/data \
    ORCH_DOMAIN=agents.devpunks.io \
    ORCH_BASE_URL=https://agents.devpunks.io \
    ORCH_NGINX_CONF_DIR=/etc/nginx/conf.d/agents

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "run.py"]
