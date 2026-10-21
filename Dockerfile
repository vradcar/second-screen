# Second Screen: one image serving the API, the WebSocket streams and the UI.

# --- build the React UI -------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build            # writes to /build/src/secondscreen/server/static

# --- runtime ------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SECONDSCREEN_DATA=/app/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=web /build/src/secondscreen/server/static ./src/secondscreen/server/static
RUN pip install ".[agents,server,azure]" && useradd --create-home app
COPY data ./data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "secondscreen.server", "--host", "0.0.0.0", "--port", "8000"]
