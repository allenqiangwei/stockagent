"""Factor auto-discovery — imports all factor modules to trigger @register_factor decorators."""

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Auto-import all .py files in this directory (except __init__ and registry)
_package_dir = str(Path(__file__).parent)
for _, module_name, _ in pkgutil.iter_modules([_package_dir]):
    if module_name not in ("registry",):
        try:
            importlib.import_module(f".{module_name}", __package__)
        except Exception as e:
            logger.warning("Failed to import factor module %s: %s", module_name, e)
