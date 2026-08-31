"""Validation helpers for local files attached through the ChatGPT web UI."""
from __future__ import annotations

import os
from collections.abc import Iterable


def normalize_file_paths(paths: Iterable[str] | None) -> list[str]:
    """Return validated absolute file paths, preserving order and de-duplicating.

    Paths are interpreted on the machine running pro-bridge. Absolute paths are
    therefore strongly preferred for MCP callers. Relative paths are resolved
    against the bridge process working directory.
    """
    if not paths:
        return []

    normalized: list[str] = []
    seen: set[str] = set()

    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("each attachment path must be a non-empty string")

        path = os.path.abspath(os.path.expanduser(raw.strip()))
        if not os.path.exists(path):
            raise FileNotFoundError(f"attachment not found: {path}")
        if not os.path.isfile(path):
            raise ValueError(f"attachment is not a regular file: {path}")
        if path in seen:
            continue

        seen.add(path)
        normalized.append(path)

    return normalized
