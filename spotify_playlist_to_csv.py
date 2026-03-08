import base64
import csv
import http.server
import json
import os
import re
import sys
import threading
import urllib.parse
import webbrowser
from typing import Dict, List, Optional, Tuple

import requests


AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
PLAYLIST_ITEMS_URL = "https://api.spotify.com/v1/playlists/{playlist_id}/items"
ME_URL = "https://api.spotify.com/v1/me"
PLAYLIST_URL = "https://api.spotify.com/v1/playlists/{playlist_id}"
DEFAULT_SCOPE = "playlist-read-private playlist-read-collaborative"
OUTPUT_DIR = "output"
DOWNLOAD_STATUS_FIELD = "downloaded"


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as dotenv_file:
        for raw_line in dotenv_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_env_or_exit(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"Variable manquante: {name} (fichier .env)")
        sys.exit(1)
    return value


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
        error_value = query["error"][0]
        raise RuntimeError(f"Authorization refusee par Spotify: {error_value}")

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


def get_user_access_token(
    client_id: str, client_secret: str, redirect_uri: str, scope: str
) -> Tuple[str, str]:
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
    headers = {"Authorization": f"Basic {encoded}"}
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    response = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))

    data = parse_json_response(response)
    access_token = data.get("access_token")
    granted_scope = str(data.get("scope", "")).strip()
    if not access_token:
        raise RuntimeError("Le token d'acces est absent de la reponse Spotify.")

    return str(access_token), granted_scope


def extract_playlist_id(value: str) -> str:
    match = re.search(r"playlist/([a-zA-Z0-9]+)", value)
    if match:
        return match.group(1)
    return value.strip()


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


def fetch_all_tracks(playlist_id: str, token: str) -> List[Dict[str, object]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    next_url = PLAYLIST_ITEMS_URL.format(playlist_id=playlist_id)
    params: Optional[Dict[str, object]] = {
        "limit": 100,
        "offset": 0,
        "additional_types": "track",
    }
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
            if not content:
                continue
            if content.get("type") != "track":
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


def get_current_user(token: str) -> Dict[str, object]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    response = requests.get(ME_URL, headers=headers, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))
    return parse_json_response(response)


def check_playlist_access(playlist_id: str, token: str) -> Dict[str, object]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = PLAYLIST_URL.format(playlist_id=playlist_id)
    response = requests.get(url, headers=headers, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(spotify_error_message(response))
    return parse_json_response(response)


def run_diagnostics(playlist_id: str, token: str, requested_scope: str, granted_scope: str) -> str:
    print("\n=== Diagnostic OAuth Spotify ===")
    print(f"Scopes demandes : {requested_scope}")
    print(f"Scopes accordes : {granted_scope or '<non retourne par Spotify>'}")

    user = get_current_user(token)
    user_id = user.get("id", "<inconnu>")
    display_name = user.get("display_name") or "<sans nom>"
    print(f"Compte authentifie : {display_name} ({user_id})")

    playlist = check_playlist_access(playlist_id, token)
    playlist_name = playlist.get("name") or "<sans nom>"
    owner = (playlist.get("owner") or {}).get("id", "<inconnu>")
    is_public = playlist.get("public")
    collaborative = playlist.get("collaborative")
    print(f"Playlist accessible : {playlist_name}")
    print(f"Owner: {owner} | Public: {is_public} | Collaborative: {collaborative}")
    print("=== Fin diagnostic ===\n")
    return str(playlist_name)


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value).strip(" .")
    return cleaned or "playlist"


def build_output_path(playlist_name: str) -> str:
    safe_playlist_name = sanitize_filename(playlist_name)
    filename = f"{safe_playlist_name}.csv"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return os.path.join(OUTPUT_DIR, filename)


def parse_downloaded_value(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "ok", "done"}


def normalize_downloaded_value(value: object) -> str:
    return "yes" if parse_downloaded_value(value) else "no"


def find_latest_playlist_csv(playlist_name: str) -> Optional[str]:
    if not os.path.isdir(OUTPUT_DIR):
        return None

    safe_playlist_name = sanitize_filename(playlist_name)
    current_name = f"{safe_playlist_name}.csv"
    current_path = os.path.join(OUTPUT_DIR, current_name)
    if os.path.exists(current_path):
        return current_path

    # Compatibilite avec les anciens fichiers "<playlist>-dd-mm.csv".
    pattern = re.compile(rf"^{re.escape(safe_playlist_name)}-\d{{2}}-\d{{2}}\.csv$", re.IGNORECASE)
    candidates: List[str] = []
    for filename in os.listdir(OUTPUT_DIR):
        if pattern.match(filename):
            candidates.append(os.path.join(OUTPUT_DIR, filename))

    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def load_existing_rows(csv_path: str) -> List[Dict[str, object]]:
    existing_rows: List[Dict[str, object]] = []
    if not os.path.exists(csv_path):
        return existing_rows

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            cleaned_row: Dict[str, object] = {}
            for key, value in row.items():
                cleaned_key = str(key or "").replace("\ufeff", "").strip()
                cleaned_row[cleaned_key] = value if value is not None else ""
            cleaned_row[DOWNLOAD_STATUS_FIELD] = normalize_downloaded_value(cleaned_row.get(DOWNLOAD_STATUS_FIELD, ""))
            existing_rows.append(cleaned_row)
    return existing_rows


def merge_tracks_with_existing_csv(
    rows: List[Dict[str, object]], playlist_name: str
) -> Tuple[List[Dict[str, object]], int, int]:
    previous_csv = find_latest_playlist_csv(playlist_name)
    if not previous_csv:
        merged_rows = []
        for row in rows:
            normalized_row = dict(row)
            normalized_row[DOWNLOAD_STATUS_FIELD] = "no"
            merged_rows.append(normalized_row)
        return merged_rows, len(merged_rows), 0

    existing_rows = load_existing_rows(previous_csv)
    existing_track_ids = {
        str(row.get("track_id", "")).strip()
        for row in existing_rows
        if str(row.get("track_id", "")).strip()
    }
    added_count = 0
    for row in rows:
        track_id = str(row.get("track_id", "")).strip()
        if not track_id or track_id in existing_track_ids:
            continue
        normalized_row = dict(row)
        normalized_row[DOWNLOAD_STATUS_FIELD] = "no"
        existing_rows.append(normalized_row)
        existing_track_ids.add(track_id)
        added_count += 1

    return existing_rows, added_count, len(existing_track_ids)


def write_csv(rows: List[Dict[str, object]], output_path: str) -> None:
    if not rows:
        print("Aucun titre trouve dans cette playlist.")
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV genere: {output_path} ({len(rows)} titres)")


def main() -> None:
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
    token, granted_scope = get_user_access_token(client_id, client_secret, redirect_uri, scope)
    playlist_name = run_diagnostics(playlist_id, token, scope, granted_scope)
    tracks = fetch_all_tracks(playlist_id, token)
    merged_rows, added_count, known_count = merge_tracks_with_existing_csv(tracks, playlist_name)
    write_csv(merged_rows, build_output_path(playlist_name))
    print(
        f"Mise a jour playlist '{playlist_name}': {added_count} nouveau(x) titre(s) ajoute(s), "
        f"{known_count} titre(s) deja present(s)."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Erreur: {exc}")
        sys.exit(1)
