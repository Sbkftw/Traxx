"""Query building and candidate selection for YouTube matching."""

from __future__ import annotations

import difflib
import json
import re
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

from ..constants import YTSEARCH_MAX_RESULTS
from .runtime import (
    build_js_runtimes,
    is_js_challenge_error,
    remove_cookies_args,
    remove_js_runtimes_args,
    run_with_auth_fallback,
)


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
    def plain(text: str) -> str:
        return " ".join(re.sub(r"[^\w\s]", " ", text).split())

    track_name = (row.get("track_name") or "").strip()
    artists = (row.get("artists") or "").strip()
    if not track_name:
        return []
    artist_list = [a.strip() for a in artists.split(",") if a.strip()]
    queries: List[str] = []
    track_plain = plain(track_name)
    artists_plain = plain(artists)

    if artists:
        queries.extend(
            [
                f"{artists_plain} {track_plain}".strip(),
                f"{artists} - {track_name}",
            ]
        )
        queries.extend([f"{artists} - {track_name} official audio", f"{artists} - {track_name} topic", f"{artists} - {track_name} audio"])
    if artist_list:
        primary = artist_list[0]
        primary_plain = plain(primary)
        queries.extend([f"{primary_plain} {track_plain}".strip(), f"{primary} - {track_name}"])
        queries.extend([f"{primary} - {track_name} official audio", f"{primary} - {track_name} topic", f"{primary} - {track_name} audio"])
    if len(artist_list) >= 2:
        top_two = ", ".join(artist_list[:2])
        top_two_plain = plain(top_two)
        queries.extend([f"{top_two_plain} {track_plain}".strip(), f"{top_two} - {track_name}"])
        queries.extend([f"{top_two} - {track_name} official audio", f"{top_two} - {track_name} topic", f"{top_two} - {track_name} audio"])

    queries.extend([track_plain or track_name, f"{track_name} official audio", f"{track_name} topic", f"{track_name} audio"])
    seen = set()
    unique_queries: List[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)
    return unique_queries


def fetch_video_metadata(
    video_id: str,
    dry_run: bool,
    cookies_from_browser: str,
    cookies_file: str,
    cookie_browser_candidates: List[str],
) -> Tuple[Optional[Dict[str, object]], str]:
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    def run_metadata_with_extractor_args(extractor_args: Optional[str]):
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
        return None, "dry-run: strict candidate evaluation was not executed"

    def run_search_with_extractor_args(extractor_args: Optional[str]):
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

