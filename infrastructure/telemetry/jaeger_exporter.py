#!/usr/bin/env python3
"""
Module: jaeger_exporter.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengekspor trace ke Jaeger collector atau agent.
               File ini adalah wrapper konfigurasi untuk Jaeger exporter
               yang menggunakan OpenTelemetry Jaeger exporter.
Dependencies:
- opentelemetry-exporter-jaeger (optional)
- opentelemetry-sdk
- config.loader_yaml
- infrastructure.telemetry.opentelemetry_setup
Audit: Trace diekspor ke Jaeger untuk observability distributed tracing.
"""

from __future__ import annotations

from typing import Any

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_JAEGER_CONFIG = {
    "agent_host_name": "localhost",
    "agent_port": 6831,
    "collector_endpoint": "http://localhost:14268/api/traces",
    "collector_timeout": 10,
    "max_tag_value_length": 256,
}

# ============================================================================
# JAEGER EXPORTER CONFIGURATION
# ============================================================================


class JaegerExporterConfig:
    """
    Konfigurasi untuk Jaeger exporter.

    Fitur:
    - Support agent mode (UDP)
    - Support collector mode (HTTP)
    - Konfigurasi dari YAML
    - Validation config
    """

    def __init__(self, config_path: str = "config_files/telemetry_config.yaml"):
        self.config = self._load_config(config_path)
        self._validate_config()

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            jaeger_config = config.get("jaeger", {})
            result = DEFAULT_JAEGER_CONFIG.copy()
            result.update(jaeger_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load Jaeger config, using defaults: {e}")
            return DEFAULT_JAEGER_CONFIG.copy()

    def _validate_config(self) -> None:
        """Validate Jaeger configuration."""
        agent_host = self.config.get("agent_host_name", "localhost")
        agent_port = self.config.get("agent_port", 6831)

        # Validate port range
        if not (1 <= agent_port <= 65535):
            logger.warning(f"Invalid Jaeger agent port: {agent_port}, using default 6831")
            self.config["agent_port"] = 6831

        # Validate collector endpoint URL format (basic)
        collector_endpoint = self.config.get("collector_endpoint", "")
        if collector_endpoint and not collector_endpoint.startswith(("http://", "https://")):
            logger.warning(f"Invalid collector endpoint: {collector_endpoint}")

    def get_agent_config(self) -> dict[str, Any]:
        """Get configuration for Jaeger agent (UDP mode)."""
        return {
            "agent_host_name": self.config.get("agent_host_name", "localhost"),
            "agent_port": self.config.get("agent_port", 6831),
            "max_tag_value_length": self.config.get("max_tag_value_length", 256),
        }

    def get_collector_config(self) -> dict[str, Any]:
        """Get configuration for Jaeger collector (HTTP mode)."""
        return {
            "collector_endpoint": self.config.get(
                "collector_endpoint", "http://localhost:14268/api/traces"
            ),
            "collector_timeout": self.config.get("collector_timeout", 10),
        }

    def is_agent_mode(self) -> bool:
        """Check if using agent mode."""
        return bool(self.config.get("use_agent", True))

    def get_service_name(self) -> str:
        """Get service name for Jaeger."""
        return self.config.get("service_name", "erp-accounting-engine")

    def get_sampling_ratio(self) -> float:
        """Get sampling ratio."""
        return self.config.get("sampling_ratio", 0.1)

    def is_enabled(self) -> bool:
        """Check if Jaeger exporter is enabled."""
        return self.config.get("enabled", True)


# ============================================================================
# JAEGER EXPORTER FACTORY
# ============================================================================


class JaegerExporterFactory:
    """
    Factory untuk membuat Jaeger exporter.
    """

    def __init__(self, config: JaegerExporterConfig | None = None):
        self.config = config or JaegerExporterConfig()

    def create_exporter(self):
        """
        Create Jaeger exporter using OpenTelemetry.
        """
        if not self.config.is_enabled():
            logger.info("Jaeger exporter disabled")
            return None

        try:
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter

            if self.config.is_agent_mode():
                exporter = JaegerExporter(**self.config.get_agent_config())
                logger.info(
                    f"Jaeger exporter created (agent mode): {self.config.get_agent_config()['agent_host_name']}:{self.config.get_agent_config()['agent_port']}"
                )
            else:
                exporter = JaegerExporter(**self.config.get_collector_config())
                logger.info(
                    f"Jaeger exporter created (collector mode): {self.config.get_collector_config()['collector_endpoint']}"
                )

            return exporter

        except ImportError:
            logger.warning("Jaeger exporter not available. Install opentelemetry-exporter-jaeger")
            return None
        except Exception as e:
            logger.error(f"Failed to create Jaeger exporter: {e}")
            return None


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_jaeger_exporter_factory: JaegerExporterFactory | None = None


def get_jaeger_exporter_factory() -> JaegerExporterFactory:
    """Get singleton instance of JaegerExporterFactory."""
    global _jaeger_exporter_factory
    if _jaeger_exporter_factory is None:
        _jaeger_exporter_factory = JaegerExporterFactory()
    return _jaeger_exporter_factory


def create_jaeger_exporter():
    """Create Jaeger exporter."""
    factory = get_jaeger_exporter_factory()
    return factory.create_exporter()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "JaegerExporterConfig",
    "JaegerExporterFactory",
    "create_jaeger_exporter",
    "get_jaeger_exporter_factory",
]
