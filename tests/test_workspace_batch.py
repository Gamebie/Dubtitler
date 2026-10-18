import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QPoint
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QLineEdit, QDialog
from PySide6.QtTest import QTest
from main import MainWindow
from project_store import read_project, save_project, write_new_srt
from timeline_checks import document_warnings
from waveform import waveform_job
from batch_queue import BatchDialog, batch_job

APP = QApplication.instance() or QApplication([])


def wait(check, seconds=5):
    import time
    end = time.monotonic() + seconds
    while not check() and time.monotonic() < end:
        QTest.qWait(10)
    return bool(check())


class StoreTests(unittest.TestCase):
    def test_project_preserves_raw_invalid_cells_and_rejects_bad_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'project.dubtitler'
            data = dict(version=1, rows=[['half edited', '00:00:02,000', '日本 🎉']], saved_rows=[], position=1200, audio_index=1, options={'names': 'Seijou'}, video_path='missing.mkv', srt_path=None)
            save_project(path, data)
            self.assertEqual(read_project(path)['rows'], data['rows'])
            previous = path.read_bytes()
            with patch('recovery.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_project(path, data)
            self.assertEqual(path.read_bytes(), previous)
            for key, value in (('rows', [['bad']]), ('position', -1), ('audio_index', 'one'), ('options', {'names': 1})):
                with self.assertRaises(ValueError):
                    save_project(path, dict(data, **{key: value}))

    def test_batch_export_never_overwrites_and_rejects_invalid_before_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'episode.srt').write_text('Keep existing')
            rows = [(0, 2000, 'Seijou 🎉')]
            a = write_new_srt(root, 'episode', rows)
            b = write_new_srt(root, 'episode', rows)
            self.assertEqual((a.name, b.name), ('episode_2.srt', 'episode_3.srt'))
            self.assertEqual((root / 'episode.srt').read_text(), 'Keep existing')
            self.assertIn('Seijou 🎉', a.read_text(encoding='utf-8-sig'))
            with self.assertRaises(ValueError):
                write_new_srt(root, 'bad', [(2000, 1000, 'Invalid')])
            self.assertFalse((root / 'bad.srt').exists())
            self.assertFalse(list(root.glob('*.tmp')))

    def test_checks_find_nested_overlap_duplicates_and_intentional_gaps(self):
        rows = [('00:00:00,000', '00:00:10,000', 'Long'), ('00:00:01,000', '00:00:02,000', 'Yes'), ('00:00:01,500', '00:00:02,500', 'yes'), ('00:00:14,000', '00:00:15,000', 'Later')]
        warnings = document_warnings(rows)
        self.assertTrue(any('Overlaps row 1' in s for s in warnings[2]))
        self.assertTrue(any('duplicate' in s for s in warnings[1]))
        self.assertTrue(any('4.0s' in s and 'intentional' in s for s in warnings[3]))
        self.assertFalse(any('Gap' in s for s in warnings[1]))

    def test_waveform_envelope_uses_selected_track_and_preserves_timeline(self):
        import numpy as np
        connection = Mock()
        audio = np.concatenate([np.zeros(8000), np.ones(8000) * .6]).astype(np.float32)
        with patch('audio_tracks.decode_audio_track', return_value=audio) as decode:
            waveform_job(connection, 'video', '', False, 1, None)
        decode.assert_called_once_with('video', 1)
        _, result = connection.send.call_args.args[0]
        self.assertEqual(result[0], 1000)
        self.assertEqual(result[1][0], 0)
        self.assertAlmostEqual(result[1][-1], .6)
        connection.close.assert_called_once()

    def test_auto_batch_requires_tagged_english_and_prefers_non_commentary(self):
        connection = Mock()
        tracks = [dict(index=0, language='jpn', title='Original'), dict(index=1, language='eng', title='Commentary'), dict(index=2, language='eng', title='Dub')]
        with patch('audio_tracks.list_audio_tracks', return_value=tracks), patch('transcription_job.run_job') as run:
            batch_job(connection, 'video', 'base.en', False, -1, {'names': 'Seijou'})
        self.assertEqual(run.call_args.args[4], 2)
        with patch('audio_tracks.list_audio_tracks', return_value=tracks[:1]), patch('transcription_job.run_job') as run:
            batch_job(connection, 'video', 'base.en', False, -1, {})
        run.assert_not_called()
        self.assertIn('No tagged English', connection.send.call_args.args[0][1])


class FakeWorker(QObject):
    progress = Signal(str, int)
    completed = Signal(list)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, outcome):
        super().__init__()
        self.outcome, self.cancelled_flag = outcome, False

    def start(self):
        QTimer.singleShot(15, self.run)

    def cancel(self):
        self.cancelled_flag = True

    def run(self):
        if self.cancelled_flag:
            self.cancelled.emit()
        elif isinstance(self.outcome, str):
            self.failed.emit(self.outcome)
        else:
            self.completed.emit(self.outcome)
        self.finished.emit()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.windows = []
        self.w = self.new_window()
        self.w.show()
        for method in ('warning', 'information'):
            p = patch.object(QMessageBox, method)
            p.start()
            self.addCleanup(p.stop)
        APP.processEvents()

    def new_window(self):
        window = MainWindow(recovery_directory=self.root / 'recovery', offer_recovery=False, profiles_directory=self.root / 'profiles', workspace_directory=self.root / 'workspace')
        self.windows.append(window)
        return window

    def tearDown(self):
        for w in self.windows:
            w.project_save_error = None
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
                w.close()
            w.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def seed(self):
        self.w.set_rows([(1000, 4000, 'Say Joe'), (5000, 7000, 'Next')], clean=True)

    def test_project_autosave_reopen_recents_and_export_baseline(self):
        w = self.w
        self.seed()
        w.video_path = str(self.root / 'missing-video.mkv')
        w.name_hints.setText('Seijou')
        w.begin_project_session()
        w.table.item(0, 0).setText('half edited')
        w.project_timer.setInterval(10)
        self.assertTrue(wait(lambda: Path(w.project_path).is_file()))
        path = w.project_path
        data = read_project(path)
        self.assertEqual(data['rows'][0][0], 'half edited')
        self.assertEqual(data['options']['names'], 'Seijou')
        w.remember_project()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            w.close()
        other = self.new_window()
        self.assertIn(str(path), other.preferences['recent'])
        self.assertTrue(other.open_project(str(path)))
        self.assertEqual(other.raw_cells()[0][0], 'half edited')
        self.assertTrue(other.dirty)
        self.assertIn('video missing', other.video_label.text())
        self.assertEqual(other.undo_stack.count(), 0)

    def test_project_lock_protects_other_window_and_corrupt_project_keeps_editor(self):
        w = self.w
        self.seed()
        w.begin_project_session()
        self.assertTrue(w.autosave_project())
        other = self.new_window()
        self.assertFalse(other.open_project(str(w.project_path)))
        self.assertEqual(other.raw_cells(), ())
        broken = self.root / 'broken.dubtitler'
        broken.write_text('broken')
        before = w.raw_cells()
        self.assertFalse(w.open_project(str(broken)))
        self.assertEqual(w.raw_cells(), before)

    def test_reopening_current_project_uses_latest_edits_and_keeps_resume_state_if_video_missing(self):
        self.seed()
        w = self.w
        w.begin_project_session()
        w.autosave_project()
        path = w.project_path
        w.table.item(0, 2).setText('Latest edit')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.assertTrue(w.open_project(str(path)))
        self.assertEqual(w.raw_cells()[0][2], 'Latest edit')
        w.project_restore_position = 12345
        w.audio_tracks.clear()
        w.audio_tracks.addItem('Saved track 3', 2)
        w.autosave_project()
        self.assertEqual(read_project(path)['position'], 12345)
        self.assertEqual(read_project(path)['audio_index'], 2)

    def test_project_save_as_cannot_replace_video_and_keeps_old_path_on_failure(self):
        self.seed()
        w = self.w
        video = self.root / 'video.mkv'
        video.write_bytes(b'video content')
        w.video_path = str(video)
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(video), '')):
            w.save_project_as()
        self.assertEqual(video.read_bytes(), b'video content')
        w.begin_project_session()
        w.autosave_project()
        original = w.project_path
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.root / 'new.dubtitler'), '')), patch('workspace_tools.save_project', side_effect=OSError('full')):
            w.save_project_as()
        self.assertEqual(w.project_path, original)

    def test_real_video_session_waveform_and_audio_selection_reopen(self):
        from smoke_media import make_media
        import numpy as np
        w = self.w
        video = str(self.root / 'episode.mkv')
        tone = np.sin(2 * np.pi * 440 * np.arange(32000) / 16000).astype(np.float32) * .4
        make_media(video, [np.zeros(32000, dtype=np.float32), tone])
        self.assertTrue(w.open_video(video))
        self.assertTrue(wait(lambda: w.track_probe is None and w.player.duration() > 0))
        self.assertTrue(wait(lambda: w.wave_worker is None and bool(w.waveform.peaks), 20))
        self.assertEqual(w.audio_tracks.currentData(), 1)
        self.assertGreater(max(w.waveform.peaks), .3)
        path = w.project_path
        w.set_rows([(100, 900, 'Saved cue')], clean=True)
        self.assertTrue(wait(lambda: w.player.isSeekable()))
        w.player.setPosition(500)
        self.assertTrue(wait(lambda: abs(w.player.position() - 500) < 120))
        w.autosave_project()
        self.assertAlmostEqual(read_project(path)['position'], 500, delta=120)
        w.close()
        self.assertAlmostEqual(read_project(path)['position'], 500, delta=120)
        other = self.new_window()
        self.assertTrue(other.open_project(str(path)))
        self.assertTrue(wait(lambda: other.track_probe is None and other.player.duration() > 0))
        self.assertEqual(other.audio_tracks.currentData(), 1)
        self.assertEqual(other.raw_cells()[0][2], 'Saved cue')
        self.assertTrue(wait(lambda: abs(other.player.position() - 500) < 120))

    def test_cancelled_waveform_restarts_even_for_same_latest_track(self):
        import threading
        w = self.w
        worker = Mock()
        worker.cancel_requested = threading.Event()
        worker.cancel_requested.set()
        w.wave_worker = worker
        w.wave_request = w.wave_pending = ('episode.mkv', 1)
        with patch.object(w, 'request_waveform') as request:
            w.waveform_finished()
            request.assert_called_once_with(('episode.mkv', 1))
        w.wave_worker = None
        w.wave_pending = None

    def test_batch_closing_cancels_active_job_and_keeps_prior_exports(self):
        dialog = BatchDialog(self.w, lambda *a, **k: FakeWorker([(0, 1000, 'Done')]))
        dialog.add_paths([self.root / 'one.mkv', self.root / 'two.mkv'])
        dialog.directory.setText(str(self.root / 'exports'))
        dialog.start_queue()
        dialog.reject()
        self.assertTrue(dialog.stopping)
        self.assertTrue(wait(lambda: not dialog.running))
        self.assertEqual(dialog.outputs, [])
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_project_failed_save_keeps_existing_file_and_blocks_close(self):
        w = self.w
        self.seed()
        w.begin_project_session()
        w.autosave_project()
        previous = Path(w.project_path).read_bytes()
        w.table.item(0, 2).setText('Changed')
        with patch('project_store.save_project', side_effect=OSError('disk full')):
            # Workspace imports the function directly; patch that binding too.
            with patch('workspace_tools.save_project', side_effect=OSError('disk full')):
                self.assertFalse(w.flush_project())
        self.assertEqual(Path(w.project_path).read_bytes(), previous)
        self.assertTrue(w.dirty)

    def test_navigation_commits_pending_dialogue_and_wraps(self):
        from PySide6.QtWidgets import QLineEdit
        self.seed()
        w = self.w
        w.navigate_cue(1, edit=True)
        APP.processEvents()
        editor = APP.focusWidget()
        self.assertIsInstance(editor, QLineEdit)
        editor.setText('Edited')
        w.navigate_cue(1)
        self.assertEqual(w.raw_cells()[0][2], 'Edited')
        self.assertEqual(w.table.currentRow(), 1)
        w.navigate_cue(1)
        self.assertEqual(w.table.currentRow(), 0)

    def test_waveform_drag_is_one_undo_and_click_seeks(self):
        self.seed()
        w = self.w
        w.waveform.set_audio(10000, [.5] * 500)
        w.table.selectRow(0)
        w.sync_waveform()
        wave = w.waveform
        before = w.raw_cells()
        x = round(wave.x(4000))
        QTest.mousePress(wave, Qt.LeftButton, pos=QPoint(x, 40))
        QTest.mouseMove(wave, QPoint(round(wave.x(4500)), 40))
        QTest.mouseRelease(wave, Qt.LeftButton, pos=QPoint(round(wave.x(4500)), 40))
        self.assertAlmostEqual(int(w.raw_cells()[0][1][-3:]), 500, delta=10)
        self.assertEqual(w.undo_stack.count(), 1)
        w.undo_stack.undo()
        self.assertEqual(w.raw_cells(), before)
        with patch.object(w, 'manual_seek') as seek:
            # Signal is connected to the original slot; inspect emitted position.
            positions = []
            wave.seek.connect(positions.append)
            QTest.mouseClick(wave, Qt.LeftButton, pos=QPoint(round(wave.x(8000)), 40))
            self.assertAlmostEqual(positions[0], 8000, delta=10)

    def test_export_overwrite_no_preserves_file_and_remembers_folder_filename(self):
        self.seed()
        w = self.w
        output = self.root / 'chosen-name.srt'
        output.write_text('Keep existing')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), '')), patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            self.assertFalse(w.export_srt())
        self.assertEqual(output.read_text(), 'Keep existing')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), '')), patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self.assertTrue(w.export_srt())
        self.assertTrue(Path(w.export_default()).samefile(output))
        other = self.new_window()
        self.assertTrue(Path(other.export_default()).samefile(output))

    def test_batch_success_failure_retry_cancel_and_editor_unchanged(self):
        self.seed()
        w = self.w
        original = w.raw_cells()
        answers = [[(0, 1000, 'First')], 'Bad audio', [(0, 1000, 'Retried')]]
        factory = lambda *a, **k: FakeWorker(answers.pop(0))
        dialog = BatchDialog(w, factory)
        dialog.add_paths([self.root / 'one.mkv', self.root / 'two.mkv'])
        dialog.directory.setText(str(self.root / 'exports'))
        dialog.start_queue()
        self.assertTrue(wait(lambda: not dialog.running))
        self.assertEqual(len(dialog.outputs), 1)
        self.assertIn('Bad audio', dialog.table.item(1, 2).text())
        dialog.start_queue()
        self.assertTrue(wait(lambda: not dialog.running))
        self.assertEqual(len(dialog.outputs), 2)
        self.assertEqual(w.raw_cells(), original)
        cancel = BatchDialog(w, lambda *a, **k: FakeWorker([(0, 1000, 'Should not write')]))
        cancel.add_paths([self.root / 'cancel.mkv', self.root / 'later.mkv'])
        cancel.directory.setText(str(self.root / 'exports'))
        cancel.start_queue()
        cancel.completed([(0, 1000, 'Queued before cancel')])
        cancel.cancel_queue()
        self.assertTrue(wait(lambda: not cancel.running))
        self.assertEqual(cancel.outputs, [])
        self.assertFalse((self.root / 'exports' / 'cancel.srt').exists())
        self.assertEqual(cancel.table.item(1, 2).text(), 'Queued')
        dialog.close()
        cancel.close()


if __name__ == '__main__':
    unittest.main()
