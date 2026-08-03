# __init__.py - Lazy-loaded exports for application.workflows package

from __future__ import annotations

"""
Package: application.workflows

Business workflows for end-to-end processes.

All submodules are loaded lazily to avoid heavy imports and circular dependencies.
"""

__version__ = "2.0.0"

__all__ = [
    "AuditForensicReconstructionCommand",
    "AuditForensicReconstructionWorkflow",
    "COGSCalculationItem",
    "ForensicReconstructionResult",
    "InventoryToCOGSCommand",
    "InventoryToCOGSResult",
    "InventoryToCOGSWorkflow",
    "ManufacturingCostFlowCommand",
    "ManufacturingCostFlowResult",
    "ManufacturingCostFlowWorkflow",
    "PayrollToGLFullCommand",
    "PayrollToGLFullWorkflow",
    "PayrollWorkflowResult",
    "ProcurementToAPFullCommand",
    "ProcurementToAPFullWorkflow",
    "ProcurementWorkflowResult",
    "ProjectBillingCommand",
    "ProjectBillingResult",
    "ProjectBillingWorkflow",
    "SalesToARFullCommand",
    "SalesToARFullWorkflow",
    "SalesWorkflowResult",
    "TransactionCategory",
    "UMKMWorkflow",
    "UMKMWorkflowCommand",
    "UMKMWorkflowResult",
    "__version__",
    "create_audit_forensic_reconstruction_workflow",
    "create_inventory_to_cogs_workflow",
    "create_manufacturing_cost_flow_workflow",
    "create_payroll_to_gl_full_workflow",
    "create_procurement_to_ap_full_workflow",
    "create_project_billing_workflow",
    "create_sales_to_ar_full_workflow",
    "create_umkm_workflow",
]


def __getattr__(name: str):
    """Lazy-load submodules when an attribute is requested."""
    if name in (
        "AuditForensicReconstructionCommand",
        "AuditForensicReconstructionWorkflow",
        "ForensicReconstructionResult",
        "create_audit_forensic_reconstruction_workflow",
    ):
        from .audit_forensic_reconstruction import (  # noqa: F401
            AuditForensicReconstructionCommand,
            AuditForensicReconstructionWorkflow,
            ForensicReconstructionResult,
            create_audit_forensic_reconstruction_workflow,
        )
        return locals()[name]

    if name in (
        "COGSCalculationItem",
        "InventoryToCOGSCommand",
        "InventoryToCOGSResult",
        "InventoryToCOGSWorkflow",
        "create_inventory_to_cogs_workflow",
    ):
        from .inventory_to_cogs import (  # noqa: F401
            COGSCalculationItem,
            InventoryToCOGSCommand,
            InventoryToCOGSResult,
            InventoryToCOGSWorkflow,
            create_inventory_to_cogs_workflow,
        )
        return locals()[name]

    if name in (
        "ManufacturingCostFlowCommand",
        "ManufacturingCostFlowResult",
        "ManufacturingCostFlowWorkflow",
        "create_manufacturing_cost_flow_workflow",
    ):
        from .manufacturing_cost_flow import (  # noqa: F401
            ManufacturingCostFlowCommand,
            ManufacturingCostFlowResult,
            ManufacturingCostFlowWorkflow,
            create_manufacturing_cost_flow_workflow,
        )
        return locals()[name]

    if name in (
        "PayrollToGLFullCommand",
        "PayrollToGLFullWorkflow",
        "PayrollWorkflowResult",
        "create_payroll_to_gl_full_workflow",
    ):
        from .payroll_to_gl_full import (  # noqa: F401
            PayrollToGLFullCommand,
            PayrollToGLFullWorkflow,
            PayrollWorkflowResult,
            create_payroll_to_gl_full_workflow,
        )
        return locals()[name]

    if name in (
        "ProcurementToAPFullCommand",
        "ProcurementToAPFullWorkflow",
        "ProcurementWorkflowResult",
        "create_procurement_to_ap_full_workflow",
    ):
        from .procurement_to_ap_full import (  # noqa: F401
            ProcurementToAPFullCommand,
            ProcurementToAPFullWorkflow,
            ProcurementWorkflowResult,
            create_procurement_to_ap_full_workflow,
        )
        return locals()[name]

    if name in (
        "ProjectBillingCommand",
        "ProjectBillingResult",
        "ProjectBillingWorkflow",
        "create_project_billing_workflow",
    ):
        from .project_billing_poc import (  # noqa: F401
            ProjectBillingCommand,
            ProjectBillingResult,
            ProjectBillingWorkflow,
            create_project_billing_workflow,
        )
        return locals()[name]

    if name in (
        "SalesToARFullCommand",
        "SalesToARFullWorkflow",
        "SalesWorkflowResult",
        "create_sales_to_ar_full_workflow",
    ):
        from .sales_to_ar_full import (  # noqa: F401
            SalesToARFullCommand,
            SalesToARFullWorkflow,
            SalesWorkflowResult,
            create_sales_to_ar_full_workflow,
        )
        return locals()[name]

    if name in (
        "TransactionCategory",
        "UMKMWorkflow",
        "UMKMWorkflowCommand",
        "UMKMWorkflowResult",
        "create_umkm_workflow",
    ):
        from .umkm_simplified import (  # noqa: F401
            TransactionCategory,
            UMKMWorkflow,
            UMKMWorkflowCommand,
            UMKMWorkflowResult,
            create_umkm_workflow,
        )
        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)

