import argparse
import csv
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_CSV_DIR = "output"
DEFAULT_DOWNLOAD_DIR = "downloads"


def sanitize_filename(value: str) -> str:
    cleaned = "".join("_" if c in '<>:"/\\|?*\x00' else c for c in value)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        return "track"
    return cleaned[:150]


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
    if shutil.which("yt-dlp") is None:
        raise RuntimeError(
            "yt-dlp est introuvable. Installe-le avec 'pip install yt-dlp' "
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


def run_ytdlp_command(cmd: List[str], dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        print("    " + " ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, capture_output=True, text=True)


def download_tracks(
    rows: List[Dict[str, str]],
    download_dir: str,
    audio_format: str,
    limit: Optional[int],
    dry_run: bool,
) -> None:
    os.makedirs(download_dir, exist_ok=True)
    errors = 0
    processed = 0

    for row in rows:
        if limit is not None and processed >= limit:
            break

        if not build_query(row):
            continue

        track_name = (row.get("track_name") or "").strip() or "track"
        artists = (row.get("artists") or "").strip() or "Unknown Artist"
        display_name = f"{track_name} - {artists}"
        safe_name = sanitize_filename(display_name)
        output_template = str(Path(download_dir) / f"{safe_name}.%(ext)s")

        processed += 1
        print(f"[{processed}] {display_name}")
        last_error = ""
        for candidate in build_query_candidates(row):
            cmd = [
                "yt-dlp",
                f"ytsearch3:{candidate}",
                "--no-playlist",
                "--no-overwrites",
                "--embed-metadata",
                "--no-update",
                "--extractor-args",
                "youtube:player_client=web",
                "-x",
                "--audio-format",
                audio_format,
                "--audio-quality",
                "0",
                "-o",
                output_template,
            ]

            run = run_ytdlp_command(cmd, dry_run)
            if run.returncode == 0:
                print("    OK")
                last_error = ""
                break

            output = (run.stderr.strip() or run.stdout.strip())
            last_error = output
            # Try a different query if DRM or extraction issues occur.
            if "DRM protected" in output or "Signature extraction failed" in output:
                continue
            # For other errors, stop trying variants for this track.
            break

        if last_error:
            errors += 1
            if (
                "Signature solving failed" in last_error
                or "n challenge solving failed" in last_error
            ):
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_ytdlp_installed()
    preflight_ytdlp_runtime_check()

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

    print(f"CSV source: {csv_path}")
    download_tracks(
        rows=rows,
        download_dir=args.download_dir,
        audio_format=args.audio_format,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Erreur: {exc}")
        sys.exit(1)
