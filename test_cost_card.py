#!/usr/bin/env python3
"""
Test endpoint POST & GET /manufacturing/cost-cards.
Verifikasi bug fix: unit_cost = total_cost / quantity_base.
"""
import asyncio
from datetime import datetime

import asyncpg
from httpx import ASGITransport, AsyncClient

from app.main import fastapi_instance


async def main():
    transport = ASGITransport(app=fastapi_instance)
    unique_code = "CC-" + datetime.now().strftime("%Y%m%d%H%M%S")
    print("Using cost_card_code:", unique_code)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with fastapi_instance.router.lifespan_context(fastapi_instance):
            # --- Login ---
            r = await ac.post(
                "/api/v1/iam/iam/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                    "legal_entity_id": "81171f76-9045-4eb5-9132-76a5d842bb78",
                },
            )
            token = r.json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}
            le = "81171f76-9045-4eb5-9132-76a5d842bb78"

            # --- POST cost card ---
            payload = {
                "cost_card_code": unique_code,
                "product_id": le,
                "effective_date": "2026-10-16",
                "material_cost": 200.00,
                "labor_cost": 80.00,
                "overhead_cost": 40.00,
                "other_cost": 0.00,
                "quantity_base": 20.00,
                "unit_of_measure": "pcs",
                "notes": "Test 3",
            }
            r = await ac.post(
                f"/api/v1/manufacturing/manufacturing/cost-cards?legal_entity_id={le}",
                json=payload,
                headers=h,
            )
            print("POST /cost-cards:", r.status_code)
            if r.status_code < 400:
                d = r.json()
                print("  id:              ", d.get("id"))
                print("  total_cost:      ", d.get("total_cost"), "<-- HARUS 320.0")
                print("  unit_cost:       ", d.get("unit_cost"), "<-- HARUS 16.0")
                print("  quantity_base:   ", d.get("quantity_base"), "<-- HARUS 20.0")
            else:
                print("  response:", r.text)

            # --- GET cost cards ---
            r = await ac.get(
                f"/api/v1/manufacturing/manufacturing/cost-cards?legal_entity_id={le}",
                headers=h,
            )
            print()
            print("GET /cost-cards:", r.status_code)
            cards = r.json() if r.status_code == 200 else []
            if isinstance(cards, list):
                print(f"  count via API: {len(cards)}")
                for c in cards[:5]:
                    code = c.get("cost_card_code", "")
                    total = c.get("total_cost")
                    unit = c.get("unit_cost")
                    qb = c.get("quantity_base")
                    print(f"    {code:30s} total={total} unit={unit} qb={qb}")
            else:
                print("  response:", cards)

    # --- Cek DB langsung ---
    print()
    print("=== DB check ===")
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@127.0.0.1:5432/erp_db"
    )
    n = await conn.fetchval("SELECT COUNT(*) FROM manufacturing_cost_card")
    print("manufacturing_cost_card rows (DB):", n)

    rows = await conn.fetch(
        """
        SELECT cost_card_id, total_cost, quantity_base, unit_cost, legal_entity_id
        FROM manufacturing_cost_card
        ORDER BY created_at DESC
        LIMIT 3
        """
    )
    for r in rows:
        print(
            f"  DB: total={r['total_cost']} qb={r['quantity_base']} "
            f"unit={r['unit_cost']} le={r['legal_entity_id']}"
        )
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
    