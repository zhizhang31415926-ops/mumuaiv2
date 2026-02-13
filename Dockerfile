# Multi-stage Dockerfile for MuMuAINovel
# Supports multi-arch build: linux/amd64, linux/arm64

ARG USE_CN_MIRROR=false

# Stage 1: build frontend
FROM node:22-alpine AS frontend-builder

ARG USE_CN_MIRROR

WORKDIR /frontend

# Install frontend dependencies
COPY frontend/package*.json ./
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        npm config set registry https://registry.npmmirror.com; \
    fi

# Avoid lockfile registry mismatch
RUN rm -f package-lock.json
RUN npm install

# Build frontend assets
COPY frontend/ ./
RUN sed -i "s|outDir: '../backend/static'|outDir: 'dist'|g" vite.config.ts
RUN npm run build


# Stage 2: final runtime image
FROM python:3.11-slim

ARG USE_CN_MIRROR

WORKDIR /app

# Optional apt mirror switch
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    fi

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./

# Install CPU torch explicitly (no GPU fallback)
RUN pip install --no-cache-dir --default-timeout=1200 --retries 10 \
    torch --index-url https://download.pytorch.org/whl/cpu

# Install backend dependencies
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
        pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# App source
COPY backend/ ./

# Frontend static assets
COPY --from=frontend-builder /frontend/dist ./static

# Migration and startup scripts
COPY backend/alembic-postgres.ini ./alembic.ini
COPY backend/alembic/postgres ./alembic
COPY backend/scripts/entrypoint.sh /app/entrypoint.sh
COPY backend/scripts/migrate.py ./scripts/migrate.py

RUN chmod +x /app/entrypoint.sh
RUN mkdir -p /app/data /app/logs

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
# Force API embedding by default in container runtime
ENV DEFAULT_EMBEDDING_MODE=api

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
