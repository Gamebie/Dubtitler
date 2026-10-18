"""Shared SRT timestamps and import validation."""
import re
from pathlib import Path


def timestamp(ms):
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f'{h:02}:{m:02}:{s:02},{milli:03}'


def parse_timestamp(value):
    match = re.fullmatch(r'\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*', value)
    if not match:
        raise ValueError('Use HH:MM:SS,mmm')
    h, m, s, milli = map(int, match.groups())
    if m >= 60 or s >= 60:
        raise ValueError('Minutes and seconds must be under 60')
    return ((h * 60 + m) * 60 + s) * 1000 + milli


def read_srt(path):
    content = Path(path).read_text(encoding='utf-8-sig')
    rows = []
    for block in re.split(r'\n\s*\n', content.replace('\r\n', '\n').strip()):
        lines = block.splitlines()
        timing_idx = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if timing_idx is None:
            continue
        start, end = [part.strip() for part in lines[timing_idx].split('-->', 1)]
        start, end = parse_timestamp(start), parse_timestamp(end)
        if end <= start:
            raise ValueError('Subtitle end must be after start. Existing subtitles were kept.')
        rows.append((start, end, '\n'.join(lines[timing_idx + 1:])))
    if not rows:
        raise ValueError('No subtitle cues found. Existing subtitles were kept.')
    return rows
