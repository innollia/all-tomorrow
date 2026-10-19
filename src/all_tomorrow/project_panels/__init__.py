"""Per-project panel plugins for the central console.

A plugin is a module in this package that defines:

    PROJECT_IDS: tuple[str, ...]          # registry ids it serves (config/projects.local.json)
    def collect(path: Path) -> dict       # cheap, read-only facts about the project folder

`collect` runs on the PC that holds the projects, never on the server. It must not
start servers, call networks, or return secrets/personal contents; the result is
size-capped and sent to the server inside the projects snapshot. The matching UI
lives in static/panels/<project id>.js and is loaded only when that page opens.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def plugins() -> dict[str, ModuleType]:
    found: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        for project_id in getattr(module, "PROJECT_IDS", ()):
            found[project_id] = module
    return found
