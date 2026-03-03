import argparse
import csv
import difflib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_CSV_DIR = "output"
DEFAULT_DOWNLOAD_DIR = "downloads"


def sanitize_filename(value: str) -> str:
    cleaned = "".join("_" if c in '<>:"/\\|?*\x00' else c for c in value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        return "track"
    return cleaned[:150]


def infer_playlist_name_from_csv(csv_path: Path) -> str:
    stem = csv_path.stem.strip()
    # Expected generator format: "<playlist-name>-dd-mm.csv"
    match = re.match(r"^(.*)-\d{2}-\d{2}$", stem)
    if match and match.group(1).strip():
        return sanitize_filename(match.group(1).strip())
    return sanitize_filename(stem or "playlist")


def find_latest_csv(csv_dir: str) -> Path:
    folder = Path(csv_dir)
    if not folder.exists():
        raise FileNotFoundError(f"Dossier introuvable: {csv_dir}")

    csv_files = [p for p in folder.glob("*.csv") if p.is_file()]
    if not csv_files:
        raise FileNotFoundError(f"Aucun fichier CSV trouve dans: {csv_dir}")

    return max(csv_files, key=lambda p: p.stat().st_mtime)


def load_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def build_query(row: Dict[str, str]) -> Optional[str]:
    track_name = (row.get("track_name") or "").strip()
    artists = (row.get("artists") or "").strip()
    if not track_name:
        return None
    if artists:
        return f"{artists} - {track_name} audio"
    return f"{track_name} audio"


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
    stop_words = {
        "the",
        "and",
        "feat",
        "featuring",
        "ft",
        "official",
        "audio",
        "video",
        "lyrics",
        "remix",
        "mix",
    }
    return [w for w in text.split() if len(w) > 1 and w not in stop_words]


def parse_duration_seconds(row: Dict[str, str]) -> Optional[int]:
    raw = (row.get("duration_ms") or "").strip()
    if not raw:
        return None
    try:
        ms = int(raw)
    except ValueError:
        return None
    if ms <= 0:
        return None
    return ms // 1000


def safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def build_search_candidate_text(entry: Dict[str, object]) -> str:
    parts = [
        str(entry.get("title") or ""),
        str(entry.get("uploader") or ""),
        str(entry.get("channel") or ""),
        str(entry.get("artist") or ""),
        str(entry.get("track") or ""),
    ]
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

    queries: List[str] = []
    if artists:
        queries.append(f"{artists} - {track_name} official audio")
        queries.append(f"{artists} - {track_name} topic")
        queries.append(f"{artists} - {track_name} audio")
    queries.append(f"{track_name} official audio")
    queries.append(f"{track_name} audio")

    # De-duplicate while preserving order.
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

    print(
        "INFO: Environnement yt-dlp incomplet pour certains flux YouTube "
        "(signature/n challenge)."
    )
    print("      Recommande: installer un runtime JS (node ou deno) + support EJS.")


def build_js_runtimes() -> List[str]:
    runtimes: List[str] = []
    if shutil.which("node") is not None:
        runtimes.append("node")
    if shutil.which("deno") is not None:
        runtimes.append("deno")
    return runtimes


def detect_cookie_browser_candidates() -> List[str]:
    # Candidate order tuned for common Windows setups first.
    candidates = ["edge", "chrome", "firefox"]
    if platform.system().lower() == "darwin":
        candidates = ["safari", "chrome", "firefox", "edge"]
    elif platform.system().lower() == "linux":
        candidates = ["chrome", "chromium", "firefox", "brave"]
    return candidates


def is_signin_required_error(output: str) -> bool:
    lowered = output.lower()
    return (
        "please sign in" in lowered
        or "use --cookies-from-browser or --cookies" in lowered
    )


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
                cmd_with_browser_cookies = cmd + ["--cookies-from-browser", browser]
                retry = run_ytdlp_command(cmd_with_browser_cookies, dry_run)
                if retry.returncode == 0:
                    run = retry
                    break
                retry_output = (retry.stderr.strip() or retry.stdout.strip())
                if "Failed to decrypt with DPAPI" in retry_output:
                    continue
    return run


def pick_best_candidate(
    row: Dict[str, str],
    query: str,
    dry_run: bool,
    cookies_from_browser: str,
    cookies_file: str,
    cookie_browser_candidates: List[str],
) -> Tuple[Optional[Dict[str, object]], str]:
    search_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        f"ytsearch8:{query}",
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--extractor-args",
        "youtube:player_client=web,web_creator",
    ]
    js_runtimes = build_js_runtimes()
    if js_runtimes:
        search_cmd.extend(["--js-runtimes", ",".join(js_runtimes)])
    if cookies_from_browser:
        search_cmd.extend(["--cookies-from-browser", cookies_from_browser])
    elif cookies_file:
        search_cmd.extend(["--cookies", cookies_file])

    if dry_run:
        return None, "dry-run: selection stricte non evaluee"

    run = run_with_auth_fallback(
        cmd=search_cmd,
        dry_run=dry_run,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        cookie_browser_candidates=cookie_browser_candidates,
    )
    if run.returncode != 0:
        output = (run.stderr.strip() or run.stdout.strip())
        return None, output or "search-failed"

    output = (run.stdout or "").strip()
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
        score, strict_match, reason = score_candidate(row, entry)
        if strict_match and score > best_score:
            best_entry = entry
            best_score = score
            best_reason = reason

    if best_entry is None:
        return None, "strict-match-not-found"
    return best_entry, best_reason


def download_tracks(
    rows: List[Dict[str, str]],
    download_dir: str,
    playlist_name: str,
    audio_format: str,
    convert_audio: bool,
    limit: Optional[int],
    dry_run: bool,
    cookies_from_browser: str,
    cookies_file: str,
) -> None:
    target_download_dir = str(Path(download_dir) / sanitize_filename(playlist_name))
    os.makedirs(target_download_dir, exist_ok=True)
    errors = 0
    processed = 0
    cookie_browser_candidates = detect_cookie_browser_candidates()

    for row in rows:
        if limit is not None and processed >= limit:
            break

        if not build_query(row):
            continue

        track_name = (row.get("track_name") or "").strip() or "track"
        artists = (row.get("artists") or "").strip() or "Unknown Artist"
        display_name = f"{track_name} - {artists}"
        safe_name = sanitize_filename(display_name)
        output_template = str(Path(target_download_dir) / f"{safe_name}.%(ext)s")

        processed += 1
        print(f"[{processed}] {display_name}")
        last_error = ""
        if dry_run:
            preview_query = build_query_candidates(row)[0] if build_query_candidates(row) else f"{track_name} audio"
            preview_cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                f"ytsearch8:{preview_query}",
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
            if convert_audio:
                preview_cmd.extend(["-x", "--audio-format", audio_format, "--audio-quality", "0"])
            else:
                preview_cmd.extend(["-f", "bestaudio/best"])
            if cookies_from_browser:
                preview_cmd.extend(["--cookies-from-browser", cookies_from_browser])
            elif cookies_file:
                preview_cmd.extend(["--cookies", cookies_file])
            print("    DRY-RUN: verification stricte non executee (pas de reseau).")
            run_ytdlp_command(preview_cmd, dry_run=True)
            continue

        selected_entry: Optional[Dict[str, object]] = None
        selected_reason = ""
        selected_query = ""

        for candidate in build_query_candidates(row):
            entry, reason = pick_best_candidate(
                row=row,
                query=candidate,
                dry_run=dry_run,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                cookie_browser_candidates=cookie_browser_candidates,
            )
            if entry is None:
                last_error = reason
                continue

            selected_entry = entry
            selected_reason = reason
            selected_query = candidate
            break

        if selected_entry is None:
            errors += 1
            print("    ECHEC: aucun resultat YouTube ne respecte les criteres stricts (titre/artiste/duree).")
            if last_error:
                print(f"    DETAIL: {last_error}")
            continue

        video_id = str(selected_entry.get("id") or "").strip()
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_title = str(selected_entry.get("title") or "<sans titre>")
        print(f"    Match retenu: {video_title} (query: {selected_query})")
        print(f"    Score match: {selected_reason}")

        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            video_url,
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
            cmd.extend(["--js-runtimes", ",".join(js_runtimes)])
        if convert_audio:
            cmd.extend(
                [
                    "-x",
                    "--audio-format",
                    audio_format,
                    "--audio-quality",
                    "0",
                ]
            )
        else:
            cmd.extend(["-f", "bestaudio/best"])
        if cookies_from_browser:
            cmd.extend(["--cookies-from-browser", cookies_from_browser])
        elif cookies_file:
            cmd.extend(["--cookies", cookies_file])

        run = run_with_auth_fallback(
            cmd=cmd,
            dry_run=dry_run,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            cookie_browser_candidates=cookie_browser_candidates,
        )
        if run.returncode == 0:
            print("    OK")
            continue

        output = (run.stderr.strip() or run.stdout.strip())
        errors += 1
        last_error = output

        if last_error:
            if "Please sign in" in last_error:
                print(
                    "    CONSEIL: YouTube demande une session. Utilise "
                    "--cookies-from-browser edge|chrome|firefox, ou --cookies <fichier.txt>."
                )
            if (
                "Signature solving failed" in last_error
                or "n challenge solving failed" in last_error
            ) and "Please sign in" not in last_error:
                print(
                    "    CONSEIL: Installe node/deno + 'pip install -U \"yt-dlp[ejs]\"'."
                )
            print(f"    ECHEC: {last_error}")

    print(f"\nTermine: {processed} titres traites, {errors} echec(s).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Telecharge les titres d'un CSV Spotify via yt-dlp (recherche YouTube)."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default="",
        help="Chemin du CSV. Si absent, prend le plus recent fichier dans output/.",
    )
    parser.add_argument(
        "--csv-dir",
        default=DEFAULT_CSV_DIR,
        help="Dossier ou chercher le CSV le plus recent (defaut: output).",
    )
    parser.add_argument(
        "--download-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help="Dossier des fichiers telecharges (defaut: downloads).",
    )
    parser.add_argument(
        "--audio-format",
        default="mp3",
        help="Format audio cible pour yt-dlp -x (defaut: mp3).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre max de titres a traiter.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les commandes sans telecharger.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=os.getenv("YTDLP_COOKIES_FROM_BROWSER", ""),
        help=(
            "Ex: chrome, edge, firefox. Recommande pour limiter les blocages YouTube "
            "(ou via env YTDLP_COOKIES_FROM_BROWSER)."
        ),
    )
    parser.add_argument(
        "--cookies",
        default=os.getenv("YTDLP_COOKIES_FILE", ""),
        help=(
            "Chemin vers un fichier cookies Netscape exporte depuis le navigateur "
            "(ou via env YTDLP_COOKIES_FILE)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_ytdlp_installed()
    preflight_ytdlp_runtime_check()
    convert_audio = has_ffmpeg()
    if not convert_audio:
        print(
            "INFO: ffmpeg/ffprobe introuvable -> telechargement audio sans conversion "
            "(pas de mp3 force)."
        )

    if args.csv_path:
        csv_path = Path(args.csv_path)
    else:
        csv_path = find_latest_csv(args.csv_dir)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV introuvable: {csv_path}")

    rows = load_rows(csv_path)
    if not rows:
        print(f"CSV vide: {csv_path}")
        return

    playlist_name = infer_playlist_name_from_csv(csv_path)
    print(f"CSV source: {csv_path}")
    print(f"Dossier cible: {Path(args.download_dir) / playlist_name}")
    download_tracks(
        rows=rows,
        download_dir=args.download_dir,
        playlist_name=playlist_name,
        audio_format=args.audio_format,
        convert_audio=convert_audio,
        limit=args.limit,
        dry_run=args.dry_run,
        cookies_from_browser=args.cookies_from_browser.strip(),
        cookies_file=args.cookies.strip(),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Erreur: {exc}")
        sys.exit(1)
