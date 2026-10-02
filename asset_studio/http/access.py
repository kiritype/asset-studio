"""Exact browser origins allowed to make mutating requests to Asset Studio."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

_ORIGIN = re.compile(r'https?://(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]{1,5})?\Z')


def _valid_origin(value):
    if not isinstance(value, str) or not _ORIGIN.fullmatch(value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            bool(parsed.hostname)
            and parsed.port != 0
            and not (
                parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            )
        )
    except ValueError:
        return False


def allowed_origin(root, origin, port):
    """Allow local origins and exact origins in data/settings/server_access.json.

    Requests without an Origin header retain support for local scripts and CLI clients.
    Invalid configuration entries are ignored, so they never broaden access.
    """
    if origin is None:
        return True
    if not _valid_origin(origin):
        return False
    if origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
        return True
    try:
        data = json.loads(
            (Path(root) / 'data' / 'settings' / 'server_access.json').read_text(encoding='utf-8')
        )
    except (OSError, ValueError):
        return False
    entries = data.get('allowed_origins') if isinstance(data, dict) else None
    return isinstance(entries, list) and any(
        _valid_origin(entry) and origin == entry for entry in entries
    )
