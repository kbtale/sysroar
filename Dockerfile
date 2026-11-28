FROM python:3.14-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.14-slim-bookworm AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system sysroar \
    && useradd --system --gid sysroar --create-home sysroar

COPY --from=builder /opt/venv /opt/venv
COPY scripts/entrypoint.sh /usr/local/bin/sysroar-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/sysroar-entrypoint.sh && \
    chmod +x /usr/local/bin/sysroar-entrypoint.sh
COPY . .
RUN chown -R sysroar:sysroar /app

USER sysroar

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/sysroar-entrypoint.sh"]
CMD ["gunicorn", "config.asgi:application", "-k", "uvicorn_worker.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "2"]
