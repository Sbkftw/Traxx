"""CLI orchestration for Traxx."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .constants import DEFAULT_DOWNLOAD_DIR, DEFAULT_SCOPE
from .csv_store import merge_tracks_with_existing_csv, rows_to_string_rows, write_csv
from .downloader import (
    download_tracks,
    ensure_download_status_field,
    ensure_ytdlp_installed,
    has_ffmpeg,
    preflight_ytdlp_runtime_check,
    save_rows,
)
from .spotify import extract_playlist_id, fetch_all_tracks, get_user_access_token, run_diagnostics
from .utils import load_dotenv


def get_env_or_exit(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"Variable manquante: {name} (fichier .env)")
        sys.exit(1)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate/merge a Spotify playlist CSV, then download pending tracks from YouTube."
    )
    parser.add_argument("--no-download", action="store_true", help="Generate/merge CSV only.")
    parser.add_argument("--download-dir", default=DEFAULT_DOWNLOAD_DIR, help="Download target folder (default: downloads).")
    parser.add_argument("--audio-format", default="mp3", help="Target audio format when ffmpeg is available (default: mp3).")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of tracks to process.")
    parser.add_argument("--dry-run", action="store_true", help="Print yt-dlp commands without downloading.")
    parser.add_argument("--cookies-from-browser", default=os.getenv("YTDLP_COOKIES_FROM_BROWSER", ""), help="Browser cookies source: edge/chrome/firefox.")
    parser.add_argument("--cookies", default=os.getenv("YTDLP_COOKIES_FILE", ""), help="Path to Netscape cookies file.")
    return parser.parse_args()


def run_download_stage(rows: list[dict[str, object]], csv_path: str, playlist_name: str, args: argparse.Namespace) -> None:
    ensure_ytdlp_installed()
    preflight_ytdlp_runtime_check()
    convert_audio = has_ffmpeg()
    if not convert_audio:
        print("INFO: ffmpeg/ffprobe introuvable -> telechargement audio sans conversion (pas de mp3 force).")

    row_dicts = rows_to_string_rows(rows)
    if ensure_download_status_field(row_dicts):
        save_rows(Path(csv_path), row_dicts)

    download_tracks(
        rows=row_dicts,
        csv_path=Path(csv_path),
        download_dir=args.download_dir,
        playlist_name=playlist_name,
        audio_format=args.audio_format,
        convert_audio=convert_audio,
        limit=args.limit,
        dry_run=args.dry_run,
        cookies_from_browser=args.cookies_from_browser.strip(),
        cookies_file=args.cookies.strip(),
    )


def main() -> None:
    args = parse_args()
    load_dotenv()
    client_id = get_env_or_exit("SPOTIFY_CLIENT_ID")
    client_secret = get_env_or_exit("SPOTIFY_CLIENT_SECRET")
    redirect_uri = get_env_or_exit("SPOTIFY_REDIRECT_URI")
    scope = os.getenv("SPOTIFY_SCOPE", DEFAULT_SCOPE).strip() or DEFAULT_SCOPE

    playlist_input = os.getenv("SPOTIFY_PLAYLIST_URL", "").strip()
    if not playlist_input:
        playlist_input = input("URL (ou ID) de la playlist Spotify: ").strip()
    if not playlist_input:
        print("Aucune URL/ID fourni.")
        sys.exit(1)

    playlist_id = extract_playlist_id(playlist_input)
    session = get_user_access_token(client_id, client_secret, redirect_uri, scope)
    playlist_name = run_diagnostics(playlist_id, session.access_token, scope, session.granted_scope)
    tracks = fetch_all_tracks(playlist_id, session.access_token)

    merge_result = merge_tracks_with_existing_csv(tracks, playlist_name)
    write_csv(merge_result.rows, merge_result.output_path)
    print(
        f"Mise a jour playlist '{playlist_name}': {merge_result.added_count} nouveau(x) titre(s) ajoute(s), "
        f"{merge_result.existing_count} titre(s) deja present(s)."
    )

    if args.no_download:
        return

    print("\nDemarrage du telechargement...")
    run_download_stage(merge_result.rows, merge_result.output_path, playlist_name, args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Erreur: {exc}")
        sys.exit(1)

