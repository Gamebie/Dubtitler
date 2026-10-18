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
        window = MainWindow(recovery_directory=recovery_temp.name, offer_recovery=False)
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
        result.update(ok=True, model=str(path), revision=manifest['revision'], silence=True, audio_selection=True, replay_loop=True, process_transcription=True, cancellation=True)
        if len(args) > 1:
            segments, _ = model.transcribe(args[1], language='en', vad_filter=True)
            text = ' '.join(s.text.strip() for s in segments)
            if not text:
                raise RuntimeError('Speech fixture produced no transcription')
            result['speech_text'] = text
    except Exception:
        result.update(ok=False, error=traceback.format_exc())
    result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
