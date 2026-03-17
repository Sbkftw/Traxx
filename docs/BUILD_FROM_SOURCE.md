# Build From Source

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` for audio conversion
- optional `node` or `deno` for some `yt-dlp` JavaScript challenges

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .[build]
```

Create `.env` from [`.env.example`](../.env.example) before running the CLI.

## Run From Source

```powershell
python traxx.py
python traxx.py --dry-run --limit 3
python traxx.py --no-download
```

## Build Windows Binary

```powershell
.\packaging\windows\build_windows.ps1
```

Output:

- `dist/traxx.exe`

## Notes

- The packaged executable looks for `.env` next to the executable first, then falls back to the current working directory.
- Browser cookies may still be required for sign-in-restricted YouTube videos.
- `yt_dlp_ejs` can be installed separately if additional `yt-dlp` fallback coverage is needed.
