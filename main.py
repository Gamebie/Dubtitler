import re
import sys
from pathlib import Path

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()

# Enter diagnostics before importing Qt so missing DLLs become a JSON failure,
# rather than a windowed bootloader error dialog that blocks CI.
if __name__ == '__main__' and '--smoke-test' in sys.argv:
    from portable_smoke import run
    sys.exit(run(sys.argv[sys.argv.index('--smoke-test') + 1:]))

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QLabel, QSlider,
    QMessageBox, QComboBox, QSplitter, QAbstractItemView, QProgressBar, QGroupBox, QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from model_runtime import DEFAULT_MODEL, bundled_model
from transcriber import Transcriber
from playback import PlaybackTools
from editing import EditingSafety


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


class MainWindow(PlaybackTools, EditingSafety, QMainWindow):
    def __init__(self, recovery_directory=None, offer_recovery=True):
        super().__init__()
        self.setWindowTitle('Dubtitler v0.3.0 — English Dub Subtitle Editor')
        self.resize(1200, 850)
        self.video_path = None
        self.busy = False
        self.worker = None
        self.cancel_pending = False
        self.job_terminal = False
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
        self.table.setMinimumHeight(150)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self.manual_seek)
        self.player.durationChanged.connect(lambda duration: self.seek.setRange(0, duration))
        self.player.positionChanged.connect(self.position_changed)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage(self.player.errorString()))
        self.table.itemSelectionChanged.connect(self.jump_to_selection)
        self.table.itemChanged.connect(self.editor_changed)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        choose = QGroupBox('1 · Choose a video')
        choose_layout = QVBoxLayout(choose)
        file_row = QHBoxLayout()
        choose_layout.addLayout(file_row)
        self.open_button = self.add_button(file_row, 'Choose Video…', self.open_video)
        self.video_label = QLabel('Start here: choose the video containing the English dub audio.')
        self.video_label.setWordWrap(True)
        file_row.addWidget(self.video_label, 1)
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
        self.cancel_button = self.add_button(bar, 'Cancel transcription', self.cancel_transcription)
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
        self.back_button = self.add_button(controls, '−5s', lambda: self.manual_seek(self.player.position()-5000))
        self.forward_button = self.add_button(controls, '+5s', lambda: self.manual_seek(self.player.position()+5000))
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
        split.setSizes([270, 330])
        self.setStyleSheet('QMainWindow,QWidget{background:#242733;color:#eaeaea;} QPushButton{background:#414a65;border:0;border-radius:5px;padding:8px;} QPushButton:hover{background:#576789;} QTableWidget{background:#20232e;alternate-background-color:#2b3040;gridline-color:#424858;} QHeaderView::section{background:#353b4e;color:white;padding:5px;} QComboBox{background:#353b4e;padding:5px;}')
        self.setStyleSheet(self.styleSheet() + ' QPushButton:disabled{background:#303441;color:#858a99;} QGroupBox{margin-top:12px;padding-top:8px;} QProgressBar{text-align:center;} QProgressBar::chunk{background:#526ea3;}')
        self.statusBar().showMessage('Ready')
        self.init_playback(choose_layout, controls)
        self.init_editing(row_controls, recovery_directory, offer_recovery)
        self.refresh_actions()

    def update_model_hint(self):
        name = self.model.currentData()
        if bundled_model(name):
            text = 'Ready offline: bundled model found. No account, internet or model download needed.'
        else:
            text = 'Uses a cached model if available. If missing, enable the one-time download below. The Offline ZIP includes Base English.'
        self.model_hint.setText(text + ' Choose the English dub in the audio-track selector above.')

    def refresh_actions(self):
        probing = self.track_probe is not None
        self.open_button.setEnabled(not self.busy and not probing)
        self.audio_tracks.setEnabled(self.audio_ready and not self.busy and not probing)
        self.model.setEnabled(not self.busy)
        self.allow_download.setEnabled(not self.busy)
        self.transcribe_button.setEnabled(bool(self.video_path) and self.audio_ready and not self.busy and not probing)
        self.cancel_button.setEnabled(self.busy and not self.cancel_pending and not self.job_terminal)
        for button in (self.import_button, self.add_row_button, self.delete_button):
            button.setEnabled(not self.busy)
        self.export_button.setEnabled((self.table.rowCount() > 0 or self.dirty) and not self.busy)
        self.table.setEnabled(not self.busy)
        self.undo_action.setEnabled(not self.busy and self.undo_stack.canUndo())
        self.redo_action.setEnabled(not self.busy and self.undo_stack.canRedo())
        for widget in (self.play_button, self.back_button, self.forward_button, self.seek):
            widget.setEnabled(bool(self.video_path) and not probing)
        self.replay_button.setEnabled(bool(self.video_path) and not probing and not self.busy and bool(self.table.selectedIndexes()) and self.player.duration() > 0)
        self.stop_replay_button.setEnabled(self.replay_range is not None)
        self.loop_replay.setEnabled(not self.busy)
        self.replay_context.setEnabled(not self.busy)

    def editor_changed(self, item):
        self.change_cells(self.raw_cells(), 'Edit subtitle', (item.row(), item.column()))

    def transcription_progress(self, message, value):
        if self.cancel_pending:
            return
        self.progress_label.setText(message)
        if value < 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat('Audio position: %p%')

    def transcription_finished(self):
        if self.cancel_pending:
            self.transcription_cancelled()
        self.busy = False
        self.cancel_pending = False
        self.refresh_actions()

    def cancel_transcription(self):
        if not self.busy or self.cancel_pending or self.job_terminal:
            return
        self.cancel_pending = True
        self.worker.cancel()
        self.progress_label.setText('Cancelling transcription… existing subtitles and recovery copies are kept.')
        self.progress_bar.setRange(0, 0)
        self.refresh_actions()

    def transcription_cancelled(self):
        self.job_terminal = True
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Cancelled')
        self.progress_label.setText('Transcription cancelled. Existing subtitles are unchanged. You can edit, export, or start again.')
        self.statusBar().showMessage('Transcription cancelled')

    def closeEvent(self, event):
        if self.busy or (self.worker is not None and self.worker.isRunning()):
            QMessageBox.information(self, 'Transcription in progress', 'Cancel transcription, then close once cancellation finishes.')
            event.ignore()
            return
        if self.track_probe is not None:
            QMessageBox.information(self, 'Reading audio tracks', 'Wait for the audio-track list to finish loading, then close.')
            event.ignore()
            return
        if not self.confirm_unsaved('close Dubtitler'):
            event.ignore()
            return
        self.finish_editing()
        self.stop_replay()
        self.player.stop()
        self.player.setSource(QUrl())
        super().closeEvent(event)

    def add_button(self, layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def open_video(self):
        if self.busy or self.track_probe is not None:
            return
        self.finish_cell_edit()
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a video with English audio', '', 'Video (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*)')
        if path:
            if self.table.rowCount():
                if self.dirty:
                    proceed = self.confirm_unsaved('choose another video and clear these subtitles')
                else:
                    proceed = QMessageBox.question(self, 'Choose another video?', 'Clear current subtitles and choose another video?') == QMessageBox.Yes
                if not proceed:
                    return
            elif not self.confirm_unsaved('choose another video'):
                return
            self.set_rows([], clean=True)
            self.srt_path = None
            self.load_video(path)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat('Ready to transcribe')
            self.progress_label.setText('Next: keep Base English for the bundled offline model, then click Transcribe English Dub.')
            self.refresh_actions()
            self.statusBar().showMessage(f'Opened {Path(path).name}')

    def toggle_play(self):
        self.stop_replay(pause=False)
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def set_rows(self, rows, clean=False):
        cells = tuple((timestamp(start), timestamp(end), text) for start, end, text in rows)
        self.undo_stack.clear()
        self._saved_rows = cells if clean else ()
        self.apply_cells(cells)

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
        row = len(self._last_rows)
        self.change_cells((*self._last_rows, (timestamp(pos), timestamp(pos + 2000), 'New subtitle')), 'Add subtitle', (row, 2))
        self.table.selectRow(row)

    def delete_row(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        self.change_cells([cells for index, cells in enumerate(self._last_rows) if index not in rows], 'Delete subtitles', (min(rows), 0) if rows else None)

    def jump_to_selection(self):
        self.stop_replay()
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            try:
                self.manual_seek(parse_timestamp(self.table.item(row, 0).text()))
            except ValueError:
                pass
        self.refresh_actions()

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
        self.finish_cell_edit()
        if not self.video_path or not self.audio_ready or self.track_probe is not None:
            QMessageBox.information(self, 'Choose video and audio', 'Choose a video, wait for its audio tracks, then select the English dub track.')
            return
        if self.dirty:
            if not self.confirm_unsaved('replace these subtitles with a new transcription'):
                return
        elif self.table.rowCount() and QMessageBox.question(self, 'Replace subtitles?', 'Transcription will replace current subtitles. Continue?') != QMessageBox.Yes:
            return
        self.busy = True
        self.cancel_pending = False
        self.job_terminal = False
        self.stop_replay()
        self.refresh_actions()
        self.transcription_progress('Starting transcription…', -1)
        self.statusBar().showMessage('Working locally. Loading and audio preparation have no percentage; transcription reports audio position.')
        self.worker = Transcriber(self.video_path, self.model.currentData(), self.allow_download.isChecked(), self.audio_tracks.currentData())
        self.worker.progress.connect(self.transcription_progress)
        self.worker.completed.connect(self.transcription_complete)
        self.worker.failed.connect(self.transcription_failed)
        self.worker.cancelled.connect(self.transcription_cancelled)
        self.worker.finished.connect(self.transcription_finished)
        self.worker.start()

    def transcription_complete(self, rows):
        if self.cancel_pending:
            return
        self.job_terminal = True
        self.cancel_button.setEnabled(False)
        self.change_cells([(timestamp(start), timestamp(end), text) for start, end, text in rows], 'Replace with transcription')
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat('Complete')
        self.progress_label.setText(f'Finished: {len(rows)} subtitles. Review and edit in step 3, then Export SRT.' if rows else 'Finished: no speech detected. Check that the video has an audible English track, or import an SRT.')
        self.statusBar().showMessage(f'Transcription finished: {len(rows)} subtitles')

    def transcription_failed(self, message):
        if self.cancel_pending:
            return
        self.job_terminal = True
        self.cancel_button.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Failed — retry available')
        self.progress_label.setText('Transcription failed. Existing subtitles are preserved. Check the model/connection or try another video, then retry.')
        QMessageBox.critical(self, 'Transcription failed', message)
        self.statusBar().showMessage('Transcription failed')

    def import_srt(self):
        self.finish_cell_edit()
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
            if not rows:
                raise ValueError('No subtitle cues found. Existing subtitles were kept.')
            if any(end <= start for start, end, _ in rows):
                raise ValueError('Subtitle end must be after start. Existing subtitles were kept.')
            if not self.confirm_unsaved('import another SRT and replace these subtitles'):
                return
            self.srt_path = path
            self.set_rows(rows, clean=True)
            self.statusBar().showMessage(f'Imported {len(rows)} subtitles')
        except Exception as exc:
            QMessageBox.warning(self, 'Import error', str(exc))

    def export_srt(self):
        self.finish_cell_edit()
        try:
            rows = self.get_rows()
            if not rows and not self.dirty:
                QMessageBox.information(self, 'Nothing to export', 'Create or import subtitles first.')
                return False
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid subtitle timing', str(exc))
            return False
        default_path = self.srt_path or (str(Path(self.video_path).with_suffix('.srt')) if self.video_path else 'subtitles.srt')
        path, _ = QFileDialog.getSaveFileName(self, 'Export subtitles', default_path, 'SubRip (*.srt)')
        if path:
            blocks = [f'{i}\n{timestamp(start)} --> {timestamp(end)}\n{text}' for i, (start, end, text) in enumerate(rows, 1)]
            try:
                from PySide6.QtCore import QSaveFile, QIODevice
                output = QSaveFile(path)
                if not output.open(QIODevice.WriteOnly):
                    raise OSError(output.errorString())
                content = ('\n\n'.join(blocks) + ('\n' if blocks else '')).encode('utf-8-sig')
                if output.write(content) != len(content):
                    output.cancelWriting()
                    raise OSError(output.errorString())
                if not output.commit():
                    raise OSError(output.errorString())
            except OSError as exc:
                QMessageBox.warning(self, 'Export error', str(exc))
                return False
            self.srt_path = path
            self.mark_saved()
            self.statusBar().showMessage(f'Exported {len(rows)} subtitles to {path}')
            return True
        return False


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
