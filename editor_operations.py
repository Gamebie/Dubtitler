"""Atomic, text-preserving subtitle operations, independent of Qt."""
import re
from subtitle_format import parse_timestamp, timestamp


def find_pattern(needle, whole_words=True, case_sensitive=False):
    if not needle:
        raise ValueError('Enter text to find.')
    return re.compile((r'(?<!\w)' if whole_words else '') + re.escape(needle)
                      + (r'(?!\w)' if whole_words else ''), 0 if case_sensitive else re.IGNORECASE)


def replace_all(rows, needle, replacement, whole_words=True, case_sensitive=False):
    pattern = find_pattern(needle, whole_words, case_sensitive)
    result, count = [], 0
    for start, end, text in rows:
        text, matches = pattern.subn(lambda _: replacement, text)
        result.append((start, end, text))
        count += matches
    return result, count


def shift_rows(rows, indices, offset):
    result = list(rows)
    for index in indices:
        start, end, text = result[index]
        start, end = parse_timestamp(start), parse_timestamp(end)
        if end <= start or start + offset < 0:
            raise ValueError(f'Row {index + 1}: shift would create invalid or negative timing. Nothing was changed.')
        result[index] = (timestamp(start + offset), timestamp(end + offset), text)
    return result


def split_row(rows, index, position, text_offset):
    start, end, text = rows[index]
    begin, finish = parse_timestamp(start), parse_timestamp(end)
    if not begin < position < finish:
        raise ValueError('Place the playhead strictly inside the selected subtitle.')
    if not 0 < text_offset < len(text) or not text[:text_offset].strip() or not text[text_offset:].strip():
        raise ValueError('Place the text cursor between two non-empty parts of the dialogue.')
    # Preserve every character, including whitespace and line breaks.
    return [*rows[:index], (start, timestamp(position), text[:text_offset]),
            (timestamp(position), end, text[text_offset:]), *rows[index + 1:]]


def merge_rows(rows, indices):
    indices = sorted(indices)
    if len(indices) < 2 or indices != list(range(indices[0], indices[-1] + 1)):
        raise ValueError('Select two or more consecutive rows to merge.')
    selected = [rows[i] for i in indices]
    timings = [(parse_timestamp(start), parse_timestamp(end)) for start, end, _ in selected]
    if any(end <= start for start, end in timings):
        raise ValueError('Fix invalid timings before merging.')
    if any(timings[i][0] < timings[i - 1][0] for i in range(1, len(timings))):
        raise ValueError('Arrange the selected rows in timeline order before merging.')
    merged = (timestamp(min(s for s, _ in timings)), timestamp(max(e for _, e in timings)),
              '\n'.join(text for _, _, text in selected))
    return [*rows[:indices[0]], merged, *rows[indices[-1] + 1:]]


def cue_warnings(row):
    start, end, text = row
    try:
        duration = (parse_timestamp(end) - parse_timestamp(start)) / 1000
        if duration <= 0:
            raise ValueError()
    except ValueError:
        return ['Invalid timing']
    messages = []
    count = len(re.sub(r'\s+', '', text))
    if count and count / duration > 20:
        messages.append(f'Fast reading: {count / duration:.1f} characters/second (guide: 20)')
    if duration < .7 and text.strip():
        messages.append('Short display: under 0.7 seconds')
    if len(text.splitlines()) > 2:
        messages.append('More than two lines')
    if any(len(line) > 42 for line in text.splitlines()):
        messages.append('Long line: over 42 characters')
    return messages
