"""Spotify-based audio metadata tagging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, ID3NoHeaderError


@dataclass(frozen=True)
class MetadataResult:
    """Outcome of applying Spotify metadata to a downloaded file."""

    updated: bool
    message: str = ""


def find_downloaded_audio_file(output_template: str, audio_format: str) -> Optional[Path]:
    """Resolve the concrete file created from a yt-dlp output template."""

    if "%(ext)s" not in output_template:
        path = Path(output_template)
        return path if path.exists() else None

    preferred_path = Path(output_template.replace("%(ext)s", audio_format))
    if preferred_path.exists():
        return preferred_path

    template_path = Path(output_template)
    if template_path.name.endswith(".%(ext)s"):
        stem_name = template_path.name.removesuffix(".%(ext)s")
    else:
        stem_name = template_path.name.replace("%(ext)s", "")
    candidates = sorted(
        [path for path in template_path.parent.iterdir() if path.is_file() and path.stem == stem_name],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_easyid3(path: Path) -> EasyID3:
    try:
        return EasyID3(path)
    except ID3NoHeaderError:
        ID3().save(path)
        return EasyID3(path)


def apply_spotify_mp3_metadata(path: Path, row: Dict[str, str]) -> None:
    tags = load_easyid3(path)
    track_name = (row.get("track_name") or "").strip()
    artists = (row.get("artists") or "").strip()
    album = (row.get("album") or "").strip()
    release_date = (row.get("release_date") or "").strip()

    if track_name:
        tags["title"] = [track_name]
    if artists:
        tags["artist"] = [artists]
        tags["albumartist"] = [artists]
    if album:
        tags["album"] = [album]
    if release_date:
        tags["date"] = [release_date]

    tags.save(path)


def tag_downloaded_file(output_template: str, audio_format: str, row: Dict[str, str]) -> MetadataResult:
    path = find_downloaded_audio_file(output_template, audio_format)
    if path is None:
        return MetadataResult(updated=False, message="Downloaded file was not found for Spotify metadata tagging.")
    if path.suffix.lower() != ".mp3":
        return MetadataResult(updated=False)

    try:
        apply_spotify_mp3_metadata(path, row)
    except Exception as exc:
        return MetadataResult(updated=False, message=f"Spotify metadata tagging failed: {exc}")
    return MetadataResult(updated=True)
