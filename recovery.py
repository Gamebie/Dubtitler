"""Local recovery snapshots. These preserve raw cells, including invalid timings."""
import json
import os
import tempfile
from pathlib import Path


def recovery_directory():
    override = os.environ.get('DUBTITLER_RECOVERY_DIR')
    return Path(override) if override else Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'Dubtitler' / 'recovery'


def read_snapshot(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported recovery format')
    for key in ('rows', 'saved_rows'):
        rows = data.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != 3 or any(not isinstance(cell, str) for cell in row) for row in rows):
            raise ValueError('Invalid recovery subtitle cells')
    for key in ('video_path', 'srt_path'):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError('Invalid recovery file path')
    return data


def write_snapshot(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix=path.stem, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
