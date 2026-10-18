import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QCloseEvent
import main
import model_runtime as runtime
from transcription_job import run_job

TRACK = dict(index=0, stream_index=0, language="eng", title="English", codec="pcm_s16le", channels=1)

APP = QApplication.instance() or QApplication([])


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.recovery_temp = tempfile.TemporaryDirectory()
        def probe(window, path):
            window.tracks_found(path, [TRACK])
        self.probe_patch = patch.object(main.MainWindow, 'start_track_probe', probe)
        self.probe_patch.start()
        self.window = main.MainWindow(recovery_directory=self.recovery_temp.name, offer_recovery=False)

    def tearDown(self):
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.recovery_temp.cleanup()
        self.probe_patch.stop()

    def test_initial_guidance_and_actions(self):
        self.assertFalse(self.window.transcribe_button.isEnabled())
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertTrue(self.window.open_button.isEnabled())
        self.assertTrue(self.window.import_button.isEnabled())
        self.assertEqual(self.window.model.currentData(), 'base.en')
        self.assertFalse(self.window.allow_download.isChecked())

    def test_video_selection_and_cancel(self):
        with patch.object(main.QFileDialog, 'getOpenFileName', return_value=('', '')):
            self.window.open_video()
        self.assertIsNone(self.window.video_path)
        with patch.object(main.QFileDialog, 'getOpenFileName', return_value=('example.mp4', '')):
            self.window.open_video()
        self.assertTrue(self.window.transcribe_button.isEnabled())
        self.assertEqual(self.window.video_label.text(), 'example.mp4')

    def test_switch_video_requires_explicit_clear(self):
        self.window.set_rows([(0, 1000, 'Keep me')])
        with patch.object(main.QFileDialog, 'getOpenFileName', return_value=('next.mp4', '')):
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
                self.window.open_video()
            self.assertEqual(self.window.get_rows()[0][2], 'Keep me')
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
                self.window.open_video()
        self.assertEqual(self.window.get_rows(), [])

    def test_edit_overlay_add_delete_and_timing_validation(self):
        self.window.set_rows([(1000, 2000, 'Hello')])
        self.window.table.item(0, 2).setText('Edited')
        self.window.update_caption(1500)
        self.assertEqual(self.window.caption.text(), 'Edited')
        self.window.add_row()
        self.assertEqual(self.window.table.rowCount(), 2)
        self.window.delete_row()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.window.table.item(0, 1).setText('00:00:00,500')
        with self.assertRaisesRegex(ValueError, 'end must be after start'):
            self.window.get_rows()
        self.window.set_rows([])
        self.assertFalse(self.window.export_button.isEnabled())

    def test_srt_roundtrip_multiline_unicode_sorted(self):
        expected = [(0, 500, 'First'), (1000, 2000, 'Hello café\nSecond line')]
        self.window.set_rows(list(reversed(expected)))
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'test.srt')
            with patch.object(main.QFileDialog, 'getSaveFileName', return_value=(path, '')):
                self.window.export_srt()
            self.assertTrue(Path(path).read_bytes().startswith(b'\xef\xbb\xbf'))
            self.window.set_rows([])
            with patch.object(main.QFileDialog, 'getOpenFileName', return_value=(path, '')):
                self.window.import_srt()
            self.assertEqual(self.window.get_rows(), expected)

    def test_export_write_error_keeps_rows(self):
        self.window.set_rows([(0, 1000, 'Keep')])
        with patch.object(main.QFileDialog, 'getSaveFileName', return_value=('x.srt', '')):
            with patch('PySide6.QtCore.QSaveFile.open', return_value=False):
                with patch.object(QMessageBox, 'warning') as warning:
                    self.window.export_srt()
                    warning.assert_called_once()
        self.assertEqual(self.window.get_rows(), [(0, 1000, 'Keep')])

    def test_busy_locks_inputs_and_close_without_losing_rows(self):
        self.window.video_path = 'example.mp4'
        self.window.tracks_found('example.mp4', [TRACK])
        self.window.set_rows([(0, 1000, 'Keep')])
        self.window.busy = True
        self.window.worker = Mock(isRunning=lambda: True)
        self.window.refresh_actions()
        for widget in (self.window.open_button, self.window.model, self.window.transcribe_button,
                       self.window.import_button, self.window.export_button, self.window.table):
            self.assertFalse(widget.isEnabled())
        event = QCloseEvent()
        with patch.object(QMessageBox, 'information'):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.window.worker = None
        with patch.object(QMessageBox, 'critical'):
            self.window.transcription_failed('Test failure')
        self.window.transcription_finished()
        self.assertTrue(self.window.transcribe_button.isEnabled())
        self.assertEqual(self.window.get_rows(), [(0, 1000, 'Keep')])
        self.assertEqual(self.window.progress_bar.value(), 0)

    def test_progress_busy_to_measured_and_empty_completion(self):
        self.window.transcription_progress('Loading', -1)
        self.assertEqual(self.window.progress_bar.maximum(), 0)
        self.window.transcription_progress('Audio position', 42)
        self.assertEqual(self.window.progress_bar.maximum(), 100)
        self.assertEqual(self.window.progress_bar.value(), 42)
        self.window.transcription_complete([])
        self.assertEqual(self.window.progress_bar.value(), 100)
        self.assertIn('no speech', self.window.progress_label.text())
        self.assertFalse(self.window.export_button.isEnabled())


class TranscriptionTests(unittest.TestCase):
    def transcribe(self, duration, ends, fail=False):
        def segments():
            for end in ends:
                yield SimpleNamespace(start=max(0, end - 1), end=end, text=' Hello ')
            if fail:
                raise RuntimeError('Decode failed')
        model = Mock()
        model.transcribe.return_value = (segments(), SimpleNamespace(duration=duration))
        connection = Mock()
        messages = []
        connection.send.side_effect = messages.append
        with patch('transcription_job.load_model', return_value=model), patch('transcription_job.decode_audio_track', return_value=[]):
            run_job(connection, 'video.mp4', 'base.en', False, 0)
        events = [(m[1], m[2]) for m in messages if m[0] == 'progress']
        completed = [m[1] for m in messages if m[0] == 'completed']
        failed = [m[1] for m in messages if m[0] == 'failed']
        return events, completed, failed

    def test_real_segment_positions_monotonic_clamped_below_complete(self):
        events, rows, errors = self.transcribe(100, [20, 10, 100, 110])
        self.assertEqual([n for _, n in events if n >= 0], [0, 20, 20, 99, 99])
        self.assertEqual(rows[0][0], (19000, 20000, 'Hello'))
        self.assertFalse(errors)

    def test_unknown_duration_and_silence(self):
        for duration in (0, float('nan'), float('inf')):
            events, rows, errors = self.transcribe(duration, [])
            self.assertTrue(all(n == -1 for _, n in events))
            self.assertEqual(rows, [[]])
            self.assertFalse(errors)

    def test_generator_failure_never_emits_partial_success(self):
        _, rows, errors = self.transcribe(20, [5], fail=True)
        self.assertFalse(rows)
        self.assertEqual(errors, ['Decode failed'])


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def model_dir(self, name='base.en', vocabulary='vocabulary.txt'):
        path = self.root / 'models' / name
        path.mkdir(parents=True)
        for file in (*runtime.MODEL_FILES[:3], vocabulary):
            (path / file).write_text('test')
        return path

    def test_frozen_uses_executable_directory(self):
        with patch.object(runtime.sys, 'frozen', True, create=True), patch.object(runtime.sys, 'executable', str(self.root / 'Dubtitler.exe')):
            self.assertTrue(runtime.app_directory().samefile(self.root))

    def test_bundle_loaded_by_path_never_downloaded(self):
        path = self.model_dir()
        with patch.object(runtime, 'app_directory', return_value=self.root):
            with patch('faster_whisper.WhisperModel') as model, patch('faster_whisper.utils.download_model') as download:
                runtime.load_model('base.en', Mock())
                model.assert_called_once_with(str(path), device='cpu', compute_type='int8', local_files_only=True)
                download.assert_not_called()

    def test_multilingual_vocabulary_json_is_supported(self):
        path = self.model_dir('tiny', 'vocabulary.json')
        self.assertTrue(runtime.complete_model(path))
        (path / 'tokenizer.json').write_text('')
        self.assertFalse(runtime.complete_model(path))

    def test_custom_cache_and_legacy_cache(self):
        path = self.model_dir('tiny', 'vocabulary.json')
        for answers in ([str(path)], [OSError('Missing'), str(path)]):
            with patch.object(runtime, 'bundled_model', return_value=None):
                with patch('faster_whisper.utils.download_model', side_effect=answers) as download:
                    with patch('faster_whisper.WhisperModel'):
                        runtime.load_model('tiny', Mock())
                    self.assertTrue(all(c.kwargs['local_files_only'] for c in download.call_args_list))

    def test_missing_model_never_downloads_without_opt_in(self):
        with patch.object(runtime, 'bundled_model', return_value=None):
            with patch('faster_whisper.utils.download_model', side_effect=OSError('Missing')) as download:
                with self.assertRaisesRegex(RuntimeError, 'one-time model download'):
                    runtime.load_model('tiny', Mock())
                self.assertEqual(download.call_count, 2)
                self.assertTrue(all(c.kwargs['local_files_only'] for c in download.call_args_list))

    def test_download_opt_in_and_incomplete_result(self):
        path = self.model_dir('tiny', 'vocabulary.json')
        with patch.object(runtime, 'bundled_model', return_value=None):
            with patch('faster_whisper.utils.download_model', side_effect=[OSError(), OSError(), str(path)]) as download:
                with patch('faster_whisper.WhisperModel'):
                    runtime.load_model('tiny', Mock(), allow_download=True)
                self.assertNotIn('local_files_only', download.call_args.kwargs)
            (path / 'model.bin').unlink()
            with patch('faster_whisper.utils.download_model', side_effect=[OSError(), OSError(), str(path)]):
                with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                    runtime.load_model('tiny', Mock(), allow_download=True)

    def test_corrupt_bundle_reports_reextract_without_network(self):
        with patch.object(runtime, 'bundled_model', return_value=self.root):
            with patch('faster_whisper.WhisperModel', side_effect=ValueError('Corrupt')):
                with patch('faster_whisper.utils.download_model') as download:
                    with self.assertRaisesRegex(RuntimeError, 'Extract the full Offline ZIP'):
                        runtime.load_model('base.en', Mock(), allow_download=True)
                    download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
