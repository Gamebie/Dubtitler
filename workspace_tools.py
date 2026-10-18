"""Autosaved projects, navigation, selected-track waveforms and export preferences."""
from pathlib import Path
from uuid import uuid4
import json
from PySide6.QtCore import QTimer, QUrl, QLockFile
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMessageBox, QHBoxLayout, QLabel, QComboBox
from project_store import workspace_directory, read_project, save_project
from recovery import write_snapshot
from subtitle_format import parse_timestamp, timestamp
from waveform import Waveform, waveform_job
from transcriber import Transcriber
from PySide6.QtMultimedia import QMediaPlayer


class WorkspaceTools:
    def init_workspace(self, player_layout, directory=None):
        self.workspace = Path(directory) if directory is not None else workspace_directory()
        self.project_path = None
        self.project_lock = None
        self.project_loading = False
        self.project_restore_position = None
        self.project_save_error = None
        self.wave_worker = None
        self.wave_request = None
        self.wave_pending = None
        self.preferences = self.read_preferences()
        self.project_timer = QTimer(self)
        self.project_timer.setSingleShot(True)
        self.project_timer.timeout.connect(self.autosave_project)
        self.project_status = QLabel('Project: not started')
        self.statusBar().addPermanentWidget(self.project_status)
        menu = self.menuBar().addMenu('File')
        self.workspace_actions = []
        for label, shortcut, callback in (
            ('Open project…', 'Ctrl+O', self.open_project),
            ('Save project…', 'Ctrl+S', self.save_project_as),
            ('Relink project video…', '', self.relink_video),
            ('Batch episodes…', 'Ctrl+B', self.open_batch),
        ):
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            menu.addAction(action)
            self.workspace_actions.append(action)
        self.recent_menu = menu.addMenu('Recent projects')
        self.rebuild_recents()
        navigation = self.menuBar().addMenu('Navigate')
        self.navigation_actions = []
        for label, shortcut, callback in (
            ('Previous cue', 'Ctrl+Up', lambda: self.navigate_cue(-1)),
            ('Next cue', 'Ctrl+Down', lambda: self.navigate_cue(1)),
            ('Edit current dialogue', 'Ctrl+E', lambda: self.navigate_cue(0, edit=True)),
            ('Edit previous dialogue', 'Alt+Up', lambda: self.navigate_cue(-1, edit=True)),
            ('Edit next dialogue', 'Alt+Down', lambda: self.navigate_cue(1, edit=True)),
            ('Replay current cue', 'F6', self.replay_selected),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            navigation.addAction(action)
            self.navigation_actions.append(action)
        self.waveform = Waveform(self)
        self.waveform.seek.connect(self.manual_seek)
        self.waveform.boundary.connect(self.waveform_boundary)
        player_layout.insertWidget(2, self.waveform)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('Waveform zoom:'))
        self.wave_zoom = QComboBox()
        for seconds in (5, 10, 30, 60, 120):
            self.wave_zoom.addItem(f'{seconds} seconds', seconds * 1000)
        self.wave_zoom.setCurrentIndex(1)
        self.wave_zoom.currentIndexChanged.connect(lambda _: self.waveform.set_span(self.wave_zoom.currentData()))
        tools.addWidget(self.wave_zoom)
        tools.addWidget(QLabel('Click to seek · drag gold cue edges · Ctrl+↑/↓ changes cue'), 1)
        player_layout.insertLayout(3, tools)
        self.player.durationChanged.connect(self.restore_project_position)
        self.player.seekableChanged.connect(self.restore_project_position)
        self.player.mediaStatusChanged.connect(self.restore_project_position)
        self.batch_dialog = None
        for widget in (self.show_context, self.name_hints, self.exact_replacements):
            widget.textChanged.connect(self.schedule_project_save)
        self.speaker_changes.toggled.connect(self.schedule_project_save)
        self.model.currentIndexChanged.connect(self.schedule_project_save)

    def read_preferences(self):
        try:
            data = json.loads((self.workspace / 'preferences.json').read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError()
            return {'recent': [p for p in data.get('recent', []) if isinstance(p, str)][:12],
                    'export_folder': data.get('export_folder', '') if isinstance(data.get('export_folder', ''), str) else '',
                    'export_names': data.get('export_names', {}) if isinstance(data.get('export_names', {}), dict) else {}}
        except (OSError, ValueError, TypeError):
            return {'recent': [], 'export_folder': '', 'export_names': {}}

    def save_preferences(self):
        try:
            write_snapshot(self.workspace / 'preferences.json', self.preferences)
        except OSError as exc:
            self.statusBar().showMessage(f'Could not remember recent/export settings: {exc}')

    def rebuild_recents(self):
        self.recent_menu.clear()
        for path in self.preferences['recent']:
            label = Path(path).stem
            try:
                data = read_project(path)
                if Path(path).parent == self.workspace / 'projects':
                    label = Path(data.get('video_path') or data.get('srt_path') or 'Subtitle session').name
            except (OSError, ValueError):
                label += ' (unavailable)'
            action = self.recent_menu.addAction(label)
            action.setToolTip(path)
            action.triggered.connect(lambda _, path=path: self.open_project(path))
        self.recent_menu.setEnabled(bool(self.preferences['recent']))

    def remember_project(self):
        path = str(Path(self.project_path).resolve())
        self.preferences['recent'] = [path, *[p for p in self.preferences['recent'] if p != path]][:12]
        self.save_preferences()
        self.rebuild_recents()

    def project_data(self):
        return {'version': 1, 'rows': self.raw_cells(), 'saved_rows': self._saved_rows,
                'video_path': self.video_path, 'srt_path': self.srt_path,
                'audio_index': self.audio_tracks.currentData() if self.audio_tracks.currentData() is not None else self.preferred_audio_index,
                'position': self.project_restore_position if self.project_restore_position is not None else self.player.position(),
                'options': self.transcription_options(validate_replacements=False),
                'profile': self.context_preset.currentData(), 'model': self.model.currentData()}

    def schedule_project_save(self, *_):
        if hasattr(self, 'project_timer') and self.project_path and not self.project_loading:
            self.project_timer.start(750)
            if not self.project_save_error:
                self.project_status.setText('Project: saving…')

    def autosave_project(self):
        if not self.project_path or self.project_loading:
            return True
        try:
            if self.project_lock is None:
                self.adopt_project(self.project_path)
            save_project(self.project_path, self.project_data())
            self.project_save_error = None
            self.project_timer.stop()
            self.project_status.setText('Project: autosaved')
            self.project_status.setToolTip(str(self.project_path))
            return True
        except (OSError, ValueError) as exc:
            self.project_save_error = str(exc)
            self.project_status.setText('Project: SAVE FAILED')
            self.project_status.setToolTip(str(exc))
            self.statusBar().showMessage(f'Project autosave failed: {exc}. Export SRT or Save project to another location.')
            return False

    def flush_project(self):
        if not hasattr(self, 'project_path') or not self.project_path:
            return True
        self.finish_cell_edit()
        if self.autosave_project():
            return True
        QMessageBox.warning(self, 'Project not saved', self.project_save_error)
        return False

    def adopt_project(self, path, validate=False):
        path = Path(path).resolve()
        if self.project_path and Path(self.project_path).resolve() == path and self.project_lock is not None:
            return read_project(path) if validate else None
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(path) + '.lock')
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise OSError('This project is already open in another window. Close it there before opening it here.')
        data = read_project(path) if validate else None
        if self.project_lock:
            self.project_lock.unlock()
        self.project_path, self.project_lock = path, lock
        return data

    def release_project(self):
        if self.project_lock:
            self.project_lock.unlock()
        self.project_lock = None

    def begin_project_session(self):
        self.release_project()
        self.project_path = self.workspace / 'projects' / f'{uuid4().hex}.dubtitler'
        self.schedule_project_save()

    def save_project_as(self):
        if self.busy or self.track_probe is not None:
            return
        self.finish_cell_edit()
        default = str(self.project_path) if self.project_path else str(self.workspace / 'projects' / 'My subtitles.dubtitler')
        path, _ = QFileDialog.getSaveFileName(self, 'Save Dubtitler project', default, 'Dubtitler project (*.dubtitler)', options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        if not Path(path).suffix:
            path += '.dubtitler'
        if Path(path).suffix.lower() != '.dubtitler' or any(source and Path(path).resolve() == Path(source).resolve() for source in (self.video_path, self.srt_path)):
            QMessageBox.warning(self, 'Choose a project filename', 'Save projects with a .dubtitler filename, separate from the video and SRT.')
            return
        if Path(path).exists() and QMessageBox.question(self, 'Replace project?', f'Replace the project at {path}?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        temporary_lock = None
        try:
            target = Path(path).resolve()
            if not self.project_path or target != Path(self.project_path).resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary_lock = QLockFile(str(target) + '.lock')
                temporary_lock.setStaleLockTime(0)
                if not temporary_lock.tryLock(0):
                    raise OSError('That project is already open in another window.')
            save_project(target, self.project_data())
            if temporary_lock:
                self.release_project()
                self.project_lock = temporary_lock
            self.project_path = target
            self.remember_project()
            self.statusBar().showMessage(f'Project saved: {path}. SRT export status is unchanged.')
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Project not saved', str(exc))
        finally:
            if temporary_lock is not None and self.project_lock is not temporary_lock:
                temporary_lock.unlock()

    def open_project(self, path=None):
        if self.busy or self.track_probe is not None:
            return False
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Open Dubtitler project', str(self.workspace / 'projects'), 'Dubtitler project (*.dubtitler)')
        if not path:
            return False
        try:
            data = read_project(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Project not opened', str(exc))
            return False
        if not self.flush_project() or not self.confirm_unsaved('open another project'):
            return False
        if not self.flush_project():
            return False
        try:
            data = self.adopt_project(path, validate=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Project not opened', str(exc))
            return False
        self.project_loading = True
        try:
            self.stop_replay()
            self.srt_path = data.get('srt_path')
            self.restore_transcription_options(data['options'])
            profile = data.get('profile')
            if profile and self.context_preset.findData(profile) >= 0:
                self.context_preset.setCurrentIndex(self.context_preset.findData(profile))
            model = self.model.findData(data.get('model', 'base.en'))
            if model >= 0:
                self.model.setCurrentIndex(model)
            self.undo_stack.clear()
            self._saved_rows = tuple(tuple(row) for row in data['saved_rows'])
            self.apply_cells(data['rows'])
            video = data.get('video_path')
            self.project_restore_position = data.get('position', 0) or 0
            if video and Path(video).is_file():
                self.load_video(video, data.get('audio_index'))
            else:
                self.video_path = video
                self.player.setSource(QUrl())
                self.audio_ready = False
                self.audio_track_list = []
                self.audio_tracks.blockSignals(True)
                self.audio_tracks.clear()
                index = data.get('audio_index')
                self.audio_tracks.addItem(f'Saved audio track {index + 1}' if index is not None else 'No video audio loaded', index)
                self.audio_tracks.blockSignals(False)
                self.request_waveform(None)
                self.video_label.setText('Project opened; video missing. File → Relink project video…' if video else 'Project contains subtitles only')
                self.refresh_actions()
        finally:
            self.project_loading = False
        self.remember_project()
        self.project_status.setText('Project: opened')
        self.project_status.setToolTip(str(self.project_path))
        self.statusBar().showMessage('Project opened. Subtitle text, saved export baseline and show settings restored; undo history starts here.')
        return True

    def relink_video(self):
        if self.busy or self.track_probe is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Relink video without clearing subtitles', '', 'Video (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*)')
        if path:
            self.load_video(path, self.audio_tracks.currentData())
            self.schedule_project_save()

    def restore_project_position(self, *_):
        duration = self.player.duration()
        if (self.project_restore_position is not None and duration > 0 and self.player.isSeekable()
                and self.player.mediaStatus() in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia, QMediaPlayer.EndOfMedia)):
            position = min(self.project_restore_position, duration)
            self.project_restore_position = None
            self.player.setPosition(position)

    def export_default(self):
        key = str(Path(self.video_path).resolve()) if self.video_path else str(self.project_path or 'srt-session')
        remembered = self.preferences['export_names'].get(key)
        if isinstance(remembered, str):
            return remembered
        name = Path(self.video_path).with_suffix('.srt').name if self.video_path else 'subtitles.srt'
        return str(Path(self.preferences['export_folder']) / name) if self.preferences['export_folder'] else (str(Path(self.video_path).with_suffix('.srt')) if self.video_path else name)

    def remember_export(self, path):
        key = str(Path(self.video_path).resolve()) if self.video_path else str(self.project_path or 'srt-session')
        self.preferences['export_folder'] = str(Path(path).resolve().parent)
        names = self.preferences['export_names']
        names.pop(key, None)
        names[key] = str(Path(path).resolve())
        self.preferences['export_names'] = dict(list(names.items())[-50:])
        self.save_preferences()
        self.schedule_project_save()

    def navigate_cue(self, direction, edit=False):
        if self.busy or not self.table.rowCount():
            return
        self.finish_cell_edit()
        current = self.table.currentRow()
        row = (current + direction) % self.table.rowCount() if current >= 0 else (0 if direction >= 0 else self.table.rowCount() - 1)
        self.table.setCurrentCell(row, 2)
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 2))
        if edit:
            self.table.editItem(self.table.item(row, 2))

    def request_waveform(self, request):
        if not hasattr(self, 'waveform'):
            return
        self.wave_pending = request
        if self.wave_worker is not None:
            self.wave_worker.cancel()
            return
        self.waveform.peaks = []
        self.waveform.message = 'Loading waveform for selected audio…' if request else 'Waveform unavailable for this selection'
        self.waveform.update()
        if request is None:
            return
        path, index = request
        self.wave_request = request
        worker = Transcriber(path, '', audio_index=index, target=waveform_job)
        self.wave_worker = worker
        worker.completed.connect(lambda result: self.waveform_ready(request, result))
        worker.failed.connect(lambda message: self.waveform_failed(request, message))
        worker.finished.connect(self.waveform_finished)
        worker.start()

    def waveform_ready(self, request, result):
        if request == self.wave_pending:
            self.waveform.set_audio(result[0], result[1])
            self.sync_waveform()

    def waveform_failed(self, request, message):
        if request == self.wave_pending:
            self.waveform.message = f'Waveform unavailable: {message}'
            self.waveform.update()

    def waveform_finished(self):
        worker = self.wave_worker
        cancelled = worker.cancel_requested.is_set() if worker else False
        self.wave_worker = None
        if worker:
            worker.deleteLater()
        if self.wave_pending != self.wave_request or (cancelled and self.wave_pending is not None):
            self.request_waveform(self.wave_pending)

    def sync_waveform(self):
        if not hasattr(self, 'waveform'):
            return
        cues = []
        for a, b, _ in self._last_rows:
            try:
                cues.append((parse_timestamp(a), parse_timestamp(b)))
            except ValueError:
                cues.append((-1, -1))
        self.waveform.cues = cues
        self.waveform.selected = self.table.currentRow() if self.table.selectedIndexes() else -1
        self.waveform.set_position(self.player.position())

    def waveform_boundary(self, row, start, end):
        if self.busy or not 0 <= row < self.table.rowCount() or not 0 <= start < end <= self.waveform.duration:
            return
        self.finish_cell_edit()
        rows = list(self.raw_cells())
        rows[row] = timestamp(start), timestamp(end), rows[row][2]
        self.change_cells(rows, 'Drag waveform boundary', (row, 2))

    def refresh_workspace(self):
        if not hasattr(self, 'waveform'):
            return
        for action in self.workspace_actions:
            action.setEnabled(not self.busy and self.track_probe is None)
        self.recent_menu.setEnabled(not self.busy and self.track_probe is None and bool(self.preferences['recent']))
        for action in self.navigation_actions:
            action.setEnabled(not self.busy and bool(self.table.rowCount()))
        self.waveform.setEnabled(not self.busy and self.track_probe is None)
        self.wave_zoom.setEnabled(not self.busy)
        self.sync_waveform()

    def stop_waveform(self):
        if self.wave_worker:
            self.wave_pending = None
            self.wave_worker.cancel()
            self.wave_worker.wait(5000)
            if self.wave_worker.isRunning():
                return False
        return True

    def open_batch(self):
        if self.busy or self.track_probe is not None:
            return
        from batch_queue import BatchDialog
        self.finish_cell_edit()
        self.batch_dialog = BatchDialog(self)
        self.batch_dialog.exec()
