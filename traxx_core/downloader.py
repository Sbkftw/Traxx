"""Public downloader API re-exported from focused internal modules."""

from __future__ import annotations

from .downloading.runtime import (
    ensure_ytdlp_installed,
    has_ffmpeg,
    preflight_ytdlp_runtime_check,
)
from .downloading.workflow import (
    DownloadOptions,
    download_tracks,
    ensure_download_status_field,
    save_rows,
)

__all__ = [
    "DownloadOptions",
    "download_tracks",
    "ensure_download_status_field",
    "ensure_ytdlp_installed",
    "has_ffmpeg",
    "preflight_ytdlp_runtime_check",
    "save_rows",
]
