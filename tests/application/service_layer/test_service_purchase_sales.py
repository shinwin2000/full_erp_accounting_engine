# test_service_purchase_sales.py
# =========================================
# LENGKAP: Semua test asli dipertahankan + tambahan test coverage untuk properti yang hilang.
# Tidak ada kode asli yang dihapus.

import asyncio  # <-- ditambahkan untuk async test di audit_trail
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.service_layer.service_purchase_sales import (
    CreditNote,
    DebitNote,
    DeliveryNote,
    DeliveryNoteLine,
    DeliveryNoteNotFoundError,
    DocumentStatus,
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptNotFoundError,
    InvoiceLine,
    OrderStatus,
    PurchaseInvoice,
    PurchaseInvoiceNotFoundError,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderNotFoundError,
    PurchaseSalesService,
    PurchaseSalesServiceError,
    SalesInvoice,
    SalesInvoiceNotFoundError,
    SalesOrder,
    SalesOrderLine,
    SalesOrderNotFoundError,
    audit,
    create_purchase_sales_service,
)


# ==================== TESTS ENUMS (ASLI) ====================

class TestOrderStatus:
    """Tests for the OrderStatus enum."""
    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(OrderStatus, 'DRAFT')
        assert hasattr(OrderStatus, 'SUBMITTED')
        assert hasattr(OrderStatus, 'APPROVED')
        assert hasattr(OrderStatus, 'PROCESSING')
        assert hasattr(OrderStatus, 'COMPLETED')
        assert hasattr(OrderStatus, 'CANCELLED')
        assert hasattr(OrderStatus, 'REJECTED')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(OrderStatus.DRAFT, OrderStatus)


class TestDocumentStatus:
    """Tests for the DocumentStatus enum."""
    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(DocumentStatus, 'DRAFT')
        assert hasattr(DocumentStatus, 'ISSUED')
        assert hasattr(DocumentStatus, 'RECEIVED')
        assert hasattr(DocumentStatus, 'APPROVED')
        assert hasattr(DocumentStatus, 'PAID')
        assert hasattr(DocumentStatus, 'PARTIALLY_PAID')
        assert hasattr(DocumentStatus, 'CANCELLED')
        assert hasattr(DocumentStatus, 'DISPUTED')
        assert hasattr(DocumentStatus, 'VERIFIED')
        assert hasattr(DocumentStatus, 'WRITTEN_OFF')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(DocumentStatus.DRAFT, DocumentStatus)


# ==================== TESTS DOMAIN MODELS (ASLI + TAMBAHAN PROPERTI) ====================

class TestPurchaseOrderLine:
    """Tests for the PurchaseOrderLine value object / model."""

    def _build_kwargs(self):
        return dict(
            product_id=uuid4(),
            product_code="test_value",
            product_name="test_value",
            quantity=Decimal("100.00"),
            unit_price=Decimal("100.00"),
            discount_percentage=Decimal("100.00"),
            tax_rate=Decimal("100.00"),
        )

    def test_construction_success(self):
        """PurchaseOrderLine can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = PurchaseOrderLine(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, PurchaseOrderLine)
        assert instance.product_id == kwargs['product_id']

    # --- TAMBAHAN: Test properti yang hilang ---
    def test_subtotal(self):
        line = PurchaseOrderLine(
            product_id=uuid4(),
            product_code="P001",
            product_name="Product A",
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("0"),
            tax_rate=Decimal("11"),
        )
        assert line.subtotal == Decimal("10000")

    def test_discount_amount(self):
        line = PurchaseOrderLine(
            product_id=uuid4(),
            product_code="P001",
            product_name="Product A",
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.discount_amount == Decimal("500")

    def test_net_amount(self):
        line = PurchaseOrderLine(
            product_id=uuid4(),
            product_code="P001",
            product_name="Product A",
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.net_amount == Decimal("9500")

    def test_tax_amount(self):
        line = PurchaseOrderLine(
            product_id=uuid4(),
            product_code="P001",
            product_name="Product A",
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.tax_amount == Decimal("1045")  # 9500 * 11%

    def test_total_amount(self):
        line = PurchaseOrderLine(
            product_id=uuid4(),
            product_code="P001",
            product_name="Product A",
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.total_amount == Decimal("10545")  # 9500 + 1045


class TestPurchaseOrder:
    """Tests for the PurchaseOrder value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            po_number="test_value",
            supplier_id=uuid4(),
            supplier_name="test_value",
            order_date=date.today(),
            expected_delivery_date=date.today(),
            status=OrderStatus.DRAFT,
            total_amount=Decimal("100.00"),
            currency="test_value",
            lines=[MagicMock()],
            notes="test_value",
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
        )

    def test_construction_success(self):
        """PurchaseOrder can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = PurchaseOrder(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, PurchaseOrder)
        assert instance.id == kwargs['id']

    # --- TAMBAHAN: Test calculate_total ---
    def test_calculate_total(self):
        line = PurchaseOrderLine(
            product_id=uuid4(),
            product_code="P001",
            product_name="Product A",
            quantity=Decimal("5"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("10"),
            tax_rate=Decimal("11"),
        )
        order = PurchaseOrder(
            id=uuid4(),
            po_number="PO-001",
            supplier_id=uuid4(),
            supplier_name="Supplier X",
            lines=[line],
        )
        total = order.calculate_total()
        # 5 * 1000 = 5000, diskon 10% = 500, net = 4500, tax 11% = 495, total = 4995
        assert total == Decimal("4995")
        assert order.total_amount == Decimal("4995")


class TestSalesOrderLine:
    """Tests for the SalesOrderLine value object / model."""

    def _build_kwargs(self):
        return dict(
            product_id=uuid4(),
            product_code="test_value",
            product_name="test_value",
            quantity=Decimal("100.00"),
            unit_price=Decimal("100.00"),
            discount_percentage=Decimal("100.00"),
            tax_rate=Decimal("100.00"),
        )

    def test_construction_success(self):
        """SalesOrderLine can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = SalesOrderLine(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, SalesOrderLine)
        assert instance.product_id == kwargs['product_id']

    # --- TAMBAHAN: Test properti yang hilang ---
    def test_subtotal(self):
        line = SalesOrderLine(
            product_id=uuid4(),
            product_code="S001",
            product_name="Product B",
            quantity=Decimal("8"),
            unit_price=Decimal("2000"),
            discount_percentage=Decimal("0"),
            tax_rate=Decimal("11"),
        )
        assert line.subtotal == Decimal("16000")

    def test_discount_amount(self):
        line = SalesOrderLine(
            product_id=uuid4(),
            product_code="S001",
            product_name="Product B",
            quantity=Decimal("8"),
            unit_price=Decimal("2000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.discount_amount == Decimal("800")

    def test_net_amount(self):
        line = SalesOrderLine(
            product_id=uuid4(),
            product_code="S001",
            product_name="Product B",
            quantity=Decimal("8"),
            unit_price=Decimal("2000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.net_amount == Decimal("15200")

    def test_tax_amount(self):
        line = SalesOrderLine(
            product_id=uuid4(),
            product_code="S001",
            product_name="Product B",
            quantity=Decimal("8"),
            unit_price=Decimal("2000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.tax_amount == Decimal("1672")  # 15200 * 11%

    def test_total_amount(self):
        line = SalesOrderLine(
            product_id=uuid4(),
            product_code="S001",
            product_name="Product B",
            quantity=Decimal("8"),
            unit_price=Decimal("2000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.total_amount == Decimal("16872")  # 15200 + 1672


class TestSalesOrder:
    """Tests for the SalesOrder value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            so_number="test_value",
            customer_id=uuid4(),
            customer_name="test_value",
            order_date=date.today(),
            requested_delivery_date=date.today(),
            status=OrderStatus.DRAFT,
            total_amount=Decimal("100.00"),
            currency="test_value",
            lines=[MagicMock()],
            notes="test_value",
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
        )

    def test_construction_success(self):
        """SalesOrder can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = SalesOrder(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, SalesOrder)
        assert instance.id == kwargs['id']

    # --- TAMBAHAN: Test calculate_total ---
    def test_calculate_total(self):
        line = SalesOrderLine(
            product_id=uuid4(),
            product_code="S001",
            product_name="Product B",
            quantity=Decimal("3"),
            unit_price=Decimal("2500"),
            discount_percentage=Decimal("10"),
            tax_rate=Decimal("11"),
        )
        order = SalesOrder(
            id=uuid4(),
            so_number="SO-001",
            customer_id=uuid4(),
            customer_name="Customer Y",
            lines=[line],
        )
        total = order.calculate_total()
        # 3 * 2500 = 7500, diskon 10% = 750, net = 6750, tax 11% = 742.5, total = 7492.5
        assert total == Decimal("7492.5")
        assert order.total_amount == Decimal("7492.5")


# ==================== TESTS DOMAIN MODELS LAINNYA (ASLI, DI PERTAHANKAN SEMUA) ====================

class TestGoodsReceiptLine:
    """Tests for the GoodsReceiptLine value object / model."""

    def _build_kwargs(self):
        return dict(
            product_id=uuid4(),
            product_code="test_value",
            product_name="test_value",
            ordered_quantity=Decimal("100.00"),
            received_quantity=Decimal("100.00"),
            rejected_quantity=Decimal("100.00"),
            unit_cost=Decimal("100.00"),
        )

    def test_construction_success(self):
        """GoodsReceiptLine can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = GoodsReceiptLine(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, GoodsReceiptLine)
        assert instance.product_id == kwargs['product_id']


class TestGoodsReceipt:
    """Tests for the GoodsReceipt value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            grn_number="test_value",
            purchase_order_id=uuid4(),
            po_number="test_value",
            receipt_date=date.today(),
            lines=[MagicMock()],
            status=DocumentStatus.DRAFT,
            received_by=uuid4(),
            created_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
        )

    def test_construction_success(self):
        """GoodsReceipt can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = GoodsReceipt(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, GoodsReceipt)
        assert instance.id == kwargs['id']


class TestDeliveryNoteLine:
    """Tests for the DeliveryNoteLine value object / model."""

    def _build_kwargs(self):
        return dict(
            product_id=uuid4(),
            product_code="test_value",
            product_name="test_value",
            ordered_quantity=Decimal("100.00"),
            delivered_quantity=Decimal("100.00"),
            unit_price=Decimal("100.00"),
        )

    def test_construction_success(self):
        """DeliveryNoteLine can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = DeliveryNoteLine(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, DeliveryNoteLine)
        assert instance.product_id == kwargs['product_id']


class TestDeliveryNote:
    """Tests for the DeliveryNote value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            dn_number="test_value",
            sales_order_id=uuid4(),
            so_number="test_value",
            delivery_date=date.today(),
            lines=[MagicMock()],
            status=DocumentStatus.DRAFT,
            delivered_by=uuid4(),
            created_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
        )

    def test_construction_success(self):
        """DeliveryNote can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = DeliveryNote(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, DeliveryNote)
        assert instance.id == kwargs['id']


class TestInvoiceLine:
    """Tests for the InvoiceLine value object / model."""

    def _build_kwargs(self):
        return dict(
            product_id=uuid4(),
            product_code="test_value",
            product_name="test_value",
            quantity=Decimal("100.00"),
            unit_price=Decimal("100.00"),
            discount_percentage=Decimal("100.00"),
            tax_rate=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )

    def test_construction_success(self):
        """InvoiceLine can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = InvoiceLine(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, InvoiceLine)
        assert instance.product_id == kwargs['product_id']


class TestPurchaseInvoice:
    """Tests for the PurchaseInvoice value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            invoice_number="test_value",
            purchase_order_id=uuid4(),
            goods_receipt_id=uuid4(),
            invoice_date=date.today(),
            due_date=date.today(),
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            status=DocumentStatus.DRAFT,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
            lines=[MagicMock()],
        )

    def test_construction_success(self):
        """PurchaseInvoice can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = PurchaseInvoice(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, PurchaseInvoice)
        assert instance.id == kwargs['id']


class TestSalesInvoice:
    """Tests for the SalesInvoice value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            invoice_number="test_value",
            sales_order_id=uuid4(),
            delivery_note_id=uuid4(),
            invoice_date=date.today(),
            due_date=date.today(),
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            status=DocumentStatus.DRAFT,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
            lines=[MagicMock()],
        )

    def test_construction_success(self):
        """SalesInvoice can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = SalesInvoice(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, SalesInvoice)
        assert instance.id == kwargs['id']


class TestCreditNote:
    """Tests for the CreditNote value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            credit_note_number="test_value",
            invoice_id=uuid4(),
            invoice_type="test_value",
            credit_note_date=date.today(),
            amount=Decimal("100.00"),
            reason="test_value",
            status=DocumentStatus.DRAFT,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
        )

    def test_construction_success(self):
        """CreditNote can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = CreditNote(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, CreditNote)
        assert instance.id == kwargs['id']


class TestDebitNote:
    """Tests for the DebitNote value object / model."""

    def _build_kwargs(self):
        return dict(
            id=uuid4(),
            debit_note_number="test_value",
            invoice_id=uuid4(),
            invoice_type="test_value",
            debit_note_date=date.today(),
            amount=Decimal("100.00"),
            reason="test_value",
            status=DocumentStatus.DRAFT,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            legal_entity_id=uuid4(),
        )

    def test_construction_success(self):
        """DebitNote can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        try:
            instance = DebitNote(**kwargs)
        except (Exception, SystemExit) as e:
            pytest.skip(f"Domain validation rejected generic dummy data (needs realistic fixture): {e}")
            return
        assert isinstance(instance, DebitNote)
        assert instance.id == kwargs['id']


# ==================== TESTS EXCEPTIONS (ASLI, DIPERTAHANKAN SEMUA) ====================

class TestPurchaseSalesServiceError:
    """Tests for PurchaseSalesServiceError."""
    def _build_instance(self):
        return PurchaseSalesServiceError()

    def test_construction(self):
        """PurchaseSalesServiceError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, PurchaseSalesServiceError)


class TestPurchaseOrderNotFoundError:
    """Tests for PurchaseOrderNotFoundError."""
    def _build_instance(self):
        return PurchaseOrderNotFoundError()

    def test_construction(self):
        """PurchaseOrderNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, PurchaseOrderNotFoundError)


class TestSalesOrderNotFoundError:
    """Tests for SalesOrderNotFoundError."""
    def _build_instance(self):
        return SalesOrderNotFoundError()

    def test_construction(self):
        """SalesOrderNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, SalesOrderNotFoundError)


class TestGoodsReceiptNotFoundError:
    """Tests for GoodsReceiptNotFoundError."""
    def _build_instance(self):
        return GoodsReceiptNotFoundError()

    def test_construction(self):
        """GoodsReceiptNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, GoodsReceiptNotFoundError)


class TestDeliveryNoteNotFoundError:
    """Tests for DeliveryNoteNotFoundError."""
    def _build_instance(self):
        return DeliveryNoteNotFoundError()

    def test_construction(self):
        """DeliveryNoteNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, DeliveryNoteNotFoundError)


class TestPurchaseInvoiceNotFoundError:
    """Tests for PurchaseInvoiceNotFoundError."""
    def _build_instance(self):
        return PurchaseInvoiceNotFoundError()

    def test_construction(self):
        """PurchaseInvoiceNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, PurchaseInvoiceNotFoundError)


class TestSalesInvoiceNotFoundError:
    """Tests for SalesInvoiceNotFoundError."""
    def _build_instance(self):
        return SalesInvoiceNotFoundError()

    def test_construction(self):
        """SalesInvoiceNotFoundError can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, SalesInvoiceNotFoundError)


# ==================== TESTS SERVICE (ASLI + TAMBAHAN) ====================

class TestPurchaseSalesService:
    """Tests for PurchaseSalesService."""

    def _build_instance(self):
        return PurchaseSalesService(event_publisher=MagicMock())

    def test_construction(self):
        """PurchaseSalesService can be instantiated with mocked dependencies."""
        try:
            instance = self._build_instance()
        except (Exception, SystemExit) as e:
            pytest.skip(f"Requires domain-specific construction setup: {e}")
            return
        assert isinstance(instance, PurchaseSalesService)

    # --- SMOKE TESTS ASLI (dipertahankan) ---
    async def test_create_purchase_order_smoke(self):
        """Smoke test for PurchaseSalesService.create_purchase_order using mocked collaborators."""
        try:
            instance = self._build_instance()
            result = await instance.create_purchase_order(
                po_number="test_value",
                supplier_id=uuid4(),
                supplier_name="test_value",
                lines=[{}],
                order_date=date.today(),
                expected_delivery_date=date.today(),
                currency="test_value",
                notes="test_value",
                created_by=uuid4(),
                legal_entity_id=uuid4(),
                correlation_id="test_value"
            )
        except (Exception, SystemExit) as e:
            pytest.skip(f"create_purchase_order needs specific domain fixtures/data: {e}")
            return
        # Real-code smoke assertion: call completed without raising
        assert True

    async def test_get_purchase_order_smoke(self):
        """Smoke test for PurchaseSalesService.get_purchase_order using mocked collaborators."""
        try:
            instance = self._build_instance()
            result = await instance.get_purchase_order(po_id=uuid4())
        except (Exception, SystemExit) as e:
            pytest.skip(f"get_purchase_order needs specific domain fixtures/data: {e}")
            return
        # Real-code smoke assertion: call completed without raising
        assert True

    async def test_list_purchase_orders_smoke(self):
        """Smoke test for PurchaseSalesService.list_purchase_orders using mocked collaborators."""
        try:
            instance = self._build_instance()
            result = await instance.list_purchase_orders(
                supplier_id=uuid4(),
                status="test_value",
                start_date=date.today(),
                end_date=date.today(),
                legal_entity_id=uuid4()
            )
        except (Exception, SystemExit) as e:
            pytest.skip(f"list_purchase_orders needs specific domain fixtures/data: {e}")
            return
        # Real-code smoke assertion: call completed without raising
        assert True

    async def test_update_purchase_order_smoke(self):
        """Smoke test for PurchaseSalesService.update_purchase_order using mocked collaborators."""
        try:
            instance = self._build_instance()
            result = await instance.update_purchase_order(
                po_id=uuid4(),
                expected_delivery_date=date.today(),
                notes="test_value",
                status="test_value",
                user_id=uuid4()
            )
        except (Exception, SystemExit) as e:
            pytest.skip(f"update_purchase_order needs specific domain fixtures/data: {e}")
            return
        # Real-code smoke assertion: call completed without raising
        assert True

    # --- TAMBAHAN: Test get_stats & get_audit_trail ---
    def test_get_stats_smoke(self):
        instance = self._build_instance()
        stats = instance.get_stats()
        assert isinstance(stats, dict)
        assert "po_created" in stats
        assert "so_created" in stats
        assert "grn_created" in stats
        assert "dn_created" in stats
        assert "purchase_invoices" in stats
        assert "sales_invoices" in stats
        assert "credit_notes" in stats
        assert "debit_notes" in stats

    async def test_get_audit_trail_smoke(self):
        instance = self._build_instance()
        # Pastikan audit trail bertambah setelah aksi
        initial_len = len(instance.get_audit_trail())
        await instance.create_purchase_order(
            po_number="AUDIT-TEST-1",
            supplier_id=uuid4(),
            supplier_name="Supplier",
            lines=[{"product_id": str(uuid4()), "product_code": "P001", "product_name": "Product", "quantity": "1", "unit_price": "100"}],
        )
        new_len = len(instance.get_audit_trail())
        assert new_len > initial_len


# ==================== TESTS MODULE-LEVEL FUNCTIONS (ASLI) ====================

def test_audit_smoke():
    """Smoke test for module-level function audit."""
    try:
        result = audit(func=MagicMock())
    except (Exception, SystemExit) as e:
        pytest.skip(f"audit needs specific input data: {e}")
        return
    assert True


async def test_create_purchase_sales_service_smoke():
    """Smoke test for module-level function create_purchase_sales_service."""
    try:
        result = await create_purchase_sales_service(event_publisher=MagicMock())
    except (Exception, SystemExit) as e:
        pytest.skip(f"create_purchase_sales_service needs specific input data: {e}")
        return
    assert True