"""Validated project documents and local recent/export preferences."""
import json
import os
import tempfile
from pathlib import Path
from recovery import write_snapshot
from transcription_options import normalize_options
from subtitle_format import timestamp


def workspace_directory():
    return Path(os.environ.get('DUBTITLER_WORKSPACE_DIR', Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'Dubtitler' / 'workspace'))


def validate_project(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported Dubtitler project.')
    for key in ('rows', 'saved_rows'):
        rows = data.get(key)
        if not isinstance(rows, (list, tuple)) or any(not isinstance(row, (list, tuple)) or len(row) != 3 or any(not isinstance(cell, str) for cell in row) for row in rows):
            raise ValueError('Invalid project subtitle cells.')
    for key in ('video_path', 'srt_path', 'profile'):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError('Invalid project file or profile name.')
    for key in ('position', 'audio_index'):
        value = data.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('Invalid project position or audio track.')
    data = dict(data)
    data['options'] = normalize_options(data.get('options'), validate_replacements=False)
    if not isinstance(data.get('model', 'base.en'), str):
        raise ValueError('Invalid project model.')
    return data


def read_project(path):
    return validate_project(json.loads(Path(path).read_text(encoding='utf-8')))


def save_project(path, data):
    write_snapshot(path, validate_project(data))


def srt_bytes(rows):
    if any(type(start) is not int or type(end) is not int or start < 0 or end <= start or not isinstance(text, str) for start, end, text in rows):
        raise ValueError('Invalid subtitle timing or text.')
    return ('\n\n'.join(f'{i}\n{timestamp(a)} --> {timestamp(b)}\n{text}' for i, (a, b, text) in enumerate(rows, 1)) + ('\n' if rows else '')).encode('utf-8-sig')


def write_new_srt(directory, stem, rows):
    """Publish a complete file without replacing an existing destination."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(srt_bytes(rows))
            stream.flush()
            os.fsync(stream.fileno())
        for number in range(1, 10001):
            target = directory / (f'{stem}.srt' if number == 1 else f'{stem}_{number}.srt')
            try:
                if os.name == 'nt':
                    os.rename(temporary, target)  # Windows rename refuses an existing target.
                else:
                    os.link(temporary, target)
                    temporary.unlink()
                temporary = None
                return target
            except FileExistsError:
                continue
        raise OSError('Too many existing exports with this filename.')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
