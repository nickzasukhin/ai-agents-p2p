# ── Stage 1a: Build frontend ─────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ── Stage 1b: Build user app ──────────────────────────────────
FROM node:20-alpine AS app-build

WORKDIR /app/app
COPY app/package.json app/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY app/ ./
RUN npm run build

# ── Stage 1c: Build 3D visualization ────────────────────────
FROM node:20-alpine AS viz-build

WORKDIR /app/viz
COPY viz/package.json viz/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY viz/ ./
RUN npm run build

# ── Stage 2: Python runtime ─────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# Put venv on PATH so `python` resolves to the venv interpreter
ENV PATH="/app/.venv/bin:$PATH"

COPY src/ src/
COPY scripts/ scripts/

# Pre-download sentence-transformers model into image
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy built frontend (admin), user app + viz
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
COPY --from=app-build /app/app/dist /app/app/dist
COPY --from=viz-build /app/viz/dist /app/viz/dist

# Default data directory (mount a volume here for persistence)
RUN mkdir -p /data/context
VOLUME /data

ENV PORT=9000 \
    DATA_DIR=/data \
    LOG_LEVEL=info \
    AGENT_NAME=Agent \
    OPENAI_API_KEY="" \
    LLM_PROVIDER=openai \
    PEERS="" \
    API_TOKEN="" \
    PUBLIC_URL="" \
    REGISTRY_URLS="" \
    A2A_REGISTRY_ENABLED=true \
    CHAT_MODE=auto

EXPOSE 9000
EXPOSE 10000/udp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:9000/health || exit 1

ENTRYPOINT ["python", "scripts/run_node.py"]
