"""Small helpers shared across the package."""

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Windows refuses to replace or open a file while another thread has it open; such
# clashes last milliseconds, so the operation is retried briefly before giving up.
SHARING_RETRIES = 50
SHARING_WAIT = 0.02


def replace_file(source, target):
    """``os.replace`` that waits out a reader holding ``target`` open."""
    for attempt in range(SHARING_RETRIES):
        try:
            return os.replace(source, target)
        except PermissionError:
            if attempt == SHARING_RETRIES - 1:
                raise
            time.sleep(SHARING_WAIT)


def read_text(path):
    """``Path.read_text`` that waits out a writer replacing the file."""
    for attempt in range(SHARING_RETRIES):
        try:
            return Path(path).read_text(encoding='utf-8')
        except PermissionError:
            if attempt == SHARING_RETRIES - 1:
                raise
            time.sleep(SHARING_WAIT)


def state_file(root, name):
    """Runtime state the server rewrites on its own (queue, review results)."""
    return Path(root) / 'data' / 'state' / name


def settings_file(root, name):
    """Connection and path settings of this machine."""
    return Path(root) / 'data' / 'settings' / name


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        replace_file(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def code(value):
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ValueError('올바르지 않은 코드입니다.')
    return value


def text(value):
    if isinstance(value, list):
        return ', '.join(str(v).strip() for v in value if str(v).strip())
    return str(value or '').strip()


def join(*values):
    return ', '.join(v for v in (text(x) for x in values) if v)
