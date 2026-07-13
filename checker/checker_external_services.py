#!/usr/bin/env python3
"""
checker_external_services.py - Real External Services Connectivity Checker
===========================================================================
Versi: 2.0.0
Fitur: JSON output, scoring berdasarkan persentase online, RCA-ready,
       exit code 0 jika ada layanan offline (hanya peringatan).
"""

import argparse
import asyncio
import json
import sys
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ServiceStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    NOT_CONFIGURED = "not_configured"

@dataclass(frozen=True)
class ServiceConfig:
    name: str
    host: str
    port: int
    check_type: str = "tcp"
    http_path: str = "/"
    timeout: float = 3.0

SERVICES_TO_CHECK = [
    ServiceConfig(name="PostgreSQL", host="localhost", port=5432, check_type="tcp"),
    ServiceConfig(name="Redis", host="localhost", port=6379, check_type="tcp"),
    ServiceConfig(name="Kafka", host="localhost", port=9092, check_type="tcp"),
    ServiceConfig(name="MinIO (API)", host="localhost", port=9000, check_type="tcp"),
    ServiceConfig(name="OpenTelemetry (gRPC)", host="localhost", port=4317, check_type="tcp"),
    ServiceConfig(name="OpenTelemetry (HTTP)", host="localhost", port=4318, check_type="tcp"),
    ServiceConfig(name="SMTP Server (MailHog)", host="localhost", port=1025, check_type="tcp"),
    ServiceConfig(name="HashiCorp Vault", host="localhost", port=8200, check_type="http", http_path="/v1/sys/health"),
]

async def check_tcp(host: str, port: int, timeout: float) -> tuple[ServiceStatus, Exception | None]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return ServiceStatus.ONLINE, None
    except Exception as e:
        return ServiceStatus.OFFLINE, e

async def check_http(host: str, port: int, path: str, timeout: float) -> tuple[ServiceStatus, Exception | None]:
    url = f"http://{host}:{port}{path}"
    def _sync_http_req():
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status
    try:
        status_code = await asyncio.to_thread(_sync_http_req)
        if 200 <= status_code < 400:
            return ServiceStatus.ONLINE, None
        else:
            raise ValueError(f"HTTP Return Code: {status_code}")
    except Exception as e:
        return ServiceStatus.OFFLINE, e

async def probe_service(service: ServiceConfig) -> tuple[ServiceConfig, ServiceStatus, Exception | None]:
    if service.host in ("NOT_CONFIGURED", "", None):
        return service, ServiceStatus.NOT_CONFIGURED, None
    if service.check_type == "tcp":
        status, err = await check_tcp(service.host, service.port, service.timeout)
    elif service.check_type == "http":
        status, err = await check_http(service.host, service.port, service.http_path, service.timeout)
    else:
        status, err = ServiceStatus.OFFLINE, ValueError(f"Unknown check_type: {service.check_type}")
    return service, status, err

async def run_checks(verbose: bool = False) -> dict[str, Any]:
    tasks = [probe_service(svc) for svc in SERVICES_TO_CHECK]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    online = 0
    total = len(results)
    details = []
    offline_errors = []

    for service, status, error in results:
        details.append({
            "name": service.name,
            "host": service.host,
            "port": service.port,
            "status": status.value,
            "error": str(error) if error else None,
            "traceback": traceback.format_exc() if error else None
        })
        if status == ServiceStatus.ONLINE:
            online += 1
        elif status == ServiceStatus.OFFLINE:
            offline_errors.append((service, error))

    score = (online / total) * 100 if total > 0 else 0

    return {
        "score": round(score, 2),
        "online": online,
        "total": total,
        "details": details,
        "offline_count": len(offline_errors),
        "offline_services": [
            {"name": s.name, "host": s.host, "port": s.port, "error": str(e) if e else None}
            for s, e in offline_errors
        ],
        "offline_tracebacks": [
            {"name": s.name, "traceback": traceback.format_exception(type(e), e, e.__traceback__) if e else None}
            for s, e in offline_errors
        ]
    }

def print_dashboard(data: dict[str, Any], verbose: bool = False):
    print("\n\033[1m=== External Services Health Dashboard ===\033[0m\n")
    print(f"{'Status':<10} | {'Service Name':<25} | {'Target':<25}")
    print("-" * 65)

    for item in data["details"]:
        status = item["status"]
        if status == "online":
            display = "\033[92m✓\033[0m"
        elif status == "offline":
            display = "\033[91m✗\033[0m"
        else:
            display = "\033[93m⚠\033[0m"
        target = f"{item['host']}:{item['port']}"
        print(f"  {display:<16} | {item['name']:<25} | {target:<25}")

    print(f"\n\033[1mScore: {data['score']:.1f}% ({data['online']}/{data['total']} online)\033[0m")

    if data["offline_count"] > 0 and verbose:
        print("\n\033[93m\033[1m=== Offline Services Details ===\033[0m")
        for idx, svc in enumerate(data["offline_services"]):
            print(f"\n  [{idx+1}] {svc['name']} ({svc['host']}:{svc['port']})")
            if svc['error']:
                print(f"      Error: {svc['error']}")
            # Optionally show traceback if verbose and available
            if verbose and data["offline_tracebacks"] and idx < len(data["offline_tracebacks"]):
                tb_data = data["offline_tracebacks"][idx]
                if tb_data.get("traceback"):
                    print("      Traceback (most recent call last):")
                    for line in tb_data["traceback"]:
                        print(f"        {line.rstrip()}")

def main():
    parser = argparse.ArgumentParser(description="External Services Health Checker")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details")
    args = parser.parse_args()

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        data = asyncio.run(run_checks(verbose=args.verbose))
    except KeyboardInterrupt:
        print("\n[!] Health check aborted.")
        sys.exit(130)

    print_dashboard(data, verbose=args.verbose)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            # Hapus tracebacks dari JSON agar tidak terlalu besar (kecuali verbose)
            export_data = data.copy()
            if not args.verbose:
                export_data.pop("offline_tracebacks", None)
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        print(f"\nJSON report saved to {args.json}")

    # Exit code: 0 selalu (tidak gagal karena offline services, hanya peringatan)
    # Ini penting agar master_checker tetap bisa mendapatkan skor granular.
    sys.exit(0)

if __name__ == "__main__":
    main()
