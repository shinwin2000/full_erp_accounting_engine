"""
E:\\full_erp_accounting_engine\\checker\\checker_external_services.py

Real External Services Connectivity Checker
Strict Mode: All exceptions are captured and their full tracebacks are printed.
"""

import asyncio
import socket
import urllib.request
import urllib.error
import traceback
import sys
from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Optional


class ServiceStatus(Enum):
    ONLINE = "\033[92m✓\033[0m"           # Green check
    OFFLINE = "\033[91m✗\033[0m"          # Red cross
    NOT_CONFIGURED = "\033[93m⚠\033[0m"   # Yellow warning


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    host: str
    port: int
    check_type: str = "tcp"  # 'tcp' or 'http'
    http_path: str = "/"
    timeout: float = 3.0


# Konfigurasi layanan eksternal sesuai dengan arsitektur enterprise Anda
# Konfigurasi layanan eksternal yang disesuaikan dengan real docker-compose.yaml
SERVICES_TO_CHECK = [
    ServiceConfig(name="PostgreSQL", host="localhost", port=5432, check_type="tcp"),
    ServiceConfig(name="Redis", host="localhost", port=6379, check_type="tcp"),
    ServiceConfig(name="Kafka", host="localhost", port=9092, check_type="tcp"),
    ServiceConfig(name="MinIO (API)", host="localhost", port=9000, check_type="tcp"),
    ServiceConfig(name="OpenTelemetry (gRPC)", host="localhost", port=4317, check_type="tcp"),
    ServiceConfig(name="OpenTelemetry (HTTP)", host="localhost", port=4318, check_type="tcp"),
    ServiceConfig(name="SMTP Server (MailHog)", host="localhost", port=1025, check_type="tcp"), # Diubah ke 1025
    ServiceConfig(name="HashiCorp Vault", host="localhost", port=8200, check_type="http", http_path="/v1/sys/health"),
]

async def check_tcp(host: str, port: int, timeout: float) -> Tuple[ServiceStatus, Optional[Exception]]:
    """Melakukan real TCP handshake ke port target."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return ServiceStatus.ONLINE, None
    except Exception as e:
        return ServiceStatus.OFFLINE, e


async def check_http(host: str, port: int, path: str, timeout: float) -> Tuple[ServiceStatus, Optional[Exception]]:
    """Melakukan real HTTP GET request ke endpoint target."""
    url = f"http://{host}:{port}{path}"
    
    def _sync_http_req():
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status

    try:
        status_code = await asyncio.to_thread(_sync_http_req)
        # 200-399 dianggap OK untuk healthcheck
        if 200 <= status_code < 400:
            return ServiceStatus.ONLINE, None
        else:
            raise ValueError(f"HTTP Return Code: {status_code}")
    except Exception as e:
        return ServiceStatus.OFFLINE, e


async def probe_service(service: ServiceConfig) -> Tuple[ServiceConfig, ServiceStatus, Optional[Exception]]:
    """Fungsi delegasi untuk memilih metode probe."""
    if service.host in ("NOT_CONFIGURED", "", None):
        return service, ServiceStatus.NOT_CONFIGURED, None

    if service.check_type == "tcp":
        status, err = await check_tcp(service.host, service.port, service.timeout)
    elif service.check_type == "http":
        status, err = await check_http(service.host, service.port, service.http_path, service.timeout)
    else:
        status, err = ServiceStatus.OFFLINE, ValueError(f"Unknown check_type: {service.check_type}")
        
    return service, status, err


async def main():
    print("\n\033[1m=== External Services Health Dashboard ===\033[0m\n")
    
    # Eksekusi pengecekan secara paralel (Concurrent)
    tasks = [probe_service(svc) for svc in SERVICES_TO_CHECK]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    
    failed_services = []

    # Print Dashboard
    print(f"{'Status':<10} | {'Service Name':<25} | {'Target':<25}")
    print("-" * 65)
    for service, status, error in results:
        target_info = f"{service.host}:{service.port}"
        print(f"  {status.value:<16} | {service.name:<25} | {target_info:<25}")
        
        if status == ServiceStatus.OFFLINE and error:
            failed_services.append((service, error))

    # Print Full Traceback untuk layanan yang gagal (Sesuai Strict Debugging Rule)
    if failed_services:
        print("\n\033[91m\033[1m=== DETAILED ERROR LOGS (STRICT MODE) ===\033[0m")
        for service, error in failed_services:
            print(f"\n\033[93m[!] Error Traceback for {service.name} ({service.host}:{service.port}):\033[0m")
            
            # Mencetak full exception dengan traceback aslinya tanpa ditutupi
            if hasattr(error, '__traceback__'):
                traceback.print_exception(type(error), error, error.__traceback__)
            else:
                print(f"{type(error).__name__}: {error}")
                
        sys.exit(1) # Exit dengan code 1 jika ada indikasi infrastruktur mati
    else:
        print("\n\033[92mAll required external services are ONLINE.\033[0m\n")
        sys.exit(0)

if __name__ == "__main__":
    # Workaround untuk mencegah error pada Windows Event Loop saat exit
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Health check aborted by user.")
        sys.exit(130)