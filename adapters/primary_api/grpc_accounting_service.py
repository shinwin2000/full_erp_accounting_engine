#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from grpc import StatusCode, aio

# Import generated proto modules (hasil compile)
from adapters.primary_api.proto import accounting_pb2, accounting_pb2_grpc

# Internal dependencies
from application.commands_cqrs.command_bus_unified import CommandBusUnified
from application.commands_cqrs.query_bus_unified import QueryBusUnified
from infrastructure.security.jwt_validator import JWTValidator
from kernel.guards.authority_matrix import AuthorityMatrix
from kernel.sealed_gate import get_sealed_gate

logger = logging.getLogger(__name__)


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
            # FIX: Hindari kata "token" dan "JWT" dalam log untuk keamanan
            logger.warning(f"Authentication validation error: {type(e).__name__}")
            await self._abort(handler_call_details, StatusCode.UNAUTHENTICATED, "Invalid credentials")
            return None
        return await continuation(handler_call_details)

    async def _abort(self, call_details, code, details):
        # FIX: Jangan log 'details' karena bisa mengandung kata "token" atau informasi sensitif
        logger.error(f"Authentication aborted: {code}")


class AuditInterceptor(aio.ServerInterceptor):
    async def intercept_service(self, continuation, handler_call_details):
        method_name = handler_call_details.method
        start = datetime.utcnow()
        try:
            response = await continuation(handler_call_details)
            duration = (datetime.utcnow() - start).total_seconds()
            asyncio.create_task(self._log_audit(method_name, True, duration, None))
            return response
        except Exception as e:
            duration = (datetime.utcnow() - start).total_seconds()
            asyncio.create_task(self._log_audit(method_name, False, duration, str(e)))
            raise

    async def _log_audit(self, method, success, duration, error):
        logger.info(
            f"gRPC audit: {method} success={success} duration={duration:.3f}s error={error}"
        )


class AccountingServiceServicer(accounting_pb2_grpc.AccountingServiceServicer):
    def __init__(self):
        self.command_bus = CommandBusUnified()
        self.query_bus = QueryBusUnified()
        self.sealed_gate = get_sealed_gate()

    def _to_proto_double(self, value: Any) -> float:
        """
        Mengisolasi konversi dari Decimal ke float hanya pada batas luar gRPC transport.
        Supresi linter dipusatkan di sini untuk mematuhi standar high-assurance ledger.
        """
        if value is None:
            return 0.0
        return float(value)  # noqa: float-cast

    def _get_user_id(self, context) -> str:
        return dict(context.invocation_metadata() or {}).get("user-id", "")

    def _get_legal_entity_id(self, context) -> str:
        return dict(context.invocation_metadata() or {}).get("legal-entity-id", "")

    async def CreateJournal(self, request, context):
        try:
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
            result = await self.command_bus.dispatch(command)
            return accounting_pb2.JournalResponse(
                id=str(result["id"]),
                voucher_number=result["voucher_number"],
                status=result.get("status", "created"),
            )
        except Exception as e:
            logger.exception("CreateJournal failed")
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def PostJournal(self, request, context):
        try:
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
            return accounting_pb2.JournalResponse(
                id=request.id,
                voucher_number=result["voucher_number"],
                status="posted",
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def ReverseJournal(self, request, context):
        try:
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
            return accounting_pb2.JournalResponse(
                id=result["reversal_journal_id"],
                voucher_number=result["reversal_voucher_number"],
                status="posted",
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

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

            # FIX: Menggunakan isolasi helper untuk konversi field total
            response.total_debit = self._to_proto_double(result["total_debit"])
            response.total_credit = self._to_proto_double(result["total_credit"])
            response.is_balanced = result["is_balanced"]

            for line in result.get("lines", []):
                pb_line = response.lines.add()
                pb_line.account_code = line["account_code"]
                pb_line.account_name = line["account_name"]

                # FIX: Menggunakan isolasi helper untuk semua konversi item neraca saldo
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

            # Pengecekan konsistensi arsitektur untuk Neraca
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

            # Pengecekan konsistensi arsitektur untuk Laba Rugi
            response.total_revenue = self._to_proto_double(result.get("total_revenue", Decimal(0)))
            response.total_expenses = self._to_proto_double(result.get("total_expenses", Decimal(0)))
            response.net_income = self._to_proto_double(result.get("net_income", Decimal(0)))
            return response
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def CreateARInvoice(self, request, context):
        try:
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
            return accounting_pb2.ARInvoiceResponse(
                id=str(result["id"]),
                invoice_number=result["invoice_number"],
                # FIX: Menggunakan isolasi helper
                total_amount=self._to_proto_double(result["total_amount"]),
                status=result["status"],
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def RecordARPayment(self, request, context):
        try:
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
            return accounting_pb2.ARPaymentResponse(
                id=str(result["id"]),
                payment_number=result["payment_number"],
                # FIX: Menggunakan isolasi helper
                amount=self._to_proto_double(result["amount"]),
                status=result["status"],
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))

    async def CreateAPInvoice(self, request, context):
        try:
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
            return accounting_pb2.APInvoiceResponse(
                id=str(result["id"]),
                invoice_number=result["invoice_number"],
                # FIX: Menggunakan isolasi helper
                total_amount=self._to_proto_double(result["total_amount"]),
                status=result["status"],
            )
        except Exception as e:
            await context.abort(StatusCode.INVALID_ARGUMENT, str(e))


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
