# leads: FastAPI API + built React SPA in one stateless container.

# --- frontend build ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# --- app ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/entrypoint.sh ./
COPY --from=web /web/dist ./static
RUN useradd -u 10001 -m leads && mkdir -p /data/files && chown leads /data/files
USER leads
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
