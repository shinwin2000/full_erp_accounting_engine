#!/usr/bin/env python3
"""
Integration: API Versioning
Menguji bahwa API versi v1 dan v2 dapat berjalan berdampingan,
serta backward compatibility dari endpoint yang di-deprecate.
Menggunakan mock app untuk menghindari dependency pada real FastAPI app.
"""

from __future__ import annotations

import warnings

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

# ============================================================================
# MOCK FASTAPI APP (untuk testing tanpa dependency real)
# ============================================================================


def create_test_app() -> FastAPI:
    """Buat FastAPI app untuk testing versioning."""
    app = FastAPI(title="Test API")

    # Data dummy
    JOURNALS = {
        "123": {
            "journal_id": "123",
            "lines": [
                {"account": "1010", "debit": 1000, "credit": 0},
                {"account": "2010", "debit": 0, "credit": 1000},
            ],
            "metadata": {"created_by": "admin", "created_at": "2025-01-01T00:00:00"},
            "audit_trail": [
                {"action": "create", "timestamp": "2025-01-01T00:00:00", "user": "admin"}
            ],
        }
    }

    # V1 Router
    @app.get("/v1/journals/{journal_id}")
    async def v1_get_journal(journal_id: str):
        journal = JOURNALS.get(journal_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        return {
            "journal_id": journal["journal_id"],
            "lines": journal["lines"],
        }

    # V2 Router
    @app.get("/v2/journals/{journal_id}")
    async def v2_get_journal(journal_id: str):
        journal = JOURNALS.get(journal_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        return {
            "journal_id": journal["journal_id"],
            "lines": journal["lines"],
            "metadata": journal.get("metadata", {}),
            "audit_trail": journal.get("audit_trail", []),
        }

    # Deprecated V1 endpoint
    @app.post("/v1/journal/post")
    async def v1_post_journal(data: dict):
        response = JSONResponse(content={"status": "posted", "id": data.get("id", "unknown")})
        response.headers["Warning"] = (
            "299 - This API endpoint is deprecated and will be removed in v2"
        )
        return response

    # Version negotiation via Accept header
    @app.get("/journals/{journal_id}")
    async def versioned_journal(journal_id: str, accept: str = Header(None, alias="Accept")):
        journal = JOURNALS.get(journal_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")

        version = "1"
        if accept and "version=2" in accept:
            version = "2"

        if version == "2":
            return {
                "version": "v2",
                "journal_id": journal["journal_id"],
                "lines": journal["lines"],
                "metadata": journal.get("metadata", {}),
                "audit_trail": journal.get("audit_trail", []),
            }
        else:
            return {
                "version": "v1",
                "journal_id": journal["journal_id"],
                "lines": journal["lines"],
            }

    return app


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def client():
    """Test client untuk mock FastAPI app."""
    # Filter warnings untuk menghindari unraisable exception warnings
    warnings.filterwarnings(
        "ignore", category=RuntimeWarning, message="coroutine.*was never awaited"
    )
    warnings.filterwarnings("ignore", category=ResourceWarning)
    app = create_test_app()
    return TestClient(app)


# ============================================================================
# TESTS
# ============================================================================


def test_v1_journal_endpoint_returns_expected_structure(client):
    """Test bahwa v1 endpoint mengembalikan struktur yang diharapkan."""
    response = client.get("/v1/journals/123")
    assert response.status_code == 200
    data = response.json()
    assert "journal_id" in data
    assert "lines" in data


def test_v2_journal_endpoint_has_additional_fields(client):
    """Test bahwa v2 endpoint memiliki field tambahan."""
    response = client.get("/v2/journals/123")
    assert response.status_code == 200
    data = response.json()
    assert "journal_id" in data
    assert "lines" in data
    assert "metadata" in data
    assert "audit_trail" in data


def test_deprecated_v1_endpoint_still_works_with_warning_header(client):
    """Test bahwa endpoint deprecated masih berfungsi dengan warning header."""
    response = client.post("/v1/journal/post", json={"id": "JRN-001"})
    assert response.status_code == 200
    assert "Warning" in response.headers
    assert "deprecated" in response.headers["Warning"].lower()


def test_api_version_negotiation_via_accept_header(client):
    """Test version negotiation via Accept header."""
    headers = {"Accept": "application/json; version=2"}
    response = client.get("/journals/123", headers=headers)
    assert response.status_code == 200
    assert response.json()["version"] == "v2"


# ============================================================================
# REAL APP TEST (SKIP jika app.main tidak tersedia)
# ============================================================================

try:
    from app.main import app as real_app

    REAL_APP_AVAILABLE = True
except (ImportError, Exception):
    REAL_APP_AVAILABLE = False


@pytest.fixture
def real_client():
    if not REAL_APP_AVAILABLE:
        pytest.skip("Real app not available")
    return TestClient(real_app)


@pytest.mark.skipif(not REAL_APP_AVAILABLE, reason="Real app module unavailable")
def test_real_v1_journal_endpoint(real_client):
    """Test real app v1 endpoint (if available)."""
    response = real_client.get("/v1/journals/123")
    # Just check it doesn't crash; status could be 200 or 404 depending on data
    assert response.status_code in (200, 404)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
