# infrastructure/persistence_orm/__init__.py
from __future__ import annotations

import importlib
import logging
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

from infrastructure.persistence_orm.base_model import Base, TimestampMixin

# Import OutboxMessageTable dari file alias (yang merujuk ke OutboxTable)
from infrastructure.persistence_orm.outbox_message_table import OutboxMessageTable

# Auto-discovery
_current_dir = pathlib.Path(__file__).parent
table_files = [p.stem for p in _current_dir.glob("*.py") if p.name not in ("__init__.py", "base_model.py")]

loaded_models: dict[str, Any] = {}

for file_stem in table_files:
    module_name = f"infrastructure.persistence_orm.{file_stem}"
    try:
        module = importlib.import_module(module_name)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Base) and attr is not Base:
                if getattr(attr, "__abstract__", False):
                    loaded_models[attr_name] = attr
                    continue
                loaded_models[attr_name] = attr
    except Exception as e:
        logger.warning(f"Gagal import {module_name}: {e}")

# Pastikan OutboxMessageTable ada di loaded_models
if "OutboxMessageTable" not in loaded_models:
    loaded_models["OutboxMessageTable"] = OutboxMessageTable

loaded_models["Base"] = Base

# Registry sanitization (opsional)
try:
    registry = getattr(Base, "registry", None)
    if registry and hasattr(registry, "_class_registry"):
        class_reg = registry._class_registry
        for model_name, model_cls in loaded_models.items():
            if model_name != "Base" and not getattr(model_cls, "__abstract__", False):
                dict.__setitem__(class_reg, model_name, model_cls)
                if hasattr(class_reg, "_data") and isinstance(class_reg._data, dict):
                    class_reg._data[model_name] = model_cls
        for name in list(class_reg.keys()):
            val = class_reg[name]
            if not isinstance(val, type):
                target_cls = loaded_models.get(name)
                if not target_cls:
                    def _find_derived(c):
                        if c.__name__ == name and not getattr(c, "__abstract__", False):
                            return c
                        for sub in c.__subclasses__():
                            res = _find_derived(sub)
                            if res:
                                return res
                        return None
                    target_cls = _find_derived(Base)
                if target_cls:
                    dict.__setitem__(class_reg, name, target_cls)
                    if hasattr(class_reg, "_data") and isinstance(class_reg._data, dict):
                        class_reg._data[name] = target_cls
except Exception:
    pass

globals().update(loaded_models)
__all__ = list(loaded_models.keys())