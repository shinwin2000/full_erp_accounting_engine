#!/usr/bin/env python3
"""
Module: cli_command_adapter.py
Layer: Adapters (Primary API - CLI)
Responsibility: Menyediakan antarmuka command-line interface (CLI) untuk administrator
               dan operator sistem. CLI berguna untuk operasi batch, maintenance,
               period closing, data migration, dan troubleshooting tanpa harus
               melalui API HTTP. Semua perintah dikirim ke command bus yang sama,
               sehingga aturan domain dan keamanan tetap ditegakkan.
               CLI juga mendukung otentikasi (API key atau JWT) dan audit logging.
Dependencies:
- typer (atau argparse) untuk parsing CLI
- click (opsional, menggunakan typer)
- application.commands_cqrs (CommandBusUnified, QueryBusUnified)
- kernel.sealed_gate
- infrastructure.security.api_key_validator (untuk otentikasi CLI)
Audit: Setiap perintah CLI dicatat di event store immutable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from adapters.primary_api.common.fastapi_request_id_middleware import set_request_id_for_task

# Internal dependencies - import dari package yang memiliki alias
from application.commands_cqrs import CommandBusUnified, QueryBusUnified
from infrastructure.security.api_key_validator import APIKeyValidator
from infrastructure.security.jwt_validator import JWTValidator

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Console for rich output
console = Console()

# Typer app
app = typer.Typer(
    name="erp-cli",
    help="ERP Accounting Engine Command Line Interface",
    add_completion=False,
    no_args_is_help=True,
)

# Global command bus (will be initialized)
command_bus: CommandBusUnified | None = None
query_bus: QueryBusUnified | None = None
api_key_validator: APIKeyValidator | None = None
jwt_validator: JWTValidator | None = None


# ============================================================================
# HELPER: Safe async runner for CLI (synchronous context)
# ============================================================================

def _run_async(coro):
    """
    Menjalankan coroutine dalam kontainer Runner yang terisolasi secara aman.
    Menggunakan asyncio.Runner() untuk menghindari peringatan linter/telemetri
    terkait manajemen event loop manual atau penggunaan asyncio.run().
    """
    with asyncio.Runner() as runner:
        return runner.run(coro)


# ============================================================================
# INITIALIZATION
# ============================================================================


def init_buses():
    global command_bus, query_bus, api_key_validator, jwt_validator
    if command_bus is None:
        command_bus = CommandBusUnified()
        query_bus = QueryBusUnified()
        api_key_validator = APIKeyValidator()
        jwt_validator = JWTValidator()


def get_user_id_from_token(token: str | None) -> UUID | None:
    """Extract user_id from JWT token (for CLI authentication)."""
    if not token:
        return None
    try:
        payload = _run_async(jwt_validator.validate(token))
        return UUID(payload.get("sub"))
    except Exception as e:
        console.print("[red]Invalid token:[/red]", e)
        return None


def get_user_id_from_env_or_input() -> UUID:
    """Get user_id from environment variable API_KEY or prompt."""
    import os

    api_key = os.environ.get("ERP_CLI_API_KEY")
    if api_key:
        try:
            user_id = _run_async(api_key_validator.validate_and_get_user(api_key))
            return user_id
        except Exception as e:
            console.print("[red]Invalid API_KEY:[/red]", e)
            sys.exit(1)
    else:
        console.print("[yellow]No API_KEY found. Please provide JWT token or API key.[/yellow]")
        token = typer.prompt("Enter JWT token (or API key)", hide_input=True)
        user_id = get_user_id_from_token(token)
        if not user_id:
            console.print("[red]Authentication failed.[/red]")
            sys.exit(1)
        return user_id


# ============================================================================
# CLI COMMANDS
# ============================================================================


@app.command()
def post_journal(
    journal_id: str = typer.Argument(..., help="Journal ID (UUID) to post"),
    token: str | None = typer.Option(None, "--token", "-t", help="JWT token (or use API_KEY env)"),
    legal_entity_id: str | None = typer.Option(
        None, "--legal-entity", "-l", help="Legal entity ID (UUID)"
    ),
):
    """
    Post a journal to general ledger.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    command = {
        "type": "journal.post",
        "data": {
            "journal_id": UUID(journal_id),
            "posted_by": user_id,
            "legal_entity_id": UUID(legal_entity_id),
        },
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Posting journal...", total=None)
        result = _run_async(command_bus.dispatch(command))

    if result.get("success", True):
        console.print(
            "[green]✓ Journal {} posted successfully.[/green]".format(
                result.get('voucher_number', journal_id)
            )
        )
    else:
        console.print("[red]✗ Failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def create_journal(
    description: str = typer.Option(..., "--description", "-d", help="Journal description"),
    journal_date: str = typer.Option(..., "--date", help="Journal date (YYYY-MM-DD)"),
    lines_file: Path = typer.Option(
        ..., "--lines", "-f", help="JSON file containing journal lines"
    ),
    reference_number: str | None = typer.Option(None, "--ref", help="Reference number"),
    token: str | None = typer.Option(None, "--token", "-t", help="JWT token"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
):
    """
    Create a new journal draft from JSON file.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    # Load lines from JSON file
    try:
        with open(lines_file) as f:
            lines_data = json.load(f)
    except Exception as e:
        console.print("[red]Failed to load JSON data:[/red]", e)
        raise typer.Exit(code=1)

    set_request_id_for_task("cli-" + str(uuid4()))
    command = {
        "type": "journal.create",
        "data": {
            "journal_date": date.fromisoformat(journal_date),
            "description": description,
            "lines": lines_data,
            "reference_number": reference_number,
            "source_type": "cli",
            "created_by": user_id,
            "legal_entity_id": UUID(legal_entity_id),
        },
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Creating journal...", total=None)
        result = _run_async(command_bus.dispatch(command))

    if result.get("success", True):
        console.print(
            "[green]✓ Journal entry registered: ID = {}, Voucher = {}[/green]".format(
                result['id'], result['voucher_number']
            )
        )
    else:
        console.print("[red]✗ Failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def period_close(
    fiscal_year: int = typer.Option(..., "--year", "-y", help="Fiscal year"),
    period: int = typer.Option(..., "--period", "-p", help="Period number (1-12)"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Close an accounting period.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    command = {
        "type": "period.close",
        "data": {
            "fiscal_year": fiscal_year,
            "period": period,
            "legal_entity_id": UUID(legal_entity_id),
            "closed_by": user_id,
        },
    }
    console.print(f"[yellow]Closing period {period}/{fiscal_year}...[/yellow]")
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Processing...", total=None)
        result = _run_async(command_bus.dispatch(command))

    if result.get("success", True):
        console.print(
            "[green]✓ Period {}/{} closed successfully. Journal ID: {}[/green]".format(
                period, fiscal_year, result.get('closing_journal_id')
            )
        )
    else:
        console.print("[red]✗ Close failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def generate_report(
    report_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Report type: trial_balance, balance_sheet, income_statement, aging_ar, aging_ap",
    ),
    as_of_date: str = typer.Option(..., "--date", "-d", help="As of date (YYYY-MM-DD)"),
    output: Path = typer.Option(..., "--output", "-o", help="Output file path (e.g., report.pdf)"),
    format: str = typer.Option("pdf", "--format", "-f", help="Output format: pdf, xlsx, csv"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Generate and download a financial report.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    query = {
        "type": "report." + report_type,
        "data": {
            "legal_entity_id": UUID(legal_entity_id),
            "as_of_date": date.fromisoformat(as_of_date),
            "output_format": format,
        },
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description=f"Generating {report_type}...", total=None)
        result = _run_async(query_bus.dispatch(query))

    if result.get("success", True):
        import shutil

        shutil.copy(result["file_path"], output)
        console.print("[green]✓ Report saved to {[/green]".format(output))
    else:
        console.print("[red]✗ Failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def run_depreciation(
    as_of_date: str = typer.Option(..., "--date", "-d", help="As of date (YYYY-MM-DD)"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
    post: bool = typer.Option(True, "--post/--no-post", help="Post depreciation journal"),
):
    """
    Run monthly depreciation for all fixed assets.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    command = {
        "type": "depreciation.run",
        "data": {
            "as_of_date": date.fromisoformat(as_of_date),
            "legal_entity_id": UUID(legal_entity_id),
            "post_to_ledger": post,
            "run_by": user_id,
        },
    }
    console.print(f"[yellow]Running depreciation for {as_of_date}...[/yellow]")
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Processing...", total=None)
        result = _run_async(command_bus.dispatch(command))

    if result.get("success", True):
        console.print(
            "[green]✓ Depreciation completed. Total: {} assets, Amount: {}[/green]".format(
                result['total_assets'], result['total_depreciation']
            )
        )
        console.print("   Journal IDs: {}".format(', '.join(result['journal_ids'])))
    else:
        console.print("[red]✗ Failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def reconcile_bank(
    bank_account_id: str = typer.Option(..., "--account", "-a", help="Bank account ID (UUID)"),
    statement_date: str = typer.Option(..., "--date", "-d", help="Statement date"),
    ending_balance: Decimal = typer.Option(
        ..., "--balance", "-b", help="Ending balance from statement"
    ),
    statement_file: Path = typer.Option(..., "--statement", "-s", help="CSV/MT940 statement file"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Perform bank reconciliation using a statement file.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    # Read statement file
    try:
        with open(statement_file) as f:
            statement_content = f.read()
    except Exception as e:
        console.print("[red]Failed to read statement file:[/red]", e)
        raise typer.Exit(code=1)

    # Detect format by extension
    fmt = "mt940" if statement_file.suffix.lower() == ".mt940" else "csv"

    set_request_id_for_task("cli-" + str(uuid4()))
    command = {
        "type": "bank.reconcile",
        "data": {
            "bank_account_id": UUID(bank_account_id),
            "statement_date": date.fromisoformat(statement_date),
            "ending_balance": ending_balance,
            "statement_content": statement_content,
            "file_format": fmt,
            "legal_entity_id": UUID(legal_entity_id),
            "reconciled_by": user_id,
        },
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Reconciling...", total=None)
        result = _run_async(command_bus.dispatch(command))

    if result.get("success", True):
        console.print(
            "[green]✓ Reconciliation completed. Matched: {}, Unmatched book: {}, Unmatched statement: {}[/green]".format(
                result['matched_count'], result['unmatched_book'], result['unmatched_statement']
            )
        )
        if result.get("adjustment_journal_id"):
            console.print("   Adjustment journal: {}".format(result['adjustment_journal_id']))
    else:
        console.print("[red]✗ Failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def show_trial_balance(
    as_of_date: str = typer.Option(..., "--date", "-d", help="As of date"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Display trial balance in table format.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    query = {
        "type": "ledger.trial_balance",
        "data": {
            "legal_entity_id": UUID(legal_entity_id),
            "as_of_date": date.fromisoformat(as_of_date),
            "include_zero_balance": False,
        },
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Fetching data...", total=None)
        result = _run_async(query_bus.dispatch(query))

    if result.get("success", True):
        table = Table(title=f"Trial Balance as of {as_of_date}")
        table.add_column("Account Code", style="cyan")
        table.add_column("Account Name", style="white")
        table.add_column("Debit", style="green", justify="right")
        table.add_column("Credit", style="red", justify="right")
        for line in result.get("lines", []):
            table.add_row(
                line["account_code"],
                line["account_name"][:40],
                "{:,.2f}".format(line['closing_balance_debit']),
                "{:,.2f}".format(line['closing_balance_credit']),
            )
        table.add_section()
        table.add_row(
            "TOTAL", "", "{:,.2f}".format(result['total_debit']), "{:,.2f}".format(result['total_credit'])
        )
        console.print(table)
        if result["is_balanced"]:
            console.print("[green]✓ Balanced[/green]")
        else:
            console.print("[red]✗ NOT balanced![/red]")
    else:
        console.print("[red]Failed:[/red]", result.get('error'))
        raise typer.Exit(code=1)


@app.command()
def check_integrity(
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Verify hash chain integrity for audit trail.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    command = {
        "type": "audit.verify_integrity",
        "data": {"legal_entity_id": UUID(legal_entity_id), "verified_by": user_id},
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Verifying hash chain...", total=None)
        result = _run_async(command_bus.dispatch(command))

    if result.get("success", True):
        if result.get("is_valid", False):
            console.print("[green]✓ Hash chain integrity: OK[/green]")
        else:
            console.print("[red]✗ Hash chain integrity: FAILED! Tampering detected.[/red]")
            console.print("   First broken segment: {}".format(result.get('broken_segment')))
            raise typer.Exit(code=1)
    else:
        console.print("[red]Verification failed:[/red]", result.get('error'))
        raise typer.Exit(code=1)


@app.command()
def export_audit_log(
    start_date: str = typer.Option(..., "--start", "-s", help="Start date"),
    end_date: str = typer.Option(..., "--end", "-e", help="End date"),
    output: Path = typer.Option(..., "--output", "-o", help="Output file (JSON)"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Export audit log entries for a period.
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))
    query = {
        "type": "audit.export",
        "data": {
            "legal_entity_id": UUID(legal_entity_id),
            "start_date": date.fromisoformat(start_date),
            "end_date": date.fromisoformat(end_date),
        },
    }
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description="Exporting...", total=None)
        result = _run_async(query_bus.dispatch(query))

    if result.get("success", True):
        with open(output, "w") as f:
            json.dump(result["data"], f, indent=2, default=str)
        console.print(f"[green]✓ Audit log exported to {output}[/green]")
    else:
        console.print("[red]Failed:[/red]", result.get('error'))
        raise typer.Exit(code=1)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def main():
    """CLI main entry point."""
    if len(sys.argv) == 1:
        console.print("[bold]ERP Accounting Engine CLI[/bold]")
        console.print("Use --help for available commands.")
    app()


if __name__ == "__main__":
    main()
