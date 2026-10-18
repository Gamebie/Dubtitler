"""Run as Dubtitler.exe --smoke-test RESULT.json [speech.wav]."""
import hashlib
import json
import os
import socket
import traceback
import tempfile
import wave
import time
from pathlib import Path


def run(args):
    result_path = Path(args[0]) if args else Path('smoke-result.json')
    result = {'ok': False}
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['DUBTITLER_OFFLINE_TEST'] = '1'

    def no_network(*_):
        raise RuntimeError('Network attempted during offline smoke test')

    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    try:
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from main import MainWindow
        from transcriber import Transcriber
        from audio_tracks import decode_audio_track, list_audio_tracks
        from smoke_media import make_media
        from unittest.mock import patch
        from model_runtime import DEFAULT_MODEL, bundled_model, load_model
        app = QApplication.instance() or QApplication([])
        recovery_temp = tempfile.TemporaryDirectory()
        window = MainWindow(recovery_directory=recovery_temp.name, offer_recovery=False, profiles_directory=Path(recovery_temp.name) / 'profiles')
        window.show()
        app.processEvents()
        assert not window.transcribe_button.isEnabled()
        assert not window.export_button.isEnabled()
        window.add_row()
        assert window.export_button.isEnabled()
        window.undo_stack.undo()
        assert window.table.rowCount() == 0
        window.undo_stack.redo()
        assert window.table.rowCount() == 1
        window.save_recovery()
        assert window.recovery_path.is_file()
        def wait_until(check, timeout=45):
            deadline = time.monotonic() + timeout
            while not check() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            app.processEvents()
            assert check(), 'Portable diagnostic timed out'

        def worker_check(path, index, cancel=False):
            worker = Transcriber(path, DEFAULT_MODEL, audio_index=index)
            completed, failed, cancelled = [], [], []
            worker.completed.connect(completed.append)
            worker.failed.connect(failed.append)
            worker.cancelled.connect(lambda: cancelled.append(True))
            if cancel:
                worker.progress.connect(lambda *_: worker.cancel())
            worker.start()
            try:
                wait_until(lambda: not worker.isRunning())
            finally:
                if worker.isRunning():
                    worker.cancel()
                    worker.wait(5000)
            assert worker.process is None, 'Transcription child was not reaped'
            assert not failed, failed
            if cancel:
                assert cancelled and not completed, 'Cancellation applied a result'
            else:
                assert completed and not cancelled, 'No transcription result'
            return completed

        with tempfile.TemporaryDirectory() as media_temp:
            fixture = str(Path(media_temp) / 'dual-track.mkv')
            tone = (0.3 * np.sin(2 * np.pi * 880 * np.arange(16000) / 16000)).astype(np.float32)
            make_media(fixture, [np.zeros(16000, dtype=np.float32), tone])
            assert len(list_audio_tracks(fixture)) == 2
            decoded = decode_audio_track(fixture, 1)
            assert np.max(abs(decoded)) > 0.2
            assert np.max(abs(decode_audio_track(fixture, 0))) == 0
            window.load_video(fixture)
            wait_until(lambda: window.track_probe is None and len(window.player.audioTracks()) == 2)
            assert window.audio_tracks.currentData() == 1
            assert window.player.activeAudioTrack() == 1
            window.set_rows([(500, 1000, 'Replay test')], clean=True)
            window.table.selectRow(0)
            with patch.object(window.player, 'play'), patch.object(window.player, 'pause'):
                window.replay_selected()
                assert window.replay_range == (0, 1500)
                window.loop_replay.setChecked(True)
                window.replay_boundary()
                assert window.replay_range == (0, 1500)
                window.loop_replay.setChecked(False)
                window.replay_boundary()
                assert window.replay_range is None
            # Exercise spawn and cancellation from the actual frozen executable.
            worker_check(fixture, 0, cancel=True)
            assert worker_check(fixture, 0) == [[]]
            # Exercise the manual workflow in the frozen app, including persistence
            # and a real Qt file-drop event. Never touch the user's profile folder.
            from PySide6.QtWidgets import QDialog, QPlainTextEdit, QFileDialog
            from PySide6.QtCore import QMimeData, QUrl, QPoint, QPointF, Qt, QItemSelectionModel
            from PySide6.QtGui import QDragEnterEvent, QDropEvent
            window.profile_store.update('Smoke show', {'names': 'Seijou', 'replacements': 'say joe => Seijou'})
            window.reload_profiles()
            window.load_show_profile('Smoke show')
            assert window.name_hints.text() == 'Seijou'
            window.set_rows([(100, 1900, 'Say Joe is ready')], clean=True)
            original = window.raw_cells()
            window.open_find_replace()
            window.find_dialog.find.setText('say joe')
            window.find_dialog.replacement.setText('Seijou')
            window.replace_dialog_matches()
            assert window.raw_cells()[0][2] == 'Seijou is ready'
            window.undo_stack.undo()
            assert window.raw_cells() == original
            window.find_dialog.hide()
            window.shift_timing(25)
            assert window.raw_cells()[0][0] == '00:00:00,125'
            window.undo_stack.undo()
            window.apply_saved_rules()
            assert window.raw_cells()[0][2] == 'Seijou is ready'
            window.table.selectRow(0)
            def choose_split(dialog):
                text = dialog.findChild(QPlainTextEdit)
                cursor = text.textCursor()
                cursor.setPosition(6)
                text.setTextCursor(cursor)
                return QDialog.Accepted
            with patch.object(window.player, 'position', return_value=900), patch.object(QDialog, 'exec', choose_split):
                window.split_selected()
            assert window.table.rowCount() == 2
            assert ''.join(row[2] for row in window.raw_cells()) == 'Seijou is ready'
            window.table.selectAll()
            window.merge_selected()
            assert window.table.rowCount() == 1
            window.undo_stack.undo()
            assert window.table.rowCount() == 2
            window.set_rows([(100, 200, 'Too quick to read')], clean=True)
            assert window.warning_rows == [0]
            exported = str(Path(media_temp) / 'tools.srt')
            with patch.object(QFileDialog, 'getSaveFileName', return_value=(exported, '')):
                assert window.export_srt()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(exported)])
            enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            app.sendEvent(window, enter)
            assert enter.isAccepted()
            drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            app.sendEvent(window, drop)
            assert drop.isAccepted() and window.raw_cells()[0][2] == 'Too quick to read'
            result.update(find_replace=True, show_profiles=True, timing_shift=True, split_merge=True, readability=True, file_drop=True)
            # Reopen a real autosaved project in a fresh window after releasing its
            # lock. The chosen English track and subtitle export baseline survive.
            assert window.autosave_project()
            project = str(window.project_path)
            expected = window.raw_cells()
            window.close()
            window = MainWindow(recovery_directory=recovery_temp.name, offer_recovery=False, profiles_directory=Path(recovery_temp.name) / 'profiles')
            window.show()
            assert window.open_project(project)
            wait_until(lambda: window.track_probe is None and len(window.player.audioTracks()) == 2)
            assert window.raw_cells() == expected
            assert window.audio_tracks.currentData() == 1
            assert window.name_hints.text() == 'Seijou'
            assert not window.dirty
            wait_until(lambda: window.wave_worker is None and bool(window.waveform.peaks))
            assert max(window.waveform.peaks) > .2
            window.table.selectRow(0)
            window.waveform_boundary(0, 100, 400)
            assert window.raw_cells()[0][1] == '00:00:00,400'
            window.undo_stack.undo()
            assert window.raw_cells() == expected
            window.navigate_cue(1)
            assert window.table.currentRow() == 0
            from timeline_checks import document_warnings
            warnings = document_warnings([('00:00:00,000', '00:00:01,000', 'Same'), ('00:00:00,500', '00:00:01,500', 'same'), ('00:00:05,000', '00:00:06,000', 'Later')])
            assert any('Overlaps' in s for s in warnings[0])
            assert any('duplicate' in s for s in warnings[1])
            assert any('Gap' in s for s in warnings[2])
            from batch_queue import BatchDialog
            from project_store import write_new_srt
            queue = BatchDialog(window)
            queue.add_paths([fixture])
            queue.table.cellWidget(0, 1).setCurrentIndex(queue.table.cellWidget(0, 1).findData(0))
            queue.directory.setText(str(Path(media_temp) / 'batch'))
            queue.start_queue()
            wait_until(lambda: not queue.running)
            assert 'No speech' in queue.table.item(0, 2).text()
            assert window.raw_cells() == expected
            queue.start_queue()
            queue.cancel_queue()
            wait_until(lambda: not queue.running)
            assert 'Cancelled' in queue.table.item(0, 2).text()
            queue.close()
            first = write_new_srt(Path(media_temp) / 'batch', 'episode', [(0, 1000, 'Original')])
            second = write_new_srt(Path(media_temp) / 'batch', 'episode', [(0, 1000, 'New')])
            assert first != second and 'Original' in first.read_text(encoding='utf-8-sig')
            result.update(project_reopen=True, waveform=True, navigation=True, timeline_checks=True, batch_queue=True, export_collision_safe=True)
            window.player.setSource(__import__('PySide6.QtCore', fromlist=['QUrl']).QUrl())
            app.processEvents()
        window.mark_saved()
        window.close()
        recovery_temp.cleanup()
        path = bundled_model(DEFAULT_MODEL)
        if path is None:
            raise RuntimeError('Offline portable is missing its complete bundled model')
        manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['sha256'].items():
            assert hashlib.sha256((path / name).read_bytes()).hexdigest() == expected, name
        model = load_model(DEFAULT_MODEL, lambda *_: None, allow_download=False)
        from speaker_runtime import detect_speaker_turns
        from subtitle_timing import make_cues
        from types import SimpleNamespace as NS
        assert detect_speaker_turns(np.zeros(32000, dtype=np.float32), lambda *_: None) == []
        aligned = [NS(words=[NS(start=.1, end=.5, word=' Ready?'), NS(start=.6, end=1, word=' Yes!')])]
        assert len(make_cues(aligned, [(0, 1.1)], [(0, .55, 0), (.55, 1.1, 1)])) == 2
        assert len(make_cues(aligned, [(0, .5), (.6, 1.1)])) == 2
        from transcription_options import normalize_options, correct_text, recognition_hints
        options = normalize_options({'context': 'Haikyuu', 'names': 'Seijou', 'replacements': 'say joe => Seijou'})
        assert correct_text('Say Joe!', options) == 'Seijou!'
        assert recognition_hints(options)['hotwords'] == 'Seijou'
        # Use a file, not just an array: this also tests bundled PyAV/FFmpeg.
        with tempfile.TemporaryDirectory() as temp:
            silence_path = str(Path(temp) / 'silence.wav')
            with wave.open(silence_path, 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0\0' * 16000)
            segments, _ = model.transcribe(silence_path, language='en', vad_filter=True)
            assert list(segments) == [], 'Silence generated subtitles'
        # Exercise decoding as well as the VAD no-speech path.
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language='en', vad_filter=False)
        list(segments)
        result.update(ok=True, model=str(path), revision=manifest['revision'], silence=True, audio_selection=True, replay_loop=True, process_transcription=True, cancellation=True, speaker_inference=True, word_timing=True, name_context=True)
        if len(args) > 1:
            completed = worker_check(args[1], 0)[0]
            text = ' '.join(row[2] for row in completed)
            if not text:
                raise RuntimeError('Speech fixture produced no transcription')
            result['speech_text'] = text
            result['speech_cues'] = completed
    except Exception:
        result.update(ok=False, error=traceback.format_exc())
    result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
