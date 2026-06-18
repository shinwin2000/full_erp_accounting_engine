#!/usr/bin/env python3
"""
Module: explanation_generator.py
Layer: Domain / Causality
Responsibility: Menghasilkan penjelasan naratif dari rantai kausalitas.
               Mendukung multiple languages, tingkat detail, dan format output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from domain.causality.causal_chain_builder import get_causal_chain_builder
from domain.causality.causal_node import get_causal_node_service

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================


class ExplanationLevel(Enum):
    SUMMARY = "summary"  # Ringkasan satu baris
    STANDARD = "standard"  # Penjelasan standar (beberapa kalimat)
    DETAILED = "detailed"  # Penjelasan detail dengan metadata
    FORENSIC = "forensic"  # Penjelasan forensik dengan semua detail


class ExplanationLanguage(Enum):
    ENGLISH = "en"
    INDONESIAN = "id"


class ExplanationFormat(Enum):
    TEXT = "text"
    JSON = "json"
    HTML = "html"


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ExplanationSegment:
    """Segmen penjelasan untuk satu langkah dalam rantai."""

    step_number: int
    node_type: str
    entity_type: str
    entity_id: str
    timestamp: str
    created_by: str
    explanation_text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "node_type": self.node_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "timestamp": self.timestamp,
            "created_by": self.created_by,
            "explanation_text": self.explanation_text,
            "metadata": self.metadata,
        }


@dataclass
class FullExplanation:
    """Penjelasan lengkap untuk suatu transaksi."""

    target_entity_id: str
    target_entity_type: str
    generated_at: str
    generated_by: str
    level: str
    language: str
    summary: str
    segments: list[ExplanationSegment]
    root_cause: dict[str, Any] | None
    final_outcome: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_entity_id": self.target_entity_id,
            "target_entity_type": self.target_entity_type,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "level": self.level,
            "language": self.language,
            "summary": self.summary,
            "segments": [s.to_dict() for s in self.segments],
            "root_cause": self.root_cause,
            "final_outcome": self.final_outcome,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_html(self) -> str:
        html = f"""<!DOCTYPE html>
<html>
<head><title>Explanation for {self.target_entity_type} {self.target_entity_id}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
h1 {{ color: #333; }}
h2 {{ color: #555; border-bottom: 1px solid #ccc; }}
.step {{ margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 5px; }}
.metadata {{ font-size: 12px; color: #777; }}
</style>
</head>
<body>
<h1>Causal Explanation</h1>
<p><strong>Target:</strong> {self.target_entity_type} {self.target_entity_id}</p>
<p><strong>Generated:</strong> {self.generated_at} by {self.generated_by}</p>
<p><strong>Level:</strong> {self.level} | <strong>Language:</strong> {self.language}</p>
<h2>Summary</h2>
<p>{self.summary}</p>
<h2>Detailed Steps</h2>
"""
        for seg in self.segments:
            html += f"""
<div class="step">
<b>Step {seg.step_number}:</b> {seg.explanation_text}<br>
<span class="metadata">Node: {seg.node_type} | Entity: {seg.entity_type} {seg.entity_id} | Time: {seg.timestamp} | By: {seg.created_by}</span>
</div>
"""
        if self.root_cause:
            html += f"<h2>Root Cause</h2><p>{self.root_cause.get('entity_type')} {self.root_cause.get('entity_id')} at {self.root_cause.get('timestamp')}</p>"
        if self.final_outcome:
            html += f"<h2>Final Outcome</h2><p>{self.final_outcome.get('entity_type')} {self.final_outcome.get('entity_id')} at {self.final_outcome.get('timestamp')}</p>"
        html += "</body></html>"
        return html


# ============================================================================
# EXPLANATION GENERATOR
# ============================================================================


class ExplanationGenerator:
    """
    Generator untuk penjelasan naratif dari rantai kausalitas.
    """

    _instance: ExplanationGenerator | None = None

    def __new__(cls) -> ExplanationGenerator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._node_service = get_causal_node_service()
        self._chain_builder = get_causal_chain_builder()
        self._history: list[FullExplanation] = []

    # ------------------------------------------------------------------------
    # Node Type Descriptions
    # ------------------------------------------------------------------------
    def _get_node_description(self, node_type: str, language: ExplanationLanguage) -> str:
        if language == ExplanationLanguage.ENGLISH:
            descriptions = {
                "INTENT": "User intent recorded",
                "ECONOMIC_EVENT": "Economic event recognized",
                "JOURNAL_ENTRY": "Journal entry created",
                "PAYMENT": "Payment processed",
                "INVOICE": "Invoice generated",
                "ADJUSTMENT": "Adjustment applied",
                "REVERSAL": "Transaction reversed",
                "CONSOLIDATION": "Consolidated",
                "EXTERNAL": "External source",
            }
        else:
            descriptions = {
                "INTENT": "Maksud pengguna dicatat",
                "ECONOMIC_EVENT": "Event ekonomi diakui",
                "JOURNAL_ENTRY": "Jurnal dibuat",
                "PAYMENT": "Pembayaran diproses",
                "INVOICE": "Faktur dibuat",
                "ADJUSTMENT": "Penyesuaian dilakukan",
                "REVERSAL": "Transaksi dibalik",
                "CONSOLIDATION": "Dikonsolidasi",
                "EXTERNAL": "Sumber eksternal",
            }
        return descriptions.get(node_type, f"Step: {node_type}")

    def _get_relationship_description(
        self, from_type: str, to_type: str, language: ExplanationLanguage
    ) -> str:
        if language == ExplanationLanguage.ENGLISH:
            templates = {
                (
                    "INTENT",
                    "ECONOMIC_EVENT",
                ): "This intent led to the recognition of an economic event.",
                (
                    "ECONOMIC_EVENT",
                    "JOURNAL_ENTRY",
                ): "The economic event was recorded as a journal entry.",
                ("JOURNAL_ENTRY", "PAYMENT"): "The journal entry resulted in a payment.",
                ("JOURNAL_ENTRY", "REVERSAL"): "This journal entry was reversed.",
                ("ECONOMIC_EVENT", "ADJUSTMENT"): "An adjustment was made to this economic event.",
            }
        else:
            templates = {
                ("INTENT", "ECONOMIC_EVENT"): "Maksud ini menyebabkan diakuinya event ekonomi.",
                ("ECONOMIC_EVENT", "JOURNAL_ENTRY"): "Event ekonomi dicatat sebagai jurnal.",
                ("JOURNAL_ENTRY", "PAYMENT"): "Jurnal ini menghasilkan pembayaran.",
                ("JOURNAL_ENTRY", "REVERSAL"): "Jurnal ini dibalik.",
                ("ECONOMIC_EVENT", "ADJUSTMENT"): "Penyesuaian dilakukan pada event ekonomi ini.",
            }
        return templates.get((from_type, to_type), f"Transition from {from_type} to {to_type}.")

    # ------------------------------------------------------------------------
    # Core Generation
    # ------------------------------------------------------------------------
    def generate_explanation(
        self,
        entity_id: UUID,
        entity_type: str,
        generated_by: str,
        level: ExplanationLevel = ExplanationLevel.STANDARD,
        language: ExplanationLanguage = ExplanationLanguage.ENGLISH,
        output_format: ExplanationFormat = ExplanationFormat.TEXT,
    ) -> str | FullExplanation:
        """
        Menghasilkan penjelasan naratif untuk suatu entitas.
        """
        # Get traceability report
        trace = self._chain_builder.get_traceability_report(entity_id, entity_type)
        if "error" in trace:
            error_msg = f"Unable to generate explanation: {trace['error']}"
            if output_format == ExplanationFormat.TEXT:
                return error_msg
            else:
                return FullExplanation(
                    target_entity_id=str(entity_id),
                    target_entity_type=entity_type,
                    generated_at=datetime.now(UTC).isoformat(),
                    generated_by=generated_by,
                    level=level.value,
                    language=language.value,
                    summary=error_msg,
                    segments=[],
                    root_cause=None,
                    final_outcome=None,
                )

        chain = trace.get("chain", [])
        if not chain:
            no_chain_msg = "No causal chain found for this entity."
            if output_format == ExplanationFormat.TEXT:
                return no_chain_msg
            else:
                return FullExplanation(
                    target_entity_id=str(entity_id),
                    target_entity_type=entity_type,
                    generated_at=datetime.now(UTC).isoformat(),
                    generated_by=generated_by,
                    level=level.value,
                    language=language.value,
                    summary=no_chain_msg,
                    segments=[],
                    root_cause=None,
                    final_outcome=None,
                )

        # Generate segments
        segments = self._generate_segments(chain, level, language)

        # Generate summary
        summary = self._generate_summary(chain, trace, level, language)

        # Get root cause and final outcome
        root_cause = trace.get("root_cause")
        final_outcome = trace.get("final_outcome")

        full_explanation = FullExplanation(
            target_entity_id=str(entity_id),
            target_entity_type=entity_type,
            generated_at=datetime.now(UTC).isoformat(),
            generated_by=generated_by,
            level=level.value,
            language=language.value,
            summary=summary,
            segments=segments,
            root_cause=root_cause,
            final_outcome=final_outcome,
        )

        self._history.append(full_explanation)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        if output_format == ExplanationFormat.TEXT:
            return self._format_as_text(full_explanation)
        elif output_format == ExplanationFormat.HTML:
            return full_explanation.to_html()
        else:
            return full_explanation

    def _generate_segments(
        self,
        chain: list[dict[str, Any]],
        level: ExplanationLevel,
        language: ExplanationLanguage,
    ) -> list[ExplanationSegment]:
        """Generate step-by-step explanation segments."""
        segments = []
        for i, node in enumerate(chain):
            node_type = node.get("node_type", "UNKNOWN")
            entity_type = node.get("entity_type", "unknown")
            entity_id = node.get("entity_id", "")
            timestamp = node.get("timestamp", "")
            created_by = node.get("created_by", "unknown")
            metadata = node.get("metadata", {})

            base_desc = self._get_node_description(node_type, language)
            if level == ExplanationLevel.SUMMARY:
                explanation = base_desc
            elif level == ExplanationLevel.STANDARD:
                explanation = f"{base_desc} on {timestamp[:10]} by {created_by}."
            elif level == ExplanationLevel.DETAILED:
                explanation = f"{base_desc} on {timestamp[:19]} by {created_by}. Entity ID: {entity_id[:12]}..."
            else:  # FORENSIC
                explanation = f"{base_desc} on {timestamp} by {created_by}. Entity: {entity_type}/{entity_id}. Metadata: {json.dumps(metadata)[:100]}"

            segments.append(
                ExplanationSegment(
                    step_number=i + 1,
                    node_type=node_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    timestamp=timestamp,
                    created_by=created_by,
                    explanation_text=explanation,
                    metadata=metadata if level == ExplanationLevel.FORENSIC else {},
                )
            )
        return segments

    def _generate_summary(
        self,
        chain: list[dict[str, Any]],
        trace: dict[str, Any],
        level: ExplanationLevel,
        language: ExplanationLanguage,
    ) -> str:
        """Generate summary explanation."""
        if language == ExplanationLanguage.ENGLISH:
            if level == ExplanationLevel.SUMMARY:
                return f"Transaction originated from {trace.get('root_cause', {}).get('entity_type', 'unknown')}. Total causal steps: {len(chain)}"
            else:
                return f"This transaction has a causal chain of {len(chain)} steps, originating from {trace.get('root_cause', {}).get('entity_type', 'unknown')} and resulting in {trace.get('final_outcome', {}).get('entity_type', 'unknown')}."
        else:
            if level == ExplanationLevel.SUMMARY:
                return f"Transaksi berasal dari {trace.get('root_cause', {}).get('entity_type', 'unknown')}. Total langkah kausal: {len(chain)}"
            else:
                return f"Transaksi ini memiliki rantai kausal sepanjang {len(chain)} langkah, berasal dari {trace.get('root_cause', {}).get('entity_type', 'unknown')} dan menghasilkan {trace.get('final_outcome', {}).get('entity_type', 'unknown')}."

    def _format_as_text(self, explanation: FullExplanation) -> str:
        """Format FullExplanation as plain text."""
        lines = [
            f"CAUSAL EXPLANATION FOR {explanation.target_entity_type.upper()} {explanation.target_entity_id}",
            "=" * 60,
            f"Generated: {explanation.generated_at} by {explanation.generated_by}",
            f"Level: {explanation.level} | Language: {explanation.language}",
            "",
            "SUMMARY",
            "-" * 30,
            explanation.summary,
            "",
            "DETAILED STEPS",
            "-" * 30,
        ]
        for seg in explanation.segments:
            lines.append(f"Step {seg.step_number}: {seg.explanation_text}")
        if explanation.root_cause:
            lines.extend(
                [
                    "",
                    "ROOT CAUSE",
                    "-" * 30,
                    f"{explanation.root_cause.get('entity_type')} {explanation.root_cause.get('entity_id')} at {explanation.root_cause.get('timestamp')}",
                ]
            )
        if explanation.final_outcome:
            lines.extend(
                [
                    "",
                    "FINAL OUTCOME",
                    "-" * 30,
                    f"{explanation.final_outcome.get('entity_type')} {explanation.final_outcome.get('entity_id')} at {explanation.final_outcome.get('timestamp')}",
                ]
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------------
    # Additional Generation Methods
    # ------------------------------------------------------------------------
    def generate_why_explanation(
        self,
        entity_id: UUID,
        entity_type: str,
        generated_by: str,
        language: ExplanationLanguage = ExplanationLanguage.ENGLISH,
    ) -> str:
        """
        Generates a "Why did this happen?" explanation focused on upstream causes.
        """
        upstream = self._chain_builder.get_traceability_report(entity_id, entity_type)
        if "error" in upstream:
            return f"Unable to determine why: {upstream['error']}"
        chain = upstream.get("chain", [])
        if not chain:
            return f"No causal information found for {entity_type} {entity_id}."
        # The "why" focuses on the root cause
        root = upstream.get("root_cause")
        if not root:
            return f"Unable to determine root cause for {entity_type} {entity_id}."
        if language == ExplanationLanguage.ENGLISH:
            return f"This {entity_type} occurred because of {root.get('entity_type')} {root.get('entity_id')} which happened at {root.get('timestamp')}. Chain length: {len(chain)}."
        else:
            return f"{entity_type} ini terjadi karena {root.get('entity_type')} {root.get('entity_id')} yang terjadi pada {root.get('timestamp')}. Panjang rantai: {len(chain)}."

    def generate_what_if_explanation(
        self,
        entity_id: UUID,
        entity_type: str,
        hypothetical_change: str,
        generated_by: str,
        language: ExplanationLanguage = ExplanationLanguage.ENGLISH,
    ) -> str:
        """
        Simulates a "what if" explanation (conceptual, not actual simulation).
        """
        impact = self._chain_builder.get_impact_chain(entity_id, entity_type)
        if language == ExplanationLanguage.ENGLISH:
            return f"If '{hypothetical_change}' were applied to {entity_type} {entity_id}, it could potentially affect {len(impact)} downstream entities."
        else:
            return f"Jika '{hypothetical_change}' diterapkan pada {entity_type} {entity_id}, ini dapat mempengaruhi {len(impact)} entitas downstream."

    # ------------------------------------------------------------------------
    # History & Statistics
    # ------------------------------------------------------------------------
    def get_history(self, limit: int = 100) -> list[FullExplanation]:
        return self._history[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        total = len(self._history)
        if total == 0:
            return {"total_explanations": 0}
        by_level = {}
        for exp in self._history:
            level = exp.level
            by_level[level] = by_level.get(level, 0) + 1
        by_lang = {}
        for exp in self._history:
            lang = exp.language
            by_lang[lang] = by_lang.get(lang, 0) + 1
        return {
            "total_explanations": total,
            "by_level": by_level,
            "by_language": by_lang,
        }

    def reset(self) -> None:
        self._history.clear()


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_explanation_generator_instance: ExplanationGenerator | None = None


def get_explanation_generator() -> ExplanationGenerator:
    global _explanation_generator_instance
    if _explanation_generator_instance is None:
        _explanation_generator_instance = ExplanationGenerator()
    return _explanation_generator_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ExplanationFormat",
    "ExplanationGenerator",
    "ExplanationLanguage",
    "ExplanationLevel",
    "ExplanationSegment",
    "FullExplanation",
    "get_explanation_generator",
]
