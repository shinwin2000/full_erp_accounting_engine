#!/usr/bin/env python3
"""Debug: cek middleware behavior untuk manufacturing endpoint."""
import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

from httpx import ASGITransport, AsyncClient

from app.main import fastapi_instance


async def main():
    transport = ASGITransport(app=fastapi_instance)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with fastapi_instance.router.lifespan_context(fastapi_instance):
            # Login
            r = await ac.post(
                "/api/v1/iam/iam/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                    "legal_entity_id": "81171f76-9045-4eb5-9132-76a5d842bb78",
                },
            )
            print("LOGIN:", r.status_code)
            if r.status_code != 200:
                print("Login body:", r.text)
                return
            token = r.json()["access_token"]
            print("Token:", token[:50], "...")

            # GET cost-cards
            le = "81171f76-9045-4eb5-9132-76a5d842bb78"
            r = await ac.get(
                f"/api/v1/manufacturing/manufacturing/cost-cards?legal_entity_id={le}",
                headers={"Authorization": f"Bearer {token}"},
            )
            print()
            print("=" * 60)
            print("GET cost-cards:", r.status_code)
            print("Response headers:", dict(r.headers))
            print("Response body:", r.text[:500])


if __name__ == "__main__":
    asyncio.run(main())
    