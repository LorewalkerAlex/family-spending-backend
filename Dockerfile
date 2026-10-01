# syntax=docker/dockerfile:1.7

ARG UV_VERSION=0.10.9
ARG PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

FROM python:3.14-slim-trixie AS runtime

ARG UV_VERSION
ARG PYPI_INDEX_URL

RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 family-spending \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin family-spending

RUN python -m pip install --no-cache-dir --index-url "${PYPI_INDEX_URL}" "uv==${UV_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PATH="/app/.venv/bin:${PATH}" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=10001:10001 src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

RUN mkdir -p /app/data && chown 10001:10001 /app/data
USER 10001:10001

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).read()"]

CMD ["family-spending-api"]
