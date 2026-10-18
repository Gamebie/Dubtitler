"""Review-only checks; quiet gaps are never filled automatically."""
import re
from editor_operations import cue_warnings
from subtitle_format import parse_timestamp


def document_warnings(rows):
    warnings = [cue_warnings(row) for row in rows]
    timed = []
    for index, (a, b, text) in enumerate(rows):
        try:
            a, b = parse_timestamp(a), parse_timestamp(b)
            if b > a:
                timed.append((a, b, index, re.sub(r'\s+', ' ', text).strip().casefold()))
        except ValueError:
            pass
    active, last_text, furthest = [], {}, None
    for start, end, index, text in sorted(timed):
        active = [(stop, row) for stop, row in active if stop > start]
        for _, row in active:
            warnings[index].append(f'Overlaps row {row + 1}')
            warnings[row].append(f'Overlaps row {index + 1}')
        if furthest is not None and start - furthest >= 3000:
            warnings[index].append(f'Gap before cue: {(start - furthest) / 1000:.1f}s (may be intentional silence)')
        previous = last_text.get(text)
        if text and previous and start <= previous[0] + 500:
            warnings[index].append(f'Possible duplicate of row {previous[1] + 1}')
            warnings[previous[1]].append(f'Possible duplicate of row {index + 1}')
        if text:
            last_text[text] = (end, index)
        active.append((end, index))
        furthest = max(furthest or 0, end)
    return warnings
