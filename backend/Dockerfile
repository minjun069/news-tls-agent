FROM python:3.12-slim-bookworm AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl fonts-nanum libgssapi-krb5-2 unixodbc \
    && curl -sSL -o /tmp/packages-microsoft-prod.deb \
        https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH"

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN mkdir -p /app/downloads /app/logs

FROM runtime AS migrate
CMD ["python", "-m", "db.migrate"]

FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS mcp
CMD ["python", "-m", "mcp_server.server"]
