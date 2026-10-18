"""Document history, unsaved-change protection, and per-window crash recovery."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QLockFile, QTimer, Qt
from PySide6.QtGui import QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QTableWidgetItem
from recovery import recovery_directory, read_snapshot, write_snapshot


class SubtitleChange(QUndoCommand):
    def __init__(self, window, before, after, label, cursor):
        super().__init__(label)
        self.window, self.before, self.after, self.cursor = window, before, after, cursor

    def redo(self):
        self.window.apply_cells(self.after, self.cursor)

    def undo(self):
        self.window.apply_cells(self.before, self.cursor)


class EditingSafety:
    def init_editing(self, controls, directory=None, offer_recovery=True):
        self._last_rows = self._saved_rows = ()
        self.srt_path = None
        self.recovery_path = Path(directory) if directory is not None else recovery_directory()
        self.recovery_path = self.recovery_path / f'{uuid4().hex}.json'
        self.recovery_lock = None
        self.recovery_saved = False
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.undo_action = self.undo_stack.createUndoAction(self, 'Undo')
        self.redo_action = self.undo_stack.createRedoAction(self, 'Redo')
        self.undo_action.setShortcuts(QKeySequence.keyBindings(QKeySequence.Undo))
        self.redo_action.setShortcuts(QKeySequence.keyBindings(QKeySequence.Redo))
        menu = self.menuBar().addMenu('Edit')
        menu.addAction(self.undo_action)
        menu.addAction(self.redo_action)
        for index, action in enumerate((self.undo_action, self.redo_action)):
            button = QPushButton(action.text())
            button.clicked.connect(action.trigger)
            action.enabledChanged.connect(button.setEnabled)
            button.setEnabled(False)
            controls.insertWidget(index, button)
        self.save_status = QLabel('All changes saved')
        self.statusBar().addPermanentWidget(self.save_status)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(750)
        self.autosave_timer.timeout.connect(self.save_recovery)
        if offer_recovery:
            QTimer.singleShot(0, self.offer_recovery)

    @property
    def dirty(self):
        return self._last_rows != self._saved_rows

    def raw_cells(self):
        return tuple(tuple(self.table.item(row, col).text() if self.table.item(row, col) else '' for col in range(3)) for row in range(self.table.rowCount()))

    def apply_cells(self, rows, cursor=None):
        self.stop_replay()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rows))
            for row, cells in enumerate(rows):
                for col, value in enumerate(cells):
                    self.table.setItem(row, col, QTableWidgetItem(value))
            if cursor and rows:
                self.table.setCurrentCell(min(max(cursor[0], 0), len(rows) - 1), max(cursor[1], 0))
        finally:
            self.table.blockSignals(False)
        self._last_rows = tuple(tuple(row) for row in rows)
        self.document_changed()
        self.update_caption(self.player.position())
        self.refresh_actions()

    def change_cells(self, rows, label, cursor=None):
        rows = tuple(tuple(row) for row in rows)
        if rows != self._last_rows:
            self.undo_stack.push(SubtitleChange(self, self._last_rows, rows, label, cursor))
        self.refresh_actions()

    def document_changed(self):
        self.recovery_saved = False
        self.setWindowTitle('Dubtitler v0.3.0 — English Dub Subtitle Editor' + (' *' if self.dirty else ''))
        if self.dirty:
            self.save_status.setText('Unsaved edits · saving recovery…')
            self.autosave_timer.start()
        else:
            self.autosave_timer.stop()
            self.clear_recovery()
            self.save_status.setText('All changes saved')

    def mark_saved(self):
        self._saved_rows = self._last_rows
        self.document_changed()
        self.refresh_actions()

    def confirm_unsaved(self, action):
        self.finish_cell_edit()
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, 'Unsaved subtitles', f'Save your subtitle changes before you {action}?', QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.export_srt()
        return answer == QMessageBox.Discard

    def finish_cell_edit(self):
        editor = QApplication.focusWidget()
        if editor is not None and self.table.isAncestorOf(editor):
            self.table.setFocus(Qt.OtherFocusReason)

    def clear_recovery(self):
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError as exc:
            self.statusBar().showMessage(f'Could not remove recovery copy: {exc}')

    def save_recovery(self):
        if not self.dirty:
            return
        try:
            self.recovery_path.parent.mkdir(parents=True, exist_ok=True)
            if self.recovery_lock is None:
                lock = QLockFile(str(self.recovery_path) + '.lock')
                lock.setStaleLockTime(0)
                if not lock.tryLock(0):
                    raise OSError('Recovery file is in use')
                self.recovery_lock = lock
            write_snapshot(self.recovery_path, {'version': 1, 'video_path': self.video_path, 'srt_path': self.srt_path, 'audio_index': self.audio_tracks.currentData(), 'rows': self._last_rows, 'saved_rows': self._saved_rows})
            self.recovery_saved = True
            self.save_status.setText('Unsaved edits · recovery saved')
        except OSError as exc:
            self.save_status.setText('Recovery unavailable · export SRT to save')
            self.statusBar().showMessage(f'Could not save recovery copy: {exc}')

    def ask_recovery(self, path, data):
        box = QMessageBox(self)
        box.setWindowTitle('Recover unsaved subtitles?')
        box.setText(f'Unsaved subtitles were found for {Path(data["video_path"]).name if data.get("video_path") else "an SRT editing session"}.')
        box.setInformativeText('Recover the edits, discard this recovery copy, or keep it for later.')
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText('Recover edits')
        box.button(QMessageBox.No).setText('Discard copy')
        box.button(QMessageBox.Cancel).setText('Later')
        box.setDefaultButton(QMessageBox.Yes)
        return box.exec()

    def offer_recovery(self):
        if self.dirty or self.busy or self.track_probe is not None:
            return
        directory = self.recovery_path.parent
        try:
            candidates = sorted(directory.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError as exc:
            self.statusBar().showMessage(f'Could not read recovery folder: {exc}')
            return
        for path in candidates:
            if path == self.recovery_path:
                continue
            lock = QLockFile(str(path) + '.lock')
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                continue  # Another running window owns this recovery copy.
            adopted = False
            try:
                data = read_snapshot(path)
                answer = self.ask_recovery(path, data)
                if answer == QMessageBox.No:
                    path.unlink()
                    continue
                if answer != QMessageBox.Yes:
                    return
                self.recovery_path, self.recovery_lock = path, lock
                adopted = True
                self.video_path, self.srt_path = data.get('video_path'), data.get('srt_path')
                if self.video_path:
                    self.load_video(self.video_path, data.get('audio_index'))
                self.undo_stack.clear()
                self._saved_rows = tuple(tuple(row) for row in data['saved_rows'])
                self.apply_cells(data['rows'])
                self.progress_label.setText('Recovered unsaved subtitles. Review them in step 3, then Export SRT.')
                self.statusBar().showMessage('Recovered edits. Undo history starts with this session.')
                return
            except (OSError, ValueError) as exc:
                self.statusBar().showMessage(f'Recovery copy could not be read; kept at {path}: {exc}')
            finally:
                if not adopted:
                    lock.unlock()

    def finish_editing(self):
        self.autosave_timer.stop()
        self.clear_recovery()
        if self.recovery_lock is not None:
            self.recovery_lock.unlock()
            self.recovery_lock = None
