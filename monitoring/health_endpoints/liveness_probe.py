#!/usr/bin/env python3
"""
Module: liveness_probe.py
Layer: Monitoring / Health Endpoints

Responsibility:
    Menyediakan endpoint /live untuk mengecek apakah aplikasi masih berjalan.
    Liveness probe tidak melakukan pengecekan dependencies, hanya kepastian proses masih hidup.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any


class LivenessProbe:
    """
    Liveness probe untuk mengecek apakah aplikasi masih hidup.
    Selalu mengembalikan status 200 jika proses masih berjalan.
    """

    def __init__(self, app_name: str = "erp-accounting-engine", version: str = "1.0.0"):
        self.app_name = app_name
        self.version = version
        self.startup_time = time.time()

    def get_status(self) -> dict[str, Any]:
        """Mengembalikan status liveness."""
        uptime_seconds = time.time() - self.startup_time
        return {
            "status": "alive",
            "app": self.app_name,
            "version": self.version,
            "uptime_seconds": round(uptime_seconds, 2),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    def as_json(self) -> str:
        """Mengembalikan status sebagai JSON string."""
        return json.dumps(self.get_status(), indent=2)


# Singleton instance
_default_probe = LivenessProbe()


def liveness_probe() -> dict[str, Any]:
    """
    Function yang dapat dipanggil oleh framework web (FastAPI, Flask, etc.)
    untuk endpoint /live.
    """
    return _default_probe.get_status()


# Untuk FastAPI:
# @app.get("/live")
# async def live():
#     return liveness_probe()

# Untuk Flask:
# @app.route("/live")
# def live():
#     return liveness_probe()
