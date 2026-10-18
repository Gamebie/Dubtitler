import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
import main
from recovery import read_snapshot, write_snapshot

APP = QApplication.instance() or QApplication([])


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.windows = []
        self.window = self.new_window()

    def new_window(self):
        window = main.MainWindow(recovery_directory=self.root, offer_recovery=False)
        self.windows.append(window)
        return window

    def tearDown(self):
        for window in reversed(self.windows):
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
                window.close()
            window.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def seed(self):
        self.window.set_rows([(0, 1000, 'Original'), (2000, 3000, 'Second')], clean=True)

    def test_text_timing_unicode_and_invalid_edits_undo_exactly(self):
        self.seed()
        original = self.window.raw_cells()
        self.window.table.item(0, 2).setText('Edited café\nline two')
        edited = self.window.raw_cells()
        self.window.table.item(0, 0).setText('unfinished timing')
        self.assertTrue(self.window.dirty)
        self.window.undo_stack.undo()
        self.assertEqual(self.window.raw_cells(), edited)
        self.window.undo_stack.undo()
        self.assertEqual(self.window.raw_cells(), original)
        self.assertFalse(self.window.dirty)
        self.window.undo_stack.redo()
        self.window.undo_stack.redo()
        self.assertEqual(self.window.raw_cells()[0], ('unfinished timing', '00:00:01,000', 'Edited café\nline two'))

    def test_add_and_multirow_delete_are_single_undo_steps(self):
        self.seed()
        original = self.window.raw_cells()
        self.window.add_row()
        self.assertEqual(self.window.undo_stack.count(), 1)
        self.window.undo_stack.undo()
        self.assertEqual(self.window.raw_cells(), original)
        self.window.undo_stack.redo()
        self.window.table.selectAll()
        self.window.delete_row()
        self.assertEqual(self.window.table.rowCount(), 0)
        self.window.undo_stack.undo()
        self.assertEqual(self.window.table.rowCount(), 3)

    def test_new_edit_after_undo_discards_redo_branch(self):
        self.seed()
        self.window.table.item(0, 2).setText('First edit')
        self.window.undo_stack.undo()
        self.window.table.item(0, 2).setText('Replacement')
        self.assertFalse(self.window.undo_stack.canRedo())
        self.assertEqual(self.window.get_rows()[0][2], 'Replacement')

    def test_export_checkpoint_and_undo_redo_dirty_state(self):
        self.seed()
        self.window.table.item(0, 2).setText('Saved edit')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.root / 'saved.srt'), '')):
            self.assertTrue(self.window.export_srt())
        self.assertFalse(self.window.dirty)
        self.window.undo_stack.undo()
        self.assertTrue(self.window.dirty)
        self.window.undo_stack.redo()
        self.assertFalse(self.window.dirty)

    def test_close_cancel_and_cancelled_save_keep_edits(self):
        self.window.add_row()
        for answer in (QMessageBox.Cancel, QMessageBox.Save):
            event = QCloseEvent()
            with patch.object(QMessageBox, 'question', return_value=answer), patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
                self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.assertTrue(self.window.dirty)

    def test_invalid_timing_save_blocks_close(self):
        self.window.add_row()
        self.window.table.item(0, 0).setText('bad')
        event = QCloseEvent()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Save), patch.object(QMessageBox, 'warning'):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.raw_cells()[0][0], 'bad')

    def test_save_on_close_writes_file_and_clears_recovery(self):
        self.window.add_row()
        self.window.save_recovery()
        event = QCloseEvent()
        output = self.root / 'saved.srt'
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Save), patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), '')):
            self.window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertIn('New subtitle', output.read_text(encoding='utf-8-sig'))
        self.assertFalse(self.window.recovery_path.exists())

    def test_failed_export_does_not_replace_existing_file_or_clear_recovery(self):
        self.window.add_row()
        self.window.save_recovery()
        output = self.root / 'existing.srt'
        output.write_text('Original file', encoding='utf-8')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), '')), patch('PySide6.QtCore.QSaveFile.commit', return_value=False), patch.object(QMessageBox, 'warning'):
            self.assertFalse(self.window.export_srt())
        self.assertEqual(output.read_text(encoding='utf-8'), 'Original file')
        self.assertTrue(self.window.dirty)
        self.assertTrue(self.window.recovery_path.exists())

    def test_import_cancel_and_bad_input_preserve_history_and_rows(self):
        self.window.add_row()
        before = self.window.raw_cells()
        count = self.window.undo_stack.count()
        source = self.root / 'import.srt'
        source.write_text('1\n00:00:01,000 --> 00:00:02,000\nImported\n', encoding='utf-8')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')), patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.window.import_srt()
        self.assertEqual(self.window.raw_cells(), before)
        self.assertEqual(self.window.undo_stack.count(), count)
        source.write_text('Not an SRT', encoding='utf-8')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')), patch.object(QMessageBox, 'warning'):
            self.window.import_srt()
        self.assertEqual(self.window.raw_cells(), before)

    def test_transcription_replacement_can_be_undone(self):
        self.seed()
        before = self.window.raw_cells()
        self.window.transcription_complete([(500, 1500, 'Generated')])
        self.assertTrue(self.window.dirty)
        self.window.undo_stack.undo()
        self.assertEqual(self.window.raw_cells(), before)
        self.assertFalse(self.window.dirty)

    def test_autosave_timer_writes_raw_cells_and_undo_clears_copy(self):
        self.seed()
        self.window.autosave_timer.setInterval(10)
        self.window.table.item(0, 0).setText('half edited')
        QTest.qWait(100)
        data = read_snapshot(self.window.recovery_path)
        self.assertEqual(data['rows'][0][0], 'half edited')
        self.assertTrue(self.window.recovery_saved)
        self.window.undo_stack.undo()
        self.assertFalse(self.window.recovery_path.exists())

    def test_live_instance_is_skipped_and_crashed_session_recovers(self):
        self.seed()
        self.window.table.item(0, 2).setText('Recover café\nexactly')
        self.window.table.item(0, 0).setText('invalid-but-preserved')
        self.window.save_recovery()
        target = self.new_window()
        with patch.object(target, 'ask_recovery', return_value=QMessageBox.Yes) as ask:
            target.offer_recovery()
            ask.assert_not_called()
        # Simulate process death: retain the snapshot but release the process lock.
        self.window.autosave_timer.stop()
        self.window.recovery_lock.unlock()
        self.window.recovery_lock = None
        with patch.object(target, 'ask_recovery', return_value=QMessageBox.Yes):
            target.offer_recovery()
        self.assertEqual(target.raw_cells(), self.window.raw_cells())
        self.assertTrue(target.dirty)
        self.assertFalse(target.undo_stack.canUndo())

    def test_abrupt_process_exit_leaves_recoverable_copy_and_stale_lock(self):
        script = """
import os, sys
from PySide6.QtWidgets import QApplication
from main import MainWindow
app = QApplication([])
window = MainWindow(recovery_directory=sys.argv[1], offer_recovery=False)
window.add_row()
window.table.item(0, 2).setText('Survived abrupt process exit')
window.save_recovery()
assert window.recovery_path.is_file()
os._exit(0)
"""
        subprocess.run([sys.executable, '-c', script, str(self.root)], check=True, timeout=30, cwd=Path(main.__file__).parent)
        self.assertEqual(len(list(self.root.glob('*.json'))), 1)
        with patch.object(self.window, 'ask_recovery', return_value=QMessageBox.Yes):
            self.window.offer_recovery()
        self.assertEqual(self.window.raw_cells()[0][2], 'Survived abrupt process exit')
        self.assertTrue(self.window.dirty)

    def test_later_keeps_recovery_and_discard_removes_it(self):
        self.window.add_row()
        self.window.save_recovery()
        self.window.autosave_timer.stop()
        self.window.recovery_lock.unlock()
        self.window.recovery_lock = None
        target = self.new_window()
        with patch.object(target, 'ask_recovery', return_value=QMessageBox.Cancel):
            target.offer_recovery()
        self.assertTrue(self.window.recovery_path.exists())
        with patch.object(target, 'ask_recovery', return_value=QMessageBox.No):
            target.offer_recovery()
        self.assertFalse(self.window.recovery_path.exists())

    def test_empty_deletion_is_recoverable_and_can_be_saved(self):
        self.seed()
        self.window.table.selectAll()
        self.window.delete_row()
        self.assertTrue(self.window.dirty)
        self.assertTrue(self.window.export_button.isEnabled())
        self.window.save_recovery()
        data = read_snapshot(self.window.recovery_path)
        self.assertEqual(data['rows'], [])
        self.assertEqual(len(data['saved_rows']), 2)
        path = self.root / 'empty.srt'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')):
            self.assertTrue(self.window.export_srt())
        self.assertEqual(path.read_text(encoding='utf-8-sig'), '')
        self.assertFalse(self.window.dirty)

    def test_failed_autosave_keeps_previous_snapshot_and_warns(self):
        self.window.add_row()
        self.window.save_recovery()
        previous = self.window.recovery_path.read_bytes()
        self.window.table.item(0, 2).setText('Newer edit')
        with patch('recovery.os.replace', side_effect=PermissionError('Read only')):
            self.window.save_recovery()
        self.assertEqual(self.window.recovery_path.read_bytes(), previous)
        self.assertIn('unavailable', self.window.save_status.text())
        self.assertTrue(self.window.dirty)

    def test_corrupt_recovery_is_kept_without_replacing_current_document(self):
        path = self.root / 'damaged.json'
        path.write_text('{damaged', encoding='utf-8')
        with patch.object(self.window, 'ask_recovery') as ask:
            self.window.offer_recovery()
            ask.assert_not_called()
        self.assertTrue(path.exists())
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertIn('kept', self.window.statusBar().currentMessage())

    def test_undo_redo_actions_locked_during_transcription(self):
        self.window.add_row()
        self.assertTrue(self.window.undo_action.isEnabled())
        self.window.busy = True
        self.window.refresh_actions()
        self.assertFalse(self.window.undo_action.isEnabled())
        self.assertFalse(self.window.redo_action.isEnabled())
        self.window.busy = False

    def test_open_cell_edit_is_committed_before_close_warning(self):
        self.seed()
        self.window.show()
        self.window.activateWindow()
        self.window.table.setCurrentCell(0, 2)
        self.window.table.editItem(self.window.table.item(0, 2))
        APP.processEvents()
        editor = self.window.table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor, 'Uncommitted text')
        event = QCloseEvent()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel) as question:
            self.window.closeEvent(event)
            question.assert_called_once()
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.get_rows()[0][2], 'Uncommitted text')


class SnapshotTests(unittest.TestCase):
    def test_schema_rejects_wrong_cells_and_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.json'
            for data in ({'version': 2}, {'version': 1, 'rows': [[1, 2, 3]], 'saved_rows': []}):
                write_snapshot(path, data)
                with self.assertRaises(ValueError):
                    read_snapshot(path)


if __name__ == '__main__':
    unittest.main()
