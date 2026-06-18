from __future__ import annotations

"""
adapters/primary_api/common/fastapi_app_factory.py
===================================================
Menyediakan router dasar (root + health stub) yang diimpor langsung oleh main.py.
Ini adalah satu-satunya file di common/ yang WAJIB ada agar main.py tidak crash.

Semua router lain di v1/ boleh belum ada — main.py akan skip dengan WARNING.
File ini harus selalu ada dan tidak boleh raise ImportError.
"""

from fastapi import APIRouter


def get_root_router() -> APIRouter:
    """
    Mengembalikan router kosong.
    Root endpoint (GET /) didefinisikan langsung di _register_internal_endpoints()
    di main.py, bukan di sini. Router ini adalah placeholder agar import tidak error.
    """
    router = APIRouter()
    return router


def get_health_router() -> APIRouter:
    """
    Mengembalikan router kosong.
    Health endpoints (GET /health, /health/live, /health/ready) didefinisikan
    langsung di _register_internal_endpoints() di main.py.
    Router ini adalah placeholder agar import tidak error.
    """
    router = APIRouter()
    return router
