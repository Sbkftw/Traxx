"""Project-wide constants."""

from __future__ import annotations

from typing import Final

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
PLAYLIST_ITEMS_URL = "https://api.spotify.com/v1/playlists/{playlist_id}/items"
ME_URL = "https://api.spotify.com/v1/me"
PLAYLIST_URL = "https://api.spotify.com/v1/playlists/{playlist_id}"

DEFAULT_SCOPE = "playlist-read-private playlist-read-collaborative"
OUTPUT_DIR = "output"
DEFAULT_DOWNLOAD_DIR = "downloads"
DOWNLOAD_STATUS_FIELD = "downloaded"
YTSEARCH_MAX_RESULTS = 12

REQUEST_TIMEOUT_SECONDS: Final[int] = 20
LOCAL_CALLBACK_WAIT_SECONDS: Final[int] = 120
