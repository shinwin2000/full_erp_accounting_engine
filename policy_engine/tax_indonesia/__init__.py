#!/usr/bin/env python3
from __future__ import annotations

"""
Package: policy_engine.tax_indonesia
Responsibility: Implementasi aturan perpajakan Indonesia untuk ERP Accounting Engine.
               Modul-modul berikut mendukung perhitungan PPN, PPh 21, 22, 23, 25, 26,
               PPh 4 ayat 2, PPh Badan, Bea Meterai, serta mesin withholding dan penalty.
"""

from .bea_meterai_calculator import (
    BeaMeteraiCalculationResult,
    BeaMeteraiCalculator,
    BeaMeteraiType,
    get_bea_meterai_calculator,
)
from .penalty_interest_engine import (
    PenaltyCalculationResult,
    PenaltyInterestEngine,
    PenaltyType,
    TaxObligationType,
    get_penalty_interest_engine,
)
from .pph_4_ayat_2_calculator import (
    PPh4Ayat2CalculationResult,
    PPh4Ayat2Calculator,
    PPh4Ayat2Type,
    get_pph4_ayat_2_calculator,
)
from .pph_21_calculator import (
    PPh21CalculationResult,
    PPh21Calculator,
    PPh21Type,
    get_pph21_calculator,
)
from .pph_22_calculator import (
    PPh22CalculationResult,
    PPh22Calculator,
    PPh22Type,
    get_pph22_calculator,
)
from .pph_23_calculator import (
    NPWPStatus,
    PPh23CalculationResult,
    PPh23Calculator,
    PPh23Rate,
    PPh23Type,
    get_pph23_calculator,
)
from .pph_25_calculator import (
    PPh25CalculationResult,
    PPh25Calculator,
    get_pph25_calculator,
)
from .pph_26_calculator import (
    PPh26CalculationResult,
    PPh26Calculator,
    PPh26Type,
    get_pph26_calculator,
)
from .pph_badan_calculator import (
    PPhBadanCalculationResult,
    PPhBadanCalculator,
    PPhBadanType,
    get_pph_badan_calculator,
)
from .ppn_calculator import (
    PPNCalculationResult,
    PPNCalculator,
    PPNStatus,
    PPNTariff,
    PPNType,
    get_ppn_calculator,
)
from .rate_registry_dynamic import (
    DynamicRateRegistry,
    RateType,
    TaxRate,
    TaxType,
    get_dynamic_rate_registry,
)
from .tax_exceptions import (
    NPWPInvalidError,
    PPhPTKPInvalidError,
    PPhTariffNotFoundError,
    PPNCalculationError,
    PPNTariffNotFoundError,
    RateExpiredError,
    RateNotFoundError,
    TaxDataIncompleteError,
    TaxError,
    TaxErrorCode,
    TaxExceptionFactory,
    TaxRegulationChangedError,
    TaxReturnLateError,
    TaxSeverity,
    TaxUnderpaymentError,
)
from .treaty_resolver import (
    TreatyArticle,
    TreatyResolver,
    TreatyType,
    get_treaty_resolver,
)
from .withholding_engine import (
    WithholdingEngine,
    WithholdingRecord,
    WithholdingStatus,
    WithholdingType,
    get_withholding_engine,
)

__all__ = [
    # PPN
    "PPNTariff",
    "PPNStatus",
    "PPNType",
    "PPNCalculationResult",
    "PPNCalculator",
    "get_ppn_calculator",
    # PPh 21
    "PPh21Type",
    "PPh21CalculationResult",
    "PPh21Calculator",
    "get_pph21_calculator",
    # PPh 22
    "PPh22Type",
    "PPh22CalculationResult",
    "PPh22Calculator",
    "get_pph22_calculator",
    # PPh 23
    "PPh23Type",
    "PPh23Rate",
    "NPWPStatus",
    "PPh23CalculationResult",
    "PPh23Calculator",
    "get_pph23_calculator",
    # PPh 25
    "PPh25CalculationResult",
    "PPh25Calculator",
    "get_pph25_calculator",
    # PPh 26
    "PPh26Type",
    "PPh26CalculationResult",
    "PPh26Calculator",
    "get_pph26_calculator",
    # PPh 4 ayat 2
    "PPh4Ayat2Type",
    "PPh4Ayat2CalculationResult",
    "PPh4Ayat2Calculator",
    "get_pph4_ayat_2_calculator",
    # PPh Badan
    "PPhBadanType",
    "PPhBadanCalculationResult",
    "PPhBadanCalculator",
    "get_pph_badan_calculator",
    # Bea Meterai
    "BeaMeteraiType",
    "BeaMeteraiCalculationResult",
    "BeaMeteraiCalculator",
    "get_bea_meterai_calculator",
    # Rate Registry
    "TaxType",
    "RateType",
    "TaxRate",
    "DynamicRateRegistry",
    "get_dynamic_rate_registry",
    # Penalty
    "PenaltyType",
    "TaxObligationType",
    "PenaltyCalculationResult",
    "PenaltyInterestEngine",
    "get_penalty_interest_engine",
    # Withholding
    "WithholdingType",
    "WithholdingStatus",
    "WithholdingRecord",
    "WithholdingEngine",
    "get_withholding_engine",
    # Treaty
    "TreatyType",
    "TreatyArticle",
    "TreatyResolver",
    "get_treaty_resolver",
    # Exceptions
    "TaxErrorCode",
    "TaxSeverity",
    "TaxError",
    "PPNTariffNotFoundError",
    "PPNCalculationError",
    "PPhTariffNotFoundError",
    "PPhPTKPInvalidError",
    "NPWPInvalidError",
    "TaxReturnLateError",
    "TaxUnderpaymentError",
    "RateNotFoundError",
    "RateExpiredError",
    "TaxDataIncompleteError",
    "TaxRegulationChangedError",
    "TaxExceptionFactory",
]
