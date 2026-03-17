"""Spotify OAuth and playlist retrieval."""

from __future__ import annotations

import base64
import http.server
import json
import re
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

from .cli import print_info, print_section
from .constants import (
    AUTHORIZE_URL,
    LOCAL_CALLBACK_WAIT_SECONDS,
    ME_URL,
    PLAYLIST_ITEMS_URL,
    PLAYLIST_URL,
    REQUEST_TIMEOUT_SECONDS,
    TOKEN_URL,
)


@dataclass(frozen=True)
class SpotifySession:
    """Authenticated Spotify session context."""

    access_token: str
    granted_scope: str


def build_authorize_url(client_id: str, redirect_uri: str, scope: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "show_dialog": "true",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def extract_code_from_redirect_url(redirected_url: str) -> str:
    parsed = urllib.parse.urlparse(redirected_url.strip())
    query = urllib.parse.parse_qs(parsed.query)
    if "error" in query:
        raise RuntimeError(f"Spotify authorization was denied: {query['error'][0]}")
    if "code" not in query or not query["code"]:
        raise RuntimeError("Could not find the 'code' parameter in the redirect URL.")
    return query["code"][0]


def try_get_code_via_local_callback(
    auth_url: str,
    redirect_uri: str,
    timeout_seconds: int = LOCAL_CALLBACK_WAIT_SECONDS,
) -> Optional[str]:
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    if parsed_redirect.scheme != "http":
        return None
    host = parsed_redirect.hostname
    if host not in {"127.0.0.1", "localhost"}:
        return None

    port = parsed_redirect.port or 80
    callback_path = parsed_redirect.path or "/"
    result: Dict[str, str] = {}
    done = threading.Event()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed_path = urllib.parse.urlparse(self.path)
            if parsed_path.path != callback_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                return

            query = urllib.parse.parse_qs(parsed_path.query)
            if "error" in query and query["error"]:
                result["error"] = query["error"][0]
                body = "Authorization denied. Return to the terminal."
            elif "code" in query and query["code"]:
                result["code"] = query["code"][0]
                body = "Authorization received. You can close this tab."
            else:
                body = "Missing 'code' parameter in redirect."

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            done.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    try:
        server = http.server.HTTPServer((host, port), CallbackHandler)
    except OSError:
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print_section("Spotify Authorization")
        print_info("Opening the browser for Spotify authorization.")
        print(auth_url)
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass
        if not done.wait(timeout_seconds):
            return None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    if "error" in result:
        raise RuntimeError(f"Spotify authorization was denied: {result['error']}")
    return result.get("code")


def parse_json_response(response: requests.Response) -> Dict[str, object]:
    try:
        return response.json()
    except json.JSONDecodeError:
        content_type = response.headers.get("Content-Type", "unknown")
        snippet = response.text[:300].strip() or "<empty body>"
        raise RuntimeError(
            f"Received a non-JSON response from Spotify (HTTP {response.status_code}, "
            f"Content-Type: {content_type}): {snippet}"
        ) from None


def spotify_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            status = error.get("status", response.status_code)
            if message:
                base = f"Spotify API error {status}: {message}"
                auth_hint = response.headers.get("WWW-Authenticate")
                if auth_hint:
                    base += f" | WWW-Authenticate: {auth_hint}"
                return base
        if isinstance(error, str):
            base = f"Spotify API error {response.status_code}: {error}"
            auth_hint = response.headers.get("WWW-Authenticate")
            if auth_hint:
                base += f" | WWW-Authenticate: {auth_hint}"
            return base
    except json.JSONDecodeError:
        pass

    snippet = response.text[:300].strip() or "<empty body>"
    base = f"Spotify API error {response.status_code}: {snippet}"
    auth_hint = response.headers.get("WWW-Authenticate")
    if auth_hint:
        base += f" | WWW-Authenticate: {auth_hint}"
    return base


def request_spotify_json(
    method: str,
    url: str,
    *,
    token: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Perform a Spotify API request and return a validated JSON payload."""

    request_headers: Dict[str, str] = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if token:
        request_headers["Authorization"] = f"Bearer {token}"

    response = requests.request(
        method=method,
        url=url,
        headers=request_headers,
        data=data,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))
    return parse_json_response(response)


def get_user_access_token(client_id: str, client_secret: str, redirect_uri: str, scope: str) -> SpotifySession:
    auth_url = build_authorize_url(client_id, redirect_uri, scope)
    code = try_get_code_via_local_callback(auth_url, redirect_uri)
    if not code:
        print_section("Spotify Authorization")
        print("1. Open this URL and authorize the application:")
        print(auth_url)
        print("\n2. After the redirect, paste the full redirect URL here.")
        redirected_url = input("\nRedirect URL: ").strip()
        code = extract_code_from_redirect_url(redirected_url)

    creds = f"{client_id}:{client_secret}".encode("utf-8")
    encoded = base64.b64encode(creds).decode("utf-8")
    data = request_spotify_json(
        "POST",
        TOKEN_URL,
        headers={"Authorization": f"Basic {encoded}"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
    )
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Spotify response did not include an access token.")
    return SpotifySession(access_token=str(access_token), granted_scope=str(data.get("scope", "")).strip())


def extract_playlist_id(value: str) -> str:
    match = re.search(r"playlist/([a-zA-Z0-9]+)", value)
    if match:
        return match.group(1)
    return value.strip()


def get_current_user(token: str) -> Dict[str, object]:
    return request_spotify_json("GET", ME_URL, token=token)


def check_playlist_access(playlist_id: str, token: str) -> Dict[str, object]:
    url = PLAYLIST_URL.format(playlist_id=playlist_id)
    return request_spotify_json("GET", url, token=token)


def run_diagnostics(playlist_id: str, token: str, requested_scope: str, granted_scope: str) -> str:
    print_section("Spotify Diagnostics")
    print(f"Requested scopes: {requested_scope}")
    print(f"Granted scopes: {granted_scope or '<not returned by Spotify>'}")
    user = get_current_user(token)
    print(f"Authenticated account: {user.get('display_name') or '<unnamed>'} ({user.get('id', '<unknown>')})")
    playlist = check_playlist_access(playlist_id, token)
    playlist_name = str(playlist.get("name") or "<unnamed>")
    owner = (playlist.get("owner") or {}).get("id", "<unknown>")
    print(f"Accessible playlist: {playlist_name}")
    print(f"Owner: {owner} | Public: {playlist.get('public')} | Collaborative: {playlist.get('collaborative')}")
    return playlist_name


def fetch_all_tracks(playlist_id: str, token: str) -> List[Dict[str, object]]:
    next_url = PLAYLIST_ITEMS_URL.format(playlist_id=playlist_id)
    params: Optional[Dict[str, object]] = {"limit": 100, "offset": 0, "additional_types": "track"}
    rows: List[Dict[str, object]] = []

    while next_url:
        try:
            data = request_spotify_json("GET", next_url, token=token, params=params)
        except RuntimeError as exc:
            # Keep original debugging hint: include URL for auth/scope 403 analysis.
            if "Spotify API error 403:" in str(exc):
                raise RuntimeError(f"{exc} | URL: {next_url}") from exc
            raise
        params = None

        for item in data.get("items", []):
            content = item.get("item")
            if not content or content.get("type") != "track":
                continue
            artists = ", ".join(artist.get("name", "") for artist in content.get("artists", []))
            album = content.get("album") or {}
            rows.append(
                {
                    "track_name": content.get("name"),
                    "artists": artists,
                    "album": album.get("name"),
                    "release_date": album.get("release_date"),
                    "duration_ms": content.get("duration_ms"),
                    "explicit": content.get("explicit"),
                    "popularity": content.get("popularity"),
                    "spotify_url": (content.get("external_urls") or {}).get("spotify"),
                    "track_id": content.get("id"),
                }
            )

        raw_next = data.get("next")
        next_url = str(raw_next) if raw_next else None

    return rows
