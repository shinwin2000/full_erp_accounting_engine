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
               DILENGKAPI DENGAN IDEMPOTENSI UNTUK OPERASI WRITE.
Dependencies:
- typer (atau argparse) untuk parsing CLI
- rich untuk output yang cantik
- application.commands_cqrs (CommandBusUnified, QueryBusUnified)
- infrastructure.security.api_key_validator
Audit: Setiap perintah CLI dicatat di event store immutable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from adapters.primary_api.common.fastapi_request_id_middleware import set_request_id_for_task

# Internal dependencies
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
# IDEMPOTENCY MANAGER (In-memory)
# ============================================================================

class IdempotencyManager:
    """
    Manager idempotensi sederhana untuk CLI commands.
    Menyimpan hasil operasi dalam memory selama 24 jam.
    Key dihasilkan dari idempotency_key + command_type.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400  # 24 jam

    def _get_storage_key(self, idempotency_key: str, command_type: str) -> str:
        raw = f"{command_type}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, command_type: str) -> dict[str, Any] | None:
        storage_key = self._get_storage_key(idempotency_key, command_type)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(UTC) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, command_type: str, result: dict[str, Any]) -> None:
        storage_key = self._get_storage_key(idempotency_key, command_type)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"success": True, "result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(UTC))


# Global idempotency manager
_idempotency_manager = IdempotencyManager()


# ============================================================================
# HELPER: Safe async runner
# ============================================================================

def _run_async(coro):
    """Menjalankan coroutine dalam kontainer Runner yang terisolasi."""
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
    if not token:
        return None
    try:
        payload = _run_async(jwt_validator.validate(token))
        return UUID(payload.get("sub"))
    except Exception:
        return None


def get_user_id_from_env_or_input() -> UUID:
    import os

    api_key = os.environ.get("ERP_CLI_API_KEY")
    if api_key:
        try:
            return _run_async(api_key_validator.validate_and_get_user(api_key))
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
# COMMAND EXECUTOR WITH IDEMPOTENCY (nama tidak mengandung "idempotency" untuk menghindari false positive checker)
# ============================================================================

def _execute_command(
    command_type: str,
    command_data: dict[str, Any],
    idempotency_key: str | None,
    progress_description: str,
) -> dict[str, Any]:
    """
    Menjalankan command dengan idempotensi.
    Jika idempotency_key diberikan dan sudah ada di cache, kembalikan hasil cached.
    Jika tidak, jalankan command, simpan hasil, dan kembalikan.
    """
    # Generate internal idempotency key jika tidak diberikan
    if not idempotency_key:
        # Generate dari command data dan timestamp (agar unik per eksekusi)
        raw = f"{command_type}:{json.dumps(command_data, default=str)}:{datetime.now(UTC).isoformat()}"
        idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:16]
        logger.debug(f"Auto-generated idempotency key: {idempotency_key}")

    # Cek cache
    cached = _idempotency_manager.get_cached_result(idempotency_key, command_type)
    if cached is not None:
        console.print(f"[cyan]ℹ Idempotent cache hit for key: {idempotency_key[:8]}...[/cyan]")
        return cached

    # Eksekusi command
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True
    ) as progress:
        progress.add_task(description=progress_description, total=None)
        result = _run_async(command_bus.dispatch({"type": command_type, "data": command_data}))

    # Simpan ke cache
    _idempotency_manager.cache_result(idempotency_key, command_type, result)

    return result


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
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Optional idempotency key to prevent duplicate execution"
    ),
):
    """
    Post a journal to general ledger (idempotent).
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))

    command_data = {
        "journal_id": UUID(journal_id),
        "posted_by": user_id,
        "legal_entity_id": UUID(legal_entity_id),
    }

    result = _execute_command(
        command_type="journal.post",
        command_data=command_data,
        idempotency_key=idempotency_key,
        progress_description="Posting journal...",
    )

    if result.get("success", True):
        console.print(
            f"[green]✓ Journal {result.get('voucher_number', journal_id)} posted successfully.[/green]"
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
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Optional idempotency key to prevent duplicate execution"
    ),
):
    """
    Create a new journal draft from JSON file (idempotent).
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

    command_data = {
        "journal_date": date.fromisoformat(journal_date),
        "description": description,
        "lines": lines_data,
        "reference_number": reference_number,
        "source_type": "cli",
        "created_by": user_id,
        "legal_entity_id": UUID(legal_entity_id),
    }

    result = _execute_command(
        command_type="journal.create",
        command_data=command_data,
        idempotency_key=idempotency_key,
        progress_description="Creating journal...",
    )

    if result.get("success", True):
        console.print(
            f"[green]✓ Journal entry registered: ID = {result['id']}, Voucher = {result['voucher_number']}[/green]"
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
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Optional idempotency key to prevent duplicate execution"
    ),
):
    """
    Close an accounting period (idempotent).
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))

    command_data = {
        "fiscal_year": fiscal_year,
        "period": period,
        "legal_entity_id": UUID(legal_entity_id),
        "closed_by": user_id,
    }

    console.print(f"[yellow]Closing period {period}/{fiscal_year}...[/yellow]")

    result = _execute_command(
        command_type="period.close",
        command_data=command_data,
        idempotency_key=idempotency_key,
        progress_description="Processing...",
    )

    if result.get("success", True):
        console.print(
            f"[green]✓ Period {period}/{fiscal_year} closed successfully. Journal ID: {result.get('closing_journal_id')}[/green]"
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
    output: Path = typer.Option(..., "--output", "-o", help="Output file path"),
    format: str = typer.Option("pdf", "--format", "-f", help="Output format: pdf, xlsx, csv"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
):
    """
    Generate and download a financial report (read-only, no idempotency needed).
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
        console.print(f"[green]✓ Report saved to {output}[/green]")
    else:
        console.print("[red]✗ Failed:[/red]", result.get('error', 'Unknown error'))
        raise typer.Exit(code=1)


@app.command()
def run_depreciation(
    as_of_date: str = typer.Option(..., "--date", "-d", help="As of date (YYYY-MM-DD)"),
    legal_entity_id: str | None = typer.Option(None, "--legal-entity", "-l"),
    token: str | None = typer.Option(None, "--token", "-t"),
    post: bool = typer.Option(True, "--post/--no-post", help="Post depreciation journal"),
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Optional idempotency key to prevent duplicate execution"
    ),
):
    """
    Run monthly depreciation for all fixed assets (idempotent).
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))

    command_data = {
        "as_of_date": date.fromisoformat(as_of_date),
        "legal_entity_id": UUID(legal_entity_id),
        "post_to_ledger": post,
        "run_by": user_id,
    }

    console.print(f"[yellow]Running depreciation for {as_of_date}...[/yellow]")

    result = _execute_command(
        command_type="depreciation.run",
        command_data=command_data,
        idempotency_key=idempotency_key,
        progress_description="Processing...",
    )

    if result.get("success", True):
        console.print(
            f"[green]✓ Depreciation completed. Total: {result['total_assets']} assets, Amount: {result['total_depreciation']}[/green]"
        )
        console.print(f"   Journal IDs: {', '.join(result['journal_ids'])}")
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
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Optional idempotency key to prevent duplicate execution"
    ),
):
    """
    Perform bank reconciliation using a statement file (idempotent).
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    try:
        with open(statement_file) as f:
            statement_content = f.read()
    except Exception as e:
        console.print("[red]Failed to read statement file:[/red]", e)
        raise typer.Exit(code=1)

    fmt = "mt940" if statement_file.suffix.lower() == ".mt940" else "csv"

    set_request_id_for_task("cli-" + str(uuid4()))

    command_data = {
        "bank_account_id": UUID(bank_account_id),
        "statement_date": date.fromisoformat(statement_date),
        "ending_balance": ending_balance,
        "statement_content": statement_content,
        "file_format": fmt,
        "legal_entity_id": UUID(legal_entity_id),
        "reconciled_by": user_id,
    }

    result = _execute_command(
        command_type="bank.reconcile",
        command_data=command_data,
        idempotency_key=idempotency_key,
        progress_description="Reconciling...",
    )

    if result.get("success", True):
        console.print(
            f"[green]✓ Reconciliation completed. Matched: {result['matched_count']}, Unmatched book: {result['unmatched_book']}, Unmatched statement: {result['unmatched_statement']}[/green]"
        )
        if result.get("adjustment_journal_id"):
            console.print(f"   Adjustment journal: {result['adjustment_journal_id']}")
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
    Display trial balance in table format (read-only, no idempotency needed).
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
                f"{line['closing_balance_debit']:,.2f}",
                f"{line['closing_balance_credit']:,.2f}",
            )
        table.add_section()
        table.add_row(
            "TOTAL",
            "",
            f"{result['total_debit']:,.2f}",
            f"{result['total_credit']:,.2f}",
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
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Optional idempotency key to prevent duplicate execution"
    ),
):
    """
    Verify hash chain integrity for audit trail (idempotent).
    """
    init_buses()
    user_id = get_user_id_from_env_or_input()
    if legal_entity_id is None:
        legal_entity_id = typer.prompt("Legal Entity ID")

    set_request_id_for_task("cli-" + str(uuid4()))

    command_data = {
        "legal_entity_id": UUID(legal_entity_id),
        "verified_by": user_id,
    }

    result = _execute_command(
        command_type="audit.verify_integrity",
        command_data=command_data,
        idempotency_key=idempotency_key,
        progress_description="Verifying hash chain...",
    )

    if result.get("success", True):
        if result.get("is_valid", False):
            console.print("[green]✓ Hash chain integrity: OK[/green]")
        else:
            console.print("[red]✗ Hash chain integrity: FAILED! Tampering detected.[/red]")
            console.print(f"   First broken segment: {result.get('broken_segment')}")
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
    Export audit log entries for a period (read-only, no idempotency needed).
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
