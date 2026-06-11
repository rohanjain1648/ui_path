"""
Integration tests for IntelliFlow AP API.
Run: pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.database import Base, get_db

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)

client = TestClient(app)


# ── Health ───────────────────────────────────────────────────────────────────

def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


# ── Analytics (empty DB) ─────────────────────────────────────────────────────

def test_dashboard_empty():
    res = client.get("/api/analytics/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert data["summary"]["total_invoices"] == 0
    assert data["exceptions"]["open"] == 0


# ── Vendor setup ─────────────────────────────────────────────────────────────

def _create_vendor():
    from backend.models import Vendor
    db = TestingSession()
    v = Vendor(name="Test Vendor Inc.", code="TEST-V", payment_terms="net30", is_active=True)
    db.add(v)
    db.commit()
    db.refresh(v)
    db.close()
    return v


def _create_po(vendor_code="TEST-V"):
    res = client.post("/api/purchase-orders/", json={
        "po_number": "PO-TEST-001",
        "vendor_code": vendor_code,
        "total_amount": 5000.00,
        "currency": "USD",
        "department": "IT",
        "line_items": [
            {"description": "Software License", "quantity": 1, "unit_price": 5000.00, "total_price": 5000.00}
        ]
    })
    return res


# ── PO endpoints ─────────────────────────────────────────────────────────────

def test_create_po_vendor_not_found():
    res = client.post("/api/purchase-orders/", json={
        "po_number": "PO-NOVENDOR",
        "vendor_code": "NONEXISTENT",
        "total_amount": 1000.00,
    })
    assert res.status_code == 404


def test_create_po_success():
    _create_vendor()
    res = _create_po()
    assert res.status_code == 200
    assert res.json()["po_number"] == "PO-TEST-001"


def test_get_po():
    res = client.get("/api/purchase-orders/PO-TEST-001")
    assert res.status_code == 200
    assert res.json()["total_amount"] == 5000.0


def test_list_pos():
    res = client.get("/api/purchase-orders/")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# ── Invoice ingestion ─────────────────────────────────────────────────────────

def test_ingest_invoice_text():
    res = client.post("/api/invoices/ingest/text", json={
        "text": "Invoice #INV-001 from Test Vendor Inc. Amount: $4,950.00 PO: PO-TEST-001",
        "source_channel": "portal"
    })
    assert res.status_code == 200
    data = res.json()
    assert "id" in data
    assert data["status"] in ("received", "extracting", "extracted")
    return data["id"]


def test_list_invoices():
    res = client.get("/api/invoices/")
    assert res.status_code == 200
    assert "invoices" in res.json()
    assert "total" in res.json()


def test_get_invoice_not_found():
    res = client.get("/api/invoices/nonexistent-id")
    assert res.status_code == 404


# ── Exception endpoints ───────────────────────────────────────────────────────

def test_list_exceptions_empty():
    res = client.get("/api/exceptions/")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# ── Approval endpoints ────────────────────────────────────────────────────────

def test_list_approvals():
    res = client.get("/api/approvals/")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_approve_nonexistent():
    res = client.post("/api/approvals/nonexistent/decide", json={"approved": True})
    assert res.status_code == 404


# ── Analytics ─────────────────────────────────────────────────────────────────

def test_sla_metrics():
    res = client.get("/api/analytics/sla")
    assert res.status_code == 200
    assert "compliance_rate_pct" in res.json()


def test_channel_breakdown():
    res = client.get("/api/analytics/channel-breakdown")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
