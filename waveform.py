"""Isolated audio-envelope decoding and an undo-friendly waveform editor."""
import math
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


def waveform_job(connection, path, model, download, index, options):
    try:
        from audio_tracks import decode_audio_track
        import numpy as np
        audio = decode_audio_track(path, index)
        step = max(320, math.ceil(len(audio) / 100000))
        peaks = [float(np.max(np.abs(audio[i:i + step]))) for i in range(0, len(audio), step)]
        connection.send(('completed', [round(len(audio) / 16), peaks]))
    except Exception as exc:
        connection.send(('failed', str(exc)))
    finally:
        connection.close()


class Waveform(QWidget):
    seek = Signal(int)
    boundary = Signal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(85)
        self.setMaximumHeight(110)
        self.setToolTip('Click to seek. Drag a selected cue’s start/end handle to change timing; Ctrl+Z undoes the drag. Use the zoom selector for a closer view.')
        self.duration = self.position = self.origin = 0
        self.span = 10000
        self.peaks, self.cues, self.selected = [], [], -1
        self.drag = None
        self.message = 'Waveform: choose a video and audio track'

    def set_audio(self, duration, peaks):
        self.duration, self.peaks = duration, peaks
        self.message = ''
        self.origin = min(self.origin, max(0, duration - self.span))
        self.update()

    def set_position(self, position):
        self.position = position
        if self.drag is None and not self.origin <= position < self.origin + self.span:
            self.origin = max(0, min(position - self.span // 4, self.duration - self.span))
        self.update()

    def set_span(self, span):
        self.span = span
        self.origin = max(0, min(self.position - span // 4, self.duration - span))
        self.update()

    def x(self, time):
        return (time - self.origin) * max(1, self.width()) / self.span

    def time(self, x):
        return max(0, min(self.duration, round(self.origin + x * self.span / max(1, self.width()))))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#171b26'))
        if not self.peaks or self.duration <= 0:
            p.setPen(QColor('#aeb9cf'))
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
            return
        p.setPen(QColor('#637fae'))
        for x in range(self.width()):
            begin = int((self.origin + x * self.span / self.width()) / self.duration * len(self.peaks))
            end = int((self.origin + (x + 1) * self.span / self.width()) / self.duration * len(self.peaks)) + 1
            peak = max(self.peaks[max(0, begin):max(0, end)], default=0)
            half = round(min(1, peak) * (self.height() - 30) / 2)
            p.drawLine(x, self.height() // 2 - half, x, self.height() // 2 + half)
        p.setPen(QColor('#aeb9cf'))
        p.drawText(5, 14, f'{self.origin / 1000:.1f}s — {min(self.duration, self.origin + self.span) / 1000:.1f}s')
        for index, (start, end) in enumerate(self.cues):
            if end < self.origin or start > self.origin + self.span:
                continue
            chosen = index == self.selected
            if self.drag and chosen:
                start, end = self.drag[2], self.drag[3]
            left, right = round(self.x(start)), round(self.x(end))
            p.fillRect(left, 22, max(1, right - left), self.height() - 26, QColor(220, 170, 75, 55) if chosen else QColor(90, 135, 190, 28))
            if chosen:
                p.setPen(QPen(QColor('#ffce7c'), 3))
                p.drawLine(left, 21, left, self.height() - 2)
                p.drawLine(right, 21, right, self.height() - 2)
        p.setPen(QPen(QColor('#f0f5ff'), 1))
        p.drawLine(round(self.x(self.position)), 0, round(self.x(self.position)), self.height())

    def mousePressEvent(self, event):
        if not self.isEnabled() or not self.peaks or event.button() != Qt.LeftButton:
            return
        if 0 <= self.selected < len(self.cues):
            start, end = self.cues[self.selected]
            for edge, time in ((0, start), (1, end)):
                if start >= 0 and end > start and abs(event.position().x() - self.x(time)) <= 7:
                    self.drag = (self.selected, edge, start, end)
                    return
        self.seek.emit(self.time(event.position().x()))

    def mouseMoveEvent(self, event):
        if self.drag:
            row, edge, start, end = self.drag
            time = self.time(event.position().x())
            if edge == 0:
                start = min(time, end - 1)
            else:
                end = max(time, start + 1)
            self.drag = row, edge, start, end
            self.update()

    def mouseReleaseEvent(self, event):
        if self.drag and event.button() == Qt.LeftButton:
            row, _, start, end = self.drag
            self.drag = None
            if self.isEnabled() and 0 <= start < end <= self.duration:
                self.boundary.emit(row, start, end)
            self.update()
