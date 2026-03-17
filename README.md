# Traxx

![Traxx banner](traxx-hero.svg)

Spotify playlist sync to CSV and selective YouTube audio download from a single CLI.

## Features

- Incremental playlist sync with one CSV per Spotify playlist.
- Persistent download state through the `downloaded` column.
- Strict YouTube candidate matching to reduce wrong downloads.
- Packaged Windows build support alongside source-based development.

## Install

### Package manager

```bash
python -m pip install .
traxx --help
```

### Release binary

```powershell
.\traxx.exe --help
```

Place `.env` next to `traxx.exe` for the packaged app.

### Build from source

```powershell
.\packaging\windows\build_windows.ps1
```

See [docs/BUILD_FROM_SOURCE.md](docs/BUILD_FROM_SOURCE.md) for source setup, packaging, and local build details.

## Configure

Create `.env` from [`.env.example`](.env.example):

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_PLAYLIST_URL=https://open.spotify.com/playlist/...
```

## Run

```bash
traxx
traxx --playlist-url "https://open.spotify.com/playlist/..."
traxx --dry-run --limit 3
```

## Project Layout

- `traxx.py`: thin executable entrypoint.
- `traxx_core/`: application logic.
- `traxx_core/downloading/`: internal downloader modules.
- `packaging/`: Windows build scripts, spec file, and icon assets.
- `docs/`: contribution and project-reference docs.

## Contributing

- Contribution guide: [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
- Build from source: [docs/BUILD_FROM_SOURCE.md](docs/BUILD_FROM_SOURCE.md)
- Project scope memo: [docs/PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md)
