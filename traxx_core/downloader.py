"""YouTube download workflow and CSV status updates."""

from __future__ import annotations

import csv
import difflib
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .constants import DOWNLOAD_STATUS_FIELD, YTSEARCH_MAX_RESULTS
from .utils import normalize_downloaded_value, parse_downloaded_value, sanitize_filename


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


def build_query(row: Dict[str, str]) -> Optional[str]:
    track_name = (row.get("track_name") or "").strip()
    artists = (row.get("artists") or "").strip()
    if not track_name:
        return None
    return f"{artists} - {track_name} audio" if artists else f"{track_name} audio"


def normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    normalized = unicodedata.normalize("NFKD", lowered)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return " ".join(cleaned.split())


def tokenize(value: str) -> List[str]:
    text = normalize_text(value)
    if not text:
        return []
    stop_words = {"the", "and", "feat", "featuring", "ft", "official", "audio", "video", "lyrics", "remix", "mix"}
    return [w for w in text.split() if len(w) > 1 and w not in stop_words]


def parse_duration_seconds(row: Dict[str, str]) -> Optional[int]:
    raw = (row.get("duration_ms") or "").strip()
    if not raw:
        return None
    try:
        ms = int(raw)
    except ValueError:
        return None
    return ms // 1000 if ms > 0 else None


def safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def build_search_candidate_text(entry: Dict[str, object]) -> str:
    parts = [str(entry.get("title") or ""), str(entry.get("uploader") or ""), str(entry.get("channel") or ""), str(entry.get("artist") or ""), str(entry.get("track") or "")]
    return " ".join(p for p in parts if p)


def token_overlap_ratio(required_tokens: List[str], candidate_tokens: List[str]) -> float:
    if not required_tokens:
        return 1.0
    if not candidate_tokens:
        return 0.0
    candidate_set = set(candidate_tokens)
    hits = sum(1 for token in required_tokens if token in candidate_set)
    return hits / len(required_tokens)


def score_candidate(row: Dict[str, str], entry: Dict[str, object]) -> Tuple[float, bool, str]:
    track_name = (row.get("track_name") or "").strip()
    artists = (row.get("artists") or "").strip()
    expected_duration = parse_duration_seconds(row)
    title = str(entry.get("title") or "")
    searchable_text = build_search_candidate_text(entry)
    duration = safe_int(entry.get("duration"))

    track_norm = normalize_text(track_name)
    title_norm = normalize_text(title)
    title_similarity = difflib.SequenceMatcher(a=track_norm, b=title_norm).ratio() if track_norm and title_norm else 0.0
    title_token_score = token_overlap_ratio(tokenize(track_name), tokenize(title))
    title_score = max(title_similarity, title_token_score)
    artist_score = token_overlap_ratio(tokenize(artists), tokenize(searchable_text))

    duration_score = 0.0
    duration_pass = True
    duration_note = "n/a"
    if expected_duration is not None:
        if duration is None:
            duration_pass = False
            duration_note = "duration-missing"
        else:
            tolerance = max(12, int(expected_duration * 0.15))
            diff = abs(duration - expected_duration)
            duration_pass = diff <= tolerance
            duration_score = max(0.0, 1.0 - (diff / max(tolerance, 1)))
            duration_note = f"{duration}s vs {expected_duration}s (diff={diff}s, tol={tolerance}s)"
    else:
        duration_score = 0.5

    title_pass = title_score >= 0.6
    artist_pass = artist_score >= 0.5 if artists.strip() else True
    strict_match = title_pass and artist_pass and duration_pass

    final_score = (title_score * 0.55) + (artist_score * 0.30) + (duration_score * 0.15)
    reason = (
        f"title={title_score:.2f} artist={artist_score:.2f} duration={duration_note} "
        f"(pass: title={title_pass}, artist={artist_pass}, duration={duration_pass})"
    )
    return final_score, strict_match, reason


def build_query_candidates(row: Dict[str, str]) -> List[str]:
    track_name = (row.get("track_name") or "").strip()
    artists = (row.get("artists") or "").strip()
    if not track_name:
        return []
    artist_list = [a.strip() for a in artists.split(",") if a.strip()]
    queries: List[str] = []

    if artists:
        queries.extend([f"{artists} - {track_name} official audio", f"{artists} - {track_name} topic", f"{artists} - {track_name} audio"])
    if artist_list:
        primary = artist_list[0]
        queries.extend([f"{primary} - {track_name} official audio", f"{primary} - {track_name} topic", f"{primary} - {track_name} audio"])
    if len(artist_list) >= 2:
        top_two = ", ".join(artist_list[:2])
        queries.extend([f"{top_two} - {track_name} official audio", f"{top_two} - {track_name} topic", f"{top_two} - {track_name} audio"])

    queries.extend([f"{track_name} official audio", f"{track_name} topic", f"{track_name} audio"])
    seen = set()
    unique_queries: List[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)
    return unique_queries


def ensure_ytdlp_installed() -> None:
    if importlib.util.find_spec("yt_dlp") is None:
        raise RuntimeError(
            "yt-dlp est introuvable dans cet environnement Python. Installe-le avec 'python -m pip install yt-dlp' "
            "et assure-toi que ffmpeg est installe si tu veux convertir en mp3."
        )


def preflight_ytdlp_runtime_check() -> None:
    has_node = shutil.which("node") is not None
    has_deno = shutil.which("deno") is not None
    has_ejs = importlib.util.find_spec("yt_dlp_ejs") is not None
    if has_ejs and (has_node or has_deno):
        return
    print("INFO: Environnement yt-dlp incomplet pour certains flux YouTube (signature/n challenge).")
    print("      Recommande: installer un runtime JS (node ou deno) + support EJS.")


def build_js_runtimes() -> List[str]:
    runtimes: List[str] = []
    if shutil.which("node") is not None:
        runtimes.append("node")
    if shutil.which("deno") is not None:
        runtimes.append("deno")
    return runtimes


def detect_cookie_browser_candidates() -> List[str]:
    candidates = ["edge", "chrome", "firefox"]
    if platform.system().lower() == "darwin":
        candidates = ["safari", "chrome", "firefox", "edge"]
    elif platform.system().lower() == "linux":
        candidates = ["chrome", "chromium", "firefox", "brave"]
    return candidates


def is_signin_required_error(output: str) -> bool:
    lowered = output.lower()
    return "please sign in" in lowered or "use --cookies-from-browser or --cookies" in lowered


def is_js_challenge_error(output: str) -> bool:
    lowered = output.lower()
    return (
        "js challenge provider" in lowered
        or "signature solving failed" in lowered
        or "n challenge solving failed" in lowered
        or "only images are available for download" in lowered
    )


def remove_js_runtimes_args(cmd: List[str]) -> List[str]:
    cleaned: List[str] = []
    skip_next = False
    for token in cmd:
        if skip_next:
            skip_next = False
            continue
        if token == "--js-runtimes":
            skip_next = True
            continue
        cleaned.append(token)
    return cleaned


def remove_cookies_args(cmd: List[str]) -> List[str]:
    cleaned: List[str] = []
    skip_next = False
    for token in cmd:
        if skip_next:
            skip_next = False
            continue
        if token in {"--cookies-from-browser", "--cookies"}:
            skip_next = True
            continue
        cleaned.append(token)
    return cleaned


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_ytdlp_command(cmd: List[str], dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        print("    " + " ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, capture_output=True, text=True)


def run_with_auth_fallback(
    cmd: List[str],
    dry_run: bool,
    cookies_from_browser: str,
    cookies_file: str,
    cookie_browser_candidates: List[str],
) -> subprocess.CompletedProcess[str]:
    run = run_ytdlp_command(cmd, dry_run)
    if run.returncode != 0 and cookies_from_browser:
        output = (run.stderr.strip() or run.stdout.strip())
        if "Failed to decrypt with DPAPI" in output:
            print("    INFO: Echec DPAPI avec cookies navigateur, nouvelle tentative sans cookies...")
            cmd_no_cookies = [c for c in cmd if c not in {"--cookies-from-browser", cookies_from_browser}]
            run = run_ytdlp_command(cmd_no_cookies, dry_run)
    if run.returncode != 0 and not cookies_from_browser and not cookies_file:
        output = (run.stderr.strip() or run.stdout.strip())
        if is_signin_required_error(output):
            for browser in cookie_browser_candidates:
                print(f"    INFO: Nouvelle tentative avec cookies navigateur: {browser}")
                retry = run_ytdlp_command(cmd + ["--cookies-from-browser", browser], dry_run)
                if retry.returncode == 0:
                    return retry
                retry_output = (retry.stderr.strip() or retry.stdout.strip())
                if "Failed to decrypt with DPAPI" in retry_output:
                    continue
    return run


def fetch_video_metadata(
    video_id: str,
    dry_run: bool,
    cookies_from_browser: str,
    cookies_file: str,
    cookie_browser_candidates: List[str],
) -> Tuple[Optional[Dict[str, object]], str]:
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    def run_metadata_with_extractor_args(extractor_args: Optional[str]) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            video_url,
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
        ]
        if extractor_args:
            cmd.extend(["--extractor-args", extractor_args])
        js_runtimes = build_js_runtimes()
        if js_runtimes:
            cmd.extend(["--js-runtimes", ",".join(js_runtimes)])
        if cookies_from_browser:
            cmd.extend(["--cookies-from-browser", cookies_from_browser])
        elif cookies_file:
            cmd.extend(["--cookies", cookies_file])
        return run_with_auth_fallback(cmd, dry_run, cookies_from_browser, cookies_file, cookie_browser_candidates)

    run = run_metadata_with_extractor_args("youtube:player_client=web")
    output = (run.stdout or "").strip()
    if run.returncode != 0:
        err = (run.stderr.strip() or output)
        if is_js_challenge_error(err):
            fallback_cmd = remove_cookies_args(
                remove_js_runtimes_args(
                [
                    sys.executable,
                    "-m",
                    "yt_dlp",
                    video_url,
                    "--dump-single-json",
                    "--skip-download",
                    "--no-playlist",
                    "--no-warnings",
                    "--extractor-args",
                    "youtube:player_client=android",
                ]
                )
            )
            run = run_with_auth_fallback(fallback_cmd, dry_run, cookies_from_browser, cookies_file, cookie_browser_candidates)
            output = (run.stdout or "").strip()
            err = (run.stderr.strip() or output)
        if "Requested format is not available" in err:
            run = run_metadata_with_extractor_args(None)
            output = (run.stdout or "").strip()
        if run.returncode != 0:
            err = (run.stderr.strip() or output)
            return None, err or "metadata-failed"

    if not output:
        return None, "metadata-empty"
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None, "metadata-json-invalid"
    if not isinstance(payload, dict):
        return None, "metadata-json-unexpected"
    return payload, ""


def pick_best_candidate(
    row: Dict[str, str],
    query: str,
    dry_run: bool,
    cookies_from_browser: str,
    cookies_file: str,
    cookie_browser_candidates: List[str],
) -> Tuple[Optional[Dict[str, object]], str]:
    base_search_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        f"ytsearch{YTSEARCH_MAX_RESULTS}:{query}",
        "--dump-single-json",
        "--flat-playlist",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--ignore-errors",
    ]
    if dry_run:
        return None, "dry-run: selection stricte non evaluee"

    def run_search_with_extractor_args(extractor_args: Optional[str]) -> subprocess.CompletedProcess[str]:
        search_cmd = list(base_search_cmd)
        if extractor_args:
            search_cmd.extend(["--extractor-args", extractor_args])
        js_runtimes = build_js_runtimes()
        if js_runtimes:
            search_cmd.extend(["--js-runtimes", ",".join(js_runtimes)])
        if cookies_from_browser:
            search_cmd.extend(["--cookies-from-browser", cookies_from_browser])
        elif cookies_file:
            search_cmd.extend(["--cookies", cookies_file])
        return run_with_auth_fallback(search_cmd, dry_run, cookies_from_browser, cookies_file, cookie_browser_candidates)

    run = run_search_with_extractor_args(None)
    output = (run.stdout or "").strip()
    if run.returncode != 0:
        err = (run.stderr.strip() or output)
        if not output:
            return None, err or "search-failed"
    if not output:
        return None, "search-empty"

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None, "search-json-invalid"

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        return None, "search-no-entries"

    best_entry: Optional[Dict[str, object]] = None
    best_score = -1.0
    best_reason = "no-candidate"
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "").strip()
        if not entry_id:
            continue
        score_entry = dict(entry)
        if safe_int(score_entry.get("duration")) is None:
            metadata, metadata_error = fetch_video_metadata(entry_id, dry_run, cookies_from_browser, cookies_file, cookie_browser_candidates)
            if metadata is not None:
                score_entry = metadata
            elif metadata_error:
                best_reason = metadata_error
                continue
        score, strict_match, reason = score_candidate(row, score_entry)
        if strict_match and score > best_score:
            best_entry = score_entry
            best_score = score
            best_reason = reason

    if best_entry is None:
        return None, "strict-match-not-found"
    return best_entry, best_reason


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
            print(f"[SKIP] {track_name} - {artists} (deja telecharge)")
            continue

        track_name = (row.get("track_name") or "").strip() or "track"
        artists = (row.get("artists") or "").strip() or "Unknown Artist"
        display_name = f"{track_name} - {artists}"
        output_template = str(Path(target_download_dir) / f"{sanitize_filename(display_name)}.%(ext)s")
        processed += 1
        print(f"[{processed}] {display_name}")
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
            print("    DRY-RUN: verification stricte non executee (pas de reseau).")
            run_ytdlp_command(preview_cmd, dry_run=True)
            continue

        selected_entry: Optional[Dict[str, object]] = None
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
            print("    ECHEC: aucun resultat YouTube ne respecte les criteres stricts (titre/artiste/duree).")
            if last_error:
                print(f"    DETAIL: {last_error}")
            continue

        video_id = str(selected_entry.get("id") or "").strip()
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_title = str(selected_entry.get("title") or "<sans titre>")
        print(f"    Match retenu: {video_title} (query: {selected_query})")
        print(f"    Score match: {selected_reason}")

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
            print("    OK")
            continue

        output = (run.stderr.strip() or run.stdout.strip())
        errors += 1
        set_downloaded_value(row, downloaded=False)
        save_rows(options.csv_path, rows)
        if output:
            if "Please sign in" in output:
                print("    CONSEIL: Utilise --cookies-from-browser edge|chrome|firefox, ou --cookies <fichier.txt>.")
            if ("Signature solving failed" in output or "n challenge solving failed" in output) and "Please sign in" not in output:
                print("    CONSEIL: Installe node/deno + 'pip install -U \"yt-dlp[ejs]\"'.")
            print(f"    ECHEC: {output}")

    print(f"\nTermine: {processed} titres traites, {errors} echec(s), {skipped_already_downloaded} deja telecharge(s).")
