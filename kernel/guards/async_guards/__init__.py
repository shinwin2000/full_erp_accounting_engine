#!/usr/bin/env python3
"""
Package: kernel.guards.async_guards
Layer: 4 - Kernel / Guards / Async Guards

Responsibility: Guard asinkron yang dijalankan setelah transaksi commit
               (post-commit) untuk deteksi fraud, AML, dan analisis lainnya.
               Tidak mempengaruhi performa transaksi utama.
"""

from __future__ import annotations

# Static imports (no dynamic import, mematuhi aturan layer kernel)
from kernel.guards.async_guards.anti_money_laundering import (
    AMLAlert,
    AMLAlertType,
    AMLScoreLevel,
    AntiMoneyLaunderingEngine,
    get_anti_money_laundering_engine,
)
from kernel.guards.async_guards.fraud_pattern_detector import (
    FraudAlert,
    FraudPatternDetector,
    FraudPatternType,
    FraudSeverity,
    get_fraud_pattern_detector,
)

__version__ = "1.0.0"

# Aliases untuk backward compatibility dengan kode yang mungkin mengimpor nama lama
AMLAlertSeverity = AMLScoreLevel
AntiMoneyLaunderingDetector = AntiMoneyLaunderingEngine
get_aml_detector = get_anti_money_laundering_engine

# Diurutkan secara alfabetis sesuai saran RUF022
__all__ = [
    "AMLAlert",
    "AMLAlertSeverity",
    "AMLAlertType",
    "AMLScoreLevel",
    "AntiMoneyLaunderingDetector",
    "AntiMoneyLaunderingEngine",
    "FraudAlert",
    "FraudPatternDetector",
    "FraudPatternType",
    "FraudSeverity",
    "__version__",
    "get_aml_detector",
    "get_anti_money_laundering_engine",
    "get_fraud_pattern_detector",
]

