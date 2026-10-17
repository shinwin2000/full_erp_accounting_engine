#!/usr/bin/env python3
"""Debug: panggil endpoint cost-cards langsung tanpa HTTP layer."""
import asyncio
import traceback

from app.main import fastapi_instance
from bootstrap.dependency_container.ioc_container import get_container
from application.service_layer.service_manufacturing import ManufacturingService


async def main():
    async with fastapi_instance.router.lifespan_context(fastapi_instance):
        container = get_container()
        try:
            svc = await container.resolve_async(ManufacturingService)
            print("ManufacturingService resolved:", type(svc))

            from uuid import UUID
            from decimal import Decimal
            from datetime import date

            le = UUID("81171f76-9045-4eb5-9132-76a5d842bb78")
            try:
                result = await svc.create_cost_card(
                    cost_card_code="DBG-DIRECT-001",
                    product_id=le,
                    effective_date=date(2026, 10, 16),
                    expiry_date=None,
                    material_cost=Decimal("200.00"),
                    labor_cost=Decimal("80.00"),
                    overhead_cost=Decimal("40.00"),
                    other_cost=Decimal("0.00"),
                    quantity_base=Decimal("20.00"),
                    unit_of_measure="pcs",
                    breakdown=None,
                    notes="Direct test",
                    created_by=UUID("5e4e5359-9b79-4683-a6b4-c1ada4925925"),
                    legal_entity_id=le,
                )
                print("SUCCESS!")
                print("  total_cost:", result.total_cost)
                print("  unit_cost:", result.unit_cost)
                print("  quantity_base:", result.quantity_base)
            except Exception as e:
                print("ENDPOINT ERROR:")
                traceback.print_exc()
        except Exception as e:
            print("RESOLVE ERROR:")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
    