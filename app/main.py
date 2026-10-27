import os
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

APP_VERSION = os.getenv("APP_VERSION", "dev")

# Metrici custom. Label-urile au valori dintr-un set mic și fix (metodă, rută, status),
# altfel fiecare valoare nouă creează o serie nouă în Prometheus (cardinality explosion).
REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

app = FastAPI(title="homelab-app", version=APP_VERSION)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    # Nu măsurăm scrape-ul Prometheus, altfel metricile s-ar umfla singure.
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    # Folosim template-ul rutei (ex: /items/{id}), nu URL-ul brut.
    # Pentru 404 nu există rută, deci toate intră sub "unmatched".
    route = request.scope.get("route")
    path = route.path if route else "unmatched"

    LATENCY.labels(request.method, path).observe(elapsed)
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    return response


@app.get("/")
def root():
    return {"message": "hello from homelab", "version": APP_VERSION}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
