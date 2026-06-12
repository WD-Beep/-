"""Ensure project .venv packages take precedence over global site-packages.

System-wide installs can leave pydantic / pydantic-settings in a broken mixed
version state (for example main.py expects `_lenient_issubclass` while utils.py
does not export it). When apps/api/.venv exists, prefer those packages.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent
_VENV_SITE = _API_ROOT / ".venv" / "Lib" / "site-packages"


def venv_python() -> Path | None:
    if sys.platform == "win32":
        candidate = _API_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = _API_ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def _prepend_path(path: Path) -> None:
    path_str = str(path.resolve())
    if path.exists() and path_str not in sys.path:
        sys.path.insert(0, path_str)


def _purge_non_venv_modules(prefix: str) -> None:
    if not _VENV_SITE.exists():
        return
    venv_root = str(_VENV_SITE.resolve())
    for name in list(sys.modules):
        if name != prefix and not name.startswith(f"{prefix}."):
            continue
        module = sys.modules.get(name)
        if module is None:
            continue
        module_file = getattr(module, "__file__", None) or ""
        normalized = module_file.replace("\\", "/")
        if module_file and venv_root.replace("\\", "/") not in normalized:
            del sys.modules[name]


def prefer_project_venv_packages() -> None:
    """Put .venv site-packages first and drop conflicting global imports."""
    _prepend_path(_API_ROOT)
    _prepend_path(_VENV_SITE)
    _purge_non_venv_modules("pydantic_settings")
    _purge_non_venv_modules("pydantic")


def reexec_with_venv_python(env_flag: str, *argv: str) -> None:
    """Re-exec the current process with the project venv Python when available."""
    interpreter = venv_python()
    if interpreter is None:
        return
    if Path(sys.executable).resolve() == interpreter.resolve():
        return
    if os.environ.get(env_flag) == "1":
        return
    os.environ[env_flag] = "1"
    os.execv(str(interpreter), [str(interpreter), *argv])
