#!/usr/bin/env python3
"""
Module: audit_story_builder.py
Layer: Domain / Causality
Responsibility: Membangun cerita audit naratif dari rantai kausalitas.
               Mendukung berbagai format output, template, dan integrasi
               dengan explanation generator dan causality tracker.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from domain.causality.causal_chain_builder import get_causal_chain_builder
from domain.causality.causal_node import get_causal_node_service
from domain.causality.causality_tracker import get_causality_tracker
from domain.causality.explanation_generator import (
    ExplanationLanguage,
    ExplanationLevel,
    get_explanation_generator,
)

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================


class AuditStoryFormat(Enum):
    TEXT = "text"  # Plain text narrative
    JSON = "json"  # Structured JSON
    HTML = "html"  # HTML report
    PDF = "pdf"  # PDF (placeholder - will generate HTML with PDF hint)


class AuditStorySection(Enum):
    HEADER = "header"
    EXECUTIVE_SUMMARY = "executive_summary"
    TIMELINE = "timeline"
    PARTIES = "parties"
    CAUSAL_CHAIN = "causal_chain"
    FINANCIAL_IMPACT = "financial_impact"
    APPROVALS = "approvals"
    RISK_ASSESSMENT = "risk_assessment"
    FORENSIC_DETAILS = "forensic_details"
    CONCLUSION = "conclusion"
    FOOTER = "footer"


class AuditStoryStatus(Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    ARCHIVED = "archived"


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class AuditEvent:
    """Single event in audit timeline."""

    sequence: int
    timestamp: datetime
    event_type: str
    entity_type: str
    entity_id: UUID
    actor: str
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "actor": self.actor,
            "description": self.description,
            "metadata": self.metadata,
        }


@dataclass
class AuditStory:
    """Complete audit story for a transaction."""

    story_id: UUID
    transaction_id: UUID
    transaction_type: str
    legal_entity_id: UUID | None
    generated_at: datetime
    generated_by: str
    format: AuditStoryFormat
    language: ExplanationLanguage
    sections: dict[AuditStorySection, str]
    timeline: list[AuditEvent]
    status: AuditStoryStatus
    cryptographic_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_hash(self) -> str:
        content = {
            "story_id": str(self.story_id),
            "transaction_id": str(self.transaction_id),
            "transaction_type": self.transaction_type,
            "generated_at": self.generated_at.isoformat(),
            "generated_by": self.generated_by,
            "sections": {k.value: v for k, v in self.sections.items()},
            "timeline": [e.to_dict() for e in self.timeline],
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def __post_init__(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_id": str(self.story_id),
            "transaction_id": str(self.transaction_id),
            "transaction_type": self.transaction_type,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "generated_at": self.generated_at.isoformat(),
            "generated_by": self.generated_by,
            "format": self.format.value,
            "language": self.language.value,
            "sections": {k.value: v for k, v in self.sections.items()},
            "timeline": [e.to_dict() for e in self.timeline],
            "status": self.status.value,
            "cryptographic_hash": self.cryptographic_hash,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_html(self) -> str:
        sections_html = ""
        for section in [
            AuditStorySection.HEADER,
            AuditStorySection.EXECUTIVE_SUMMARY,
            AuditStorySection.TIMELINE,
            AuditStorySection.PARTIES,
            AuditStorySection.CAUSAL_CHAIN,
            AuditStorySection.FINANCIAL_IMPACT,
            AuditStorySection.APPROVALS,
            AuditStorySection.RISK_ASSESSMENT,
            AuditStorySection.FORENSIC_DETAILS,
            AuditStorySection.CONCLUSION,
        ]:
            content = self.sections.get(section, "")
            if content:
                sections_html += f"""
    <div class="section">
        <h2>{section.value.replace("_", " ").title()}</h2>
        <div class="content">{content.replace(chr(10), "<br>")}</div>
    </div>
"""
        timeline_html = ""
        for event in self.timeline:
            timeline_html += f"""
    <tr>
        <td>{event.sequence}</td>
        <td>{event.timestamp.isoformat()}</td>
        <td>{event.event_type}</td>
        <td>{event.entity_type}/{event.entity_id.hex[:8]}</td>
        <td>{event.actor}</td>
        <td>{event.description[:100]}</td>
    </tr>
"""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Audit Story - {self.transaction_id.hex[:8]}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 30px; background: #f8f9fa; }}
        .container {{ max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; border-left: 4px solid #3498db; padding-left: 10px; margin-top: 25px; }}
        .section {{ margin-bottom: 30px; }}
        .content {{ padding: 10px; background: #f1f3f5; border-radius: 5px; white-space: pre-wrap; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
        .footer {{ margin-top: 40px; font-size: 12px; color: #777; text-align: center; border-top: 1px solid #ddd; padding-top: 15px; }}
        .hash {{ font-family: monospace; font-size: 10px; color: #999; }}
    </style>
</head>
<body>
<div class="container">
    <h1>Audit Story</h1>
    <div class="hash">Story ID: {self.story_id} | Hash: {self.cryptographic_hash[:16]}...</div>
    {sections_html}
    <div class="section">
        <h2>Timeline</h2>
        <table>
            <tr><th>Seq</th><th>Timestamp</th><th>Event Type</th><th>Entity</th><th>Actor</th><th>Description</th></tr>
            {timeline_html}
        </table>
    </div>
    <div class="footer">
        Generated: {self.generated_at.isoformat()} by {self.generated_by}<br>
        Status: {self.status.value} | Format: {self.format.value} | Language: {self.language.value}
    </div>
</div>
</body>
</html>"""
        return html

    def to_text(self) -> str:
        lines = [
            f"AUDIT STORY - {self.transaction_type.upper()} {self.transaction_id.hex[:8]}",
            "=" * 60,
            f"Story ID: {self.story_id}",
            f"Generated: {self.generated_at.isoformat()} by {self.generated_by}",
            f"Status: {self.status.value} | Language: {self.language.value}",
            "",
        ]
        for section in [
            AuditStorySection.HEADER,
            AuditStorySection.EXECUTIVE_SUMMARY,
            AuditStorySection.TIMELINE,
            AuditStorySection.PARTIES,
            AuditStorySection.CAUSAL_CHAIN,
            AuditStorySection.FINANCIAL_IMPACT,
            AuditStorySection.APPROVALS,
            AuditStorySection.RISK_ASSESSMENT,
            AuditStorySection.CONCLUSION,
        ]:
            content = self.sections.get(section, "")
            if content:
                lines.append(f"\n{section.value.replace('_', ' ').upper()}")
                lines.append("-" * 40)
                lines.append(content)
        lines.append("\n\nTIMELINE")
        lines.append("-" * 40)
        for event in self.timeline:
            lines.append(
                f"{event.sequence:3d} | {event.timestamp.isoformat()} | {event.event_type:15} | {event.entity_type}/{event.entity_id.hex[:8]} | {event.actor}"
            )
        lines.append(f"\nHash: {self.cryptographic_hash}")
        return "\n".join(lines)

    def export(self, filepath: str) -> None:
        """Export story to file based on format."""
        if self.format == AuditStoryFormat.TEXT:
            content = self.to_text()
        elif self.format == AuditStoryFormat.HTML:
            content = self.to_html()
        else:
            content = self.to_json()
        Path(filepath).write_text(content, encoding="utf-8")
        logger.info(f"Audit story exported to {filepath}")


# ============================================================================
# AUDIT STORY BUILDER
# ============================================================================


class AuditStoryBuilder:
    """
    Builder untuk cerita audit lengkap dengan narasi, timeline, dan analisis.
    """

    _instance: AuditStoryBuilder | None = None

    def __new__(cls) -> AuditStoryBuilder:
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
        self._causality_tracker = get_causality_tracker()
        self._explanation_gen = get_explanation_generator()
        self._stories: list[AuditStory] = []
        self._audit_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------------
    def _log_audit(self, action: str, story_id: UUID, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "story_id": str(story_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"AUDIT STORY BUILDER: {action} on {story_id}")

    # ------------------------------------------------------------------------
    # Section Builders
    # ------------------------------------------------------------------------
    def _build_header(
        self,
        transaction_id: UUID,
        transaction_type: str,
        legal_entity_id: UUID | None,
        language: ExplanationLanguage,
    ) -> str:
        if language == ExplanationLanguage.ENGLISH:
            return f"""Transaction ID: {transaction_id}
Transaction Type: {transaction_type}
Legal Entity: {legal_entity_id if legal_entity_id else "Global"}
Report Generated: {datetime.now(UTC).isoformat()}
This audit trail document provides a complete causal narrative of the transaction."""
        else:
            return f"""ID Transaksi: {transaction_id}
Jenis Transaksi: {transaction_type}
Entitas Hukum: {legal_entity_id if legal_entity_id else "Global"}
Laporan Dibuat: {datetime.now(UTC).isoformat()}
Dokumen jejak audit ini menyediakan narasi kausal lengkap transaksi."""

    def _build_executive_summary(
        self,
        trace: dict[str, Any],
        impact: dict[str, Any],
        language: ExplanationLanguage,
    ) -> str:
        chain_len = len(trace["chain"]) if "chain" in trace else 0
        root = trace.get("root_cause", {})
        final = trace.get("final_outcome", {})
        downstream = impact.get("downstream_count", 0)

        if language == ExplanationLanguage.ENGLISH:
            if root:
                root_text = (
                    f"The transaction originates from a {root.get('entity_type', 'unknown')} event."
                )
            else:
                root_text = "The origin of this transaction could not be determined."
            return f"""This {chain_len}-step causal chain describes a transaction that {"impacts " + str(downstream) + " downstream entities" if downstream else "has no recorded downstream impact"}.
{root_text}
The final outcome is a {final.get('entity_type', 'unknown')}.
Total causal steps: {chain_len}."""
        else:
            if root:
                root_text = (
                    f"Transaksi ini berasal dari event {root.get('entity_type', 'unknown')}."
                )
            else:
                root_text = "Asal transaksi ini tidak dapat ditentukan."
            return f"""Rantai kausal sepanjang {chain_len} langkah ini {"memengaruhi " + str(downstream) + " entitas downstream" if downstream else "tidak memiliki dampak downstream tercatat"}.
{root_text}
Hasil akhir adalah {final.get('entity_type', 'unknown')}.
Total langkah kausal: {chain_len}."""

    def _build_timeline_section(
        self,
        chain: list[dict[str, Any]],
        language: ExplanationLanguage,
    ) -> tuple[str, list[AuditEvent]]:
        events = []
        text_lines = []
        for i, node in enumerate(chain):
            ts = node.get("timestamp", "")
            node_type = node.get("node_type", "UNKNOWN")
            entity_type = node.get("entity_type", "unknown")
            entity_id = UUID(node["entity_id"]) if "entity_id" in node else uuid4()
            created_by = node.get("created_by", "system")
            desc = self._get_node_description(node_type, language)
            events.append(
                AuditEvent(
                    sequence=i + 1,
                    timestamp=datetime.fromisoformat(ts) if ts else datetime.now(UTC),
                    event_type=node_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    actor=created_by,
                    description=desc,
                    metadata=node.get("metadata", {}),
                )
            )
            if language == ExplanationLanguage.ENGLISH:
                text_lines.append(f"{i + 1}. {ts[:19]} - {node_type}: {desc} (by {created_by})")
            else:
                text_lines.append(f"{i + 1}. {ts[:19]} - {node_type}: {desc} (oleh {created_by})")
        return "\n".join(text_lines), events

    def _build_parties_section(
        self, chain: list[dict[str, Any]], language: ExplanationLanguage
    ) -> str:
        actors = set()
        for node in chain:
            actor = node.get("created_by", "system")
            actors.add(actor)
        if language == ExplanationLanguage.ENGLISH:
            lines = ["The following parties were involved in the causal chain:"]
            for actor in sorted(actors):
                lines.append(f"  - {actor}")
            return "\n".join(lines)
        else:
            lines = ["Pihak-pihak berikut terlibat dalam rantai kausal:"]
            for actor in sorted(actors):
                lines.append(f"  - {actor}")
            return "\n".join(lines)

    def _build_causal_chain_section(
        self,
        chain: list[dict[str, Any]],
        impact: dict[str, Any],
        language: ExplanationLanguage,
        level: ExplanationLevel,
    ) -> str:
        if level == ExplanationLevel.SUMMARY:
            return self._build_executive_summary({"chain": chain}, impact, language)

        lines = []
        for i, node in enumerate(chain):
            node_type = node.get("node_type", "UNKNOWN")
            entity_type = node.get("entity_type", "unknown")
            entity_id = node.get("entity_id", "")
            ts = node.get("timestamp", "")
            actor = node.get("created_by", "system")
            desc = self._get_node_description(node_type, language)
            if level == ExplanationLevel.STANDARD:
                lines.append(f"Step {i + 1}: {node_type} - {desc}")
            elif level == ExplanationLevel.DETAILED:
                lines.append(f"Step {i + 1}: {node_type} on {ts[:19]} by {actor} - {desc}")
            else:  # FORENSIC
                lines.append(
                    f"Step {i + 1}: {node_type} ({entity_type}/{entity_id[:12]}) at {ts} by {actor} - {desc}"
                )
        return "\n".join(lines)

    def _build_financial_impact_section(
        self,
        transaction_id: UUID,
        transaction_type: str,
        language: ExplanationLanguage,
    ) -> str:
        if language == ExplanationLanguage.ENGLISH:
            return f"""Financial impact analysis for transaction {transaction_id}:
- Transaction Type: {transaction_type}
- Amount: To be retrieved from journal/ledger
- Currency: Based on transaction currency
Note: Detailed financial data requires integration with accounting module."""
        else:
            return f"""Analisis dampak finansial untuk transaksi {transaction_id}:
- Jenis Transaksi: {transaction_type}
- Jumlah: Diambil dari jurnal/buku besar
- Mata Uang: Berdasarkan mata uang transaksi
Catatan: Data finansial detail memerlukan integrasi dengan modul akuntansi."""

    def _build_approvals_section(
        self, chain: list[dict[str, Any]], language: ExplanationLanguage
    ) -> str:
        approvals = []
        for node in chain:
            if node.get("node_type") == "APPROVAL":
                actor = node.get("created_by", "unknown")
                ts = node.get("timestamp", "")
                approvals.append(f"  - Approved by {actor} at {ts[:19]}")
        if not approvals:
            if language == ExplanationLanguage.ENGLISH:
                return "No explicit approval events found in the causal chain."
            else:
                return "Tidak ditemukan event approval dalam rantai kausal."
        if language == ExplanationLanguage.ENGLISH:
            return "Approval events:\n" + "\n".join(approvals)
        else:
            return "Event approval:\n" + "\n".join(approvals)

    def _build_risk_assessment_section(
        self,
        chain: list[dict[str, Any]],
        impact: dict[str, Any],
        language: ExplanationLanguage,
    ) -> str:
        downstream_count = impact.get("downstream_count", 0)
        upstream_count = impact.get("upstream_count", 0)
        has_cycles = impact.get("has_cycles", False)

        if language == ExplanationLanguage.ENGLISH:
            risk_level = (
                "HIGH"
                if downstream_count > 10
                else "MEDIUM"
                if downstream_count > 3
                else "LOW"
            )
            return f"""Risk Assessment:
- Risk Level: {risk_level}
- Number of downstream entities: {downstream_count}
- Number of upstream dependencies: {upstream_count}
- Cycles detected: {"Yes" if has_cycles else "No"}
- Recommendation: {"Review causal chain for potential systemic risk" if risk_level == "HIGH" else "Normal monitoring sufficient."}"""
        else:
            risk_level = (
                "TINGGI"
                if downstream_count > 10
                else "SEDANG"
                if downstream_count > 3
                else "RENDAH"
            )
            return f"""Penilaian Risiko:
- Tingkat Risiko: {risk_level}
- Jumlah entitas downstream: {downstream_count}
- Jumlah dependensi upstream: {upstream_count}
- Siklus terdeteksi: {"Ya" if has_cycles else "Tidak"}
- Rekomendasi: {"Tinjau rantai kausal untuk risiko sistemik" if risk_level == "TINGGI" else "Pemantauan normal cukup."}"""

    def _build_forensic_details_section(
        self,
        chain: list[dict[str, Any]],
        language: ExplanationLanguage,
    ) -> str:
        if language == ExplanationLanguage.ENGLISH:
            lines = ["FORENSIC DETAILS", "=" * 20]
            for node in chain:
                node_id = node.get("node_id", "")
                entity_id = node.get("entity_id", "")
                metadata = node.get("metadata", {})
                lines.append(f"Node: {node_id}")
                lines.append(f"  Entity: {entity_id}")
                lines.append(f"  Metadata: {json.dumps(metadata, indent=2)}")
            return "\n".join(lines)
        else:
            lines = ["DETAIL FORENSIK", "=" * 20]
            for node in chain:
                node_id = node.get("node_id", "")
                entity_id = node.get("entity_id", "")
                metadata = node.get("metadata", {})
                lines.append(f"Node: {node_id}")
                lines.append(f"  Entitas: {entity_id}")
                lines.append(f"  Metadata: {json.dumps(metadata, indent=2)}")
            return "\n".join(lines)

    def _build_conclusion_section(
        self,
        trace: dict[str, Any],
        impact: dict[str, Any],
        language: ExplanationLanguage,
    ) -> str:
        chain_len = len(trace["chain"]) if "chain" in trace else 0
        has_cycle = impact.get("has_cycles", False)
        if language == ExplanationLanguage.ENGLISH:
            integrity = "VERIFIED" if not has_cycle else "WARNING - Cycle Detected"
            return f"""CONCLUSION
The causal chain has been fully traced with {chain_len} steps.
Audit trail integrity: {integrity}
{"A cycle was detected in the causal graph. This may indicate a circular dependency that should be investigated." if has_cycle else "No cycles detected. The causal chain is acyclic."}
This audit story provides a complete, verifiable record of the transaction's causal history."""
        else:
            integrity = "TERVERIFIKASI" if not has_cycle else "PERINGATAN - Siklus Terdeteksi"
            return f"""KESIMPULAN
Rantai kausal telah dilacak sepenuhnya dengan {chain_len} langkah.
Integritas jejak audit: {integrity}
{"Siklus terdeteksi dalam graf kausal. Ini mungkin menunjukkan dependensi sirkular yang perlu diselidiki." if has_cycle else "Tidak ada siklus terdeteksi. Rantai kausal bersifat asiklik."}
Cerita audit ini menyediakan rekaman lengkap dan terverifikasi dari sejarah kausal transaksi."""

    def _build_footer(self, story_id: UUID, hash_val: str, language: ExplanationLanguage) -> str:
        if language == ExplanationLanguage.ENGLISH:
            return f"Audit Story ID: {story_id}\nCryptographic Hash: {hash_val}\nThis document is cryptographically sealed. Any alteration will invalidate the hash."
        else:
            return f"ID Cerita Audit: {story_id}\nHash Kriptografi: {hash_val}\nDokumen ini dimeterai secara kriptografis. Perubahan apapun akan membatalkan hash."

    def _get_node_description(self, node_type: str, language: ExplanationLanguage) -> str:
        if language == ExplanationLanguage.ENGLISH:
            desc = {
                "INTENT": "User intent captured",
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
            desc = {
                "INTENT": "Maksud pengguna ditangkap",
                "ECONOMIC_EVENT": "Event ekonomi diakui",
                "JOURNAL_ENTRY": "Jurnal dibuat",
                "PAYMENT": "Pembayaran diproses",
                "INVOICE": "Faktur dibuat",
                "ADJUSTMENT": "Penyesuaian dilakukan",
                "REVERSAL": "Transaksi dibalik",
                "CONSOLIDATION": "Dikonsolidasi",
                "EXTERNAL": "Sumber eksternal",
            }
        return desc.get(node_type, f"Step: {node_type}")

    # ------------------------------------------------------------------------
    # Main Build Method
    # ------------------------------------------------------------------------
    def build_audit_story(
        self,
        transaction_id: UUID,
        transaction_type: str,
        generated_by: str,
        format: AuditStoryFormat = AuditStoryFormat.TEXT,
        language: ExplanationLanguage = ExplanationLanguage.ENGLISH,
        level: ExplanationLevel = ExplanationLevel.DETAILED,
        legal_entity_id: UUID | None = None,
        include_forensic: bool = True,
    ) -> AuditStory:
        """
        Membangun cerita audit lengkap untuk suatu transaksi.
        """
        story_id = uuid4()
        self._log_audit(
            "BUILD_START",
            story_id,
            {"transaction_id": str(transaction_id), "type": transaction_type},
        )

        trace = self._chain_builder.get_traceability_report(transaction_id, transaction_type)
        if "error" in trace:
            error_msg = trace["error"]
            sections = {
                AuditStorySection.HEADER: f"Error: {error_msg}",
                AuditStorySection.EXECUTIVE_SUMMARY: f"Could not build audit story: {error_msg}",
                AuditStorySection.CONCLUSION: "Build failed.",
            }
            story = AuditStory(
                story_id=story_id,
                transaction_id=transaction_id,
                transaction_type=transaction_type,
                legal_entity_id=legal_entity_id,
                generated_at=datetime.now(UTC),
                generated_by=generated_by,
                format=format,
                language=language,
                sections=sections,
                timeline=[],
                status=AuditStoryStatus.DRAFT,
                metadata={"error": error_msg},
            )
            self._stories.append(story)
            self._log_audit("BUILD_ERROR", story_id, {"error": error_msg})
            return story

        chain = trace.get("chain", [])
        impact_analysis = self._causality_tracker.analyze_impact(transaction_id) if chain else None
        impact_dict = impact_analysis.__dict__ if impact_analysis else {}

        sections = {}

        sections[AuditStorySection.HEADER] = self._build_header(
            transaction_id, transaction_type, legal_entity_id, language
        )
        sections[AuditStorySection.EXECUTIVE_SUMMARY] = self._build_executive_summary(
            trace, impact_dict, language
        )
        timeline_text, timeline_events = self._build_timeline_section(chain, language)
        sections[AuditStorySection.TIMELINE] = timeline_text
        sections[AuditStorySection.PARTIES] = self._build_parties_section(chain, language)
        sections[AuditStorySection.CAUSAL_CHAIN] = self._build_causal_chain_section(
            chain, impact_dict, language, level
        )
        sections[AuditStorySection.FINANCIAL_IMPACT] = self._build_financial_impact_section(
            transaction_id, transaction_type, language
        )
        sections[AuditStorySection.APPROVALS] = self._build_approvals_section(chain, language)
        sections[AuditStorySection.RISK_ASSESSMENT] = self._build_risk_assessment_section(
            chain, impact_dict, language
        )
        if include_forensic:
            sections[AuditStorySection.FORENSIC_DETAILS] = self._build_forensic_details_section(
                chain, language
            )
        sections[AuditStorySection.CONCLUSION] = self._build_conclusion_section(
            trace, impact_dict, language
        )
        sections[AuditStorySection.FOOTER] = self._build_footer(
            story_id, "", language
        )

        story = AuditStory(
            story_id=story_id,
            transaction_id=transaction_id,
            transaction_type=transaction_type,
            legal_entity_id=legal_entity_id,
            generated_at=datetime.now(UTC),
            generated_by=generated_by,
            format=format,
            language=language,
            sections=sections,
            timeline=timeline_events,
            status=AuditStoryStatus.DRAFT,
            metadata={"level": level.value, "include_forensic": include_forensic},
        )
        story.sections[AuditStorySection.FOOTER] = self._build_footer(
            story_id, story.cryptographic_hash, language
        )

        self._stories.append(story)
        self._log_audit(
            "BUILD_SUCCESS", story_id, {"chain_length": len(chain), "events": len(timeline_events)}
        )
        return story

    # ------------------------------------------------------------------------
    # Story Management
    # ------------------------------------------------------------------------
    def get_story(self, story_id: UUID) -> AuditStory | None:
        for story in self._stories:
            if story.story_id == story_id:
                return story
        return None

    def get_stories_by_transaction(self, transaction_id: UUID) -> list[AuditStory]:
        return [s for s in self._stories if s.transaction_id == transaction_id]

    def finalize_story(self, story_id: UUID, finalizer: str) -> AuditStory | None:
        story = self.get_story(story_id)
        if not story:
            return None
        updated = AuditStory(
            story_id=story.story_id,
            transaction_id=story.transaction_id,
            transaction_type=story.transaction_type,
            legal_entity_id=story.legal_entity_id,
            generated_at=story.generated_at,
            generated_by=story.generated_by,
            format=story.format,
            language=story.language,
            sections=story.sections,
            timeline=story.timeline,
            status=AuditStoryStatus.FINALIZED,
            cryptographic_hash=story.cryptographic_hash,
            metadata={
                **story.metadata,
                "finalized_by": finalizer,
                "finalized_at": datetime.now(UTC).isoformat(),
            },
        )
        for i, s in enumerate(self._stories):
            if s.story_id == story_id:
                self._stories[i] = updated
                break
        self._log_audit("FINALIZE", story_id, {"finalizer": finalizer})
        return updated

    def archive_story(self, story_id: UUID, archiver: str) -> AuditStory | None:
        story = self.get_story(story_id)
        if not story:
            return None
        updated = AuditStory(
            story_id=story.story_id,
            transaction_id=story.transaction_id,
            transaction_type=story.transaction_type,
            legal_entity_id=story.legal_entity_id,
            generated_at=story.generated_at,
            generated_by=story.generated_by,
            format=story.format,
            language=story.language,
            sections=story.sections,
            timeline=story.timeline,
            status=AuditStoryStatus.ARCHIVED,
            cryptographic_hash=story.cryptographic_hash,
            metadata={
                **story.metadata,
                "archived_by": archiver,
                "archived_at": datetime.now(UTC).isoformat(),
            },
        )
        for i, s in enumerate(self._stories):
            if s.story_id == story_id:
                self._stories[i] = updated
                break
        self._log_audit("ARCHIVE", story_id, {"archiver": archiver})
        return updated

    def delete_story(self, story_id: UUID) -> bool:
        original_len = len(self._stories)
        self._stories = [s for s in self._stories if s.story_id != story_id]
        if len(self._stories) < original_len:
            self._log_audit("DELETE", story_id, {})
            return True
        return False

    def list_stories(
        self, status: AuditStoryStatus | None = None, limit: int = 100
    ) -> list[AuditStory]:
        stories = self._stories[-limit:]
        if status:
            stories = [s for s in stories if s.status == status]
        return stories

    # ------------------------------------------------------------------------
    # Statistics & Audit
    # ------------------------------------------------------------------------
    def get_statistics(self) -> dict[str, Any]:
        total = len(self._stories)
        by_status = {}
        for s in self._stories:
            by_status[s.status.value] = by_status.get(s.status.value, 0) + 1
        by_format = {}
        for s in self._stories:
            by_format[s.format.value] = by_format.get(s.format.value, 0) + 1
        return {
            "total_stories": total,
            "by_status": by_status,
            "by_format": by_format,
            "audit_log_size": len(self._audit_log),
        }

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_log[-limit:]

    def reset(self) -> None:
        self._stories.clear()
        self._audit_log.clear()


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_audit_story_builder_instance: AuditStoryBuilder | None = None


def get_audit_story_builder() -> AuditStoryBuilder:
    global _audit_story_builder_instance
    if _audit_story_builder_instance is None:
        _audit_story_builder_instance = AuditStoryBuilder()
    return _audit_story_builder_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AuditEvent",
    "AuditStory",
    "AuditStoryBuilder",
    "AuditStoryFormat",
    "AuditStorySection",
    "AuditStoryStatus",
    "get_audit_story_builder",
]
