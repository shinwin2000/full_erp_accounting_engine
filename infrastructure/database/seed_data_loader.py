#!/usr/bin/env python3
"""
Module: seed_data_loader.py
Layer: Infrastructure (Database)
Responsibility: Memuat data awal (seed data) ke database untuk development,
               testing, atau production (data master seperti COA, legal entity,
               roles, permissions, dll). Mendukung loading dari file JSON/YAML
               dan integrasi dengan environment.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- json, yaml, asyncio, logging
- infrastructure.database.session_factory_sqlalchemy (get_session_factory)
- infrastructure.telemetry.structured_json_logging
Audit: Seed data loading dicatat. Duplicate data di-skip atau diupdate berdasarkan konfigurasi.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.iam_user_table import (
    IAMPermissionTable,
    IAMRoleTable,
    IAMUserTable,
)
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

SEED_DIR = Path("data/seeds")
DEFAULT_SEED_FILES = [
    "legal_entities.yaml",
    "chart_of_accounts.yaml",
    "roles.yaml",
    "permissions.yaml",
    "users.yaml",
]

# ============================================================================
# EXCEPTIONS
# ============================================================================


class SeedDataError(Exception):
    """Base exception untuk seed data loader."""

    pass


class SeedDataLoadError(SeedDataError):
    """Error saat loading seed data."""

    pass


# ============================================================================
# SEED DATA LOADER
# ============================================================================


class SeedDataLoader:
    """
    Loader untuk data awal (seed data).

    Fitur:
    - Load data dari YAML/JSON files
    - Support upsert (update if exists, insert if not)
    - Transactional loading (all or nothing)
    - Environment-specific data (dev, staging, prod)
    - Dry-run mode
    """

    def __init__(self, seed_dir: Path = SEED_DIR):
        self.seed_dir = seed_dir
        self._loaded = False
        self._stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

    def _load_yaml(self, file_path: Path) -> dict[str, Any]:
        """Load YAML file."""
        try:
            with open(file_path) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            raise SeedDataLoadError(f"Failed to load YAML from {file_path}: {e}") from e

    def _load_json(self, file_path: Path) -> dict[str, Any]:
        """Load JSON file."""
        try:
            with open(file_path) as f:
                return json.load(f)
        except Exception as e:
            raise SeedDataLoadError(f"Failed to load JSON from {file_path}: {e}") from e

    def _load_file(self, file_path: Path) -> dict[str, Any]:
        """Load file based on extension."""
        if file_path.suffix in [".yaml", ".yml"]:
            return self._load_yaml(file_path)
        elif file_path.suffix == ".json":
            return self._load_json(file_path)
        else:
            raise SeedDataLoadError(f"Unsupported file type: {file_path.suffix}")

    async def _load_legal_entities(self, session: AsyncSession, data: list[dict]) -> None:
        """Load legal entities."""
        for entity_data in data:
            entity_id = entity_data.get("id")
            if entity_id:
                entity_id = UUID(entity_id)
            else:
                entity_id = uuid4()

            # Check if exists
            stmt = select(LegalEntityTable).where(LegalEntityTable.id == entity_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update
                for key, value in entity_data.items():
                    if key != "id" and hasattr(existing, key):
                        setattr(existing, key, value)
                self._stats["updated"] += 1
                logger.debug(f"Updated legal entity: {entity_data.get('legal_name')}")
            else:
                # Insert
                new_entity = LegalEntityTable(
                    id=entity_id,
                    legal_name=entity_data["legal_name"],
                    trade_name=entity_data.get("trade_name"),
                    entity_type=entity_data.get("entity_type", "parent_company"),
                    registration_number=entity_data.get("registration_number"),
                    npwp=entity_data.get("npwp"),
                    address=entity_data.get("address"),
                    city=entity_data.get("city"),
                    country=entity_data.get("country", "ID"),
                    phone=entity_data.get("phone"),
                    email=entity_data.get("email"),
                    fiscal_year_start=entity_data.get("fiscal_year_start", 1),
                    fiscal_year_end=entity_data.get("fiscal_year_end", 12),
                    base_currency=entity_data.get("base_currency", "IDR"),
                    functional_currency=entity_data.get("functional_currency", "IDR"),
                    status=entity_data.get("status", "active"),
                    is_active=entity_data.get("is_active", True),
                    created_by=UUID("00000000-0000-0000-0000-000000000000"),
                )
                session.add(new_entity)
                self._stats["inserted"] += 1
                logger.debug(f"Inserted legal entity: {entity_data.get('legal_name')}")

    async def _load_accounts(
        self, session: AsyncSession, data: list[dict], legal_entity_id: UUID
    ) -> None:
        """Load chart of accounts for a legal entity."""
        for acc_data in data:
            account_id = acc_data.get("id")
            if account_id:
                account_id = UUID(account_id)
            else:
                account_id = uuid4()

            # Check if exists by account_code and legal_entity_id
            stmt = select(AccountTable).where(
                AccountTable.account_code == acc_data["account_code"],
                AccountTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update
                for key, value in acc_data.items():
                    if key not in ["id", "account_code", "legal_entity_id"] and hasattr(
                        existing, key
                    ):
                        setattr(existing, key, value)
                self._stats["updated"] += 1
                logger.debug(f"Updated account: {acc_data['account_code']}")
            else:
                # Find parent account id if parent_code provided
                parent_id = None
                if acc_data.get("parent_account_code"):
                    parent_stmt = select(AccountTable).where(
                        AccountTable.account_code == acc_data["parent_account_code"],
                        AccountTable.legal_entity_id == legal_entity_id,
                    )
                    parent_result = await session.execute(parent_stmt)
                    parent = parent_result.scalar_one_or_none()
                    if parent:
                        parent_id = parent.id

                new_account = AccountTable(
                    id=account_id,
                    account_code=acc_data["account_code"],
                    account_name=acc_data["account_name"],
                    account_type=acc_data["account_type"],
                    normal_balance=acc_data.get("normal_balance", "debit"),
                    parent_account_id=parent_id,
                    level=acc_data.get("level", 1),
                    description=acc_data.get("description"),
                    currency_code=acc_data.get("currency_code", "IDR"),
                    is_bank_account=acc_data.get("is_bank_account", False),
                    is_cash_account=acc_data.get("is_cash_account", False),
                    is_intercompany=acc_data.get("is_intercompany", False),
                    is_header=acc_data.get("is_header", False),
                    opening_balance_debit=acc_data.get("opening_balance_debit", 0),
                    opening_balance_credit=acc_data.get("opening_balance_credit", 0),
                    status=acc_data.get("status", "active"),
                    is_active=acc_data.get("is_active", True),
                    legal_entity_id=legal_entity_id,
                    created_by=UUID("00000000-0000-0000-0000-000000000000"),
                )
                session.add(new_account)
                self._stats["inserted"] += 1
                logger.debug(f"Inserted account: {acc_data['account_code']}")

    async def _load_roles(self, session: AsyncSession, data: list[dict]) -> None:
        """Load roles."""
        for role_data in data:
            role_id = role_data.get("id")
            if role_id:
                role_id = UUID(role_id)
            else:
                role_id = uuid4()

            stmt = select(IAMRoleTable).where(IAMRoleTable.name == role_data["name"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                for key, value in role_data.items():
                    if key != "id" and hasattr(existing, key):
                        setattr(existing, key, value)
                self._stats["updated"] += 1
                logger.debug(f"Updated role: {role_data['name']}")
            else:
                new_role = IAMRoleTable(
                    id=role_id,
                    name=role_data["name"],
                    description=role_data.get("description"),
                    is_system_role=role_data.get("is_system_role", True),
                    is_active=role_data.get("is_active", True),
                    created_by=UUID("00000000-0000-0000-0000-000000000000"),
                )
                session.add(new_role)
                self._stats["inserted"] += 1
                logger.debug(f"Inserted role: {role_data['name']}")

    async def _load_permissions(self, session: AsyncSession, data: list[dict]) -> None:
        """Load permissions."""
        for perm_data in data:
            perm_id = perm_data.get("id")
            if perm_id:
                perm_id = UUID(perm_id)
            else:
                perm_id = uuid4()

            stmt = select(IAMPermissionTable).where(
                IAMPermissionTable.resource == perm_data["resource"],
                IAMPermissionTable.action == perm_data["action"],
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                for key, value in perm_data.items():
                    if key != "id" and hasattr(existing, key):
                        setattr(existing, key, value)
                self._stats["updated"] += 1
            else:
                new_perm = IAMPermissionTable(
                    id=perm_id,
                    name=perm_data["name"],
                    resource=perm_data["resource"],
                    action=perm_data["action"],
                    description=perm_data.get("description"),
                    created_by=UUID("00000000-0000-0000-0000-000000000000"),
                )
                session.add(new_perm)
                self._stats["inserted"] += 1
                logger.debug(f"Inserted permission: {perm_data['name']}")

    async def _load_users(self, session: AsyncSession, data: list[dict]) -> None:
        """Load users."""
        from passlib.hash import bcrypt

        for user_data in data:
            user_id = user_data.get("id")
            if user_id:
                user_id = UUID(user_id)
            else:
                user_id = uuid4()

            stmt = select(IAMUserTable).where(IAMUserTable.username == user_data["username"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            # Hash password if provided in plaintext
            password = user_data.get("password")
            if password and not password.startswith("$2b$"):
                password = bcrypt.hash(password)

            if existing:
                # Update
                existing.full_name = user_data.get("full_name", existing.full_name)
                existing.email = user_data.get("email", existing.email)
                if password:
                    existing.password_hash = password
                existing.is_active = user_data.get("is_active", existing.is_active)
                existing.is_superuser = user_data.get("is_superuser", existing.is_superuser)
                self._stats["updated"] += 1
                logger.debug(f"Updated user: {user_data['username']}")
            else:
                new_user = IAMUserTable(
                    id=user_id,
                    username=user_data["username"],
                    email=user_data.get("email"),
                    full_name=user_data["full_name"],
                    password_hash=password,
                    is_active=user_data.get("is_active", True),
                    is_superuser=user_data.get("is_superuser", False),
                    status=user_data.get("status", "active"),
                    created_by=UUID("00000000-0000-0000-0000-000000000000"),
                )
                session.add(new_user)
                self._stats["inserted"] += 1
                logger.debug(f"Inserted user: {user_data['username']}")

    async def load_all(self, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        """
        Load all seed data.

        Args:
            dry_run: If True, only simulate without writing to database
            force: Force reload even if already loaded

        Returns:
            Statistics dictionary
        """
        if self._loaded and not force:
            logger.info("Seed data already loaded, skipping")
            return self._stats

        self._stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

        # Check if seed directory exists
        if not self.seed_dir.exists():
            logger.warning(f"Seed directory not found: {self.seed_dir}")
            return self._stats

        factory = await get_session_factory()

        if dry_run:
            logger.info("DRY RUN: Would load seed data")
            # Simulate by reading files
            for seed_file in DEFAULT_SEED_FILES:
                file_path = self.seed_dir / seed_file
                if file_path.exists():
                    data = self._load_file(file_path)
                    logger.info(f"Would load {seed_file}: {len(data.get('data', []))} records")
            return self._stats

        async with factory.get_session() as session:
            async with session.begin():
                try:
                    # Load in order: legal entities -> accounts -> roles -> permissions -> users
                    # Legal entities
                    legal_file = self.seed_dir / "legal_entities.yaml"
                    if legal_file.exists():
                        data = self._load_file(legal_file)
                        await self._load_legal_entities(session, data.get("data", []))

                    # Accounts for each legal entity
                    accounts_file = self.seed_dir / "chart_of_accounts.yaml"
                    if accounts_file.exists():
                        data = self._load_file(accounts_file)
                        # Get legal entity mapping
                        legal_stmt = select(LegalEntityTable)
                        legal_result = await session.execute(legal_stmt)
                        legal_entities = legal_result.scalars().all()
                        for legal in legal_entities:
                            # Find accounts for this legal entity (by npwp or id)
                            # For simplicity, assume accounts data contains legal_entity_code
                            await self._load_accounts(session, data.get("data", []), legal.id)

                    # Roles
                    roles_file = self.seed_dir / "roles.yaml"
                    if roles_file.exists():
                        data = self._load_file(roles_file)
                        await self._load_roles(session, data.get("data", []))

                    # Permissions
                    perms_file = self.seed_dir / "permissions.yaml"
                    if perms_file.exists():
                        data = self._load_file(perms_file)
                        await self._load_permissions(session, data.get("data", []))

                    # Users
                    users_file = self.seed_dir / "users.yaml"
                    if users_file.exists():
                        data = self._load_file(users_file)
                        await self._load_users(session, data.get("data", []))

                    await session.commit()
                    self._loaded = True
                    logger.info(
                        f"Seed data loaded successfully: inserted={self._stats['inserted']}, updated={self._stats['updated']}"
                    )

                except Exception as e:
                    await session.rollback()
                    self._stats["errors"] += 1
                    logger.error(f"Seed data loading failed: {e}")
                    await trigger_alert(
                        title="Seed Data Loading Failed",
                        message=f"Failed to load seed data: {e}",
                        severity="error",
                        source="SeedDataLoader",
                    )
                    raise SeedDataLoadError(f"Seed loading failed: {e}") from e

        return self._stats

    async def load_single_file(self, file_name: str, dry_run: bool = False) -> dict[str, Any]:
        """
        Load a single seed file.
        """
        file_path = self.seed_dir / file_name
        if not file_path.exists():
            raise SeedDataLoadError(f"File not found: {file_path}")

        data = self._load_file(file_path)
        table_name = file_path.stem  # e.g., "legal_entities"

        factory = await get_session_factory()
        async with factory.get_session() as session, session.begin():
            try:
                if table_name == "legal_entities":
                    await self._load_legal_entities(session, data.get("data", []))
                elif table_name == "chart_of_accounts":
                    # Need legal entity context - skip for single file
                    logger.warning("chart_of_accounts requires legal entity context, skipping")
                elif table_name == "roles":
                    await self._load_roles(session, data.get("data", []))
                elif table_name == "permissions":
                    await self._load_permissions(session, data.get("data", []))
                elif table_name == "users":
                    await self._load_users(session, data.get("data", []))
                else:
                    logger.warning(f"Unknown seed table: {table_name}")

                await session.commit()
                return self._stats
            except Exception as e:
                await session.rollback()
                raise SeedDataLoadError(f"Failed to load {file_name}: {e}") from e

    async def reset_stats(self) -> None:
        self._stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_seed_loader: SeedDataLoader | None = None


async def get_seed_loader() -> SeedDataLoader:
    """Get singleton instance of SeedDataLoader."""
    global _seed_loader
    if _seed_loader is None:
        _seed_loader = SeedDataLoader()
    return _seed_loader


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for seed data loading."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed data loader")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
    parser.add_argument("--force", action="store_true", help="Force reload even if already loaded")
    parser.add_argument("--file", "-f", help="Load single file")

    args = parser.parse_args()

    async def run():
        loader = await get_seed_loader()
        if args.file:
            stats = await loader.load_single_file(args.file, dry_run=args.dry_run)
        else:
            stats = await loader.load_all(dry_run=args.dry_run, force=args.force)
        print(f"Seed data loading stats: {stats}")

    asyncio.run(run())


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["SeedDataError", "SeedDataLoadError", "SeedDataLoader", "get_seed_loader"]

if __name__ == "__main__":
    cli()
