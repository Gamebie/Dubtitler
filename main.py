import re
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QLabel, QSlider,
    QMessageBox, QComboBox, QSplitter, QAbstractItemView)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget


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


class Transcriber(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, path, model_name):
        super().__init__()
        self.path = path
        self.model_name = model_name

    def run(self):
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(self.model_name, device='cpu', compute_type='int8')
            segments, _ = model.transcribe(self.path, language='en', vad_filter=True)
            rows = [(round(s.start * 1000), round(s.end * 1000), s.text.strip()) for s in segments]
            self.completed.emit(rows)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Dubtitler — English Dub Subtitle Editor')
        self.resize(1200, 760)
        self.video_path = None
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(0.8)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.caption = QLabel('Open a video to begin')
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setMinimumHeight(55)
        self.caption.setStyleSheet('background:#191c24;color:white;font-size:17px;padding:8px;')
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Start (HH:MM:SS,mmm)', 'End (HH:MM:SS,mmm)', 'Dialogue'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda duration: self.seek.setRange(0, duration))
        self.player.positionChanged.connect(self.position_changed)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage(self.player.errorString()))
        self.table.itemSelectionChanged.connect(self.jump_to_selection)
        self.table.itemChanged.connect(lambda *_: self.update_caption(self.player.position()))
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        bar = QHBoxLayout()
        outer.addLayout(bar)
        self.add_button(bar, 'Open Video', self.open_video)
        self.add_button(bar, 'Import SRT', self.import_srt)
        self.add_button(bar, 'Export SRT', self.export_srt)
        self.model = QComboBox()
        self.model.addItems(['tiny', 'base', 'small', 'medium'])
        self.model.setCurrentText('base')
        bar.addWidget(QLabel('AI model:'))
        bar.addWidget(self.model)
        self.transcribe_button = self.add_button(bar, 'Transcribe English Dub', self.transcribe)
        bar.addStretch()
        split = QSplitter(Qt.Vertical)
        outer.addWidget(split, 1)
        player_pane = QWidget()
        player_layout = QVBoxLayout(player_pane)
        player_layout.addWidget(self.video, 1)
        player_layout.addWidget(self.caption)
        player_layout.addWidget(self.seek)
        controls = QHBoxLayout()
        player_layout.addLayout(controls)
        self.add_button(controls, 'Play / Pause', self.toggle_play)
        self.add_button(controls, '−5s', lambda: self.player.setPosition(max(0, self.player.position()-5000)))
        self.add_button(controls, '+5s', lambda: self.player.setPosition(self.player.position()+5000))
        controls.addStretch()
        split.addWidget(player_pane)
        editor_pane = QWidget()
        editor_layout = QVBoxLayout(editor_pane)
        row_controls = QHBoxLayout()
        editor_layout.addLayout(row_controls)
        self.add_button(row_controls, 'Add Subtitle', self.add_row)
        self.add_button(row_controls, 'Delete Selected', self.delete_row)
        row_controls.addStretch()
        editor_layout.addWidget(self.table)
        split.addWidget(editor_pane)
        split.setSizes([410, 300])
        self.setStyleSheet('QMainWindow,QWidget{background:#242733;color:#eaeaea;} QPushButton{background:#414a65;border:0;border-radius:5px;padding:8px;} QPushButton:hover{background:#576789;} QTableWidget{background:#20232e;alternate-background-color:#2b3040;gridline-color:#424858;} QHeaderView::section{background:#353b4e;color:white;padding:5px;} QComboBox{background:#353b4e;padding:5px;}')
        self.statusBar().showMessage('Ready')

    def add_button(self, layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open anime video', '', 'Video (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*)')
        if path:
            self.video_path = path
            self.player.setSource(QUrl.fromLocalFile(path))
            self.statusBar().showMessage(f'Opened {Path(path).name}')

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def set_rows(self, rows):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for start, end, text in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate((timestamp(start), timestamp(end), text)):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.update_caption(self.player.position())

    def get_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text() if self.table.item(row, col) else '' for col in range(3)]
            start, end = parse_timestamp(values[0]), parse_timestamp(values[1])
            if end <= start:
                raise ValueError(f'Row {row + 1}: end must be after start')
            rows.append((start, end, values[2]))
        return sorted(rows, key=lambda entry: entry[0])

    def add_row(self):
        pos = self.player.position()
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((timestamp(pos), timestamp(pos + 2000), 'New subtitle')):
            self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.selectRow(row)

    def delete_row(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        self.update_caption(self.player.position())

    def jump_to_selection(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            try:
                self.player.setPosition(parse_timestamp(self.table.item(row, 0).text()))
            except ValueError:
                pass

    def position_changed(self, pos):
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.update_caption(pos)

    def update_caption(self, pos):
        for row in range(self.table.rowCount()):
            try:
                start = parse_timestamp(self.table.item(row, 0).text())
                end = parse_timestamp(self.table.item(row, 1).text())
                if start <= pos < end:
                    self.caption.setText(self.table.item(row, 2).text())
                    return
            except (ValueError, AttributeError):
                continue
        self.caption.setText('')

    def transcribe(self):
        if not self.video_path:
            QMessageBox.information(self, 'No video', 'Open a video first.')
            return
        if self.table.rowCount() and QMessageBox.question(self, 'Replace subtitles?', 'Transcription will replace current subtitles. Continue?') != QMessageBox.Yes:
            return
        self.transcribe_button.setEnabled(False)
        self.statusBar().showMessage('Transcribing locally… first run downloads the AI model.')
        self.worker = Transcriber(self.video_path, self.model.currentText())
        self.worker.completed.connect(self.transcription_complete)
        self.worker.failed.connect(self.transcription_failed)
        self.worker.finished.connect(lambda: self.transcribe_button.setEnabled(True))
        self.worker.start()

    def transcription_complete(self, rows):
        self.set_rows(rows)
        self.statusBar().showMessage(f'Transcription finished: {len(rows)} subtitles')

    def transcription_failed(self, message):
        QMessageBox.critical(self, 'Transcription failed', message)
        self.statusBar().showMessage('Transcription failed')

    def import_srt(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import subtitles', '', 'SubRip (*.srt)')
        if not path:
            return
        try:
            content = Path(path).read_text(encoding='utf-8-sig')
            rows = []
            for block in re.split(r'\n\s*\n', content.replace('\r\n', '\n').strip()):
                lines = block.splitlines()
                timing_idx = next((i for i, line in enumerate(lines) if '-->' in line), None)
                if timing_idx is None:
                    continue
                start, end = [part.strip() for part in lines[timing_idx].split('-->', 1)]
                rows.append((parse_timestamp(start), parse_timestamp(end), '\n'.join(lines[timing_idx+1:])))
            self.set_rows(rows)
            self.statusBar().showMessage(f'Imported {len(rows)} subtitles')
        except Exception as exc:
            QMessageBox.warning(self, 'Import error', str(exc))

    def export_srt(self):
        try:
            rows = self.get_rows()
            if not rows:
                QMessageBox.information(self, 'Nothing to export', 'Create or import subtitles first.')
                return
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid subtitle timing', str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export subtitles', str(Path(self.video_path).with_suffix('.srt')) if self.video_path else 'subtitles.srt', 'SubRip (*.srt)')
        if path:
            blocks = [f'{i}\n{timestamp(start)} --> {timestamp(end)}\n{text}' for i, (start, end, text) in enumerate(rows, 1)]
            Path(path).write_text('\n\n'.join(blocks) + '\n', encoding='utf-8-sig')
            self.statusBar().showMessage(f'Exported {len(rows)} subtitles to {path}')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
