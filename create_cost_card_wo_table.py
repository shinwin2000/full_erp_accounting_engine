#!/usr/bin/env python3
import asyncio
from sqlalchemy import MetaData, Table, Column, String, Numeric, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from infrastructure.database.session_factory_sqlalchemy import get_session_factory

async def create_table():
    session_factory = await get_session_factory()
    async with session_factory() as session:
        # Cek apakah tabel sudah ada
        inspector = await session.connection().run_sync(lambda conn: 
            MetaData().reflect(conn, only=["cost_card_work_order"])
        )
        if "cost_card_work_order" in inspector.tables:
            print("Table cost_card_work_order already exists.")
            return

        # Buat tabel
        await session.execute("""
            CREATE TABLE cost_card_work_order (
                id UUID PRIMARY KEY,
                work_order_id UUID NOT NULL,
                work_order_number VARCHAR(50) NOT NULL,
                product_id UUID NOT NULL,
                product_name VARCHAR(200),
                status VARCHAR(20) NOT NULL,
                planned_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
                completed_quantity NUMERIC(20,2) NOT NULL DEFAULT 0,
                material_actual NUMERIC(20,2) NOT NULL DEFAULT 0,
                material_standard NUMERIC(20,2) NOT NULL DEFAULT 0,
                material_variance NUMERIC(20,2) NOT NULL DEFAULT 0,
                labor_actual NUMERIC(20,2) NOT NULL DEFAULT 0,
                labor_standard NUMERIC(20,2) NOT NULL DEFAULT 0,
                labor_variance NUMERIC(20,2) NOT NULL DEFAULT 0,
                overhead_actual NUMERIC(20,2) NOT NULL DEFAULT 0,
                overhead_standard NUMERIC(20,2) NOT NULL DEFAULT 0,
                overhead_variance NUMERIC(20,2) NOT NULL DEFAULT 0,
                total_actual NUMERIC(20,2) NOT NULL DEFAULT 0,
                total_standard NUMERIC(20,2) NOT NULL DEFAULT 0,
                total_variance NUMERIC(20,2) NOT NULL DEFAULT 0,
                unit_actual NUMERIC(20,2) NOT NULL DEFAULT 0,
                unit_standard NUMERIC(20,2) NOT NULL DEFAULT 0,
                unit_variance NUMERIC(20,2) NOT NULL DEFAULT 0,
                last_updated TIMESTAMP WITH TIME ZONE NOT NULL
            );
            CREATE INDEX idx_cost_card_wo_work_order ON cost_card_work_order (work_order_id);
            CREATE INDEX idx_cost_card_wo_product ON cost_card_work_order (product_id);
        """)
        await session.commit()
        print("Table cost_card_work_order created successfully.")

if __name__ == "__main__":
    asyncio.run(create_table())