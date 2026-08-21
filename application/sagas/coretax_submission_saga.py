#!/usr/bin/env python3

"""
Module: coretax_submission_saga.py

Layer: 8 - Application / Sagas

Responsibility:
    Saga orchestrator untuk submission ke Coretax DJP.
    Steps: Validate -> Sign -> Submit -> Wait Approval -> Save Result -> Update Status
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from application.sagas.coretax_submission_saga_state import CoretaxSubmissionSagaState
from application.sagas.saga_orchestrator_base import SagaOrchestratorBase
from ports.primary.saga_state_store_port import SagaStateStorePort

logger = logging.getLogger(__name__)


class CoretaxSubmissionSaga(SagaOrchestratorBase[CoretaxSubmissionSagaState]):
    """
    Saga untuk submit SPT ke Coretax.
    """

    def __init__(
        self,
        state_store: SagaStateStorePort,
        coretax_service: Any,  # CoretaxService protocol
    ):
        super().__init__(state_store, "coretax_submission")
        self._coretax = coretax_service
        self._register_steps()

    def _register_steps(self):
        self.add_step(self._validate_data, self._compensate_validate, "validate_data")
        self.add_step(self._generate_signature, self._compensate_signature, "generate_signature")
        self.add_step(self._submit_to_coretax, self._compensate_submit, "submit_to_coretax")
        self.add_step(self._wait_for_approval, self._compensate_approval, "wait_for_approval")
        self.add_step(self._save_result, self._compensate_save, "save_result")
        self.add_step(self._update_status, self._compensate_status, "update_status")

    async def _validate_data(self, state: CoretaxSubmissionSagaState) -> CoretaxSubmissionSagaState:
        """Validate SPT data before submission."""
        logger.info(f"Validating Coretax submission data for {state.tax_type}")

        if not state.submission_payload:
            raise ValueError("Submission payload is empty")

        # Validate required fields based on tax type
        required_fields = ["npwp", "masa_pajak", "tahun_pajak"]
        if state.tax_type == "PPN":
            required_fields.extend(["total_ppn_keluaran", "total_ppn_masukan"])
        elif state.tax_type in ["PPH21", "PPH23"]:
            required_fields.extend(["total_bruto", "total_pph_dipotong"])

        for field in required_fields:
            if field not in state.submission_payload:
                raise ValueError(f"Missing required field: {field}")

        state.status = "VALIDATED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _compensate_validate(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        logger.info(f"Compensating validation for saga {state.saga_id}")
        state.status = "VALIDATION_COMPENSATED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _generate_signature(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        """Generate digital signature for SPT."""
        logger.info(f"Generating digital signature for {state.tax_type}")

        secret_key = os.environ.get("CORETAX_SIGNING_SECRET")
        if not secret_key:
            raise RuntimeError(
                "CORETAX_SIGNING_SECRET environment variable is required. "
                "Please set it before running Coretax submission."
            )

        signature_data = (
            f"{state.legal_entity_id}{state.period_year}{state.period_month}{state.tax_type}"
        )
        digital_signature = hmac.new(
            secret_key.encode(), signature_data.encode(), hashlib.sha256
        ).hexdigest()

        state.submission_payload["digital_signature"] = digital_signature
        state.submission_payload["signature_timestamp"] = datetime.now(UTC).isoformat()
        state.status = "SIGNED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _compensate_signature(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        logger.info(f"Compensating signature for saga {state.saga_id}")
        state.submission_payload.pop("digital_signature", None)
        state.status = "SIGNATURE_COMPENSATED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _submit_to_coretax(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        """Submit to Coretax API."""
        logger.info(f"Submitting to Coretax for {state.tax_type}")

        if not hasattr(self._coretax, "submit_spt"):
            raise NotImplementedError("CoretaxService.submit_spt not implemented")

        response = await self._coretax.submit_spt(
            tax_type=state.tax_type,
            payload=state.submission_payload,
            user_id=state.user_id,
        )

        if not response.get("success", False):
            raise Exception(
                f"Coretax submission failed: {response.get('message', 'Unknown error')}"
            )

        state.submission_id = UUID(response.get("submission_id"))
        state.approval_code = response.get("approval_code")
        state.status = "SUBMITTED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _compensate_submit(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        """Cancel submission if possible."""
        logger.info(f"Compensating submission for saga {state.saga_id}")

        if state.submission_id and hasattr(self._coretax, "cancel_submission"):
            try:
                await self._coretax.cancel_submission(state.submission_id)
                state.status = "SUBMISSION_CANCELLED"
            except Exception as e:
                logger.error(f"Failed to cancel submission: {e}")
                state.status = "SUBMISSION_CANCEL_FAILED"

        state.updated_at = datetime.now(UTC)
        return state

    async def _wait_for_approval(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        """Poll for approval status."""
        logger.info(f"Waiting for approval for submission {state.submission_id}")

        max_attempts = 30
        poll_interval = 2.0

        for _attempt in range(max_attempts):
            if not hasattr(self._coretax, "check_submission_status"):
                raise NotImplementedError("CoretaxService.check_submission_status not implemented")

            status_response = await self._coretax.check_submission_status(state.submission_id)
            current_status = status_response.get("status", "")

            if current_status == "APPROVED":
                state.status = "APPROVED"
                state.approval_code = status_response.get("approval_code", state.approval_code)
                state.pdf_bukti = status_response.get("pdf_bukti")
                state.updated_at = datetime.now(UTC)
                logger.info(f"Submission {state.submission_id} approved")
                return state
            elif current_status == "REJECTED":
                raise Exception(
                    f"Coretax submission rejected: {status_response.get('reason', 'Unknown')}"
                )
            elif current_status == "NEEDS_REVISION":
                raise Exception(
                    f"Coretax submission needs revision: {status_response.get('notes', '')}"
                )

            await asyncio.sleep(poll_interval)

        raise Exception("Approval timeout after 60 seconds")

    async def _compensate_approval(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        logger.info(f"Compensating approval for saga {state.saga_id}")
        state.status = "APPROVAL_COMPENSATED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _save_result(self, state: CoretaxSubmissionSagaState) -> CoretaxSubmissionSagaState:
        """Save approval result to database."""
        logger.info(f"Saving submission result for {state.submission_id}")

        if hasattr(self._coretax, "save_submission_result"):
            await self._coretax.save_submission_result(
                submission_id=state.submission_id,
                approval_code=state.approval_code,
                status=state.status,
                pdf_bukti=state.pdf_bukti,
            )

        state.status = "RESULT_SAVED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _compensate_save(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        logger.info(f"Compensating save for saga {state.saga_id}")
        state.status = "SAVE_COMPENSATED"
        state.updated_at = datetime.now(UTC)
        return state

    async def _update_status(self, state: CoretaxSubmissionSagaState) -> CoretaxSubmissionSagaState:
        """Update final status."""
        state.status = "COMPLETED"
        state.updated_at = datetime.now(UTC)
        logger.info(f"Coretax submission saga {state.saga_id} completed")
        return state

    async def _compensate_status(
        self, state: CoretaxSubmissionSagaState
    ) -> CoretaxSubmissionSagaState:
        return state

    # ===================== FIX: synchronous serialization =====================

    def _serialize_data(self, data: CoretaxSubmissionSagaState) -> dict[str, Any]:
        """Serialize state to dictionary for storage."""
        return {
            "saga_id": str(data.saga_id),
            "legal_entity_id": str(data.legal_entity_id),
            "period_year": data.period_year,
            "period_month": data.period_month,
            "user_id": str(data.user_id) if data.user_id else None,
            "correlation_id": data.correlation_id,
            "tax_type": data.tax_type,
            "submission_payload": data.submission_payload,
            "submission_id": str(data.submission_id) if data.submission_id else None,
            "approval_code": data.approval_code,
            "pdf_bukti": data.pdf_bukti,
            "status": data.status,
            "errors": data.errors,
            "retry_count": data.retry_count,
            "created_at": data.created_at.isoformat(),
            "updated_at": data.updated_at.isoformat(),
        }

    def _deserialize_data(self, data_dict: dict[str, Any]) -> CoretaxSubmissionSagaState:
        """Deserialize state from dictionary."""
        return CoretaxSubmissionSagaState(
            saga_id=UUID(data_dict["saga_id"]),
            legal_entity_id=UUID(data_dict["legal_entity_id"]),
            period_year=data_dict["period_year"],
            period_month=data_dict["period_month"],
            user_id=UUID(data_dict["user_id"]) if data_dict.get("user_id") else None,
            correlation_id=data_dict.get("correlation_id"),
            tax_type=data_dict["tax_type"],
            submission_payload=data_dict.get("submission_payload", {}),
            submission_id=UUID(data_dict["submission_id"])
            if data_dict.get("submission_id")
            else None,
            approval_code=data_dict.get("approval_code"),
            pdf_bukti=data_dict.get("pdf_bukti"),
            status=data_dict.get("status", "INITIATED"),
            errors=data_dict.get("errors", []),
            retry_count=data_dict.get("retry_count", 0),
            created_at=datetime.fromisoformat(data_dict["created_at"]),
            updated_at=datetime.fromisoformat(data_dict["updated_at"]),
        )


__all__ = ["CoretaxSubmissionSaga"]
