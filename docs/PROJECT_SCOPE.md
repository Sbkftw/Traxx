# Traxx Project Scope Memo

Last updated: 2026-03-17
Source basis: repository snapshot in `c:\workspace\traxx`

## Purpose

Traxx is a local Python CLI that synchronizes a Spotify playlist into a persistent CSV snapshot and downloads pending tracks from YouTube via `yt-dlp`.

The core value proposition is incremental reuse:
- one CSV per Spotify playlist in `output/`
- one download status per track through the `downloaded` column
- safe re-runs over time as the Spotify playlist evolves

This is not a general media manager, web app, daemon, or library-first project. It is a task-oriented command-line workflow.

## Product Scope

Current supported flow:
1. Load Spotify credentials from `.env`
2. Resolve the playlist URL or ID from CLI, `.env`, or interactive prompt
3. Run Spotify OAuth for a user token
4. Fetch playlist metadata and all playlist tracks from Spotify Web API
5. Merge fetched tracks into an existing CSV or create a new one
6. Optionally download only tracks still marked `downloaded=no`
7. Mark successful downloads as `downloaded=yes` in the CSV

Current persistence model:
- CSV files in `output/<PlaylistName>.csv`
- downloaded files in `downloads/<PlaylistName>/`
- no database
- no cache layer besides CSV state

## Main User-Facing Behavior

- `python traxx.py` is the main entrypoint.
- The CLI can run in update-only mode with `--no-download`.
- The CLI can run in preview mode with `--dry-run`.
- Existing downloaded rows are skipped automatically.
- New Spotify tracks are detected by `track_id`, not by title/artist text.
- Backward compatibility exists for older CSV names formatted like `<playlist>-dd-mm.csv`.

Playlist input priority:
1. `--playlist-url`
2. positional playlist argument
3. `SPOTIFY_PLAYLIST_URL` from `.env`
4. interactive terminal prompt

## Architecture

Minimal module split, each with a narrow responsibility:

- `traxx.py`
  Thin executable entrypoint that calls `traxx_core.app.main`.

- `traxx_core/app.py`
  Application orchestration, env loading, CLI parsing, Spotify credential loading, CSV merge call, and download-stage handoff.

- `traxx_core/spotify.py`
  Spotify OAuth authorization-code flow, optional local callback HTTP server, Spotify API requests, playlist diagnostics, and playlist track pagination.

- `traxx_core/csv_store.py`
  Output path construction, existing CSV discovery, CSV loading, merge logic, and CSV writing.

- `traxx_core/downloader.py`
  Stable public downloader API used by the app layer.

- `traxx_core/downloading/`
  Internal downloader package split by concern:
  - `matching.py`: query building and candidate scoring
  - `runtime.py`: yt-dlp runtime/process helpers
  - `workflow.py`: end-to-end download orchestration and CSV updates

- `traxx_core/utils.py`
  Simple `.env` loader, filename sanitization, and `downloaded` normalization/parsing.

- `traxx_core/constants.py`
  Shared constants and default paths.

## Data Model

Spotify track rows are stored as flat dictionaries with these fields currently emitted by `fetch_all_tracks()`:
- `track_name`
- `artists`
- `album`
- `release_date`
- `duration_ms`
- `explicit`
- `popularity`
- `spotify_url`
- `track_id`
- `downloaded` (added during CSV merge / normalization)

Important identity rule:
- `track_id` is the deduplication key during CSV merge.

Important state rule:
- `downloaded=yes|no` is the operational state machine for the download stage.

## Download Selection Strategy

Traxx does not blindly download the first YouTube result.

Current strategy:
- build several search query variants from track title and artists
- search YouTube through `yt-dlp`
- enrich candidates with metadata when duration is missing
- score candidates on title similarity, artist token overlap, and duration proximity
- require a strict match before downloading
- otherwise keep the row as `downloaded=no`

This makes the tool conservative by design. False negatives are preferred over downloading the wrong audio.

## Runtime Dependencies

Direct Python dependencies from `requirements.txt`:
- `requests`
- `yt-dlp[ejs]`

External tools and optional helpers:
- `ffmpeg` and `ffprobe` for audio conversion to formats like mp3
- `node` or `deno` to improve `yt-dlp` JavaScript challenge handling
- browser cookies or Netscape cookie file for sign-in-restricted YouTube videos

Spotify requirements:
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`
- optional `SPOTIFY_SCOPE`
- optional `SPOTIFY_PLAYLIST_URL`

YouTube-related optional env vars:
- `YTDLP_COOKIES_FROM_BROWSER`
- `YTDLP_COOKIES_FILE`

## Not In Scope Today

Based on the current repository, Traxx does not currently provide:
- automated tests
- a GUI or web UI
- playlist diff reporting beyond console summary counts
- deletion handling when tracks are removed from Spotify
- retries/backoff for Spotify HTTP calls
- persistent OAuth token refresh/storage
- parallel downloads
- album art/library metadata management beyond what `yt-dlp` embeds
- support for services other than Spotify as source and YouTube as download backend

## Operational Constraints And Risks

- OAuth is interactive and user-driven. This is not suitable yet for unattended automation.
- `.env` loading is intentionally simple and always overrides existing env vars by default.
- The downloader relies on the evolving behavior of YouTube and `yt-dlp`; cookie and JS-runtime fallbacks are part of the current design because the platform is unstable.
- Strict candidate matching can leave valid tracks pending when metadata is weak or noisy.
- CSV is the only durable source of download state; corruption or manual edits can affect behavior.
- `write_csv()` skips file creation when there are no rows, so empty playlists are only reported in stdout.
- There is no explicit removal/archival policy for tracks no longer present in Spotify playlists.

## Code Quality And Maturity Signals

- The repo is small, focused, and currently clean (`git status` showed no uncommitted tracked changes at analysis time).
- The codebase has a clear separation of concerns and uses dataclasses and type hints in key areas.
- Documentation exists (`README.md`, `docs/CONTRIBUTING.md`) and broadly matches the implementation.
- Packaging concerns are now isolated under `packaging/`, which keeps the repo root more readable.
- There is no test suite yet; validation is manual plus `py_compile`.
- Recent commit history suggests active refinement after MVP:
  - `Fix overriding env variables`
  - `Candidate selection upgrade`
  - `Readability improvement + misc`
  - `MVP Delivered`

## Practical Mental Model For Future Sessions

When discussing Traxx in future sessions, assume this default framing:

Traxx is a Python CLI for incremental Spotify-playlist ingestion and selective YouTube audio download, with CSV as the persistent state layer and `yt-dlp` as the media backend.

If a future request concerns:
- playlist ingestion, OAuth, `.env`, CLI arguments: inspect `traxx_core/app.py` and `traxx_core/spotify.py`
- CSV persistence, merge semantics, `downloaded` state: inspect `traxx_core/csv_store.py`
- YouTube matching or download failures: inspect `traxx_core/downloader.py` and `traxx_core/downloading/`

## Recommended Next Improvements

Highest-leverage improvements if the project evolves:
- add automated tests for CSV merge behavior and candidate scoring
- separate pure selection/scoring logic from subprocess execution for easier testing
- add structured logging or verbose/debug modes
- define behavior for removed Spotify tracks
- add token refresh or session reuse if non-interactive flows become important
- add a lockfile and pinned toolchain guidance for reproducibility

## Session Reuse Note

If asked in a future session to remember the project scope, reread this file first:

- `docs/PROJECT_SCOPE.md`

This file is intended to be the compact project memory artifact for Traxx.

