"""Download workflow and CSV state updates."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..cli import print_error, print_info, print_success
from ..constants import DOWNLOAD_STATUS_FIELD
from ..utils import normalize_downloaded_value, parse_downloaded_value, sanitize_filename
from .matching import build_query, build_query_candidates, pick_best_candidate
from .runtime import (
    build_js_runtimes,
    detect_cookie_browser_candidates,
    is_js_challenge_error,
    remove_cookies_args,
    remove_js_runtimes_args,
    run_with_auth_fallback,
    run_ytdlp_command,
)


@dataclass(frozen=True)
class DownloadOptions:
    """Runtime options for one download session."""

    csv_path: Path
    download_dir: str
    playlist_name: str
    audio_format: str
    convert_audio: bool
    limit: Optional[int]
    dry_run: bool
    cookies_from_browser: str
    cookies_file: str


def set_downloaded_value(row: Dict[str, str], downloaded: bool) -> None:
    row[DOWNLOAD_STATUS_FIELD] = "yes" if downloaded else "no"


def ensure_download_status_field(rows: List[Dict[str, str]]) -> bool:
    added = False
    for row in rows:
        if DOWNLOAD_STATUS_FIELD not in row:
            row[DOWNLOAD_STATUS_FIELD] = "no"
            added = True
        else:
            row[DOWNLOAD_STATUS_FIELD] = normalize_downloaded_value(row.get(DOWNLOAD_STATUS_FIELD, ""))
    return added


def save_rows(csv_path: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    if DOWNLOAD_STATUS_FIELD not in fieldnames:
        fieldnames.append(DOWNLOAD_STATUS_FIELD)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_download_command(
    *,
    video_url: str,
    output_template: str,
    audio_format: str,
    convert_audio: bool,
    cookies_from_browser: str,
    cookies_file: str,
) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        video_url,
        "--no-playlist",
        "--no-overwrites",
        "--embed-metadata",
        "--no-update",
        "-o",
        output_template,
    ]
    js_runtimes = build_js_runtimes()
    if js_runtimes:
        cmd.extend(["--js-runtimes", ",".join(js_runtimes)])
    cmd.extend(["-x", "--audio-format", audio_format, "--audio-quality", "0"] if convert_audio else ["-f", "bestaudio/best"])
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    elif cookies_file:
        cmd.extend(["--cookies", cookies_file])
    return cmd


def build_dry_run_preview_command(
    *,
    query: str,
    output_template: str,
    audio_format: str,
    convert_audio: bool,
    cookies_from_browser: str,
    cookies_file: str,
) -> List[str]:
    preview_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        f"ytsearch8:{query}",
        "--no-playlist",
        "--no-overwrites",
        "--embed-metadata",
        "--no-update",
        "--extractor-args",
        "youtube:player_client=web,web_creator",
        "-o",
        output_template,
    ]
    js_runtimes = build_js_runtimes()
    if js_runtimes:
        preview_cmd.extend(["--js-runtimes", ",".join(js_runtimes)])
    preview_cmd.extend(["-x", "--audio-format", audio_format, "--audio-quality", "0"] if convert_audio else ["-f", "bestaudio/best"])
    if cookies_from_browser:
        preview_cmd.extend(["--cookies-from-browser", cookies_from_browser])
    elif cookies_file:
        preview_cmd.extend(["--cookies", cookies_file])
    return preview_cmd


def download_tracks(rows: List[Dict[str, str]], options: DownloadOptions) -> None:
    target_download_dir = str(Path(options.download_dir) / sanitize_filename(options.playlist_name))
    Path(target_download_dir).mkdir(parents=True, exist_ok=True)
    errors = 0
    processed = 0
    skipped_already_downloaded = 0
    cookie_browser_candidates = detect_cookie_browser_candidates()

    for row in rows:
        if options.limit is not None and processed >= options.limit:
            break
        if not build_query(row):
            continue
        if parse_downloaded_value(row.get(DOWNLOAD_STATUS_FIELD, "")):
            skipped_already_downloaded += 1
            track_name = (row.get("track_name") or "").strip() or "track"
            artists = (row.get("artists") or "").strip() or "Unknown Artist"
            print_info(f"Skipping already downloaded track: {track_name} - {artists}")
            continue

        track_name = (row.get("track_name") or "").strip() or "track"
        artists = (row.get("artists") or "").strip() or "Unknown Artist"
        display_name = f"{track_name} - {artists}"
        output_template = str(Path(target_download_dir) / f"{sanitize_filename(display_name)}.%(ext)s")
        processed += 1
        print(f"[{processed}] Processing: {display_name}")
        last_error = ""

        if options.dry_run:
            candidates = build_query_candidates(row)
            preview_query = candidates[0] if candidates else f"{track_name} audio"
            preview_cmd = build_dry_run_preview_command(
                query=preview_query,
                output_template=output_template,
                audio_format=options.audio_format,
                convert_audio=options.convert_audio,
                cookies_from_browser=options.cookies_from_browser,
                cookies_file=options.cookies_file,
            )
            print_info("Dry run mode: strict candidate verification was skipped.")
            run_ytdlp_command(preview_cmd, dry_run=True)
            continue

        selected_entry = None
        selected_reason = ""
        selected_query = ""
        for candidate in build_query_candidates(row):
            entry, reason = pick_best_candidate(
                row,
                candidate,
                options.dry_run,
                options.cookies_from_browser,
                options.cookies_file,
                cookie_browser_candidates,
            )
            if entry is None:
                last_error = reason
                continue
            selected_entry, selected_reason, selected_query = entry, reason, candidate
            break

        if selected_entry is None:
            errors += 1
            set_downloaded_value(row, downloaded=False)
            save_rows(options.csv_path, rows)
            print_error("No YouTube result matched the strict title/artist/duration criteria.")
            if last_error:
                print_info(f"Last selection detail: {last_error}")
            continue

        video_id = str(selected_entry.get("id") or "").strip()
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_title = str(selected_entry.get("title") or "<untitled>")
        print_info(f"Selected match: {video_title} (query: {selected_query})")
        print_info(f"Match score: {selected_reason}")

        cmd = build_download_command(
            video_url=video_url,
            output_template=output_template,
            audio_format=options.audio_format,
            convert_audio=options.convert_audio,
            cookies_from_browser=options.cookies_from_browser,
            cookies_file=options.cookies_file,
        )

        run = run_with_auth_fallback(
            cmd,
            options.dry_run,
            options.cookies_from_browser,
            options.cookies_file,
            cookie_browser_candidates,
        )
        output = (run.stderr.strip() or run.stdout.strip())
        if run.returncode != 0 and is_js_challenge_error(output):
            cmd_android = remove_cookies_args(remove_js_runtimes_args(list(cmd)))
            cmd_android.extend(["--extractor-args", "youtube:player_client=android"])
            run = run_with_auth_fallback(
                cmd_android,
                options.dry_run,
                options.cookies_from_browser,
                options.cookies_file,
                cookie_browser_candidates,
            )
        if run.returncode == 0:
            set_downloaded_value(row, downloaded=True)
            save_rows(options.csv_path, rows)
            print_success("Download completed.")
            continue

        output = (run.stderr.strip() or run.stdout.strip())
        errors += 1
        set_downloaded_value(row, downloaded=False)
        save_rows(options.csv_path, rows)
        if output:
            if "Please sign in" in output:
                print_info("Tip: use --cookies-from-browser edge|chrome|firefox or --cookies <file.txt>.")
            if ("Signature solving failed" in output or "n challenge solving failed" in output) and "Please sign in" not in output:
                print_info("Tip: install node/deno and, if needed, add 'pip install -U yt_dlp_ejs'.")
            print_error(output)

    print(f"\nSummary: processed={processed}, failed={errors}, skipped_already_downloaded={skipped_already_downloaded}")

