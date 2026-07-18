"""
core/config.py
==============
Konfigurasi aplikasi frontend. Nilai default bisa dioverride lewat
environment variable atau file `~/.sovereign_erp/config.ini`.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Sovereign ERP Desktop"
APP_ORG = "SovereignERP"
APP_VERSION = "1.0.0"

CONFIG_FILE = Path.home() / ".sovereign_erp" / "config.ini"


@dataclass
class AppConfig:
    api_base_url: str = "http://127.0.0.1:8080/api/v1"
    request_timeout: int = 30
    verify_ssl: bool = True
    remember_last_username: bool = True

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        cfg.api_base_url = os.environ.get("ERP_API_BASE_URL", cfg.api_base_url)
        if CONFIG_FILE.exists():
            parser = configparser.ConfigParser()
            parser.read(CONFIG_FILE, encoding="utf-8")
            if parser.has_section("api"):
                cfg.api_base_url = parser.get("api", "base_url", fallback=cfg.api_base_url)
                cfg.request_timeout = parser.getint("api", "timeout", fallback=cfg.request_timeout)
                cfg.verify_ssl = parser.getboolean("api", "verify_ssl", fallback=cfg.verify_ssl)
        return cfg

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        parser = configparser.ConfigParser()
        parser["api"] = {
            "base_url": self.api_base_url,
            "timeout": str(self.request_timeout),
            "verify_ssl": str(self.verify_ssl),
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            parser.write(fh)


settings = AppConfig.load()
