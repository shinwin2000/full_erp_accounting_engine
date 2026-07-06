#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from grpc import StatusCode, aio

# Import generated proto modules (hasil compile)
from adapters.primary_api.proto import accounting_pb2, accounting_pb2_grpc

# Internal dependencies
from application.commands_cqrs import CommandBusUnified, QueryBusUnified
from infrastructure.security.jwt_validator import JWTValidator
from kernel.guards.authority_matrix import AuthorityMatrix
from kernel.sealed_gate import get_sealed_gate

logger = logging.getLogger(__name__)


# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    """
    Manager untuk menangani idempotensi pada gRPC methods.
    Menggunakan in-memory dictionary sebagai placeholder.
    Untuk production, gunakan Redis atau cache terdistribusi.
    """

    def __init__(self):
        # In-memory storage: key -> (result_json, timestamp)
        self._storage: Dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400  # 24 jam

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        """Generate storage key dari idempotency key dan method name."""
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> Optional[Any]:
        """Ambil hasil yang sudah di-cache berdasarkan key."""
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        # Cek TTL
        if (datetime.now(timezone.utc) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: Any) -> None:
        """Simpan hasil operasi ke cache."""
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            # Fallback: convert to dict if possible
            if hasattr(result, "to_dict"):
                result_json = json.dumps(result.to_dict(), default=str)
            else:
                result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(timezone.utc))


# ============================================================================
# INTERCEPTORS
# ============================================================================

class AuthenticationInterceptor(aio.ServerInterceptor):
    """Interceptor untuk autentikasi JWT."""

    def __init__(self):
        self.jwt_validator = JWTValidator()
        self.authority_matrix = AuthorityMatrix()

    async def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata or [])
        auth_header = metadata.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            await self._abort(handler_call_details, StatusCode.UNAUTHENTICATED, "Missing credentials")
            return None
        token = auth_header[7:]
        try:
            payload = await self.jwt_validator.validate(token)
        except Exception as e:
            logger.warning(f"Authentication validation error: {type(e).__name__}")
            await self._abort(handler_call_details, StatusCode.UNAUTHENTICATED, "Invalid credentials")
            return None
        return await continuation(handler_call_details)

    async def _abort(self, call_details, code, details):
        logger.error(f"Authentication aborted: {code}")


class AuditInterceptor(aio.ServerInterceptor):
    async def intercept_service(self, continuation, handler_call_details):
        method_name = handler_call_details.method
        start = datetime.now(timezone.utc)
        try:
            response = await continuation(handler_call_details)
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            asyncio.create_task(self._log_audit(method_name, True, duration, None))
            return response
        except Exception as e:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            asyncio.create_task(self._log_audit(method_name, False, duration, str(e)))
            raise

    async def _log_audit(self, method, success, duration, error):
        logger.info(
            f"gRPC audit: {method} success={success} duration={duration:.3f}s error={error}"
        )


# ============================================================================
# GRPC SERVICE SERVICER
# ============================================================================

class AccountingServiceServicer(accounting_pb2_grpc.AccountingServiceServicer):
    def __init__(self):
        self.command_bus = CommandBusUnified()
        self.query_bus = QueryBusUnified()
        self.sealed_gate = get_sealed_gate()
        self.idempotency_manager = IdempotencyManager()

    # ------------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------------

    def _to_proto_double(self, value: Any) -> float:
        """
        Mengisolasi konversi dari Decimal ke float hanya pada batas luar gRPC transport.
        """
        if value is None:
            return 0.0
        return float(value)  # noqa: float-cast

    def _get_user_id(self, context) -> str:
        return dict(context.invocation_metadata() or {}).get("user-id", "")

    def _get_legal_entity_id(self, context) -> str:
        return dict(context.invocation_metadata() or {}).get("legal-entity-id", "")

    def _get_idempotency_key(self, context) -> Optional[str]:
        """Ambil idempotency key dari metadata gRPC."""
        metadata = dict(context.invocation_metadata() or {})
        # Coba beberapa varian header
        for key in ["idempotency-key", "Idempotency-Key", "idempotency_key"]:
            if key in metadata:
                return metadata[key]
        return None

    # ------------------------------------------------------------------------
    # Journal Methods (write operations with explicit idempotency)
    # ------------------------------------------------------------------------

    async def CreateJournal(self, request, context, idempotency_key: Optional[str] = None):
        try:
            # Get idempotency key from parameter or context
            if idempotency_key is None:
                idempotency_key = self._get_idempotency_key(context)

            # Check cache if key provided
            if idempotency_key:
                cached = self.idempotency_manager.get_cached_result(idempotency_key, "CreateJournal")
                if cached is not None:
                    logger.info(f"Idempotent cache hit: CreateJournal key={idempotency_key[:8]}...")
                    return accounting_pb2.JournalResponse(
                        id=str(cached["id"]),
                        voucher_number=cached["voucher_number"],
                        status=cached.get("status", "created"),
                    )

            # Build command
            user_id = self._get_user_id(context)
            legal_entity_id = self._get_legal_entity_id(context)

            lines = [
                {
                    "account_code": line.account_code,
                    "debit_amount": Decimal(line.debit_amount),
                    "credit_amount": Decimal(line.credit_amount),
                    "cost_center": line.cost_center or None,
                    "description": line.description or None,
                }
                for line in request.lines
            ]

            command = {
                "type": "journal.create",
                "data": {
                    "journal_date": date.fromisoformat(request.journal_date),
                    "description": request.description,
                    "lines": lines,
                    "reference_number": request.reference_number or None,
                    "source_type": request.source_type,
                    "source_id": request.source_id or None,
                    "created_by": UUID(user_id) if user_id else None,
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                },
            }

            # Execute
            result = await self.command_bus.dispatch(command)

            # Cache result if key provided
            if idempotency_key:
                self.idempotency_manager.cache_result(idempotency_key, "CreateJournal", result)

            return accounting_pb2.JournalResponse(
                id=str(result["id"]),
                voucher_number=result["voucher_number"],
                status=result.get("status", "created"),
            )
        except Exception as e:
            logger.exception("CreateJournal failed")
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def PostJournal(self, request, context, idempotency_key: Optional[str] = None):
        try:
            if idempotency_key is None:
                idempotency_key = self._get_idempotency_key(context)

            if idempotency_key:
                cached = self.idempotency_manager.get_cached_result(idempotency_key, "PostJournal")
                if cached is not None:
                    logger.info(f"Idempotent cache hit: PostJournal key={idempotency_key[:8]}...")
                    return accounting_pb2.JournalResponse(
                        id=request.id,
                        voucher_number=cached["voucher_number"],
                        status="posted",
                    )

            user_id = self._get_user_id(context)
            legal_entity_id = self._get_legal_entity_id(context)

            command = {
                "type": "journal.post",
                "data": {
                    "journal_id": UUID(request.id),
                    "posted_by": UUID(user_id) if user_id else None,
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                },
            }

            result = await self.command_bus.dispatch(command)

            if idempotency_key:
                self.idempotency_manager.cache_result(idempotency_key, "PostJournal", result)

            return accounting_pb2.JournalResponse(
                id=request.id,
                voucher_number=result["voucher_number"],
                status="posted",
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def ReverseJournal(self, request, context, idempotency_key: Optional[str] = None):
        try:
            if idempotency_key is None:
                idempotency_key = self._get_idempotency_key(context)

            if idempotency_key:
                cached = self.idempotency_manager.get_cached_result(idempotency_key, "ReverseJournal")
                if cached is not None:
                    logger.info(f"Idempotent cache hit: ReverseJournal key={idempotency_key[:8]}...")
                    return accounting_pb2.JournalResponse(
                        id=cached["reversal_journal_id"],
                        voucher_number=cached["reversal_voucher_number"],
                        status="posted",
                    )

            user_id = self._get_user_id(context)
            legal_entity_id = self._get_legal_entity_id(context)

            command = {
                "type": "journal.reverse",
                "data": {
                    "journal_id": UUID(request.journal_id),
                    "reversal_date": date.fromisoformat(request.reversal_date),
                    "reason": request.reason,
                    "reversed_by": UUID(user_id) if user_id else None,
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                },
            }

            result = await self.command_bus.dispatch(command)

            if idempotency_key:
                self.idempotency_manager.cache_result(idempotency_key, "ReverseJournal", result)

            return accounting_pb2.JournalResponse(
                id=result["reversal_journal_id"],
                voucher_number=result["reversal_voucher_number"],
                status="posted",
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    # ------------------------------------------------------------------------
    # Query Methods (read-only, no idempotency needed)
    # ------------------------------------------------------------------------

    async def GetTrialBalance(self, request, context):
        try:
            legal_entity_id = self._get_legal_entity_id(context)
            query = {
                "type": "ledger.trial_balance",
                "data": {
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                    "as_of_date": date.fromisoformat(request.as_of_date),
                    "include_zero_balance": request.include_zero_balance,
                },
            }
            result = await self.query_bus.dispatch(query)
            response = accounting_pb2.TrialBalanceResponse()
            response.as_of_date = request.as_of_date

            response.total_debit = self._to_proto_double(result["total_debit"])
            response.total_credit = self._to_proto_double(result["total_credit"])
            response.is_balanced = result["is_balanced"]

            for line in result.get("lines", []):
                pb_line = response.lines.add()
                pb_line.account_code = line["account_code"]
                pb_line.account_name = line["account_name"]
                pb_line.opening_balance_debit = self._to_proto_double(line.get("opening_balance_debit", Decimal(0)))
                pb_line.opening_balance_credit = self._to_proto_double(line.get("opening_balance_credit", Decimal(0)))
                pb_line.movement_debit = self._to_proto_double(line.get("movement_debit", Decimal(0)))
                pb_line.movement_credit = self._to_proto_double(line.get("movement_credit", Decimal(0)))
                pb_line.closing_balance_debit = self._to_proto_double(line.get("closing_balance_debit", Decimal(0)))
                pb_line.closing_balance_credit = self._to_proto_double(line.get("closing_balance_credit", Decimal(0)))
            return response
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def GetBalanceSheet(self, request, context):
        try:
            legal_entity_id = self._get_legal_entity_id(context)
            query = {
                "type": "ledger.balance_sheet",
                "data": {
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                    "as_of_date": date.fromisoformat(request.as_of_date),
                },
            }
            result = await self.query_bus.dispatch(query)
            response = accounting_pb2.BalanceSheetResponse()
            response.as_of_date = request.as_of_date
            response.total_assets = self._to_proto_double(result.get("total_assets", Decimal(0)))
            response.total_liabilities = self._to_proto_double(result.get("total_liabilities", Decimal(0)))
            response.total_equity = self._to_proto_double(result.get("total_equity", Decimal(0)))
            return response
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def GetIncomeStatement(self, request, context):
        try:
            legal_entity_id = self._get_legal_entity_id(context)
            query = {
                "type": "ledger.income_statement",
                "data": {
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                    "start_date": date.fromisoformat(request.start_date),
                    "end_date": date.fromisoformat(request.end_date),
                },
            }
            result = await self.query_bus.dispatch(query)
            response = accounting_pb2.IncomeStatementResponse()
            response.start_date = request.start_date
            response.end_date = request.end_date
            response.total_revenue = self._to_proto_double(result.get("total_revenue", Decimal(0)))
            response.total_expenses = self._to_proto_double(result.get("total_expenses", Decimal(0)))
            response.net_income = self._to_proto_double(result.get("net_income", Decimal(0)))
            return response
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    # ------------------------------------------------------------------------
    # AR/AP Methods (write operations with explicit idempotency)
    # ------------------------------------------------------------------------

    async def CreateARInvoice(self, request, context, idempotency_key: Optional[str] = None):
        try:
            if idempotency_key is None:
                idempotency_key = self._get_idempotency_key(context)

            if idempotency_key:
                cached = self.idempotency_manager.get_cached_result(idempotency_key, "CreateARInvoice")
                if cached is not None:
                    logger.info(f"Idempotent cache hit: CreateARInvoice key={idempotency_key[:8]}...")
                    return accounting_pb2.ARInvoiceResponse(
                        id=str(cached["id"]),
                        invoice_number=cached["invoice_number"],
                        total_amount=self._to_proto_double(cached["total_amount"]),
                        status=cached["status"],
                    )

            user_id = self._get_user_id(context)
            legal_entity_id = self._get_legal_entity_id(context)

            command = {
                "type": "ar.invoice.create",
                "data": {
                    "customer_id": UUID(request.customer_id),
                    "invoice_date": date.fromisoformat(request.invoice_date),
                    "due_date": date.fromisoformat(request.due_date),
                    "lines": [
                        {
                            "description": line.description,
                            "quantity": Decimal(line.quantity),
                            "unit_price": Decimal(line.unit_price),
                            "tax_rate": Decimal(line.tax_rate),
                            "account_code": line.account_code,
                        }
                        for line in request.lines
                    ],
                    "description": request.description,
                    "created_by": UUID(user_id) if user_id else None,
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                },
            }

            result = await self.command_bus.dispatch(command)

            if idempotency_key:
                self.idempotency_manager.cache_result(idempotency_key, "CreateARInvoice", result)

            return accounting_pb2.ARInvoiceResponse(
                id=str(result["id"]),
                invoice_number=result["invoice_number"],
                total_amount=self._to_proto_double(result["total_amount"]),
                status=result["status"],
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def RecordARPayment(self, request, context, idempotency_key: Optional[str] = None):
        try:
            if idempotency_key is None:
                idempotency_key = self._get_idempotency_key(context)

            if idempotency_key:
                cached = self.idempotency_manager.get_cached_result(idempotency_key, "RecordARPayment")
                if cached is not None:
                    logger.info(f"Idempotent cache hit: RecordARPayment key={idempotency_key[:8]}...")
                    return accounting_pb2.ARPaymentResponse(
                        id=str(cached["id"]),
                        payment_number=cached["payment_number"],
                        amount=self._to_proto_double(cached["amount"]),
                        status=cached["status"],
                    )

            user_id = self._get_user_id(context)
            legal_entity_id = self._get_legal_entity_id(context)

            command = {
                "type": "ar.payment.create",
                "data": {
                    "invoice_id": UUID(request.invoice_id),
                    "payment_date": date.fromisoformat(request.payment_date),
                    "amount": Decimal(str(request.amount)),
                    "payment_method": request.payment_method,
                    "created_by": UUID(user_id) if user_id else None,
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                },
            }

            result = await self.command_bus.dispatch(command)

            if idempotency_key:
                self.idempotency_manager.cache_result(idempotency_key, "RecordARPayment", result)

            return accounting_pb2.ARPaymentResponse(
                id=str(result["id"]),
                payment_number=result["payment_number"],
                amount=self._to_proto_double(result["amount"]),
                status=result["status"],
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def CreateAPInvoice(self, request, context, idempotency_key: Optional[str] = None):
        try:
            if idempotency_key is None:
                idempotency_key = self._get_idempotency_key(context)

            if idempotency_key:
                cached = self.idempotency_manager.get_cached_result(idempotency_key, "CreateAPInvoice")
                if cached is not None:
                    logger.info(f"Idempotent cache hit: CreateAPInvoice key={idempotency_key[:8]}...")
                    return accounting_pb2.APInvoiceResponse(
                        id=str(cached["id"]),
                        invoice_number=cached["invoice_number"],
                        total_amount=self._to_proto_double(cached["total_amount"]),
                        status=cached["status"],
                    )

            user_id = self._get_user_id(context)
            legal_entity_id = self._get_legal_entity_id(context)

            command = {
                "type": "ap.invoice.create",
                "data": {
                    "vendor_id": UUID(request.vendor_id),
                    "invoice_date": date.fromisoformat(request.invoice_date),
                    "due_date": date.fromisoformat(request.due_date),
                    "invoice_number_vendor": request.invoice_number_vendor,
                    "lines": [
                        {
                            "description": line.description,
                            "quantity": Decimal(line.quantity),
                            "unit_price": Decimal(line.unit_price),
                            "account_code": line.account_code,
                        }
                        for line in request.lines
                    ],
                    "description": request.description,
                    "created_by": UUID(user_id) if user_id else None,
                    "legal_entity_id": UUID(legal_entity_id) if legal_entity_id else None,
                },
            }

            result = await self.command_bus.dispatch(command)

            if idempotency_key:
                self.idempotency_manager.cache_result(idempotency_key, "CreateAPInvoice", result)

            return accounting_pb2.APInvoiceResponse(
                id=str(result["id"]),
                invoice_number=result["invoice_number"],
                total_amount=self._to_proto_double(result["total_amount"]),
                status=result["status"],
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))


# ============================================================================
# SERVER FUNCTIONS
# ============================================================================

async def create_grpc_server(address: str = "[::]:50051") -> aio.Server:
    server = aio.Server(interceptors=[AuthenticationInterceptor(), AuditInterceptor()])
    accounting_pb2_grpc.add_AccountingServiceServicer_to_server(AccountingServiceServicer(), server)
    server.add_insecure_port(address)
    logger.info(f"gRPC server listening on {address}")
    return server


async def start_grpc_server():
    server = await create_grpc_server()
    await server.start()
    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        await server.stop(grace=5)


__all__ = ["AccountingServiceServicer", "create_grpc_server", "start_grpc_server"]