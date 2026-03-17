"""Low-level helpers reused across modules."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any


def resolve_dotenv_path(path: str = ".env") -> Path:
    """Resolve the preferred .env location for source and packaged execution."""
    candidate_name = Path(path)
    if candidate_name.is_absolute():
        return candidate_name

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        packaged_candidate = executable_dir / candidate_name
        if packaged_candidate.exists():
            return packaged_candidate

    working_dir_candidate = Path.cwd() / candidate_name
    if working_dir_candidate.exists():
        return working_dir_candidate

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / candidate_name

    return working_dir_candidate


def load_dotenv(path: str = ".env", override: bool = True) -> None:
    """Load simple KEY=VALUE pairs into os.environ."""
    resolved_path = resolve_dotenv_path(path)
    if not resolved_path.exists():
        return

    with resolved_path.open("r", encoding="utf-8") as dotenv_file:
        for raw_line in dotenv_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (override or key not in os.environ):
                os.environ[key] = value


def sanitize_filename(value: str) -> str:
    """Return a filesystem-safe filename stem."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value).strip(" .")
    return cleaned or "playlist"


def parse_downloaded_value(value: Any) -> bool:
    """Interpret common truthy values used in CSV status fields."""
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "ok", "done"}


def normalize_downloaded_value(value: Any) -> str:
    """Normalize to canonical CSV values: yes/no."""
    return "yes" if parse_downloaded_value(value) else "no"

