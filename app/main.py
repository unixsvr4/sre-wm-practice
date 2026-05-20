"""
Weedmaps SRE demo — FastAPI microservice
Demonstrates: four golden signals, OpenTelemetry traces, structured JSON logging.
"""
import os
import time
import random
import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST,
)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# ── Structured JSON logging ─────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

# ── OpenTelemetry setup ─────────────────────────────────────────────────────
OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://otel-collector:4317")
_provider = TracerProvider()
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(_provider)
tracer = trace.get_tracer(__name__)

# ── Four Golden Signals ─────────────────────────────────────────────────────
# 1. Latency
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
# 2. Traffic
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
# 3. Errors
ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP errors by endpoint and type",
    ["endpoint", "error_type"],
)
# 4. Saturation
REQUESTS_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "HTTP requests currently being processed",
)

app = FastAPI(title="weedmaps-sre-demo", version="1.0.0")


@app.middleware("http")
async def golden_signals_middleware(request: Request, call_next):
    REQUESTS_IN_FLIGHT.inc()
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    path = request.url.path
    REQUEST_COUNT.labels(
        method=request.method, endpoint=path, status_code=response.status_code
    ).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=path).observe(duration)
    REQUESTS_IN_FLIGHT.dec()
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/products")
def list_products():
    with tracer.start_as_current_span("list-products") as span:
        span.set_attribute("db.operation", "SELECT")
        time.sleep(random.uniform(0.01, 0.06))
        log.info("products.listed", count=42)
        return {"products": [{"id": i, "name": f"strain-{i}", "price": round(random.uniform(8, 45), 2)} for i in range(1, 6)]}


@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    with tracer.start_as_current_span("get-product") as span:
        span.set_attribute("product.id", product_id)
        time.sleep(random.uniform(0.005, 0.04))
        if product_id > 100:
            ERROR_COUNT.labels(endpoint="/api/products/{id}", error_type="not_found").inc()
            log.warning("product.not_found", product_id=product_id)
            raise HTTPException(status_code=404, detail="Product not found")
        # 5% of requests are slow (p99 scenario to demo histogram_quantile)
        if random.random() < 0.05:
            time.sleep(random.uniform(0.45, 0.9))
        log.info("product.fetched", product_id=product_id)
        return {"id": product_id, "name": f"strain-{product_id}", "price": 12.99}


@app.get("/api/orders")
def list_orders():
    with tracer.start_as_current_span("list-orders") as span:
        # 2% error rate — enough to see on Grafana, not enough to burn SLO
        if random.random() < 0.02:
            ERROR_COUNT.labels(endpoint="/api/orders", error_type="db_timeout").inc()
            log.error("orders.db_timeout", timeout_ms=5000)
            raise HTTPException(status_code=500, detail="Database timeout")
        time.sleep(random.uniform(0.02, 0.12))
        log.info("orders.listed", count=7)
        return {"orders": [{"id": f"ord-{i}", "status": "completed"} for i in range(1, 4)]}


@app.post("/api/orders")
async def create_order(request: Request):
    with tracer.start_as_current_span("create-order") as span:
        time.sleep(random.uniform(0.05, 0.18))
        order_id = f"ord-{random.randint(1000, 9999)}"
        span.set_attribute("order.id", order_id)
        log.info("order.created", order_id=order_id)
        return {"order_id": order_id, "status": "pending"}
