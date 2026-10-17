#!/usr/bin/env python3
"""Debug: cek token dan response detail."""
import asyncio
from datetime import datetime

from httpx import ASGITransport, AsyncClient

from app.main import fastapi_instance


async def main():
    transport = ASGITransport(app=fastapi_instance)
    unique_code = "DBG-" + datetime.now().strftime("%Y%m%d%H%M%S")

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with fastapi_instance.router.lifespan_context(fastapi_instance):
            # === LOGIN ===
            r = await ac.post(
                "/api/v1/iam/iam/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                    "legal_entity_id": "81171f76-9045-4eb5-9132-76a5d842bb78",
                },
            )
            print("=" * 60)
            print("LOGIN")
            print("=" * 60)
            print("Status:", r.status_code)
            body = r.json()
            print("Body keys:", list(body.keys()))
            token = body.get("access_token")
            print("Token present:", token is not None)
            print("Token length:", len(token) if token else 0)
            print("Token[:80]:", token[:80] if token else "None")
            print()

            if not token:
                print("ERROR: No token received!")
                return

            # === POST cost-card ===
            le = "81171f76-9045-4eb5-9132-76a5d842bb78"
            h = {"Authorization": f"Bearer {token}"}

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
                "notes": "Debug Test",
            }

            print("=" * 60)
            print("POST /cost-cards")
            print("=" * 60)
            print("URL:", f"/api/v1/manufacturing/manufacturing/cost-cards?legal_entity_id={le}")
            print("Headers:", h)
            print("Payload:", payload)
            print()

            r = await ac.post(
                f"/api/v1/manufacturing/manufacturing/cost-cards?legal_entity_id={le}",
                json=payload,
                headers=h,
            )
            print("Status:", r.status_code)
            print("Response headers:", dict(r.headers))
            print("Response body:", r.text[:500])
            print()

            if r.status_code < 400:
                d = r.json()
                print("SUCCESS!")
                print("  id:", d.get("id"))
                print("  total_cost:", d.get("total_cost"))
                print("  unit_cost:", d.get("unit_cost"), "<-- HARUS 16.0")
                print("  quantity_base:", d.get("quantity_base"))
            print()

            # === GET cost-cards ===
            print("=" * 60)
            print("GET /cost-cards")
            print("=" * 60)
            r = await ac.get(
                f"/api/v1/manufacturing/manufacturing/cost-cards?legal_entity_id={le}",
                headers=h,
            )
            print("Status:", r.status_code)
            print("Response body:", r.text[:500])
            if r.status_code == 200:
                cards = r.json()
                print("Count:", len(cards))
                for c in cards[:5]:
                    print(f"  {c.get('cost_card_code'):30s} "
                          f"total={c.get('total_cost')} "
                          f"unit={c.get('unit_cost')} "
                          f"qb={c.get('quantity_base')}")


if __name__ == "__main__":
    asyncio.run(main())