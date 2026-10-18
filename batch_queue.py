"""Sequential isolated jobs; editor content and existing exports stay untouched."""
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem, QComboBox, QProgressBar)
from transcriber import Transcriber
from transcription_options import normalize_options
from project_store import write_new_srt


def batch_job(connection, path, model, download, index, options):
    if index == -1:
        try:
            from audio_tracks import list_audio_tracks, default_audio_track
            tracks = list_audio_tracks(path)
            english = [track for track in tracks if track['language'].lower().replace('_', '-').split('-')[0] in ('en', 'eng', 'english')]
            if not english:
                raise ValueError('No tagged English track. Choose an explicit audio track and retry this row.')
            index = default_audio_track(english)
        except Exception as exc:
            connection.send(('failed', str(exc)))
            connection.close()
            return
    from transcription_job import run_job
    run_job(connection, path, model, download, index, options)


class BatchDialog(QDialog):
    def __init__(self, window, worker_factory=Transcriber):
        super().__init__(window)
        self.window, self.worker_factory = window, worker_factory
        self.worker = None
        self.running = self.stopping = self.close_after = False
        self.current = -1
        self.job_rows = self.error = None
        self.paths, self.outputs = [], []
        self.setWindowTitle('Batch episodes — separate SRTs')
        self.resize(850, 500)
        layout = QVBoxLayout(self)
        info = QLabel('Queue videos with one show profile. Auto English requires a tagged English track; otherwise choose a track explicitly.\nJobs run one at a time. Existing SRTs get a new numbered filename; current editor subtitles are kept. Cancel keeps completed exports.')
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.add = QPushButton('Add videos…')
        self.remove = QPushButton('Remove selected')
        row.addWidget(self.add)
        row.addWidget(self.remove)
        row.addWidget(QLabel('Show profile:'))
        self.profile = QComboBox()
        self.profile.addItem('Current editor settings', None)
        for name in sorted(window.show_profiles, key=str.casefold):
            self.profile.addItem(name, name)
        row.addWidget(self.profile, 1)
        self.add.clicked.connect(self.add_videos)
        self.remove.clicked.connect(self.remove_selected)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Video', 'Audio track', 'Status / output'])
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 160)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        layout.addLayout(row)
        row.addWidget(QLabel('Output folder:'))
        self.directory = QLineEdit(window.preferences.get('export_folder', ''))
        row.addWidget(self.directory, 1)
        self.browse = QPushButton('Choose folder…')
        self.browse.clicked.connect(self.choose_directory)
        row.addWidget(self.browse)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.detail = QLabel('Add videos, choose an output folder, then Start queue.')
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.start = QPushButton('Start queue')
        self.cancel = QPushButton('Cancel queue')
        self.close_button = QPushButton('Close')
        self.start.clicked.connect(self.start_queue)
        self.cancel.clicked.connect(self.cancel_queue)
        self.close_button.clicked.connect(self.reject)
        for button in (self.start, self.cancel, self.close_button):
            row.addWidget(button)
        self.refresh()

    def add_paths(self, paths):
        if self.running:
            return
        for path in paths:
            path = str(Path(path).resolve())
            if path in self.paths:
                continue
            self.paths.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(Path(path).name)
            item.setToolTip(path)
            self.table.setItem(row, 0, item)
            tracks = QComboBox()
            tracks.addItem('Auto English', -1)
            for index in range(16):
                tracks.addItem(f'Track {index + 1}', index)
            self.table.setCellWidget(row, 1, tracks)
            self.table.setItem(row, 2, QTableWidgetItem('Queued'))
        self.refresh()

    def add_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Queue videos', '', 'Video (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv);;All files (*)')
        self.add_paths(paths)

    def remove_selected(self):
        if self.running:
            return
        for row in sorted({item.row() for item in self.table.selectedIndexes()}, reverse=True):
            del self.paths[row]
            self.table.removeRow(row)
        self.refresh()

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, 'Batch export folder', self.directory.text())
        if path:
            self.directory.setText(path)

    def status(self, row, message):
        self.table.item(row, 2).setText(message)
        self.table.item(row, 2).setToolTip(message)

    def refresh(self):
        for widget in (self.add, self.remove, self.profile, self.directory, self.browse):
            widget.setEnabled(not self.running)
        for row in range(self.table.rowCount()):
            self.table.cellWidget(row, 1).setEnabled(not self.running)
        self.start.setEnabled(not self.running and bool(self.paths))
        self.cancel.setEnabled(self.running and not self.stopping)

    def start_queue(self):
        if self.running or not self.paths:
            return
        try:
            folder = self.directory.text().strip()
            if not folder:
                raise ValueError('Choose an output folder first.')
            self.output_directory = Path(folder).resolve()
            self.output_directory.mkdir(parents=True, exist_ok=True)
            name = self.profile.currentData()
            self.options = normalize_options(self.window.profile_store.load()[name] if name else self.window.transcription_options())
            self.model = self.window.model.currentData()
            self.allow_download = self.window.allow_download.isChecked()
        except (OSError, ValueError, KeyError) as exc:
            self.detail.setText(str(exc))
            return
        self.pending = [row for row in range(len(self.paths)) if not self.table.item(row, 2).text().startswith('Exported:')]
        self.total = len(self.pending)
        if not self.pending:
            self.detail.setText('All queued videos already have an export. Add more videos to continue.')
            return
        self.processed = 0
        self.running, self.stopping = True, False
        self.window.preferences['export_folder'] = str(self.output_directory)
        self.window.save_preferences()
        self.refresh()
        self.next_job()

    def next_job(self):
        if self.stopping or not self.pending:
            self.running = False
            self.progress.setRange(0, 100)
            self.progress.setValue(0 if self.stopping else 100)
            self.detail.setText(f'Queue stopped. {self.processed}/{self.total} jobs finished; completed exports are kept.' if self.stopping else f'Queue finished: {self.processed}/{self.total} jobs processed. Review each SRT; see individual row results.')
            self.refresh()
            if self.close_after:
                self.accept()
            return
        self.current = self.pending.pop(0)
        self.job_rows = self.error = None
        self.status(self.current, 'Running')
        index = self.table.cellWidget(self.current, 1).currentData()
        self.worker = self.worker_factory(self.paths[self.current], self.model, self.allow_download, index, target=batch_job, options=self.options)
        self.worker.progress.connect(self.job_progress)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(lambda: self.failed('Cancelled'))
        self.worker.finished.connect(self.job_finished)
        self.worker.start()

    def job_progress(self, message, value):
        if self.stopping:
            return
        self.detail.setText(f'Job {self.processed + 1}/{self.total}: {Path(self.paths[self.current]).name} — {message}')
        self.progress.setRange(0, 0 if value < 0 else 100)
        if value >= 0:
            self.progress.setValue(value)
        self.progress.setFormat('Current job phase: %p%')

    def completed(self, rows):
        if not self.stopping:
            self.job_rows = rows

    def failed(self, message):
        self.error = message

    def job_finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        if self.stopping:
            self.status(self.current, 'Cancelled — no output applied')
        elif self.job_rows is not None:
            if not self.job_rows:
                self.status(self.current, 'No speech — no SRT created')
            else:
                try:
                    path = write_new_srt(self.output_directory, Path(self.paths[self.current]).stem, self.job_rows)
                    self.outputs.append(str(path))
                    self.status(self.current, f'Exported: {path}')
                except (OSError, ValueError) as exc:
                    self.status(self.current, f'Export failed: {exc}')
        else:
            self.status(self.current, f'Failed: {self.error or "No result received"}')
        self.processed += 1
        QTimer.singleShot(0, self.next_job)

    def cancel_queue(self):
        if not self.running or self.stopping:
            return
        self.stopping = True
        self.detail.setText('Stopping queue; existing editor subtitles and completed exports are kept…')
        if self.worker:
            self.worker.cancel()
        else:
            self.next_job()
        self.refresh()

    def reject(self):
        if self.running:
            self.close_after = True
            self.cancel_queue()
            return
        super().reject()

    def closeEvent(self, event):
        if self.running:
            self.close_after = True
            self.cancel_queue()
            event.ignore()
        else:
            super().closeEvent(event)
