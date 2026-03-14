"""Low-level helpers reused across modules."""

from __future__ import annotations

import os
import re
from typing import Any


def load_dotenv(path: str = ".env", override: bool = True) -> None:
    """Load simple KEY=VALUE pairs into os.environ."""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as dotenv_file:
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

