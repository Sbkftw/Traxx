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

from .constants import AUTHORIZE_URL, ME_URL, PLAYLIST_ITEMS_URL, PLAYLIST_URL, TOKEN_URL


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
        raise RuntimeError(f"Authorization refusee par Spotify: {query['error'][0]}")
    if "code" not in query or not query["code"]:
        raise RuntimeError("Impossible de trouver le parametre 'code' dans l'URL de redirection.")
    return query["code"][0]


def try_get_code_via_local_callback(auth_url: str, redirect_uri: str, timeout_seconds: int = 120) -> Optional[str]:
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
                body = "Autorisation refusee. Retourne au terminal."
            elif "code" in query and query["code"]:
                result["code"] = query["code"][0]
                body = "Autorisation recue. Tu peux fermer cet onglet."
            else:
                body = "Parametre 'code' absent de la redirection."

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
        print("\nOuverture du navigateur pour autorisation Spotify...")
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
        raise RuntimeError(f"Authorization refusee par Spotify: {result['error']}")
    return result.get("code")


def parse_json_response(response: requests.Response) -> Dict[str, object]:
    try:
        return response.json()
    except json.JSONDecodeError:
        content_type = response.headers.get("Content-Type", "unknown")
        snippet = response.text[:300].strip() or "<empty body>"
        raise RuntimeError(
            f"Reponse non-JSON recue de Spotify (HTTP {response.status_code}, "
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


def get_user_access_token(client_id: str, client_secret: str, redirect_uri: str, scope: str) -> SpotifySession:
    auth_url = build_authorize_url(client_id, redirect_uri, scope)
    code = try_get_code_via_local_callback(auth_url, redirect_uri)
    if not code:
        print("\n1) Ouvre cette URL et autorise l'application:")
        print(auth_url)
        print("\n2) Apres redirection, copie-colle l'URL complete ici.")
        redirected_url = input("\nURL de redirection: ").strip()
        code = extract_code_from_redirect_url(redirected_url)

    creds = f"{client_id}:{client_secret}".encode("utf-8")
    encoded = base64.b64encode(creds).decode("utf-8")
    response = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {encoded}"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))
    data = parse_json_response(response)
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Le token d'acces est absent de la reponse Spotify.")
    return SpotifySession(access_token=str(access_token), granted_scope=str(data.get("scope", "")).strip())


def extract_playlist_id(value: str) -> str:
    match = re.search(r"playlist/([a-zA-Z0-9]+)", value)
    if match:
        return match.group(1)
    return value.strip()


def get_current_user(token: str) -> Dict[str, object]:
    response = requests.get(ME_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))
    return parse_json_response(response)


def check_playlist_access(playlist_id: str, token: str) -> Dict[str, object]:
    url = PLAYLIST_URL.format(playlist_id=playlist_id)
    response = requests.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))
    return parse_json_response(response)


def run_diagnostics(playlist_id: str, token: str, requested_scope: str, granted_scope: str) -> str:
    print("\n=== Diagnostic OAuth Spotify ===")
    print(f"Scopes demandes : {requested_scope}")
    print(f"Scopes accordes : {granted_scope or '<non retourne par Spotify>'}")
    user = get_current_user(token)
    print(f"Compte authentifie : {user.get('display_name') or '<sans nom>'} ({user.get('id', '<inconnu>')})")
    playlist = check_playlist_access(playlist_id, token)
    playlist_name = str(playlist.get("name") or "<sans nom>")
    owner = (playlist.get("owner") or {}).get("id", "<inconnu>")
    print(f"Playlist accessible : {playlist_name}")
    print(f"Owner: {owner} | Public: {playlist.get('public')} | Collaborative: {playlist.get('collaborative')}")
    print("=== Fin diagnostic ===\n")
    return playlist_name


def fetch_all_tracks(playlist_id: str, token: str) -> List[Dict[str, object]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    next_url = PLAYLIST_ITEMS_URL.format(playlist_id=playlist_id)
    params: Optional[Dict[str, object]] = {"limit": 100, "offset": 0, "additional_types": "track"}
    rows: List[Dict[str, object]] = []

    while next_url:
        response = requests.get(next_url, headers=headers, params=params, timeout=20)
        if response.status_code >= 400:
            message = spotify_error_message(response)
            if response.status_code == 403:
                message += f" | URL: {response.url}"
            raise RuntimeError(message)
        data = parse_json_response(response)
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

