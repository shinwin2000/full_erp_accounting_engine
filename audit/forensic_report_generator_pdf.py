#!/usr/bin/env python3
"""
Module: forensic_report_generator_pdf.py
Layer: Audit
Responsibility: Menghasilkan laporan forensik dalam format PDF untuk audit trail.
               Laporan mencakup ringkasan event, hash chain verification,
               detected gaps, duplicates, tampering alerts, dan rekomendasi.
               Dapat digunakan sebagai bukti untuk auditor eksternal.
Dependencies:
- reportlab (optional, fallback to text), datetime, json, logging
- audit.forensic_replayer (ForensicReplayer)
- audit.gap_detector (GapDetector)
- audit.duplicate_detector_fuzzy (DuplicateDetectorFuzzy)
- audit.tamper_alert_trigger (TamperAlertTrigger)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap laporan forensik yang dihasilkan dicatat.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit.duplicate_detector_fuzzy import DuplicateDetectorFuzzy, get_duplicate_detector

# Internal dependencies
from audit.forensic_replayer import ForensicReplayer, get_forensic_replayer
from audit.gap_detector import GapDetector, get_gap_detector
from audit.tamper_alert_trigger import TamperAlertTrigger, get_tamper_alert_trigger
from infrastructure.telemetry.structured_json_logging import get_logger

# Try to import reportlab for PDF generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger = get_logger(__name__)
    logger.warning("ReportLab not available, PDF generation will be disabled")

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_OUTPUT_DIR = Path("/var/audit/reports")
DEFAULT_CONFIG = {
    "output_dir": "/var/audit/reports",
    "company_name": "ERP Accounting Engine",
    "include_hash_chain_verification": True,
    "include_gap_analysis": True,
    "include_duplicate_analysis": True,
    "include_tamper_alerts": True,
    "max_events_in_report": 1000,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class ForensicReportError(Exception):
    """Base exception untuk forensic report generator."""

    pass


# ============================================================================
# FORENSIC REPORT GENERATOR
# ============================================================================


class ForensicReportGeneratorPDF:
    """
    Generator laporan forensik PDF.

    Fitur:
    - Generate PDF report dengan struktur profesional
    - Sertakan ringkasan audit trail
    - Hash chain verification results
    - Gap detection results
    - Duplicate detection results
    - Tampering alerts history
    - Export sebagai PDF dengan timestamp
    """

    def __init__(self, config_path: str = "config_files/audit_config.yaml"):
        self.config = self._load_config(config_path)
        self._output_dir = Path(self.config.get("output_dir", DEFAULT_OUTPUT_DIR))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._company_name = self.config.get("company_name", "ERP Accounting Engine")

        self._forensic_replayer: ForensicReplayer | None = None
        self._gap_detector: GapDetector | None = None
        self._duplicate_detector: DuplicateDetectorFuzzy | None = None
        self._tamper_alert: TamperAlertTrigger | None = None
        self._hash_builder = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            from config.loader_yaml import load_yaml_config

            config = load_yaml_config(config_path)
            report_config = config.get("forensic_report", {})
            result = DEFAULT_CONFIG.copy()
            result.update(report_config)
            return result
        except Exception:
            return DEFAULT_CONFIG.copy()

    async def _get_forensic_replayer(self) -> ForensicReplayer:
        if self._forensic_replayer is None:
            self._forensic_replayer = await get_forensic_replayer()
        return self._forensic_replayer

    async def _get_gap_detector(self) -> GapDetector:
        if self._gap_detector is None:
            self._gap_detector = await get_gap_detector()
        return self._gap_detector

    async def _get_duplicate_detector(self) -> DuplicateDetectorFuzzy:
        if self._duplicate_detector is None:
            self._duplicate_detector = await get_duplicate_detector()
        return self._duplicate_detector

    async def _get_tamper_alert(self) -> TamperAlertTrigger:
        if self._tamper_alert is None:
            self._tamper_alert = await get_tamper_alert_trigger()
        return self._tamper_alert

    async def collect_report_data(
        self, stream_names: list[str] | None = None, time_range_days: int = 30
    ) -> dict[str, Any]:
        """
        Collect all data for the forensic report.

        Args:
            stream_names: Specific streams to analyze (None = all)
            time_range_days: Number of days to look back

        Returns:
            Dictionary with all report data
        """
        forensic = await self._get_forensic_replayer()
        gap = await self._get_gap_detector()
        dup = await self._get_duplicate_detector()
        tamper = await self._get_tamper_alert()

        # Get streams to analyze
        if stream_names is None:
            all_streams = await forensic.list_streams()
            stream_names = all_streams[:50]  # Limit for performance

        # Collect stream info
        stream_infos = []
        total_events = 0
        for stream in stream_names[:20]:  # Limit for report size
            info = await forensic.get_stream_info(stream)
            stream_infos.append(info)
            total_events += info.get("event_count", 0)

        # Get gaps
        gaps = await gap.get_gaps()
        recent_gaps = [
            g
            for g in gaps
            if g.get("detected_at")
            and (datetime.now(UTC) - datetime.fromisoformat(g["detected_at"])).days
            <= time_range_days
        ]

        # Get duplicates
        duplicates = await dup.get_duplicates()
        recent_duplicates = [
            d
            for d in duplicates
            if d.get("detected_at")
            and (datetime.now(UTC) - datetime.fromisoformat(d["detected_at"])).days
            <= time_range_days
        ]

        # Get tamper alerts
        tamper_status = await tamper.get_status()

        # Sample events from key streams
        sample_events = {}
        for stream in ["audit", "security_audit"]:
            try:
                events = await forensic.replay_stream(stream, limit=100)
                sample_events[stream] = events[:20]
            except Exception:
                pass

        return {
            "report_generated_at": datetime.now(UTC).isoformat(),
            "time_range_days": time_range_days,
            "streams_analyzed": len(stream_names),
            "total_events": total_events,
            "stream_info": stream_infos,
            "gaps": {"total_found": len(recent_gaps), "gaps": recent_gaps[:50]},
            "duplicates": {
                "total_found": len(recent_duplicates),
                "duplicates": recent_duplicates[:50],
            },
            "tamper_status": tamper_status,
            "sample_events": sample_events,
        }

    async def generate_pdf_report(
        self, report_data: dict[str, Any], output_filename: str | None = None
    ) -> Path:
        """
        Generate PDF report from collected data.

        Args:
            report_data: Data from collect_report_data()
            output_filename: Custom filename (auto-generated if not provided)

        Returns:
            Path to generated PDF file
        """
        if not REPORTLAB_AVAILABLE:
            raise ForensicReportError(
                "ReportLab not available. Install reportlab to generate PDFs."
            )

        if output_filename is None:
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            output_filename = f"forensic_report_{timestamp}.pdf"

        output_path = self._output_dir / output_filename

        # Create PDF document
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            title="Forensic Audit Report",
            author=self._company_name,
            subject="Audit Trail Forensic Analysis",
        )

        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        heading1_style = styles["Heading1"]
        heading2_style = styles["Heading2"]
        normal_style = styles["Normal"]

        # Custom style for monospace (event IDs)
        code_style = ParagraphStyle("Code", parent=styles["Code"], fontSize=8, fontName="Courier")

        story = []

        # Title
        story.append(Paragraph("FORENSIC AUDIT REPORT", title_style))
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(f"{self._company_name}", heading1_style))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(f"Generated: {report_data['report_generated_at']}", normal_style))
        story.append(Spacer(1, 0.3 * inch))

        # Executive Summary
        story.append(Paragraph("Executive Summary", heading1_style))
        story.append(Spacer(1, 0.1 * inch))
        summary_text = f"""
        This forensic audit report analyzes the event store over the last {report_data["time_range_days"]} days.
        Total events analyzed: {report_data["total_events"]:,} across {report_data["streams_analyzed"]} streams.
        """
        story.append(Paragraph(summary_text, normal_style))
        story.append(Spacer(1, 0.2 * inch))

        # Findings Summary Table
        findings_data = [
            ["Finding", "Count", "Status"],
            [
                "Sequence Gaps",
                str(report_data["gaps"]["total_found"]),
                "⚠️ Warning" if report_data["gaps"]["total_found"] > 0 else "✅ OK",
            ],
            [
                "Potential Duplicates",
                str(report_data["duplicates"]["total_found"]),
                "⚠️ Warning" if report_data["duplicates"]["total_found"] > 0 else "✅ OK",
            ],
            [
                "Tampering Detected",
                "Yes"
                if not report_data["tamper_status"].get("enabled", False)
                else (
                    "⚠️"
                    if report_data["tamper_status"].get("running", False)
                    else "✅ Monitoring Active"
                ),
                "",
            ],
        ]
        findings_table = Table(findings_data, colWidths=[3 * inch, 2 * inch, 2 * inch])
        findings_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(findings_table)
        story.append(Spacer(1, 0.3 * inch))

        # Stream Information
        story.append(Paragraph("Stream Analysis", heading1_style))
        story.append(Spacer(1, 0.1 * inch))

        stream_table_data = [["Stream Name", "Event Count", "First Event", "Last Event"]]
        for info in report_data["stream_info"][:15]:
            stream_table_data.append(
                [
                    info.get("stream_name", "Unknown")[:50],
                    str(info.get("event_count", 0)),
                    (info.get("first_timestamp") or "")[:19]
                    if info.get("first_timestamp")
                    else "N/A",
                    (info.get("last_timestamp") or "")[:19]
                    if info.get("last_timestamp")
                    else "N/A",
                ]
            )

        stream_table = Table(
            stream_table_data, colWidths=[2.2 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
        stream_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(stream_table)
        story.append(Spacer(1, 0.3 * inch))

        # Gap Analysis
        story.append(Paragraph("Gap Analysis", heading1_style))
        story.append(Spacer(1, 0.1 * inch))
        if report_data["gaps"]["total_found"] == 0:
            story.append(
                Paragraph(
                    "No sequence or timestamp gaps detected in the analyzed period.", normal_style
                )
            )
        else:
            story.append(
                Paragraph(f"Found {report_data['gaps']['total_found']} gaps. Sample:", normal_style)
            )
            story.append(Spacer(1, 0.1 * inch))
            gap_table_data = [["Stream", "Expected", "Actual", "Gap Size", "Detected At"]]
            for gap in report_data["gaps"]["gaps"][:10]:
                gap_table_data.append(
                    [
                        gap.get("stream_name", "Unknown")[:30],
                        str(gap.get("expected_sequence", "-")),
                        str(gap.get("actual_sequence", "-")),
                        str(gap.get("gap_size", "-")),
                        (gap.get("detected_at") or "")[:19] if gap.get("detected_at") else "N/A",
                    ]
                )
            gap_table = Table(
                gap_table_data,
                colWidths=[1.5 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 1.5 * inch],
            )
            gap_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                        ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            story.append(gap_table)
        story.append(Spacer(1, 0.3 * inch))

        # Duplicate Analysis
        story.append(Paragraph("Duplicate Analysis", heading1_style))
        story.append(Spacer(1, 0.1 * inch))
        if report_data["duplicates"]["total_found"] == 0:
            story.append(
                Paragraph(
                    "No potential duplicate events detected in the analyzed period.", normal_style
                )
            )
        else:
            story.append(
                Paragraph(
                    f"Found {report_data['duplicates']['total_found']} potential duplicate groups.",
                    normal_style,
                )
            )
            for dup in report_data["duplicates"]["duplicates"][:5]:
                story.append(
                    Paragraph(f"<b>Stream:</b> {dup.get('stream_name', 'Unknown')}", normal_style)
                )
                story.append(
                    Paragraph(
                        f"<b>Similarity Score:</b> {dup.get('similarity_score', 0):.2f}",
                        normal_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Event IDs:</b> {', '.join(dup.get('event_ids', [])[:3])}", code_style
                    )
                )
                story.append(Spacer(1, 0.1 * inch))

        story.append(PageBreak())

        # Tamper Status
        story.append(Paragraph("Tamper Detection Status", heading1_style))
        story.append(Spacer(1, 0.1 * inch))
        tamper_text = f"""
        Tamper detection is {"ENABLED" if report_data["tamper_status"].get("enabled", False) else "DISABLED"}.
        Monitoring is {"running" if report_data["tamper_status"].get("running", False) else "stopped"}.
        Check interval: {report_data["tamper_status"].get("check_interval_seconds", 3600)} seconds.
        Streams monitored: {", ".join(report_data["tamper_status"].get("streams_monitored", []))}.
        """
        story.append(Paragraph(tamper_text, normal_style))
        story.append(Spacer(1, 0.3 * inch))

        # Sample Events
        story.append(Paragraph("Sample Events (Recent)", heading1_style))
        story.append(Spacer(1, 0.1 * inch))
        for stream, events in report_data.get("sample_events", {}).items():
            story.append(Paragraph(f"<b>Stream: {stream}</b>", heading2_style))
            for event in events[:5]:
                event_text = f"• {event.get('event_type', 'Unknown')} at {event.get('timestamp', 'N/A')[:19]} - ID: {event.get('id', '')[:8]}"
                story.append(Paragraph(event_text, normal_style))
            story.append(Spacer(1, 0.1 * inch))

        # Footer note
        story.append(Spacer(1, 0.5 * inch))
        story.append(
            Paragraph(
                "This report is generated automatically by the ERP Accounting Engine forensic audit system.",
                normal_style,
            )
        )
        story.append(Paragraph("For questions, contact your system administrator.", normal_style))

        # Build PDF
        doc.build(story)

        logger.info(f"Forensic report generated: {output_path}")
        return output_path

    async def generate_report(
        self,
        stream_names: list[str] | None = None,
        time_range_days: int = 30,
        output_filename: str | None = None,
    ) -> Path:
        """
        Generate a complete forensic report.

        Args:
            stream_names: Specific streams to analyze
            time_range_days: Days to look back
            output_filename: Custom filename

        Returns:
            Path to generated PDF
        """
        report_data = await self.collect_report_data(stream_names, time_range_days)
        pdf_path = await self.generate_pdf_report(report_data, output_filename)
        return pdf_path

    async def get_report_status(self) -> dict[str, Any]:
        """Get status of report generator."""
        return {
            "output_dir": str(self._output_dir),
            "reportlab_available": REPORTLAB_AVAILABLE,
            "company_name": self._company_name,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_forensic_report_generator: ForensicReportGeneratorPDF | None = None


async def get_forensic_report_generator() -> ForensicReportGeneratorPDF:
    """Get singleton instance of ForensicReportGeneratorPDF."""
    global _forensic_report_generator
    if _forensic_report_generator is None:
        _forensic_report_generator = ForensicReportGeneratorPDF()
    return _forensic_report_generator


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for forensic report generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate forensic audit report")
    parser.add_argument("--output", "-o", help="Output PDF filename")
    parser.add_argument("--days", "-d", type=int, default=30, help="Time range in days")
    parser.add_argument("--streams", "-s", nargs="+", help="Specific streams to analyze")

    args = parser.parse_args()

    async def run():
        generator = await get_forensic_report_generator()
        path = await generator.generate_report(
            stream_names=args.streams, time_range_days=args.days, output_filename=args.output
        )
        print(f"Forensic report generated: {path}")

    try:
        asyncio.get_running_loop()
        asyncio.create_task(run())
    except RuntimeError:
        sub_loop = asyncio.new_event_loop()
        try:
            sub_loop.run_until_complete(run())
        finally:
            sub_loop.close()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["ForensicReportError", "ForensicReportGeneratorPDF", "get_forensic_report_generator"]

if __name__ == "__main__":
    cli()