# syntax=docker/dockerfile:1

# ---- Stage 1: builder - instalează dependențele într-un venv izolat ----
FROM python:3.12-slim AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiem DOAR requirements.txt înaintea codului: layer-ul cu pip install
# rămâne în cache cât timp dependențele nu se schimbă.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ---- Stage 2: runtime - doar ce trebuie ca să ruleze aplicația ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# User fără privilegii, cu UID numeric (Kubernetes poate verifica runAsNonRoot doar pe UID numeric).
RUN useradd --system --uid 10001 --no-create-home app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY main.py .

# Versiunea vine din CI la build; e pusă la final ca să nu invalideze layer-urile de mai sus.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

USER 10001
EXPOSE 8000

# Exec form: uvicorn devine PID 1 și primește direct SIGTERM la oprire.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
