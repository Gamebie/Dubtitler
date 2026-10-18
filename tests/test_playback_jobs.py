import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer
from audio_tracks import list_audio_tracks, default_audio_track, decode_audio_track
from smoke_media import make_media
from transcriber import Transcriber
from playback import replay_bounds
from recovery import read_snapshot
from main import MainWindow

APP = QApplication.instance() or QApplication([])


def blocked_job(connection, *_):
    connection.send(('progress', 'Blocked native-like work', -1))
    time.sleep(60)


def completed_job(connection, *_):
    connection.send(('completed', [(0, 1000, 'Done')]))
    connection.close()


def crashed_job(connection, *_):
    os._exit(7)


def wait_until(condition, seconds=8):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    return bool(condition())


def tone(frequency, seconds=2, rate=16000):
    return (np.sin(2 * np.pi * frequency * np.arange(round(rate * seconds)) / rate) * 0.3).astype(np.float32)


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'dual.mkv'
        make_media(cls.path, [tone(440), tone(880)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_metadata_and_english_default(self):
        tracks = list_audio_tracks(str(self.path))
        self.assertEqual([track['language'] for track in tracks], ['jpn', 'eng'])
        self.assertEqual([track['stream_index'] for track in tracks], [1, 2])
        self.assertEqual(default_audio_track(tracks), 1)

    def test_decoding_selects_requested_audio_not_first_stream(self):
        for index, expected in enumerate((440, 880)):
            audio = decode_audio_track(str(self.path), index)
            self.assertEqual(audio.dtype, np.float32)
            peak = np.argmax(abs(np.fft.rfft(audio))) * 16000 / len(audio)
            self.assertAlmostEqual(peak, expected, delta=1)

    def test_resampling_stereo_48k_to_mono_16k(self):
        path = Path(self.temp.name) / 'stereo.mkv'
        samples = tone(650, rate=48000)
        make_media(path, [np.column_stack((samples, samples))], rate=48000, languages=['eng'])
        audio = decode_audio_track(str(path), 0)
        self.assertEqual(audio.ndim, 1)
        self.assertAlmostEqual(len(audio), 32000, delta=16)
        peak = np.argmax(abs(np.fft.rfft(audio))) * 16000 / len(audio)
        self.assertAlmostEqual(peak, 650, delta=1)

    def test_leading_audio_offset_is_preserved_on_video_timeline(self):
        path = Path(self.temp.name) / 'delayed.mkv'
        make_media(path, [tone(440), tone(880)], starts=[0, 1])
        audio = decode_audio_track(str(path), 1)
        self.assertTrue(np.all(audio[:16000] == 0))
        self.assertGreater(np.max(abs(audio[16000:])), 0.2)
        self.assertAlmostEqual(len(audio) / 16000, 3, delta=0.01)

    def test_invalid_or_missing_tracks_fail_instead_of_using_first(self):
        for index in (-1, 5):
            with self.assertRaises(ValueError):
                decode_audio_track(str(self.path), index)
        path = Path(self.temp.name) / 'video-only.mkv'
        make_media(path)
        self.assertEqual(list_audio_tracks(str(path)), [])
        with self.assertRaises(ValueError):
            decode_audio_track(str(path), 0)

    def test_default_falls_back_and_avoids_english_commentary(self):
        tracks = [dict(index=0, language='eng', title='Commentary'), dict(index=1, language='en-US', title='English dub')]
        self.assertEqual(default_audio_track(tracks), 1)
        self.assertEqual(default_audio_track([dict(index=0, language='', title='')]), 0)
        self.assertIsNone(default_audio_track([]))


class BridgeTests(unittest.TestCase):
    def collect(self, target, cancel=False):
        worker = Transcriber('unused', 'base.en', target=target)
        completed, failed, cancelled, progress = [], [], [], []
        worker.completed.connect(completed.append)
        worker.failed.connect(failed.append)
        worker.cancelled.connect(lambda: cancelled.append(True))
        def phase(*args):
            progress.append(args)
            if cancel:
                worker.cancel()
        worker.progress.connect(phase)
        worker.start()
        finished = wait_until(lambda: not worker.isRunning(), 10)
        if not finished:
            worker.cancel()
            worker.wait(5000)
        APP.processEvents()
        self.assertTrue(finished, 'Bridge did not finish within timeout')
        self.assertIsNone(worker.process)
        return completed, failed, cancelled, progress

    def test_cancel_interrupts_blocked_work_and_reaps_child(self):
        completed, failed, cancelled, progress = self.collect(blocked_job, cancel=True)
        self.assertTrue(progress)
        self.assertEqual(cancelled, [True])
        self.assertFalse(completed or failed)

    def test_success_after_prior_cancel_can_start_fresh(self):
        self.collect(blocked_job, cancel=True)
        completed, failed, cancelled, _ = self.collect(completed_job)
        self.assertEqual(completed, [[(0, 1000, 'Done')]])
        self.assertFalse(failed or cancelled)

    def test_unexpected_child_exit_is_reported(self):
        completed, failed, cancelled, _ = self.collect(crashed_job)
        self.assertTrue(failed)
        self.assertFalse(completed or cancelled)

    def test_cancel_before_start_does_not_launch_child(self):
        worker = Transcriber('unused', 'base.en')
        cancelled = []
        worker.cancelled.connect(lambda: cancelled.append(True))
        worker.cancel()
        worker.run()
        self.assertEqual(cancelled, [True])
        self.assertIsNone(worker.process)


class PlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = str(Path(cls.temp.name) / 'dual.mkv')
        make_media(cls.path, [tone(440), tone(880)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.recovery_temp = tempfile.TemporaryDirectory()
        self.window = MainWindow(recovery_directory=self.recovery_temp.name, offer_recovery=False)
        self.window.load_video(self.path)
        self.assertTrue(wait_until(lambda: self.window.track_probe is None))
        self.assertTrue(wait_until(lambda: self.window.player.duration() > 0))
        # Controller tests should not depend on a physical audio output device.
        self.play_patch = patch.object(self.window.player, 'play')
        self.pause_patch = patch.object(self.window.player, 'pause')
        self.play_patch.start()
        self.pause_patch.start()

    def tearDown(self):
        if self.window.worker is not None and self.window.worker.isRunning():
            self.window.worker.cancel()
            self.window.worker.wait(5000)
            APP.processEvents()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.play_patch.stop()
        self.pause_patch.stop()
        self.recovery_temp.cleanup()

    def cue(self):
        self.window.set_rows([(600, 1000, 'Selected'), (1200, 1500, 'Next')], clean=True)
        self.window.table.selectRow(0)

    def test_real_track_choice_updates_preview_and_recovery(self):
        self.assertEqual(self.window.audio_tracks.currentData(), 1)
        self.assertTrue(wait_until(lambda: len(self.window.player.audioTracks()) == 2))
        self.window.sync_playback_audio()
        self.assertEqual(self.window.player.activeAudioTrack(), 1)
        self.window.audio_tracks.setCurrentIndex(0)
        self.assertEqual(self.window.player.activeAudioTrack(), 0)
        self.window.add_row()
        self.window.save_recovery()
        self.assertEqual(read_snapshot(self.window.recovery_path)['audio_index'], 0)

    def test_explicit_recovered_track_overrides_automatic_default(self):
        self.window.load_video(self.path, preferred_audio_index=0)
        self.assertTrue(wait_until(lambda: self.window.track_probe is None))
        self.assertEqual(self.window.audio_tracks.currentData(), 0)

    def test_no_audio_disables_transcription(self):
        path = str(Path(self.temp.name) / 'silent-video.mkv')
        make_media(path)
        self.window.load_video(path)
        self.assertTrue(wait_until(lambda: self.window.track_probe is None))
        self.assertFalse(self.window.transcribe_button.isEnabled())
        self.assertIn('no audio', self.window.track_hint.text().lower())

    def test_replay_stops_at_end_with_context(self):
        self.cue()
        with patch.object(self.window.player, 'play'), patch.object(self.window.player, 'pause') as pause, patch.object(self.window.player, 'setPosition') as seek:
            self.window.replay_selected()
            self.assertEqual(self.window.replay_range, (100, 1500))
            with patch.object(self.window.player, 'position', return_value=100):
                self.window.check_replay()
            with patch.object(self.window.player, 'position', return_value=1500):
                self.window.check_replay()
            self.assertIsNone(self.window.replay_range)
            pause.assert_called()
            seek.assert_called_with(1500)

    def test_loop_restarts_and_end_of_media_is_handled(self):
        self.cue()
        self.window.loop_replay.setChecked(True)
        with patch.object(self.window.player, 'play') as play, patch.object(self.window.player, 'setPosition') as seek:
            self.window.replay_selected()
            self.window.replay_media_status(QMediaPlayer.EndOfMedia)
            self.assertEqual(self.window.replay_range, (100, 1500))
            seek.assert_called_with(100)
            self.assertGreaterEqual(play.call_count, 2)

    def test_short_cue_overshoot_does_not_leave_replay_running(self):
        self.window.replay_range = (100, 110)
        self.window.replay_seeking = True
        with patch.object(self.window.player, 'position', return_value=130):
            self.window.check_replay()
        self.assertIsNone(self.window.replay_range)

    def test_manual_seek_selection_edit_and_track_change_stop_loop(self):
        self.cue()
        for action in (lambda: self.window.manual_seek(800), lambda: self.window.table.selectRow(1), lambda: self.window.table.item(0, 2).setText('Edited'), lambda: self.window.audio_tracks.setCurrentIndex(0)):
            self.window.table.selectRow(0)
            self.window.loop_replay.setChecked(True)
            self.window.replay_selected()
            action()
            self.assertIsNone(self.window.replay_range)

    def test_invalid_timing_has_clear_replay_error(self):
        self.cue()
        self.window.table.item(0, 0).setText('invalid')
        with patch.object(QMessageBox, 'warning') as warning:
            self.window.replay_selected()
            warning.assert_called_once()
        self.assertIsNone(self.window.replay_range)

    def test_cancellation_ignores_queued_results_and_keeps_edits(self):
        self.cue()
        self.window.table.item(0, 2).setText('Keep my edit')
        self.window.save_recovery()
        rows = self.window.raw_cells()
        self.window.busy = True
        self.window.worker = Mock()
        self.window.cancel_transcription()
        self.assertTrue(self.window.cancel_pending)
        self.assertFalse(self.window.cancel_button.isEnabled())
        self.window.transcription_progress('Late progress', 99)
        self.window.transcription_complete([(0, 2000, 'Late result')])
        self.window.transcription_failed('Late failure')
        self.window.transcription_finished()
        self.assertEqual(self.window.raw_cells(), rows)
        self.assertTrue(self.window.recovery_path.exists())
        self.assertEqual(self.window.progress_bar.value(), 0)
        self.assertFalse(self.window.busy)
        self.window.worker = None

    def test_cancel_after_result_is_applied_cannot_relabel_success(self):
        self.window.busy = True
        worker = Mock()
        self.window.worker = worker
        self.window.transcription_complete([(0, 1000, 'Finished result')])
        self.window.cancel_transcription()
        worker.cancel.assert_not_called()
        self.assertFalse(self.window.cancel_pending)
        self.assertFalse(self.window.cancel_button.isEnabled())
        self.window.transcription_finished()
        self.assertEqual(self.window.progress_bar.value(), 100)
        self.window.worker = None


class BoundsTests(unittest.TestCase):
    def test_context_clamps_to_video_edges(self):
        self.assertEqual(replay_bounds(100, 1900, 2000, 500), (0, 2000))
        for values in ((-1, 10, 20, 0), (10, 5, 20, 0), (10, 20, 0, 0), (100, 200, 50, 0)):
            with self.assertRaises(ValueError):
                replay_bounds(*values)


if __name__ == '__main__':
    unittest.main()
