"""Runtime and process helpers for yt-dlp integration."""

from __future__ import annotations

import importlib.util
import io
import platform
import shutil
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import List, Optional

from ..cli import print_info, print_warning


def ensure_ytdlp_installed() -> None:
    if importlib.util.find_spec("yt_dlp") is None:
        raise RuntimeError(
            "yt-dlp is not available in this Python environment. Install it with "
            "'python -m pip install yt-dlp' and ensure ffmpeg is installed if you want mp3 conversion."
        )


def preflight_ytdlp_runtime_check() -> None:
    has_node = shutil.which("node") is not None
    has_deno = shutil.which("deno") is not None
    has_ejs = importlib.util.find_spec("yt_dlp_ejs") is not None
    if has_ejs and (has_node or has_deno):
        return
    print_warning("yt-dlp runtime is incomplete for some YouTube streams (signature/n challenge).")
    print_info("Recommended: install a JS runtime (node or deno) and optionally add yt_dlp_ejs.")


def build_js_runtimes() -> List[str]:
    runtimes: List[str] = []
    if shutil.which("node") is not None:
        runtimes.append("node")
    if shutil.which("deno") is not None:
        runtimes.append("deno")
    return runtimes


def detect_cookie_browser_candidates() -> List[str]:
    candidates = ["edge", "chrome", "firefox"]
    if platform.system().lower() == "darwin":
        candidates = ["safari", "chrome", "firefox", "edge"]
    elif platform.system().lower() == "linux":
        candidates = ["chrome", "chromium", "firefox", "brave"]
    return candidates


def is_signin_required_error(output: str) -> bool:
    lowered = output.lower()
    return "please sign in" in lowered or "use --cookies-from-browser or --cookies" in lowered


def is_js_challenge_error(output: str) -> bool:
    lowered = output.lower()
    return (
        "js challenge provider" in lowered
        or "signature solving failed" in lowered
        or "n challenge solving failed" in lowered
        or "only images are available for download" in lowered
    )


def remove_js_runtimes_args(cmd: List[str]) -> List[str]:
    cleaned: List[str] = []
    skip_next = False
    for token in cmd:
        if skip_next:
            skip_next = False
            continue
        if token == "--js-runtimes":
            skip_next = True
            continue
        cleaned.append(token)
    return cleaned


def remove_cookies_args(cmd: List[str]) -> List[str]:
    cleaned: List[str] = []
    skip_next = False
    for token in cmd:
        if skip_next:
            skip_next = False
            continue
        if token in {"--cookies-from-browser", "--cookies"}:
            skip_next = True
            continue
        cleaned.append(token)
    return cleaned


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def extract_ytdlp_argv(cmd: List[str]) -> Optional[List[str]]:
    if len(cmd) >= 3 and cmd[0] == sys.executable and cmd[1] == "-m" and cmd[2] == "yt_dlp":
        return cmd[3:]
    return None


def render_command_for_output(cmd: List[str]) -> str:
    ytdlp_argv = extract_ytdlp_argv(cmd)
    if ytdlp_argv is not None:
        return "yt_dlp " + " ".join(ytdlp_argv)
    return " ".join(cmd)


def run_ytdlp_command(cmd: List[str], dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        print("      " + render_command_for_output(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    ytdlp_argv = extract_ytdlp_argv(cmd)
    if getattr(sys, "frozen", False) and ytdlp_argv is not None:
        import yt_dlp

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        returncode = 0
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            try:
                result = yt_dlp.main(ytdlp_argv)
                if isinstance(result, int):
                    returncode = result
            except SystemExit as exc:
                returncode = exc.code if isinstance(exc.code, int) else 1
            except Exception:
                traceback.print_exc(file=stderr_buffer)
                returncode = 1
        return subprocess.CompletedProcess(cmd, returncode, stdout_buffer.getvalue(), stderr_buffer.getvalue())
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
            print_info("Browser cookie decryption failed with DPAPI. Retrying without browser cookies.")
            cmd_no_cookies = [c for c in cmd if c not in {"--cookies-from-browser", cookies_from_browser}]
            run = run_ytdlp_command(cmd_no_cookies, dry_run)
    if run.returncode != 0 and not cookies_from_browser and not cookies_file:
        output = (run.stderr.strip() or run.stdout.strip())
        if is_signin_required_error(output):
            for browser in cookie_browser_candidates:
                print_info(f"Retrying with browser cookies: {browser}")
                retry = run_ytdlp_command(cmd + ["--cookies-from-browser", browser], dry_run)
                if retry.returncode == 0:
                    return retry
                retry_output = (retry.stderr.strip() or retry.stdout.strip())
                if "Failed to decrypt with DPAPI" in retry_output:
                    continue
    return run

