"""CLI presentation helpers for consistent console output."""

from __future__ import annotations

TRAXX_BANNER = r"""
████████╗██████╗  █████╗ ██╗  ██╗██╗  ██╗
╚══██╔══╝██╔══██╗██╔══██╗╚██╗██╔╝╚██╗██╔╝
   ██║   ██████╔╝███████║ ╚███╔╝  ╚███╔╝
   ██║   ██╔══██╗██╔══██║ ██╔██╗  ██╔██╗
   ██║   ██║  ██║██║  ██║██╔╝ ██╗██╔╝ ██╗
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝
""".strip("\n")


def print_banner() -> None:
    print(TRAXX_BANNER)
    print("Spotify playlist sync and YouTube downloader")


def print_section(title: str) -> None:
    print(f"\n== {title} ==")


def print_info(message: str) -> None:
    print(f"[INFO] {message}")


def print_success(message: str) -> None:
    print(f"[OK] {message}")


def print_warning(message: str) -> None:
    print(f"[WARN] {message}")


def print_error(message: str) -> None:
    print(f"[ERROR] {message}")

