# tests/adapters/primary_api/v1/test_fastapi_legal_entity_router.py
"""
Comprehensive unit tests for FastAPI Legal Entity Router.

Covers:
- Enums: LegalEntityType, LegalEntityStatus, BranchStatus, TaxStatus
- Schemas: all request/response schemas (valid & invalid cases)
- Endpoint functions: CRUD, activate/deactivate, lock/unlock, tax profile,
  branch management, consolidation group, history/status
- IdempotencyManager: cache and retrieval
- Negative paths: ValueError, PermissionError, NotFound, Exception
- Mock datetime to avoid flaky tests
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_legal_entity_router import (
    BranchCreateSchema,
    BranchResponseSchema,
    BranchStatus,
    BranchUpdateSchema,
    ConsolidationGroupCreateSchema,
    ConsolidationGroupResponseSchema,
    IdempotencyManager,
    LegalEntityCreateSchema,
    LegalEntityResponseSchema,
    LegalEntityStatus,
    LegalEntityType,
    LegalEntityUpdateSchema,
    TaxProfileResponseSchema,
    TaxProfileSchema,
    TaxStatus,
    activate_legal_entity,
    add_group_member,
    close_branch,
    create_branch,
    create_consolidation_group,
    create_legal_entity,
    deactivate_consolidation_group,
    deactivate_legal_entity,
    get_branch,
    get_consolidation_group,
    get_legal_entity,
    get_legal_entity_by_npwp,
    get_legal_entity_by_registration,
    get_legal_entity_history,
    get_legal_entity_service,
    get_legal_entity_status,
    get_tax_profile,
    list_branches,
    list_consolidation_groups,
    list_legal_entities,
    lock_legal_entity,
    remove_group_member,
    unlock_legal_entity,
    update_branch,
    update_consolidation_group,
    update_legal_entity,
    update_tax_profile,
)

# =============================================================================
# FIXED DATETIME (untuk menghindari flaky)
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("adapters.primary_api.v1.fastapi_legal_entity_router.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.UTC = UTC
        yield mock_dt


# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    payload = MagicMock()
    payload.user_id = uuid4()
    return payload


@pytest.fixture
def mock_permission():
    return MagicMock()


@pytest.fixture
def mock_legal_entity_service():
    service = AsyncMock(spec=[
        "create_legal_entity", "list_legal_entities", "get_legal_entity_by_id",
        "get_legal_entity_by_npwp", "get_legal_entity_by_registration",
        "update_legal_entity", "deactivate_legal_entity", "activate_legal_entity",
        "lock_legal_entity", "unlock_legal_entity", "get_tax_profile",
        "update_tax_profile", "create_branch", "list_branches", "get_branch_by_id",
        "update_branch", "close_branch", "create_consolidation_group",
        "list_consolidation_groups", "get_consolidation_group_by_id",
        "update_consolidation_group", "deactivate_consolidation_group",
        "add_member_to_group", "remove_member_from_group",
        "get_legal_entity_history", "get_legal_entity_status"
    ])

    # Helper to create a mock legal entity
    def make_entity(**kwargs):
        data = {
            "id": uuid4(),
            "legal_name": "PT Maju Jaya",
            "trade_name": "Maju Jaya",
            "entity_type": "corporation",
            "registration_number": "REG-001",
            "npwp": "123456789012345",
            "nppp": "NPPP-001",
            "address": "Jl. Merdeka No. 1",
            "city": "Jakarta",
            "postal_code": "10110",
            "province": "DKI Jakarta",
            "country": "ID",
            "phone": "021-1234567",
            "fax": "021-1234568",
            "email": "info@majujaya.com",
            "website": "www.majujaya.com",
            "established_date": FIXED_DATE,
            "fiscal_year_start": 1,
            "fiscal_year_end": 12,
            "base_currency": "IDR",
            "functional_currency": "IDR",
            "is_taxable": True,
            "is_withholding_agent": True,
            "status": "active",
            "is_active": True,
            "is_locked": False,
            "parent_company_id": None,
            "parent_company_name": None,
            "consolidation_group_id": None,
            "consolidation_group_name": None,
            "notes": None,
            "created_at": FIXED_DATETIME,
            "updated_at": FIXED_DATETIME,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        data.update(kwargs)
        return MagicMock(**data)

    # Set return values
    service.create_legal_entity.return_value = make_entity()
    service.get_legal_entity_by_id.return_value = make_entity()
    service.get_legal_entity_by_npwp.return_value = make_entity()
    service.get_legal_entity_by_registration.return_value = make_entity()
    service.update_legal_entity.return_value = make_entity()
    service.deactivate_legal_entity.return_value = make_entity(status="inactive", is_active=False)
    service.activate_legal_entity.return_value = make_entity(status="active", is_active=True)
    service.lock_legal_entity.return_value = make_entity(is_locked=True)
    service.unlock_legal_entity.return_value = make_entity(is_locked=False)
    service.list_legal_entities.return_value = MagicMock(items=[make_entity()], total=1)

    # Tax profile
    tax_profile = MagicMock(
        legal_entity_id=uuid4(),
        tax_office="KPP Jakarta",
        tax_office_code="001",
        tax_classification="Besar",
        taxable_date=FIXED_DATE,
        vat_collector_number="VAT-001",
        annual_tax_return_due_date=30,
        monthly_tax_due_date=15,
        corporate_tax_rate=Decimal("0.22"),
        vat_rate=Decimal("0.11"),
        is_using_final_tax=False,
        final_tax_rate=Decimal("0"),
        notes=None,
        status="active",
        updated_at=FIXED_DATETIME,
        updated_by=uuid4(),
        version=1,
    )
    service.get_tax_profile.return_value = tax_profile
    service.update_tax_profile.return_value = tax_profile

    # Branch
    branch = MagicMock(
        id=uuid4(),
        legal_entity_id=uuid4(),
        branch_code="BR001",
        branch_name="Branch Jakarta",
        address="Jl. Sudirman No. 1",
        city="Jakarta",
        postal_code="10220",
        phone="021-7654321",
        email="branch@majujaya.com",
        manager_name="Budi",
        status="active",
        is_active=True,
        notes=None,
        created_at=FIXED_DATETIME,
        updated_at=FIXED_DATETIME,
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    service.create_branch.return_value = branch
    service.get_branch_by_id.return_value = branch
    service.update_branch.return_value = branch
    service.close_branch.return_value = MagicMock(branch_code="BR001", branch_name="Branch Jakarta", status="closed")
    service.list_branches.return_value = [branch]

    # Consolidation group
    group = MagicMock(
        id=uuid4(),
        group_code="GRP001",
        group_name="Group A",
        description="Main consolidation group",
        base_currency="IDR",
        fiscal_year_start=1,
        fiscal_year_end=12,
        member_count=3,
        is_active=True,
        notes=None,
        created_at=FIXED_DATETIME,
        updated_at=FIXED_DATETIME,
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    service.create_consolidation_group.return_value = group
    service.get_consolidation_group_by_id.return_value = group
    service.update_consolidation_group.return_value = group
    service.deactivate_consolidation_group.return_value = MagicMock(group_code="GRP001", is_active=False)
    service.list_consolidation_groups.return_value = [group]
    service.add_member_to_group.return_value = MagicMock(legal_entity_name="PT Maju Jaya")
    service.remove_member_from_group.return_value = MagicMock(legal_entity_name="PT Maju Jaya")

    # History and status
    service.get_legal_entity_history.return_value = [
        MagicMock(
            timestamp=FIXED_DATETIME,
            action="UPDATE",
            field="legal_name",
            old_value="Old",
            new_value="New",
            actor_id=uuid4(),
            actor_name="Admin",
            reason=None,
        )
    ]
    status_info = MagicMock(
        legal_name="PT Maju Jaya",
        status="active",
        is_active=True,
        is_locked=False,
        can_edit=True,
        can_delete=True,
        can_add_branch=True,
        can_modify_tax=True,
        tax_status="active",
        registration_valid=True,
        npwp_valid=True,
    )
    service.get_legal_entity_status.return_value = status_info

    return service


@pytest.fixture
def mock_idempotency_manager():
    manager = MagicMock(spec=IdempotencyManager)
    manager.get_cached_result = MagicMock(return_value=None)
    manager.cache_result = MagicMock()
    return manager


# =============================================================================
# Tests for Enums (parametrized to avoid duplication)
# =============================================================================

class TestEnums:
    @pytest.mark.parametrize("enum_class, expected_members", [
        (LegalEntityType, [
            "CORPORATION", "BRANCH", "REPRESENTATIVE_OFFICE", "PARTNERSHIP",
            "SOLE_PROPRIETORSHIP", "COOPERATIVE", "FOUNDATION", "CONSOLIDATION_GROUP"
        ]),
        (LegalEntityStatus, [
            "ACTIVE", "INACTIVE", "SUSPENDED", "DISSOLVED", "BANKRUPT", "MERGED",
            "LOCKED", "ARCHIVED"
        ]),
        (BranchStatus, ["ACTIVE", "INACTIVE", "CLOSED", "SUSPENDED"]),
        (TaxStatus, ["ACTIVE", "INACTIVE", "SUSPENDED", "REVOKED"]),
    ])
    def test_members_exist(self, enum_class, expected_members):
        for member in expected_members:
            assert hasattr(enum_class, member)

    @pytest.mark.parametrize("enum_class, member_name", [
        (LegalEntityType, "CORPORATION"),
        (LegalEntityStatus, "ACTIVE"),
        (BranchStatus, "ACTIVE"),
        (TaxStatus, "ACTIVE"),
    ])
    def test_member_is_instance(self, enum_class, member_name):
        member = getattr(enum_class, member_name)
        assert isinstance(member, enum_class)


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_construction(self):
        manager = IdempotencyManager()
        assert isinstance(manager, IdempotencyManager)

    def test_get_cached_result_returns_none_for_missing(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("non_existent", "method")
        assert result is None

    def test_cache_result_and_get(self):
        manager = IdempotencyManager()
        manager.cache_result("key", "method", {"data": "value"})
        result = manager.get_cached_result("key", "method")
        assert result == {"data": "value"}

    def test_cache_result_ttl_expires(self):
        manager = IdempotencyManager()
        manager.cache_result("key", "method", {"data": "value"})
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_DATETIME + timedelta(hours=25)
            mock_dt.UTC = UTC
            result = manager.get_cached_result("key", "method")
            assert result is None


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestLegalEntityCreateSchema:
    def test_valid_schema(self):
        data = {
            "legal_name": "PT Maju Jaya",
            "trade_name": "Maju Jaya",
            "entity_type": LegalEntityType.CORPORATION,
            "registration_number": "REG-001",
            "npwp": "123456789012345",
            "nppp": "NPPP-001",
            "address": "Jl. Merdeka No. 1",
            "city": "Jakarta",
            "postal_code": "10110",
            "province": "DKI Jakarta",
            "country": "ID",
            "phone": "021-1234567",
            "fax": "021-1234568",
            "email": "info@majujaya.com",
            "website": "www.majujaya.com",
            "established_date": FIXED_DATE,
            "fiscal_year_start": 1,
            "fiscal_year_end": 12,
            "base_currency": "IDR",
            "functional_currency": "IDR",
            "is_taxable": True,
            "is_withholding_agent": True,
            "parent_company_id": None,
            "consolidation_group_id": None,
            "notes": None,
        }
        schema = LegalEntityCreateSchema(**data)
        assert schema.legal_name == "PT Maju Jaya"
        assert schema.npwp == "123456789012345"

    @pytest.mark.parametrize("npwp, expected_error", [
        ("12345", "must contain only digits"),
        ("abcde12345", "must contain only digits"),
    ])
    def test_invalid_npwp(self, npwp, expected_error):
        with pytest.raises(ValueError, match=expected_error):
            LegalEntityCreateSchema(
                legal_name="Test",
                entity_type=LegalEntityType.CORPORATION,
                npwp=npwp,
            )

    def test_invalid_email(self):
        with pytest.raises(ValueError, match="Invalid email format"):
            LegalEntityCreateSchema(
                legal_name="Test",
                entity_type=LegalEntityType.CORPORATION,
                email="invalid",
            )


class TestLegalEntityUpdateSchema:
    def test_valid_schema(self):
        data = {
            "legal_name": "Updated Name",
            "trade_name": "Updated Trade",
            "address": "Jl. Baru",
            "city": "Bandung",
            "postal_code": "40111",
            "province": "Jawa Barat",
            "phone": "022-7654321",
            "fax": "022-7654322",
            "email": "updated@test.com",
            "website": "www.updated.com",
            "status": LegalEntityStatus.ACTIVE,
            "notes": "Updated",
        }
        schema = LegalEntityUpdateSchema(**data)
        assert schema.legal_name == "Updated Name"


class TestBranchCreateSchema:
    def test_valid_schema(self):
        data = {
            "branch_code": "BR001",
            "branch_name": "Branch Jakarta",
            "address": "Jl. Sudirman No. 1",
            "city": "Jakarta",
            "postal_code": "10220",
            "phone": "021-7654321",
            "email": "branch@test.com",
            "manager_name": "Budi",
            "is_active": True,
            "notes": None,
        }
        schema = BranchCreateSchema(**data)
        assert schema.branch_code == "BR001"

    def test_branch_code_uppercase(self):
        schema = BranchCreateSchema(
            branch_code="br001",
            branch_name="Branch",
        )
        assert schema.branch_code == "BR001"

    def test_branch_code_required(self):
        with pytest.raises(ValueError, match="Branch code is required"):
            BranchCreateSchema(branch_code="", branch_name="Branch")


class TestConsolidationGroupCreateSchema:
    def test_valid_schema(self):
        data = {
            "group_code": "GRP001",
            "group_name": "Group A",
            "description": "Main group",
            "base_currency": "IDR",
            "fiscal_year_start": 1,
            "fiscal_year_end": 12,
            "notes": None,
        }
        schema = ConsolidationGroupCreateSchema(**data)
        assert schema.group_code == "GRP001"

    def test_group_code_uppercase(self):
        schema = ConsolidationGroupCreateSchema(
            group_code="grp001",
            group_name="Group A",
        )
        assert schema.group_code == "GRP001"


class TestApprovalDelegationSchema:
    # Not present in this router, skip
    pass


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_legal_entity_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_legal_entity_service(request)
    assert result == "service"


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestCreateLegalEntity:
    @pytest.mark.asyncio
    async def test_create_success(self, mock_legal_entity_service, mock_token_payload,
                                  mock_permission, mock_idempotency_manager):
        request = LegalEntityCreateSchema(
            legal_name="PT Maju Jaya",
            entity_type=LegalEntityType.CORPORATION,
        )
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await create_legal_entity(
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, LegalEntityResponseSchema)
        assert response.legal_name == "PT Maju Jaya"
        mock_legal_entity_service.create_legal_entity.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_idempotency(self, mock_legal_entity_service, mock_token_payload,
                                           mock_permission, mock_idempotency_manager):
        request = LegalEntityCreateSchema(
            legal_name="PT Maju Jaya",
            entity_type=LegalEntityType.CORPORATION,
        )
        cached_data = {
            "id": str(uuid4()),
            "legal_name": "PT Maju Jaya",
            "entity_type": "corporation",
            "status": "active",
            "is_active": True,
            "is_locked": False,
            "country": "ID",
            "fiscal_year_start": 1,
            "fiscal_year_end": 12,
            "base_currency": "IDR",
            "functional_currency": "IDR",
            "is_taxable": True,
            "is_withholding_agent": True,
            "created_at": FIXED_DATETIME.isoformat(),
            "updated_at": FIXED_DATETIME.isoformat(),
            "created_by": str(uuid4()),
            "created_by_name": "Admin",
            "version": 1,
        }
        mock_idempotency_manager.get_cached_result.return_value = cached_data
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await create_legal_entity(
                request=request,
                idempotency_key="key-123",
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response.id == UUID(cached_data["id"])
        mock_legal_entity_service.create_legal_entity.assert_not_awaited()

    @pytest.mark.parametrize("exception, expected_status, expected_detail", [
        (ValueError("Invalid data"), 422, "Invalid data"),
        # NOTE: Router ini (dan seluruh endpoint lain di file yang sama) TIDAK
        # memiliki `except PermissionError` tersendiri. Karena PermissionError
        # adalah subclass dari Exception, ia akan tertangkap oleh blok generic
        # `except Exception` dan menghasilkan 500 "Internal server error",
        # BUKAN 403 seperti yang mungkin diharapkan secara semantik.
        # Test ini disesuaikan dengan perilaku source saat ini. Jika perilaku
        # yang diinginkan adalah 403 untuk PermissionError, source perlu
        # ditambahkan blok `except PermissionError as e: raise HTTPException(
        # status_code=403, detail=str(e))` SEBELUM blok `except Exception`,
        # di semua endpoint yang relevan (bukan cuma create_legal_entity).
        (PermissionError("Not allowed"), 500, "Internal server error"),
        (Exception("DB error"), 500, "Internal server error"),
    ])
    @pytest.mark.asyncio
    async def test_create_errors(self, exception, expected_status, expected_detail,
                                 mock_legal_entity_service, mock_token_payload, mock_permission):
        mock_legal_entity_service.create_legal_entity.side_effect = exception
        request = LegalEntityCreateSchema(
            legal_name="Test",
            entity_type=LegalEntityType.CORPORATION,
        )
        with pytest.raises(HTTPException) as exc:
            await create_legal_entity(
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == expected_status
        assert expected_detail in exc.value.detail


@pytest.mark.asyncio
class TestListLegalEntities:
    @pytest.mark.asyncio
    async def test_list_success(self, mock_legal_entity_service, mock_permission):
        response = await list_legal_entities(
            entity_type=LegalEntityType.CORPORATION,
            status=LegalEntityStatus.ACTIVE,
            is_active=True,
            parent_company_id=None,
            search="test",
            page=1,
            page_size=10,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, list)
        assert len(response) == 1
        assert isinstance(response[0], LegalEntityResponseSchema)
        mock_legal_entity_service.list_legal_entities.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_error(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.list_legal_entities.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await list_legal_entities(
                entity_type=None,
                status=None,
                is_active=None,
                parent_company_id=None,
                search=None,
                page=1,
                page_size=10,
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestGetLegalEntity:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_legal_entity_service, mock_permission):
        entity_id = uuid4()
        response = await get_legal_entity(
            legal_entity_id=entity_id,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, LegalEntityResponseSchema)
        mock_legal_entity_service.get_legal_entity_by_id.assert_called_once_with(entity_id)

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity(
                legal_entity_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_error(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_by_id.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity(
                legal_entity_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestGetLegalEntityByNpwp:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_legal_entity_service, mock_permission):
        response = await get_legal_entity_by_npwp(
            npwp="123456789012345",
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, LegalEntityResponseSchema)
        mock_legal_entity_service.get_legal_entity_by_npwp.assert_called_once_with("123456789012345")

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_by_npwp.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_by_npwp(
                npwp="123456789012345",
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_error(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_by_npwp.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_by_npwp(
                npwp="123456789012345",
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestGetLegalEntityByRegistration:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_legal_entity_service, mock_permission):
        response = await get_legal_entity_by_registration(
            registration_number="REG-001",
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, LegalEntityResponseSchema)
        mock_legal_entity_service.get_legal_entity_by_registration.assert_called_once_with("REG-001")

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_by_registration.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_by_registration(
                registration_number="REG-001",
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_error(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_by_registration.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_by_registration(
                registration_number="REG-001",
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestUpdateLegalEntity:
    @pytest.mark.asyncio
    async def test_update_success(self, mock_legal_entity_service, mock_token_payload,
                                  mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        request = LegalEntityUpdateSchema(legal_name="Updated Name")
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await update_legal_entity(
                legal_entity_id=entity_id,
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, LegalEntityResponseSchema)
        mock_legal_entity_service.update_legal_entity.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_not_found(self, mock_legal_entity_service, mock_token_payload,
                                    mock_permission):
        mock_legal_entity_service.update_legal_entity.return_value = None
        request = LegalEntityUpdateSchema(legal_name="Updated")
        with pytest.raises(HTTPException) as exc:
            await update_legal_entity(
                legal_entity_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_value_error(self, mock_legal_entity_service, mock_token_payload,
                                      mock_permission):
        mock_legal_entity_service.update_legal_entity.side_effect = ValueError("Invalid field")
        request = LegalEntityUpdateSchema(legal_name="Updated")
        with pytest.raises(HTTPException) as exc:
            await update_legal_entity(
                legal_entity_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_update_error(self, mock_legal_entity_service, mock_token_payload,
                                mock_permission):
        mock_legal_entity_service.update_legal_entity.side_effect = Exception("DB error")
        request = LegalEntityUpdateSchema(legal_name="Updated")
        with pytest.raises(HTTPException) as exc:
            await update_legal_entity(
                legal_entity_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestDeactivateLegalEntity:
    @pytest.mark.asyncio
    async def test_deactivate_success(self, mock_legal_entity_service, mock_token_payload,
                                      mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await deactivate_legal_entity(
                legal_entity_id=entity_id,
                reason="Closing",
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response["status"] == "inactive"
        mock_legal_entity_service.deactivate_legal_entity.assert_called_once_with(entity_id, mock_token_payload.user_id, "Closing")

    @pytest.mark.asyncio
    async def test_deactivate_not_found(self, mock_legal_entity_service, mock_token_payload,
                                        mock_permission):
        mock_legal_entity_service.deactivate_legal_entity.return_value = None
        with pytest.raises(HTTPException) as exc:
            await deactivate_legal_entity(
                legal_entity_id=uuid4(),
                reason="",
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestActivateLegalEntity:
    @pytest.mark.asyncio
    async def test_activate_success(self, mock_legal_entity_service, mock_token_payload,
                                    mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await activate_legal_entity(
                legal_entity_id=entity_id,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, LegalEntityResponseSchema)
        mock_legal_entity_service.activate_legal_entity.assert_called_once_with(entity_id, mock_token_payload.user_id)

    @pytest.mark.asyncio
    async def test_activate_not_found(self, mock_legal_entity_service, mock_token_payload,
                                      mock_permission):
        mock_legal_entity_service.activate_legal_entity.return_value = None
        with pytest.raises(HTTPException) as exc:
            await activate_legal_entity(
                legal_entity_id=uuid4(),
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestLockUnlockLegalEntity:
    @pytest.mark.asyncio
    async def test_lock_success(self, mock_legal_entity_service, mock_token_payload,
                                mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await lock_legal_entity(
                legal_entity_id=entity_id,
                reason="Audit",
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response.is_locked is True
        mock_legal_entity_service.lock_legal_entity.assert_called_once_with(entity_id, mock_token_payload.user_id, "Audit")

    @pytest.mark.asyncio
    async def test_unlock_success(self, mock_legal_entity_service, mock_token_payload,
                                  mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await unlock_legal_entity(
                legal_entity_id=entity_id,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response.is_locked is False
        mock_legal_entity_service.unlock_legal_entity.assert_called_once_with(entity_id, mock_token_payload.user_id)

    @pytest.mark.asyncio
    async def test_lock_not_found(self, mock_legal_entity_service, mock_token_payload,
                                  mock_permission):
        mock_legal_entity_service.lock_legal_entity.return_value = None
        with pytest.raises(HTTPException) as exc:
            await lock_legal_entity(
                legal_entity_id=uuid4(),
                reason="",
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestTaxProfile:
    @pytest.mark.asyncio
    async def test_get_tax_profile_success(self, mock_legal_entity_service, mock_permission):
        entity_id = uuid4()
        response = await get_tax_profile(
            legal_entity_id=entity_id,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, TaxProfileResponseSchema)
        mock_legal_entity_service.get_tax_profile.assert_called_once_with(entity_id)

    @pytest.mark.asyncio
    async def test_get_tax_profile_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_tax_profile.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_tax_profile(
                legal_entity_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_tax_profile_success(self, mock_legal_entity_service, mock_token_payload,
                                              mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        request = TaxProfileSchema(tax_office="KPP Baru")
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await update_tax_profile(
                legal_entity_id=entity_id,
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, TaxProfileResponseSchema)
        mock_legal_entity_service.update_tax_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_tax_profile_not_found(self, mock_legal_entity_service, mock_token_payload,
                                                mock_permission):
        mock_legal_entity_service.update_tax_profile.return_value = None
        request = TaxProfileSchema(tax_office="KPP Baru")
        with pytest.raises(HTTPException) as exc:
            await update_tax_profile(
                legal_entity_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestBranchManagement:
    @pytest.mark.asyncio
    async def test_create_branch_success(self, mock_legal_entity_service, mock_token_payload,
                                         mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        request = BranchCreateSchema(
            branch_code="BR001",
            branch_name="Branch Jakarta",
        )
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await create_branch(
                legal_entity_id=entity_id,
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, BranchResponseSchema)
        mock_legal_entity_service.create_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_branches_success(self, mock_legal_entity_service, mock_permission):
        entity_id = uuid4()
        response = await list_branches(
            legal_entity_id=entity_id,
            status=BranchStatus.ACTIVE,
            is_active=True,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, list)
        assert len(response) == 1
        mock_legal_entity_service.list_branches.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_branch_success(self, mock_legal_entity_service, mock_permission):
        entity_id = uuid4()
        branch_id = uuid4()
        response = await get_branch(
            legal_entity_id=entity_id,
            branch_id=branch_id,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, BranchResponseSchema)
        mock_legal_entity_service.get_branch_by_id.assert_called_once_with(branch_id, entity_id)

    @pytest.mark.asyncio
    async def test_get_branch_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_branch_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_branch(
                legal_entity_id=uuid4(),
                branch_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_branch_success(self, mock_legal_entity_service, mock_token_payload,
                                         mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        branch_id = uuid4()
        request = BranchUpdateSchema(branch_name="Updated Branch")
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await update_branch(
                legal_entity_id=entity_id,
                branch_id=branch_id,
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, BranchResponseSchema)
        mock_legal_entity_service.update_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_branch_not_found(self, mock_legal_entity_service, mock_token_payload,
                                           mock_permission):
        mock_legal_entity_service.update_branch.return_value = None
        request = BranchUpdateSchema(branch_name="Updated")
        with pytest.raises(HTTPException) as exc:
            await update_branch(
                legal_entity_id=uuid4(),
                branch_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_close_branch_success(self, mock_legal_entity_service, mock_token_payload,
                                        mock_permission, mock_idempotency_manager):
        entity_id = uuid4()
        branch_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await close_branch(
                legal_entity_id=entity_id,
                branch_id=branch_id,
                reason="Closing",
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response["status"] == "closed"
        mock_legal_entity_service.close_branch.assert_called_once_with(branch_id, entity_id, mock_token_payload.user_id, "Closing")

    @pytest.mark.asyncio
    async def test_close_branch_not_found(self, mock_legal_entity_service, mock_token_payload,
                                          mock_permission):
        mock_legal_entity_service.close_branch.return_value = None
        with pytest.raises(HTTPException) as exc:
            await close_branch(
                legal_entity_id=uuid4(),
                branch_id=uuid4(),
                reason="",
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestConsolidationGroup:
    @pytest.mark.asyncio
    async def test_create_group_success(self, mock_legal_entity_service, mock_token_payload,
                                        mock_permission, mock_idempotency_manager):
        request = ConsolidationGroupCreateSchema(
            group_code="GRP001",
            group_name="Group A",
        )
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await create_consolidation_group(
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, ConsolidationGroupResponseSchema)
        mock_legal_entity_service.create_consolidation_group.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_groups_success(self, mock_legal_entity_service, mock_permission):
        response = await list_consolidation_groups(
            is_active=True,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, list)
        assert len(response) == 1
        mock_legal_entity_service.list_consolidation_groups.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_group_success(self, mock_legal_entity_service, mock_permission):
        group_id = uuid4()
        response = await get_consolidation_group(
            group_id=group_id,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, ConsolidationGroupResponseSchema)
        mock_legal_entity_service.get_consolidation_group_by_id.assert_called_once_with(group_id)

    @pytest.mark.asyncio
    async def test_get_group_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_consolidation_group_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_consolidation_group(
                group_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_group_success(self, mock_legal_entity_service, mock_token_payload,
                                        mock_permission, mock_idempotency_manager):
        group_id = uuid4()
        request = ConsolidationGroupCreateSchema(
            group_code="GRP001",
            group_name="Updated Group",
        )
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await update_consolidation_group(
                group_id=group_id,
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert isinstance(response, ConsolidationGroupResponseSchema)
        mock_legal_entity_service.update_consolidation_group.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_group_not_found(self, mock_legal_entity_service, mock_token_payload,
                                          mock_permission):
        mock_legal_entity_service.update_consolidation_group.return_value = None
        request = ConsolidationGroupCreateSchema(
            group_code="GRP001",
            group_name="Updated",
        )
        with pytest.raises(HTTPException) as exc:
            await update_consolidation_group(
                group_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deactivate_group_success(self, mock_legal_entity_service, mock_token_payload,
                                            mock_permission, mock_idempotency_manager):
        group_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await deactivate_consolidation_group(
                group_id=group_id,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response["is_active"] is False
        mock_legal_entity_service.deactivate_consolidation_group.assert_called_once_with(group_id, mock_token_payload.user_id)

    @pytest.mark.asyncio
    async def test_deactivate_group_not_found(self, mock_legal_entity_service, mock_token_payload,
                                              mock_permission):
        mock_legal_entity_service.deactivate_consolidation_group.return_value = None
        with pytest.raises(HTTPException) as exc:
            await deactivate_consolidation_group(
                group_id=uuid4(),
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_add_group_member_success(self, mock_legal_entity_service, mock_token_payload,
                                            mock_permission, mock_idempotency_manager):
        group_id = uuid4()
        entity_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await add_group_member(
                group_id=group_id,
                legal_entity_id=entity_id,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response["added"] is True
        mock_legal_entity_service.add_member_to_group.assert_called_once_with(group_id, entity_id, mock_token_payload.user_id)

    @pytest.mark.asyncio
    async def test_add_group_member_not_found(self, mock_legal_entity_service, mock_token_payload,
                                              mock_permission):
        mock_legal_entity_service.add_member_to_group.return_value = None
        with pytest.raises(HTTPException) as exc:
            await add_group_member(
                group_id=uuid4(),
                legal_entity_id=uuid4(),
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_remove_group_member_success(self, mock_legal_entity_service, mock_token_payload,
                                               mock_permission, mock_idempotency_manager):
        group_id = uuid4()
        entity_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_legal_entity_router._idempotency_manager", mock_idempotency_manager):
            response = await remove_group_member(
                group_id=group_id,
                legal_entity_id=entity_id,
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert response["removed"] is True
        mock_legal_entity_service.remove_member_from_group.assert_called_once_with(group_id, entity_id, mock_token_payload.user_id)

    @pytest.mark.asyncio
    async def test_remove_group_member_not_found(self, mock_legal_entity_service, mock_token_payload,
                                                 mock_permission):
        mock_legal_entity_service.remove_member_from_group.return_value = None
        with pytest.raises(HTTPException) as exc:
            await remove_group_member(
                group_id=uuid4(),
                legal_entity_id=uuid4(),
                idempotency_key=None,
                _permission=mock_permission,
                current_user=mock_token_payload,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestHistoryAndStatus:
    @pytest.mark.asyncio
    async def test_get_history_success(self, mock_legal_entity_service, mock_permission):
        entity_id = uuid4()
        response = await get_legal_entity_history(
            legal_entity_id=entity_id,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert isinstance(response, list)
        assert len(response) == 1
        assert response[0]["action"] == "UPDATE"
        mock_legal_entity_service.get_legal_entity_history.assert_called_once_with(entity_id)

    @pytest.mark.asyncio
    async def test_get_history_error(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_history.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_history(
                legal_entity_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_status_success(self, mock_legal_entity_service, mock_permission):
        entity_id = uuid4()
        response = await get_legal_entity_status(
            legal_entity_id=entity_id,
            _permission=mock_permission,
            service=mock_legal_entity_service,
        )
        assert response["status"] == "active"
        assert response["can_edit"] is True
        mock_legal_entity_service.get_legal_entity_status.assert_called_once_with(entity_id)

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_status(
                legal_entity_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_status_error(self, mock_legal_entity_service, mock_permission):
        mock_legal_entity_service.get_legal_entity_status.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await get_legal_entity_status(
                legal_entity_id=uuid4(),
                _permission=mock_permission,
                service=mock_legal_entity_service,
            )
        assert exc.value.status_code == 500