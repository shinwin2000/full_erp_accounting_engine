#!/usr/bin/env python3
"""
Module: structured_json_logging.py
Layer: Infrastructure (Telemetry)
Responsibility: Structured JSON logging untuk observability.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from config.loader_yaml import load_yaml_config

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "level": "INFO",
    "format": "json",
    "json_ensure_ascii": False,
    "json_indent": None,
    "include_correlation_id": True,
    "include_user_id": True,
    "include_legal_entity_id": True,
    "log_to_console": True,
    "log_to_file": False,
    "file_path": "/var/log/erp/erp.log",
}


class StructuredJsonLogger:
    def __init__(self, name: str) -> None:
        self.name = name
        self._logger = logging.getLogger(name)
        self._config: dict[str, Any] = self._load_config()
        self._configure()

    def _load_config(self) -> dict[str, Any]:
        try:
            config = load_yaml_config("config_files/logging_config.yaml")
            return config.get("structured_logging", DEFAULT_CONFIG)
        except Exception:
            return DEFAULT_CONFIG

    def _configure(self) -> None:
        level = getattr(logging, self._config.get("level", "INFO").upper())
        self._logger.setLevel(level)
        self._logger.handlers.clear()
        # Anotasi eksplisit ``logging.Formatter`` agar mypy tidak mengunci tipe
        # dari assignment pertama (CustomJsonFormatter) lalu menolak
        # reassignment dengan base class Formatter di cabang ``else``.
        formatter: logging.Formatter
        if self._config.get("format") == "json":
            formatter = CustomJsonFormatter()
        else:
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        if self._config.get("log_to_console", True):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)
        if self._config.get("log_to_file", False):
            file_path = self._config.get("file_path", "/var/log/erp/erp.log")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file_handler = logging.FileHandler(file_path)
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def _get_current_correlation_id(self) -> str:
        try:
            from infrastructure.telemetry.correlation_id_injector import get_current_correlation_id

            corr_id = get_current_correlation_id()
            if corr_id:
                return corr_id
        except ImportError:
            pass
        return str(uuid4())

    def _get_current_user_id(self) -> str | None:
        try:
            from infrastructure.telemetry.correlation_id_injector import get_current_user_id

            return get_current_user_id()
        except ImportError:
            return None

    def _get_current_legal_entity_id(self) -> str | None:
        try:
            from infrastructure.telemetry.correlation_id_injector import get_current_legal_entity_id

            return get_current_legal_entity_id()
        except ImportError:
            return None

    def _add_context(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {"correlation_id": self._get_current_correlation_id()}
        if self._config.get("include_user_id", True):
            uid = self._get_current_user_id()
            if uid:
                context["user_id"] = uid
        if self._config.get("include_legal_entity_id", True):
            leid = self._get_current_legal_entity_id()
            if leid:
                context["legal_entity_id"] = leid
        if extra:
            context.update(extra)
        return context

    def debug(self, message: str, extra: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.debug(message, extra=self._add_context(extra), **kwargs)

    def info(self, message: str, extra: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.info(message, extra=self._add_context(extra), **kwargs)

    def warning(self, message: str, extra: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.warning(message, extra=self._add_context(extra), **kwargs)

    def error(self, message: str, extra: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.error(message, extra=self._add_context(extra), **kwargs)

    def critical(self, message: str, extra: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.critical(message, extra=self._add_context(extra), **kwargs)

    def exception(self, message: str, extra: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._logger.exception(message, extra=self._add_context(extra), **kwargs)

    def log(
        self, level: int, message: str, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        self._logger.log(level, message, extra=self._add_context(extra), **kwargs)


class CustomJsonFormatter(logging.Formatter):
    def __init__(
        self,
        fmt: dict[str, Any] | None = None,
        style: Literal["%", "{", "$"] = "%",
        validate: bool = True,
    ) -> None:
        # ``style`` di-parent ``Formatter`` bertipe ``Literal["%", "{", "$"]``,
        # bukan ``str``. Anotasi di sini menyempitkan tipe agar kompatibel.
        super().__init__(style=style, validate=validate)
        # Simpan sebagai atribut privat terpisah — jangan overwrite
        # ``self._fmt`` milik parent (bertipe ``str | None``).
        self._custom_fmt = fmt

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        # Manual ISO format with microseconds, works on all platforms
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.created % 1 * 1e6):06d}Z"

    def _get_current_correlation_id(self) -> str:
        try:
            from infrastructure.telemetry.correlation_id_injector import get_current_correlation_id

            corr_id = get_current_correlation_id()
            if corr_id:
                return corr_id
        except ImportError:
            pass
        return str(uuid4())

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.thread,
            "correlation_id": self._get_current_correlation_id(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in log_entry and not key.startswith("_"):
                    try:
                        json.dumps(value)
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        log_entry[key] = str(value)
        return json.dumps(log_entry, default=str, ensure_ascii=False)


_loggers: dict[str, StructuredJsonLogger] = {}


def get_logger(name: str) -> StructuredJsonLogger:
    if name not in _loggers:
        _loggers[name] = StructuredJsonLogger(name)
    return _loggers[name]


def get_json_logger(name: str) -> StructuredJsonLogger:
    return get_logger(name)


def configure_root_logger(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.handlers.clear()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomJsonFormatter())
    root_logger.addHandler(console_handler)
    logger.info(f"Root logger configured with level {level}")


class LogContext:
    def __init__(self, **kwargs: Any) -> None:
        self._context = kwargs
        self._previous_context: dict[str, Any] | None = None
        self._current_context: dict[str, Any] = {}

    def __enter__(self) -> "LogContext":
        self._previous_context = self._current_context.copy()
        self._current_context = self._context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._previous_context is not None:
            self._current_context = self._previous_context


def setup_logging(level: str = "INFO", **kwargs: Any) -> None:
    """Alias / wrapper untuk configure_root_logger demi kompatibilitas daur hidup ASGI."""
    configure_root_logger(level=level)


StructuredLogger = StructuredJsonLogger

__all__ = [
    "CustomJsonFormatter",
    "LogContext",
    "StructuredJsonLogger",
    "StructuredLogger",
    "configure_root_logger",
    "get_json_logger",
    "get_logger",
    "setup_logging",
]
