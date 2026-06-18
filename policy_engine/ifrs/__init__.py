#!/usr/bin/env python3
from __future__ import annotations

"""
Package: policy_engine.ifrs
Responsibility: Implementasi standar IFRS (International Financial Reporting Standards)
               yang diadopsi penuh. Setiap modul menyediakan validator dan aturan
               untuk standar tertentu, identik dengan PSAK yang setara.
"""

from .ias_01_presentation import (
    IAS1PresentationStandard,
    IAS1Validator,
    get_ias1_validator,
)
from .ias_02_inventories import (
    IAS2InventoryMeasurement,
    IAS2Validator,
    get_ias2_validator,
)
from .ias_12_income_taxes import (
    IAS12TaxBase,
    IAS12Validator,
    get_ias12_validator,
)
from .ias_16_ppe import (
    IAS16PPEMeasurement,
    IAS16Validator,
    get_ias16_validator,
)
from .ias_19_employee_benefits import (
    IAS19BenefitType,
    IAS19Validator,
    get_ias19_validator,
)
from .ias_21_foreign_exchange import (
    IAS21FunctionalCurrency,
    IAS21Validator,
    get_ias21_validator,
)
from .ias_36_impairment import (
    IAS36ImpairmentTest,
    IAS36Validator,
    get_ias36_validator,
)
from .ias_37_provisions import (
    IAS37ProvisionType,
    IAS37Validator,
    get_ias37_validator,
)
from .ifrs_9_financial_instruments import (
    IFRS9Validator,
    get_ifrs9_validator,
)
from .ifrs_10_consolidation import (
    IFRS10ControlAssessment,
    IFRS10Validator,
    get_ifrs10_validator,
)
from .ifrs_15_revenue import (
    IFRS15Validator,
    get_ifrs15_validator,
)
from .ifrs_16_leases import (
    IFRS16Validator,
    get_ifrs16_validator,
)
from .ifrs_aggregator import (
    IFRSAggregator,
    IFRSComplianceLevel,
    IFRSComplianceReport,
    IFRSStandard,
    get_ifrs_aggregator,
)
from .ifrs_for_smes import (
    IFRSForSMESection,
    IFRSForSMESValidator,
    get_ifrs_for_smes_validator,
)

__all__ = [
    # IAS 1
    "IAS1PresentationStandard",
    "IAS1Validator",
    "get_ias1_validator",
    # IAS 2
    "IAS2InventoryMeasurement",
    "IAS2Validator",
    "get_ias2_validator",
    # IAS 12
    "IAS12TaxBase",
    "IAS12Validator",
    "get_ias12_validator",
    # IAS 16
    "IAS16PPEMeasurement",
    "IAS16Validator",
    "get_ias16_validator",
    # IAS 19
    "IAS19BenefitType",
    "IAS19Validator",
    "get_ias19_validator",
    # IAS 21
    "IAS21FunctionalCurrency",
    "IAS21Validator",
    "get_ias21_validator",
    # IAS 36
    "IAS36ImpairmentTest",
    "IAS36Validator",
    "get_ias36_validator",
    # IAS 37
    "IAS37ProvisionType",
    "IAS37Validator",
    "get_ias37_validator",
    # IFRS 9
    "IFRS9Validator",
    "get_ifrs9_validator",
    # IFRS 10
    "IFRS10ControlAssessment",
    "IFRS10Validator",
    "get_ifrs10_validator",
    # IFRS 15
    "IFRS15Validator",
    "get_ifrs15_validator",
    # IFRS 16
    "IFRS16Validator",
    "get_ifrs16_validator",
    # IFRS for SMEs
    "IFRSForSMESection",
    "IFRSForSMESValidator",
    "get_ifrs_for_smes_validator",
    # Aggregator
    "IFRSStandard",
    "IFRSComplianceLevel",
    "IFRSComplianceReport",
    "IFRSAggregator",
    "get_ifrs_aggregator",
]
