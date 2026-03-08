"""Traxx core package.

This package contains the application logic split by responsibility:
- Spotify API/OAuth interactions
- CSV persistence and merge behavior
- YouTube download workflow
- CLI orchestration
"""

from .app import main

__all__ = ["main"]
