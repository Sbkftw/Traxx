"""CSV read/merge/write utilities for playlist snapshots."""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .constants import DOWNLOAD_STATUS_FIELD, OUTPUT_DIR
from .utils import normalize_downloaded_value, sanitize_filename


@dataclass(frozen=True)
class MergeResult:
    """Result summary for playlist merge operations."""

    rows: List[Dict[str, object]]
    added_count: int
    existing_count: int
    output_path: str


def build_output_path(playlist_name: str) -> str:
    safe_name = sanitize_filename(playlist_name)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return os.path.join(OUTPUT_DIR, f"{safe_name}.csv")


def find_existing_playlist_csv(playlist_name: str) -> Optional[str]:
    if not os.path.isdir(OUTPUT_DIR):
        return None

    safe_name = sanitize_filename(playlist_name)
    current_path = os.path.join(OUTPUT_DIR, f"{safe_name}.csv")
    if os.path.exists(current_path):
        return current_path

    # Backward compatibility with older naming format: "<playlist>-dd-mm.csv".
    pattern = re.compile(rf"^{re.escape(safe_name)}-\d{{2}}-\d{{2}}\.csv$", re.IGNORECASE)
    candidates = [os.path.join(OUTPUT_DIR, name) for name in os.listdir(OUTPUT_DIR) if pattern.match(name)]
    return max(candidates, key=os.path.getmtime) if candidates else None


def load_existing_rows(csv_path: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if not os.path.exists(csv_path):
        return rows

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            cleaned: Dict[str, object] = {}
            for key, value in row.items():
                cleaned[str(key or "").replace("\ufeff", "").strip()] = value if value is not None else ""
            cleaned[DOWNLOAD_STATUS_FIELD] = normalize_downloaded_value(cleaned.get(DOWNLOAD_STATUS_FIELD, ""))
            rows.append(cleaned)
    return rows


def make_pending_download_row(track: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(track)
    normalized[DOWNLOAD_STATUS_FIELD] = "no"
    return normalized


def merge_tracks_with_existing_csv(new_tracks: List[Dict[str, object]], playlist_name: str) -> MergeResult:
    existing_csv = find_existing_playlist_csv(playlist_name)
    output_path = build_output_path(playlist_name)
    if not existing_csv:
        fresh_rows = [make_pending_download_row(row) for row in new_tracks]
        return MergeResult(rows=fresh_rows, added_count=len(fresh_rows), existing_count=0, output_path=output_path)

    existing_rows = load_existing_rows(existing_csv)
    existing_track_ids = {
        str(row.get("track_id", "")).strip()
        for row in existing_rows
        if str(row.get("track_id", "")).strip()
    }
    added_count = 0
    for track in new_tracks:
        track_id = str(track.get("track_id", "")).strip()
        if not track_id or track_id in existing_track_ids:
            continue
        existing_rows.append(make_pending_download_row(track))
        existing_track_ids.add(track_id)
        added_count += 1

    return MergeResult(rows=existing_rows, added_count=added_count, existing_count=len(existing_track_ids), output_path=output_path)


def write_csv(rows: List[Dict[str, object]], output_path: str) -> None:
    if not rows:
        print("Aucun titre trouve dans cette playlist.")
        return

    # Preserve visible field order from first row and ensure status column is present.
    fieldnames = list(rows[0].keys())
    if DOWNLOAD_STATUS_FIELD not in fieldnames:
        fieldnames.append(DOWNLOAD_STATUS_FIELD)
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV genere: {output_path} ({len(rows)} titres)")


def rows_to_string_rows(rows: List[Dict[str, object]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for row in rows:
        normalized.append({str(k): "" if v is None else str(v) for k, v in row.items()})
    return normalized
