import re
import sys
import math
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QLabel, QSlider,
    QMessageBox, QComboBox, QSplitter, QAbstractItemView, QProgressBar, QGroupBox, QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from model_runtime import DEFAULT_MODEL, bundled_model, load_model


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
    progress = Signal(str, int)  # -1 means no measurable total for this phase.

    def __init__(self, path, model_name, allow_download=False):
        super().__init__()
        self.path = path
        self.model_name = model_name
        self.allow_download = allow_download

    def run(self):
        try:
            model = load_model(self.model_name, self.progress.emit, self.allow_download)
            self.progress.emit('Preparing audio and detecting speech…', -1)
            segments, info = model.transcribe(self.path, language='en', vad_filter=True)
            duration = info.duration
            measured = duration > 0 and math.isfinite(duration)
            self.progress.emit('Transcribing English audio…', 0 if measured else -1)
            rows = []
            furthest = 0.0
            for segment in segments:
                rows.append((round(segment.start * 1000), round(segment.end * 1000), segment.text.strip()))
                # faster-whisper restores original media timestamps after VAD.
                # This measures audio position reached, never elapsed time or ETA.
                furthest = max(furthest, segment.end)
                percent = min(99, int(100 * furthest / duration)) if measured else -1
                detail = f'Audio position {furthest:.1f}s / {duration:.1f}s' if measured else f'{len(rows)} subtitles generated'
                self.progress.emit(f'Transcribing — {detail}', percent)
            self.progress.emit('Finishing subtitle list…', -1)
            self.completed.emit(rows)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Dubtitler v0.2 — English Dub Subtitle Editor')
        self.resize(1200, 850)
        self.video_path = None
        self.busy = False
        self.worker = None
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
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 180)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda duration: self.seek.setRange(0, duration))
        self.player.positionChanged.connect(self.position_changed)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage(self.player.errorString()))
        self.table.itemSelectionChanged.connect(self.jump_to_selection)
        self.table.itemChanged.connect(self.editor_changed)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        choose = QGroupBox('1 · Choose a video')
        choose_layout = QHBoxLayout(choose)
        self.open_button = self.add_button(choose_layout, 'Choose Video…', self.open_video)
        self.video_label = QLabel('Start here: choose the video containing the English dub audio.')
        self.video_label.setWordWrap(True)
        choose_layout.addWidget(self.video_label, 1)
        outer.addWidget(choose)
        transcribe_group = QGroupBox('2 · Choose a model and transcribe')
        transcribe_layout = QVBoxLayout(transcribe_group)
        bar = QHBoxLayout()
        transcribe_layout.addLayout(bar)
        self.model = QComboBox()
        for label, name in [('Base English — recommended / Offline ZIP', DEFAULT_MODEL),
                            ('Tiny — fastest', 'tiny'), ('Base — multilingual', 'base'),
                            ('Small — more accurate, slower', 'small'), ('Medium — slowest, more memory', 'medium')]:
            self.model.addItem(label, name)
        bar.addWidget(QLabel('AI model:'))
        bar.addWidget(self.model)
        self.transcribe_button = self.add_button(bar, 'Transcribe English Dub', self.transcribe)
        bar.addStretch()
        self.model_hint = QLabel()
        self.model_hint.setWordWrap(True)
        transcribe_layout.addWidget(self.model_hint)
        self.allow_download = QCheckBox('Allow a one-time download if this model is missing (internet required; reused from cache afterwards)')
        transcribe_layout.addWidget(self.allow_download)
        self.progress_label = QLabel('Choose a video in step 1 to enable transcription, or import an SRT in step 3.')
        self.progress_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Waiting for video')
        transcribe_layout.addWidget(self.progress_label)
        transcribe_layout.addWidget(self.progress_bar)
        outer.addWidget(transcribe_group)
        self.model.currentIndexChanged.connect(self.update_model_hint)
        self.update_model_hint()
        split = QSplitter(Qt.Vertical)
        outer.addWidget(split, 1)
        player_pane = QWidget()
        player_layout = QVBoxLayout(player_pane)
        player_layout.addWidget(self.video, 1)
        player_layout.addWidget(self.caption)
        player_layout.addWidget(self.seek)
        controls = QHBoxLayout()
        player_layout.addLayout(controls)
        self.play_button = self.add_button(controls, 'Play / Pause', self.toggle_play)
        self.back_button = self.add_button(controls, '−5s', lambda: self.player.setPosition(max(0, self.player.position()-5000)))
        self.forward_button = self.add_button(controls, '+5s', lambda: self.player.setPosition(self.player.position()+5000))
        controls.addStretch()
        split.addWidget(player_pane)
        editor_pane = QGroupBox('3 · Review, edit and export subtitles')
        editor_layout = QVBoxLayout(editor_pane)
        instructions = QLabel('Double-click a cell to edit text or timing (HH:MM:SS,mmm). Select a row to seek the video.\nReview the dialogue, then Export SRT and save it beside your video. You can also import an existing SRT.')
        instructions.setWordWrap(True)
        editor_layout.addWidget(instructions)
        row_controls = QHBoxLayout()
        editor_layout.addLayout(row_controls)
        self.import_button = self.add_button(row_controls, 'Import SRT…', self.import_srt)
        self.add_row_button = self.add_button(row_controls, 'Add Subtitle', self.add_row)
        self.delete_button = self.add_button(row_controls, 'Delete Selected', self.delete_row)
        row_controls.addStretch()
        self.export_button = self.add_button(row_controls, 'Export SRT…', self.export_srt)
        editor_layout.addWidget(self.table)
        split.addWidget(editor_pane)
        split.setSizes([410, 300])
        self.setStyleSheet('QMainWindow,QWidget{background:#242733;color:#eaeaea;} QPushButton{background:#414a65;border:0;border-radius:5px;padding:8px;} QPushButton:hover{background:#576789;} QTableWidget{background:#20232e;alternate-background-color:#2b3040;gridline-color:#424858;} QHeaderView::section{background:#353b4e;color:white;padding:5px;} QComboBox{background:#353b4e;padding:5px;}')
        self.setStyleSheet(self.styleSheet() + ' QPushButton:disabled{background:#303441;color:#858a99;} QGroupBox{margin-top:12px;padding-top:8px;} QProgressBar{text-align:center;} QProgressBar::chunk{background:#526ea3;}')
        self.statusBar().showMessage('Ready')
        self.refresh_actions()

    def update_model_hint(self):
        name = self.model.currentData()
        if bundled_model(name):
            text = 'Ready offline: bundled model found. No account, internet or model download needed.'
        else:
            text = 'Uses a cached model if available. If missing, enable the one-time download below. The Offline ZIP includes Base English.'
        self.model_hint.setText(text + ' Transcribes spoken English; choose the English audio track in your source video.')

    def refresh_actions(self):
        self.open_button.setEnabled(not self.busy)
        self.model.setEnabled(not self.busy)
        self.allow_download.setEnabled(not self.busy)
        self.transcribe_button.setEnabled(bool(self.video_path) and not self.busy)
        for button in (self.import_button, self.add_row_button, self.delete_button):
            button.setEnabled(not self.busy)
        self.export_button.setEnabled(self.table.rowCount() > 0 and not self.busy)
        self.table.setEnabled(not self.busy)
        for widget in (self.play_button, self.back_button, self.forward_button, self.seek):
            widget.setEnabled(bool(self.video_path))

    def editor_changed(self, *_):
        self.update_caption(self.player.position())
        self.refresh_actions()

    def transcription_progress(self, message, value):
        self.progress_label.setText(message)
        if value < 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat('Audio position: %p%')

    def transcription_finished(self):
        self.busy = False
        self.refresh_actions()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, 'Transcription in progress', 'Wait for transcription to finish before closing Dubtitler.')
            event.ignore()
            return
        super().closeEvent(event)

    def add_button(self, layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def open_video(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a video with English audio', '', 'Video (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*)')
        if path:
            if self.table.rowCount():
                if QMessageBox.question(self, 'Choose another video?', 'Current subtitles belong to the previous video. Clear them and continue? Export them first if needed.') != QMessageBox.Yes:
                    return
                self.set_rows([])
            self.video_path = path
            self.video_label.setText(Path(path).name)
            self.video_label.setToolTip(path)
            self.player.setSource(QUrl.fromLocalFile(path))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat('Ready to transcribe')
            self.progress_label.setText('Next: keep Base English for the bundled offline model, then click Transcribe English Dub.')
            self.refresh_actions()
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
        self.refresh_actions()

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
        self.refresh_actions()

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
        if self.busy:
            return
        if not self.video_path:
            QMessageBox.information(self, 'No video', 'Open a video first.')
            return
        if self.table.rowCount() and QMessageBox.question(self, 'Replace subtitles?', 'Transcription will replace current subtitles. Continue?') != QMessageBox.Yes:
            return
        self.busy = True
        self.refresh_actions()
        self.transcription_progress('Starting transcription…', -1)
        self.statusBar().showMessage('Working locally. Loading and audio preparation have no percentage; transcription reports audio position.')
        self.worker = Transcriber(self.video_path, self.model.currentData(), self.allow_download.isChecked())
        self.worker.progress.connect(self.transcription_progress)
        self.worker.completed.connect(self.transcription_complete)
        self.worker.failed.connect(self.transcription_failed)
        self.worker.finished.connect(self.transcription_finished)
        self.worker.start()

    def transcription_complete(self, rows):
        self.set_rows(rows)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat('Complete')
        self.progress_label.setText(f'Finished: {len(rows)} subtitles. Review and edit in step 3, then Export SRT.' if rows else 'Finished: no speech detected. Check that the video has an audible English track, or import an SRT.')
        self.statusBar().showMessage(f'Transcription finished: {len(rows)} subtitles')

    def transcription_failed(self, message):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Failed — retry available')
        self.progress_label.setText('Transcription failed. Existing subtitles are preserved. Check the model/connection or try another video, then retry.')
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
            try:
                Path(path).write_text('\n\n'.join(blocks) + '\n', encoding='utf-8-sig')
            except OSError as exc:
                QMessageBox.warning(self, 'Export error', str(exc))
                return
            self.statusBar().showMessage(f'Exported {len(rows)} subtitles to {path}')


if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        from portable_smoke import run
        sys.exit(run(sys.argv[sys.argv.index('--smoke-test') + 1:]))
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
