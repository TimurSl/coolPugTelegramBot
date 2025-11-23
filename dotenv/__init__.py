"""Lightweight fallback implementation of python-dotenv."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def find_dotenv(usecwd: bool = False, filename: str = ".env") -> str:
    """Locate the nearest .env file by walking up the directory tree."""

    start = Path.cwd() if usecwd else Path(__file__).resolve().parent
    for candidate in [start, *start.parents]:
        target = candidate / filename
        if target.exists():
            return str(target)
    return ""


def load_dotenv(path: Optional[str] = None) -> bool:
    """Load key=value pairs from a .env file into the environment."""

    file_path = Path(path) if path else Path(find_dotenv(usecwd=True))
    if not file_path.exists() or not file_path.is_file():
        return False

    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)
    return True

