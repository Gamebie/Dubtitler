"""Manual subtitle workflow: search, profiles, timing, cue surgery and drops."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QDialogButtonBox, QComboBox, QMessageBox, QPlainTextEdit)
from editor_operations import find_pattern, replace_all, shift_rows, split_row, merge_rows, cue_warnings
from show_profiles import ProfileStore
from timeline_checks import document_warnings
from subtitle_format import parse_timestamp, timestamp, read_srt

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.wmv'}


class EditorTools:
    def init_editor_tools(self, controls, context_row, profiles_directory=None):
        self.profile_store = ProfileStore(profiles_directory)
        self.find_dialog = None
        self.tool_actions = {}
        menu = self.menuBar().addMenu('Subtitle tools')
        for key, label, shortcut, callback in (
            ('find', 'Find / replace…', 'Ctrl+H', self.open_find_replace),
            ('start', 'Set start to playhead', 'Ctrl+Alt+S', lambda: self.set_cue_boundary(0)),
            ('end', 'Set end to playhead', 'Ctrl+Alt+E', lambda: self.set_cue_boundary(1)),
            ('shift', 'Shift timing…', 'Ctrl+Shift+T', self.open_shift),
            ('split', 'Split at playhead…', 'Ctrl+Shift+S', self.split_selected),
            ('merge', 'Merge selected', 'Ctrl+M', self.merge_selected),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            menu.addAction(action)
            self.tool_actions[key] = action
        for key in ('find', 'shift', 'split', 'merge'):
            action = self.tool_actions[key]
            button = QPushButton(action.text())
            button.setToolTip(f'{action.text()} ({action.shortcut().toString()})')
            button.clicked.connect(action.trigger)
            action.enabledChanged.connect(button.setEnabled)
            controls.addWidget(button)
        self.warnings_label = QLabel('Readability: no warnings')
        self.warnings_label.setToolTip('Checks include overlaps, possible duplicates, gaps of at least 3 seconds (possibly intentional), and readability guides: 20 non-space characters/second, 42 characters/line, two lines, 0.7 seconds minimum. Warnings never block export.')
        controls.addWidget(self.warnings_label, 1)
        self.next_warning = QPushButton('Next warning')
        self.next_warning.clicked.connect(self.jump_to_warning)
        controls.addWidget(self.next_warning)
        self.profile_button = QPushButton('Profiles…')
        self.profile_button.clicked.connect(self.manage_profiles)
        context_row.addWidget(self.profile_button)
        self.reload_profiles()
        self.setAcceptDrops(True)

    def selected_rows(self):
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def refresh_editor_tools(self):
        if not hasattr(self, 'tool_actions'):
            return
        selected = self.selected_rows()
        ready = not self.busy
        media = bool(self.video_path) and self.track_probe is None and self.player.duration() > 0
        for key, action in self.tool_actions.items():
            enabled = ready and self.table.rowCount() > 0
            if key in ('start', 'end', 'split'):
                enabled = enabled and media and len(selected) == 1
            if key == 'merge':
                enabled = enabled and len(selected) > 1
            action.setEnabled(enabled)
        self.profile_button.setEnabled(ready)
        self.next_warning.setEnabled(ready and bool(getattr(self, 'warning_rows', [])))
        if self.find_dialog is not None:
            self.find_dialog.setEnabled(ready)

    def update_readability(self):
        if not hasattr(self, 'warnings_label'):
            return
        self.warning_rows = []
        self.table.blockSignals(True)
        try:
            for row, warnings in enumerate(document_warnings(self._last_rows)):
                if warnings:
                    self.warning_rows.append(row)
                for col in range(3):
                    item = self.table.item(row, col)
                    item.setToolTip('\n'.join(warnings))
                    item.setForeground(QColor('#ffd38a') if warnings else QColor('#eaeaea'))
        finally:
            self.table.blockSignals(False)
        self.warnings_label.setText(f'Checks: {len(self.warning_rows)} cues to review' if self.warning_rows else 'Checks: no warnings')
        self.refresh_editor_tools()
        if self.find_dialog is not None:
            self.find_dialog.update_matches()

    def jump_to_warning(self):
        if self.busy or not self.warning_rows:
            return
        current = self.table.currentRow()
        row = next((row for row in self.warning_rows if row > current), self.warning_rows[0])
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 2))
        self.statusBar().showMessage(self.table.item(row, 2).toolTip())

    def open_find_replace(self):
        if self.busy:
            return
        self.finish_cell_edit()
        if self.find_dialog is None:
            self.find_dialog = FindReplaceDialog(self)
        self.find_dialog.update_matches()
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.find.setFocus()

    def replace_dialog_matches(self):
        if self.busy:
            return
        self.finish_cell_edit()
        dialog = self.find_dialog
        try:
            rows, count = replace_all(self.raw_cells(), dialog.find.text(), dialog.replacement.text(),
                                      dialog.whole.isChecked(), dialog.case.isChecked())
            self.change_cells(rows, 'Replace all text')
            self.statusBar().showMessage(f'Replaced {count} matches. Undo restores all changes together.')
        except ValueError as exc:
            dialog.matches.setText(str(exc))

    def set_cue_boundary(self, column):
        if self.busy:
            return
        self.finish_cell_edit()
        selected = self.selected_rows()
        if len(selected) != 1 or not self.video_path or self.track_probe is not None or self.player.duration() <= 0:
            return
        row = selected[0]
        cells = list(self.raw_cells())
        cue = list(cells[row])
        cue[column] = timestamp(self.player.position())
        try:
            if parse_timestamp(cue[1]) <= parse_timestamp(cue[0]):
                raise ValueError('Start must be before end. Move the playhead and try again.')
            cells[row] = tuple(cue)
            self.change_cells(cells, 'Set subtitle boundary', (row, column))
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid timing', str(exc))

    def open_shift(self):
        if self.busy:
            return
        self.finish_cell_edit()
        dialog = QDialog(self)
        dialog.setWindowTitle('Shift subtitle timing')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Offset in milliseconds: positive = later; negative = earlier.\nNothing changes if any shifted cue would become invalid.'))
        from PySide6.QtWidgets import QSpinBox
        offset = QSpinBox()
        offset.setRange(-86400000, 86400000)
        offset.setSingleStep(100)
        offset.setSuffix(' ms')
        layout.addWidget(offset)
        scope = QComboBox()
        scope.addItems(['All subtitles', 'Selected rows only'])
        layout.addWidget(scope)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            self.shift_timing(offset.value(), scope.currentIndex() == 1)

    def shift_timing(self, offset, selected_only=False):
        if self.busy:
            return
        self.finish_cell_edit()
        indices = self.selected_rows() if selected_only else range(self.table.rowCount())
        if not indices:
            QMessageBox.information(self, 'Select subtitles', 'Select at least one row to shift.')
            return
        try:
            self.change_cells(shift_rows(self.raw_cells(), indices, offset), 'Shift subtitle timing')
        except ValueError as exc:
            QMessageBox.warning(self, 'Shift not applied', str(exc))

    def split_selected(self):
        if self.busy:
            return
        self.finish_cell_edit()
        selected = self.selected_rows()
        if len(selected) != 1 or not self.video_path or self.track_probe is not None or self.player.duration() <= 0:
            return
        row, position = selected[0], self.player.position()
        cells = self.raw_cells()
        try:
            begin, end = map(parse_timestamp, cells[row][:2])
            if not begin < position < end:
                raise ValueError('Place the playhead strictly inside the selected subtitle before splitting.')
        except ValueError as exc:
            QMessageBox.warning(self, 'Cannot split', str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Split subtitle at playhead')
        dialog.resize(600, 230)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f'Time split: {timestamp(position)}. Click between the words to choose the text split.\nBoth parts are preserved; you can adjust them afterwards.'))
        text = cells[row][2]
        editor = QPlainTextEdit(text)
        editor.setReadOnly(True)
        target = round(len(text) * (position - begin) / (end - begin))
        boundaries = [i for i in range(1, len(text)) if text[i].isspace() and text[:i].strip() and text[i:].strip()]
        offset = min(boundaries, key=lambda i: abs(i - target)) if boundaries else target
        cursor = editor.textCursor()
        cursor.setPosition(len(text[:offset].encode('utf-16-le')) // 2)
        editor.setTextCursor(cursor)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            # Qt cursor positions use UTF-16; Python slices use Unicode code points.
            offset = len(text.encode('utf-16-le')[:editor.textCursor().position() * 2].decode('utf-16-le', errors='ignore'))
            try:
                self.change_cells(split_row(cells, row, position, offset), 'Split subtitle', (row, 2))
            except ValueError as exc:
                QMessageBox.warning(self, 'Cannot split', str(exc))

    def merge_selected(self):
        if self.busy:
            return
        self.finish_cell_edit()
        try:
            indices = self.selected_rows()
            rows = merge_rows(self.raw_cells(), indices)
            self.change_cells(rows, 'Merge subtitles', (min(indices), 2))
        except ValueError as exc:
            QMessageBox.warning(self, 'Cannot merge', str(exc))

    def reload_profiles(self):
        try:
            self.show_profiles = self.profile_store.load()
            self.profile_error = None
        except (OSError, ValueError) as exc:
            self.show_profiles, self.profile_error = {}, str(exc)
            self.statusBar().showMessage(f'Could not load show profiles: {exc}')
        self.context_preset.blockSignals(True)
        try:
            while self.context_preset.count() > 2:
                self.context_preset.removeItem(2)
            for name in sorted(self.show_profiles, key=str.casefold):
                self.context_preset.addItem(f'Saved: {name}', name)
        finally:
            self.context_preset.blockSignals(False)

    def load_show_profile(self, name):
        if self.busy:
            return
        try:
            options = self.profile_store.load()[name]
            self.restore_transcription_options(options)
            self.context_preset.setCurrentIndex(self.context_preset.findData(name))
            self.statusBar().showMessage(f'Loaded show profile: {name}. Rules affect future transcription; use Apply current rules for existing cues.')
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, 'Profile unavailable', str(exc))

    def apply_saved_rules(self):
        if self.busy:
            return
        from transcription_options import correct_text
        self.finish_cell_edit()
        try:
            options = self.transcription_options()
            self.change_cells([(a, b, correct_text(text, options)) for a, b, text in self.raw_cells()], 'Apply show spelling rules')
        except ValueError as exc:
            QMessageBox.warning(self, 'Check spelling rules', str(exc))

    def manage_profiles(self):
        if self.busy:
            return
        self.reload_profiles()
        dialog = QDialog(self)
        dialog.setWindowTitle('Saved show profiles')
        layout = QVBoxLayout(dialog)
        info = QLabel('Profiles save the current show context, names, exact spelling rules and voice-change setting locally.\nLoad a profile before transcribing another episode. Loading does not change existing subtitles.\nAdd recurring spellings in “Always replace”, then save the profile. Existing cues can use Apply current rules.')
        info.setWordWrap(True)
        layout.addWidget(info)
        names = QComboBox()
        names.setEditable(True)
        names.setInsertPolicy(QComboBox.NoInsert)
        names.addItems(sorted(self.show_profiles, key=str.casefold))
        names.lineEdit().setMaxLength(80)
        names.setCurrentText(self.context_preset.currentData() or '')
        names.lineEdit().setPlaceholderText('Show profile name')
        layout.addWidget(names)
        row = QHBoxLayout()
        layout.addLayout(row)

        def save():
            name = names.currentText().strip()
            try:
                options = self.transcription_options()
                current = self.profile_store.load()
                if name in current and QMessageBox.question(dialog, 'Replace profile?', f'Overwrite saved settings for {name}?') != QMessageBox.Yes:
                    return
                self.profile_store.update(name, options)
                self.reload_profiles()
                self.context_preset.setCurrentIndex(self.context_preset.findData(name))
                dialog.accept()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, 'Profile not saved', str(exc))

        def load():
            self.load_show_profile(names.currentText().strip())
            dialog.accept()

        def delete():
            name = names.currentText().strip()
            if name not in self.show_profiles:
                return
            if QMessageBox.question(dialog, 'Delete saved profile?', f'Delete {name}? Current subtitles and settings are kept.') != QMessageBox.Yes:
                return
            try:
                self.profile_store.update(name, delete=True)
                self.reload_profiles()
                names.clear()
                names.addItems(sorted(self.show_profiles, key=str.casefold))
                names.setCurrentText('')
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, 'Profile not deleted', str(exc))

        for label, callback in (('Save current settings', save), ('Load profile', load), ('Delete profile', delete)):
            button = QPushButton(label)
            row.addWidget(button)
            button.clicked.connect(callback)
        apply = QPushButton('Apply current spelling rules to existing subtitles')
        apply.clicked.connect(self.apply_saved_rules)
        layout.addWidget(apply)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def drop_paths(self, mime):
        if self.busy or self.track_probe is not None or not mime.hasUrls():
            return []
        urls = mime.urls()
        if not 1 <= len(urls) <= 2 or any(not url.isLocalFile() for url in urls):
            return []
        paths = [str(Path(url.toLocalFile()).resolve()) for url in urls]
        suffixes = [Path(path).suffix.lower() for path in paths]
        if (any(not Path(path).is_file() for path in paths)
                or any(suffix not in VIDEO_EXTENSIONS | {'.srt'} for suffix in suffixes)
                or sum(suffix == '.srt' for suffix in suffixes) > 1
                or sum(suffix in VIDEO_EXTENSIONS for suffix in suffixes) > 1):
            return []
        return paths

    def dragEnterEvent(self, event):
        if self.drop_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self.drop_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        video = next((path for path in paths if Path(path).suffix.lower() in VIDEO_EXTENSIONS), None)
        srt = next((path for path in paths if Path(path).suffix.lower() == '.srt'), None)
        try:
            rows = None
            if srt:
                rows = read_srt(srt)  # Validate before clearing edits; import this same snapshot.
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Import error', str(exc))
            event.ignore()
            return
        if video and not self.open_video(video):
            event.ignore()
            return
        if srt and not self.import_srt(srt, parsed_rows=rows):
            event.ignore()
            return
        event.acceptProposedAction()


class FindReplaceDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Find and replace subtitle text')
        self.resize(540, 230)
        layout = QVBoxLayout(self)
        self.find, self.replacement = QLineEdit(), QLineEdit()
        self.find.setPlaceholderText('Find, e.g. say joe')
        self.replacement.setPlaceholderText('Replace with, e.g. Seijou (blank deletes matches)')
        layout.addWidget(self.find)
        layout.addWidget(self.replacement)
        row = QHBoxLayout()
        self.whole, self.case = QCheckBox('Whole words'), QCheckBox('Match case')
        self.whole.setChecked(True)
        row.addWidget(self.whole)
        row.addWidget(self.case)
        layout.addLayout(row)
        self.matches = QLabel()
        layout.addWidget(self.matches)
        row = QHBoxLayout()
        layout.addLayout(row)
        for label, callback in (('Find next subtitle', self.find_next), ('Replace all', window.replace_dialog_matches)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        remember = QPushButton('Remember this correction in a show profile…')
        remember.clicked.connect(self.remember_correction)
        layout.addWidget(remember)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.hide)
        layout.addWidget(close)
        self.find.textChanged.connect(self.update_matches)
        self.whole.toggled.connect(self.update_matches)
        self.case.toggled.connect(self.update_matches)

    def matching_rows(self):
        pattern = find_pattern(self.find.text(), self.whole.isChecked(), self.case.isChecked())
        return [(index, len(pattern.findall(row[2]))) for index, row in enumerate(self.window.raw_cells()) if pattern.search(row[2])]

    def update_matches(self):
        try:
            rows = self.matching_rows()
            self.matches.setText(f'{sum(count for _, count in rows)} matches in {len(rows)} subtitles. Replace all changes dialogue only; Ctrl+Z undoes the entire replacement.')
        except ValueError as exc:
            self.matches.setText(str(exc))

    def find_next(self):
        if self.window.busy:
            return
        try:
            rows = self.matching_rows()
        except ValueError:
            return
        if rows:
            current = self.window.table.currentRow()
            index = next((index for index, _ in rows if index > current), rows[0][0])
            self.window.table.selectRow(index)
            self.window.table.scrollToItem(self.window.table.item(index, 2))

    def remember_correction(self):
        if self.window.busy:
            return
        from transcription_options import normalize_options, replacement_rules
        try:
            if not self.whole.isChecked() or self.case.isChecked():
                raise ValueError('Show spelling rules use whole words and ignore case. Enable Whole words and turn off Match case to remember this correction.')
            heard, spelling = self.find.text().strip(), self.replacement.text().strip()
            if not heard or not spelling or ';' in heard + spelling or '=>' in heard + spelling:
                raise ValueError('Enter non-empty heard words and the correct spelling, without semicolons or =>.')
            options = self.window.transcription_options()
            rules = [(a, b) for a, b in replacement_rules(options['replacements']) if a.casefold() != heard.casefold()]
            rules.append((heard, spelling))
            options['replacements'] = '; '.join(f'{a} => {b}' for a, b in rules)
            options = normalize_options(options)
            self.window.exact_replacements.setText(options['replacements'])
            self.hide()
            self.window.manage_profiles()
        except ValueError as exc:
            QMessageBox.warning(self, 'Correction not remembered', str(exc))
