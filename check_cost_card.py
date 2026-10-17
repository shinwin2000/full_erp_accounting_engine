#!/usr/bin/env python3
"""Verifikasi struktur tabel manufacturing_cost_card."""
import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@127.0.0.1:5432/erp_db"
    )

    print("=== Kolom manufacturing_cost_card ===")
    cols = await conn.fetch(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'manufacturing_cost_card'
        ORDER BY ordinal_position
        """
    )
    for c in cols:
        print(
            f"  {c['column_name']:25s} "
            f"{c['data_type']:20s} "
            f"null={c['is_nullable']:3s} "
            f"default={c['column_default']}"
        )

    print()
    print("=== Constraints ===")
    cons = await conn.fetch(
        """
        SELECT constraint_name, constraint_type
        FROM information_schema.table_constraints
        WHERE table_name = 'manufacturing_cost_card'
        """
    )
    for c in cons:
        print(f"  {c['constraint_type']:12s} {c['constraint_name']}")

    print()
    print("=== Index ===")
    idx = await conn.fetch(
        "SELECT indexname FROM pg_indexes "
        "WHERE tablename = 'manufacturing_cost_card'"
    )
    for i in idx:
        print(f"  {i['indexname']}")

    print()
    print("=== Data 5 baris terbaru ===")
    rows = await conn.fetch(
        """
        SELECT id, total_cost, quantity_base, unit_cost,
               quantity_produced, status, legal_entity_id
        FROM manufacturing_cost_card
        ORDER BY created_at DESC
        LIMIT 5
        """
    )
    for r in rows:
        print(
            f"  id={r['id']} "
            f"total={r['total_cost']} "
            f"qb={r['quantity_base']} "
            f"unit={r['unit_cost']} "
            f"produced={r['quantity_produced']} "
            f"status={r['status']} "
            f"le={r['legal_entity_id']}"
        )

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
    