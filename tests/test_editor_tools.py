import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt, QMimeData, QUrl, QPoint, QPointF, QItemSelectionModel, QTimer, QLockFile
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QPlainTextEdit, QComboBox, QPushButton
from main import MainWindow
from editor_operations import replace_all, shift_rows, split_row, merge_rows, cue_warnings
from show_profiles import ProfileStore

APP = QApplication.instance() or QApplication([])
A, B, C, D = '00:00:01,000', '00:00:02,000', '00:00:03,000', '00:00:04,000'


class OperationTests(unittest.TestCase):
    def test_replacement_is_literal_unicode_and_dialogue_only(self):
        rows = [(A, B, 'SAY JOE; say joey; say joe. 東京')]
        result, count = replace_all(rows, 'say joe', r'Seijou\1')
        self.assertEqual(count, 2)
        self.assertEqual(result, [(A, B, 'Seijou\\1; say joey; Seijou\\1. 東京')])
        self.assertEqual(rows[0][2], 'SAY JOE; say joey; say joe. 東京')
        self.assertEqual(replace_all(rows, 'say joe', '', True, True)[1], 1)
        self.assertEqual(replace_all(rows, 'say joe', 'x', False)[1], 3)
        self.assertEqual(replace_all(rows, '.', '!', False)[0][0][2], 'SAY JOE; say joey; say joe! 東京')
        with self.assertRaises(ValueError):
            replace_all(rows, '', 'anything')

    def test_shift_preserves_text_and_is_atomic_on_negative_or_invalid(self):
        rows = [(A, B, 'One'), (C, D, 'Two')]
        self.assertEqual(shift_rows(rows, [1], -1000), [(A, B, 'One'), (B, C, 'Two')])
        for bad in ([(A, B, 'One'), ('broken', D, 'Two')], rows):
            with self.assertRaises(ValueError):
                shift_rows(bad, range(2), -2000)
        self.assertEqual(rows, [(A, B, 'One'), (C, D, 'Two')])

    def test_split_preserves_every_character_and_rejects_boundaries(self):
        rows = [(A, D, 'Hello 🎉\nSeijou!')]
        split = split_row(rows, 0, 2000, 7)
        self.assertEqual(''.join(r[2] for r in split), rows[0][2])
        self.assertEqual(split[0][:2], (A, B))
        self.assertEqual(split[1][:2], (B, D))
        for time, offset in ((1000, 3), (4000, 3), (2000, 0), (2000, len(rows[0][2]))):
            with self.assertRaises(ValueError):
                split_row(rows, 0, time, offset)

    def test_merge_preserves_multiline_text_outer_bounds_and_adjacent_rule(self):
        rows = [(A, D, 'One\nTwo'), (B, C, 'Three'), (D, '00:00:05,000', 'Four')]
        self.assertEqual(merge_rows(rows, [0, 1]), [(A, D, 'One\nTwo\nThree'), rows[2]])
        for indices in ([], [0], [0, 2]):
            with self.assertRaises(ValueError):
                merge_rows(rows, indices)
        with self.assertRaises(ValueError):
            merge_rows(list(reversed(rows)), [0, 1])

    def test_readability_guides_cover_duration_speed_lines_and_invalid(self):
        self.assertEqual(cue_warnings((A, D, 'Hello there')), [])
        self.assertIn('Invalid timing', cue_warnings(('broken', B, 'Hello')))
        self.assertIn('Invalid timing', cue_warnings((B, A, 'Hello')))
        warnings = cue_warnings((A, '00:00:01,500', 'x' * 43 + '\nSecond\nThird'))
        self.assertEqual(len(warnings), 4)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProfileStore(self.temp.name)

    def test_save_reload_overwrite_delete_and_independent_windows(self):
        self.store.update('Haikyuu', {'names': 'Seijou', 'replacements': 'say joe => Seijou'})
        other = ProfileStore(self.temp.name)
        other.update('Another show', {'context': 'Other'})
        self.store.update('Haikyuu', {'names': 'Seijou, Hinata'})
        self.assertEqual(len(other.load()), 2)
        self.assertEqual(other.load()['Haikyuu']['names'], 'Seijou, Hinata')
        self.store.update('Haikyuu', delete=True)
        self.assertEqual(list(other.load()), ['Another show'])

    def test_failed_atomic_save_and_corrupt_store_are_preserved(self):
        self.store.update('Keep', {'names': 'Seijou'})
        previous = self.store.path.read_bytes()
        with patch('recovery.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.update('New', {})
        self.assertEqual(self.store.path.read_bytes(), previous)
        self.store.path.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            self.store.update('New', {})
        self.assertEqual(self.store.path.read_bytes(), b'broken')

    def test_profile_lock_invalid_rules_and_invalid_names(self):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.store.path) + '.lock')
        self.assertTrue(lock.tryLock(0))
        try:
            with self.assertRaises(OSError):
                self.store.update('Show', {})
        finally:
            lock.unlock()
        for name, options in (('', {}), ('x' * 81, {}), ('Show', {'replacements': 'bad rule'})):
            with self.assertRaises(ValueError):
                self.store.update(name, options)


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        warning = patch.object(QMessageBox, 'warning')
        warning.start()
        self.addCleanup(warning.stop)
        self.window = MainWindow(recovery_directory=self.root / 'recovery', offer_recovery=False, profiles_directory=self.root / 'profiles')
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.busy = False
        self.window.mark_saved()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def seed(self):
        self.window.set_rows([(1000, 2000, 'Say Joe is ready'), (3000, 4000, 'Say Joe returns')], clean=True)

    def select(self, *indices):
        self.window.table.clearSelection()
        for row in indices:
            self.window.table.selectionModel().select(self.window.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def test_find_replace_counts_wraps_and_undoes_in_one_step(self):
        self.seed()
        w = self.window
        w.open_find_replace()
        w.find_dialog.find.setText('say joe')
        w.find_dialog.replacement.setText('Seijou')
        self.assertIn('2 matches', w.find_dialog.matches.text())
        w.find_dialog.find_next()
        self.assertEqual(w.table.currentRow(), 0)
        w.find_dialog.find_next()
        self.assertEqual(w.table.currentRow(), 1)
        w.find_dialog.find_next()
        self.assertEqual(w.table.currentRow(), 0)
        before = w.raw_cells()
        w.replace_dialog_matches()
        self.assertEqual(w.undo_stack.count(), 1)
        self.assertEqual(w.raw_cells()[0], (A, B, 'Seijou is ready'))
        w.undo_stack.undo()
        self.assertEqual(w.raw_cells(), before)
        self.assertIn('2 matches', w.find_dialog.matches.text())

    def test_shift_selected_and_all_with_undo_and_failed_atomic_edit(self):
        self.seed()
        w = self.window
        before = w.raw_cells()
        self.select(1)
        w.shift_timing(100, True)
        self.assertEqual(w.raw_cells()[0], before[0])
        self.assertEqual(w.raw_cells()[1][:2], ('00:00:03,100', '00:00:04,100'))
        w.undo_stack.undo()
        w.shift_timing(-500)
        self.assertEqual(w.raw_cells()[0][0], '00:00:00,500')
        changed = w.raw_cells()
        with patch.object(QMessageBox, 'warning') as warning:
            w.shift_timing(-1000)
            warning.assert_called_once()
        self.assertEqual(w.raw_cells(), changed)

    def test_find_correction_can_be_remembered_without_changing_current_cues(self):
        self.seed()
        w = self.window
        before = w.raw_cells()
        w.open_find_replace()
        w.find_dialog.find.setText('say joe')
        w.find_dialog.replacement.setText('Seijou')
        with patch.object(w, 'manage_profiles') as manage:
            w.find_dialog.remember_correction()
            manage.assert_called_once()
        self.assertEqual(w.exact_replacements.text(), 'say joe => Seijou')
        self.assertEqual(w.raw_cells(), before)
        w.find_dialog.replacement.setText('Seijō')
        with patch.object(w, 'manage_profiles'):
            w.find_dialog.remember_correction()
        self.assertEqual(w.exact_replacements.text(), 'say joe => Seijō')
        w.find_dialog.whole.setChecked(False)
        with patch.object(w, 'manage_profiles') as manage:
            w.find_dialog.remember_correction()
            manage.assert_not_called()

    def test_playhead_boundaries_validate_and_undo(self):
        self.seed()
        w = self.window
        w.video_path = 'preview.mp4'
        self.select(0)
        with patch.object(w.player, 'duration', return_value=10000), patch.object(w.player, 'position', return_value=1200):
            w.set_cue_boundary(0)
            self.assertEqual(w.raw_cells()[0][0], '00:00:01,200')
            w.set_cue_boundary(1)
        self.assertEqual(w.raw_cells()[0][1], B)
        w.undo_stack.undo()
        self.assertEqual(w.raw_cells()[0][0], A)

    def test_split_dialog_handles_emoji_cursor_and_single_undo(self):
        w = self.window
        w.set_rows([(1000, 4000, 'Hello 🎉 Seijou')], clean=True)
        w.video_path = 'preview.mp4'
        self.select(0)
        def choose_split(dialog):
            editor = dialog.findChild(QPlainTextEdit)
            cursor = editor.textCursor()
            cursor.setPosition(len('Hello 🎉'.encode('utf-16-le')) // 2)
            editor.setTextCursor(cursor)
            return QDialog.Accepted
        before = w.raw_cells()
        with patch.object(w.player, 'duration', return_value=10000), patch.object(w.player, 'position', return_value=2000), patch.object(QDialog, 'exec', choose_split):
            w.split_selected()
        self.assertEqual(w.raw_cells(), ((A, B, 'Hello 🎉'), (B, D, ' Seijou')))
        w.undo_stack.undo()
        self.assertEqual(w.raw_cells(), before)

    def test_merge_multi_selection_and_undo(self):
        self.seed()
        w = self.window
        before = w.raw_cells()
        self.select(0, 1)
        w.merge_selected()
        self.assertEqual(w.raw_cells(), ((A, D, 'Say Joe is ready\nSay Joe returns'),))
        w.undo_stack.undo()
        self.assertEqual(w.raw_cells(), before)

    def test_readability_refresh_is_not_an_edit_and_never_blocks_export(self):
        w = self.window
        w.set_rows([(1000, 1200, 'A very long subtitle that disappears too fast')], clean=True)
        self.assertEqual(w.warning_rows, [0])
        self.assertEqual(w.undo_stack.count(), 0)
        self.assertIn('Fast reading', w.table.item(0, 2).toolTip())
        w.jump_to_warning()
        self.assertEqual(w.table.currentRow(), 0)
        with patch('main.QFileDialog.getSaveFileName', return_value=(str(self.root / 'warned.srt'), '')):
            self.assertTrue(w.export_srt())
        w.table.item(0, 1).setText(D)
        w.table.item(0, 2).setText('Fine')
        self.assertEqual(w.warning_rows, [])
        w.undo_stack.undo()
        w.undo_stack.undo()
        self.assertEqual(w.warning_rows, [0])

    def test_show_profile_saved_through_ui_loads_and_applies_rules_undoably(self):
        w = self.window
        w.name_hints.setText('Seijou')
        w.exact_replacements.setText('say joe => Seijou')
        def save():
            dialog = APP.activeModalWidget()
            dialog.findChild(QComboBox).setCurrentText('Haikyuu')
            next(b for b in dialog.findChildren(QPushButton) if b.text() == 'Save current settings').click()
        QTimer.singleShot(0, save)
        w.manage_profiles()
        self.assertEqual(w.profile_store.load()['Haikyuu']['names'], 'Seijou')
        w.name_hints.clear()
        w.exact_replacements.clear()
        w.load_show_profile('Haikyuu')
        self.assertEqual(w.name_hints.text(), 'Seijou')
        self.seed()
        before = w.raw_cells()
        w.apply_saved_rules()
        self.assertEqual(w.raw_cells()[0][2], 'Seijou is ready')
        w.undo_stack.undo()
        self.assertEqual(w.raw_cells(), before)

    def test_switching_to_builtin_or_custom_context_drops_other_show_rules(self):
        w = self.window
        for index in (0, 1):
            w.exact_replacements.setText('say joe => Seijou')
            w.apply_context_preset(index)
            self.assertEqual(w.exact_replacements.text(), '')

    def test_shortcuts_set_selected_boundary_and_open_find_dialog(self):
        from PySide6.QtTest import QTest
        self.seed()
        w = self.window
        w.video_path = 'preview.mp4'
        self.select(0)
        with patch.object(w.player, 'duration', return_value=10000), patch.object(w.player, 'position', return_value=1500):
            w.refresh_actions()
            w.activateWindow()
            w.table.setFocus()
            APP.processEvents()
            QTest.keyClick(w.table, Qt.Key_S, Qt.ControlModifier | Qt.AltModifier)
            self.assertEqual(w.raw_cells()[0][0], '00:00:01,500')
            QTest.keyClick(w.table, Qt.Key_H, Qt.ControlModifier)
            self.assertTrue(w.find_dialog.isVisible())

    def test_drop_reuses_prevalidated_srt_if_file_changes_during_video_open(self):
        self.seed()
        w = self.window
        video = self.root / 'video.mkv'
        video.write_bytes(b'fixture')
        srt = self.srt()
        def load(_):
            srt.write_text('replaced while opening video')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(w, 'load_video', side_effect=load):
            self.assertTrue(self.drop([video, srt]))
        self.assertEqual(w.raw_cells()[0][2], 'Dropped subtitles')

    def test_drop_rejects_duplicates_folders_unknown_types_and_remote_urls(self):
        w = self.window
        first, second = self.srt(), self.srt('second.srt')
        for paths in ([first, second], [self.root], [self.root / 'missing.mp4']):
            self.assertFalse(self.drop(paths))
        unknown = self.root / 'notes.txt'
        unknown.write_text('text')
        self.assertFalse(self.drop([unknown]))
        mime = QMimeData()
        mime.setUrls([QUrl('https://example.com/video.mp4')])
        self.assertEqual(w.drop_paths(mime), [])

    def drop(self, paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        APP.sendEvent(self.window, enter)
        event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        if enter.isAccepted():
            APP.sendEvent(self.window, event)
        return event.isAccepted()

    def srt(self, name='subtitles.SRT'):
        path = self.root / name
        path.write_text('1\n00:00:00,000 --> 00:00:02,000\nDropped subtitles\n', encoding='utf-8-sig')
        return path

    def test_drop_srt_imports_without_file_dialog_and_cancel_keeps_edits(self):
        w = self.window
        self.assertTrue(self.drop([self.srt()]))
        self.assertEqual(w.get_rows(), [(0, 2000, 'Dropped subtitles')])
        w.table.item(0, 2).setText('Keep edit')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.assertFalse(self.drop([self.srt('another.srt')]))
        self.assertEqual(w.raw_cells()[0][2], 'Keep edit')

    def test_drop_video_srt_pair_validates_before_replacing_existing_document(self):
        self.seed()
        w = self.window
        video = self.root / 'video.MKV'
        video.write_bytes(b'fixture')
        invalid = self.root / 'bad.srt'
        invalid.write_text('invalid')
        before = w.raw_cells()
        with patch.object(QMessageBox, 'warning'), patch.object(w, 'load_video') as load:
            self.assertFalse(self.drop([video, invalid]))
            load.assert_not_called()
        self.assertEqual(w.raw_cells(), before)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(w, 'load_video') as load:
            self.assertTrue(self.drop([video, self.srt()]))
            load.assert_called_once_with(str(video.resolve()))
        self.assertEqual(w.raw_cells()[0][2], 'Dropped subtitles')

    def test_busy_locks_every_new_mutation_and_drop(self):
        self.seed()
        w = self.window
        before = w.raw_cells()
        w.busy = True
        w.refresh_actions()
        self.assertTrue(all(not action.isEnabled() for action in w.tool_actions.values()))
        self.assertFalse(w.profile_button.isEnabled())
        w.shift_timing(100)
        w.merge_selected()
        w.apply_saved_rules()
        self.assertFalse(self.drop([self.srt()]))
        self.assertEqual(w.raw_cells(), before)

    def test_edit_keeps_selected_row_in_an_inactive_editor_window(self):
        other = MainWindow(recovery_directory=self.root / 'other-recovery', offer_recovery=False, profiles_directory=self.root / 'profiles')
        try:
            other.set_rows([(1000, 2000, 'Selected cue')], clean=True)
            other.table.selectRow(0)
            self.window.activateWindow()
            self.window.name_hints.setFocus()
            APP.processEvents()
            other.table.item(0, 0).setText('invalid')
            self.assertEqual(other.selected_rows(), [0])
            self.assertEqual(other.table.currentRow(), 0)
        finally:
            other.mark_saved()
            other.close()
            other.deleteLater()


if __name__ == '__main__':
    unittest.main()
