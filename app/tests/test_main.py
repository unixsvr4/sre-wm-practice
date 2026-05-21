import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_metrics_endpoint():
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"http_requests_total" in r.content


def test_list_products():
    r = client.get("/api/products")
    assert r.status_code == 200
    assert "products" in r.json()
    assert len(r.json()["products"]) == 5


def test_get_product_valid():
    r = client.get("/api/products/1")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == 1
    assert "price" in data


def test_get_product_not_found():
    r = client.get("/api/products/999")
    assert r.status_code == 404


def test_list_orders():
    # 2% DB-timeout rate — retry to reliably hit a 200
    for _ in range(20):
        r = client.get("/api/orders")
        if r.status_code == 200:
            assert "orders" in r.json()
            return
    assert r.status_code == 200


def test_create_order():
    r = client.post("/api/orders")
    assert r.status_code == 200
    data = r.json()
    assert data["order_id"].startswith("ord-")
    assert data["status"] == "pending"
