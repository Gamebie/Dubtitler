"""Assemble readable cues from aligned words, speech regions, and speaker turns."""
import bisect
import math


class IntervalIndex:
    def __init__(self, intervals):
        self.intervals = sorted(intervals)
        self.starts = [entry[0] for entry in self.intervals]
        self.max_end = []
        furthest = -math.inf
        for entry in self.intervals:
            furthest = max(furthest, entry[1])
            self.max_end.append(furthest)

    def best(self, start, end):
        index = bisect.bisect_left(self.starts, end) - 1
        best, overlap = None, 0
        while index >= 0 and self.max_end[index] > start:
            entry = self.intervals[index]
            score = min(end, entry[1]) - max(start, entry[0])
            if score > overlap:
                best, overlap = entry, score
            index -= 1
        return best


def make_cues(segments, speech_regions, speaker_turns=()):
    speech = IntervalIndex((start, end, index) for index, (start, end) in enumerate(speech_regions))
    speakers = IntervalIndex(speaker_turns)
    rows, group = [], []

    def flush():
        if not group:
            return
        start, end = round(group[0][0] * 1000), round(group[-1][1] * 1000)
        text = ''.join(word[2] for word in group).strip()
        if rows:
            start = max(start, rows[-1][1])
        if text and end > start:
            rows.append((start, end, text))
        group.clear()

    for segment in segments:
        words = getattr(segment, 'words', None)
        if words is None:
            # A decoder without alignment cannot safely split its text at silence.
            # Keep its text only if the entire segment fits in one speech region.
            region = speech.best(segment.start, segment.end)
            if region and segment.start >= region[0] and segment.end <= region[1]:
                from types import SimpleNamespace
                words = [SimpleNamespace(start=segment.start, end=segment.end, word=segment.text)]
            else:
                words = []
        for word in words:
            start, end = word.start, word.end
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            region = speech.best(start, end)
            if region is None:
                flush()
                continue  # No subtitle for words hallucinated entirely in silence.
            start, end = max(start, region[0]), min(end, region[1])
            turn = speakers.best(start, end)
            speaker = turn[2] if turn else None
            if group:
                previous = group[-1]
                changed = speaker is not None and previous[4] is not None and speaker != previous[4]
                if (region[2] != previous[3] or start - previous[1] >= 0.35 or changed
                        or end - group[0][0] > 6 or sum(len(w[2]) for w in group) + len(word.word) > 84):
                    flush()
            group.append((start, end, word.word, region[2], speaker))
        flush()
    return rows
